"""
reference_analyzer.py
---------------------
Main orchestrator for the AI analysis layer.

INPUT : path to a reference/demo video
OUTPUT: blueprint.json saved to disk + Blueprint object returned

Pipeline:
  1. Read video metadata (FPS, resolution, duration, orientation)
  2. Extract audio to a temp WAV
  3. Detect scene cuts (PySceneDetect or OpenCV)
  4. Detect musical beats (librosa)
  5. Transcribe speech with word timestamps (Whisper)
  6. Classify editing style
  7. Assemble Blueprint dataclass
  8. Serialize to JSON and save

Usage (CLI):
    cd ai-video-agent
    python -m analysis.reference_analyzer --video path/to/demo.mp4

Usage (Python):
    from analysis.reference_analyzer import analyze_reference
    blueprint = analyze_reference("demo.mp4", output_dir="reference/extracted_data")
"""

import argparse
import json
import os
import sys
import tempfile
import time

from utils.logger import get_logger
from utils.video_utils import get_video_metadata
from utils.ffmpeg_utils import extract_audio
from analysis.cuts import detect_cuts
from analysis.beats import extract_beats
from analysis.captions_extract import generate_captions
from analysis.style_analysis import analyze_style
from analysis.blueprint_generator import generate_blueprint
from config.constants import (
    AUDIO_SAMPLE_RATE_WHISPER,
    BLUEPRINT_FILENAME,
    WHISPER_MODEL_SIZE,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_reference(
    video_path: str,
    output_dir: str = None,
    output_filename: str = BLUEPRINT_FILENAME,
    cut_threshold: float = None,
    whisper_model: str = WHISPER_MODEL_SIZE,
    skip_captions: bool = False,
) -> dict:
    """
    Run the full analysis pipeline on a reference video and save blueprint.json.

    Args:
        video_path:       Absolute (or relative) path to the reference video.
        output_dir:       Directory to write blueprint.json.
                          Defaults to  reference/extracted_data/  next to the video.
        output_filename:  Override the output filename (default: blueprint.json).
        cut_threshold:    Override default cut-detection sensitivity.
        whisper_model:    Whisper model size: tiny | base | small | medium | large.
        skip_captions:    Skip Whisper transcription (saves time if no speech needed).

    Returns:
        The blueprint as a plain dict (JSON-safe).
    """
    video_path = os.path.abspath(video_path)

    # Auto-discover: if the exact path doesn't exist, look for any video in its directory
    if not os.path.isfile(video_path):
        parent_dir = os.path.dirname(video_path)
        if os.path.isdir(parent_dir):
            _VIDEO_EXTS = {".mp4", ".mov", ".mxf", ".avi", ".mkv", ".m4v", ".r3d", ".braw"}
            candidates = sorted([
                os.path.join(parent_dir, f) for f in os.listdir(parent_dir)
                if os.path.splitext(f)[1].lower() in _VIDEO_EXTS
            ])
            if candidates:
                logger.warning(
                    "Path '{}' not found — using first video in folder: {}",
                    video_path, os.path.basename(candidates[0]),
                )
                video_path = candidates[0]
            else:
                raise FileNotFoundError(
                    f"Reference video not found and no videos in: {parent_dir}"
                )
        else:
            raise FileNotFoundError(f"Reference video not found: {video_path}")

    # Resolve output directory
    if output_dir is None:
        output_dir = os.path.join(
            os.path.dirname(video_path), "extracted_data"
        )
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, output_filename)

    t_start = time.perf_counter()
    logger.info("=" * 60)
    logger.info("Reference Analyzer — START")
    logger.info("Video : {}", video_path)
    logger.info("Output: {}", output_path)
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Step 1: Video metadata
    # ------------------------------------------------------------------
    logger.info("[1/6] Reading video metadata …")
    video_meta = get_video_metadata(video_path)
    logger.info(
        "  {}×{} @ {:.2f} fps | {:.2f} s | {} | {}",
        video_meta["width"], video_meta["height"],
        video_meta["fps"], video_meta["duration_seconds"],
        "vertical" if video_meta["is_vertical"] else "horizontal",
        video_meta["aspect_ratio"],
    )

    # ------------------------------------------------------------------
    # Step 2: Extract audio to temp WAV (shared by beats + captions)
    # ------------------------------------------------------------------
    logger.info("[2/6] Extracting audio …")
    tmp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_audio.close()
    audio_ok = extract_audio(
        video_path, tmp_audio.name,
        sample_rate=AUDIO_SAMPLE_RATE_WHISPER, channels=1,
    )
    if not audio_ok:
        logger.warning("Audio extraction failed — beats and captions will be empty")
        tmp_audio_path = None
    else:
        tmp_audio_path = tmp_audio.name
        logger.info("  Temp audio: {}", tmp_audio_path)

    # ------------------------------------------------------------------
    # Step 3: Detect cuts
    # ------------------------------------------------------------------
    logger.info("[3/6] Detecting scene cuts …")
    cuts_raw = detect_cuts(video_path, threshold=cut_threshold)
    logger.info("  {} cuts detected", len(cuts_raw))

    # ------------------------------------------------------------------
    # Step 4: Beat detection
    # ------------------------------------------------------------------
    if tmp_audio_path:
        logger.info("[4/6] Detecting beats …")
        beat_data = extract_beats(tmp_audio_path)
        logger.info("  {} beats @ {:.1f} BPM", beat_data["beat_count"], beat_data["bpm"])
    else:
        logger.warning("[4/6] Skipping beats (no audio)")
        beat_data = {"bpm": 0.0, "beat_count": 0, "beats": []}

    # ------------------------------------------------------------------
    # Step 5: Captions / transcription
    # ------------------------------------------------------------------
    if tmp_audio_path and not skip_captions:
        logger.info("[5/6] Transcribing speech (model={}) …", whisper_model)
        caption_data = generate_captions(
            tmp_audio_path, model_size=whisper_model, word_timestamps=True
        )
        logger.info(
            "  {} segments | {} words | lang={}",
            len(caption_data["segments"]),
            caption_data["word_count"],
            caption_data["language"],
        )
    else:
        reason = "no audio" if not tmp_audio_path else "skip_captions=True"
        logger.info("[5/6] Skipping captions ({})", reason)
        caption_data = {"language": "unknown", "full_text": "", "duration": 0.0,
                        "word_count": 0, "segments": []}

    # ------------------------------------------------------------------
    # Step 6: Style analysis
    # ------------------------------------------------------------------
    logger.info("[6/6] Classifying editing style …")
    style_data = analyze_style(
        cuts=cuts_raw,
        beat_data=beat_data,
        caption_data=caption_data,
        video_duration=video_meta["duration_seconds"],
    )
    logger.info("  Style: {}", style_data["style"])

    # ------------------------------------------------------------------
    # Assemble blueprint
    # ------------------------------------------------------------------
    blueprint = generate_blueprint(
        video_path=video_path,
        video_metadata=video_meta,
        cuts_raw=cuts_raw,
        beat_data=beat_data,
        caption_data=caption_data,
        style_data=style_data,
    )
    blueprint_dict = blueprint.to_dict()

    # ------------------------------------------------------------------
    # Persist to JSON
    # ------------------------------------------------------------------
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(blueprint_dict, f, indent=2, ensure_ascii=False)

    elapsed = time.perf_counter() - t_start
    logger.info("=" * 60)
    logger.info("Blueprint saved -> {}", output_path)
    logger.info("Total analysis time: {:.1f} s", elapsed)
    logger.info("=" * 60)

    # Clean up shared temp audio
    if tmp_audio_path and os.path.isfile(tmp_audio_path):
        os.remove(tmp_audio_path)

    return blueprint_dict


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Analyze a reference video and produce a blueprint.json"
    )
    p.add_argument("--video", required=True, help="Path to the reference video")
    p.add_argument("--output-dir", default=None,
                   help="Directory to save blueprint.json (default: next to video)")
    p.add_argument("--output-file", default=BLUEPRINT_FILENAME,
                   help=f"Output filename (default: {BLUEPRINT_FILENAME})")
    p.add_argument("--cut-threshold", type=float, default=None,
                   help="Cut detection sensitivity (lower = more cuts)")
    p.add_argument("--whisper-model", default=WHISPER_MODEL_SIZE,
                   choices=["tiny", "base", "small", "medium", "large"],
                   help="Whisper model size (default: base)")
    p.add_argument("--skip-captions", action="store_true",
                   help="Skip speech transcription to save time")
    return p


if __name__ == "__main__":
    args = _build_parser().parse_args()
    try:
        result = analyze_reference(
            video_path=args.video,
            output_dir=args.output_dir,
            output_filename=args.output_file,
            cut_threshold=args.cut_threshold,
            whisper_model=args.whisper_model,
            skip_captions=args.skip_captions,
        )
        print(f"\nBlueprint written: {len(result.get('cuts', []))} cuts | "
              f"style={result.get('edit_rhythm', {}).get('style', 'unknown')}")
        sys.exit(0)
    except Exception as e:
        logger.exception("Analysis failed: {}", e)
        sys.exit(1)
