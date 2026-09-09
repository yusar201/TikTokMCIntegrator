"""Overlay settings persistence.

Stores user preferences for dashboard/overlay visibility toggles.
Settings are persisted to JSON and loaded live by overlay HTML without bot restart.
"""
import os
import json
import threading

OVERRLAY_SETTINGS_FILE = None  # Will be set by init_overlay_settings_blueprint()

# Default settings (both amount displays OFF as requested)
DEFAULT_SETTINGS = {
    "show_gift_amounts": False,  # Coin amounts for top gifter board
    "show_like_amounts": False,  # Like amounts for top liker board
}

_lock = threading.RLock()


def init_overlay_settings_blueprint(data_dir):
    """Initialize the path to the settings file.
    
    For test isolation: always update the path, even if already set.
    This allows tests to create fresh Flask apps with different data directories.
    """
    global OVERRLAY_SETTINGS_FILE
    if data_dir is not None:
        OVERRLAY_SETTINGS_FILE = os.path.join(data_dir, "overlay_settings.json")


def _load():
    """Load settings from disk with defaults filled in."""
    if not OVERRLAY_SETTINGS_FILE:
        return dict(DEFAULT_SETTINGS)
    try:
        with open(OVERRLAY_SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            # Merge with defaults to ensure all keys exist
            merged = dict(DEFAULT_SETTINGS)
            merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
            return merged
    except FileNotFoundError:
        pass
    except Exception:
        print("[OVERLAY-SETTINGS] Failed to load settings, using defaults")
    return dict(DEFAULT_SETTINGS)


def get_settings():
    """Get current settings (thread-safe)."""
    with _lock:
        return _load()


def update_settings(show_gift_amounts=None, show_like_amounts=None):
    """Update settings and persist to disk (thread-safe).
    
    Only provided arguments are updated; others remain unchanged.
    """
    if not OVERRLAY_SETTINGS_FILE:
        return False
    
    with _lock:
        settings = _load()
        if show_gift_amounts is not None:
            settings["show_gift_amounts"] = bool(show_gift_amounts)
        if show_like_amounts is not None:
            settings["show_like_amounts"] = bool(show_like_amounts)
        
        try:
            # Ensure directory exists
            dir_path = os.path.dirname(OVERRLAY_SETTINGS_FILE)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            
            # Write atomically via temp file + rename
            tmp_path = OVERRLAY_SETTINGS_FILE + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(settings, f)
            os.replace(tmp_path, OVERRLAY_SETTINGS_FILE)
        except Exception as e:
            print(f"[OVERLAY-SETTINGS] Failed to persist settings: {e}")
            return False
        return True


def request_reload():
    """Signal overlay to reload settings (for dashboard preview).
    
    Creates a timestamp file that the Flask overlay route checks on each poll.
    """
    if not OVERRLAY_SETTINGS_FILE:
        return
    ts_file = OVERRLAY_SETTINGS_FILE + ".reload_ts"
    try:
        ts = str(__import__('time').time())
        with open(ts_file, "w", encoding="utf-8") as f:
            f.write(ts)
    except Exception:
        pass  # Non-critical; overlay will pick up on next read
