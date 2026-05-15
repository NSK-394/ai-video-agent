"""
Audio beat detection and rhythm analysis using librosa.

Accepts either an audio file (WAV/MP3) or a video file path.
When a video path is given, audio is extracted to a temp WAV first.
"""

import os
import tempfile
import numpy as np
import librosa
from config.constants import BEAT_AUDIO_SAMPLE_RATE, BEAT_HOP_LENGTH
from utils.logger import get_logger

logger = get_logger(__name__)

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mxf", ".avi", ".mkv", ".m4v", ".r3d", ".braw"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_beats(
    audio_path: str,
    sample_rate: int = BEAT_AUDIO_SAMPLE_RATE,
    hop_length: int = BEAT_HOP_LENGTH,
) -> dict:
    """
    Detect beat positions and estimate BPM from an audio or video file.

    Args:
        audio_path:  Path to a WAV/MP3 (or video — audio is extracted first).
        sample_rate: Librosa sample rate in Hz.
        hop_length:  Hop size for onset detection frames.

    Returns:
        {
            "bpm":         float,           # global tempo estimate
            "beat_count":  int,
            "beats": [
                {
                    "index": int,
                    "time":  float,         # seconds
                    "frame": int,           # at default_fps=30
                },
                ...
            ]
        }
    """
    resolved_path = _maybe_extract_audio(audio_path)
    logger.info("Analysing beats in: {}", resolved_path)

    try:
        y, sr = librosa.load(resolved_path, sr=sample_rate, mono=True)
    except Exception as e:
        logger.error("librosa.load failed: {}", e)
        return _empty_result()

    # Global tempo + beat frame indices
    tempo, beat_frames = librosa.beat.beat_track(
        y=y, sr=sr, hop_length=hop_length, units="frames"
    )
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop_length)

    # Per-beat local tempo (smoothed via adjacent inter-beat interval)
    ibi = np.diff(beat_times)  # inter-beat intervals
    local_bpm = np.where(ibi > 0, 60.0 / ibi, float(tempo))

    beats = []
    for i, (t, f) in enumerate(zip(beat_times, beat_frames)):
        local = float(local_bpm[i - 1]) if i > 0 else float(tempo)
        beats.append({
            "index":     i,
            "time":      round(float(t), 4),
            "frame":     int(round(float(t) * 30)),  # 30 fps default display frame
            "bpm_local": round(local, 2),
        })

    result = {
        "bpm":        round(float(tempo), 2),
        "beat_count": len(beats),
        "beats":      beats,
    }

    logger.info(
        "Beat detection complete: {} beats @ {:.1f} BPM",
        result["beat_count"], result["bpm"],
    )

    # Clean up temp file if we created one
    if resolved_path != audio_path and os.path.isfile(resolved_path):
        os.remove(resolved_path)

    return result


def beat_times_list(beat_result: dict) -> list:
    """Convenience: return a flat list of beat timestamps in seconds."""
    return [b["time"] for b in beat_result.get("beats", [])]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _maybe_extract_audio(path: str) -> str:
    """
    If path is a video file, extract its audio to a temp WAV and return
    the temp path. Otherwise return path unchanged.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in _VIDEO_EXTENSIONS:
        return path

    logger.debug("Video path detected — extracting audio for beat analysis")
    from utils.ffmpeg_utils import extract_audio

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    ok = extract_audio(path, tmp.name, sample_rate=BEAT_AUDIO_SAMPLE_RATE, channels=1)
    if not ok:
        raise RuntimeError(f"Audio extraction failed for: {path}")
    return tmp.name


def _empty_result() -> dict:
    return {"bpm": 0.0, "beat_count": 0, "beats": []}
