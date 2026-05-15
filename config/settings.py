"""
Configuration loading — reads .env and returns a flat settings dict.
"""
import os
from dotenv import load_dotenv


def load_settings() -> dict:
    """
    Load environment variables from .env (if present) and return settings.

    Returns a dict with keys used throughout the application.
    Missing optional keys return None.
    """
    load_dotenv()

    return {
        "RESOLVE_SCRIPT_API": os.getenv(
            "RESOLVE_SCRIPT_API",
            r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting",
        ),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "LOG_LEVEL":      os.getenv("LOG_LEVEL", "INFO"),
        "WHISPER_MODEL":  os.getenv("WHISPER_MODEL", "base"),
    }
