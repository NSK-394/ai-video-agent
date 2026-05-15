"""
Centralized logging configuration.
Uses loguru when available (external Python); falls back to stdlib logging
(Resolve's bundled Python does not have loguru installed).
"""

import sys
from pathlib import Path

try:
    from loguru import logger as _loguru_logger
    _HAS_LOGURU = True
except ImportError:
    _HAS_LOGURU = False

_configured = False
_LOG_DIR = Path(__file__).parent.parent / "logs"


# ---------------------------------------------------------------------------
# Loguru path
# ---------------------------------------------------------------------------

def _configure_loguru():
    global _configured
    if _configured:
        return

    _LOG_DIR.mkdir(exist_ok=True)

    _loguru_logger.remove()

    _loguru_logger.add(
        sys.stderr,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{extra[module]}</cyan> | "
            "{message}"
        ),
        level="DEBUG",
        colorize=True,
        enqueue=True,
    )

    _loguru_logger.add(
        str(_LOG_DIR / "ai_editor_{time:YYYY-MM-DD}.log"),
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | "
            "{level: <8} | "
            "{extra[module]} | "
            "{message}"
        ),
        level="DEBUG",
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
        enqueue=True,
    )

    _configured = True


# ---------------------------------------------------------------------------
# Stdlib fallback — thin wrapper that mimics the loguru interface
# ---------------------------------------------------------------------------

class _StdlibLogger:
    """Minimal loguru-compatible logger backed by stdlib logging."""

    def __init__(self, name: str):
        import logging
        self._log = logging.getLogger(name)
        if not self._log.handlers:
            _configure_stdlib()

    # loguru uses .format()-style {} placeholders; convert to % for stdlib
    @staticmethod
    def _fmt(msg, *args):
        if args:
            try:
                return msg.format(*args)
            except Exception:
                return msg
        return msg

    def debug(self, msg, *args, **_kw):
        self._log.debug(self._fmt(msg, *args))

    def info(self, msg, *args, **_kw):
        self._log.info(self._fmt(msg, *args))

    def warning(self, msg, *args, **_kw):
        self._log.warning(self._fmt(msg, *args))

    def error(self, msg, *args, **_kw):
        self._log.error(self._fmt(msg, *args))

    def exception(self, msg, *args, **_kw):
        self._log.exception(self._fmt(msg, *args))

    # bind() is a loguru concept — return self (module name already set)
    def bind(self, **_kw):
        return self


_stdlib_configured = False


def _configure_stdlib():
    global _stdlib_configured
    if _stdlib_configured:
        return
    import logging

    _LOG_DIR.mkdir(exist_ok=True)

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%H:%M:%S"

    handler_console = logging.StreamHandler(sys.stderr)
    handler_console.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

    try:
        log_file = _LOG_DIR / "ai_editor.log"
        handler_file = logging.FileHandler(str(log_file), encoding="utf-8")
        handler_file.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        )
        handlers = [handler_console, handler_file]
    except Exception:
        handlers = [handler_console]

    logging.basicConfig(level=logging.DEBUG, handlers=handlers)
    _stdlib_configured = True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_logger(name: str):
    """Return a logger bound to the given module name."""
    if _HAS_LOGURU:
        _configure_loguru()
        return _loguru_logger.bind(module=name)
    return _StdlibLogger(name)
