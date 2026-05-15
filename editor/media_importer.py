"""
media_importer.py
-----------------
Imports raw footage into the Resolve Media Pool.

Wraps the ResolveController to create bins, validate paths, and return
MediaPoolItem handles needed by timeline_builder.
"""

import os
from utils.logger import get_logger

logger = get_logger(__name__)

SUPPORTED_EXTENSIONS = {
    ".mp4", ".mov", ".mxf", ".avi", ".mkv",
    ".m4v", ".r3d", ".braw", ".wav", ".mp3", ".aac",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def import_media(resolve_ctrl, file_paths: list, bin_name: str = "AI_Imports") -> list:
    """
    Import a list of absolute file paths into the Media Pool.

    Creates a dedicated bin (sub-folder) so imported clips don't clutter the root.
    Returns a list of MediaPoolItem objects in the same order as file_paths
    (missing files are silently skipped).

    Args:
        resolve_ctrl: Connected ResolveController.
        file_paths:   Absolute paths to media files.
        bin_name:     Name of the bin to create/reuse inside the Media Pool.

    Returns:
        List of MediaPoolItem objects.
    """
    resolve_ctrl.require_connection()
    media_pool = resolve_ctrl.media_pool
    root_folder = resolve_ctrl.root_folder

    valid_paths = _validate_paths(file_paths)
    if not valid_paths:
        logger.error("No valid media files to import")
        return []

    ai_bin = _get_or_create_bin(media_pool, root_folder, bin_name)

    logger.info("Setting active folder -> '{}'", ai_bin.GetName())
    media_pool.SetCurrentFolder(ai_bin)

    logger.info("Importing {} file(s) …", len(valid_paths))
    imported = media_pool.ImportMedia(valid_paths)

    if not imported:
        logger.error("ImportMedia returned None — check file formats and codec support")
        return []

    logger.info("Import complete: {}/{} clips succeeded", len(imported), len(valid_paths))
    for item in imported:
        logger.debug("  ✓ {}", item.GetName())

    return imported


def collect_clip_paths(clip_dir: str) -> list:
    """
    Walk clip_dir recursively and return all media file paths.
    Only returns files with extensions in SUPPORTED_EXTENSIONS.
    """
    found = []
    if not os.path.isdir(clip_dir):
        logger.error("Clip directory not found: {}", clip_dir)
        return found

    for root, _dirs, files in os.walk(clip_dir):
        for fname in sorted(files):
            ext = os.path.splitext(fname)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                found.append(os.path.join(root, fname))

    logger.info("Found {} media file(s) in '{}'", len(found), clip_dir)
    return found


def build_clip_index(media_pool_items: list) -> dict:
    """
    Build a {filename_without_ext: MediaPoolItem} lookup dict.
    Useful for matching ranked clip paths back to Resolve handles.
    """
    index = {}
    for item in media_pool_items:
        name = os.path.splitext(item.GetName())[0]
        index[name] = item
    return index


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_paths(paths: list) -> list:
    valid = []
    for p in paths:
        if not os.path.isfile(p):
            logger.warning("File not found, skipping: {}", p)
            continue
        ext = os.path.splitext(p)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            logger.warning("Unsupported extension '{}', skipping: {}", ext, p)
            continue
        valid.append(p)
    return valid


def _get_or_create_bin(media_pool, parent_folder, bin_name: str):
    """Return existing bin or create a new one."""
    existing = {f.GetName(): f for f in (parent_folder.GetSubFolderList() or [])}
    if bin_name in existing:
        logger.debug("Reusing existing bin '{}'", bin_name)
        return existing[bin_name]

    folder = media_pool.AddSubFolder(parent_folder, bin_name)
    if not folder:
        logger.error("AddSubFolder('{}') failed — using root folder", bin_name)
        return parent_folder

    logger.info("Created bin '{}'", folder.GetName())
    return folder
