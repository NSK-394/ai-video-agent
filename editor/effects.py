"""
effects.py
----------
Visual effect helpers. Currently a stub with structured placeholders for
effects that require OFX plugins or Fusion compositions.

All functions log a warning if the Resolve API call is unavailable in the
current version, so the pipeline never crashes on missing effects.
"""

from utils.logger import get_logger

logger = get_logger(__name__)


def apply_effect(resolve_ctrl, clip_item, effect_name: str, params: dict = None):
    """
    Apply a named video effect to a TimelineItem.

    Args:
        resolve_ctrl: Connected ResolveController.
        clip_item:    TimelineItem to modify.
        effect_name:  Name as it appears in Resolve's effect library.
        params:       Optional dict of effect parameter overrides.

    Returns:
        True if the effect was applied, False otherwise.
    """
    params = params or {}
    logger.info("Applying effect '{}' to '{}'", effect_name, clip_item.GetName())

    try:
        ok = clip_item.AddVideoEffect(effect_name)
        if ok and params:
            _set_effect_params(clip_item, effect_name, params)
        return bool(ok)
    except AttributeError:
        logger.warning(
            "AddVideoEffect not available — '{}' skipped on '{}'",
            effect_name, clip_item.GetName(),
        )
        return False
    except Exception as e:
        logger.error("Effect error '{}' on '{}': {}", effect_name, clip_item.GetName(), e)
        return False


def apply_speed_change(clip_item, speed_percent: float) -> bool:
    """
    Change playback speed of a TimelineItem.
    speed_percent: 50.0 = half speed, 200.0 = double speed.
    """
    logger.info("Speed change: {}% on '{}'", speed_percent, clip_item.GetName())
    try:
        ok = clip_item.ChangeClipColor("Orange")  # visual marker; actual speed below
        clip_item.SetClipProperty("Speed", str(speed_percent))
        return True
    except Exception as e:
        logger.warning("Speed change failed: {}", e)
        return False


def _set_effect_params(clip_item, effect_name: str, params: dict):
    """Attempt to set named parameters on an applied effect."""
    try:
        for key, val in params.items():
            clip_item.SetProperty(key, val)
    except Exception as e:
        logger.warning("Could not set params for '{}': {}", effect_name, e)
