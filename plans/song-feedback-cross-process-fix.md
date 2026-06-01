# Plan — Song Feedback Cross-Process Fix

**Status:** ✅ Implemented, built, deployed, verified

## Problem
The song feedback toast system works in **simulation** but not for **real TikTok events** during streams.

### Root Cause
The bot (`minecraftDiamond.py`) runs as a **separate subprocess** from the Flask web server (see `app.py:331` — `subprocess.Popen(bot_cmd, ...)`).

When a real `!play` event fires:
1. Bot process calls `sh.push_song_feedback(...)` → adds to its **own private** `_song_feedback_queue` deque
2. Flask process (which serves the overlay poll) has a **different** `_song_feedback_queue` in its own memory
3. The two deques never share state

Sim works because the sim endpoints run **inside** the Flask process — they share the deque with the overlay.

### Confirmation
- `minecraftDiamond.py:34` — `import spotify_handler as sh` (in bot process)
- `routes/spotify.py:4` — `import spotify_handler as sh` (in Flask process)
- `routes/stats.py:158` — Flask serves `sh.get_and_clear_feedback()` to overlay
- `app.py:308-350` — bot launched as `subprocess.Popen`

## Fix: File-Based Feedback Queue

Use a JSON file (`song_feedback.json`) as the cross-process bridge. This matches the existing pattern for `song_queue.json`, `song_history.json`, `song_blocked_uris.json`.

### Architecture
```
Bot process                          Flask process
   │                                     │
   ├─ push_song_feedback()               │
   │     ↓                               │
   ├─ append to song_feedback.json ──→  read on every overlay poll
   │                                     ├─ get_and_clear_feedback()
   │                                     ├─ returns entries
   │                                     ├─ truncates file
```

### Implementation

#### 1. New helper functions in `spotify_handler.py`

Add to `spotify_handler.py` (replace in-memory deque with file-based):

```python
# Replace lines 36-72 (deque + push/get functions)

import json as _feedback_json
import threading as _feedback_threading
import time as _feedback_time
from constants import SONG_FEEDBACK_FILE
from utils import _load_json_safe, _save_json_atomic

_FEEDBACK_TTL = 5  # seconds
_feedback_lock = _feedback_threading.Lock()


def _load_feedback_file():
    """Load feedback entries from file. Returns list of dicts."""
    return _load_json_safe(SONG_FEEDBACK_FILE, default=[])


def _save_feedback_file(entries):
    """Atomically write feedback entries to file."""
    _save_json_atomic(SONG_FEEDBACK_FILE, entries)


def push_song_feedback(nick, feedback_type, icon, title, detail=""):
    """Push a feedback entry to the cross-process feedback file.
    Called by bot process on every !play / !skip / !pull event.
    """
    entry = {
        "nick": nick,
        "type": feedback_type,
        "icon": icon,
        "title": title,
        "detail": detail,
        "timestamp": _feedback_time.time(),
    }
    with _feedback_lock:
        entries = _load_feedback_file()
        entries.append(entry)
        # Cap to last 50 entries to prevent unbounded growth
        entries = entries[-50:]
        _save_feedback_file(entries)
    print(f"[SONG FEEDBACK] {feedback_type}: {title}")


def get_and_clear_feedback():
    """Return all feedback entries. Clear only entries older than 5s.
    Called by Flask process on every overlay poll.
    """
    now = _feedback_time.time()
    with _feedback_lock:
        entries = _load_feedback_file()
        # Filter out entries older than 5 seconds
        fresh = [e for e in entries if now - e.get("timestamp", 0) < _FEEDBACK_TTL]
        # Write back only fresh entries (preserves unexpired ones for next poll)
        if len(fresh) != len(entries):
            _save_feedback_file(fresh)
        return fresh
```

#### 2. New constant in `constants.py`

Add line after `SONG_HISTORY_FILE`:
```python
SONG_FEEDBACK_FILE = "song_feedback.json"
```

#### 3. Check `utils.py` for `_load_json_safe` and `_save_json_atomic`

If these exist, use them. If not, create simple versions in `spotify_handler.py`:

```python
def _load_json_safe(path, default):
    """Load JSON file with safe defaults."""
    import os
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _feedback_json.load(f)
    except (json.JSONDecodeError, IOError, OSError):
        return default


def _save_json_atomic(path, data):
    """Atomically write JSON file (write to temp + rename)."""
    import os
    import tempfile
    dir_name = os.path.dirname(path) or "."
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            _feedback_json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
```

#### 4. Add `song_feedback.json` to `.gitignore` (if not already)

Runtime files like `song_queue.json`, `song_history.json`, etc. should not be committed.

#### 5. Update `minecraftDiamond.py`

**No code changes needed** — it already calls `sh.push_song_feedback()`. The change to file-based persistence happens inside that function.

#### 6. No changes needed in `routes/spotify.py` or `routes/stats.py`

The sim endpoints and the overlay poll already call `sh.push_song_feedback()` and `sh.get_and_clear_feedback()` — they'll just work with the new file-based implementation.

## Pitfalls

- **Race condition on read-modify-write** — both bot and Flask could read the file at the same time. The `_feedback_lock` is per-process, so this doesn't fully prevent races. For this use case (low-frequency feedback events + overlay poll), a brief race is acceptable. If it becomes a problem, use file locking (`fcntl` on Linux) or write a sentinel.
- **File location** — `SONG_FEEDBACK_FILE = "song_feedback.json"` is a relative path. It must resolve to the same directory in both processes. The bot process changes cwd via PyInstaller, so verify the path resolves correctly. May need to use an absolute path derived from `os.path.dirname(os.path.abspath(__file__))`.
- **PyInstaller bundling** — verify `song_feedback.json` is writable at runtime, not inside the bundled zip. Since this is a runtime data file (not a code import), PyInstaller won't bundle it — it's created at runtime.
- **Cross-platform path** — `tempfile.mkstemp` + `os.replace` works on both Windows and Linux (WSL).

## Verification

1. **Sim still works:** Click sim buttons in dashboard → toast appears in overlay (existing behavior, should not break)
2. **Real event works:** During stream, have someone type `!play <song>` → toast appears in overlay
3. **Cross-process test:** Manually POST to `/api/spotify/feedback` from outside Flask → toast appears in overlay on next poll (proves file-based path works)

## Build & Deploy

1. Edit `spotify_handler.py` (replace lines 36-72 with new file-based impl)
2. Edit `constants.py` (add `SONG_FEEDBACK_FILE`)
3. Run `cmd.exe /c build.bat` from project root
4. Deploy: copy `TikTokMCIntegrator.exe` + `_internal/` to `release/` ROOT
5. Sync frontend files (no changes, but rebuild for consistency)
6. **Restart the app** — must pick up new exe
7. Test sim buttons first
8. Test live with a real `!play` from another account

## Files Modified

- `spotify_handler.py` — replace deque with file-based queue
- `constants.py` — add `SONG_FEEDBACK_FILE`
- `release/TikTokMCIntegrator/TikTokMCIntegrator.exe` — rebuilt
- `release/TikTokMCIntegrator/_internal/spotify_handler.py` — bundled in exe
- `release/TikTokMCIntegrator/_internal/constants.py` — bundled in exe
- `release/TikTokMCIntegrator/song_feedback.json` — created at runtime

## Estimated Time

~15 min implementation + 5 min build + 2 min deploy + testing
