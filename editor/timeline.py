"""
timeline.py
-----------
Low-level timeline primitives used by timeline_builder.

These thin wrappers keep the raw Resolve API calls in one place so the
higher-level builder never touches resolve objects directly.
"""

from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Timeline creation
# ---------------------------------------------------------------------------

def create_timeline(resolve_ctrl, name: str):
    """
    Create an empty timeline in the current project's Media Pool.
    Returns the Timeline object, or raises RuntimeError on failure.
    """
    resolve_ctrl.require_connection()
    logger.info("Creating timeline '{}'", name)
    timeline = resolve_ctrl.media_pool.CreateEmptyTimeline(name)
    if not timeline:
        raise RuntimeError(f"CreateEmptyTimeline('{name}') returned None")
    logger.info("Timeline created: {}", timeline.GetName())
    return timeline


# ---------------------------------------------------------------------------
# Clip insertion
# ---------------------------------------------------------------------------

def append_clips(resolve_ctrl, clips_with_range: list) -> list:
    """
    Append clips to the current timeline.

    Args:
        resolve_ctrl:       Connected ResolveController.
        clips_with_range:   List of dicts:
                            {
                                "mediaPoolItem": MediaPoolItem,
                                "startFrame":    int,
                                "endFrame":      int,
                            }

    Returns:
        List of TimelineItem objects placed on the timeline.
    """
    resolve_ctrl.require_connection()

    if not clips_with_range:
        logger.warning("append_clips: empty clip list")
        return []

    logger.info("Appending {} clip(s) to timeline …", len(clips_with_range))
    result = resolve_ctrl.media_pool.AppendToTimeline(clips_with_range)

    if not result:
        logger.error("AppendToTimeline returned None — check in/out frame validity")
        return []

    logger.info("Placed {} timeline item(s)", len(result))
    return result


# ---------------------------------------------------------------------------
# Track inspection
# ---------------------------------------------------------------------------

def get_video_items(timeline, track_index: int = 1) -> list:
    """Return all TimelineItems on a video track (1-indexed)."""
    items = timeline.GetItemListInTrack("video", track_index) or []
    logger.debug("Track V{} has {} item(s)", track_index, len(items))
    return items


def get_audio_items(timeline, track_index: int = 1) -> list:
    """Return all TimelineItems on an audio track (1-indexed)."""
    items = timeline.GetItemListInTrack("audio", track_index) or []
    logger.debug("Track A{} has {} item(s)", track_index, len(items))
    return items


# ---------------------------------------------------------------------------
# Timeline item helpers
# ---------------------------------------------------------------------------

def item_name(item) -> str:
    try:
        return item.GetName()
    except Exception:
        return "<unknown>"


def item_start(item) -> int:
    """Start frame on the timeline (absolute)."""
    try:
        return int(item.GetStart())
    except Exception:
        return 0


def item_end(item) -> int:
    """End frame on the timeline (absolute)."""
    try:
        return int(item.GetEnd())
    except Exception:
        return 0


def item_duration(item) -> int:
    """Duration in timeline frames."""
    return item_end(item) - item_start(item)
