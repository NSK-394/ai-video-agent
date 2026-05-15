"""
diversity_manager.py
--------------------
Tracks clip usage history and applies diversity penalties to prevent
repetitive reuse of the same footage across edit slots.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ClipUsageRecord:
    """Tracks how often and where a single clip has been used."""

    times_used: int = 0
    last_used_slot: int = -99
    used_windows: List[Tuple[float, float]] = field(default_factory=list)
    # used_windows: list of (start_sec, end_sec) previously assigned segments


class DiversityMemory:
    """
    Maintains per-clip usage history and computes diversity penalty multipliers.

    All penalty multipliers are in the range [0.01, 1.0].
    A value of 1.0 means no penalty; lower values reduce effective clip score.

    Constructor parameters (all have defaults):
        cooldown_slots          – number of slots before the same clip can
                                  win freely again after being used.
        min_temporal_gap_secs   – minimum time gap (seconds) required between
                                  reused segments of the same clip.
        frequency_decay         – per-use multiplier to discourage over-used
                                  clips  (penalty = frequency_decay ^ times_used).
        consecutive_penalty     – additional multiplier applied when the same
                                  clip would occupy back-to-back slots.
        temporal_proximity_penalty – multiplier applied when a new segment
                                  overlaps or sits too close to an existing
                                  used window of that clip.
    """

    def __init__(
        self,
        cooldown_slots: int = 2,
        min_temporal_gap_secs: float = 2.0,
        frequency_decay: float = 0.4,
        consecutive_penalty: float = 0.05,
        temporal_proximity_penalty: float = 0.3,
    ) -> None:
        self.cooldown_slots = cooldown_slots
        self.min_temporal_gap_secs = min_temporal_gap_secs
        self.frequency_decay = frequency_decay
        self.consecutive_penalty = consecutive_penalty
        self.temporal_proximity_penalty = temporal_proximity_penalty

        # Internal state
        self._records: Dict[str, ClipUsageRecord] = {}
        self._last_slot_clip: str | None = None  # clip used in the previous slot

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def penalty(self, clip_path: str, segment: dict, current_slot: int) -> float:
        """
        Return a multiplier in [0.01, 1.0] reflecting how heavily this
        clip/segment combination should be penalised given prior usage.

        Parameters
        ----------
        clip_path    : absolute or relative path identifying the clip.
        segment      : dict with keys ``start_time`` and ``end_time`` (seconds).
        current_slot : zero-based index of the slot being filled.

        Penalty sources (applied multiplicatively):
        - Consecutive reuse    : consecutive_penalty if same clip as prev slot
        - Cooldown             : linear ramp from 0.01 → 1.0 over cooldown_slots
        - Frequency decay      : frequency_decay ^ times_used
        - Temporal proximity   : temporal_proximity_penalty if gap < min_temporal_gap_secs
        - Window overlap       : 0.02 if the segment overlaps a previous window
        """
        record = self._records.get(clip_path)

        if record is None or record.times_used == 0:
            return 1.0  # never used → no penalty

        multiplier = 1.0

        seg_start: float = segment.get("start_time", 0.0)
        seg_end: float = segment.get("end_time", seg_start + 1.0)

        # 1. Consecutive-slot penalty
        if clip_path == self._last_slot_clip:
            multiplier *= self.consecutive_penalty
            logger.info(
                "diversity: consecutive penalty applied to {}: x{}",
                os.path.basename(clip_path),
                self.consecutive_penalty,
            )

        # 2. Cooldown penalty – linear interpolation from 0.01 at 0 slots
        #    elapsed to 1.0 at cooldown_slots elapsed.
        slots_elapsed = current_slot - record.last_used_slot
        if slots_elapsed < self.cooldown_slots:
            cooldown_factor = max(0.01, slots_elapsed / max(1, self.cooldown_slots))
            multiplier *= cooldown_factor
            logger.info(
                "diversity: cooldown penalty for {}: slots_elapsed={} factor={:.3f}",
                os.path.basename(clip_path),
                slots_elapsed,
                cooldown_factor,
            )

        # 3. Frequency-decay penalty
        freq_factor = self.frequency_decay ** record.times_used
        multiplier *= freq_factor
        logger.info(
            "diversity: frequency decay for {} (used {} times): x{:.4f}",
            os.path.basename(clip_path),
            record.times_used,
            freq_factor,
        )

        # 4. Temporal-proximity / overlap check against all used windows
        for win_start, win_end in record.used_windows:
            # Check for direct overlap first
            if seg_start < win_end and seg_end > win_start:
                multiplier *= 0.02
                logger.info(
                    "diversity: window overlap penalty for {}: new=[{}, {}] existing=[{}, {}]",
                    os.path.basename(clip_path),
                    seg_start,
                    seg_end,
                    win_start,
                    win_end,
                )
                break  # worst case already applied

            # Check temporal proximity (gap between segments)
            gap = max(win_start - seg_end, seg_start - win_end)
            if gap < self.min_temporal_gap_secs:
                multiplier *= self.temporal_proximity_penalty
                logger.info(
                    "diversity: proximity penalty for {}: gap={:.2f}s < {:.2f}s",
                    os.path.basename(clip_path),
                    gap,
                    self.min_temporal_gap_secs,
                )
                break

        # Clamp to valid range
        return max(0.01, min(1.0, multiplier))

    def record_use(self, clip_path: str, segment: dict, slot_index: int) -> None:
        """
        Register that *clip_path* was assigned for *segment* at *slot_index*.

        Parameters
        ----------
        clip_path  : path identifying the clip (same key used in ``penalty``).
        segment    : dict with ``start_time`` and ``end_time``.
        slot_index : zero-based slot that received this clip.
        """
        if clip_path not in self._records:
            self._records[clip_path] = ClipUsageRecord()

        record = self._records[clip_path]
        record.times_used += 1
        record.last_used_slot = slot_index
        record.used_windows.append(
            (segment.get("start_time", 0.0), segment.get("end_time", 0.0))
        )

        self._last_slot_clip = clip_path

        logger.info(
            "diversity: recorded use of {} at slot {} (total uses: {})",
            os.path.basename(clip_path),
            slot_index,
            record.times_used,
        )

    def usage_summary(self) -> dict:
        """
        Return a lightweight summary of clip usage.

        Returns
        -------
        dict
            ``{basename: {"times_used": int, "windows_count": int}}``
        """
        return {
            os.path.basename(path): {
                "times_used": rec.times_used,
                "windows_count": len(rec.used_windows),
            }
            for path, rec in self._records.items()
        }

    def reset(self) -> None:
        """Clear all usage history (useful between independent edit sessions)."""
        self._records.clear()
        self._last_slot_clip = None
        logger.info("diversity: usage history reset")
