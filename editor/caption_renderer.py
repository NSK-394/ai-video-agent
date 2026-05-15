"""
caption_renderer.py
-------------------
Renders blueprint captions into the Resolve timeline.

Strategy (in priority order):
  1. Generate an SRT file from blueprint caption segments.
  2. Attempt to import the SRT via the Resolve subtitle import API
     (available in Resolve 18+; gracefully degrades if unavailable).
  3. Log the SRT path so the user can manually import if the API call fails.

The SRT file is always written regardless of whether the API import succeeds,
so captions are never silently lost.

Timecode format:  HH:MM:SS,mmm  (SRT standard)
"""

import os
from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_captions(
    resolve_ctrl,
    timeline,
    blueprint: dict,
    output_dir: str = None,
    srt_filename: str = "captions.srt",
) -> str:
    """
    Generate an SRT file from the blueprint and import it into the timeline.

    Args:
        resolve_ctrl: Connected ResolveController (may be None for SRT-only mode).
        timeline:     Resolve Timeline object to receive the subtitles.
        blueprint:    Parsed blueprint dict (must contain "captions").
        output_dir:   Directory to write the SRT file. Defaults to output/captions/.
        srt_filename: Override the SRT filename.

    Returns:
        Absolute path to the written SRT file.
    """
    captions = blueprint.get("captions", [])
    if not captions:
        logger.info("No captions in blueprint — skipping caption render")
        return ""

    # Resolve output path
    if output_dir is None:
        output_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "output", "captions",
        )
    os.makedirs(output_dir, exist_ok=True)
    srt_path = os.path.join(output_dir, srt_filename)

    # Write SRT
    _write_srt(captions, srt_path)
    logger.info("SRT written -> {}", srt_path)

    # Attempt Resolve import if we have an active timeline
    if resolve_ctrl is not None and timeline is not None:
        _import_srt_into_timeline(resolve_ctrl, timeline, srt_path)
    else:
        logger.info("No timeline provided — SRT written but not imported")

    return srt_path


def write_srt_only(blueprint: dict, output_path: str) -> str:
    """
    Write SRT without touching Resolve. Useful for testing or offline workflows.
    Returns the output path.
    """
    captions = blueprint.get("captions", [])
    _write_srt(captions, output_path)
    return output_path


# ---------------------------------------------------------------------------
# SRT generation
# ---------------------------------------------------------------------------

def _write_srt(captions: list, path: str):
    """Serialise caption segments to SRT format."""
    lines = []
    for i, seg in enumerate(captions, start=1):
        start_tc = _seconds_to_srt_time(seg.get("start_time", 0))
        end_tc   = _seconds_to_srt_time(seg.get("end_time", 0))
        text     = seg.get("text", "").strip()
        if not text:
            continue
        lines.append(str(i))
        lines.append(f"{start_tc} --> {end_tc}")
        lines.append(text)
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.debug("SRT: {} caption block(s) written", len(captions))


def _seconds_to_srt_time(seconds: float) -> str:
    """Convert float seconds to SRT timecode: HH:MM:SS,mmm"""
    seconds = max(0.0, seconds)
    total_ms  = int(round(seconds * 1000))
    ms  = total_ms % 1000
    s   = (total_ms // 1000) % 60
    m   = (total_ms // 60_000) % 60
    h   = total_ms // 3_600_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------------------------------------------------------------------
# Resolve import
# ---------------------------------------------------------------------------

def _import_srt_into_timeline(resolve_ctrl, timeline, srt_path: str):
    """
    Attempt to import the SRT as a subtitle track in the Resolve timeline.

    DaVinci Resolve 18+ supports subtitle import via:
        timeline.ImportIntoTimeline(file_path, options_dict)

    If this API is unavailable (older Resolve), we log a clear manual instruction
    so the user knows what to do.
    """
    logger.info("Importing SRT into timeline '{}' …", timeline.GetName())

    try:
        # Resolve 18.5+ API
        ok = timeline.ImportIntoTimeline(srt_path, {})
        if ok:
            logger.info("SRT imported successfully into subtitle track")
            return
        logger.warning("ImportIntoTimeline returned False — check Resolve version")
    except AttributeError:
        logger.warning(
            "timeline.ImportIntoTimeline not available in this Resolve version.\n"
            "  Manual import: Edit page -> File -> Import -> Subtitles -> select:\n"
            "  {}", srt_path,
        )
    except Exception as e:
        logger.error("SRT import error: {}", e)

    logger.info(
        "SRT is at '{}' — import manually via File -> Import -> Subtitles",
        srt_path,
    )
