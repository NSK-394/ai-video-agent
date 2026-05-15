"""
Blueprint schema — dataclass definitions for the editing blueprint JSON.

All dataclasses are JSON-serializable via dataclasses.asdict().
The Blueprint.to_dict() helper produces the canonical wire format.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Optional


# ---------------------------------------------------------------------------
# Leaf types
# ---------------------------------------------------------------------------

@dataclass
class SourceVideo:
    """Raw metadata about the analyzed reference video."""
    path:             str
    duration_seconds: float
    fps:              float
    width:            int
    height:           int
    frame_count:      int
    is_vertical:      bool
    aspect_ratio:     str   # e.g. "9:16"


@dataclass
class CutSegment:
    """One detected scene between two consecutive cuts."""
    index:       int
    start_time:  float   # seconds
    end_time:    float   # seconds
    duration:    float   # seconds
    start_frame: int
    end_frame:   int
    confidence:  float = 1.0


@dataclass
class BeatMark:
    """A single musical beat position."""
    index:     int
    time:      float          # seconds
    frame:     int            # display frame at 30 fps
    bpm_local: Optional[float] = None


@dataclass
class Word:
    """Word-level timing from Whisper."""
    word:       str
    start:      float
    end:        float
    confidence: float = 0.0


@dataclass
class CaptionSegment:
    """One speech segment with optional word-level timing."""
    index:      int
    start_time: float
    end_time:   float
    text:       str
    confidence: float = 0.0
    words:      List[Word] = field(default_factory=list)


@dataclass
class EditRhythm:
    """
    Quantitative summary of the editing pace and a qualitative style label.

    Style labels:
        "beat_synced"      — cuts predominantly land on musical beats
        "fast_cut"         — avg scene < 2 s
        "slow_burn"        — avg scene > 6 s
        "dialogue_driven"  — > 65 % of video has speech
        "mixed"            — no dominant pattern
    """
    average_cut_duration: float
    median_cut_duration:  float
    total_cuts:           int
    cuts_per_minute:      float
    dominant_bpm:         float
    beat_aligned_cuts:    int
    beat_alignment_ratio: float
    speech_coverage:      float
    style:                str


@dataclass
class BlueprintMetadata:
    """Provenance information written into every blueprint."""
    analyzed_at:      str   # ISO-8601
    analyzer_version: str
    source_file:      str


# ---------------------------------------------------------------------------
# Root blueprint
# ---------------------------------------------------------------------------

@dataclass
class Blueprint:
    """
    Complete editing blueprint produced by reference_analyzer.

    Serialise with Blueprint.to_dict() -> JSON-ready dict.
    """
    version:      str
    metadata:     BlueprintMetadata
    source_video: SourceVideo
    cuts:         List[CutSegment]
    beats:        List[BeatMark]
    captions:     List[CaptionSegment]
    edit_rhythm:  EditRhythm

    def to_dict(self) -> dict:
        """Return a fully nested plain-dict representation (JSON-safe)."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

BLUEPRINT_VERSION = "1.0"
ANALYZER_VERSION = "1.0.0"


def make_blueprint(
    source_video: SourceVideo,
    cuts: List[CutSegment],
    beats: List[BeatMark],
    captions: List[CaptionSegment],
    edit_rhythm: EditRhythm,
) -> Blueprint:
    """Construct a Blueprint with auto-filled metadata."""
    return Blueprint(
        version=BLUEPRINT_VERSION,
        metadata=BlueprintMetadata(
            analyzed_at=datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            analyzer_version=ANALYZER_VERSION,
            source_file=source_video.path,
        ),
        source_video=source_video,
        cuts=cuts,
        beats=beats,
        captions=captions,
        edit_rhythm=edit_rhythm,
    )


def source_video_from_metadata(path: str, meta: dict) -> SourceVideo:
    """Build a SourceVideo from the dict returned by video_utils.get_video_metadata."""
    return SourceVideo(
        path=path,
        duration_seconds=meta["duration_seconds"],
        fps=meta["fps"],
        width=meta["width"],
        height=meta["height"],
        frame_count=meta["frame_count"],
        is_vertical=meta["is_vertical"],
        aspect_ratio=meta["aspect_ratio"],
    )
