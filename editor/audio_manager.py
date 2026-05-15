"""
audio_manager.py
----------------
Handles extraction and placement of the reference audio track in the Resolve timeline.

Pipeline:
  1. extract_reference_audio()  — pull full-quality stereo WAV from reference video
  2. import_audio_to_media_pool() — add WAV to Media Pool under AI_Audio bin
  3. place_audio_on_timeline()  — append audio-only item to A1 track

Muting video clips:
  timeline_builder already accepts video_only=True, which sets mediaType=1 on every
  clip dict so Resolve strips the embedded audio channel at import time. This is
  cleaner than post-hoc muting because no audio track is ever created for those clips.
"""

import os
from utils.logger import get_logger
from utils.ffmpeg_utils import get_video_duration_ffprobe

logger = get_logger(__name__)

_AUDIO_BIN = "AI_Audio"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_reference_audio(
    reference_video_path: str,
    output_dir: str,
    filename: str = "reference_audio.wav",
) -> str | None:
    """
    Extract the full stereo audio track from the reference video as a 48 kHz WAV.

    The 48 kHz / stereo format is broadcast-standard and what Resolve expects
    for timeline audio. (The 16 kHz mono WAV used by Whisper/librosa is separate.)

    Returns:
        Absolute path to the extracted WAV, or None on failure.
    """
    out_path = os.path.join(output_dir, filename)
    os.makedirs(output_dir, exist_ok=True)

    if os.path.isfile(out_path):
        logger.info("Reference audio already extracted: {}", out_path)
        return out_path

    if not os.path.isfile(reference_video_path):
        logger.error("Reference video not found: {}", reference_video_path)
        return None

    logger.info(
        "Extracting reference audio: {} -> {}",
        os.path.basename(reference_video_path), out_path,
    )

    # Use the ffmpeg binary directly via subprocess — works in any Python environment
    # regardless of whether ffmpeg-python is installed.
    import subprocess
    cmd = [
        "ffmpeg", "-y",
        "-i", reference_video_path,
        "-vn",               # no video
        "-acodec", "pcm_s16le",
        "-ac", "2",          # stereo
        "-ar", "48000",      # 48 kHz broadcast standard
        out_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")
            logger.error("ffmpeg binary failed (code {}): {}", result.returncode, stderr[-400:])
            return None
        duration = get_audio_duration(out_path)
        logger.info(
            "Reference audio extracted: {:.2f}s @ 48kHz stereo -> {}",
            duration, out_path,
        )
        return out_path
    except FileNotFoundError:
        logger.error(
            "ffmpeg binary not found on PATH — install ffmpeg and ensure it is in PATH"
        )
        return None
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timed out extracting audio from {}", reference_video_path)
        return None
    except Exception as e:
        logger.error("Audio extraction failed: {}", e)
        return None


def get_audio_duration(audio_path: str) -> float:
    """
    Return duration of an audio/video file in seconds.
    Tries ffprobe subprocess first, then ffmpeg-python, then cv2 — works in any environment.
    """
    # Try ffprobe binary directly (always available if ffmpeg is on PATH)
    import subprocess
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass

    # Fallback: ffmpeg-python or cv2
    return get_video_duration_ffprobe(audio_path)


def import_audio_to_media_pool(resolve_ctrl, audio_path: str):
    """
    Import an audio file into the Resolve Media Pool under the AI_Audio bin.

    Returns:
        MediaPoolItem, or None on failure.
    """
    from editor.media_importer import import_media

    items = import_media(resolve_ctrl, [audio_path], bin_name=_AUDIO_BIN)
    if not items or items[0] is None:
        logger.error("Failed to import audio to Media Pool: {}", audio_path)
        return None

    logger.info("Audio imported to Media Pool: {}", os.path.basename(audio_path))
    return items[0]


def place_audio_on_timeline(
    resolve_ctrl,
    timeline,
    audio_item,
    audio_duration_secs: float,
    track_index: int = 1,
) -> bool:
    """
    Append the audio MediaPoolItem to the Resolve timeline on an audio track.

    Uses mediaType=2 in the AppendToTimeline clip dict so Resolve creates an
    audio-only item on track A{track_index} rather than a video clip.

    Args:
        resolve_ctrl:        Connected ResolveController.
        timeline:            The Resolve Timeline object.
        audio_item:          MediaPoolItem for the WAV file.
        audio_duration_secs: Total length of the audio file in seconds.
        track_index:         Audio track index (1 = A1, default).

    Returns:
        True on success, False on failure.
    """
    resolve_ctrl.require_connection()
    media_pool = resolve_ctrl.media_pool

    try:
        fps = float(timeline.GetSetting("timelineFrameRate") or 30)
    except Exception:
        fps = 30.0

    total_audio_frames = int(audio_duration_secs * fps)

    clip_dict = {
        "mediaPoolItem": audio_item,
        "startFrame":    0,
        "endFrame":      total_audio_frames,
        "mediaType":     2,            # audio-only placement
        "trackIndex":    track_index,
    }

    logger.info(
        "Placing audio on A{}: {:.2f}s ({} frames @ {}fps)",
        track_index, audio_duration_secs, total_audio_frames, int(fps),
    )

    try:
        placed = media_pool.AppendToTimeline([clip_dict])
        if placed:
            logger.info("Audio placed on timeline (A{} track)", track_index)
            return True
        logger.warning("AppendToTimeline returned empty for audio clip")
        return False
    except Exception as e:
        logger.error("Failed to place audio on timeline: {}", e)
        return False


def resolve_audio_source(blueprint: dict, blueprint_path: str, audio_source_override: str = None) -> str | None:
    """
    Determine the reference video path to extract audio from.

    Priority:
      1. audio_source_override (user-supplied via CLI / config)
      2. blueprint["source_video"]["path"] (recorded at analysis time)

    Returns the path if the file exists, None otherwise.
    """
    candidates = []

    if audio_source_override:
        candidates.append(os.path.abspath(audio_source_override))

    bp_path = (blueprint.get("source_video") or {}).get("path", "")
    if bp_path:
        candidates.append(os.path.abspath(bp_path))
        # Also try relative to the blueprint file
        bp_dir = os.path.dirname(os.path.abspath(blueprint_path))
        candidates.append(os.path.abspath(os.path.join(bp_dir, bp_path)))
        # Walk up one level (reference/ -> reference/demo_videos/)
        for fname in (os.path.basename(bp_path), os.path.basename(blueprint_path).replace(".json", ".mp4")):
            for dirpath, _, fnames in os.walk(os.path.dirname(bp_dir)):
                if fname in fnames:
                    candidates.append(os.path.join(dirpath, fname))
                break  # only one level up

    for c in candidates:
        if os.path.isfile(c):
            logger.debug("Resolved audio source: {}", c)
            return c

    logger.warning(
        "Could not locate reference video for audio extraction. "
        "Tried: {}", candidates,
    )
    return None
