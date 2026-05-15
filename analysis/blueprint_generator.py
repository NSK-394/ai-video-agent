"""
Blueprint builder — converts raw analysis dicts into the typed Blueprint schema.

Input  : raw dicts from cuts, beats, captions, style_analysis, and video_utils.
Output : Blueprint dataclass (call .to_dict() for the JSON-serializable form).
"""

from analysis.blueprint_schema import (
    Blueprint,
    SourceVideo,
    CutSegment,
    BeatMark,
    CaptionSegment,
    Word,
    EditRhythm,
    make_blueprint,
    source_video_from_metadata,
)
from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_blueprint(
    video_path: str,
    video_metadata: dict,
    cuts_raw: list,
    beat_data: dict,
    caption_data: dict,
    style_data: dict,
) -> Blueprint:
    """
    Assemble a Blueprint from the outputs of all analysis modules.

    Args:
        video_path:     Absolute path to the reference video.
        video_metadata: From video_utils.get_video_metadata().
        cuts_raw:       From cuts.detect_cuts().
        beat_data:      From beats.extract_beats().
        caption_data:   From captions_extract.generate_captions().
        style_data:     From style_analysis.analyze_style().

    Returns:
        Blueprint dataclass instance.
    """
    logger.info("Assembling blueprint …")

    source = source_video_from_metadata(video_path, video_metadata)

    cut_segments   = _build_cuts(cuts_raw)
    beat_marks     = _build_beats(beat_data)
    caption_segs   = _build_captions(caption_data)
    edit_rhythm    = _build_edit_rhythm(style_data)

    blueprint = make_blueprint(
        source_video=source,
        cuts=cut_segments,
        beats=beat_marks,
        captions=caption_segs,
        edit_rhythm=edit_rhythm,
    )

    logger.info(
        "Blueprint ready | {} cuts | {} beats | {} caption segments | style: {}",
        len(cut_segments), len(beat_marks), len(caption_segs), edit_rhythm.style,
    )
    return blueprint


# ---------------------------------------------------------------------------
# Internal converters
# ---------------------------------------------------------------------------

def _build_cuts(cuts_raw: list) -> list:
    result = []
    for c in cuts_raw:
        result.append(CutSegment(
            index=c["index"],
            start_time=c["start_time"],
            end_time=c["end_time"],
            duration=c["duration"],
            start_frame=c["start_frame"],
            end_frame=c["end_frame"],
            confidence=c.get("confidence", 1.0),
        ))
    return result


def _build_beats(beat_data: dict) -> list:
    result = []
    for b in beat_data.get("beats", []):
        result.append(BeatMark(
            index=b["index"],
            time=b["time"],
            frame=b["frame"],
            bpm_local=b.get("bpm_local"),
        ))
    return result


def _build_captions(caption_data: dict) -> list:
    result = []
    for seg in caption_data.get("segments", []):
        words = [
            Word(
                word=w["word"],
                start=w["start"],
                end=w["end"],
                confidence=w.get("confidence", 0.0),
            )
            for w in seg.get("words", [])
        ]
        result.append(CaptionSegment(
            index=seg["index"],
            start_time=seg["start_time"],
            end_time=seg["end_time"],
            text=seg["text"],
            confidence=seg.get("confidence", 0.0),
            words=words,
        ))
    return result


def _build_edit_rhythm(style_data: dict) -> EditRhythm:
    return EditRhythm(
        average_cut_duration=style_data.get("average_cut_duration", 0.0),
        median_cut_duration=style_data.get("median_cut_duration", 0.0),
        total_cuts=style_data.get("total_cuts", 0),
        cuts_per_minute=style_data.get("cuts_per_minute", 0.0),
        dominant_bpm=style_data.get("dominant_bpm", 0.0),
        beat_aligned_cuts=style_data.get("beat_aligned_cuts", 0),
        beat_alignment_ratio=style_data.get("beat_alignment_ratio", 0.0),
        speech_coverage=style_data.get("speech_coverage", 0.0),
        style=style_data.get("style", "mixed"),
    )
