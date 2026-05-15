# Demo Workflow

This document walks through a complete end-to-end run of the AI Video Agent pipeline using a real reference video.

---

## Setup Checklist

Before running, confirm:

- [ ] DaVinci Resolve Studio is open with a project loaded
- [ ] Python virtual environment is activated
- [ ] FFmpeg is accessible: `ffmpeg -version` returns output
- [ ] Raw footage clips are in `assets/clips/` (`.mp4`, `.mov`, `.mxf`)
- [ ] Reference video is saved somewhere accessible

---

## Step 1 — Analyze the Reference Video

```bash
python main.py analyze \
  --video reference/demo_videos/my_reference.mp4 \
  --whisper-model base
```

**Expected output:**
```
Blueprint written
  Cuts    : 5
  Beats   : 27
  Style   : beat_synced
  BPM     : 136.0
  Avg cut : 2.70s
```

**What was created:** `reference/demo_videos/blueprint.json`

---

## Step 2 — Inspect the Blueprint

The blueprint captures the full editing DNA of your reference video. Example structure:

```json
{
  "version": "1.0",
  "source_video": {
    "duration_seconds": 13.5,
    "fps": 30.0,
    "width": 720,
    "height": 1280,
    "is_vertical": true,
    "aspect_ratio": "9:16"
  },
  "cuts": [
    { "index": 0, "start_time": 0.0,  "end_time": 3.5,  "duration": 3.5  },
    { "index": 1, "start_time": 3.5,  "end_time": 6.6,  "duration": 3.1  },
    { "index": 2, "start_time": 6.6,  "end_time": 10.6, "duration": 4.0  },
    { "index": 3, "start_time": 10.6, "end_time": 12.1, "duration": 1.4  },
    { "index": 4, "start_time": 12.1, "end_time": 13.5, "duration": 1.4  }
  ],
  "beats": [
    { "index": 0,  "time": 0.093, "frame": 3,  "bpm_local": 136.0 },
    { "index": 1,  "time": 0.557, "frame": 17, "bpm_local": 129.2 }
  ],
  "captions": [
    { "word": "amazing", "start": 1.2, "end": 1.6, "confidence": 0.92 }
  ],
  "edit_rhythm": {
    "style": "beat_synced",
    "dominant_bpm": 136.0,
    "average_cut_duration": 2.7,
    "beat_alignment_ratio": 0.74
  }
}
```

---

## Step 3 — Run the Edit (Terminal Mode)

```bash
python main.py edit \
  --blueprint reference/demo_videos/blueprint.json \
  --clips assets/clips/ \
  --transition dissolve
```

**Expected output:**
```
Execution SUCCESS
  Timeline    : AI_Edit_blueprint
  Slots built : 5
  Clips placed: 5
  Audio track : placed
  SRT captions: reference/demo_videos/captions.srt
  Elapsed     : 12.4s
```

---

## Step 4 — Run the Edit (Inside Resolve — Recommended)

Edit the `CONFIG` block at the top of `run_blueprint.py`:

```python
PROJECT_DIR    = r"C:\path\to\your\ai-video-agent"
BLUEPRINT_PATH = os.path.join(PROJECT_DIR, r"reference\demo_videos\blueprint.json")
CLIPS_DIR      = os.path.join(PROJECT_DIR, r"assets\clips")
TIMELINE_NAME  = "AI_Edit_v1"
TRANSITION     = "dissolve"
BEAT_SYNC      = True
MIX_MODE       = "reference_only"
EFFECT_PRESET  = "cinematic"
```

Then in Resolve: **Workspace → Scripts → Utility → run_blueprint**

**Fusion console output:**
```
========================================================
  AI Blueprint Executor — Fusion Script
========================================================
  Blueprint : ...\blueprint.json
  Clips     : ...\assets\clips
  Timeline  : AI_Edit_v1
  Transition: dissolve | Beat-sync: True
========================================================
  Connected  : My Project
[1] Loading blueprint ...
[2] Using pre-connected ResolveController
[3] Scanning clips and classifying semantics ...
[4] Computing pacing curve ...
[5] Ranking clips ...
[6] Building edit plan ...
[7] Snapping cuts to beats (aggressiveness=0.8) ...
[8] Building Resolve timeline 'AI_Edit_v1' ...
[8.5] Running cinematic effect engine (preset=cinematic) ...
[9] Applying transitions ('dissolve') ...
[10] Placing reference audio (reference_only) ...
[11] Rendering captions ...
[12] Running quality analysis ...
========================================================
  SUCCESS
  Timeline : AI_Edit_v1
  Slots    : 5
  Placed   : 5
  Audio    : placed
  SRT      : ...\captions.srt
  Time     : 18.3s
  Quality  : overall=7.8 diversity=8.2 beat=9.1 pacing=7.4
  Effects  : cam=5 speed=2 flash=0 trans=4
========================================================
```

---

## Step 5 — Review the Quality Report

`reference/demo_videos/quality_report.json`:

```json
{
  "overall_score": 7.8,
  "diversity_score": 8.2,
  "beat_alignment": 9.1,
  "pacing_consistency": 7.4,
  "semantic_match": 7.0,
  "hook_strength": 8.5,
  "repetition_penalty": 8.8,
  "details": {
    "unique_clips_used": 5,
    "total_slots": 5,
    "cuts_on_beat": 4,
    "total_cuts": 5
  }
}
```

---

## Effect Engine Output

The cinematic effect engine applies the following to a 5-slot timeline with `cinematic` preset:

| Slot | Energy | Camera | Speed | Transition |
|------|--------|--------|-------|------------|
| 0 (hook) | 0.82 | zoom 1.06×, pan +0.02 | 130% (hook) | — |
| 1 (hook) | 0.76 | zoom 1.06×, pan −0.02 | 130% (hook) | cut |
| 2 | 0.59 | zoom 1.08×, pan +0.02 | normal | cut (beat) |
| 3 | 0.30 (calm) | zoom 1.0×, pan −0.01 | 50% (slow-mo) | dissolve |
| 4 | 0.68 | zoom 1.08×, pan +0.02 | normal | cut (beat) |

---

## Demo GIFs / Screenshots

> Planned for v1.0 release — contribution welcome!

Placeholders:
- `docs/assets/demo_analyze.gif` — terminal running `analyze` command
- `docs/assets/demo_timeline.png` — Resolve timeline with placed clips
- `docs/assets/demo_quality.png` — quality report output
- `docs/assets/demo_blueprint.png` — blueprint.json structure visualization

---

## CLI Quick Reference

```bash
# Analyze with fast Whisper model
python main.py analyze --video ref.mp4 --whisper-model tiny --skip-captions

# Edit with aggressive beat-sync and render
python main.py edit \
  --blueprint blueprint.json \
  --clips assets/clips/ \
  --no-beat-sync \
  --transition cut \
  --render output/rendered/final.mp4 \
  --render-profile youtube_vertical

# Edit with reference audio, mute all clips
python main.py edit \
  --blueprint blueprint.json \
  --clips assets/clips/ \
  --mute-clips \
  --audio-source reference/demo_videos/original.mp4
```
