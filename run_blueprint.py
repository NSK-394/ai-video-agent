"""
run_blueprint.py — Fusion Utility Script
=========================================
Runs the full AI blueprint execution pipeline from INSIDE DaVinci Resolve.

INSTALLATION:
    Copy this file to:
    C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Fusion\\Scripts\\Utility\\

    Then launch from Resolve:
    Workspace > Scripts > Utility > run_blueprint

WHAT IT DOES:
    1. Reads blueprint.json from disk
    2. Scans your clips folder and scores moments
    3. Builds an edit plan matching the reference video's pacing
    4. Creates a timeline in the currently open Resolve project
    5. Imports clips, places them with correct in/out points
    6. Applies cinematic effects (zoom, speed, transitions)
    7. Places reference audio track
    8. Writes captions.srt
    9. Generates quality_report.json
"""

import sys
import os

# ─── CONFIG — edit these before running ────────────────────────────────────
# Set PROJECT_DIR to the absolute path where you cloned this repository
PROJECT_DIR = r"C:\path\to\your\ai-video-agent"

BLUEPRINT_PATH = os.path.join(PROJECT_DIR, r"reference\extracted_data\blueprint.json")
CLIPS_DIR      = os.path.join(PROJECT_DIR, r"assets\clips")
TIMELINE_NAME  = "AI_Edit_v1"
TRANSITION     = "dissolve"        # "cut" or "dissolve"
BEAT_SYNC      = True

# Audio — "reference_only" | "clip_only" | "hybrid_mix"
MIX_MODE       = "reference_only"
AUDIO_SOURCE   = None              # None = auto-detect from blueprint

# Intelligence settings
SKIP_SEMANTIC       = False        # True = faster but less smart clip selection
HOOK_COUNT          = 2            # first N slots get high-energy bias
BEAT_AGGRESSIVENESS = 0.8          # 0=no snap  1=always snap to beat

# Effect engine — "subtle" | "cinematic" | "aggressive" | "anime" | "gaming"
EFFECT_PRESET       = "cinematic"
SKIP_EFFECTS        = False        # True = skip all cinematic effects
# ───────────────────────────────────────────────────────────────────────────

if PROJECT_DIR == r"C:\path\to\your\ai-video-agent":
    print("[ERROR] You must set PROJECT_DIR in run_blueprint.py before running.")
    print("        Edit the CONFIG block at the top of the script.")
    raise SystemExit(1)

# Add project to Python path so imports resolve correctly
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

# Inline logger for Fusion console (loguru may not be installed in Fusion's Python)
import logging as _logging
_logging.basicConfig(
    level=_logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
_fusion_log = _logging.getLogger("run_blueprint")


def _print(msg):
    print(msg)
    _fusion_log.info(msg)


# Verify blueprint exists
if not os.path.isfile(BLUEPRINT_PATH):
    _print(f"[ERROR] Blueprint not found: {BLUEPRINT_PATH}")
    _print("        Run: python main.py analyze --video your_reference.mp4")
    _print("        Then update BLUEPRINT_PATH in run_blueprint.py")
else:
    _print("=" * 56)
    _print("  AI Blueprint Executor — Fusion Script")
    _print("=" * 56)
    _print(f"  Blueprint : {BLUEPRINT_PATH}")
    _print(f"  Clips     : {CLIPS_DIR}")
    _print(f"  Timeline  : {TIMELINE_NAME}")
    _print(f"  Transition: {TRANSITION} | Beat-sync: {BEAT_SYNC}")
    _print("=" * 56)

    # Build a ResolveController backed by the Fusion `app` global
    try:
        from editor.resolve_api import ResolveController

        ctrl = ResolveController()
        # Inject the Fusion `app` directly — bypasses external API entirely
        resolve_obj = app.GetResolve()       # `app` is a Fusion global
        if not resolve_obj:
            raise RuntimeError("app.GetResolve() returned None — is a project open?")

        ctrl.resolve         = resolve_obj
        ctrl.project_manager = resolve_obj.GetProjectManager()
        ctrl.project         = ctrl.project_manager.GetCurrentProject()
        ctrl.media_pool      = ctrl.project.GetMediaPool()
        ctrl.root_folder     = ctrl.media_pool.GetRootFolder()
        ctrl._connected      = True
        _print(f"  Connected  : {ctrl.project.GetName()}")

    except Exception as e:
        _print(f"[ERROR] Resolve connection failed: {e}")
        raise SystemExit(1)

    # Run the pipeline
    try:
        from editor.blueprint_executor import execute_blueprint

        result = execute_blueprint(
            blueprint_path      = BLUEPRINT_PATH,
            clip_dir            = CLIPS_DIR,
            timeline_name       = TIMELINE_NAME,
            beat_sync           = BEAT_SYNC,
            default_transition  = TRANSITION,
            audio_source        = AUDIO_SOURCE,
            mix_mode            = MIX_MODE,
            skip_semantic       = SKIP_SEMANTIC,
            hook_count          = HOOK_COUNT,
            beat_aggressiveness = BEAT_AGGRESSIVENESS,
            effect_preset       = EFFECT_PRESET,
            skip_effects        = SKIP_EFFECTS,
            resolve_ctrl        = ctrl,
        )

        _print("=" * 56)
        if result["success"]:
            _print("  SUCCESS")
            _print(f"  Timeline : {result['timeline_name']}")
            _print(f"  Slots    : {result['slots_built']}")
            _print(f"  Placed   : {result['clips_placed']}")
            _print(f"  Audio    : {'placed' if result.get('audio_placed') else 'skipped'}")
            _print(f"  SRT      : {result.get('srt_path', 'none')}")
            _print(f"  Time     : {result['elapsed_secs']:.1f}s")
            qr = result.get("quality_report")
            if qr:
                _print(f"  Quality  : overall={qr.get('overall_score', 0):.1f} "
                       f"diversity={qr.get('diversity_score', 0):.1f} "
                       f"beat={qr.get('beat_alignment', 0):.1f} "
                       f"pacing={qr.get('pacing_consistency', 0):.1f}")
            ef = result.get("effect_summary")
            if ef:
                _print(f"  Effects  : cam={ef.get('camera_applied', 0)} "
                       f"speed={ef.get('speed_applied', 0)} "
                       f"flash={ef.get('flash_planned', 0)} "
                       f"trans={ef.get('transitions_applied', 0)}")
        else:
            _print(f"  FAILED: {result.get('error', 'unknown error')}")
        _print("=" * 56)

    except Exception as e:
        import traceback
        _print(f"[ERROR] Pipeline failed: {e}")
        _print(traceback.format_exc())
