"""
effect_engine.py
----------------
Orchestrates all cinematic effects for a generated edit.

Coordinates:
  - visual_energy_mapper  -> per-slot energy levels
  - impact_detector       -> music impact markers
  - camera_animation      -> zoom / pan directives
  - motion_effects        -> speed ramps, flash frames
  - transition_effects    -> beat/energy-aware transition planning

Presets:
  subtle      — gentle zoom, soft dissolves, minimal speed change
  cinematic   — moderate zoom, dip-to-black on drops, slow-mo on calm
  aggressive  — hard cuts everywhere, speed ramps, max zoom
  anime       — dip-to-white on drops, high zoom, fast/slow extremes
  gaming      — hard cuts, speed ramps, maximum energy
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List
from utils.logger import get_logger
from editor.visual_energy_mapper import build_energy_map, EnergyMap
from editor.impact_detector import detect_impacts, ImpactTimeline
from editor.camera_animation import plan_camera_moves, apply_camera_moves
from editor.motion_effects import plan_motion_effects, apply_motion_effects
from editor.transition_effects import plan_transitions, apply_transition_decisions

logger = get_logger(__name__)

VALID_PRESETS = {"subtle", "cinematic", "aggressive", "anime", "gaming"}
DEFAULT_PRESET = "cinematic"

# Effect cooldown in slots — prevents spamming the same effect back to back
_EFFECT_COOLDOWN = {
    "subtle":     3,
    "cinematic":  2,
    "aggressive": 1,
    "anime":      2,
    "gaming":     1,
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class EffectSummary:
    """Returned by apply_all_effects — used in quality_report.json."""
    preset: str
    camera_applied:    int = 0
    camera_skipped:    int = 0
    speed_applied:     int = 0
    flash_planned:     int = 0
    transitions_applied: int = 0
    transitions_skipped: int = 0
    energy_map_peaks:  int = 0
    energy_map_drops:  int = 0
    impact_markers:    int = 0
    elapsed_secs:      float = 0.0
    errors:            List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "preset":               self.preset,
            "camera_applied":       self.camera_applied,
            "camera_skipped":       self.camera_skipped,
            "speed_applied":        self.speed_applied,
            "flash_planned":        self.flash_planned,
            "transitions_applied":  self.transitions_applied,
            "transitions_skipped":  self.transitions_skipped,
            "energy_peaks":         self.energy_map_peaks,
            "energy_drops":         self.energy_map_drops,
            "impact_markers":       self.impact_markers,
            "elapsed_secs":         round(self.elapsed_secs, 2),
            "errors":               self.errors,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_and_apply_effects(
    resolve_ctrl,
    timeline,
    timeline_items: list,
    plan,                           # EditPlan
    blueprint: dict,
    pacing_curve: list,
    beat_categories: dict = None,
    semantic_analyses: dict = None,
    preset: str = DEFAULT_PRESET,
    hook_count: int = 2,
    skip_camera: bool = False,
    skip_motion: bool = False,
    skip_smart_transitions: bool = False,
) -> EffectSummary:
    """
    Run the full effect pipeline for a completed Resolve timeline.

    Steps:
      1. Build EnergyMap (per-slot combined energy)
      2. Detect impact markers from blueprint beats
      3. Plan + apply camera moves (zoom / pan)
      4. Plan + apply motion effects (speed ramps, flash frames)
      5. Plan + apply smart transitions

    Args:
        resolve_ctrl:           Connected ResolveController.
        timeline:               Resolve Timeline object.
        timeline_items:         Placed TimelineItem list from timeline_builder.
        plan:                   EditPlan (has .slots, .fps, .edit_style).
        blueprint:              Parsed blueprint.json dict.
        pacing_curve:           Per-slot energy floats from build_pacing_curve().
        beat_categories:        From categorize_beats() — optional.
        semantic_analyses:      {clip_path: [SemanticProfile]} — optional.
        preset:                 Effect intensity preset name.
        hook_count:             First N slots are "hook" (high-energy bias).
        skip_camera:            Skip zoom/pan effects.
        skip_motion:            Skip speed ramps and flash frames.
        skip_smart_transitions: Skip transition planning (use existing transitions).

    Returns:
        EffectSummary with counts of applied/planned/skipped effects.
    """
    t_start = time.perf_counter()
    preset  = preset if preset in VALID_PRESETS else DEFAULT_PRESET
    summary = EffectSummary(preset=preset)

    logger.info("Effect engine START | preset={} | {} items | {} slots",
                preset, len(timeline_items), plan.total_slots if plan else 0)

    if not timeline_items or not plan or plan.total_slots == 0:
        logger.warning("Effect engine: no timeline items or empty plan — skipping all effects")
        return summary

    fps = plan.fps

    # ------------------------------------------------------------------
    # Step 1: Build energy map
    # ------------------------------------------------------------------
    logger.info("[E1] Building energy map ...")
    try:
        energy_map: EnergyMap = build_energy_map(
            plan=plan,
            blueprint=blueprint,
            pacing_curve=pacing_curve,
            semantic_analyses=semantic_analyses,
            beat_categories=beat_categories,
        )
        summary.energy_map_peaks = len(energy_map.peak_slots)
        summary.energy_map_drops = len(energy_map.drop_slots)
        logger.info("  EnergyMap: peaks={} drops={} calms={}",
                    len(energy_map.peak_slots),
                    len(energy_map.drop_slots),
                    len(energy_map.calm_slots))
    except Exception as e:
        logger.error("Energy map failed: {} — effects will use neutral energy", e)
        summary.errors.append(f"energy_map: {e}")
        from editor.visual_energy_mapper import EnergyMap
        energy_map = EnergyMap(points=[], peak_slots=[], calm_slots=[], drop_slots=[])

    # ------------------------------------------------------------------
    # Step 2: Detect impact markers
    # ------------------------------------------------------------------
    logger.info("[E2] Detecting impact markers ...")
    try:
        impact_timeline: ImpactTimeline = detect_impacts(blueprint, fps=fps)
        summary.impact_markers = len(impact_timeline.markers)
        logger.info("  ImpactTimeline: {} markers | drops={} buildups={} strongest={}",
                    len(impact_timeline.markers),
                    len(impact_timeline.drops),
                    len(impact_timeline.buildups),
                    len(impact_timeline.strongest))
    except Exception as e:
        logger.error("Impact detection failed: {} — effects will skip impact triggers", e)
        summary.errors.append(f"impact_detector: {e}")
        from editor.impact_detector import ImpactTimeline
        impact_timeline = ImpactTimeline(markers=[], drops=[], buildups=[], strongest=[])

    # ------------------------------------------------------------------
    # Step 3: Camera animation
    # ------------------------------------------------------------------
    if not skip_camera:
        logger.info("[E3] Planning camera moves (preset={}) ...", preset)
        try:
            cam_directives = plan_camera_moves(plan, energy_map, preset, hook_count)
            logger.info("  Camera directives: {}", len(cam_directives))

            cam_result = apply_camera_moves(timeline_items, cam_directives)
            summary.camera_applied  = cam_result.get("applied", 0)
            summary.camera_skipped  = cam_result.get("skipped", 0)
            summary.errors.extend(cam_result.get("errors", []))
            logger.info("  Camera: applied={} skipped={}",
                        summary.camera_applied, summary.camera_skipped)
        except Exception as e:
            logger.error("Camera animation failed: {}", e)
            summary.errors.append(f"camera: {e}")
    else:
        logger.info("[E3] Camera animation skipped")

    # ------------------------------------------------------------------
    # Step 4: Motion effects (speed ramps, flash frames)
    # ------------------------------------------------------------------
    if not skip_motion:
        logger.info("[E4] Planning motion effects (preset={}) ...", preset)
        try:
            cooldown = _EFFECT_COOLDOWN.get(preset, 2)
            motion_directives = plan_motion_effects(
                plan, energy_map, impact_timeline, preset, cooldown
            )
            logger.info("  Motion directives: {}", len(motion_directives))

            motion_result = apply_motion_effects(
                resolve_ctrl, timeline, timeline_items, motion_directives, fps
            )
            summary.speed_applied  = motion_result.get("speed_applied", 0)
            summary.flash_planned  = motion_result.get("flash_planned", 0)
            logger.info("  Motion: speed_applied={} flash_planned={}",
                        summary.speed_applied, summary.flash_planned)
        except Exception as e:
            logger.error("Motion effects failed: {}", e)
            summary.errors.append(f"motion: {e}")
    else:
        logger.info("[E4] Motion effects skipped")

    # ------------------------------------------------------------------
    # Step 5: Smart transitions
    # ------------------------------------------------------------------
    if not skip_smart_transitions and len(timeline_items) >= 2:
        logger.info("[E5] Planning smart transitions (preset={}) ...", preset)
        try:
            trans_decisions = plan_transitions(
                plan, energy_map, impact_timeline,
                default_transition="cut",
                preset=preset,
            )
            logger.info("  Transition decisions: {}", len(trans_decisions))

            trans_result = apply_transition_decisions(
                resolve_ctrl, timeline, timeline_items, trans_decisions
            )
            summary.transitions_applied = trans_result.get("applied", 0)
            summary.transitions_skipped = trans_result.get("skipped_cuts", 0)
            logger.info("  Transitions: applied={} cuts_skipped={}",
                        summary.transitions_applied, summary.transitions_skipped)
        except Exception as e:
            logger.error("Smart transitions failed: {}", e)
            summary.errors.append(f"transitions: {e}")
    else:
        logger.info("[E5] Smart transitions skipped")

    # ------------------------------------------------------------------
    # Done
    # ------------------------------------------------------------------
    summary.elapsed_secs = time.perf_counter() - t_start
    logger.info(
        "Effect engine DONE in {:.1f}s | cam={}/{} speed={} flash={} trans={}",
        summary.elapsed_secs,
        summary.camera_applied, summary.camera_applied + summary.camera_skipped,
        summary.speed_applied, summary.flash_planned,
        summary.transitions_applied,
    )
    return summary
