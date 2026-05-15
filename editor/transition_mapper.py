"""
transition_mapper.py
--------------------
Applies transitions between consecutive timeline clips.

Transition types:
  "cut"           — hard cut, no extra action needed (default)
  "dissolve"      — cross dissolve via TimelineItem API
  "fade_to_black" — dissolve through black via property setting

The Resolve scripting API for transitions is available in Resolve 18+.
For older versions, all transitions fall back gracefully to hard cuts.

The mapper operates on TimelineItems returned by timeline_builder.build_timeline().
"""

from editor.timeline import item_name
from utils.logger import get_logger

logger = get_logger(__name__)

# Resolve transition identifiers (as expected by the API)
_TRANSITION_MAP = {
    "dissolve":      "Cross Dissolve",
    "cross_dissolve":"Cross Dissolve",
    "fade_to_black": "Fade To Color",
    "dip_to_white":  "Dip To Color",
}

# Default dissolve duration in frames
_DEFAULT_DISSOLVE_FRAMES = 15


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_transitions(
    resolve_ctrl,
    timeline,
    timeline_items: list,
    edit_plan=None,
    default_transition: str = "cut",
    dissolve_frames: int = _DEFAULT_DISSOLVE_FRAMES,
) -> list:
    """
    Walk consecutive timeline item pairs and apply the requested transition.

    Args:
        resolve_ctrl:       Connected ResolveController.
        timeline:           The Resolve Timeline object.
        timeline_items:     Ordered list of TimelineItems from timeline_builder.
        edit_plan:          Optional EditPlan (used to read per-slot transition hints).
        default_transition: Transition type for all slots unless overridden per-slot.
        dissolve_frames:    Cross-dissolve duration in frames.

    Returns:
        Same list of timeline_items (unchanged; transitions mutate clips in-place in Resolve).
    """
    if len(timeline_items) < 2:
        logger.info("Fewer than 2 clips — no transitions to apply")
        return timeline_items

    slot_map = {}
    if edit_plan:
        slot_map = {i: s for i, s in enumerate(edit_plan.slots)}

    applied = 0
    for i in range(len(timeline_items) - 1):
        item_out = timeline_items[i]
        item_in  = timeline_items[i + 1]

        # Determine which transition type to use
        tr_type = default_transition
        if i in slot_map:
            tr_type = slot_map[i].transition_out or default_transition

        if tr_type == "cut":
            logger.debug("Pair {}-{}: hard cut (no action)", i, i + 1)
            continue

        success = _apply_single_transition(
            timeline, item_out, item_in, tr_type, dissolve_frames
        )
        if success:
            applied += 1

    logger.info(
        "Transitions applied: {}/{} pairs (type='{}')",
        applied, len(timeline_items) - 1, default_transition,
    )
    return timeline_items


def set_slot_transitions(edit_plan, style: str = "cut"):
    """
    Set all slot transition types to `style` in-place.
    Convenience helper for callers that want a uniform transition across the edit.
    """
    for slot in edit_plan.slots:
        slot.transition_in  = style
        slot.transition_out = style
    logger.debug("All slots set to transition_out='{}'", style)
    return edit_plan


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _apply_single_transition(timeline, item_out, item_in, tr_type: str,
                              dissolve_frames: int) -> bool:
    resolve_name = _TRANSITION_MAP.get(tr_type)
    if not resolve_name:
        logger.warning("Unknown transition '{}' — treating as hard cut", tr_type)
        return False

    try:
        # Resolve 18+ API: timeline.AddTransition(type, item, duration, position)
        # position 0 = end of item_out / start of item_in
        ok = timeline.AddTransition(resolve_name, item_out, dissolve_frames, 0)
        if ok:
            logger.debug(
                "'{}' transition [{} frames] between '{}' -> '{}'",
                resolve_name, dissolve_frames,
                item_name(item_out), item_name(item_in),
            )
            return True

        logger.warning(
            "AddTransition returned False for '{}' -> '{}'",
            item_name(item_out), item_name(item_in),
        )
        return False

    except AttributeError:
        logger.warning(
            "timeline.AddTransition not available in this Resolve version — "
            "falling back to hard cut between '{}' and '{}'",
            item_name(item_out), item_name(item_in),
        )
        return False
    except Exception as e:
        logger.error(
            "Transition error between '{}' and '{}': {}",
            item_name(item_out), item_name(item_in), e,
        )
        return False
