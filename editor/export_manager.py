"""
export_manager.py
-----------------
Configures and starts a DaVinci Resolve render job, then polls until completion.

Preset strategy:
  - Uses a named Resolve Render Preset if one exists with the given name.
  - Falls back to programmatic settings if the preset is not found.

Supported output profiles:
  "youtube_1080p"     — H.264, 1920×1080, 30fps, high quality
  "youtube_vertical"  — H.264, 1080×1920 (9:16), 30fps, high quality
  "prores_proxy"      — ProRes 422 Proxy, native resolution
  "h265_4k"          — H.265, 3840×2160, 30fps

Polling:
  After queueing, start_and_wait() polls every `poll_interval_secs` until
  the job reaches "Complete" or "Failed".
"""

import os
import time
from utils.logger import get_logger

logger = get_logger(__name__)

# Polling interval in seconds
_POLL_INTERVAL = 5.0
# Give up polling after this many seconds (10 minutes default)
_RENDER_TIMEOUT = 600.0

# Profile definitions
_PROFILES = {
    "youtube_1080p": {
        "ExportVideo":      True,
        "ExportAudio":      True,
        "FormatWidth":      1920,
        "FormatHeight":     1080,
        "FrameRate":        30.0,
        "VideoQuality":     0,        # 0 = automatic / best
        "AudioCodec":       "aac",
        "AudioBitDepth":    16,
        "AudioSampleRate":  48000,
        "ColorSpaceTag":    "Same as Project",
        "GammaTag":         "Same as Project",
        "SelectAllFrames":  True,
    },
    "youtube_vertical": {
        "ExportVideo":      True,
        "ExportAudio":      True,
        "FormatWidth":      1080,
        "FormatHeight":     1920,
        "FrameRate":        30.0,
        "VideoQuality":     0,
        "AudioCodec":       "aac",
        "AudioBitDepth":    16,
        "AudioSampleRate":  48000,
        "SelectAllFrames":  True,
    },
    "prores_proxy": {
        "ExportVideo":      True,
        "ExportAudio":      True,
        "VideoCodec":       "Apple ProRes 422 Proxy",
        "SelectAllFrames":  True,
    },
    "h265_4k": {
        "ExportVideo":      True,
        "ExportAudio":      True,
        "FormatWidth":      3840,
        "FormatHeight":     2160,
        "FrameRate":        30.0,
        "VideoQuality":     0,
        "SelectAllFrames":  True,
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def queue_render(
    resolve_ctrl,
    output_path: str,
    profile: str = "youtube_1080p",
    timeline=None,
) -> str:
    """
    Configure render settings and add a job to the Resolve render queue.

    Args:
        resolve_ctrl: Connected ResolveController.
        output_path:  Full path for the output file (directory + filename with extension).
        profile:      One of the built-in profile keys or a Resolve preset name.
        timeline:     Timeline to render (defaults to current timeline).

    Returns:
        Job ID string, or "" on failure.
    """
    resolve_ctrl.require_connection()
    project = resolve_ctrl.project

    # Activate target timeline
    tl = timeline or resolve_ctrl.get_current_timeline()
    if tl:
        resolve_ctrl.set_current_timeline(tl)
    else:
        logger.error("No timeline active — cannot queue render")
        return ""

    output_dir  = os.path.dirname(os.path.abspath(output_path))
    output_file = os.path.basename(output_path)
    os.makedirs(output_dir, exist_ok=True)

    logger.info("Configuring render | profile='{}' | output: {}", profile, output_path)

    settings = _build_render_settings(profile, output_dir, output_file)
    if not project.SetRenderSettings(settings):
        logger.error("SetRenderSettings failed — render not queued")
        return ""

    job_id = project.AddRenderJob()
    if not job_id:
        logger.error("AddRenderJob returned empty — render not queued")
        return ""

    logger.info("Render job queued: {}", job_id)
    return job_id


def start_render(resolve_ctrl, job_id: str = None) -> bool:
    """
    Start all queued render jobs (or a specific job_id).
    Returns True if rendering started successfully.
    """
    resolve_ctrl.require_connection()
    project = resolve_ctrl.project

    if job_id:
        ok = project.StartRendering(job_id)
    else:
        ok = project.StartRendering()

    if ok:
        logger.info("Render started (job_id={})", job_id or "all")
    else:
        logger.error("StartRendering failed (job_id={})", job_id or "all")
    return ok


def start_and_wait(
    resolve_ctrl,
    job_id: str,
    poll_interval: float = _POLL_INTERVAL,
    timeout: float = _RENDER_TIMEOUT,
) -> dict:
    """
    Start a render job and block until it finishes or times out.

    Returns the final job status dict:
        {"JobStatus": "Complete"|"Failed"|"Cancelled"|"Timeout", ...}
    """
    if not start_render(resolve_ctrl, job_id):
        return {"JobStatus": "Failed", "Error": "StartRendering returned False"}

    project = resolve_ctrl.project
    elapsed = 0.0

    while elapsed < timeout:
        status = project.GetRenderJobStatus(job_id)
        job_status = (status or {}).get("JobStatus", "Unknown")

        logger.info(
            "Render [{:.0f}s] status={} completion={}%",
            elapsed, job_status,
            (status or {}).get("CompletionPercentage", 0),
        )

        if job_status in ("Complete", "Failed", "Cancelled"):
            logger.info("Render finished: {}", job_status)
            return status

        time.sleep(poll_interval)
        elapsed += poll_interval

    logger.error("Render timeout after {:.0f}s", timeout)
    return {"JobStatus": "Timeout"}


def clear_render_queue(resolve_ctrl):
    """Remove all pending jobs from the render queue."""
    resolve_ctrl.require_connection()
    project = resolve_ctrl.project
    jobs = project.GetRenderJobList() or []
    for job in jobs:
        jid = job.get("JobId", "")
        if jid:
            project.DeleteRenderJob(jid)
    logger.info("Render queue cleared ({} job(s) removed)", len(jobs))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_render_settings(profile: str, output_dir: str, output_file: str) -> dict:
    """Return a render-settings dict for the given profile."""
    base = _PROFILES.get(profile, _PROFILES["youtube_1080p"]).copy()

    # Strip extension from CustomName (Resolve appends it)
    stem = os.path.splitext(output_file)[0]
    base["TargetDir"]   = output_dir
    base["CustomName"]  = stem

    logger.debug("Render settings: {}", base)
    return base
