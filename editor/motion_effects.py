"""
editor/motion_effects.py

Speed ramps and flash frame planning for DaVinci Resolve timeline items.
Flash frames are logged as PLANNED because the Resolve scripting API
does not reliably expose solid-color generator insertion at arbitrary
positions — they are recorded for manual finishing.
"""

from dataclasses import dataclass, field
from enum import Enum
from utils.logger import get_logger

log = get_logger("motion_effects")

# ---------------------------------------------------------------------------
# Enums & presets
# ---------------------------------------------------------------------------

class MotionEffectType(str, Enum):
    SPEED_RAMP  = "speed_ramp"
    FLASH_FRAME = "flash_frame"
    SLOW_MOTION = "slow_motion"


PRESET_SPEED = {
    "subtle":     {"ramp_speed": 110.0, "slow_speed": 85.0,  "flash_frames": 2},
    "cinematic":  {"ramp_speed": 130.0, "slow_speed": 75.0,  "flash_frames": 2},
    "aggressive": {"ramp_speed": 200.0, "slow_speed": 50.0,  "flash_frames": 3},
    "anime":      {"ramp_speed": 250.0, "slow_speed": 30.0,  "flash_frames": 3},
    "gaming":     {"ramp_speed": 180.0, "slow_speed": 60.0,  "flash_frames": 2},
}

_DEFAULT_PRESET = PRESET_SPEED["cinematic"]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class MotionDirective:
    slot_idx: int
    effect_type: MotionEffectType
    params: dict        # {"speed": float} or {"duration_frames": int, "color": str}
    trigger: str        # "drop" | "hook" | "beat_hit" | "calm"
    priority: int       # higher = more important; used for cooldown skipping


# ---------------------------------------------------------------------------
# Planning helpers
# ---------------------------------------------------------------------------

def _is_drop_slot(slot_idx: int, energy_map) -> bool:
    try:
        drop_slots = getattr(energy_map, "drop_slots", [])
        return slot_idx in drop_slots
    except Exception:
        return False


def _energy(slot_idx: int, energy_map) -> float:
    try:
        val = energy_map.get(slot_idx)
        return float(val) if val is not None else 0.5
    except Exception:
        return 0.5


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def plan_motion_effects(
    plan,
    energy_map,
    impact_timeline,
    preset: str = "cinematic",
    cooldown_slots: int = 2,
) -> list:
    """
    Build MotionDirectives for each slot.

    Speed effect rules (one per slot, first match wins):
        - Drop slot              → SPEED_RAMP (drop/punch)
        - Hook slot (idx < 2)    → SPEED_RAMP (aggressive entry)
        - Peak energy (>0.7)     → SPEED_RAMP
        - Calm (energy < 0.3)    → SLOW_MOTION

    Cooldown: same MotionEffectType cannot appear in consecutive
    `cooldown_slots` slots; skip (lower-priority) if it would.

    Flash frames: added for the top 30% strongest impact markers
    whose timestamp falls within a slot's time window.
    At most 1 FLASH_FRAME per slot.

    Returns list[MotionDirective].
    """
    cfg = PRESET_SPEED.get(preset, _DEFAULT_PRESET)
    ramp_speed   = cfg["ramp_speed"]
    slow_speed   = cfg["slow_speed"]
    flash_frames = cfg["flash_frames"]

    slots = getattr(plan, "slots", [])
    fps   = getattr(plan, "fps", 30.0) or 30.0

    if not slots:
        log.warning("plan_motion_effects: plan.slots is empty — returning no directives")
        return []

    # ---- Gather & rank impact markers for flash planning ----
    impact_markers: list[tuple[float, float]] = []  # (time_secs, strength)
    try:
        raw_markers = getattr(impact_timeline, "markers", []) or []
        for m in raw_markers:
            t = getattr(m, "time_secs", None) or getattr(m, "time", None)
            s = getattr(m, "strength", 0.5)
            if t is not None:
                impact_markers.append((float(t), float(s)))
    except Exception as exc:
        log.warning("Could not read impact_timeline.markers: {}", exc)

    flash_threshold = 0.0
    if impact_markers:
        strengths = sorted([s for _, s in impact_markers], reverse=True)
        cutoff_idx = max(0, int(len(strengths) * 0.30) - 1)
        flash_threshold = strengths[cutoff_idx]

    # ---- Per-slot planning ----
    directives: list[MotionDirective] = []
    last_type_at: dict[MotionEffectType, int] = {}  # type → last slot_idx it was used

    for i, slot in enumerate(slots):
        slot_idx       = getattr(slot, "slot_index", i)
        beat_aligned   = getattr(slot, "beat_aligned", False)
        tl_start_frame = getattr(slot, "timeline_start_frame", None)
        tl_end_frame   = getattr(slot, "timeline_end_frame", None)

        nrg    = _energy(slot_idx, energy_map)
        is_drop = _is_drop_slot(slot_idx, energy_map)
        is_hook = (slot_idx < 2)
        is_peak = (nrg > 0.7 and not is_drop and not is_hook)
        is_calm = (nrg < 0.3 and not beat_aligned and not is_drop)

        # ---- Choose speed effect ----
        effect: MotionEffectType | None = None
        trigger = "default"
        speed_val = ramp_speed
        priority = 0

        if is_drop:
            effect, trigger, speed_val, priority = MotionEffectType.SPEED_RAMP, "drop", ramp_speed, 10
        elif is_hook:
            effect, trigger, speed_val, priority = MotionEffectType.SPEED_RAMP, "hook", ramp_speed, 9
        elif is_peak:
            effect, trigger, speed_val, priority = MotionEffectType.SPEED_RAMP, "beat_hit", ramp_speed, 7
        elif is_calm:
            effect, trigger, speed_val, priority = MotionEffectType.SLOW_MOTION, "calm", slow_speed, 5

        # ---- Cooldown check ----
        if effect is not None:
            last_used = last_type_at.get(effect, -999)
            if (slot_idx - last_used) <= cooldown_slots and priority <= 7:
                log.warning(
                    "Cooldown skip: {} at slot={} (last used at {})",
                    effect.value, slot_idx, last_used,
                )
                effect = None
            else:
                last_type_at[effect] = slot_idx

        if effect is not None:
            directives.append(MotionDirective(
                slot_idx=slot_idx,
                effect_type=effect,
                params={"speed": speed_val},
                trigger=trigger,
                priority=priority,
            ))
            log.debug(
                "Planned {} slot={} speed={} trigger={}",
                effect.value, slot_idx, speed_val, trigger,
            )

        # ---- Flash frame planning within this slot's window ----
        if tl_start_frame is not None and tl_end_frame is not None and impact_markers:
            t_start = tl_start_frame / fps
            t_end   = tl_end_frame   / fps
            slot_flashes = [
                (t, s) for t, s in impact_markers
                if t_start <= t < t_end and s >= flash_threshold
            ]
            if slot_flashes:
                # Pick the strongest one in this window
                best_t, best_s = max(slot_flashes, key=lambda x: x[1])
                directives.append(MotionDirective(
                    slot_idx=slot_idx,
                    effect_type=MotionEffectType.FLASH_FRAME,
                    params={"duration_frames": flash_frames, "color": "white", "at_secs": best_t},
                    trigger="drop" if is_drop else "beat_hit",
                    priority=6,
                ))
                log.debug(
                    "Planned FLASH_FRAME slot={} at={:.2f}s strength={:.2f}",
                    slot_idx, best_t, best_s,
                )

    return directives


# ---------------------------------------------------------------------------
# Individual effect appliers
# ---------------------------------------------------------------------------

def apply_speed_ramp(timeline_item, speed_percent: float) -> bool:
    """
    Set clip playback speed via SetClipProperty("Speed", str(speed_percent)).
    Returns True on success, False on any failure.
    """
    try:
        result = timeline_item.SetClipProperty("Speed", str(float(speed_percent)))
        if result is False:
            log.warning("SetClipProperty('Speed', '{}') returned False", speed_percent)
            return False
        log.debug("Speed ramp applied: {}%", speed_percent)
        return True
    except AttributeError as exc:
        log.warning("apply_speed_ramp: AttributeError — {}", exc)
        return False
    except Exception as exc:
        log.warning("apply_speed_ramp: Exception — {}", exc)
        return False


def apply_flash_frame(
    resolve_ctrl,
    timeline,
    at_timeline_secs: float,
    fps: float = 30.0,
    duration_frames: int = 2,
    color: str = "white",
) -> bool:
    """
    Log the intended flash frame for manual finishing.

    Solid-color generator insertion at an arbitrary timeline position is not
    reliably achievable via the public Resolve scripting API without a
    pre-existing media pool generator clip.  The position is recorded so an
    editor can apply it manually or via a future API.

    Always returns False (effect is PLANNED, not applied).
    """
    log.warning(
        "Flash frame at {:.2f}s ({}f, color={}) — PLANNED (manual finishing required)",
        at_timeline_secs, duration_frames, color,
    )
    return False


# ---------------------------------------------------------------------------
# Batch application
# ---------------------------------------------------------------------------

def apply_motion_effects(
    resolve_ctrl,
    timeline,
    timeline_items: list,
    directives: list,
    fps: float = 30.0,
) -> dict:
    """
    Apply all MotionDirectives to Resolve timeline items.

    Returns:
        {
            "speed_applied":  int,
            "flash_planned":  int,
            "skipped":        int,
            "log":            list[str],
        }
    """
    speed_applied = 0
    flash_planned = 0
    skipped       = 0
    result_log: list[str] = []

    if not directives:
        log.warning("apply_motion_effects: no directives — nothing to do")
        return {"speed_applied": 0, "flash_planned": 0, "skipped": 0, "log": []}

    for directive in directives:
        idx = directive.slot_idx

        # Flash frames don't need a specific timeline_item
        if directive.effect_type == MotionEffectType.FLASH_FRAME:
            at_secs = directive.params.get("at_secs", 0.0)
            dur     = directive.params.get("duration_frames", 2)
            col     = directive.params.get("color", "white")
            apply_flash_frame(resolve_ctrl, timeline, at_secs, fps, dur, col)
            flash_planned += 1
            result_log.append(f"FLASH_FRAME planned slot={idx} at={at_secs:.2f}s")
            continue

        # Speed-based effects need a timeline item
        try:
            item = timeline_items[idx]
        except IndexError:
            msg = f"slot_idx={idx} out of range ({len(timeline_items)} items)"
            log.warning("Skipping motion directive — {}", msg)
            result_log.append(f"SKIPPED {directive.effect_type.value} slot={idx}: {msg}")
            skipped += 1
            continue

        if item is None:
            msg = f"slot_idx={idx}: timeline_items entry is None"
            log.warning("Skipping motion directive — {}", msg)
            result_log.append(f"SKIPPED {directive.effect_type.value} slot={idx}: {msg}")
            skipped += 1
            continue

        speed = directive.params.get("speed", 100.0)

        if directive.effect_type in (MotionEffectType.SPEED_RAMP, MotionEffectType.SLOW_MOTION):
            success = apply_speed_ramp(item, speed)
            if success:
                speed_applied += 1
                result_log.append(
                    f"{directive.effect_type.value} applied slot={idx} speed={speed}% trigger={directive.trigger}"
                )
            else:
                skipped += 1
                result_log.append(f"SKIPPED {directive.effect_type.value} slot={idx}: SetClipProperty failed")
        else:
            log.warning("Unknown MotionEffectType '{}' for slot={} — skipping", directive.effect_type, idx)
            skipped += 1

    log.debug(
        "apply_motion_effects complete — speed_applied={} flash_planned={} skipped={}",
        speed_applied, flash_planned, skipped,
    )
    return {
        "speed_applied": speed_applied,
        "flash_planned": flash_planned,
        "skipped":       skipped,
        "log":           result_log,
    }
