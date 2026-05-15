"""
rendering.py
------------
Low-level rendering primitives. Delegates to export_manager for the full pipeline.
Kept as a compatibility layer for callers using the original interface.
"""

from editor.export_manager import queue_render, start_render, start_and_wait
from utils.logger import get_logger

logger = get_logger(__name__)


def start_render_job(resolve_ctrl, output_path: str, preset: str = "youtube_1080p",
                     wait: bool = False) -> dict:
    """
    Queue and optionally wait for a render to complete.

    Args:
        resolve_ctrl: Connected ResolveController.
        output_path:  Full output file path.
        preset:       Render profile key or Resolve preset name.
        wait:         If True, block until render finishes.

    Returns:
        Final status dict (or {"JobStatus": "Queued"} if wait=False).
    """
    logger.info("Starting render -> {}", output_path)

    job_id = queue_render(resolve_ctrl, output_path, profile=preset)
    if not job_id:
        return {"JobStatus": "Failed", "Error": "Could not queue render job"}

    if wait:
        return start_and_wait(resolve_ctrl, job_id)

    start_render(resolve_ctrl, job_id)
    return {"JobStatus": "Queued", "JobId": job_id}
