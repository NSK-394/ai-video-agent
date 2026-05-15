# Changelog

All notable changes to AI Video Agent are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] — 2026-05-15

### Added

**Analysis Engine**
- `reference_analyzer.py` — full reference video analysis pipeline producing `blueprint.json`
- `cuts.py` — PySceneDetect primary cut detection with OpenCV histogram fallback
- `beats.py` — librosa onset detection; BPM estimation and beat-timestamp extraction
- `captions_extract.py` — OpenAI Whisper speech transcription with word-level timestamps
- `style_analysis.py` — editing style classification (`fast_cut`, `slow_burn`, `beat_synced`, `dialogue_driven`, `mixed`)
- `blueprint_schema.py` — Blueprint dataclass with JSON serialization and validation
- `blueprint_generator.py` — assembles final blueprint from individual analysis components

**Clip Intelligence**
- `semantic_classifier.py` — per-clip visual profiling via OpenCV heuristics (motion speed, shot scale, tone, energy, color mood)
- `semantic_score_engine.py` — maps edit style + pacing zone to desired semantic tags; scores clip fit
- `clip_ranker.py` — four-factor scoring: `motion × semantic × hook × diversity`
- `diversity_manager.py` — `DiversityMemory` class with consecutive, cooldown, frequency-decay, and temporal-proximity penalties
- `hook_selector.py` — energy gate and multiplier for hook (opening) slots

**Editor Pipeline**
- `blueprint_executor.py` — 13-step end-to-end orchestrator
- `pacing_engine.py` — converts blueprint timing into slot-by-slot `EditPlan`
- `beat_sync_editor.py` — `snap_to_beats_advanced()` with aggressiveness control and major-beat preference; `build_pacing_curve()` per edit style; `categorize_beats()` (major / drop / buildup)
- `timeline_builder.py` — builds Resolve timeline from EditPlan; supports `video_only` mode
- `media_importer.py` — Media Pool import with clip index
- `transition_mapper.py` — style-to-transition mapping

**Effect Engine**
- `effect_engine.py` — 5-step cinematic effect orchestrator with preset system
- `visual_energy_mapper.py` — per-slot `EnergyMap` combining beat, semantic, and pacing energy
- `impact_detector.py` — IBI analysis → `ImpactTimeline` with drops, buildups, strongest markers
- `camera_animation.py` — static zoom/pan directives (Ken Burns) keyed to energy and presets
- `motion_effects.py` — speed ramps and slow motion planned from energy map and impact timeline
- `transition_effects.py` — beat-aware transition decisions (dissolve, dip-to-black, dip-to-white, cut)

**Audio & Captions**
- `audio_manager.py` — reference audio extraction via FFmpeg subprocess; Resolve timeline placement; `resolve_audio_source()` with multiple fallback paths
- `audio_mixer.py` — `AudioMixMode` enum (`reference_only`, `clip_only`, `hybrid_mix`); EBU R128 two-pass loudness normalization
- `caption_renderer.py` — SRT file generation from blueprint captions

**Quality & Export**
- `edit_quality_analyzer.py` — `QualityReport` dataclass; six-factor scoring (diversity, beat-alignment, pacing, semantic, hook, repetition)
- `export_manager.py` — render queue with format profiles (`youtube_1080p`, `youtube_vertical`, `prores_proxy`, `h265_4k`)

**Infrastructure**
- `utils/logger.py` — loguru logger with stdlib `_StdlibLogger` fallback (for Resolve's bundled Python)
- `utils/ffmpeg_utils.py` — lazy `import ffmpeg` via `_ffmpeg()` helper; `_get_duration_cv2()` fallback
- `config/constants.py` — comprehensive constants: diversity weights, semantic thresholds, hook parameters, beat aggressiveness, audio mix defaults, quality scoring weights
- `run_blueprint.py` — Fusion Script (`app.GetResolve()`) for running pipeline inside DaVinci Resolve
- `main.py` — CLI entry point with `analyze` and `edit` subcommands

### Fixed
- `camera_animation.py` — `EnergyPoint` object was compared to float directly; fixed to use `.combined_energy` attribute
- `visual_energy_mapper.py` — log format used `%d` instead of `{}` (loguru-style)
- `impact_detector.py` — same log format fix
- `audio_manager.py` — replaced `ffmpeg-python` package calls with `subprocess.run(['ffmpeg', ...])` to work inside Resolve's Python environment
- `utils/logger.py` — replaced hard `from loguru import logger` with try/except fallback for Resolve compatibility

---

## [0.3.0] — 2026-05-10

### Added
- Audio transfer support: extract reference audio, import to Resolve timeline, align to timeline duration
- `AudioMixMode` enum with `reference_only`, `clip_only`, `hybrid_mix`
- `--audio-source` and `--mute-clips` CLI flags
- `mediaType: 1` (video-only) clip placement strips embedded clip audio

---

## [0.2.0] — 2026-05-05

### Added
- Clip diversity system: `DiversityMemory` with four-factor penalty to prevent repeated clip reuse
- Semantic classification using OpenCV heuristics
- Advanced beat-sync with major-beat preference and aggressiveness control
- Hook prioritization for opening slots
- Quality scoring framework

### Fixed
- `No module named 'loguru'` in Resolve's Fusion Python — added stdlib fallback
- `No module named 'ffmpeg'` in Resolve's Fusion Python — made import lazy

---

## [0.1.0] — 2026-04-28

### Added
- Initial modular pipeline: analyze reference video → generate blueprint.json → build Resolve timeline
- Cut detection, beat tracking, Whisper captions
- Basic clip ranking by motion score
- DaVinci Resolve API connection layer (external + Fusion script modes)
