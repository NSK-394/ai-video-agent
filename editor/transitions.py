"""
transitions.py
--------------
Low-level transition primitives. Delegates to transition_mapper for the full pipeline.
Kept as a compatibility layer for callers using the original interface.
"""

from editor.transition_mapper import apply_transitions, _apply_single_transition
from utils.logger import get_logger

logger = get_logger(__name__)


def apply_transition(resolve_ctrl, clip_in, clip_out,
                     transition_type: str = "Cross Dissolve",
                     duration_frames: int = 15):
    """
    Apply a single transition between two consecutive timeline items.
    clip_in / clip_out: TimelineItem objects in timeline order.
    """
    logger.info("Applying '{}' between '{}' -> '{}'",
                transition_type, clip_out.GetName(), clip_in.GetName())

    tl = resolve_ctrl.get_current_timeline()
    if not tl:
        logger.error("No active timeline — cannot apply transition")
        return False

    # Normalise caller-supplied name to internal key
    tr_key = transition_type.lower().replace(" ", "_")
    return _apply_single_transition(tl, clip_out, clip_in, tr_key, duration_frames)
