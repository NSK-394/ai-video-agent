# AI Video Agent

> **Autonomous AI-powered video editing system** — analyzes a reference video's editing style and recreates it automatically inside DaVinci Resolve using your own footage.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](https://www.microsoft.com/windows)
[![DaVinci Resolve](https://img.shields.io/badge/DaVinci_Resolve-18%2B-orange.svg)](https://www.blackmagicdesign.com/products/davinciresolve)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## Overview

AI Video Agent is a modular Python pipeline that bridges computer vision, audio analysis, and professional NLE software. Give it a reference video — a YouTube short, a film trailer, a music video — and it reverse-engineers the edit: detecting every cut, beat, spoken word, and pacing pattern. Then it takes your raw footage, scores each clip intelligently, and reconstructs a beat-synchronized, semantically coherent edit directly inside DaVinci Resolve.

The system is designed around a **blueprint** — a structured JSON file that captures the full editing DNA of a reference video — acting as the data contract between the analysis and editing layers.

```
Reference Video  ──→  Blueprint Extraction  ──→  Clip Intelligence  ──→  Resolve Timeline
     (any .mp4)           (blueprint.json)        (scored + ranked)       (auto-assembled)
```

---

## Demo

> **Note:** Demo GIFs and output screenshots are planned for the v1.0 release. See [`docs/demo_workflow.md`](docs/demo_workflow.md) for a walkthrough with example output data.

**What a typical run produces:**
- A beat-synchronized DaVinci Resolve timeline built from your footage
- Cinematic zoom, speed ramp, and transition effects applied automatically
- Reference audio track imported and aligned
- `captions.srt` subtitle file generated from speech
- `quality_report.json` scoring diversity, beat-alignment, and pacing consistency

---

## Features

### Analysis Engine
- **Cut detection** — PySceneDetect (primary) with OpenCV histogram fallback; configurable sensitivity
- **Beat tracking** — librosa onset detection; BPM estimation, beat categorization (major / drop / buildup)
- **Speech transcription** — OpenAI Whisper with word-level timestamps → `captions.srt`
- **Editing style classification** — `fast_cut`, `slow_burn`, `beat_synced`, `dialogue_driven`, `mixed`
- **Blueprint generation** — self-contained JSON capturing cuts, beats, captions, pacing, and metadata

### Clip Intelligence
- **Semantic classification** — per-clip visual profiling: motion speed, shot scale, tone, energy level, color mood
- **Motion scoring** — mean absolute deviation (MAD) on downscaled frames; per-second granularity
- **Diversity memory** — four-factor penalty system prevents clip repetition across slots
- **Hook prioritization** — first N slots biased toward high-energy clips for maximum viewer retention
- **Pacing curve matching** — per-slot energy targets derived from edit style and beat density

### Effect Engine (5 cinematic modules)
- **Visual energy mapper** — per-slot combined energy from beats + semantics + pacing
- **Impact detector** — IBI analysis finds drops, buildups, and major beats for effect triggers
- **Camera animation** — static zoom/pan directives (Ken Burns style) with preset intensity
- **Motion effects** — speed ramps (130–200%) and slow motion (40–60%) keyed to energy
- **Smart transitions** — beat-aware dissolve, dip-to-black, dip-to-white, and cut decisions

### Effect Presets
| Preset | Style |
|--------|-------|
| `subtle` | Gentle zoom, soft dissolves, minimal speed change |
| `cinematic` | Moderate zoom, dip-to-black on drops, slow-mo on calm (default) |
| `aggressive` | Hard cuts, max speed ramps, maximum zoom |
| `anime` | Dip-to-white on drops, high zoom, fast/slow extremes |
| `gaming` | Hard cuts, speed ramps, maximum energy throughout |

### Audio & Caption
- Reference audio extraction and timeline placement (48 kHz stereo WAV via FFmpeg)
- Three mix modes: `reference_only`, `clip_only`, `hybrid_mix`
- EBU R128 loudness normalization (two-pass ffmpeg loudnorm)
- Caption rendering to `.srt` from Whisper transcription

### Quality Reporting
Six-factor quality score written to `quality_report.json` after every edit:

| Factor | Weight | Measures |
|--------|--------|---------|
| Diversity | 25% | Clip variety across all slots |
| Beat alignment | 25% | Cut points near musical beats |
| Pacing consistency | 15% | Energy curve match to blueprint |
| Semantic match | 15% | Visual character fit per slot |
| Hook strength | 10% | Energy of opening slots |
| Repetition penalty | 10% | Frequency of identical clip reuse |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        AI VIDEO AGENT                           │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   ANALYSIS LAYER                         │  │
│  │                                                          │  │
│  │  Reference Video ──► Cut Detector ──► cuts[]            │  │
│  │       (.mp4)     ──► Beat Tracker ──► beats[]           │  │
│  │                  ──► Whisper STT  ──► captions[]        │  │
│  │                  ──► Style Analyzer ► edit_rhythm{}     │  │
│  │                        │                                │  │
│  │                        ▼                                │  │
│  │                  blueprint.json                         │  │
│  └──────────────────────────────────────────────────────────┘  │
│                           │                                     │
│                           ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    EDITOR LAYER                          │  │
│  │                                                          │  │
│  │  Raw Clips ──► Semantic Classifier ──► SemanticProfile  │  │
│  │            ──► Motion Scorer       ──► per-second MAD   │  │
│  │            ──► Clip Ranker         ──► slot assignments │  │
│  │                 (motion × semantic × diversity × hook)  │  │
│  │                        │                                │  │
│  │  Blueprint ──► Pacing Engine ──► EditPlan               │  │
│  │            ──► Beat Sync     ──► snapped cut points     │  │
│  │                        │                                │  │
│  │            ──► Timeline Builder ──► Resolve Timeline    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                           │                                     │
│                           ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   EFFECT ENGINE                          │  │
│  │                                                          │  │
│  │  EnergyMap ──► Camera Animation ──► zoom/pan directives │  │
│  │            ──► Motion Effects   ──► speed ramps         │  │
│  │            ──► Smart Transitions──► dissolve/cut/dip    │  │
│  │  ImpactTimeline ──► trigger points for effects          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                           │                                     │
│                           ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │               RESOLVE INTEGRATION                        │  │
│  │                                                          │  │
│  │  Audio Manager ──► extract + import reference audio     │  │
│  │  Caption Renderer ──► .srt subtitle file                │  │
│  │  Export Manager ──► render queue + format profiles      │  │
│  │  Quality Analyzer ──► quality_report.json               │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Pipeline Workflow

```
Step 1   python main.py analyze --video reference.mp4
         │
         └─► Extracts: cuts, beats, BPM, captions, style
             Writes:   reference/extracted_data/blueprint.json

Step 2   python main.py edit --blueprint blueprint.json --clips assets/clips/
         │
         ├─► [3]  Semantic classification of all raw clips
         ├─► [4]  Build pacing curve + beat categories
         ├─► [5]  Rank clips: motion × semantic × diversity × hook scores
         ├─► [6]  Build EditPlan from blueprint timing
         ├─► [7]  Beat-sync snap (aggressiveness configurable)
         ├─► [8]  Build Resolve timeline
         ├─► [8.5] Apply cinematic effect engine
         ├─► [9]  Apply transitions
         ├─► [10] Place reference audio track
         ├─► [11] Render captions → captions.srt
         └─► [12] Generate quality_report.json

Step 3   (Optional) Inside Resolve, run:
         Workspace > Scripts > Utility > run_blueprint
         (uses app.GetResolve() Fusion context for direct API access)
```

---

## Semantic Editing System

The semantic classifier analyzes each raw clip using OpenCV heuristics to produce a `SemanticProfile` — a structured characterization of a clip segment's visual properties.

**Extracted features per segment:**
| Feature | Values |
|---------|--------|
| `motion_speed` | `static`, `slow`, `medium`, `fast`, `very_fast` |
| `shot_scale` | `closeup`, `medium`, `wide` |
| `tone` | `dark`, `neutral`, `bright` |
| `energy_level` | `calm`, `moderate`, `energetic`, `intense` |
| `color_mood` | `warm`, `cool`, `neutral` |
| `energy_score` | 0.0 – 1.0 |
| `cinematic_score` | 0.0 – 1.0 |

These profiles drive the **semantic score engine**, which maps each edit slot's position and pacing zone to a set of desired tags, then scores every candidate clip segment for fit. The final clip ranking formula:

```
effective_score = motion_score
                × semantic_multiplier    (0.5 – 1.5)
                × hook_multiplier        (1.0 or 1.5 for hook slots)
                × diversity_penalty      (0.01 – 1.0)
```

---

## Beat Synchronization

The beat-sync system operates in two passes:

1. **Beat categorization** — beats are classified as `major` (every 4th beat / downbeats), `drop` (IBI < 75% of rolling average), or `minor`
2. **Advanced snap** — each planned cut is moved to the nearest beat within a tolerance window, with `aggressiveness` (0–1) controlling how hard cuts are pulled toward beats

The **pacing curve** is style-aware:
- `fast_cut` → flat high energy
- `slow_burn` → gradual ramp
- `beat_synced` → peaks at detected drops
- `mixed` → sinusoidal wave

---

## DaVinci Resolve Integration

The system supports **two connection modes**:

| Mode | Usage | Connection |
|------|-------|------------|
| **Fusion Script** | Run inside Resolve: `Workspace > Scripts > run_blueprint` | `app.GetResolve()` (Fusion global) |
| **External Script** | Run from terminal: `python main.py edit ...` | DaVinciResolveScript module via `RESOLVE_SCRIPT_API` env var |

**API operations used:**
- `media_pool.ImportMedia([paths])` — import clips
- `media_pool.CreateEmptyTimeline(name)` — create timeline
- `media_pool.AppendToTimeline([clip_dicts])` — place clips with in/out points
- `timeline_item.SetProperty("ZoomX", val)` — camera zoom
- `timeline_item.SetClipProperty("Speed", str(pct))` — speed ramps
- `project.SetCurrentTimeline(timeline)` — activate timeline

---

## Installation

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10 – 3.12 | 3.11 recommended |
| DaVinci Resolve Studio | 18+ | Free version lacks Python API |
| FFmpeg | 6.0+ | Must be on system `PATH` |
| Git | Any | For cloning |

### 1 — Clone the repository

```bash
git clone https://github.com/NSK-394/ai-video-agent.git
cd ai-video-agent
```

### 2 — Create a virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
```

### 3 — Install Python dependencies

```bash
pip install -r requirements.txt
```

> **First run:** Whisper will download the selected model (~150 MB for `base`) automatically.

### 4 — Install FFmpeg

Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to `PATH`:

```powershell
# Windows (via winget)
winget install Gyan.FFmpeg
```

Verify:
```bash
ffmpeg -version
```

### 5 — Configure DaVinci Resolve scripting

In DaVinci Resolve: **Preferences → System → General**
- Enable **"External scripting using"** → set to `Local`

Set the environment variable so the external script can find Resolve's API:

```bash
# .env file (copy from .env.example)
RESOLVE_SCRIPT_API=C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting
```

The default path is used automatically on Windows if the env var is not set.

### 6 — Configure environment

```bash
copy .env.example .env
# Edit .env with your settings
```

### Troubleshooting

| Problem | Solution |
|---------|----------|
| `No module named 'DaVinciResolveScript'` | Set `RESOLVE_SCRIPT_API` in `.env`; ensure Resolve is running |
| `No module named 'loguru'` | Install with `pip install loguru`; the logger falls back to stdlib automatically inside Resolve |
| `ffmpeg not found` | Add FFmpeg to system `PATH` and restart terminal |
| `No module named 'whisper'` | `pip install openai-whisper` |
| Fusion script can't find project modules | Check `PROJECT_DIR` in `run_blueprint.py` matches your clone path |

---

## Usage

### Analyze a reference video

```bash
python main.py analyze --video path/to/reference.mp4
```

Options:
```
--output-dir DIR        Directory for blueprint.json (default: next to video)
--cut-threshold FLOAT   Cut sensitivity — lower = more cuts (default: 27.0)
--whisper-model SIZE    tiny | base | small | medium | large (default: base)
--skip-captions         Skip speech transcription (faster)
```

### Execute the edit in Resolve

```bash
python main.py edit \
  --blueprint reference/extracted_data/blueprint.json \
  --clips assets/clips/
```

Full options:
```
--blueprint PATH        Path to blueprint.json (required)
--clips DIR             Folder with raw footage (required)
--project NAME          Resolve project name (default: AI_Editor_Project)
--timeline-name NAME    Override output timeline name
--render PATH           Auto-render to this file after editing
--render-profile        youtube_1080p | youtube_vertical | prores_proxy | h265_4k
--transition            cut | dissolve (default: cut)
--no-beat-sync          Disable beat-snapping
--caption-dir DIR       Directory for captions.srt
--audio-source PATH     Override reference audio path
--mute-clips            Strip clip audio (use reference audio only)
```

### Run inside DaVinci Resolve (recommended)

1. Edit the `CONFIG` block in `run_blueprint.py` (at top of file)
2. In Resolve: **Workspace → Scripts → Utility → run_blueprint**
3. Watch the Fusion console for progress

---

## Example Workflow

```bash
# 1. Analyze a Spider-Man edit from YouTube
python main.py analyze \
  --video reference/demo_videos/spiderman_edit.mp4 \
  --whisper-model base

# Output:
# Blueprint written
#   Cuts    : 5
#   Beats   : 27
#   Style   : beat_synced
#   BPM     : 136.0
#   Avg cut : 2.70s

# 2. Run the edit with cinematic effects (inside Resolve via Fusion Script)
# Edit run_blueprint.py:
#   EFFECT_PRESET = "cinematic"
#   BEAT_SYNC = True
#   MIX_MODE = "reference_only"
# Then: Workspace > Scripts > Utility > run_blueprint

# 3. Check quality report
cat reference/extracted_data/quality_report.json
```

---

## Folder Structure

```
ai-video-agent/
│
├── main.py                     # CLI entry point (analyze / edit subcommands)
├── run_blueprint.py            # Fusion Script for running inside Resolve
├── requirements.txt
├── .env.example
│
├── analysis/                   # Reference video analysis
│   ├── reference_analyzer.py   # Main orchestrator → blueprint.json
│   ├── cuts.py                 # PySceneDetect + OpenCV cut detection
│   ├── beats.py                # librosa beat tracking
│   ├── captions_extract.py     # Whisper speech-to-text
│   ├── style_analysis.py       # Editing style classification
│   ├── semantic_classifier.py  # Per-clip visual profiling
│   ├── semantic_score_engine.py# Semantic fit scoring
│   ├── clip_ranker.py          # Motion + semantic + diversity ranking
│   ├── hook_selector.py        # Hook slot energy gating
│   ├── diversity_manager.py    # Clip reuse tracking + penalties
│   ├── blueprint_generator.py  # Blueprint assembly
│   └── blueprint_schema.py     # Blueprint dataclass + serialization
│
├── editor/                     # DaVinci Resolve editing pipeline
│   ├── blueprint_executor.py   # 13-step pipeline orchestrator
│   ├── resolve_api.py          # Resolve connection (external + Fusion)
│   ├── pacing_engine.py        # Blueprint → EditPlan conversion
│   ├── beat_sync_editor.py     # Beat-snap + pacing curves
│   ├── timeline_builder.py     # Resolve timeline construction
│   ├── media_importer.py       # Media Pool import
│   ├── effect_engine.py        # Cinematic effect orchestrator
│   ├── visual_energy_mapper.py # Per-slot energy map
│   ├── impact_detector.py      # Drop / buildup / major beat detection
│   ├── camera_animation.py     # Zoom / pan directives
│   ├── motion_effects.py       # Speed ramps + flash frames
│   ├── transition_effects.py   # Smart transition planning
│   ├── transition_mapper.py    # Style → transition type mapping
│   ├── audio_manager.py        # Reference audio extraction + placement
│   ├── audio_mixer.py          # Mix modes + EBU R128 normalization
│   ├── caption_renderer.py     # SRT generation
│   ├── edit_quality_analyzer.py# Post-edit quality scoring
│   └── export_manager.py       # Render queue + format profiles
│
├── config/
│   ├── constants.py            # All thresholds, weights, and defaults
│   └── settings.py             # .env loader
│
├── utils/
│   ├── logger.py               # loguru + stdlib fallback logger
│   ├── ffmpeg_utils.py         # FFmpeg subprocess wrappers
│   ├── video_utils.py          # OpenCV metadata helpers
│   └── file_manager.py         # File I/O utilities
│
├── automation/                 # UI automation fallback (pyautogui)
│   ├── ui_actions.py
│   ├── mouse_control.py
│   └── keyboard_control.py
│
├── docs/
│   ├── demo_workflow.md        # Step-by-step demo with example output
│   ├── architecture.md         # Detailed module design
│   ├── roadmap.md              # Future development plans
│   └── api_notes.md            # DaVinci Resolve API quirks + limitations
│
├── assets/                     # User media (git-ignored)
│   ├── clips/                  # Raw footage goes here
│   └── music/
│
├── reference/                  # Reference videos + blueprints (git-ignored)
│   └── extracted_data/
│       ├── blueprint.json
│       └── quality_report.json
│
└── output/                     # Rendered output (git-ignored)
    ├── rendered/
    ├── temp/
    └── captions/
```

---

## Current Limitations

- **Windows only** — DaVinci Resolve's external scripting path is configured for Windows by default; macOS paths require manual `.env` adjustment
- **DaVinci Resolve Studio required** — Free version of Resolve does not expose the Python scripting API
- **FFmpeg must be on PATH** — The audio extraction uses `subprocess` calls to the system `ffmpeg` binary
- **No frame-level keyframes** — Resolve's scripting API does not expose per-frame keyframe insertion; zoom/pan effects use static `SetProperty` calls
- **Flash frames planned only** — Inserting solid-color generator clips via API is not supported; flash frame directives are logged but not applied
- **Whisper runs on CPU** — Large model transcription can be slow; use `--whisper-model base` for speed
- **Single project at a time** — Pipeline assumes one active Resolve project

---

## Roadmap

See [`docs/roadmap.md`](docs/roadmap.md) for the full list. Highlights:

- [ ] **Color grading transfer** — extract color LUT fingerprint from reference, apply via DCTL
- [ ] **Per-frame keyframe animation** — implement zoom/pan with Resolve Fusion node injection
- [ ] **Cloud rendering** — queue renders via Resolve render API to a remote workstation
- [ ] **MCP integration** — expose analysis + editing as Claude MCP tools for conversational editing
- [ ] **Multi-reference blending** — blend editing styles from multiple reference videos
- [ ] **Real-time preview** — live blueprint editing with instant Resolve timeline update
- [ ] **macOS / Linux support** — abstract platform-specific Resolve API paths
- [ ] **GPU-accelerated semantic analysis** — CUDA-backed OpenCV for faster clip scoring
- [ ] **Web UI** — browser-based interface for blueprint visualization and clip assignment

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 |
| Video analysis | OpenCV, PySceneDetect |
| Audio analysis | librosa, FFmpeg |
| Speech-to-text | OpenAI Whisper |
| NLE integration | DaVinci Resolve Python API |
| UI automation | PyAutoGUI, pynput |
| Logging | loguru (stdlib fallback) |
| Config | python-dotenv |
| Data | JSON blueprints, numpy |

---

## Contributing

Contributions are welcome! Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a pull request.

---

## License

This project is licensed under the MIT License — see [`LICENSE`](LICENSE) for details.

---

## Credits

Built by [Nikhil](https://github.com/NSK-394) as an AI systems engineering project combining computer vision, audio analysis, and professional NLE automation.

**Powered by:**
- [DaVinci Resolve](https://www.blackmagicdesign.com/products/davinciresolve) — professional NLE by Blackmagic Design
- [OpenAI Whisper](https://github.com/openai/whisper) — speech recognition
- [librosa](https://librosa.org/) — audio and music analysis
- [PySceneDetect](https://www.scenedetect.com/) — scene cut detection
- [OpenCV](https://opencv.org/) — computer vision
