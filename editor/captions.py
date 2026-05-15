"""
captions.py
-----------
Low-level caption primitives — delegates to caption_renderer for the full pipeline.
Kept as a thin compatibility layer for callers that use the original interface.
"""

from editor.caption_renderer import render_captions, write_srt_only, _seconds_to_srt_time
from utils.logger import get_logger

logger = get_logger(__name__)


def add_caption(resolve_ctrl, timeline, text: str, start_time: float, duration: float,
                output_dir: str = None):
    """
    Add a single caption to the timeline.

    For single captions, builds a minimal blueprint-compatible dict and delegates
    to the caption_renderer pipeline (SRT -> import).
    """
    logger.info("Adding caption '{}' at {:.2f}s for {:.2f}s", text, start_time, duration)

    mini_blueprint = {
        "captions": [{
            "index":      0,
            "start_time": start_time,
            "end_time":   start_time + duration,
            "text":       text,
            "confidence": 1.0,
            "words":      [],
        }]
    }
    return render_captions(
        resolve_ctrl=resolve_ctrl,
        timeline=timeline,
        blueprint=mini_blueprint,
        output_dir=output_dir,
    )
