"""
beat_sync_editor.py
-------------------
Snaps EditPlan slot boundaries to musical beat frames.

Public API (backwards-compatible):
  snap_to_beats()         - snap boundaries; now delegates to advanced logic
  annotate_beat_markers() - list beat frames within edit duration

New API (this revision):
  categorize_beats()        - label beats as major / minor / drop
  snap_to_beats_advanced()  - prefer major/drop beats; aggressiveness threshold
  build_pacing_curve()      - per-slot energy targets for pacing guidance
"""

from __future__ import annotations

import bisect
import copy
import statistics
from typing import Optional

from editor.pacing_engine import EditPlan, EditSlot
from config.constants import BEAT_ALIGNMENT_TOLERANCE
from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Original public API
# ---------------------------------------------------------------------------

def snap_to_beats(
    plan: EditPlan,
    beat_data: dict,
    tolerance_secs: float = BEAT_ALIGNMENT_TOLERANCE,
) -> EditPlan:
    """Snap slot boundaries to beats. Delegates to advanced logic internally."""
    if not beat_data.get("beats"):
        logger.info("No beat data available — skipping beat-sync pass")
        return plan
    try:
        return snap_to_beats_advanced(plan, beat_data, tolerance_secs=tolerance_secs,
                                      aggressiveness=0.8, prefer_major_beats=True)
    except Exception as exc:
        logger.warning("snap_to_beats_advanced failed ({}); using legacy snap", exc)
        return _run_snap(plan, beat_data, tolerance_secs,
                         sorted(int(round(b["time"] * plan.fps))
                                for b in beat_data.get("beats", [])))


def annotate_beat_markers(plan: EditPlan, beat_data: dict) -> list:
    """Return beat frame indices that fall within the edit plan's total duration."""
    fps, total = plan.fps, plan.total_duration_frames
    markers = [
        int(round(b["time"] * fps))
        for b in beat_data.get("beats", [])
        if int(round(b["time"] * fps)) < total
    ]
    logger.debug("Beat markers within edit: {}", len(markers))
    return markers


# ---------------------------------------------------------------------------
# New: beat categorisation
# ---------------------------------------------------------------------------

def categorize_beats(beat_data: dict, fps: float = 30.0) -> dict:
    """
    Label each beat as major, minor, or drop and return frame indices.

    Major beats : every 4th beat (4/4-time downbeats).
    Drop  beats : beats where the current IBI is >20% shorter than the rolling
                  4-beat average IBI (sudden tempo spike signals a drop/fill).
    Minor beats : everything else.
    """
    beats = beat_data.get("beats", [])
    if not beats:
        return {"major": [], "minor": [], "drop": [], "all": []}

    times  = [float(b["time"]) for b in beats]
    frames = [int(round(t * fps)) for t in times]
    ibis   = [times[i] - times[i - 1] for i in range(1, len(times))]

    major, minor, drop = [], [], []
    for i, frame in enumerate(frames):
        is_drop = False
        if i >= 1:
            cur_ibi     = ibis[i - 1]
            window_ibis = ibis[max(0, i - 4): i - 1]
            if window_ibis:
                avg_ibi = statistics.mean(window_ibis)
                # Shorter IBI = faster tempo -> drop/fill moment
                is_drop = avg_ibi > 0 and cur_ibi < avg_ibi * 0.80

        if is_drop:
            drop.append(frame)
        elif i % 4 == 0:
            major.append(frame)
        else:
            minor.append(frame)

    logger.debug("Beat categories: {} major {} minor {} drop",
                 len(major), len(minor), len(drop))
    return {"major": major, "minor": minor, "drop": drop, "all": frames}


# ---------------------------------------------------------------------------
# New: advanced snapping
# ---------------------------------------------------------------------------

def snap_to_beats_advanced(
    plan: EditPlan,
    beat_data: dict,
    tolerance_secs: float = 0.08,
    aggressiveness: float = 0.8,    # 0=never snap, 1=snap whenever in window
    prefer_major_beats: bool = True,
) -> EditPlan:
    """
    Beat-snap with major/drop beat preference and aggressiveness gating.

    A boundary is moved only when its proximity ratio
    (1 - distance/tolerance_frames) >= aggressiveness.
    """
    beats = beat_data.get("beats", [])
    if not beats:
        logger.info("No beat data — skipping advanced beat-sync pass")
        return plan

    tol_frames = max(1, int(round(tolerance_secs * plan.fps)))

    categories     = categorize_beats(beat_data, fps=plan.fps) if prefer_major_beats else None
    preferred_frames = sorted(set(
        (categories["major"] if categories else []) +
        (categories["drop"]  if categories else [])
    ))
    all_frames = sorted(int(round(b["time"] * plan.fps)) for b in beats)

    logger.info("Advanced beat-sync | {} beats | {} preferred | tol=±{} | aggr={}",
                len(all_frames), len(preferred_frames), tol_frames, aggressiveness)

    adjusted = copy.deepcopy(plan)
    slots    = adjusted.slots
    n_aligned = 0

    for i, slot in enumerate(slots):
        orig = slot.timeline_end_frame

        # Prefer major/drop; fall back to all beats
        snapped = (_nearest_beat(orig, preferred_frames, tol_frames)
                   if prefer_major_beats and preferred_frames else None)
        if snapped is None:
            snapped = _nearest_beat(orig, all_frames, tol_frames)
        if snapped is None:
            continue

        # Aggressiveness gate: only snap if beat is "close enough"
        proximity = 1.0 - abs(snapped - orig) / tol_frames
        if proximity < aggressiveness:
            continue

        delta = snapped - orig
        slot.timeline_end_frame = snapped
        slot.clip_out_frame = max(
            slot.clip_in_frame + 1,
            slot.clip_in_frame + (snapped - slot.timeline_start_frame),
        )
        slot.beat_aligned = True
        n_aligned += 1

        for j in range(i + 1, len(slots)):
            slots[j].timeline_start_frame += delta
            slots[j].timeline_end_frame   += delta

    if slots:
        adjusted.total_duration_frames = slots[-1].timeline_end_frame
        adjusted.total_duration_secs   = round(adjusted.total_duration_frames / plan.fps, 3)

    ratio = n_aligned / len(slots) if slots else 0.0
    logger.info("Advanced beat-sync: {}/{} slots aligned ({:.0%})", n_aligned, len(slots), ratio)
    return adjusted


# ---------------------------------------------------------------------------
# New: pacing curve
# ---------------------------------------------------------------------------

def build_pacing_curve(
    total_slots: int,
    style: str = "mixed",
    beat_categories: dict = None,
) -> list:
    """
    Return per-slot float energy targets in [0, 1] of length total_slots.

    Styles: "fast_cut" | "slow_burn" | "beat_synced" | "mixed" | default ramp.
    """
    if total_slots <= 0:
        return []

    if style == "fast_cut":
        return [0.8] * total_slots

    if style == "slow_burn":
        return [round(0.3 + 0.6 * i / max(1, total_slots - 1), 3) for i in range(total_slots)]

    if style == "beat_synced":
        curve = [0.4] * total_slots
        if beat_categories and beat_categories.get("drop") and beat_categories.get("all"):
            last_frame = beat_categories["all"][-1] or 1
            for df in beat_categories["drop"]:
                idx = min(int(df / last_frame * total_slots), total_slots - 1)
                curve[idx] = 0.95
        return curve

    if style == "mixed":
        wave = [0.9, 0.5, 0.8, 0.4]
        return [round(wave[i % 4], 3) for i in range(total_slots)]

    # Default: gentle ramp 0.4 -> 0.85
    return [round(0.4 + 0.45 * i / max(1, total_slots - 1), 3) for i in range(total_slots)]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _nearest_beat(frame: int, sorted_frames: list, tol: int) -> Optional[int]:
    """Return the beat frame nearest to `frame` within ±tol, or None."""
    if not sorted_frames:
        return None
    idx = bisect.bisect_left(sorted_frames, frame)
    candidates = [sorted_frames[c] for c in (idx, idx - 1)
                  if 0 <= c < len(sorted_frames)]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda b: abs(b - frame))
    return nearest if abs(nearest - frame) <= tol else None


def _run_snap(plan: EditPlan, beat_data: dict,
              tolerance_secs: float, beat_frames: list) -> EditPlan:
    """Minimal boundary-walk snap used as emergency fallback."""
    tol = max(1, int(round(tolerance_secs * plan.fps)))
    adjusted = copy.deepcopy(plan)
    aligned  = 0
    for i, slot in enumerate(adjusted.slots):
        snapped = _nearest_beat(slot.timeline_end_frame, beat_frames, tol)
        if snapped is None:
            continue
        delta = snapped - slot.timeline_end_frame
        slot.timeline_end_frame = snapped
        slot.clip_out_frame = max(slot.clip_in_frame + 1,
                                  slot.clip_in_frame + snapped - slot.timeline_start_frame)
        slot.beat_aligned = True
        aligned += 1
        for j in range(i + 1, len(adjusted.slots)):
            adjusted.slots[j].timeline_start_frame += delta
            adjusted.slots[j].timeline_end_frame   += delta
    if adjusted.slots:
        adjusted.total_duration_frames = adjusted.slots[-1].timeline_end_frame
        adjusted.total_duration_secs   = round(adjusted.total_duration_frames / plan.fps, 3)
    logger.info("Fallback snap: {}/{} aligned", aligned, len(adjusted.slots))
    return adjusted
