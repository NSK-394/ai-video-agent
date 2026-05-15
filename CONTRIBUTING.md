# Contributing to AI Video Agent

Thank you for your interest in contributing! This document explains how to set up your development environment, the project conventions, and how to submit changes.

---

## Getting Started

### 1. Fork and clone

```bash
git clone https://github.com/YOUR_USERNAME/ai-video-agent.git
cd ai-video-agent
```

### 2. Set up the development environment

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
```

### 3. Configure your environment

```bash
copy .env.example .env
# Fill in RESOLVE_SCRIPT_API and other settings
```

---

## Project Structure

Before contributing, familiarize yourself with the module layout described in [README.md](README.md#folder-structure). Key design principles:

- **`analysis/`** — pure Python; no Resolve API calls; testable without Resolve installed
- **`editor/`** — all Resolve API calls live here; can be mocked for testing
- **`config/constants.py`** — single source of truth for all thresholds and defaults; no magic numbers elsewhere
- **`utils/logger.py`** — always use `get_logger(__name__)`, never `print()` for diagnostics

---

## Code Conventions

### Logging
```python
from utils.logger import get_logger
logger = get_logger(__name__)

# Use {} placeholders (loguru-style), not %s or f-strings in log calls
logger.info("Processing {} clips in slot {}", len(clips), slot_idx)
logger.warning("No beats found — skipping beat-sync")
logger.debug("Score details: motion={:.3f} semantic={:.3f}", m, s)
```

### Type hints
Use type hints on all public function signatures:
```python
def rank_clips_for_slots(
    clip_paths: list[str],
    slot_durations: list[float],
    allow_reuse: bool = True,
) -> list[dict]:
```

### Constants
All numeric thresholds and defaults belong in `config/constants.py`:
```python
# Good
from config.constants import BEAT_ALIGNMENT_TOLERANCE
if delta < BEAT_ALIGNMENT_TOLERANCE:
    ...

# Bad
if delta < 0.08:   # magic number
    ...
```

### No hardcoded paths
All paths must be relative or come from environment variables / function arguments. Never hardcode absolute paths in library code.

### Comments
Only comment the *why*, not the *what*. Well-named identifiers explain what; comments explain non-obvious constraints or workarounds:
```python
# Good: documents a non-obvious API constraint
# SetProperty returns False (not raises) on failure — check explicitly
result = item.SetProperty("ZoomX", zoom)
if result is False:
    logger.warning(...)

# Bad: restates the code
# Set the zoom property
result = item.SetProperty("ZoomX", zoom)
```

---

## Making Changes

### Branch naming
```
feature/short-description
fix/short-description
docs/short-description
refactor/short-description
```

### Commit messages
Use imperative mood, present tense:
```
Add semantic score caching for large clip sets
Fix EnergyPoint comparison bug in camera_animation
Update beat aggressiveness default to 0.8
```

### Before submitting a PR

1. **Test your changes** — at minimum, run the dry-run test to verify all effect modules load:
   ```bash
   python -c "from editor.effect_engine import build_and_apply_effects; print('OK')"
   ```

2. **Run imports check** — ensure all modules import cleanly:
   ```bash
   python -c "import analysis.clip_ranker, editor.blueprint_executor, config.constants; print('All imports OK')"
   ```

3. **Check for regressions** — if you changed `analysis/`, re-analyze a test video and compare the blueprint output. If you changed `editor/`, run the pipeline against a known blueprint and verify clip count and quality score.

4. **Update docs** — if you added/changed a public API, update the relevant docstring and any relevant section of `README.md` or `docs/`.

---

## Areas Where Contributions Are Welcome

- **Tests** — `tests/` directory currently has placeholder stubs; real unit tests are high value
- **macOS / Linux support** — Resolve path handling and environment setup for non-Windows platforms
- **GPU acceleration** — OpenCV CUDA backend for faster semantic classification
- **MCP integration** — `mcp/` module is scaffolded but not implemented
- **Color grading** — LUT extraction from reference video and application via DCTL
- **Documentation** — demo GIFs, screenshots, and more thorough API docs

---

## Reporting Bugs

Please open a GitHub issue with:
- OS and Python version
- DaVinci Resolve version
- Full error traceback
- Minimal reproduction steps (which command, which files)

---

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
