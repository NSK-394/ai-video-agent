"""
edit_quality_analyzer.py
------------------------
Scores a completed EditPlan against the original blueprint and returns a
structured QualityReport covering six quality dimensions.

Dimensions
----------
diversity_score     – How many unique clips are used relative to total slots.
beat_alignment      – % of slot start-frames that land within 3 frames of a beat.
pacing_consistency  – Inverse coefficient of variation of slot durations.
semantic_score      – Mean semantic affinity from SemanticProfile data (if given).
hook_strength       – Energy of the first two clips (critical for viewer retention).
repetition_penalty  – Penalises consecutive repeated clip paths.
overall_score       – Weighted average of all six dimensions.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Dimension weights (must sum to 1.0)
# ---------------------------------------------------------------------------
_WEIGHTS = {
    "diversity":    0.25,
    "beat":         0.25,
    "pacing":       0.15,
    "semantic":     0.15,
    "hook":         0.10,
    "repetition":   0.10,
}

# Beat alignment tolerance: a slot is "aligned" if its start is ≤ this many
# frames away from the nearest beat frame.
_BEAT_TOLERANCE_FRAMES = 3


# ---------------------------------------------------------------------------
# QualityReport dataclass
# ---------------------------------------------------------------------------

@dataclass
class QualityReport:
    diversity_score:    float        # 0-100
    beat_alignment:     float        # 0-100
    pacing_consistency: float        # 0-100
    semantic_score:     float        # 0-100
    hook_strength:      float        # 0-100
    repetition_penalty: float        # 0-100  (100 = zero repetition)
    overall_score:      float        # weighted average 0-100
    details:            dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "diversity_score":    round(self.diversity_score, 2),
            "beat_alignment":     round(self.beat_alignment, 2),
            "pacing_consistency": round(self.pacing_consistency, 2),
            "semantic_score":     round(self.semantic_score, 2),
            "hook_strength":      round(self.hook_strength, 2),
            "repetition_penalty": round(self.repetition_penalty, 2),
            "overall_score":      round(self.overall_score, 2),
            "details":            self.details,
        }

    def write_json(self, path: str) -> None:
        """Persist the report to a JSON file."""
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        logger.info("Quality report written to {}", path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_edit_quality(
    plan,                          # EditPlan from pacing_engine
    blueprint: dict,
    clip_assignments: list,
    semantic_profiles: dict = None,  # {clip_path: list[SemanticProfile]}  optional
) -> QualityReport:
    """
    Score the edit plan and return a QualityReport.

    Parameters
    ----------
    plan              : EditPlan returned by pacing_engine / beat_sync_editor.
    blueprint         : Parsed blueprint.json dict (used for beat frames).
    clip_assignments  : Segment dicts from clip_ranker (may carry extra metadata).
    semantic_profiles : Optional mapping from clip_path -> list of SemanticProfile
                        objects. Each profile is expected to have .affinity and
                        .energy_score attributes (or dict-compatible keys).
    """
    slots = plan.slots
    total_slots = len(slots)

    if total_slots == 0:
        logger.warning("analyze_edit_quality called on empty plan")
        zero = QualityReport(0, 0, 0, 50, 50, 100, 0)
        return zero

    # ------------------------------------------------------------------ #
    # 1. Diversity score                                                   #
    # ------------------------------------------------------------------ #
    clip_paths = [s.clip_path for s in slots]
    unique_clips = len(set(clip_paths))

    # Count consecutive duplicate runs (same clip in adjacent slots)
    consecutive_same = sum(
        1 for i in range(1, len(clip_paths))
        if clip_paths[i] and clip_paths[i] == clip_paths[i - 1]
    )

    # Base: ratio of unique clips used; penalise consecutive repeats
    diversity_raw = (unique_clips / total_slots) * 100 - (consecutive_same * 20)
    diversity_score = _clamp(diversity_raw)

    # ------------------------------------------------------------------ #
    # 2. Beat alignment                                                    #
    # ------------------------------------------------------------------ #
    beat_frames = _extract_beat_frames(blueprint, plan.fps)
    if beat_frames:
        aligned = sum(
            1 for s in slots
            if _within_tolerance(s.timeline_start_frame, beat_frames, _BEAT_TOLERANCE_FRAMES)
        )
        beat_alignment = (aligned / total_slots) * 100
    else:
        # No beat data available — neutral score
        beat_alignment = 50.0
        logger.debug("No beat frames found; beat_alignment set to 50.0")

    # ------------------------------------------------------------------ #
    # 3. Pacing consistency                                                #
    # ------------------------------------------------------------------ #
    durations = [s.timeline_end_frame - s.timeline_start_frame for s in slots]
    # Filter out zero-length slots (shouldn't happen, but guard anyway)
    durations = [d for d in durations if d > 0]

    if len(durations) >= 2:
        mean_dur = statistics.mean(durations)
        stdev_dur = statistics.stdev(durations)
        # Coefficient of variation; higher = less consistent
        cv = (stdev_dur / mean_dur) if mean_dur > 0 else 0.0
        pacing_consistency = _clamp(100 - cv * 100)
    else:
        pacing_consistency = 100.0  # single slot is trivially consistent

    # ------------------------------------------------------------------ #
    # 4. Semantic score                                                    #
    # ------------------------------------------------------------------ #
    if semantic_profiles:
        affinities = []
        for slot in slots:
            profiles = semantic_profiles.get(slot.clip_path, [])
            for prof in profiles:
                # Support both attribute-access and dict-style profiles
                val = _get_attr_or_key(prof, "affinity")
                if val is not None:
                    affinities.append(float(val))
        semantic_score = (statistics.mean(affinities) * 100) if affinities else 50.0
    else:
        semantic_score = 50.0

    # ------------------------------------------------------------------ #
    # 5. Hook strength (first 2 clips)                                    #
    # ------------------------------------------------------------------ #
    if semantic_profiles:
        energy_vals = []
        for slot in slots[:2]:           # only first two slots matter for hook
            profiles = semantic_profiles.get(slot.clip_path, [])
            for prof in profiles:
                val = _get_attr_or_key(prof, "energy_score")
                if val is not None:
                    energy_vals.append(float(val))
        hook_strength = (statistics.mean(energy_vals) * 100) if energy_vals else 50.0
    else:
        hook_strength = 50.0

    # ------------------------------------------------------------------ #
    # 6. Repetition penalty                                               #
    # ------------------------------------------------------------------ #
    # Count how many slots share a clip_path that appeared in a prior slot
    seen: set = set()
    repeated = 0
    for path in clip_paths:
        if path and path in seen:
            repeated += 1
        elif path:
            seen.add(path)
    repetition_penalty = _clamp(100 - (repeated / total_slots) * 100)

    # ------------------------------------------------------------------ #
    # Weighted overall score                                               #
    # ------------------------------------------------------------------ #
    overall_score = (
        diversity_score    * _WEIGHTS["diversity"]  +
        beat_alignment     * _WEIGHTS["beat"]       +
        pacing_consistency * _WEIGHTS["pacing"]     +
        semantic_score     * _WEIGHTS["semantic"]   +
        hook_strength      * _WEIGHTS["hook"]       +
        repetition_penalty * _WEIGHTS["repetition"]
    )

    details = {
        "total_slots":       total_slots,
        "unique_clips":      unique_clips,
        "consecutive_same":  consecutive_same,
        "repeated_segments": repeated,
        "beat_frames_count": len(beat_frames),
        "weights":           _WEIGHTS,
    }

    report = QualityReport(
        diversity_score    = round(diversity_score,    2),
        beat_alignment     = round(beat_alignment,     2),
        pacing_consistency = round(pacing_consistency, 2),
        semantic_score     = round(semantic_score,     2),
        hook_strength      = round(hook_strength,      2),
        repetition_penalty = round(repetition_penalty, 2),
        overall_score      = round(overall_score,      2),
        details            = details,
    )

    logger.info(
        "Quality report | overall={} | diversity={} beat={} pacing={} semantic={} hook={} rep={}",
        report.overall_score,
        report.diversity_score,
        report.beat_alignment,
        report.pacing_consistency,
        report.semantic_score,
        report.hook_strength,
        report.repetition_penalty,
    )
    return report


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp a float to [lo, hi]."""
    return max(lo, min(hi, value))


def _extract_beat_frames(blueprint: dict, fps: float) -> list[int]:
    """Convert blueprint beat timestamps to integer frame indices."""
    beats = blueprint.get("beat_data", {}).get("beats", [])
    if not beats:
        # Some blueprints store beats at top level
        beats = blueprint.get("beats", [])
    return sorted(int(round(b["time"] * fps)) for b in beats if "time" in b)


def _within_tolerance(frame: int, sorted_frames: list[int], tol: int) -> bool:
    """Return True if `frame` is within ±tol of any frame in sorted_frames."""
    import bisect
    idx = bisect.bisect_left(sorted_frames, frame)
    for candidate_idx in (idx, idx - 1):
        if 0 <= candidate_idx < len(sorted_frames):
            if abs(sorted_frames[candidate_idx] - frame) <= tol:
                return True
    return False


def _get_attr_or_key(obj, name: str):
    """Retrieve a value from an object supporting either attribute or dict access."""
    if hasattr(obj, name):
        return getattr(obj, name)
    if isinstance(obj, dict):
        return obj.get(name)
    return None
