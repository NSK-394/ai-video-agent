"""
audio_mixer.py
--------------
Audio mix modes and loudness normalization via subprocess ffmpeg.

Supports three mixing strategies (AudioMixMode) and two utility functions:
  - normalize_audio : two-pass EBU R128 loudnorm
  - apply_fade      : fade-in / fade-out via afade filter

Gracefully degrades when ffmpeg is not on PATH.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from enum import Enum

from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Enums & constants
# ---------------------------------------------------------------------------

class AudioMixMode(str, Enum):
    REFERENCE_ONLY = "reference_only"  # mute clips, only reference/music track
    CLIP_ONLY      = "clip_only"       # keep clip audio, no reference track
    HYBRID_MIX     = "hybrid_mix"      # both tracks; reference sits -6 dB under clips


# EBU R128 loudnorm targets (industry standard for streaming/broadcast)
LOUDNORM_TARGET_I   = -14.0   # integrated loudness  (LUFS)
LOUDNORM_TARGET_TP  =  -1.0   # true peak            (dBTP)
LOUDNORM_TARGET_LRA =   7.0   # loudness range       (LU)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def normalize_audio(input_path: str, output_path: str) -> bool:
    """
    Two-pass ffmpeg loudnorm normalization (EBU R128).

    Pass 1 — measure actual loudness stats from the file.
    Pass 2 — apply linear gain correction using the measured stats.

    Falls back to a plain file copy if ffmpeg is not available.
    Returns True on success, False on any failure.
    """
    if not shutil.which("ffmpeg"):
        logger.warning("ffmpeg not found — copying file without normalization")
        return _copy_fallback(input_path, output_path)

    # --- Pass 1: probe loudness stats ----------------------------------------
    loudnorm_filter = (
        f"loudnorm=I={LOUDNORM_TARGET_I}"
        f":TP={LOUDNORM_TARGET_TP}"
        f":LRA={LOUDNORM_TARGET_LRA}"
        f":print_format=json"
    )
    probe_cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", input_path,
        "-af", loudnorm_filter,
        "-f", "null", "-",
    ]
    result = subprocess.run(probe_cmd, capture_output=True, text=True)

    # ffmpeg writes the JSON stats to stderr
    stats = _parse_loudnorm_json(result.stderr)
    if stats is None:
        logger.error("Pass-1 loudnorm parse failed for {}", input_path)
        return _copy_fallback(input_path, output_path)

    logger.info(
        "Loudnorm pass-1 | I={input_i} TP={input_tp} LRA={input_lra}",
        **{k: stats.get(k, "?") for k in ("input_i", "input_tp", "input_lra")},
    )

    # --- Pass 2: apply measured correction ------------------------------------
    apply_filter = (
        f"loudnorm=I={LOUDNORM_TARGET_I}"
        f":TP={LOUDNORM_TARGET_TP}"
        f":LRA={LOUDNORM_TARGET_LRA}"
        f":measured_I={stats['input_i']}"
        f":measured_TP={stats['input_tp']}"
        f":measured_LRA={stats['input_lra']}"
        f":measured_thresh={stats['input_thresh']}"
        f":offset={stats['target_offset']}"
        f":linear=true"
    )
    apply_cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", input_path,
        "-af", apply_filter,
        output_path,
    ]
    result2 = subprocess.run(apply_cmd, capture_output=True, text=True)
    if result2.returncode != 0:
        logger.error("Pass-2 loudnorm failed (rc={}) for {}", result2.returncode, input_path)
        return False

    logger.info("Normalized audio written to {}", output_path)
    return True


def apply_fade(
    input_path: str,
    output_path: str,
    fade_in_secs: float = 0.0,
    fade_out_secs: float = 0.5,
) -> bool:
    """
    Apply fade-in and/or fade-out using ffmpeg's afade filter.

    Skips a fade direction entirely when its duration is <= 0.
    Returns True on success, False on failure.
    """
    if not shutil.which("ffmpeg"):
        logger.warning("ffmpeg not found — skipping fade, copying file")
        return _copy_fallback(input_path, output_path)

    filters = []

    if fade_in_secs > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in_secs}")

    if fade_out_secs > 0:
        # We need the duration to calculate the fade-out start time.
        # Use ffprobe to get it; fall back to a 0-start if unavailable.
        duration = _probe_duration(input_path)
        if duration is not None:
            start = max(0.0, duration - fade_out_secs)
            filters.append(f"afade=t=out:st={start:.4f}:d={fade_out_secs}")
        else:
            # Cannot determine duration — skip fade-out rather than corrupt audio
            logger.warning("Could not probe duration for {}; fade-out skipped", input_path)

    if not filters:
        # Nothing to do — just copy
        return _copy_fallback(input_path, output_path)

    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", input_path,
        "-af", ",".join(filters),
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("apply_fade failed (rc={}) for {}", result.returncode, input_path)
        return False

    logger.info("Fades applied ({} in / {} out) -> {}", fade_in_secs, fade_out_secs, output_path)
    return True


# ---------------------------------------------------------------------------
# Mode resolution helpers
# ---------------------------------------------------------------------------

def get_mix_mode(mute_clips: bool, mix_mode_str: str = None) -> AudioMixMode:
    """
    Resolve the active AudioMixMode from caller flags.

    Priority:
      1. If mix_mode_str is explicitly provided, parse it as an enum value.
      2. If mute_clips=True (and no explicit string), use REFERENCE_ONLY.
      3. Default: CLIP_ONLY.
    """
    if mix_mode_str:
        try:
            mode = AudioMixMode(mix_mode_str)
            logger.debug("Audio mix mode from string: {}", mode)
            return mode
        except ValueError:
            logger.warning("Unknown mix_mode_str '{}' — falling back to CLIP_ONLY", mix_mode_str)

    if mute_clips:
        logger.debug("mute_clips=True -> REFERENCE_ONLY")
        return AudioMixMode.REFERENCE_ONLY

    return AudioMixMode.CLIP_ONLY


def resolve_mute_clips(mix_mode: AudioMixMode) -> bool:
    """
    Return True when video clips should be imported as mediaType=1 (video-only).

    REFERENCE_ONLY and HYBRID_MIX both strip embedded audio from clips so
    that the reference/music track can be the sole or dominant audio source.
    CLIP_ONLY keeps the clip's original audio track.
    """
    return mix_mode in (AudioMixMode.REFERENCE_ONLY, AudioMixMode.HYBRID_MIX)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _parse_loudnorm_json(stderr_text: str) -> dict | None:
    """Extract the JSON block ffmpeg loudnorm writes to stderr."""
    # ffmpeg outputs a JSON object starting with '{'
    start = stderr_text.rfind("{")
    end   = stderr_text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(stderr_text[start: end + 1])
    except json.JSONDecodeError:
        return None


def _probe_duration(path: str) -> float | None:
    """Return audio duration in seconds using ffprobe, or None on error."""
    if not shutil.which("ffprobe"):
        return None
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return None


def _copy_fallback(src: str, dst: str) -> bool:
    """Copy src to dst using ffmpeg (codec copy); returns True on success."""
    if not shutil.which("ffmpeg"):
        import shutil as _sh
        try:
            _sh.copy2(src, dst)
            return True
        except Exception as exc:
            logger.error("File copy fallback failed: {}", exc)
            return False

    cmd = ["ffmpeg", "-hide_banner", "-y", "-i", src, "-c", "copy", dst]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0
