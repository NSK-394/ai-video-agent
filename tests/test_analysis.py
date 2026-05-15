"""
Unit tests for the analysis layer.

These tests cover pure-Python logic that does not require DaVinci Resolve,
FFmpeg, or video files to be present.
"""
import pytest
from analysis.style_analysis import analyze_style
from analysis.blueprint_schema import (
    Blueprint, SourceVideo, CutSegment, BeatMark,
    CaptionSegment, EditRhythm, BlueprintMetadata, make_blueprint,
)


# ---------------------------------------------------------------------------
# Style Analysis
# ---------------------------------------------------------------------------

def _make_cuts(durations: list) -> list:
    """Build minimal CutSegment dicts from a list of durations."""
    cuts = []
    t = 0.0
    for i, dur in enumerate(durations):
        cuts.append({
            "index": i, "start_time": t, "end_time": t + dur,
            "duration": dur, "start_frame": int(t * 30), "end_frame": int((t + dur) * 30),
            "confidence": 1.0,
        })
        t += dur
    return cuts


class TestAnalyzeStyle:
    def test_fast_cut_classification(self):
        cuts = _make_cuts([1.0] * 10)
        result = analyze_style(
            cuts=cuts,
            beat_data={"beats": [], "dominant_bpm": 0.0},
            caption_data={"segments": [], "words": []},
            video_duration=10.0,
        )
        assert result["style"] == "fast_cut"

    def test_slow_burn_classification(self):
        cuts = _make_cuts([8.0] * 4)
        result = analyze_style(
            cuts=cuts,
            beat_data={"beats": [], "dominant_bpm": 0.0},
            caption_data={"segments": [], "words": []},
            video_duration=32.0,
        )
        assert result["style"] == "slow_burn"

    def test_average_cut_duration_computed(self):
        cuts = _make_cuts([2.0, 4.0, 6.0])
        result = analyze_style(
            cuts=cuts,
            beat_data={"beats": [], "dominant_bpm": 0.0},
            caption_data={"segments": [], "words": []},
            video_duration=12.0,
        )
        assert abs(result["average_cut_duration"] - 4.0) < 0.01

    def test_beat_alignment_ratio_with_perfectly_aligned_cuts(self):
        # Cuts end exactly on beats
        cuts = _make_cuts([1.0, 1.0, 1.0, 1.0])
        beat_times = [1.0, 2.0, 3.0, 4.0]
        beats = [{"index": i, "time": t, "frame": int(t * 30), "bpm_local": 60.0}
                 for i, t in enumerate(beat_times)]
        result = analyze_style(
            cuts=cuts,
            beat_data={"beats": beats, "dominant_bpm": 60.0},
            caption_data={"segments": [], "words": []},
            video_duration=4.0,
        )
        assert result["beat_alignment_ratio"] > 0.5

    def test_returns_dominant_bpm(self):
        cuts = _make_cuts([2.0, 2.0])
        beats = [{"index": i, "time": i * 0.5, "frame": i * 15, "bpm_local": 120.0}
                 for i in range(8)]
        result = analyze_style(
            cuts=cuts,
            beat_data={"beats": beats, "bpm": 120.0},
            caption_data={"segments": [], "words": []},
            video_duration=4.0,
        )
        assert result["dominant_bpm"] == 120.0


# ---------------------------------------------------------------------------
# Blueprint Schema
# ---------------------------------------------------------------------------

class TestBlueprintSchema:
    def _make_blueprint(self) -> Blueprint:
        sv = SourceVideo(
            path="/tmp/test.mp4",
            duration_seconds=10.0,
            fps=30.0,
            width=1920,
            height=1080,
            frame_count=300,
            is_vertical=False,
            aspect_ratio="16:9",
        )
        cuts = [CutSegment(index=0, start_time=0.0, end_time=5.0, duration=5.0,
                           start_frame=0, end_frame=150, confidence=1.0)]
        beats = [BeatMark(index=0, time=0.5, frame=15, bpm_local=120.0)]
        captions = []
        rhythm = EditRhythm(
            style="mixed",
            dominant_bpm=120.0,
            average_cut_duration=5.0,
            median_cut_duration=5.0,
            total_cuts=1,
            cuts_per_minute=6.0,
            beat_aligned_cuts=0,
            beat_alignment_ratio=0.5,
            speech_coverage=0.0,
        )
        return make_blueprint(sv, cuts, beats, captions, rhythm)

    def test_make_blueprint_fields(self):
        bp = self._make_blueprint()
        assert len(bp.cuts) == 1
        assert len(bp.beats) == 1
        assert bp.edit_rhythm.style == "mixed"
        assert bp.version == "1.0"

    def test_to_dict_is_json_serializable(self):
        import json
        bp = self._make_blueprint()
        d = bp.to_dict()
        # Should not raise
        json.dumps(d)

    def test_to_dict_structure(self):
        bp = self._make_blueprint()
        d = bp.to_dict()
        assert "version" in d
        assert "cuts" in d
        assert "beats" in d
        assert d["cuts"][0]["duration"] == 5.0
        assert d["source_video"]["is_vertical"] is False
