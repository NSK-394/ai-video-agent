"""
Edit-style classifier.

Derives a human-readable editing style label and quantitative metrics
from the outputs of the cut, beat, and caption detectors.

Style labels (mutually exclusive, priority-ordered):
    "beat_synced"      — most cuts land on a musical beat
    "fast_cut"         — average scene is very short (< 2 s)
    "slow_burn"        — average scene is long (> 6 s)
    "dialogue_driven"  — majority of video has speech
    "mixed"            — doesn't fit a dominant category
"""

import statistics
from config.constants import (
    FAST_CUT_MAX_SECONDS,
    SLOW_BURN_MIN_SECONDS,
    BEAT_SYNC_MIN_RATIO,
    DIALOGUE_MIN_COVERAGE,
    BEAT_ALIGNMENT_TOLERANCE,
)
from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_style(
    cuts: list,
    beat_data: dict,
    caption_data: dict,
    video_duration: float,
) -> dict:
    """
    Compute edit-rhythm statistics and classify the editing style.

    Args:
        cuts:           Output of cuts.detect_cuts().
        beat_data:      Output of beats.extract_beats().
        caption_data:   Output of captions_extract.generate_captions().
        video_duration: Total video length in seconds.

    Returns:
        {
            "average_cut_duration":  float,
            "median_cut_duration":   float,
            "total_cuts":            int,
            "cuts_per_minute":       float,
            "dominant_bpm":          float,
            "beat_aligned_cuts":     int,
            "beat_alignment_ratio":  float,
            "speech_coverage":       float,
            "style":                 str,
        }
    """
    logger.info("Analysing editing style …")

    durations = [c["duration"] for c in cuts]
    total_cuts = len(cuts)

    avg_dur = statistics.mean(durations) if durations else 0.0
    med_dur = statistics.median(durations) if durations else 0.0
    cuts_per_min = (total_cuts / video_duration * 60.0) if video_duration > 0 else 0.0

    beat_times = [b["time"] for b in beat_data.get("beats", [])]
    aligned, ratio = _beat_alignment(cuts, beat_times)

    from analysis.captions_extract import speech_coverage
    coverage = speech_coverage(caption_data, video_duration)

    style = _classify_style(avg_dur, ratio, coverage)

    result = {
        "average_cut_duration":  round(avg_dur, 3),
        "median_cut_duration":   round(med_dur, 3),
        "total_cuts":            total_cuts,
        "cuts_per_minute":       round(cuts_per_min, 2),
        "dominant_bpm":          beat_data.get("bpm", 0.0),
        "beat_aligned_cuts":     aligned,
        "beat_alignment_ratio":  round(ratio, 3),
        "speech_coverage":       round(coverage, 3),
        "style":                 style,
    }

    logger.info(
        "Style: {} | avg cut {:.2f}s | {:.1f} cuts/min | "
        "beat align {:.0%} | speech {:.0%}",
        style, avg_dur, cuts_per_min, ratio, coverage,
    )
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _beat_alignment(cuts: list, beat_times: list, tolerance: float = BEAT_ALIGNMENT_TOLERANCE):
    """
    Count how many cut start-times fall within `tolerance` seconds of any beat.
    Returns (aligned_count, ratio).
    """
    if not beat_times or not cuts:
        return 0, 0.0

    import bisect
    sorted_beats = sorted(beat_times)
    aligned = 0

    for cut in cuts:
        t = cut["start_time"]
        # Binary-search nearest beat
        idx = bisect.bisect_left(sorted_beats, t)
        candidates = []
        if idx < len(sorted_beats):
            candidates.append(sorted_beats[idx])
        if idx > 0:
            candidates.append(sorted_beats[idx - 1])
        nearest_diff = min(abs(t - b) for b in candidates) if candidates else float("inf")
        if nearest_diff <= tolerance:
            aligned += 1

    ratio = aligned / len(cuts) if cuts else 0.0
    return aligned, ratio


def _classify_style(avg_cut_dur: float, beat_ratio: float, speech_coverage: float) -> str:
    if beat_ratio >= BEAT_SYNC_MIN_RATIO:
        return "beat_synced"
    if avg_cut_dur <= FAST_CUT_MAX_SECONDS:
        return "fast_cut"
    if avg_cut_dur >= SLOW_BURN_MIN_SECONDS:
        return "slow_burn"
    if speech_coverage >= DIALOGUE_MIN_COVERAGE:
        return "dialogue_driven"
    return "mixed"
