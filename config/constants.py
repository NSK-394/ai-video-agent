"""
Static project constants — thresholds, paths, and format definitions.
"""

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ASSETS_DIR = "assets"
OUTPUT_DIR = "output"
REFERENCE_DIR = "reference"
TEMP_DIR = "output/temp"

# ---------------------------------------------------------------------------
# Video defaults
# ---------------------------------------------------------------------------
DEFAULT_FPS = 30.0
RES_1080P = (1920, 1080)
RES_4K = (3840, 2160)
RES_VERTICAL_1080 = (1080, 1920)   # 9:16 short-form
RES_VERTICAL_4K = (2160, 3840)

SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mxf", ".avi", ".mkv", ".m4v", ".r3d", ".braw"}
SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".aac", ".flac", ".m4a"}

# ---------------------------------------------------------------------------
# Cut detection thresholds
# ---------------------------------------------------------------------------
# PySceneDetect ContentDetector: lower = more sensitive (more cuts detected)
SCENEDETECT_THRESHOLD = 27.0
# OpenCV fallback: L2 norm between consecutive histogram vectors
OPENCV_HIST_DIFF_THRESHOLD = 0.35
# Minimum scene length in seconds (avoids flash-frame false positives)
MIN_SCENE_DURATION = 0.5

# ---------------------------------------------------------------------------
# Beat detection
# ---------------------------------------------------------------------------
BEAT_AUDIO_SAMPLE_RATE = 22050   # Hz — standard for librosa
BEAT_HOP_LENGTH = 512            # Frames per hop for onset detection
# A cut is "beat-aligned" if it falls within this window of a beat (seconds)
BEAT_ALIGNMENT_TOLERANCE = 0.08

# ---------------------------------------------------------------------------
# Caption / Whisper
# ---------------------------------------------------------------------------
WHISPER_MODEL_SIZE = "base"      # tiny | base | small | medium | large
WHISPER_LANGUAGE = None          # None = auto-detect
AUDIO_SAMPLE_RATE_WHISPER = 16000  # Hz — Whisper expects 16 kHz mono

# ---------------------------------------------------------------------------
# Blueprint style thresholds
# ---------------------------------------------------------------------------
FAST_CUT_MAX_SECONDS = 2.0       # avg cut duration -> fast_cut
SLOW_BURN_MIN_SECONDS = 6.0      # avg cut duration -> slow_burn
BEAT_SYNC_MIN_RATIO = 0.55       # fraction of cuts aligned to beats -> beat_synced
DIALOGUE_MIN_COVERAGE = 0.65     # fraction of video with speech -> dialogue_driven

# ---------------------------------------------------------------------------
# Blueprint schema
# ---------------------------------------------------------------------------
BLUEPRINT_VERSION = "1.0"
BLUEPRINT_FILENAME = "blueprint.json"

# ---------------------------------------------------------------------------
# Diversity / clip reuse
# ---------------------------------------------------------------------------
DIVERSITY_COOLDOWN_SLOTS       = 2      # slots before same clip re-ranks freely
DIVERSITY_MIN_TEMPORAL_GAP     = 2.0    # sec — min gap between reused time windows
DIVERSITY_FREQUENCY_DECAY      = 0.4    # score multiplier per additional use
DIVERSITY_CONSECUTIVE_PENALTY  = 0.05   # multiplier for back-to-back same clip
DIVERSITY_TEMPORAL_PROXIMITY   = 0.3    # penalty factor near-but-not-overlapping window

# ---------------------------------------------------------------------------
# Semantic classification
# ---------------------------------------------------------------------------
# MAD thresholds for motion_speed labels
SEMANTIC_MOTION_SLOW_MAX    = 3.0
SEMANTIC_MOTION_MEDIUM_MAX  = 8.0
SEMANTIC_MOTION_FAST_MAX    = 20.0
# Edge density (canny edges / pixels) thresholds for shot_scale
SEMANTIC_EDGE_CLOSEUP_MIN   = 0.12
SEMANTIC_EDGE_WIDE_MAX      = 0.04
# Brightness thresholds
SEMANTIC_BRIGHTNESS_DARK    = 60
SEMANTIC_BRIGHTNESS_BRIGHT  = 170
# Contrast (std dev) for cinematic label
SEMANTIC_CONTRAST_CINEMATIC = 45

# ---------------------------------------------------------------------------
# Hook (intro) selection
# ---------------------------------------------------------------------------
HOOK_SLOT_COUNT         = 2     # number of leading slots treated as hook
HOOK_ENERGY_MULTIPLIER  = 1.5   # score boost for hook-slot candidates
HOOK_MIN_ENERGY         = 0.6   # reject clips below this normalised energy at hook slots

# ---------------------------------------------------------------------------
# Beat sync
# ---------------------------------------------------------------------------
BEAT_AGGRESSIVENESS     = 0.8   # 0=no snapping 1=always snap
BEAT_PREFER_MAJOR       = True  # prefer 4/4 downbeats over weak beats
BEAT_MAJOR_INTERVAL     = 4     # every Nth beat is a major/downbeat

# ---------------------------------------------------------------------------
# Audio mixing
# ---------------------------------------------------------------------------
AUDIO_MIX_MODE_DEFAULT      = "reference_only"  # reference_only | clip_only | hybrid_mix
AUDIO_LOUDNORM_TARGET_I     = -14.0   # LUFS integrated
AUDIO_LOUDNORM_TARGET_TP    = -1.0    # dBTP true peak
AUDIO_LOUDNORM_TARGET_LRA   = 7.0     # LU loudness range
AUDIO_FADE_OUT_SECS         = 0.5     # default fade-out on reference audio

# ---------------------------------------------------------------------------
# Quality scoring weights
# ---------------------------------------------------------------------------
QUALITY_WEIGHT_DIVERSITY    = 0.25
QUALITY_WEIGHT_BEAT         = 0.25
QUALITY_WEIGHT_PACING       = 0.15
QUALITY_WEIGHT_SEMANTIC     = 0.15
QUALITY_WEIGHT_HOOK         = 0.10
QUALITY_WEIGHT_REPETITION   = 0.10
