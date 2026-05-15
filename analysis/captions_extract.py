"""
Speech transcription with word-level timestamps using OpenAI Whisper.

Accepts a WAV/MP3 audio file or a video file (audio extracted automatically).
Returns structured segments compatible with the blueprint schema.
"""

import os
import tempfile
import whisper
from config.constants import WHISPER_MODEL_SIZE, WHISPER_LANGUAGE
from utils.logger import get_logger

logger = get_logger(__name__)

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mxf", ".avi", ".mkv", ".m4v", ".r3d", ".braw"}

# Module-level model cache — load once per process
_model_cache: dict = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_captions(
    audio_path: str,
    model_size: str = WHISPER_MODEL_SIZE,
    language: str = WHISPER_LANGUAGE,
    word_timestamps: bool = True,
) -> dict:
    """
    Transcribe audio and return structured caption data.

    Args:
        audio_path:       Path to audio (WAV/MP3) or video file.
        model_size:       Whisper model variant: tiny | base | small | medium | large.
        language:         ISO-639-1 code (e.g. "en"), or None for auto-detect.
        word_timestamps:  When True, each segment includes per-word timing.

    Returns:
        {
            "language":    str,
            "full_text":   str,
            "duration":    float,   # total audio duration in seconds
            "word_count":  int,
            "segments": [
                {
                    "index":      int,
                    "start_time": float,
                    "end_time":   float,
                    "text":       str,
                    "confidence": float,   # from avg_logprob; range ≈ -∞ to 0
                    "words": [             # only when word_timestamps=True
                        {"word": str, "start": float, "end": float, "confidence": float}
                    ]
                },
                ...
            ]
        }
    """
    resolved_path = _maybe_extract_audio(audio_path)
    logger.info("Transcribing: {} (model={})", resolved_path, model_size)

    model = _load_model(model_size)

    try:
        result = model.transcribe(
            resolved_path,
            language=language,
            word_timestamps=word_timestamps,
            verbose=False,
        )
    except Exception as e:
        logger.error("Whisper transcription failed: {}", e)
        return _empty_result()

    segments = []
    total_words = 0

    for seg in result.get("segments", []):
        words = []
        if word_timestamps and "words" in seg:
            for w in seg["words"]:
                words.append({
                    "word":       w.get("word", "").strip(),
                    "start":      round(float(w.get("start", 0)), 4),
                    "end":        round(float(w.get("end", 0)), 4),
                    "confidence": round(float(w.get("probability", 0)), 4),
                })
            total_words += len(words)

        segments.append({
            "index":      int(seg.get("id", len(segments))),
            "start_time": round(float(seg.get("start", 0)), 4),
            "end_time":   round(float(seg.get("end", 0)), 4),
            "text":       seg.get("text", "").strip(),
            "confidence": round(float(seg.get("avg_logprob", 0)), 6),
            "words":      words,
        })

    duration = segments[-1]["end_time"] if segments else 0.0

    caption_data = {
        "language":   result.get("language", "unknown"),
        "full_text":  result.get("text", "").strip(),
        "duration":   duration,
        "word_count": total_words,
        "segments":   segments,
    }

    logger.info(
        "Transcription complete: {} segments | {} words | lang={}",
        len(segments), total_words, caption_data["language"],
    )

    # Clean up temp audio if we created it
    if resolved_path != audio_path and os.path.isfile(resolved_path):
        os.remove(resolved_path)

    return caption_data


def speech_coverage(caption_data: dict, video_duration: float) -> float:
    """
    Return the fraction of the video that contains spoken words (0.0–1.0).
    Useful for classifying dialogue-driven edits.
    """
    if video_duration <= 0 or not caption_data.get("segments"):
        return 0.0
    total_speech = sum(
        s["end_time"] - s["start_time"] for s in caption_data["segments"]
    )
    return min(1.0, total_speech / video_duration)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_model(model_size: str) -> whisper.Whisper:
    if model_size not in _model_cache:
        logger.info("Loading Whisper model '{}' …", model_size)
        _model_cache[model_size] = whisper.load_model(model_size)
        logger.info("Whisper model '{}' loaded", model_size)
    return _model_cache[model_size]


def _maybe_extract_audio(path: str) -> str:
    """Extract audio from video to a temp WAV if needed."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in _VIDEO_EXTENSIONS:
        return path

    logger.debug("Video path — extracting audio for Whisper")
    from utils.ffmpeg_utils import extract_audio
    from config.constants import AUDIO_SAMPLE_RATE_WHISPER

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    ok = extract_audio(path, tmp.name, sample_rate=AUDIO_SAMPLE_RATE_WHISPER, channels=1)
    if not ok:
        raise RuntimeError(f"Audio extraction failed for: {path}")
    return tmp.name


def _empty_result() -> dict:
    return {
        "language":   "unknown",
        "full_text":  "",
        "duration":   0.0,
        "word_count": 0,
        "segments":   [],
    }
