"""
semantic_score_engine.py
------------------------
Maps blueprint edit style + beat energy + timeline position to desired
semantic labels, then scores how well a clip segment matches those labels.

Three public helpers cover the typical scoring pipeline:
1. ``get_pacing_zone``    – map position_ratio → zone name
2. ``get_desired_tags``   – combine style + zone → ordered tag list
3. ``score_semantic_match`` – compare segment profile to desired tags → 0..1
"""

from __future__ import annotations

from typing import Dict, List

from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Style → desired semantic tags
# ---------------------------------------------------------------------------

STYLE_DESIRED: Dict[str, List[str]] = {
    "beat_synced":     ["action", "intense", "fast_motion", "close_up"],
    "fast_cut":        ["fast_motion", "action", "intense"],
    "slow_burn":       ["cinematic", "calm", "wide_shot", "emotional"],
    "dialogue_driven": ["close_up", "medium_shot", "calm"],
    "mixed":           ["action", "cinematic", "medium_shot"],
}

# ---------------------------------------------------------------------------
# Pacing zones
# ---------------------------------------------------------------------------

# Timeline position ranges: (start_ratio_inclusive, end_ratio_exclusive)
_PACING_ZONE_BOUNDS = [
    ("hook",  0.00, 0.15),
    ("build", 0.15, 0.50),
    ("drop",  0.50, 0.70),
    ("outro", 0.70, 1.01),  # 1.01 so ratio==1.0 is caught by "outro"
]

PACING_ZONES: Dict[str, dict] = {
    "hook": {
        "energy_min": 0.7,
        "preferred_tags": ["intense", "fast_motion", "action"],
    },
    "build": {
        "energy_min": 0.4,
        "preferred_tags": ["action", "medium_shot"],
    },
    "drop": {
        "energy_min": 0.8,
        "preferred_tags": ["intense", "action", "close_up"],
    },
    "outro": {
        "energy_min": 0.3,
        "preferred_tags": ["cinematic", "wide_shot", "calm"],
    },
}

# ---------------------------------------------------------------------------
# Tag weights – used when computing the semantic match score
# ---------------------------------------------------------------------------

_TAG_WEIGHTS: Dict[str, float] = {
    "intense":     2.0,
    "action":      2.0,
    "fast_motion": 1.5,
    "cinematic":   1.5,
    "close_up":    1.2,
    "wide_shot":   1.2,
    "calm":        1.0,
    "medium_shot": 1.0,
    "slow_motion": 1.0,
    "emotional":   1.0,
    "static":      0.8,
}
_DEFAULT_TAG_WEIGHT = 1.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_pacing_zone(position_ratio: float) -> str:
    """
    Return the pacing-zone name for a normalised timeline position.

    Parameters
    ----------
    position_ratio : float in [0.0, 1.0]  (0 = start, 1 = end of edit).

    Returns
    -------
    str
        One of ``"hook"``, ``"build"``, ``"drop"``, ``"outro"``.
    """
    for zone, start, end in _PACING_ZONE_BOUNDS:
        if start <= position_ratio < end:
            return zone
    # Fallback for edge cases (e.g., position_ratio slightly > 1.0)
    return "outro"


def get_desired_tags(
    slot_idx: int,
    total_slots: int,
    edit_style: str,
    beat_energy: float = 0.5,
) -> List[str]:
    """
    Build an ordered list of desired semantic tags for a given slot.

    Strategy
    --------
    1. Determine the pacing zone from ``slot_idx / total_slots``.
    2. Start with the style-specific base tags (from ``STYLE_DESIRED``).
    3. At high beat_energy (≥ 0.6), prepend the pacing zone's preferred tags
       so they rank higher in the matching step.
    4. At low beat_energy (< 0.4), append calmer / cinematic zone tags.

    Parameters
    ----------
    slot_idx    : zero-based index of the current slot.
    total_slots : total number of slots in the edit.
    edit_style  : key from ``STYLE_DESIRED`` (falls back to ``"mixed"``).
    beat_energy : normalised beat strength at this slot (0.0 – 1.0).

    Returns
    -------
    list[str]
        Deduplicated tag list (preserving first-seen order).
    """
    position_ratio = slot_idx / max(1, total_slots - 1) if total_slots > 1 else 0.0
    zone = get_pacing_zone(position_ratio)
    zone_info = PACING_ZONES[zone]

    base_tags: List[str] = list(STYLE_DESIRED.get(edit_style, STYLE_DESIRED["mixed"]))
    zone_tags: List[str] = list(zone_info["preferred_tags"])

    # Merge according to beat energy
    if beat_energy >= 0.6:
        # Energetic beat → zone tags take priority
        merged = zone_tags + base_tags
    elif beat_energy < 0.4:
        # Quiet beat → base style first, quieter zone tags appended
        merged = base_tags + ["cinematic", "calm"] + zone_tags
    else:
        # Balanced
        merged = base_tags + zone_tags

    # Deduplicate while preserving order
    seen: set = set()
    result: List[str] = []
    for tag in merged:
        if tag not in seen:
            seen.add(tag)
            result.append(tag)

    logger.info(
        "score_engine: slot={} style={} zone={} beat_energy={:.2f} tags={}",
        slot_idx,
        edit_style,
        zone,
        beat_energy,
        result,
    )
    return result


def score_semantic_match(segment_profile: dict, desired_tags: List[str]) -> float:
    """
    Score how well a segment's semantic tags match a desired tag list.

    Parameters
    ----------
    segment_profile : dict as returned by
                      ``semantic_classifier.classify_segment``.
                      Must contain a ``"tags"`` key (list[str]).
                      May optionally contain ``"mean_energy_score"`` and
                      ``"mean_cinematic_score"`` (both 0-1).
    desired_tags    : ordered list of desired tags (earlier = higher priority).

    Scoring logic
    -------------
    * Each tag in *desired_tags* that also appears in *segment_profile["tags"]*
      contributes its weight (from ``_TAG_WEIGHTS``).
    * The raw score is divided by the theoretical maximum (sum of weights of
      all desired tags) to normalise to [0, 1].
    * If *segment_profile* contains no usable semantic data (empty tags,
      missing key), 0.5 is returned as a neutral, non-penalising default.

    Returns
    -------
    float
        Semantic match score in [0.0, 1.0].
    """
    if not segment_profile:
        return 0.5

    segment_tags: List[str] = segment_profile.get("tags", [])

    # Neutral fallback when no semantic data is available
    if not segment_tags and not desired_tags:
        return 0.5

    if not desired_tags:
        return 0.5

    # Build a set for O(1) lookup
    segment_tag_set = set(segment_tags)

    raw_score = 0.0
    max_score = 0.0

    for tag in desired_tags:
        weight = _TAG_WEIGHTS.get(tag, _DEFAULT_TAG_WEIGHT)
        max_score += weight
        if tag in segment_tag_set:
            raw_score += weight

    if max_score == 0.0:
        return 0.5

    base_score = raw_score / max_score

    # Minor boost from composite scores already available in the profile
    energy_bonus = segment_profile.get("mean_energy_score", 0.5) * 0.05
    cinematic_bonus = segment_profile.get("mean_cinematic_score", 0.5) * 0.05

    # Only add these bonuses when the relevant tags are desired
    final_score = base_score
    if any(t in desired_tags for t in ("intense", "action", "fast_motion")):
        final_score += energy_bonus
    if "cinematic" in desired_tags:
        final_score += cinematic_bonus

    final_score = round(max(0.0, min(1.0, final_score)), 4)

    logger.info(
        "score_engine: match={:.4f} segment_tags={} desired_tags={}",
        final_score,
        segment_tags,
        desired_tags,
    )
    return final_score
