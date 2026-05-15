"""
File system utilities — directory creation, safe naming, path helpers.
"""
import os
import re
from pathlib import Path
from utils.logger import get_logger

logger = get_logger(__name__)


def ensure_dir(path: str) -> str:
    """Create directory (and parents) if it does not exist. Returns path."""
    Path(path).mkdir(parents=True, exist_ok=True)
    return path


def ensure_dirs_exist(dirs: list) -> None:
    """Create each directory in the list if it does not exist."""
    for d in dirs:
        ensure_dir(d)


def safe_filename(name: str) -> str:
    """
    Strip characters that are illegal in file names on Windows and Unix.
    Replaces runs of whitespace with underscores.
    """
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name or "unnamed"


def find_files(directory: str, extensions: set) -> list[str]:
    """
    Return all files under `directory` whose suffix is in `extensions`.
    Extensions should include the dot: {'.mp4', '.mov'}.
    """
    found = []
    for root, _, files in os.walk(directory):
        for fname in files:
            if Path(fname).suffix.lower() in extensions:
                found.append(os.path.join(root, fname))
    return sorted(found)
