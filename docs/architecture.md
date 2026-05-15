# Architecture

AI Video Agent is organized into four functional layers. Each layer is independently importable and has minimal coupling to the others — the blueprint JSON is the primary data contract between analysis and editing.

---

## Layer Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: ANALYSIS                                              │
│  analysis/          Pure Python — no Resolve dependency         │
│  Input:  reference video (.mp4/.mov)                            │
│  Output: blueprint.json                                         │
└──────────────────────────────┬──────────────────────────────────┘
                               │ blueprint.json
┌──────────────────────────────▼──────────────────────────────────┐
│  Layer 2: EDITOR PIPELINE                                       │
│  editor/            Resolve API calls + pure Python scoring     │
│  Input:  blueprint.json + raw clips folder                      │
│  Output: Resolve Timeline + captions.srt + quality_report.json  │
└──────────────────────────────┬──────────────────────────────────┘
                               │ timeline (Resolve internal)
┌──────────────────────────────▼──────────────────────────────────┐
│  Layer 3: EFFECT ENGINE                                         │
│  editor/effect_engine.py + sub-modules                          │
│  Input:  Resolve timeline items + EnergyMap + ImpactTimeline    │
│  Output: Modified timeline items (zoom, speed, transitions)     │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  Layer 4: INFRASTRUCTURE                                        │
│  config/ utils/ automation/                                     │
│  Constants, logging, FFmpeg wrappers, UI automation fallback    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Module Reference

### `analysis/` — Reference Video Analysis

| Module | Role |
|--------|------|
| `reference_analyzer.py` | Top-level orchestrator; calls all sub-analyzers and assembles blueprint |
| `cuts.py` | PySceneDetect `ContentDetector` primary; OpenCV histogram L2 fallback |
| `beats.py` | `librosa.beat.beat_track()` + onset strength; returns beat timestamps and BPM |
| `captions_extract.py` | `whisper.transcribe()` with `word_timestamps=True`; produces caption segments |
| `style_analysis.py` | Classifies `edit_rhythm.style` from cut durations and beat-alignment ratio |
| `blueprint_schema.py` | `Blueprint` dataclass; `to_dict()` / `from_dict()` / `write_json()` |
| `blueprint_generator.py` | Merges cuts, beats, captions, style → `Blueprint` instance |
| `semantic_classifier.py` | `SemanticProfile` dataclass; per-second visual characterization via OpenCV |
| `semantic_score_engine.py` | `get_desired_tags()` + `score_semantic_match()` → 0–1 affinity score |
| `clip_ranker.py` | `rank_clips_for_slots()` — main scoring loop: motion × semantic × hook × diversity |
| `diversity_manager.py` | `DiversityMemory` — tracks clip usage, returns penalty multipliers |
| `hook_selector.py` | Energy gate and score multiplier for opening (hook) slots |

### `editor/` — DaVinci Resolve Editing Pipeline

| Module | Role |
|--------|------|
| `blueprint_executor.py` | 13-step end-to-end orchestrator; the top-level callable for the edit layer |
| `resolve_api.py` | `ResolveController` — connection layer; external API and Fusion script modes |
| `pacing_engine.py` | `build_edit_plan()` — blueprint timing → `EditPlan` with slot durations |
| `beat_sync_editor.py` | `snap_to_beats_advanced()`, `build_pacing_curve()`, `categorize_beats()` |
| `timeline_builder.py` | `build_timeline()` — creates Resolve timeline; imports + places clips |
| `media_importer.py` | `collect_clip_paths()`, `import_clips_to_pool()` |
| `transition_mapper.py` | `set_slot_transitions()`, `apply_transitions()` |
| `audio_manager.py` | `extract_reference_audio()`, `place_audio_on_timeline()`, `resolve_audio_source()` |
| `audio_mixer.py` | `AudioMixMode` enum, `normalize_audio()` (EBU R128), `get_mix_mode()` |
| `caption_renderer.py` | `render_captions()` → writes `.srt` from blueprint captions |
| `edit_quality_analyzer.py` | `analyze_edit_quality()` → `QualityReport` with six weighted scores |
| `export_manager.py` | `queue_render()`, `start_and_wait()` — render queue management |

### `editor/` — Effect Engine Sub-modules

| Module | Role |
|--------|------|
| `effect_engine.py` | `build_and_apply_effects()` — 5-step orchestrator; returns `EffectSummary` |
| `visual_energy_mapper.py` | `build_energy_map()` → `EnergyMap` with `EnergyPoint` per slot |
| `impact_detector.py` | `detect_impacts()` → `ImpactTimeline` with drops, buildups, strongest markers |
| `camera_animation.py` | `plan_camera_moves()` + `apply_camera_moves()` — zoom/pan via `SetProperty` |
| `motion_effects.py` | `plan_motion_effects()` + `apply_speed_ramp()` — speed via `SetClipProperty` |
| `transition_effects.py` | `plan_transitions()` + `apply_transition_decisions()` — smart per-slot transitions |

### `config/` — Configuration

| Module | Role |
|--------|------|
| `constants.py` | All numeric thresholds and defaults — single source of truth |
| `settings.py` | `load_settings()` — reads `.env` via `python-dotenv` |

### `utils/` — Utilities

| Module | Role |
|--------|------|
| `logger.py` | `get_logger(name)` — returns loguru logger or `_StdlibLogger` fallback |
| `ffmpeg_utils.py` | FFmpeg subprocess wrappers; `_ffmpeg()` lazy import guard |
| `video_utils.py` | OpenCV-based metadata extraction (duration, FPS, resolution) |
| `file_manager.py` | `ensure_dir()`, `safe_filename()` helpers |

---

## Data Flow: Blueprint JSON

The blueprint is the serialized output of the analysis layer and the input contract for the editor layer.

```
Blueprint = {
    "version":      "1.0",
    "metadata":     { analyzed_at, analyzer_version },
    "source_video": { duration_seconds, fps, width, height, is_vertical },
    "cuts": [
        { index, start_time, end_time, duration, start_frame, end_frame, confidence }
    ],
    "beats": [
        { index, time, frame, bpm_local }
    ],
    "captions": [
        { word, start, end, confidence }
    ],
    "edit_rhythm": {
        style, dominant_bpm, average_cut_duration,
        beat_alignment_ratio, total_duration
    }
}
```

---

## Key Design Decisions

**Why subprocess for FFmpeg instead of ffmpeg-python?**
DaVinci Resolve's bundled Python environment does not include pip-installed packages. All third-party imports are guarded with try/except, and critical operations (audio extraction) use `subprocess.run(['ffmpeg', ...])` directly — no package dependency.

**Why loguru with stdlib fallback?**
Same reason — Resolve's Python lacks loguru. `utils/logger.py` implements `_StdlibLogger` which mimics the loguru interface (`{}` placeholders, `.bind()`) so all call sites work identically in both environments.

**Why static `SetProperty` instead of keyframe animation?**
The DaVinci Resolve scripting API does not expose per-frame keyframe insertion on timeline items. The `SetProperty("ZoomX", val)` call sets a clip-wide static property. True animated zoom requires Fusion node injection, which is on the roadmap.

**Why blueprint.json as the interface boundary?**
Separating analysis from editing via a file-based contract enables:
- Running analysis once and editing many times with different settings
- Sharing blueprints as "editing style templates"
- Future cloud analysis → local editing workflows
- Testability of the editor layer without requiring a reference video
