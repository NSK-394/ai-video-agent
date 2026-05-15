"""
test_resolve.py — DaVinci Resolve connectivity check
=====================================================
Run this script OUTSIDE of Resolve (from your terminal) to verify that
the external scripting API is reachable.

Usage:
    python test_resolve.py

Requirements:
    - DaVinci Resolve Studio must be running with a project open
    - RESOLVE_SCRIPT_API must be set in .env (or use the Windows default)
    - "External scripting using Local" must be enabled in Resolve Preferences
"""

import sys
import os

from config.settings import load_settings

settings = load_settings()
api_path = settings["RESOLVE_SCRIPT_API"]
module_path = os.path.join(api_path, "Modules")

print(f"[1] Resolve scripting path : {api_path}")
print(f"[2] Modules path           : {module_path}")

if not os.path.isdir(module_path):
    print(f"\n[ERROR] Modules directory not found: {module_path}")
    print("        Is DaVinci Resolve Studio installed?")
    print("        Set RESOLVE_SCRIPT_API in your .env file.")
    sys.exit(1)

sys.path.insert(0, module_path)
os.environ.setdefault("RESOLVE_SCRIPT_API", api_path)
os.environ.setdefault("RESOLVE_SCRIPT_LIB",
    r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll")

print("[3] Importing DaVinciResolveScript ...")
try:
    import DaVinciResolveScript as dvr
except ImportError as e:
    print(f"\n[ERROR] Could not import DaVinciResolveScript: {e}")
    print("        Ensure Resolve is running and scripting is enabled.")
    sys.exit(1)

print("[4] Connecting to Resolve ...")
resolve = dvr.scriptapp("Resolve")
if not resolve:
    print("\n[ERROR] dvr.scriptapp('Resolve') returned None")
    print("        Is DaVinci Resolve open with a project loaded?")
    sys.exit(1)

pm = resolve.GetProjectManager()
project = pm.GetCurrentProject()
print(f"\n[OK] Connected to Resolve")
print(f"     Project : {project.GetName() if project else '(no project open)'}")
print(f"     Version : {resolve.GetVersionString()}")
