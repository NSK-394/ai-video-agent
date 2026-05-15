"""
Unit tests for the editor layer.

These tests cover pure-Python logic that does not require DaVinci Resolve
to be running. Resolve API objects are replaced with simple fakes.
"""
import pytest
from editor.beat_sync_editor import categorize_beats, build_pacing_curve
from editor.visual_energy_mapper import build_energy_map, EnergyPoint
from editor.camera_animation import plan_camera_moves, CameraDirective


# ---------------------------------------------------------------------------
# Minimal fakes — no Resolve dependency
# ---------------------------------------------------------------------------

class _FakeSlot:
    def __init__(self, idx: int, dur: float = 2.0):
        self.slot_index = idx
        self.duration = dur
        self.clip_path = f"clip_{idx}.mp4"
        self.beat_aligned = False


class _FakePlan:
    def __init__(self, n: int = 5):
        self.slots = [_FakeSlot(i) for i in range(n)]
        self.total_slots = n
        self.fps = 30.0
        self.edit_style = "mixed"


# ---------------------------------------------------------------------------
# Beat sync
# ---------------------------------------------------------------------------

class TestCategorizeBeats:
    def _make_beat_data(self, times):
        return {"beats": [{"index": i, "time": t} for i, t in enumerate(times)]}

    def test_major_beats_every_fourth(self):
        times = [0.5 * i for i in range(12)]
        result = categorize_beats(self._make_beat_data(times), fps=30.0)
        assert len(result["major"]) == 3   # beats 0, 4, 8

    def test_empty_beats(self):
        result = categorize_beats({"beats": []}, fps=30.0)
        assert result["major"] == []
        assert result["drop"] == []
        assert result["minor"] == []


class TestBuildPacingCurve:
    def test_length_matches_slots(self):
        curve = build_pacing_curve(total_slots=7, style="mixed")
        assert len(curve) == 7

    def test_values_in_range(self):
        for style in ("fast_cut", "slow_burn", "beat_synced", "mixed"):
            curve = build_pacing_curve(total_slots=5, style=style)
            assert all(0.0 <= v <= 1.0 for v in curve), f"Out-of-range value for style={style}"

    def test_fast_cut_stays_high(self):
        curve = build_pacing_curve(total_slots=6, style="fast_cut")
        assert all(v >= 0.6 for v in curve)


# ---------------------------------------------------------------------------
# Visual energy mapper
# ---------------------------------------------------------------------------

class TestBuildEnergyMap:
    def _blueprint(self):
        return {
            "beats": [{"time": 0.5 * i} for i in range(10)],
            "fps": 30.0,
        }

    def test_produces_one_point_per_slot(self):
        plan = _FakePlan(5)
        em = build_energy_map(plan, self._blueprint(), pacing_curve=[0.5] * 5)
        assert len(em.points) == 5

    def test_combined_energy_in_range(self):
        plan = _FakePlan(5)
        em = build_energy_map(plan, self._blueprint(), pacing_curve=[0.5] * 5)
        for pt in em.points:
            assert 0.0 <= pt.combined_energy <= 1.0

    def test_peak_slots_subset_of_all_slots(self):
        plan = _FakePlan(8)
        em = build_energy_map(plan, self._blueprint(), pacing_curve=[float(i) / 8 for i in range(8)])
        all_indices = {pt.slot_idx for pt in em.points}
        assert all(s in all_indices for s in em.peak_slots)

    def test_empty_plan(self):
        class EmptyPlan:
            slots = []
            total_slots = 0
            fps = 30.0
            edit_style = "mixed"

        em = build_energy_map(EmptyPlan(), {}, pacing_curve=[])
        assert len(em.points) == 0


# ---------------------------------------------------------------------------
# Camera animation
# ---------------------------------------------------------------------------

class TestPlanCameraMoves:
    def _energy_map(self):
        plan = _FakePlan(5)
        blueprint = {"beats": [{"time": 0.5 * i} for i in range(10)], "fps": 30.0}
        return build_energy_map(plan, blueprint, pacing_curve=[0.8, 0.5, 0.9, 0.3, 0.7])

    def test_one_directive_per_slot(self):
        plan = _FakePlan(5)
        em = self._energy_map()
        directives = plan_camera_moves(plan, em, preset="cinematic", hook_count=2)
        assert len(directives) == 5

    def test_hook_slots_have_hook_emphasis_reason(self):
        plan = _FakePlan(5)
        em = self._energy_map()
        directives = plan_camera_moves(plan, em, preset="cinematic", hook_count=2)
        assert directives[0].reason == "hook_emphasis"
        assert directives[1].reason == "hook_emphasis"

    def test_zoom_in_valid_range(self):
        plan = _FakePlan(5)
        em = self._energy_map()
        for preset in ("subtle", "cinematic", "aggressive", "anime", "gaming"):
            directives = plan_camera_moves(plan, em, preset=preset)
            for d in directives:
                assert 0.9 <= d.zoom_x <= 1.5, f"zoom_x={d.zoom_x} out of range for {preset}"

    def test_energy_point_comparison_does_not_raise(self):
        """Regression test: EnergyPoint must not be compared directly to float."""
        plan = _FakePlan(5)
        em = self._energy_map()
        # This used to raise TypeError: '>' not supported between EnergyPoint and float
        directives = plan_camera_moves(plan, em, preset="cinematic")
        assert len(directives) == 5
