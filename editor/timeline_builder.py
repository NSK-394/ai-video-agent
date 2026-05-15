"""
timeline_builder.py
-------------------
Builds the complete edited timeline inside DaVinci Resolve from an EditPlan.

Responsibilities:
  1. Create the timeline with correct resolution and frame rate
  2. Ensure all required clips are imported into the Media Pool
  3. Append each EditSlot as a clip with correct in/out points
  4. Return the Timeline object and the list of placed TimelineItems

The module operates as a pure builder — it does not make timing decisions
(those come from pacing_engine + beat_sync_editor).
"""

import os
from editor.resolve_api import ResolveController
from editor.pacing_engine import EditPlan, EditSlot
from editor.media_importer import import_media, build_clip_index
from editor.timeline import (
    create_timeline,
    append_clips,
    get_video_items,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# Name used for the auto-generated bin that holds user clips
_CLIP_BIN = "AI_User_Clips"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_timeline(
    resolve_ctrl: ResolveController,
    plan: EditPlan,
    timeline_name: str = "AI_Edit_v1",
    clip_dir: str = None,
    pre_imported_items: list = None,
    video_only: bool = False,
) -> tuple:
    """
    Create the Resolve timeline and populate it from the EditPlan.

    Provide EITHER:
      - clip_dir            -> clips are imported from this folder automatically
      - pre_imported_items  -> list of MediaPoolItems already in the Media Pool

    Args:
        resolve_ctrl:       Connected ResolveController.
        plan:               Resolved EditPlan (from pacing_engine / beat_sync_editor).
        timeline_name:      Name for the new Resolve timeline.
        clip_dir:           Folder containing raw footage (used if pre_imported_items=None).
        pre_imported_items: Already-imported MediaPoolItem list (optional).
        video_only:         If True, sets mediaType=1 on every clip dict so Resolve
                            strips embedded clip audio — use when a separate reference
                            audio track is placed on the timeline instead.

    Returns:
        (Timeline, List[TimelineItem])  — the created timeline and placed items.
    """
    resolve_ctrl.require_connection()

    # ------------------------------------------------------------------
    # Step A: Collect all unique clip paths from the plan
    # ------------------------------------------------------------------
    unique_paths = list({s.clip_path for s in plan.slots if s.clip_path})
    logger.info("Timeline builder: {} unique source clip(s)", len(unique_paths))

    # ------------------------------------------------------------------
    # Step B: Ensure clips are in the Media Pool
    # ------------------------------------------------------------------
    if pre_imported_items is not None:
        pool_items = pre_imported_items
        logger.info("Using {} pre-imported Media Pool item(s)", len(pool_items))
    elif clip_dir:
        logger.info("Importing from clip_dir: {}", clip_dir)
        pool_items = import_media(resolve_ctrl, unique_paths, bin_name=_CLIP_BIN)
    else:
        logger.info("Importing clip paths from plan")
        pool_items = import_media(resolve_ctrl, unique_paths, bin_name=_CLIP_BIN)

    if not pool_items:
        raise RuntimeError("No clips imported — cannot build timeline")

    # Build filename -> MediaPoolItem lookup
    clip_index = build_clip_index(pool_items)
    # Also build path-based index for direct lookup
    path_index = {os.path.abspath(item_path): item
                  for item_path, item in zip(unique_paths, pool_items)
                  if item}

    # ------------------------------------------------------------------
    # Step C: Create the timeline
    # ------------------------------------------------------------------
    tl = create_timeline(resolve_ctrl, timeline_name)
    resolve_ctrl.set_current_timeline(tl)

    if plan.is_vertical:
        resolve_ctrl.configure_timeline_for_vertical(tl, fps=plan.fps)
    else:
        resolve_ctrl.configure_timeline_for_horizontal(tl, fps=plan.fps)

    # ------------------------------------------------------------------
    # Step D: Build clip-dict list for AppendToTimeline
    # ------------------------------------------------------------------
    clip_dicts = []
    skipped = 0

    for slot in plan.slots:
        mp_item = _resolve_pool_item(slot, path_index, clip_index)
        if mp_item is None:
            logger.warning("Slot {}: could not resolve MediaPoolItem for '{}' — skipping",
                           slot.slot_index, slot.clip_path)
            skipped += 1
            continue

        # Clamp frames to valid range
        total_clip_frames = _get_clip_frames(mp_item)
        in_frame  = max(0, slot.clip_in_frame)
        out_frame = min(slot.clip_out_frame, total_clip_frames - 1) if total_clip_frames > 0 else slot.clip_out_frame

        if out_frame <= in_frame:
            logger.warning("Slot {}: invalid frame range [{}, {}] — skipping",
                           slot.slot_index, in_frame, out_frame)
            skipped += 1
            continue

        cd = {
            "mediaPoolItem": mp_item,
            "startFrame":    in_frame,
            "endFrame":      out_frame,
        }
        if video_only:
            cd["mediaType"] = 1  # strip embedded audio from clip
        clip_dicts.append(cd)
        logger.debug(
            "Slot {:>3}: '{}' frames [{:>6}–{:>6}]",
            slot.slot_index, os.path.basename(slot.clip_path), in_frame, out_frame,
        )

    if not clip_dicts:
        raise RuntimeError("All slots were skipped — timeline would be empty")

    # ------------------------------------------------------------------
    # Step E: Append to timeline in one batch call
    # ------------------------------------------------------------------
    logger.info("Appending {} clip(s) to '{}' …", len(clip_dicts), timeline_name)
    placed_items = append_clips(resolve_ctrl, clip_dicts)

    logger.info(
        "Timeline '{}' built: {} placed | {} skipped",
        timeline_name, len(placed_items), skipped,
    )
    return tl, placed_items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_pool_item(slot: EditSlot, path_index: dict, clip_index: dict):
    """Try path lookup first, then filename stem lookup."""
    abs_path = os.path.abspath(slot.clip_path)
    if abs_path in path_index:
        return path_index[abs_path]

    stem = os.path.splitext(os.path.basename(slot.clip_path))[0]
    if stem in clip_index:
        return clip_index[stem]

    return None


def _get_clip_frames(mp_item) -> int:
    """Safely read total frame count from a MediaPoolItem."""
    try:
        props = mp_item.GetClipProperty()
        return int(str(props.get("Frames", "0")).split(".")[0])
    except Exception:
        return 0
