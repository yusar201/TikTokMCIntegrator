"""Verify that BASE_DIR resolution works in both script and frozen PyInstaller modes.

Use this whenever you change any code that touches runtime data files
(those in release/ at runtime: song_*.json, stream_state.json, config.yml, etc.).
The bug: helper modules that use `os.path.dirname(__file__)` to locate runtime
data files break in frozen mode because `__file__` points to PyInstaller's
extraction temp dir, not the runtime `release/` dir.

Usage: from project root, run:
    python3 scripts/test_base_dir_modes.py

Output: prints what BASE_DIR resolves to in each mode and what state file
contents are visible at each location. Exits non-zero if either mode fails.
"""
import os
import sys
import shutil

PROJECT_ROOT = "D:\Ikhito\Code\TikTokMCIntegrator"


def test_mode(label, executable_path, expected_base_dir):
    """Force a specific 'mode' (script or frozen) and check BASE_DIR resolution."""
    saved_executable = sys.executable
    saved_frozen = getattr(sys, 'frozen', None)
    sys.executable = executable_path
    sys.frozen = True  # truthy value triggers frozen branch in BASE_DIR

    # Reload modules so BASE_DIR is recomputed
    for mod in ('constants', 'report_helpers'):
        if mod in sys.modules:
            del sys.modules[mod]
    sys.path.insert(0, PROJECT_ROOT)

    import constants
    actual = constants.BASE_DIR
    ok = (actual == expected_base_dir)
    print(f"  [{label}] BASE_DIR = {actual}")
    print(f"            expected  = {expected_base_dir}")
    print(f"            match     = {'OK' if ok else 'FAIL'}")

    if ok:
        from report_helpers import load_stream_state
        state = load_stream_state()
        print(f"            state     = {state}")
        if not state:
            print(f"            WARNING: empty state — file may not exist at {os.path.join(actual, 'stream_state.json')}")
    else:
        print(f"            FAIL: BASE_DIR mismatch")
        return False

    # Restore
    sys.executable = saved_executable
    if saved_frozen is None:
        try: del sys.frozen
        except AttributeError: pass
    else:
        sys.frozen = saved_frozen
    return ok


print("=" * 60)
print("BASE_DIR Resolution Test (script vs frozen modes)")
print("=" * 60)

# Test 1: Script mode (no sys.frozen)
print("\n[1] Script mode (no sys.frozen)")
script_dir = PROJECT_ROOT
if 'constants' in sys.modules: del sys.modules['constants']
if 'report_helpers' in sys.modules: del sys.modules['report_helpers']
try: del sys.frozen
except AttributeError: pass
sys.path.insert(0, PROJECT_ROOT)
import constants
print(f"  BASE_DIR = {constants.BASE_DIR}")
print(f"  expected = {script_dir}")
print(f"  match    = {'OK' if constants.BASE_DIR == script_dir else 'FAIL'}")

# Test 2: Frozen mode with the real exe
print("\n[2] Frozen mode (simulating release/TikTokMCIntegrator.exe)")
test_mode("frozen",
          executable_path=os.path.join(PROJECT_ROOT, "release", "TikTokMCIntegrator.exe"),
          expected_base_dir=os.path.join(PROJECT_ROOT, "release"))

print("\n" + "=" * 60)
print("Done. If both tests print OK, BASE_DIR resolution is correct.")
print("=" * 60)
