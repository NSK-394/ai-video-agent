"""
impact_detector.py
Analyses blueprint beat data to find and classify music impact moments.
"""

from dataclasses import dataclass, field
from typing import List

from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ImpactMarker:
    beat_idx: int
    time_secs: float
    frame: int              # at blueprint fps
    strength: float         # 0-1 normalised
    impact_type: str        # "major" | "drop" | "buildup" | "impact" | "minor"


@dataclass
class ImpactTimeline:
    markers: List[ImpactMarker] = field(default_factory=list)
    drops: List[ImpactMarker] = field(default_factory=list)
    buildups: List[ImpactMarker] = field(default_factory=list)
    strongest: List[ImpactMarker] = field(default_factory=list)

    def markers_in_window(
        self, start_secs: float, end_secs: float
    ) -> List[ImpactMarker]:
        """Return markers whose time_secs falls within [start_secs, end_secs]."""
        return [m for m in self.markers if start_secs <= m.time_secs <= end_secs]

    def strongest_in_window(
        self, start_secs: float, end_secs: float, n: int = 1
    ) -> List[ImpactMarker]:
        """Return top-N strongest markers in window, sorted by strength desc."""
        window = self.markers_in_window(start_secs, end_secs)
        return sorted(window, key=lambda m: m.strength, reverse=True)[:n]


# ---------------------------------------------------------------------------
# Strength constants
# ---------------------------------------------------------------------------

_STRENGTH = {
    "impact":  1.00,
    "drop":    1.00,
    "major":   0.85,
    "buildup": 0.60,
    "minor":   0.30,
}


# ---------------------------------------------------------------------------
# Main detector
# ---------------------------------------------------------------------------

def detect_impacts(
    blueprint: dict,
    fps: float = 30.0,
    top_n: int = 10,
) -> ImpactTimeline:
    """
    Analyse beat data in blueprint to classify each beat and return an ImpactTimeline.

    Algorithm
    ---------
    1. Extract beat times from blueprint["beats"][i]["time"].
    2. Compute inter-beat intervals (IBI): IBI[i] = time[i+1] - time[i].
    3. Rolling 4-beat average IBI.
    4. Drop    : IBI[i] < rolling_avg[i] * 0.75  (sudden speedup).
    5. Buildup : IBI[i] > rolling_avg[i] * 1.20  (slowing before drop).
    6. Major   : beat index % 4 == 0.
    7. Impact  : beat is both major AND follows a buildup beat (strength = 1.0).
    8. Strength mapping: impact=1.0, drop=1.0, major=0.85, buildup=0.60, minor=0.30.

    Parameters
    ----------
    blueprint : dict with a "beats" list; each beat must have a "time" key (seconds).
    fps       : frames-per-second used to compute the frame field.
    top_n     : number of markers kept in ImpactTimeline.strongest.

    Returns
    -------
    ImpactTimeline (all lists empty if no beats found in blueprint).
    """
    beats_raw: list = []
    if isinstance(blueprint, dict):
        beats_raw = blueprint.get("beats", []) or []
        fps = float(blueprint.get("fps", fps))

    # Filter valid beat entries
    beat_times = []
    for b in beats_raw:
        if isinstance(b, dict) and "time" in b:
            try:
                beat_times.append(float(b["time"]))
            except (TypeError, ValueError):
                pass

    n_beats = len(beat_times)

    if n_beats == 0:
        logger.info("ImpactDetector: 0 beats | drops=0 buildups=0 major=0")
        return ImpactTimeline()

    # ------------------------------------------------------------------
    # Inter-beat intervals (IBI)
    # IBI has length n_beats-1; IBI[i] corresponds to the gap AFTER beat i.
    # For the last beat there is no IBI — treat it as minor unless major.
    # ------------------------------------------------------------------
    ibi: List[float] = [
        beat_times[i + 1] - beat_times[i] for i in range(n_beats - 1)
    ]

    # Rolling 4-beat average IBI centered on current index
    def _rolling_avg(idx: int) -> float:
        window = ibi[max(0, idx - 3): idx + 1]
        return sum(window) / len(window) if window else 1.0

    # ------------------------------------------------------------------
    # Classify each beat
    # ------------------------------------------------------------------
    markers: List[ImpactMarker] = []
    prev_is_buildup = False

    for i, t in enumerate(beat_times):
        is_major = (i % 4 == 0)

        # IBI-based classification (only available for beats 0..n-2)
        is_drop = False
        is_buildup = False

        if i < len(ibi):
            avg = _rolling_avg(i)
            if avg > 0:
                ratio = ibi[i] / avg
                if ratio < 0.75:
                    is_drop = True
                elif ratio > 1.20:
                    is_buildup = True

        # Impact: major beat that follows a buildup
        is_impact = is_major and prev_is_buildup

        # Determine type and strength (priority: impact > drop > major > buildup > minor)
        if is_impact:
            impact_type = "impact"
        elif is_drop:
            impact_type = "drop"
        elif is_major:
            impact_type = "major"
        elif is_buildup:
            impact_type = "buildup"
        else:
            impact_type = "minor"

        strength = _STRENGTH[impact_type]
        frame = int(round(t * fps))

        markers.append(ImpactMarker(
            beat_idx=i,
            time_secs=t,
            frame=frame,
            strength=strength,
            impact_type=impact_type,
        ))

        prev_is_buildup = is_buildup

    # ------------------------------------------------------------------
    # Categorise into sublists
    # ------------------------------------------------------------------
    drops = [m for m in markers if m.impact_type == "drop"]
    buildups = [m for m in markers if m.impact_type == "buildup"]
    major_count = sum(1 for m in markers if m.impact_type in ("major", "impact"))

    strongest = sorted(markers, key=lambda m: m.strength, reverse=True)[:top_n]

    logger.info(
        "ImpactDetector: {} beats | drops={} buildups={} major={}",
        n_beats,
        len(drops),
        len(buildups),
        major_count,
    )

    return ImpactTimeline(
        markers=markers,
        drops=drops,
        buildups=buildups,
        strongest=strongest,
    )
