"""
General video processing utilities — metadata extraction and frame helpers.
"""

from math import gcd
import cv2
from utils.logger import get_logger

logger = get_logger(__name__)


def get_video_metadata(video_path: str) -> dict:
    """
    Read FPS, resolution, duration, frame count, and aspect-ratio info via OpenCV.

    Returns:
        {
            "fps": float,
            "width": int,
            "height": int,
            "frame_count": int,
            "duration_seconds": float,
            "is_vertical": bool,
            "aspect_ratio": str,   # e.g. "16:9" or "9:16"
        }

    Raises:
        ValueError: if the video cannot be opened.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video file: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    duration_seconds = frame_count / fps if fps > 0 else 0.0
    is_vertical = height > width

    divisor = gcd(width, height) if (width and height) else 1
    aspect_ratio = f"{width // divisor}:{height // divisor}"

    logger.debug(
        "Metadata | {}x{} @ {:.2f}fps | {:.2f}s | {} | {}",
        width, height, fps, duration_seconds,
        "vertical" if is_vertical else "horizontal",
        aspect_ratio,
    )

    return {
        "fps": fps,
        "width": width,
        "height": height,
        "frame_count": frame_count,
        "duration_seconds": duration_seconds,
        "is_vertical": is_vertical,
        "aspect_ratio": aspect_ratio,
    }


def seconds_to_frames(seconds: float, fps: float) -> int:
    """Convert a timestamp in seconds to an integer frame index."""
    return int(round(seconds * fps))


def frames_to_seconds(frame_index: int, fps: float) -> float:
    """Convert a frame index to a timestamp in seconds."""
    return frame_index / fps if fps > 0 else 0.0


def clamp_frame(frame_index: int, total_frames: int) -> int:
    """Keep a frame index within [0, total_frames - 1]."""
    return max(0, min(frame_index, total_frames - 1))
