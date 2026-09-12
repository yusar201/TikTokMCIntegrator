"""
Centralized path resolution for TikTokMCIntegrator.

Single source of truth for the on-disk layout. Resolves correctly both as a
.py script (dev) and as a frozen PyInstaller .exe (release) via the sys.frozen
check — this is the ONE place that check lives, so the frozen-path bug that bit
report_helpers / constants / gift_assets can't recur per-module.

Layout (relative to the exe in release/, or the project root in dev):

    BASE_DIR/
      TikTokMCIntegrator.exe      (frozen only)
      _internal/ templates/ static/   (swappable build artifacts)
      config/    config.yml, profiles/, active_profile.txt
      data/      all runtime JSON state
      logs/      all *.log files
      assets/    gift_assets/, sounds/, tts/, reports/

On import this module (1) creates the four subdirs and (2) migrates any legacy
files still sitting at BASE_DIR root into their new home. The migration is
idempotent and safe to run from both the dashboard and bot processes
concurrently (move-if-dest-absent, wrapped in try/except).
"""
import os
import re
import sys
import shutil

# ---- The one frozen-aware root resolution -------------------------------
# When frozen: sys.executable = TikTokMCIntegrator.exe → dirname() = release/
# When run via 'python app.py': check if __file__ contains '/release/' in path
# If it does, trust that; otherwise fall back to parent of __file__.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Not frozen: resolve based on invocation context
    abs_file = os.path.abspath(__file__)
    if 'release' in abs_file.split(os.sep):
        # Called from release/app.py → trust that location
        BASE_DIR = os.path.dirname(abs_file)
    else:
        # Called from source dir or main.py → trust the project root
        BASE_DIR = os.path.dirname(abs_file)

CONFIG_DIR = os.path.join(BASE_DIR, "config")
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
ADDONS_DIR = os.path.join(BASE_DIR, "addons")

_NEW_DIRS = (CONFIG_DIR, DATA_DIR, LOGS_DIR, ASSETS_DIR, ADDONS_DIR)

for _d in _NEW_DIRS:
    try:
        os.makedirs(_d, exist_ok=True)
    except Exception:
        pass

# ---- Classification ------------------------------------------------------
# Bare files that belong in config/
_CONFIG_FILES = {"config.yml", "active_profile.txt"}
# Subdirectories that belong in config/
_CONFIG_DIRNAMES = {"profiles"}
# Subdirectories that belong in assets/
_ASSET_DIRNAMES = {"gift_assets", "sounds", "tts", "reports"}
# Build artifacts / runtime junk that MUST stay at root (never migrate)
_KEEP_AT_ROOT_DIRS = {"_internal", "templates", "static", "config", "data", "logs", "assets", "addons"}


# ---- Path helpers (explicit subdir) -------------------------------------
def data(name):
    """Full path for a runtime data file in data/."""
    return os.path.join(DATA_DIR, os.path.basename(name))


def config(name):
    """Full path for a config file in config/."""
    return os.path.join(CONFIG_DIR, os.path.basename(name))


def logs(name):
    """Full path for a log file in logs/."""
    return os.path.join(LOGS_DIR, os.path.basename(name))


def assets(name):
    """Full path for an asset (file or subdir) in assets/."""
    return os.path.join(ASSETS_DIR, os.path.basename(name))


def addons(name=""):
    """Full path for an add-on directory/file in addons/."""
    base = os.path.basename(name) if name else ""
    return os.path.join(ADDONS_DIR, base) if base else ADDONS_DIR


_SAFE_ADDON_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_SAFE_DATA_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def addon_data(addon_id, name):
    """Return a path scoped to ``data/addons/<addon_id>/``.

    Both components must be plain names. Rejecting separators and dot-only
    values keeps add-ons from escaping their own runtime-state directory.
    """
    addon_id = str(addon_id or "")
    name = str(name or "")
    if not _SAFE_ADDON_ID.fullmatch(addon_id):
        raise ValueError("invalid add-on id")
    if name in {".", ".."} or not _SAFE_DATA_NAME.fullmatch(name):
        raise ValueError("invalid add-on data filename")
    directory = os.path.join(DATA_DIR, "addons", addon_id)
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, name)


def resolve(name):
    """Resolve a bare filename to its full path in the new layout.

    Used to replace legacy cwd-relative opens (e.g. open("viewer_stats.json")).
    Rules: known config files -> config/, *.log -> logs/, everything else
    (json/txt runtime state) -> data/.
    """
    base = os.path.basename(name)
    if base in _CONFIG_FILES:
        return os.path.join(CONFIG_DIR, base)
    if base.endswith(".log"):
        return os.path.join(LOGS_DIR, base)
    return os.path.join(DATA_DIR, base)


# ---- One-time migration of legacy root layout ---------------------------
def _migrate_legacy_layout():
    """Move legacy root files/dirs into the new subdirs. Idempotent + safe."""
    try:
        entries = os.listdir(BASE_DIR)
    except Exception:
        return

    moves = []
    for entry in entries:
        src = os.path.join(BASE_DIR, entry)
        try:
            is_dir = os.path.isdir(src)
        except Exception:
            continue

        if is_dir:
            if entry in _KEEP_AT_ROOT_DIRS:
                continue
            if entry in _ASSET_DIRNAMES:
                dst = os.path.join(ASSETS_DIR, entry)
            elif entry in _CONFIG_DIRNAMES:
                dst = os.path.join(CONFIG_DIR, entry)
            else:
                continue
        else:
            if entry in _CONFIG_FILES:
                dst = os.path.join(CONFIG_DIR, entry)
            elif entry.endswith(".log"):
                dst = os.path.join(LOGS_DIR, entry)
            elif entry.endswith(".json"):
                dst = os.path.join(DATA_DIR, entry)
            else:
                # leave anything else at root (.reload_signal, exe, build files)
                continue

        # Only move when the destination doesn't already exist — never clobber.
        if not os.path.exists(dst):
            moves.append((src, dst))

    for src, dst in moves:
        try:
            shutil.move(src, dst)
        except Exception:
            pass


_migrate_legacy_layout()
