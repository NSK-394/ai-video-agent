"""
blueprint_executor.py
---------------------
Main orchestrator for the blueprint execution layer.

Pipeline (13 steps):
  1.  Load blueprint.json
  2.  Connect to DaVinci Resolve
  3.  Semantic classification of all raw clips
  4.  Pacing curve + beat categorisation
  5.  Clip ranking (motion + semantic + diversity + hook)
  6.  Build EditPlan from blueprint timing
  7.  Beat-sync snap (advanced)
  8.  Build Resolve timeline
  8.5 Cinematic effect engine (zoom, speed, transitions, energy mapping)
  9.  Place reference audio track
  10. Render captions / SRT
  11. Quality analysis report (includes effect summary)
  [12. Auto-render — optional]
"""

import json
import os
import time
from utils.logger import get_logger
from editor.resolve_api import ResolveController
from editor.media_importer import collect_clip_paths
from analysis.clip_ranker import rank_clips_for_slots
from analysis.diversity_manager import DiversityMemory
from editor.pacing_engine import build_edit_plan, describe_plan
from editor.beat_sync_editor import snap_to_beats_advanced, build_pacing_curve, categorize_beats
from editor.timeline_builder import build_timeline
from editor.transition_mapper import apply_transitions, set_slot_transitions
from editor.caption_renderer import render_captions
from editor.audio_manager import (
    extract_reference_audio,
    import_audio_to_media_pool,
    place_audio_on_timeline,
    get_audio_duration,
    resolve_audio_source,
)
from editor.audio_mixer import AudioMixMode, get_mix_mode, resolve_mute_clips
from editor.edit_quality_analyzer import analyze_edit_quality
from editor.effect_engine import build_and_apply_effects
from config.constants import (
    DIVERSITY_COOLDOWN_SLOTS, DIVERSITY_MIN_TEMPORAL_GAP,
    DIVERSITY_FREQUENCY_DECAY, DIVERSITY_CONSECUTIVE_PENALTY,
    DIVERSITY_TEMPORAL_PROXIMITY,
    HOOK_SLOT_COUNT, BEAT_AGGRESSIVENESS, BEAT_PREFER_MAJOR,
)

logger = get_logger(__name__)


def _make_result(success: bool, **kwargs) -> dict:
    return {"success": success, **kwargs}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute_blueprint(
    blueprint_path: str,
    clip_dir: str,
    timeline_name: str = None,
    project_name: str = "AI_Editor_Project",
    render_output: str = None,
    render_profile: str = None,
    beat_sync: bool = True,
    default_transition: str = "cut",
    caption_output_dir: str = None,
    resolve_ctrl: ResolveController = None,
    # Audio
    audio_source: str = None,
    mute_clips: bool = False,
    mix_mode: str = None,
    # Intelligence
    skip_semantic: bool = False,
    hook_count: int = HOOK_SLOT_COUNT,
    beat_aggressiveness: float = BEAT_AGGRESSIVENESS,
    # Effect engine
    effect_preset: str = "cinematic",
    skip_effects: bool = False,
) -> dict:
    """
    Execute a blueprint end-to-end, building an edited timeline in Resolve.

    Args:
        blueprint_path:     Path to blueprint.json.
        clip_dir:           Folder with raw user footage.
        timeline_name:      Override timeline name.
        project_name:       Resolve project name.
        render_output:      Auto-render output path.
        render_profile:     Render profile name.
        beat_sync:          Snap cuts to musical beats.
        default_transition: "cut" | "dissolve".
        caption_output_dir: Directory for captions.srt.
        resolve_ctrl:       Pre-connected ResolveController.
        audio_source:       Reference video/audio path override.
        mute_clips:         Strip audio from video clips (overrides mix_mode).
        mix_mode:           "reference_only" | "clip_only" | "hybrid_mix".
        skip_semantic:      Skip semantic classification (faster, lower quality).
        hook_count:         First N slots treated as hook (high-energy bias).
        beat_aggressiveness: 0-1 how hard to snap cuts to beats.
        effect_preset:      "subtle"|"cinematic"|"aggressive"|"anime"|"gaming".
        skip_effects:       Skip all cinematic effects (fastest, but flat output).

    Returns:
        Result dict with success, timeline_name, slots_built, clips_placed,
        audio_placed, srt_path, quality_report, effect_summary,
        render_status, elapsed_secs.
    """
    t_start        = time.perf_counter()
    audio_placed   = False
    quality_report = None
    effect_summary = None

    # Resolve audio mix mode
    resolved_mix = get_mix_mode(mute_clips, mix_mode)
    video_only   = resolve_mute_clips(resolved_mix)

    logger.info("=" * 60)
    logger.info("Blueprint Executor — START")
    logger.info("Blueprint   : {}", blueprint_path)
    logger.info("Clips       : {}", clip_dir)
    logger.info("Mix mode    : {} | video_only={}", resolved_mix.value, video_only)
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Step 1: Load blueprint
    # ------------------------------------------------------------------
    logger.info("[1] Loading blueprint ...")
    blueprint = _load_blueprint(blueprint_path)
    if blueprint is None:
        return _make_result(False, error="Could not load blueprint.json")

    source     = blueprint.get("source_video", {})
    rhythm     = blueprint.get("edit_rhythm", {})
    cuts       = blueprint.get("cuts", [])
    beats_data = blueprint.get("beats", [])

    tl_name    = timeline_name or _derive_timeline_name(blueprint_path)
    is_vertical = bool(source.get("is_vertical", False))
    edit_style  = rhythm.get("style", "mixed")
    fps         = float(source.get("fps", 30.0))

    logger.info("  {} cuts | style={} | vertical={} | beats={}",
                len(cuts), edit_style, is_vertical, len(beats_data))

    if not cuts:
        return _make_result(False, error="Blueprint contains no cuts")

    # ------------------------------------------------------------------
    # Step 2: Connect to Resolve
    # ------------------------------------------------------------------
    logger.info("[2] Connecting to DaVinci Resolve ...")
    if resolve_ctrl is None:
        resolve_ctrl = ResolveController()
        try:
            resolve_ctrl.connect(project_name=project_name)
        except RuntimeError as e:
            logger.error("Resolve connection failed: {}", e)
            return _make_result(False, error=str(e))
    else:
        logger.info("  Using pre-connected ResolveController")

    # ------------------------------------------------------------------
    # Step 3: Collect clips + semantic classification
    # ------------------------------------------------------------------
    logger.info("[3] Scanning clips and classifying semantics ...")
    clip_paths = collect_clip_paths(clip_dir)
    if not clip_paths:
        return _make_result(False, error=f"No media files found in: {clip_dir}")

    semantic_analyses = None
    if not skip_semantic:
        semantic_analyses = _classify_clips(clip_paths)

    # ------------------------------------------------------------------
    # Step 4: Build pacing curve + beat categories
    # ------------------------------------------------------------------
    logger.info("[4] Computing pacing curve ...")
    total_slots    = len(cuts)
    slot_durations = [c["duration"] for c in cuts]

    beat_categories = None
    if beats_data:
        beat_categories = categorize_beats({"beats": beats_data}, fps=fps)
        logger.info(
            "  Beat categories: major={} drop={} minor={}",
            len(beat_categories.get("major", [])),
            len(beat_categories.get("drop", [])),
            len(beat_categories.get("minor", [])),
        )

    pacing_curve = build_pacing_curve(total_slots, edit_style, beat_categories)
    logger.debug("  Pacing curve: {}", [round(x, 2) for x in pacing_curve])

    # ------------------------------------------------------------------
    # Step 5: Rank clips with intelligence
    # ------------------------------------------------------------------
    logger.info("[5] Ranking clips ...")
    diversity_mem = DiversityMemory(
        cooldown_slots=DIVERSITY_COOLDOWN_SLOTS,
        min_temporal_gap_secs=DIVERSITY_MIN_TEMPORAL_GAP,
        frequency_decay=DIVERSITY_FREQUENCY_DECAY,
        consecutive_penalty=DIVERSITY_CONSECUTIVE_PENALTY,
        temporal_proximity_penalty=DIVERSITY_TEMPORAL_PROXIMITY,
    )

    clip_assignments = rank_clips_for_slots(
        clip_paths=clip_paths,
        slot_durations=slot_durations,
        allow_reuse=True,
        diversity_memory=diversity_mem,
        semantic_analyses=semantic_analyses,
        edit_style=edit_style,
        beats=beats_data if beats_data else None,
        pacing_curve=pacing_curve,
        hook_count=hook_count,
    )
    logger.info("  {} slots assigned from {} clips", len(clip_assignments), len(clip_paths))

    # ------------------------------------------------------------------
    # Step 6: Build EditPlan
    # ------------------------------------------------------------------
    logger.info("[6] Building edit plan ...")
    plan = build_edit_plan(blueprint, clip_assignments)
    logger.info(describe_plan(plan))

    # ------------------------------------------------------------------
    # Step 7: Beat-sync snap
    # ------------------------------------------------------------------
    if beat_sync and beats_data:
        logger.info("[7] Snapping cuts to beats (aggressiveness={:.1f}) ...", beat_aggressiveness)
        plan = snap_to_beats_advanced(
            plan, blueprint,
            aggressiveness=beat_aggressiveness,
            prefer_major_beats=BEAT_PREFER_MAJOR,
        )
    else:
        logger.info("[7] Beat-sync skipped")

    # Apply transition style
    if edit_style == "beat_synced" and default_transition == "cut":
        default_transition = "dissolve"
    set_slot_transitions(plan, default_transition)

    # ------------------------------------------------------------------
    # Step 8: Build Resolve timeline
    # ------------------------------------------------------------------
    logger.info("[8] Building Resolve timeline '{}' ...", tl_name)
    try:
        timeline, placed_items = build_timeline(
            resolve_ctrl=resolve_ctrl,
            plan=plan,
            timeline_name=tl_name,
            clip_dir=clip_dir,
            video_only=video_only,
        )
    except RuntimeError as e:
        logger.error("Timeline build failed: {}", e)
        return _make_result(False, error=str(e))

    logger.info("  {} clip(s) placed", len(placed_items))

    # ------------------------------------------------------------------
    # Step 9: Apply transitions
    # ------------------------------------------------------------------
    logger.info("[9] Applying transitions ('{}') ...", default_transition)
    apply_transitions(
        resolve_ctrl=resolve_ctrl,
        timeline=timeline,
        timeline_items=placed_items,
        edit_plan=plan,
        default_transition=default_transition,
    )

    # ------------------------------------------------------------------
    # Step 8.5: Cinematic effect engine
    # ------------------------------------------------------------------
    if not skip_effects:
        logger.info("[8.5] Running cinematic effect engine (preset={}) ...", effect_preset)
        try:
            effect_summary_obj = build_and_apply_effects(
                resolve_ctrl=resolve_ctrl,
                timeline=timeline,
                timeline_items=placed_items,
                plan=plan,
                blueprint=blueprint,
                pacing_curve=pacing_curve,
                beat_categories=beat_categories,
                semantic_analyses=semantic_analyses,
                preset=effect_preset,
                hook_count=hook_count,
                # Smart transitions already handled here — skip legacy apply_transitions
                skip_smart_transitions=False,
            )
            effect_summary = effect_summary_obj.to_dict()
            logger.info(
                "  Effects: cam={}/{} speed={} flash={} trans={}",
                effect_summary_obj.camera_applied,
                effect_summary_obj.camera_applied + effect_summary_obj.camera_skipped,
                effect_summary_obj.speed_applied,
                effect_summary_obj.flash_planned,
                effect_summary_obj.transitions_applied,
            )
        except Exception as e:
            logger.error("Effect engine failed (non-fatal): {}", e)
            effect_summary = {"error": str(e)}
    else:
        logger.info("[8.5] Effects skipped (skip_effects=True)")

    # ------------------------------------------------------------------
    # Step 10: Reference audio track
    # ------------------------------------------------------------------
    ref_video_path = resolve_audio_source(blueprint, blueprint_path, audio_source)
    if ref_video_path and resolved_mix != AudioMixMode.CLIP_ONLY:
        logger.info("[10] Placing reference audio ({}) ...", resolved_mix.value)
        audio_out_dir = os.path.dirname(os.path.abspath(blueprint_path))
        audio_wav     = extract_reference_audio(ref_video_path, output_dir=audio_out_dir)
        if audio_wav:
            audio_item = import_audio_to_media_pool(resolve_ctrl, audio_wav)
            if audio_item:
                audio_dur    = get_audio_duration(audio_wav)
                audio_placed = place_audio_on_timeline(
                    resolve_ctrl, timeline, audio_item, audio_dur,
                )
                if audio_placed:
                    logger.info("  Audio on timeline: {:.2f}s | mode={}", audio_dur, resolved_mix.value)
    else:
        logger.info("[10] Audio track skipped (mode={})", resolved_mix.value)

    # ------------------------------------------------------------------
    # Step 11: Render captions
    # ------------------------------------------------------------------
    logger.info("[11] Rendering captions ...")
    srt_path = render_captions(
        resolve_ctrl=resolve_ctrl,
        timeline=timeline,
        blueprint=blueprint,
        output_dir=caption_output_dir,
    )

    # ------------------------------------------------------------------
    # Step 12: Quality analysis
    # ------------------------------------------------------------------
    logger.info("[12] Running quality analysis ...")
    try:
        qr = analyze_edit_quality(
            plan=plan,
            blueprint=blueprint,
            clip_assignments=clip_assignments,
            semantic_profiles=semantic_analyses,
        )
        quality_report = qr.to_dict()
        if effect_summary:
            quality_report["effect_summary"] = effect_summary
        # Write report alongside blueprint
        report_path = os.path.join(
            os.path.dirname(os.path.abspath(blueprint_path)),
            "quality_report.json",
        )
        qr.write_json(report_path)
        logger.info(
            "  Quality: overall={:.1f} diversity={:.1f} beat={:.1f} pacing={:.1f}",
            qr.overall_score, qr.diversity_score, qr.beat_alignment, qr.pacing_consistency,
        )
    except Exception as e:
        logger.warning("Quality analysis failed (non-fatal): {}", e)
        quality_report = None

    # ------------------------------------------------------------------
    # Optional: Auto-render
    # ------------------------------------------------------------------
    render_status = None
    if render_output:
        logger.info("Auto-render -> {}", render_output)
        from editor.export_manager import queue_render, start_and_wait
        job_id = queue_render(
            resolve_ctrl, render_output,
            profile=render_profile or ("youtube_vertical" if is_vertical else "youtube_1080p"),
            timeline=timeline,
        )
        if job_id:
            render_status = start_and_wait(resolve_ctrl, job_id)
        else:
            render_status = {"JobStatus": "Failed", "Error": "Queue failed"}

    elapsed = time.perf_counter() - t_start
    logger.info("=" * 60)
    logger.info("Blueprint Executor — COMPLETE in {:.1f}s", elapsed)
    logger.info("Timeline : {} | Slots: {} | Placed: {} | Audio: {}",
                tl_name, plan.total_slots, len(placed_items),
                "placed" if audio_placed else "skipped")
    if quality_report:
        logger.info("Quality  : overall={:.1f}", quality_report.get("overall_score", 0))
    logger.info("=" * 60)

    return _make_result(
        True,
        timeline_name=tl_name,
        slots_built=plan.total_slots,
        clips_placed=len(placed_items),
        audio_placed=audio_placed,
        srt_path=srt_path,
        quality_report=quality_report,
        effect_summary=effect_summary,
        render_status=render_status,
        elapsed_secs=round(elapsed, 2),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_blueprint(path: str) -> dict | None:
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        logger.error("Blueprint not found: {}", path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            bp = json.load(f)
        logger.info("Blueprint loaded: v{} | {} cuts | {} beats | {} captions",
                    bp.get("version", "?"), len(bp.get("cuts", [])),
                    len(bp.get("beats", [])), len(bp.get("captions", [])))
        return bp
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to parse blueprint: {}", e)
        return None


def _derive_timeline_name(blueprint_path: str) -> str:
    stem = os.path.splitext(os.path.basename(blueprint_path))[0]
    return f"AI_Edit_{stem}"


def _classify_clips(clip_paths: list) -> dict:
    """Run semantic classification on all clips. Returns {path: [SemanticProfile]}."""
    from analysis.semantic_classifier import classify_clip
    analyses = {}
    logger.info("  Classifying {} clip(s) semantically ...", len(clip_paths))
    for path in clip_paths:
        try:
            profiles = classify_clip(path)
            analyses[path] = profiles
            if profiles:
                mean_energy = sum(p.energy_score for p in profiles) / len(profiles)
                logger.debug(
                    "  Semantic '{}': {}s | mean_energy={:.2f}",
                    os.path.basename(path), len(profiles), mean_energy,
                )
        except Exception as e:
            logger.warning("Semantic classification failed for '{}': {}", path, e)
            analyses[path] = []
    return analyses
