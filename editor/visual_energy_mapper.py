"""
visual_energy_mapper.py
Pure analysis module — no Resolve API.
Maps timeline energy at each edit slot, producing an EnergyMap.
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EnergyPoint:
    slot_idx: int
    position_ratio: float      # 0.0-1.0, slot position in full timeline
    beat_energy: float         # 0-1, beat density around this slot
    semantic_energy: float     # 0-1, mean energy_score from SemanticProfiles
    pacing_energy: float       # 0-1, from pacing curve
    combined_energy: float     # weighted: beat*0.4 + semantic*0.3 + pacing*0.3
    zone: str                  # "hook" | "build" | "drop" | "outro"
    is_peak: bool              # True if top 25% combined_energy
    is_calm: bool              # True if bottom 25% combined_energy


@dataclass
class EnergyMap:
    points: List[EnergyPoint] = field(default_factory=list)
    peak_slots: List[int] = field(default_factory=list)   # top 25% by combined_energy
    calm_slots: List[int] = field(default_factory=list)   # bottom 25% by combined_energy
    drop_slots: List[int] = field(default_factory=list)   # sudden energy increase >0.3

    def get(self, slot_idx: int) -> Optional[EnergyPoint]:
        """Return EnergyPoint for slot_idx, or None if not found."""
        for pt in self.points:
            if pt.slot_idx == slot_idx:
                return pt
        return None

    def energy_at(self, slot_idx: int) -> float:
        """Return combined_energy for slot_idx, or 0.5 if missing."""
        pt = self.get(slot_idx)
        return pt.combined_energy if pt is not None else 0.5


# ---------------------------------------------------------------------------
# Zone helper (mirrors semantic_score_engine.get_pacing_zone)
# ---------------------------------------------------------------------------

def _get_pacing_zone(position_ratio: float) -> str:
    """Return the pacing zone name based on normalised position in timeline."""
    if position_ratio < 0.15:
        return "hook"
    elif position_ratio < 0.60:
        return "build"
    elif position_ratio < 0.85:
        return "drop"
    else:
        return "outro"


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_energy_map(
    plan,
    blueprint: dict,
    pacing_curve: list,
    semantic_analyses: dict = None,
    beat_categories: dict = None,
) -> EnergyMap:
    """
    Build a per-slot EnergyMap from an EditPlan, blueprint, and auxiliary data.

    Parameters
    ----------
    plan             : EditPlan — must have a .slots iterable; each slot needs
                       .clip_path and optionally a duration in seconds.
    blueprint        : dict with at least a "beats" list; each beat has "time" (secs)
                       and an optional "duration".
    pacing_curve     : list[float] — one value per slot from build_pacing_curve().
    semantic_analyses: optional dict {clip_path: [SemanticProfile]} where each
                       SemanticProfile has an .energy_score attribute.
    beat_categories  : optional dict from categorize_beats() (not used directly
                       in energy computation but accepted for API consistency).

    Returns
    -------
    EnergyMap
    """
    slots = list(plan.slots) if plan and hasattr(plan, "slots") else []

    if not slots:
        logger.info("EnergyMap: 0 slots | peaks=0 drops=0 calms=0")
        return EnergyMap()

    total_slots = len(slots)
    beats: list = blueprint.get("beats", []) if isinstance(blueprint, dict) else []
    beat_times = [b["time"] for b in beats if isinstance(b, dict) and "time" in b]

    # ------------------------------------------------------------------
    # Estimate per-slot durations and cumulative timeline positions
    # ------------------------------------------------------------------
    # Try to get duration from slot directly; fallback to blueprint fps
    fps: float = float(blueprint.get("fps", 30.0)) if isinstance(blueprint, dict) else 30.0

    def _slot_duration(slot) -> float:
        for attr in ("duration", "duration_secs", "duration_seconds"):
            val = getattr(slot, attr, None)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
        # Fallback: assume 2-second slots
        return 2.0

    slot_durations = [_slot_duration(s) for s in slots]
    total_duration = sum(slot_durations) or 1.0

    # Cumulative start time for each slot
    cumulative = 0.0
    slot_starts = []
    for dur in slot_durations:
        slot_starts.append(cumulative)
        cumulative += dur

    # ------------------------------------------------------------------
    # Beat energy per slot: count beats within ±slot_duration window
    # ------------------------------------------------------------------
    beat_counts = []
    for i, slot in enumerate(slots):
        t_center = slot_starts[i] + slot_durations[i] / 2.0
        window = slot_durations[i]
        count = sum(
            1 for bt in beat_times
            if abs(bt - t_center) <= window
        )
        beat_counts.append(count)

    max_count = max(beat_counts) if beat_counts else 1
    if max_count == 0:
        max_count = 1
    beat_energies = [min(1.0, c / max_count) for c in beat_counts]

    # ------------------------------------------------------------------
    # Build EnergyPoints
    # ------------------------------------------------------------------
    points: List[EnergyPoint] = []

    for i, slot in enumerate(slots):
        position_ratio = slot_starts[i] / total_duration

        beat_energy = _clamp(beat_energies[i])

        # Semantic energy
        semantic_energy = 0.5
        if semantic_analyses is not None:
            clip_path = getattr(slot, "clip_path", None)
            profiles = semantic_analyses.get(clip_path, []) if clip_path else []
            if profiles:
                scores = []
                for p in profiles:
                    score = getattr(p, "energy_score", None)
                    if score is not None:
                        try:
                            scores.append(float(score))
                        except (TypeError, ValueError):
                            pass
                if scores:
                    semantic_energy = _clamp(sum(scores) / len(scores))

        # Pacing energy
        pacing_energy = 0.5
        if pacing_curve and i < len(pacing_curve):
            try:
                pacing_energy = _clamp(float(pacing_curve[i]))
            except (TypeError, ValueError):
                pass

        combined_energy = _clamp(
            beat_energy * 0.4
            + semantic_energy * 0.3
            + pacing_energy * 0.3
        )

        zone = _get_pacing_zone(position_ratio)

        points.append(EnergyPoint(
            slot_idx=i,
            position_ratio=position_ratio,
            beat_energy=beat_energy,
            semantic_energy=semantic_energy,
            pacing_energy=pacing_energy,
            combined_energy=combined_energy,
            zone=zone,
            is_peak=False,   # filled below
            is_calm=False,   # filled below
        ))

    # ------------------------------------------------------------------
    # Peak / calm classification (top/bottom 25%, minimum 1)
    # ------------------------------------------------------------------
    n_threshold = max(1, math.ceil(total_slots * 0.25))

    sorted_by_energy = sorted(points, key=lambda p: p.combined_energy, reverse=True)
    peak_set = {p.slot_idx for p in sorted_by_energy[:n_threshold]}
    calm_set = {p.slot_idx for p in sorted_by_energy[-n_threshold:]}

    for pt in points:
        pt.is_peak = pt.slot_idx in peak_set
        pt.is_calm = pt.slot_idx in calm_set

    # ------------------------------------------------------------------
    # Drop slots: combined_energy > prev combined_energy + 0.3
    # ------------------------------------------------------------------
    drop_slots: List[int] = []
    for i in range(1, len(points)):
        if points[i].combined_energy > points[i - 1].combined_energy + 0.3:
            drop_slots.append(i)

    energy_map = EnergyMap(
        points=points,
        peak_slots=sorted(peak_set),
        calm_slots=sorted(calm_set),
        drop_slots=drop_slots,
    )

    logger.info(
        "EnergyMap: {} slots | peaks={} drops={} calms={}",
        total_slots,
        len(peak_set),
        len(drop_slots),
        len(calm_set),
    )

    return energy_map


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, value))
