"""
editor/camera_animation.py

Applies zoom/pan/tilt camera moves to DaVinci Resolve timeline items.
Uses static SetProperty calls only — Resolve scripting does not support
per-frame keyframes.
"""

from dataclasses import dataclass
from utils.logger import get_logger

log = get_logger("camera_animation")

# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

PRESET_ZOOM = {
    "subtle":     {"zoom": 1.03, "pan": 0.01},
    "cinematic":  {"zoom": 1.06, "pan": 0.02},
    "aggressive": {"zoom": 1.12, "pan": 0.03},
    "anime":      {"zoom": 1.18, "pan": 0.02},
    "gaming":     {"zoom": 1.10, "pan": 0.03},
}

_DEFAULT_PRESET = {"zoom": 1.06, "pan": 0.02}  # cinematic fallback


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CameraDirective:
    slot_idx: int
    zoom_x: float       # 1.0 = no zoom
    zoom_y: float
    pan_x: float        # 0.0 = center
    tilt_y: float
    rotation: float     # degrees; 0 = no rotation
    reason: str         # "hook_emphasis" | "beat_punch" | "drop_impact" | "cinematic_drift"


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def plan_camera_moves(
    plan,
    energy_map,
    preset: str = "cinematic",
    hook_count: int = 2,
) -> list:
    """
    Build a CameraDirective for every slot in plan.slots.

    Priority (highest → lowest):
        1. Hook slots (slot_idx < hook_count): max preset zoom, reason="hook_emphasis"
        2. Peak-energy slots: preset zoom * 1.05, reason="drop_impact"
        3. Beat-aligned slots: preset zoom * 1.02, reason="beat_punch"
        4. Calm slots (low energy, not beat-aligned): zoom=1.0, reason="cinematic_drift"
        5. Default: preset zoom, reason="cinematic_drift"

    Pan alternates sign per slot to simulate slow drift left/right.
    Returns list[CameraDirective].
    """
    cfg = PRESET_ZOOM.get(preset, _DEFAULT_PRESET)
    base_zoom = cfg["zoom"]
    base_pan = cfg["pan"]

    directives: list[CameraDirective] = []

    slots = getattr(plan, "slots", [])
    if not slots:
        log.warning("plan_camera_moves: plan.slots is empty — returning no directives")
        return directives

    for i, slot in enumerate(slots):
        slot_idx = getattr(slot, "slot_index", i)
        beat_aligned = getattr(slot, "beat_aligned", False)

        # Energy value for this slot (may be None / missing)
        energy = None
        try:
            energy = energy_map.get(slot_idx)
        except Exception as exc:
            log.warning("energy_map.get({}) failed: {}", slot_idx, exc)

        peak_energy = (energy is not None and energy.combined_energy > 0.7)
        calm = (energy is not None and energy.combined_energy < 0.3 and not beat_aligned)

        # Pan sign alternates per slot index
        pan_sign = 1.0 if (i % 2 == 0) else -1.0

        # ---- Choose zoom / reason based on priority ----
        if slot_idx < hook_count:
            zoom = base_zoom
            pan = base_pan * pan_sign
            reason = "hook_emphasis"
        elif peak_energy:
            zoom = base_zoom * 1.05
            pan = base_pan * pan_sign
            reason = "drop_impact"
        elif beat_aligned:
            zoom = base_zoom * 1.02
            pan = base_pan * pan_sign
            reason = "beat_punch"
        elif calm:
            zoom = 1.0
            pan = 0.01 * pan_sign
            reason = "cinematic_drift"
        else:
            zoom = base_zoom
            pan = base_pan * pan_sign
            reason = "cinematic_drift"

        directives.append(CameraDirective(
            slot_idx=slot_idx,
            zoom_x=round(zoom, 4),
            zoom_y=round(zoom, 4),
            pan_x=round(pan, 4),
            tilt_y=0.0,
            rotation=0.0,
            reason=reason,
        ))
        log.debug(
            "Planned camera [{}/{}] slot={} zoom={:.3f} pan={:.3f} reason={}",
            i + 1, len(slots), slot_idx, zoom, pan, reason,
        )

    return directives


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def apply_camera_moves(timeline_items: list, directives: list) -> dict:
    """
    Apply each CameraDirective to the matching Resolve timeline item.

    Matching: timeline_items[directive.slot_idx]

    Returns:
        {
            "applied": int,
            "skipped": int,
            "errors": list[str],
        }
    """
    applied = 0
    skipped = 0
    errors: list[str] = []

    if not directives:
        log.warning("apply_camera_moves: no directives provided — nothing to do")
        return {"applied": 0, "skipped": 0, "errors": []}

    for directive in directives:
        idx = directive.slot_idx

        # ---- Bounds check ----
        try:
            item = timeline_items[idx]
        except IndexError:
            msg = f"slot_idx={idx} out of range (timeline_items has {len(timeline_items)} items)"
            log.warning("Skipping camera directive — {}", msg)
            errors.append(msg)
            skipped += 1
            continue

        if item is None:
            msg = f"slot_idx={idx}: timeline_items entry is None"
            log.warning("Skipping camera directive — {}", msg)
            errors.append(msg)
            skipped += 1
            continue

        # ---- Property map ----
        props = {
            "ZoomX":         directive.zoom_x,
            "ZoomY":         directive.zoom_y,
            "Pan":           directive.pan_x,
            "Tilt":          directive.tilt_y,
            "RotationAngle": directive.rotation,
        }

        slot_errors: list[str] = []
        for key, value in props.items():
            try:
                result = item.SetProperty(key, value)
                if result is False:
                    slot_errors.append(f"{key}=False")
            except AttributeError as exc:
                slot_errors.append(f"{key}: AttributeError({exc})")
            except Exception as exc:
                slot_errors.append(f"{key}: Exception({exc})")

        if slot_errors:
            msg = f"slot_idx={idx} partial failure: {'; '.join(slot_errors)}"
            log.warning("Camera apply issues — {}", msg)
            errors.append(msg)
            skipped += 1
        else:
            log.debug(
                "Applied camera move slot={} zoom=({},{}) pan={} reason={}",
                idx,
                directive.zoom_x, directive.zoom_y,
                directive.pan_x,
                directive.reason,
            )
            applied += 1

    log.debug(
        "apply_camera_moves complete — applied={} skipped={} errors={}",
        applied, skipped, len(errors),
    )
    return {"applied": applied, "skipped": skipped, "errors": errors}
