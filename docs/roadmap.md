# Roadmap

This document tracks planned improvements and future development directions for AI Video Agent.

Items are grouped by category and rough priority. Contributions on any of these are welcome — see [CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Near-term (v1.1)

### Stability & Testing
- [ ] Real unit tests for `analysis/cuts.py`, `analysis/beats.py`, `analysis/clip_ranker.py`
- [ ] Integration test that runs the full pipeline against a fixture blueprint (no Resolve required)
- [ ] `pytest` configuration with fixtures and CI via GitHub Actions
- [ ] Type checking pass (`mypy` or `pyright`) on public APIs

### Platform Support
- [ ] macOS path handling for Resolve scripting API
- [ ] Linux support (Resolve 19+ supports Linux scripting)
- [ ] Auto-detect Resolve install path across platforms

### Effect Engine Improvements
- [ ] Flash frame implementation — insert solid-color generator clips via Fusion node injection
- [ ] Per-frame keyframe animation — zoom/pan with actual keyframe curves instead of static `SetProperty`
- [ ] Color temperature effect — warm/cool tint per slot based on semantic mood

---

## Medium-term (v1.2)

### Color Grading Transfer
- [ ] Extract dominant color palette and LUT fingerprint from reference video
- [ ] Apply extracted LUT to timeline clips via Resolve DCTL scripting
- [ ] Match brightness/contrast curve from reference to output

### Audio Intelligence
- [ ] Multi-source audio mixing — true `hybrid_mix` with per-track level control
- [ ] Beat-reactive audio effects — dynamic volume ducking on cuts
- [ ] Automatic SFX placement at impact moments (whoosh on transitions, hit on cuts)

### Semantic Analysis Upgrades
- [ ] Replace OpenCV heuristics with a lightweight CLIP-based semantic classifier
- [ ] Face detection for shot-scale refinement (closeup = face detected)
- [ ] Object/scene tagging for thematic coherence (e.g., "action" clips near action moments)

---

## Long-term (v2.0)

### MCP Integration
- [ ] Expose `analyze_video` as a Claude MCP tool — conversational blueprint generation
- [ ] Expose `edit_timeline` as a Claude MCP tool — AI-directed timeline adjustments
- [ ] Real-time blueprint editing with instant Resolve preview updates
- [ ] Multi-turn dialogue for iterative edit refinement

### Multi-Reference Blending
- [ ] Analyze multiple reference videos and blend their editing DNA
- [ ] Weighted style mixing — "70% fast_cut, 30% beat_synced"
- [ ] Style interpolation over timeline (fast opening → slow outro)

### Cloud & Collaboration
- [ ] Cloud render queue — submit render jobs to remote Resolve workstation
- [ ] Blueprint sharing — export/import blueprints as shareable editing templates
- [ ] Web UI — browser-based blueprint visualization and clip assignment

### GPU Acceleration
- [ ] CUDA-backed OpenCV for semantic classification (10–50× faster on GPU)
- [ ] Batch Whisper inference on GPU
- [ ] Parallel clip analysis using `concurrent.futures`

---

## Known Limitations (to address)

| Limitation | Planned Fix |
|------------|-------------|
| Windows-only default paths | Platform detection + macOS/Linux path constants |
| Static zoom (no keyframes) | Fusion node-based keyframe injection |
| Flash frames only planned | Fusion generator clip insertion |
| No real unit tests | Full pytest suite targeting analysis layer |
| MCP module is scaffolding | Full `fastmcp` implementation with `stdio` transport |
| Single project assumption | Multi-project session management in `resolve_api.py` |
