"""
editor/transition_effects.py

Smart per-slot transition planning with beat/energy awareness.

Generates TransitionDecision objects (type + duration) for each consecutive
slot pair.  These feed into the existing apply_transitions() pipeline via
_apply_single_transition from editor.transition_mapper.

Does NOT replace transition_mapper — it produces per-pair recommendations.
"""

from dataclasses import dataclass
from enum import Enum
from utils.logger import get_logger

log = get_logger("transition_effects")

# ---------------------------------------------------------------------------
# Enums & presets
# ---------------------------------------------------------------------------

class TransitionStyle(str, Enum):
    HARD_CUT   = "cut"
    DISSOLVE   = "dissolve"
    DIP_BLACK  = "fade_to_black"
    DIP_WHITE  = "dip_to_white"
    IMPACT_CUT = "cut"          # intentional hard cut on strong beat


PRESET_TRANSITIONS = {
    "subtle":     {"default": "dissolve",    "on_beat": "cut",         "on_drop": "dissolve"},
    "cinematic":  {"default": "dissolve",    "on_beat": "cut",         "on_drop": "fade_to_black"},
    "aggressive": {"default": "cut",         "on_beat": "cut",         "on_drop": "cut"},
    "anime":      {"default": "cut",         "on_beat": "cut",         "on_drop": "dip_to_white"},
    "gaming":     {"default": "cut",         "on_beat": "cut",         "on_drop": "cut"},
}

PRESET_DISSOLVE_FRAMES = {
    "subtle": 20, "cinematic": 15, "aggressive": 8, "anime": 6, "gaming": 8,
}

_HOOK_COUNT = 2  # first N slots are treated as "hook" slots


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TransitionDecision:
    slot_idx: int           # outgoing slot index (transition happens after this slot)
    transition_type: str    # key recognised by transition_mapper._TRANSITION_MAP
    duration_frames: int
    reason: str             # "beat_hit" | "drop" | "hook_exit" | "calm_bridge" | "default"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_drop_slot(slot_idx: int, energy_map) -> bool:
    try:
        return slot_idx in getattr(energy_map, "drop_slots", [])
    except Exception:
        return False


def _energy(slot_idx: int, energy_map) -> float:
    try:
        val = energy_map.get(slot_idx)
        return float(val) if val is not None else 0.5
    except Exception:
        return 0.5


def _duration(tr_type: str, preset: str) -> int:
    if tr_type == "cut":
        return 0
    return PRESET_DISSOLVE_FRAMES.get(preset, 15)


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

def plan_transitions(
    plan,
    energy_map,
    impact_timeline,
    default_transition: str = "cut",
    preset: str = "cinematic",
) -> list:
    """
    Decide the best transition for every consecutive slot pair.

    Decision priority for the outgoing slot (slot_idx):
        1. Drop slot         → PRESET["on_drop"]
        2. Beat-aligned slot → PRESET["on_beat"]
        3. Hook slot         → "cut" (maximum impact)
        4. Consecutive calm  → PRESET["default"] (soft bridge)
        5. Else              → PRESET["default"]

    Deduplication: if 3+ consecutive decisions share the same non-cut
    transition type the 3rd and beyond are rotated to "cut".

    Returns one TransitionDecision per slot pair (len(plan.slots)-1 total).
    """
    slots = getattr(plan, "slots", [])
    if len(slots) < 2:
        log.warning("plan_transitions: fewer than 2 slots — no transitions to plan")
        return []

    cfg = PRESET_TRANSITIONS.get(preset, PRESET_TRANSITIONS["cinematic"])

    decisions: list[TransitionDecision] = []

    for i in range(len(slots) - 1):
        out_slot = slots[i]
        in_slot  = slots[i + 1]

        out_idx = getattr(out_slot, "slot_index", i)
        in_idx  = getattr(in_slot,  "slot_index", i + 1)

        beat_aligned_out = getattr(out_slot, "beat_aligned", False)
        beat_aligned_in  = getattr(in_slot,  "beat_aligned", False)

        nrg_out = _energy(out_idx, energy_map)
        nrg_in  = _energy(in_idx,  energy_map)

        is_drop_out = _is_drop_slot(out_idx, energy_map)
        is_calm_out = (nrg_out < 0.3 and not beat_aligned_out)
        is_calm_in  = (nrg_in  < 0.3 and not beat_aligned_in)
        consecutive_calm = is_calm_out and is_calm_in

        # ---- Priority decision ----
        if is_drop_out:
            tr_type = cfg["on_drop"]
            reason  = "drop"
        elif beat_aligned_out:
            tr_type = cfg["on_beat"]
            reason  = "beat_hit"
        elif out_idx < _HOOK_COUNT:
            tr_type = "cut"
            reason  = "hook_exit"
        elif consecutive_calm:
            tr_type = cfg["default"]
            reason  = "calm_bridge"
        else:
            tr_type = cfg["default"]
            reason  = "default"

        duration = _duration(tr_type, preset)

        decisions.append(TransitionDecision(
            slot_idx=out_idx,
            transition_type=tr_type,
            duration_frames=duration,
            reason=reason,
        ))
        log.debug(
            "Planned transition slot={}→{} type={} frames={} reason={}",
            out_idx, in_idx, tr_type, duration, reason,
        )

    # ---- Deduplication: no 3+ consecutive identical non-cut transitions ----
    for j in range(2, len(decisions)):
        prev2 = decisions[j - 2]
        prev1 = decisions[j - 1]
        curr  = decisions[j]

        if (
            curr.transition_type != "cut"
            and curr.transition_type == prev1.transition_type == prev2.transition_type
        ):
            log.debug(
                "Dedup: rotating slot={} transition from {} to cut (3+ consecutive)",
                curr.slot_idx, curr.transition_type,
            )
            decisions[j] = TransitionDecision(
                slot_idx=curr.slot_idx,
                transition_type="cut",
                duration_frames=0,
                reason=curr.reason + "+dedup",
            )

    return decisions


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def apply_transition_decisions(
    resolve_ctrl,
    timeline,
    timeline_items: list,
    decisions: list,
) -> dict:
    """
    Apply TransitionDecisions to Resolve timeline items using
    _apply_single_transition from editor.transition_mapper.

    "cut" decisions are skipped (no action needed — hard cuts are the default).

    Returns:
        {
            "applied":       int,
            "skipped_cuts":  int,
            "failed":        int,
        }
    """
    try:
        from editor.transition_mapper import _apply_single_transition
    except ImportError as exc:
        log.error("Cannot import _apply_single_transition: {}", exc)
        return {"applied": 0, "skipped_cuts": 0, "failed": len(decisions)}

    applied      = 0
    skipped_cuts = 0
    failed       = 0

    if not decisions:
        log.warning("apply_transition_decisions: no decisions provided")
        return {"applied": 0, "skipped_cuts": 0, "failed": 0}

    for decision in decisions:
        out_idx = decision.slot_idx
        in_idx  = out_idx + 1      # transitions are between consecutive slots

        # ---- Hard cut: nothing to apply ----
        if decision.transition_type == "cut":
            log.debug(
                "Skipping cut at slot_idx={} (reason={})",
                out_idx, decision.reason,
            )
            skipped_cuts += 1
            continue

        # ---- Bounds check for outgoing item ----
        try:
            item_out = timeline_items[out_idx]
        except IndexError:
            log.warning(
                "apply_transition_decisions: out slot_idx={} out of range — skipping",
                out_idx,
            )
            failed += 1
            continue

        # ---- Bounds check for incoming item ----
        try:
            item_in = timeline_items[in_idx]
        except IndexError:
            log.warning(
                "apply_transition_decisions: in slot_idx={} out of range — skipping",
                in_idx,
            )
            failed += 1
            continue

        if item_out is None or item_in is None:
            log.warning(
                "apply_transition_decisions: None item at out={} or in={} — skipping",
                out_idx, in_idx,
            )
            failed += 1
            continue

        # ---- Apply ----
        try:
            result = _apply_single_transition(
                timeline,
                item_out,
                item_in,
                decision.transition_type,
                decision.duration_frames,
            )
            if result is False:
                log.warning(
                    "_apply_single_transition returned False for slot_idx={} type={}",
                    out_idx, decision.transition_type,
                )
                failed += 1
            else:
                log.debug(
                    "Applied transition slot={}→{} type={} frames={} reason={}",
                    out_idx, in_idx,
                    decision.transition_type,
                    decision.duration_frames,
                    decision.reason,
                )
                applied += 1
        except AttributeError as exc:
            log.warning(
                "AttributeError applying transition slot={}: {}",
                out_idx, exc,
            )
            failed += 1
        except Exception as exc:
            log.warning(
                "Exception applying transition slot={}: {}",
                out_idx, exc,
            )
            failed += 1

    log.debug(
        "apply_transition_decisions complete — applied={} skipped_cuts={} failed={}",
        applied, skipped_cuts, failed,
    )
    return {"applied": applied, "skipped_cuts": skipped_cuts, "failed": failed}
