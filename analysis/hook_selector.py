"""
hook_selector.py
----------------
Simple module for hook-slot detection and scoring bias.

A "hook" is the opening section of an edit — the first few slots — where
high-energy footage is strongly preferred to capture viewer attention
immediately.

Constants
---------
DEFAULT_HOOK_SLOTS     : How many leading slots are classified as "hook".
HOOK_ENERGY_MULTIPLIER : Score boost applied to hook-slot candidates.
HOOK_MIN_ENERGY        : Minimum energy_score a segment must have to be
                         accepted at a hook slot (allows graceful fallback
                         when no qualifying clip is available).

Public functions
----------------
is_hook_slot          – predicate: is this slot in the hook region?
hook_score_multiplier – score multiplier for the given slot.
hook_min_energy       – minimum energy gate for the given slot.
"""

from __future__ import annotations

from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

DEFAULT_HOOK_SLOTS: int = 2
"""Number of leading slots treated as the hook region."""

HOOK_ENERGY_MULTIPLIER: float = 1.5
"""Score multiplier applied to candidates at hook slots."""

HOOK_MIN_ENERGY: float = 0.6
"""
Minimum ``energy_score`` required for a segment to qualify at hook slots.
Segments below this threshold are skipped at hook positions; the caller
should fall back to the best available clip when no segment qualifies.
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_hook_slot(
    slot_idx: int,
    total_slots: int,
    hook_count: int = DEFAULT_HOOK_SLOTS,
) -> bool:
    """
    Return ``True`` when *slot_idx* falls inside the hook region.

    The hook region consists of the first *hook_count* slots of the edit,
    provided the edit is long enough to have a meaningful hook.  For very
    short edits (total_slots <= hook_count) every slot is a hook slot.

    Parameters
    ----------
    slot_idx    : zero-based index of the slot to test.
    total_slots : total number of slots in the edit.
    hook_count  : size of the hook region (default ``DEFAULT_HOOK_SLOTS``).

    Returns
    -------
    bool
    """
    if total_slots <= 0 or hook_count <= 0:
        return False
    effective_hook = min(hook_count, total_slots)
    result = slot_idx < effective_hook
    logger.info(
        "hook_selector: slot={} total={} hook_count={} is_hook={}",
        slot_idx,
        total_slots,
        hook_count,
        result,
    )
    return result


def hook_score_multiplier(
    slot_idx: int,
    total_slots: int,
    hook_count: int = DEFAULT_HOOK_SLOTS,
) -> float:
    """
    Return the score multiplier to apply to a candidate at *slot_idx*.

    Hook slots receive ``HOOK_ENERGY_MULTIPLIER`` to bias selection toward
    high-energy footage.  All other slots receive ``1.0`` (no change).

    Parameters
    ----------
    slot_idx    : zero-based index of the slot.
    total_slots : total number of slots in the edit.
    hook_count  : size of the hook region (default ``DEFAULT_HOOK_SLOTS``).

    Returns
    -------
    float
        ``HOOK_ENERGY_MULTIPLIER`` for hook slots, ``1.0`` otherwise.
    """
    if is_hook_slot(slot_idx, total_slots, hook_count):
        logger.info(
            "hook_selector: applying hook multiplier {:.2f} at slot {}",
            HOOK_ENERGY_MULTIPLIER,
            slot_idx,
        )
        return HOOK_ENERGY_MULTIPLIER
    return 1.0


def hook_min_energy(
    slot_idx: int,
    total_slots: int,
    hook_count: int = DEFAULT_HOOK_SLOTS,
) -> float:
    """
    Return the minimum energy gate for a candidate at *slot_idx*.

    Hook slots enforce ``HOOK_MIN_ENERGY`` to prevent dull footage from
    opening the edit.  Non-hook slots have no minimum (returns ``0.0``).

    The caller is responsible for the fallback behaviour when no segment
    satisfies the gate — typically selecting the highest-energy available
    clip regardless of threshold.

    Parameters
    ----------
    slot_idx    : zero-based index of the slot.
    total_slots : total number of slots in the edit.
    hook_count  : size of the hook region (default ``DEFAULT_HOOK_SLOTS``).

    Returns
    -------
    float
        ``HOOK_MIN_ENERGY`` for hook slots, ``0.0`` otherwise.
    """
    if is_hook_slot(slot_idx, total_slots, hook_count):
        logger.info(
            "hook_selector: enforcing min_energy={:.2f} at hook slot {}",
            HOOK_MIN_ENERGY,
            slot_idx,
        )
        return HOOK_MIN_ENERGY
    return 0.0
