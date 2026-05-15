"""
resolve_api.py
--------------
Core connection layer to DaVinci Resolve.

Supports two execution contexts, tried in order:
  1. External script  — DaVinciResolveScript (Resolve must be running; external
                        scripting must be enabled in Resolve Preferences > General).
  2. Fusion script    — app.GetResolve() (running inside Resolve as a Fusion utility
                        script, where `app` is a Fusion global).

All higher-level editor modules receive a ResolveController instance and call
its properties/methods instead of touching the raw Resolve API directly.
"""

import os
import sys
from utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# External API bootstrap
# ---------------------------------------------------------------------------

_RESOLVE_SCRIPT_API = os.environ.get(
    "RESOLVE_SCRIPT_API",
    r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting",
)
_RESOLVE_SCRIPT_LIB = os.environ.get(
    "RESOLVE_SCRIPT_LIB",
    r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
)
_MODULES_PATH = os.path.join(_RESOLVE_SCRIPT_API, "Modules")


def _is_resolve_running() -> bool:
    """Return True if Resolve.exe is in the Windows process list."""
    try:
        import subprocess
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Resolve.exe", "/NH"],
            capture_output=True, text=True, timeout=3,
        )
        return "Resolve.exe" in result.stdout
    except Exception:
        return False


def _load_external_api():
    """
    Import DaVinciResolveScript and return a Resolve object, or None on failure.
    Checks that Resolve.exe is running BEFORE loading the DLL — loading
    fusionscript.dll when Resolve is not running causes a segfault.
    """
    if not _is_resolve_running():
        logger.debug("Resolve.exe not running — skipping external API")
        return None

    os.environ.setdefault("RESOLVE_SCRIPT_API", _RESOLVE_SCRIPT_API)
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", _RESOLVE_SCRIPT_LIB)

    if _MODULES_PATH not in sys.path:
        sys.path.append(_MODULES_PATH)

    try:
        import DaVinciResolveScript as dvr  # type: ignore
        resolve = dvr.scriptapp("Resolve")
        if resolve:
            logger.debug("External DaVinciResolveScript connected")
            return resolve
        logger.warning("DaVinciResolveScript loaded but scriptapp('Resolve') returned None")
    except ImportError as e:
        logger.debug("DaVinciResolveScript not available: {}", e)
    return None


def _load_fusion_api():
    """
    Use the Fusion-injected global `app` to get Resolve. Only works inside Fusion.
    """
    try:
        resolve = app.GetResolve()  # noqa: F821  (Fusion global)
        if resolve:
            logger.debug("Fusion app.GetResolve() connected")
            return resolve
    except NameError:
        pass
    return None


# ---------------------------------------------------------------------------
# ResolveController
# ---------------------------------------------------------------------------

class ResolveController:
    """
    Thin wrapper around the DaVinci Resolve API.

    Exposes a stable interface used by all editor modules:
        ctrl.resolve          — raw Resolve object
        ctrl.project_manager  — ProjectManager
        ctrl.project          — current Project
        ctrl.media_pool       — MediaPool
        ctrl.root_folder      — root MediaPool Folder

    Call ctrl.connect() before using any other method.
    """

    def __init__(self):
        self.resolve = None
        self.project_manager = None
        self.project = None
        self.media_pool = None
        self.root_folder = None
        self._connected = False

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self, project_name: str = "AI_Editor_Project") -> "ResolveController":
        """
        Connect to a running Resolve instance and populate all handles.
        Raises RuntimeError if connection or project lookup fails.
        Returns self so callers can chain: ctrl = ResolveController().connect()
        """
        logger.info("Connecting to DaVinci Resolve …")

        self.resolve = _load_external_api() or _load_fusion_api()
        if not self.resolve:
            raise RuntimeError(
                "Cannot reach DaVinci Resolve.\n\n"
                "  Option A — External scripting (run from terminal):\n"
                "    1. Open DaVinci Resolve\n"
                "    2. Preferences > General > External scripting using > Local\n"
                "    3. Re-run: py -3.10 main.py edit ...\n\n"
                "  Option B — Fusion Script (recommended, no extra config):\n"
                "    1. Open DaVinci Resolve\n"
                "    2. Workspace > Scripts > Utility > run_blueprint\n"
            )

        self.project_manager = self.resolve.GetProjectManager()
        if not self.project_manager:
            raise RuntimeError("GetProjectManager() returned None")

        self.project = self.project_manager.GetCurrentProject()
        if not self.project:
            logger.info("No open project — loading/creating '{}'", project_name)
            self.project = self.project_manager.LoadProject(project_name)
            if not self.project:
                self.project = self.project_manager.CreateProject(project_name)
            if not self.project:
                raise RuntimeError(f"Could not load or create project '{project_name}'")

        self.media_pool = self.project.GetMediaPool()
        if not self.media_pool:
            raise RuntimeError("GetMediaPool() returned None")

        self.root_folder = self.media_pool.GetRootFolder()
        self._connected = True
        logger.info("Connected | project: {}", self.project.GetName())
        return self

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def require_connection(self):
        if not self._connected:
            raise RuntimeError("ResolveController is not connected — call connect() first")

    # ------------------------------------------------------------------
    # Timeline helpers
    # ------------------------------------------------------------------

    def get_current_timeline(self):
        self.require_connection()
        return self.project.GetCurrentTimeline()

    def set_current_timeline(self, timeline) -> bool:
        self.require_connection()
        ok = self.project.SetCurrentTimeline(timeline)
        if ok:
            logger.debug("Active timeline -> '{}'", timeline.GetName())
        else:
            logger.warning("SetCurrentTimeline failed for '{}'", timeline.GetName())
        return ok

    def get_timeline_fps(self, timeline=None) -> float:
        """Return FPS of the given timeline (or current) as float."""
        tl = timeline or self.get_current_timeline()
        if not tl:
            return 30.0
        try:
            return float(tl.GetSetting("timelineFrameRate"))
        except Exception:
            return 30.0

    # ------------------------------------------------------------------
    # Project settings helpers
    # ------------------------------------------------------------------

    def configure_timeline_for_vertical(self, timeline, fps: float = 30.0):
        """Apply 9:16 (1080×1920) settings to a timeline."""
        self.require_connection()
        settings = {
            "useCustomSettings":      "1",
            "timelineResolutionWidth":  "1080",
            "timelineResolutionHeight": "1920",
            "timelineFrameRate":        str(int(fps)),
        }
        for key, val in settings.items():
            timeline.SetSetting(key, val)
        logger.info("Timeline '{}' configured for 9:16 vertical @ {} fps",
                    timeline.GetName(), int(fps))

    def configure_timeline_for_horizontal(self, timeline, fps: float = 30.0,
                                           width: int = 1920, height: int = 1080):
        """Apply horizontal settings to a timeline."""
        self.require_connection()
        settings = {
            "useCustomSettings":      "1",
            "timelineResolutionWidth":  str(width),
            "timelineResolutionHeight": str(height),
            "timelineFrameRate":        str(int(fps)),
        }
        for key, val in settings.items():
            timeline.SetSetting(key, val)
        logger.info("Timeline '{}' configured for {}×{} @ {} fps",
                    timeline.GetName(), width, height, int(fps))
