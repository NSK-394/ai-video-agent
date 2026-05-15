"""
pacing_engine.py
----------------
Converts a Blueprint's edit_rhythm + cut list into a concrete EditPlan:
a fully resolved list of EditSlots that timeline_builder can execute frame-
by-frame without further decisions.

Design principles:
  - Deterministic: same blueprint + same clips -> same edit every time
  - Beat-awareness delegated to beat_sync_editor (called after plan creation)
  - Clips assigned greedily by descending score from clip_ranker
  - Total timeline duration matches blueprint duration (clamped per slot)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional
from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class EditSlot:
    """
    A single clip placement on the timeline.

    All frame values are in the TARGET timeline's frame rate (plan.fps).
    """
    slot_index:            int
    # Blueprint-derived target
    target_duration_secs:  float
    target_duration_frames: int
    # Timeline position (filled by pacing_engine; adjusted by beat_sync_editor)
    timeline_start_frame:  int = 0
    timeline_end_frame:    int = 0
    # Source clip (filled after clip assignment)
    clip_path:             str = ""
    clip_in_frame:         int = 0
    clip_out_frame:        int = 0
    clip_score:            float = 0.0
    # Flags
    beat_aligned:          bool = False
    transition_in:         str = "cut"   # "cut" | "dissolve" | "fade"
    transition_out:        str = "cut"


@dataclass
class EditPlan:
    """Complete edit plan ready for timeline_builder to execute."""
    fps:                    float
    is_vertical:            bool
    edit_style:             str
    dominant_bpm:           float
    total_duration_secs:    float
    total_duration_frames:  int
    slots:                  List[EditSlot] = field(default_factory=list)

    @property
    def total_slots(self) -> int:
        return len(self.slots)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_edit_plan(blueprint: dict, clip_assignments: list) -> EditPlan:
    """
    Combine blueprint timing with ranked clip assignments into an EditPlan.

    Args:
        blueprint:        Parsed blueprint.json dict.
        clip_assignments: Output of clip_ranker.rank_clips_for_slots() —
                          one entry per blueprint cut slot, each containing
                          {slot_index, clip_path, start_time, end_time,
                           duration, score, start_frame, end_frame}.

    Returns:
        EditPlan ready for beat_sync_editor and timeline_builder.
    """
    source = blueprint.get("source_video", {})
    rhythm = blueprint.get("edit_rhythm", {})
    cuts   = blueprint.get("cuts", [])

    fps         = float(source.get("fps", 30.0))
    is_vertical = bool(source.get("is_vertical", False))
    edit_style  = rhythm.get("style", "mixed")
    bpm         = float(rhythm.get("dominant_bpm", 0.0))
    total_secs  = float(source.get("duration_seconds", 0.0))

    logger.info(
        "Building edit plan | {} cuts | style={} | fps={} | vertical={}",
        len(cuts), edit_style, fps, is_vertical,
    )

    # Map slot_index -> assignment for O(1) lookup
    assign_map = {a["slot_index"]: a for a in clip_assignments}

    slots: List[EditSlot] = []
    cursor_frame = 0  # current write head on the output timeline

    for cut in cuts:
        idx = cut["index"]
        target_secs   = float(cut["duration"])
        target_frames = _secs_to_frames(target_secs, fps)

        assignment = assign_map.get(idx)
        if assignment is None:
            logger.warning("No clip assignment for slot {} — skipping", idx)
            continue

        clip_path    = assignment.get("clip_path", "")
        clip_in_frm  = int(assignment.get("start_frame", 0))
        clip_out_frm = int(assignment.get("end_frame", target_frames))

        # Clamp clip range to available duration
        clip_avail_frames = clip_out_frm - clip_in_frm
        if clip_avail_frames <= 0:
            logger.warning("Slot {}: zero-length clip window — skipping", idx)
            continue
        if clip_avail_frames < target_frames:
            logger.debug(
                "Slot {}: clip shorter than target ({} < {} frames) — using full clip",
                idx, clip_avail_frames, target_frames,
            )
            target_frames = clip_avail_frames
            target_secs   = target_frames / fps

        slot = EditSlot(
            slot_index=idx,
            target_duration_secs=round(target_secs, 4),
            target_duration_frames=target_frames,
            timeline_start_frame=cursor_frame,
            timeline_end_frame=cursor_frame + target_frames,
            clip_path=clip_path,
            clip_in_frame=clip_in_frm,
            clip_out_frame=clip_in_frm + target_frames,
            clip_score=float(assignment.get("score", 0.0)),
        )
        slots.append(slot)
        cursor_frame += target_frames

    total_frames = cursor_frame
    plan = EditPlan(
        fps=fps,
        is_vertical=is_vertical,
        edit_style=edit_style,
        dominant_bpm=bpm,
        total_duration_secs=round(total_frames / fps, 3),
        total_duration_frames=total_frames,
        slots=slots,
    )

    logger.info(
        "Edit plan ready: {} slots | {:.2f}s | {} frames",
        plan.total_slots, plan.total_duration_secs, plan.total_duration_frames,
    )
    return plan


def describe_plan(plan: EditPlan) -> str:
    """Return a compact human-readable summary of the edit plan."""
    lines = [
        f"EditPlan | {plan.total_slots} slots | "
        f"{plan.total_duration_secs:.1f}s | {plan.fps}fps | "
        f"style={plan.edit_style}",
    ]
    for s in plan.slots:
        lines.append(
            f"  [{s.slot_index:>3}] {s.clip_path[-40:]} "
            f"in={s.clip_in_frame} out={s.clip_out_frame} "
            f"-> tl[{s.timeline_start_frame}:{s.timeline_end_frame}] "
            f"score={s.clip_score:.2f}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _secs_to_frames(seconds: float, fps: float) -> int:
    return max(1, int(math.ceil(seconds * fps)))
