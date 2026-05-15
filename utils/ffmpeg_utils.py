"""
Wrapper functions for common FFmpeg operations via the ffmpeg-python binding.
ffmpeg is imported lazily inside each function so this module can be safely
imported in environments where ffmpeg-python is not installed (e.g. Resolve's
bundled Python). Functions will raise ImportError only when actually called.
"""

import os
from utils.logger import get_logger

logger = get_logger(__name__)


def _ffmpeg():
    """Lazy import of ffmpeg-python; raises ImportError with a clear message if missing."""
    try:
        import ffmpeg as _ff
        return _ff
    except ImportError:
        raise ImportError(
            "ffmpeg-python is not installed in this Python environment.\n"
            "Run: pip install ffmpeg-python"
        )


def extract_audio(
    video_path: str,
    output_audio_path: str,
    sample_rate: int = 16000,
    channels: int = 1,
) -> bool:
    """
    Extract the audio track from a video file and write it as a WAV.

    Args:
        video_path:        Absolute path to the source video.
        output_audio_path: Destination path for the extracted WAV file.
        sample_rate:       Target sample rate in Hz (16 000 works well for Whisper).
        channels:          1 = mono (recommended for analysis), 2 = stereo.

    Returns:
        True on success, False on failure.
    """
    ffmpeg = _ffmpeg()
    logger.info("Extracting audio: {} -> {}", video_path, output_audio_path)
    os.makedirs(os.path.dirname(os.path.abspath(output_audio_path)), exist_ok=True)

    try:
        (
            ffmpeg
            .input(video_path)
            .output(
                output_audio_path,
                acodec="pcm_s16le",
                ac=channels,
                ar=sample_rate,
            )
            .overwrite_output()
            .run(quiet=True)
        )
        logger.info("Audio extracted successfully -> {}", output_audio_path)
        return True

    except ffmpeg.Error as e:
        stderr = e.stderr.decode(errors="replace") if e.stderr else str(e)
        logger.error("FFmpeg failed: {}", stderr)
        return False


def extract_full_audio_track(
    video_path: str,
    output_audio_path: str,
    sample_rate: int = 48000,
    channels: int = 2,
) -> bool:
    """
    Extract the full-quality stereo audio track for timeline use (48 kHz, stereo).
    Distinct from extract_audio() which produces a 16 kHz mono file for AI analysis.
    """
    ffmpeg = _ffmpeg()
    logger.info("Extracting full audio track: {} -> {}", video_path, output_audio_path)
    os.makedirs(os.path.dirname(os.path.abspath(output_audio_path)), exist_ok=True)
    try:
        (
            ffmpeg
            .input(video_path)
            .output(
                output_audio_path,
                acodec="pcm_s16le",
                ac=channels,
                ar=sample_rate,
                vn=None,
            )
            .overwrite_output()
            .run(quiet=True)
        )
        logger.info("Full audio track extracted -> {}", output_audio_path)
        return True
    except ffmpeg.Error as e:
        stderr = e.stderr.decode(errors="replace") if e.stderr else str(e)
        logger.error("FFmpeg failed: {}", stderr)
        return False


def get_video_duration_ffprobe(video_path: str) -> float:
    """
    Use ffprobe to read the exact duration of a video in seconds.
    Returns 0.0 if the probe fails.
    """
    try:
        ffmpeg = _ffmpeg()
        probe = ffmpeg.probe(video_path)
        return float(probe["format"].get("duration", 0))
    except ImportError:
        return _get_duration_cv2(video_path)
    except Exception as e:
        logger.warning("ffprobe failed for {}: {}", video_path, e)
        return 0.0


def _get_duration_cv2(video_path: str) -> float:
    """Fallback duration reader using OpenCV (no ffmpeg needed)."""
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return 0.0
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        return frames / fps if fps > 0 else 0.0
    except Exception:
        return 0.0
