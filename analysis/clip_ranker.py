"""
clip_ranker.py
--------------
Scores raw footage clips and assigns the best moment to each edit slot.

Scoring pipeline (all multiplicative):
  1. Motion score   — mean absolute frame difference (MAD) over the window
  2. Semantic score — how well the clip's visual character matches the slot's need
  3. Diversity penalty — DiversityMemory penalises recent/repeated reuse
  4. Hook multiplier — first N slots get a bias toward high-energy clips

A higher effective_score wins the slot.
"""

import os
import cv2
import numpy as np
from utils.logger import get_logger

logger = get_logger(__name__)

_ANALYSIS_WIDTH  = 160   # px — downscale width for fast MAD computation
_SAMPLE_EVERY    = 4     # analyse every Nth frame


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_clip(clip_path: str, sample_every: int = _SAMPLE_EVERY) -> dict:
    """
    Compute per-second motion scores for a single clip.

    Returns:
        {clip_path, duration, fps, peak_score, mean_score,
         second_scores: [{second, start_time, end_time, score}]}
    """
    if not os.path.isfile(clip_path):
        logger.warning("Clip not found, skipping: {}", clip_path)
        return _empty_result(clip_path)

    cap = cv2.VideoCapture(clip_path)
    if not cap.isOpened():
        logger.warning("Cannot open clip: {}", clip_path)
        return _empty_result(clip_path)

    fps          = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration     = total_frames / fps

    frame_scores = []
    prev_gray    = None
    frame_idx    = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % sample_every == 0:
            small = _downscale(frame)
            gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            if prev_gray is not None:
                mad = float(np.mean(np.abs(gray.astype(np.int16) - prev_gray.astype(np.int16))))
                frame_scores.append((frame_idx, mad))
            prev_gray = gray
        frame_idx += 1

    cap.release()

    second_scores = _aggregate_to_seconds(frame_scores, fps, int(duration))
    all_scores    = [s["score"] for s in second_scores]

    result = {
        "clip_path":     clip_path,
        "duration":      round(duration, 3),
        "fps":           fps,
        "peak_score":    round(max(all_scores, default=0.0), 4),
        "mean_score":    round(float(np.mean(all_scores)) if all_scores else 0.0, 4),
        "second_scores": second_scores,
    }
    logger.debug(
        "Ranked '{}': {:.2f}s | peak={:.2f} | mean={:.2f}",
        os.path.basename(clip_path), duration,
        result["peak_score"], result["mean_score"],
    )
    return result


def find_best_segment(
    clip_analysis: dict,
    target_duration: float,
    min_score: float = 0.0,
    min_start_time: float = 0.0,  # skip seconds before this (avoid already-used region)
) -> dict:
    """
    Locate the highest-scoring contiguous window of `target_duration` seconds.

    Returns segment dict:
        {clip_path, start_time, end_time, duration, score, start_frame, end_frame}
    """
    scores = clip_analysis.get("second_scores", [])
    fps    = clip_analysis.get("fps", 30.0)
    window = max(1, int(round(target_duration)))

    # Filter to seconds at or after min_start_time
    eligible = [s for s in scores if s["start_time"] >= min_start_time - 0.01]

    if len(eligible) < window:
        # Use full clip if shorter than target
        start_t = 0.0
        end_t   = clip_analysis["duration"]
        avg     = clip_analysis.get("mean_score", 0.0)
        return _segment_dict(clip_analysis["clip_path"], start_t, end_t, avg, fps)

    best_score = -1.0
    best_start = 0

    for i in range(len(eligible) - window + 1):
        window_scores = [eligible[j]["score"] for j in range(i, i + window)]
        avg = float(np.mean(window_scores))
        if avg > best_score and avg >= min_score:
            best_score = avg
            best_start = i

    start_t = float(eligible[best_start]["start_time"])
    end_t   = min(start_t + target_duration, clip_analysis["duration"])

    return _segment_dict(clip_analysis["clip_path"], start_t, end_t, best_score, fps)


def rank_clips_for_slots(
    clip_paths: list,
    slot_durations: list,
    allow_reuse: bool = True,
    # --- New intelligence parameters (all optional, backwards-compatible) ---
    diversity_memory=None,      # DiversityMemory instance
    semantic_analyses: dict = None,   # {clip_path: list[SemanticProfile]}
    edit_style: str = "mixed",
    beats: list = None,         # list of beat dicts with "time" key
    pacing_curve: list = None,  # list of float energy targets per slot
    hook_count: int = 2,
) -> list:
    """
    Assign the best-scored clip segment to each edit slot.

    Scoring formula (all multiplied):
        effective = motion_score * semantic_multiplier * diversity_penalty * hook_multiplier

    Args:
        clip_paths:        Absolute paths to raw footage.
        slot_durations:    Target seconds for each slot.
        allow_reuse:       Allow the same clip to fill multiple slots.
        diversity_memory:  DiversityMemory instance for tracking usage.
        semantic_analyses: Pre-computed {clip_path: [SemanticProfile]} (optional).
        edit_style:        Blueprint edit style for semantic matching.
        beats:             Beat list for computing per-slot beat energy.
        pacing_curve:      Per-slot energy targets 0-1 from build_pacing_curve().
        hook_count:        Number of leading slots treated as "hook".

    Returns:
        List of segment dicts with added slot_index key.
    """
    from analysis.semantic_score_engine import get_desired_tags, score_semantic_match
    from analysis.semantic_classifier import classify_segment
    from analysis.hook_selector import hook_score_multiplier, hook_min_energy

    total_slots = len(slot_durations)
    logger.info(
        "Ranking {} clip(s) for {} slot(s) | style={} | diversity={} | semantic={}",
        len(clip_paths), total_slots, edit_style,
        diversity_memory is not None, semantic_analyses is not None,
    )

    # Analyse all clips upfront
    analyses = {}
    for path in clip_paths:
        analyses[path] = analyze_clip(path)
        logger.debug("  {} -> peak={:.2f}", os.path.basename(path),
                     analyses[path]["peak_score"])

    # Build per-slot beat energy (0-1) from beats list
    beat_energies = _compute_beat_energies(beats, slot_durations) if beats else [0.5] * total_slots

    assignments   = []
    used_windows: dict = {}   # path -> set of (start, end) tuples (fallback for no diversity_memory)

    for slot_idx, duration in enumerate(slot_durations):
        position_ratio = slot_idx / max(total_slots - 1, 1)
        beat_energy    = beat_energies[slot_idx] if slot_idx < len(beat_energies) else 0.5
        energy_target  = pacing_curve[slot_idx] if pacing_curve and slot_idx < len(pacing_curve) else 0.5

        # Desired semantic tags for this slot
        desired_tags = get_desired_tags(slot_idx, total_slots, edit_style, beat_energy)

        hook_mult    = hook_score_multiplier(slot_idx, total_slots, hook_count)
        hook_min_e   = hook_min_energy(slot_idx, total_slots, hook_count)

        best_seg   = None
        best_score = -1.0

        for path, analysis in analyses.items():
            seg = find_best_segment(analysis, duration)

            # ── 1. Motion score (base)
            motion = seg["score"]
            if motion <= 0:
                continue

            # ── 2. Semantic affinity multiplier
            semantic_mult = 1.0
            if semantic_analyses and path in semantic_analyses:
                seg_profile = classify_segment(
                    semantic_analyses[path],
                    seg["start_time"], seg["end_time"],
                )
                semantic_match = score_semantic_match(seg_profile, desired_tags)
                # Map [0,1] match -> [0.5, 1.5] multiplier (neutral=1.0 at match=0.5)
                semantic_mult = 0.5 + semantic_match
            elif semantic_analyses is not None:
                semantic_mult = 0.75  # clip not classified — mild penalty

            # ── 3. Hook multiplier (boosts hook slots)
            hook_multiplier = hook_mult
            # Skip clip at hook slot if energy is too low
            seg_energy = (seg["score"] / max(max(a["peak_score"] for a in analyses.values()), 1.0))
            if hook_min_e > 0 and seg_energy < hook_min_e:
                hook_multiplier *= 0.3  # strongly penalise weak clips at hook positions

            # ── 4. Diversity penalty
            diversity_mult = 1.0
            if diversity_memory is not None:
                diversity_mult = diversity_memory.penalty(path, seg, slot_idx)
            elif path in used_windows:
                # Simple legacy fallback: penalise recently used path
                diversity_mult = 0.5

            # ── Combine
            effective = motion * semantic_mult * hook_multiplier * diversity_mult

            if effective > best_score:
                # Also check non-diversity reuse constraint
                if not allow_reuse and path in used_windows:
                    if _overlaps(seg, used_windows[path]):
                        continue
                best_seg   = seg
                best_score = effective

        # Fallback — if hook energy gate blocked everything, relax and retry
        if best_seg is None and hook_min_e > 0:
            logger.debug("Slot {}: hook gate blocked all clips — relaxing energy gate", slot_idx)
            for path, analysis in analyses.items():
                seg = find_best_segment(analysis, duration)
                motion = seg["score"]
                diversity_mult = diversity_memory.penalty(path, seg, slot_idx) if diversity_memory else 1.0
                effective = motion * diversity_mult
                if effective > best_score:
                    best_seg   = seg
                    best_score = effective

        if best_seg is None:
            logger.warning("Slot {}: no clip found — using first available", slot_idx)
            first = clip_paths[0] if clip_paths else None
            if first:
                best_seg = find_best_segment(analyses[first], duration)
            else:
                best_seg = {
                    "clip_path": "", "start_time": 0, "end_time": duration,
                    "duration": duration, "score": 0.0,
                    "start_frame": 0, "end_frame": int(duration * 30),
                }

        best_seg["slot_index"] = slot_idx
        assignments.append(best_seg)

        # Record usage
        if diversity_memory is not None:
            diversity_memory.record_use(best_seg["clip_path"], best_seg, slot_idx)
        used_windows.setdefault(best_seg["clip_path"], set())
        used_windows[best_seg["clip_path"]].add(
            (best_seg["start_time"], best_seg["end_time"])
        )

        logger.debug(
            "Slot {:>2} [{:.2f}s] -> '{}' [{:.1f}-{:.1f}s] "
            "score={:.2f} semantic_x{:.2f} hook_x{:.2f} div_x{:.2f}",
            slot_idx, duration,
            os.path.basename(best_seg["clip_path"]),
            best_seg["start_time"], best_seg["end_time"],
            best_seg["score"],
            semantic_mult if "semantic_mult" in dir() else 1.0,
            hook_mult,
            diversity_mult if "diversity_mult" in dir() else 1.0,
        )

    if diversity_memory:
        logger.info("Diversity summary: {}", diversity_memory.usage_summary())

    logger.info("Slot assignment complete: {} slots", len(assignments))
    return assignments


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _downscale(frame) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= _ANALYSIS_WIDTH:
        return frame
    scale = _ANALYSIS_WIDTH / w
    return cv2.resize(frame, (int(w * scale), int(h * scale)),
                      interpolation=cv2.INTER_LINEAR)


def _aggregate_to_seconds(frame_scores: list, fps: float, duration_secs: int) -> list:
    result = []
    for second in range(duration_secs):
        start_f = second * fps
        end_f   = start_f + fps
        window  = [s for f, s in frame_scores if start_f <= f < end_f]
        score   = float(np.mean(window)) if window else 0.0
        result.append({
            "second":     second,
            "start_time": float(second),
            "end_time":   float(second + 1),
            "score":      round(score, 4),
        })
    return result


def _segment_dict(clip_path, start_t, end_t, score, fps) -> dict:
    return {
        "clip_path":   clip_path,
        "start_time":  round(start_t, 4),
        "end_time":    round(end_t, 4),
        "duration":    round(end_t - start_t, 4),
        "score":       round(score, 4),
        "start_frame": int(round(start_t * fps)),
        "end_frame":   int(round(end_t * fps)),
    }


def _overlaps(seg: dict, used_windows: set) -> bool:
    for (us, ue) in used_windows:
        if seg["start_time"] < ue and seg["end_time"] > us:
            return True
    return False


def _empty_result(clip_path: str) -> dict:
    return {
        "clip_path": clip_path, "duration": 0.0, "fps": 30.0,
        "peak_score": 0.0, "mean_score": 0.0, "second_scores": [],
    }


def _compute_beat_energies(beats: list, slot_durations: list) -> list:
    """
    Map each slot to a 0-1 beat energy value based on beat density around
    the slot's approximate timeline position.
    """
    if not beats:
        return [0.5] * len(slot_durations)

    beat_times = [b["time"] for b in beats if "time" in b]
    if not beat_times:
        return [0.5] * len(slot_durations)

    total_dur = sum(slot_durations)
    energies  = []
    cursor    = 0.0

    for dur in slot_durations:
        slot_start = cursor
        slot_end   = cursor + dur
        # Count beats in a ±dur window around this slot
        window_beats = sum(1 for t in beat_times if slot_start - dur <= t <= slot_end + dur)
        total_beats  = max(len(beat_times), 1)
        # Normalize: fraction of all beats in this neighbourhood
        energy = min(window_beats / max(total_beats * (dur * 2 / total_dur), 1), 1.0)
        energies.append(round(energy, 3))
        cursor = slot_end

    return energies
