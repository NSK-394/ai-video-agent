# Editing Workflow

This document describes the full pipeline from raw footage to finished Resolve timeline.

---

## Overview

```
  python main.py analyze --video reference.mp4
             |
             +---> blueprint.json  (edit DNA)
                           |
  python main.py edit --blueprint blueprint.json --clips clips/
             |
             +---> DaVinci Resolve Timeline + quality_report.json
```

---

## Step 1 — Ingest

**User provides:**
- A reference video (any `.mp4`, `.mov`, etc.) — the edit you want to replicate
- Raw footage clips in `assets/clips/` — your source material for the new edit

---

## Step 2 — Analyze Reference Video

**Command:** `python main.py analyze --video reference.mp4`

1. `cuts.py` — PySceneDetect `ContentDetector` detects scene changes; OpenCV histogram L2 fallback fires if fewer than 2 cuts are found.
2. `beats.py` — `librosa.beat.beat_track()` extracts onset times and estimates BPM.
3. `captions_extract.py` — Whisper transcribes speech with word-level timestamps.
4. `style_analysis.py` — Classifies edit rhythm: `fast_cut` / `slow_burn` / `beat_synced` / `dialogue_driven` / `mixed`.
5. `blueprint_generator.py` — Assembles everything into `blueprint.json`.

---

## Step 3 — Semantic Classification

For each clip in `assets/clips/`, `semantic_classifier.py` profiles visual properties:
motion speed, shot scale, tone, color mood, and energy score.

---

## Step 4 — Pacing Curve + Beat Categories

Beats are categorized as major (every 4th), drop (IBI 25%+ shorter), or buildup (IBI 20%+ longer).
A per-slot energy curve is computed based on edit style.

---

## Step 5 — Clip Ranking

`clip_ranker.py` scores every clip against every slot:

```
effective_score = motion x semantic_multiplier x hook_multiplier x diversity_penalty
```

`DiversityMemory` applies consecutive (0.05x), cooldown, frequency-decay (0.4x per reuse),
and temporal-proximity penalties to ensure variety across all slots.

---

## Step 6 — EditPlan

`pacing_engine.py` converts blueprint cuts into `EditPlan` — a list of `EditSlot` objects
with target duration, clip assignment, and transition type.

---

## Step 7 — Beat-Sync Snap

Cut points are snapped toward the nearest beat:
```
snapped = planned x (1 - aggressiveness) + nearest_beat x aggressiveness
```
Default `aggressiveness = 0.8`. Major beats and drops are preferred.

---

## Step 8 — Build Resolve Timeline

`timeline_builder.py` calls Resolve API: create timeline, import clips, append clips
with precise in/out points. `mediaType: 1` strips embedded clip audio in `reference_only` mode.

---

## Step 8.5 — Cinematic Effect Engine

Five sub-modules in sequence:
1. Energy map (per-slot combined energy)
2. Impact detection (drops, buildups, major beats)
3. Camera moves (zoom/pan via SetProperty)
4. Speed ramps and slow motion
5. Smart transitions (dissolve, dip-to-black, cut)

---

## Step 9 — Reference Audio

FFmpeg extracts reference audio as 48 kHz stereo WAV; `audio_manager.py` places it
on Audio Track 1 using `mediaType: 2`.

---

## Step 10 — Captions

`caption_renderer.py` writes `captions.srt` from blueprint word-level timestamps.

---

## Step 11 — Quality Report

`edit_quality_analyzer.py` scores the edit and writes `quality_report.json` with six
weighted metrics: diversity, beat alignment, pacing consistency, semantic match,
hook strength, and repetition penalty.
