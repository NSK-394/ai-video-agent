"""
Cut / scene-change detector.

Primary backend : PySceneDetect (ContentDetector — accurate, handles fades).
Fallback backend: OpenCV histogram differencing (zero extra dependencies).

Both return the same list-of-dicts schema so the rest of the pipeline is
backend-agnostic.
"""

import os
import cv2
import numpy as np
from config.constants import (
    SCENEDETECT_THRESHOLD,
    OPENCV_HIST_DIFF_THRESHOLD,
    MIN_SCENE_DURATION,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Backend availability check
# ---------------------------------------------------------------------------
try:
    from scenedetect import open_video, SceneManager
    from scenedetect.detectors import ContentDetector
    _SCENEDETECT_AVAILABLE = True
    logger.debug("PySceneDetect available — will use as primary backend")
except ImportError:
    _SCENEDETECT_AVAILABLE = False
    logger.warning("PySceneDetect not installed — falling back to OpenCV detector")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_cuts(
    video_path: str,
    threshold: float = None,
    min_scene_duration: float = MIN_SCENE_DURATION,
) -> list:
    """
    Detect scene cuts in a video file.

    Args:
        video_path:         Absolute path to the video.
        threshold:          Detection sensitivity.
                            PySceneDetect: 27.0 (lower = more cuts).
                            OpenCV fallback: 0.35 L2-norm difference ratio.
        min_scene_duration: Minimum scene length in seconds. Scenes shorter
                            than this are merged into the previous one.

    Returns:
        List of cut-segment dicts:
        [
            {
                "index":       int,
                "start_time":  float,  # seconds
                "end_time":    float,  # seconds
                "duration":    float,  # seconds
                "start_frame": int,
                "end_frame":   int,
                "confidence":  float,  # 0.0–1.0
            },
            ...
        ]
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    logger.info("Detecting cuts in: {}", video_path)

    if _SCENEDETECT_AVAILABLE:
        th = threshold if threshold is not None else SCENEDETECT_THRESHOLD
        cuts = _detect_scenedetect(video_path, th, min_scene_duration)
    else:
        th = threshold if threshold is not None else OPENCV_HIST_DIFF_THRESHOLD
        cuts = _detect_opencv(video_path, th, min_scene_duration)

    logger.info("Cut detection complete: {} scenes found", len(cuts))
    return cuts


# ---------------------------------------------------------------------------
# PySceneDetect backend
# ---------------------------------------------------------------------------

def _detect_scenedetect(
    video_path: str, threshold: float, min_scene_duration: float
) -> list:
    logger.debug("Using PySceneDetect (threshold={})", threshold)

    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(
        ContentDetector(threshold=threshold, min_scene_len=1)
    )
    scene_manager.detect_scenes(video, show_progress=False)
    scene_list = scene_manager.get_scene_list()

    fps = video.frame_rate

    cuts = []
    for i, (start_tc, end_tc) in enumerate(scene_list):
        start_s = start_tc.get_seconds()
        end_s = end_tc.get_seconds()
        duration = end_s - start_s

        if duration < min_scene_duration and cuts:
            # Absorb short scene into previous
            cuts[-1]["end_time"] = end_s
            cuts[-1]["end_frame"] = end_tc.get_frames()
            cuts[-1]["duration"] = end_s - cuts[-1]["start_time"]
            continue

        cuts.append({
            "index":       len(cuts),
            "start_time":  round(start_s, 4),
            "end_time":    round(end_s, 4),
            "duration":    round(duration, 4),
            "start_frame": start_tc.get_frames(),
            "end_frame":   end_tc.get_frames(),
            "confidence":  1.0,
        })

    return cuts


# ---------------------------------------------------------------------------
# OpenCV fallback backend
# ---------------------------------------------------------------------------

def _detect_opencv(
    video_path: str, threshold: float, min_scene_duration: float
) -> list:
    logger.debug("Using OpenCV histogram fallback (threshold={})", threshold)

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    min_frames = max(1, int(min_scene_duration * fps))

    cuts = []
    prev_hist = None
    frame_idx = 0
    scene_start_frame = 0
    scene_start_time = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [64], [0, 256])
        cv2.normalize(hist, hist)
        hist = hist.flatten()

        if prev_hist is not None:
            diff = float(np.linalg.norm(hist - prev_hist))
            is_cut = diff > threshold
            long_enough = (frame_idx - scene_start_frame) >= min_frames

            if is_cut and long_enough:
                current_time = frame_idx / fps
                confidence = min(1.0, diff / (threshold * 3.0))
                cuts.append({
                    "index":       len(cuts),
                    "start_time":  round(scene_start_time, 4),
                    "end_time":    round(current_time, 4),
                    "duration":    round(current_time - scene_start_time, 4),
                    "start_frame": scene_start_frame,
                    "end_frame":   frame_idx,
                    "confidence":  round(confidence, 4),
                })
                scene_start_frame = frame_idx
                scene_start_time = current_time

        prev_hist = hist
        frame_idx += 1

    cap.release()

    # Close the final scene
    if frame_idx > scene_start_frame:
        end_time = frame_idx / fps
        cuts.append({
            "index":       len(cuts),
            "start_time":  round(scene_start_time, 4),
            "end_time":    round(end_time, 4),
            "duration":    round(end_time - scene_start_time, 4),
            "start_frame": scene_start_frame,
            "end_frame":   frame_idx,
            "confidence":  1.0,
        })

    return cuts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def cut_timestamps(cuts: list) -> list:
    """Return just the list of cut start-times in seconds (useful for alignment)."""
    return [c["start_time"] for c in cuts]
