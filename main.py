"""
Main entry point for the AI Video Agent.

Usage:
    cd ai-video-agent

    # Step 1 — Analyze a reference video -> produces blueprint.json
    python main.py analyze --video reference/demo_videos/demo.mp4

    # Step 2 — Execute blueprint against your raw footage in Resolve
    python main.py edit --blueprint reference/extracted_data/blueprint.json \\
                        --clips assets/clips/ \\
                        --render output/rendered/final.mp4
"""

import argparse
import json
import sys

from utils.logger import get_logger
from config.settings import load_settings

logger = get_logger(__name__)


def _cmd_analyze(args):
    from analysis.reference_analyzer import analyze_reference
    blueprint = analyze_reference(
        video_path=args.video,
        output_dir=args.output_dir,
        cut_threshold=args.cut_threshold,
        whisper_model=args.whisper_model,
        skip_captions=args.skip_captions,
    )
    rhythm = blueprint.get("edit_rhythm", {})
    print(
        f"\nBlueprint written"
        f"\n  Cuts    : {len(blueprint.get('cuts', []))}"
        f"\n  Beats   : {len(blueprint.get('beats', []))}"
        f"\n  Style   : {rhythm.get('style', 'unknown')}"
        f"\n  BPM     : {rhythm.get('dominant_bpm', 0):.1f}"
        f"\n  Avg cut : {rhythm.get('average_cut_duration', 0):.2f}s"
    )


def _cmd_edit(args):
    from editor.blueprint_executor import execute_blueprint
    result = execute_blueprint(
        blueprint_path=args.blueprint,
        clip_dir=args.clips,
        timeline_name=args.timeline_name,
        project_name=args.project,
        render_output=args.render,
        render_profile=args.render_profile,
        beat_sync=not args.no_beat_sync,
        default_transition=args.transition,
        caption_output_dir=args.caption_dir,
        audio_source=args.audio_source,
        mute_clips=args.mute_clips,
    )

    print(f"\nExecution {'SUCCESS' if result['success'] else 'FAILED'}")
    if result.get("error"):
        print(f"  Error       : {result['error']}")
        sys.exit(1)

    print(
        f"  Timeline    : {result.get('timeline_name', '')}\n"
        f"  Slots built : {result.get('slots_built', 0)}\n"
        f"  Clips placed: {result.get('clips_placed', 0)}\n"
        f"  Audio track : {'placed' if result.get('audio_placed') else 'skipped'}\n"
        f"  SRT captions: {result.get('srt_path', 'none')}\n"
        f"  Elapsed     : {result.get('elapsed_secs', 0):.1f}s"
    )
    if result.get("render_status"):
        print(f"  Render      : {result['render_status'].get('JobStatus', '?')}")


def main():
    settings = load_settings()
    logger.info("AI Video Agent | log_level={}", settings.get("LOG_LEVEL", "INFO"))

    parser = argparse.ArgumentParser(
        prog="ai-video-agent",
        description="AI-driven video editing assistant for DaVinci Resolve",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── analyze ─────────────────────────────────────────────────────────────
    p_analyze = sub.add_parser("analyze", help="Analyze a reference video -> blueprint.json")
    p_analyze.add_argument("--video", required=True, help="Path to reference video")
    p_analyze.add_argument("--output-dir", default=None,
                           help="Directory for blueprint.json")
    p_analyze.add_argument("--cut-threshold", type=float, default=None,
                           help="Cut detection sensitivity (lower = more cuts)")
    p_analyze.add_argument("--whisper-model",
                           choices=["tiny", "base", "small", "medium", "large"],
                           default="base", help="Whisper model size")
    p_analyze.add_argument("--skip-captions", action="store_true",
                           help="Skip speech transcription")

    # ── edit ────────────────────────────────────────────────────────────────
    p_edit = sub.add_parser("edit", help="Execute blueprint -> Resolve timeline")
    p_edit.add_argument("--blueprint", required=True, help="Path to blueprint.json")
    p_edit.add_argument("--clips", required=True,
                        help="Folder containing raw user footage")
    p_edit.add_argument("--project", default="AI_Editor_Project",
                        help="Resolve project name (default: AI_Editor_Project)")
    p_edit.add_argument("--timeline-name", default=None,
                        help="Override the output timeline name")
    p_edit.add_argument("--render", default=None,
                        help="Auto-render to this output file path after editing")
    p_edit.add_argument("--render-profile",
                        choices=["youtube_1080p", "youtube_vertical",
                                 "prores_proxy", "h265_4k"],
                        default=None, help="Render profile (auto-selected if not set)")
    p_edit.add_argument("--transition",
                        choices=["cut", "dissolve"],
                        default="cut", help="Default transition between clips")
    p_edit.add_argument("--no-beat-sync", action="store_true",
                        help="Disable beat-snapping of cut points")
    p_edit.add_argument("--caption-dir", default=None,
                        help="Directory to write captions.srt")
    p_edit.add_argument("--audio-source", default=None,
                        help="Path to reference video/audio to use as master audio track "
                             "(defaults to the reference video recorded in blueprint.json)")
    p_edit.add_argument("--mute-clips", action="store_true",
                        help="Strip audio from all video clips so only the reference "
                             "audio track plays in the rendered output")

    args = parser.parse_args()

    if args.command == "analyze":
        _cmd_analyze(args)
    elif args.command == "edit":
        _cmd_edit(args)


if __name__ == "__main__":
    main()
