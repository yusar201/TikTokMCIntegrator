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
import sys
import shutil

# ---- The one frozen-aware root resolution -------------------------------
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
           else os.path.dirname(os.path.abspath(__file__))

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
