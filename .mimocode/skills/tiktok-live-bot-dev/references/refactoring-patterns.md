# Refactoring Patterns for TikTokMCIntegrator

## Phase 1: Utility Extraction

### Created Files
- `utils.py` — `load_json()`, `save_json()`, `safe_json_read()`
- `constants.py` — `API_PORT`, `TIMEOUT_*`, `MAX_TTS_HISTORY`, `MAX_LOGS`

### Pattern
Search for duplicate JSON load/save patterns across files, extract to utils.py.

**Before (5 copies):**
```python
# In app.py, minecraftDiamond.py, spotify_handler.py, etc.
def load_json(filename):
    path = os.path.join(BASE_DIR, filename)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []
```

**After (1 import):**
```python
from utils import load_json, save_json
```

## Phase 2: Function Splitting

### Giant Functions Split

| Function | Before | After | Helpers Created |
|----------|--------|-------|-----------------|
| `on_comment()` | 236 lines | 100 lines | `_extract_user_info()`, `_build_tags()`, `_check_chat_filter()`, `_handle_tts_trigger()` |
| `generate_report()` | 127 lines | 30 lines | `report_helpers.py` (6 functions) |
| `process_song_queue()` | 115 lines | 40 lines | `_push_queued_songs()`, `_sync_playback_state()`, `_auto_skip_blocked_uris()` |
| `_extract_badge_icons()` | 104 lines | 61 lines | `badge_helpers.py` (6 functions) |

### Helper File Pattern
Keep helpers close to the function they serve:

```
├── report_helpers.py      # Helper functions for generate_report()
├── badge_helpers.py       # Helper functions for _extract_badge_icons()
└── spotify_queue_helpers.py  # (Example, not used - kept in spotify_handler.py)
```

### When to Split
- Function > 100 lines
- Function has 3+ distinct sections (each section can be a helper)
- Function has nested helper functions (extract to module level)

## Phase 3: Flask Blueprint Extraction

### Created Blueprints

| Blueprint | File | Routes | Prefix |
|-----------|------|--------|--------|
| `spotify_bp` | `routes/spotify.py` | 18 routes | `/api/spotify` |
| `stats_bp` | `routes/stats.py` | 12 routes | `/api/stats` |

### Blueprint Pattern

**Simple blueprint (no app state needed):**
```python
# routes/spotify.py
from flask import Blueprint, request, jsonify
import spotify_handler as sh

spotify_bp = Blueprint('spotify', __name__)

@spotify_bp.route("/config", methods=["GET"])
def get_config():
    cfg = sh.load_config()
    return jsonify(cfg)
```

**Blueprint needing app state (like BASE_DIR):**
```python
# routes/stats.py
from flask import Blueprint, jsonify

stats_bp = Blueprint('stats', __name__)
BASE_DIR = None  # Set by init function

def init_stats_blueprint(base_dir):
    """Initialize the blueprint with app state."""
    global BASE_DIR
    BASE_DIR = base_dir

@stats_bp.route("/viewers", methods=["GET"])
def get_viewer_stats():
    data = safe_json_read(os.path.join(BASE_DIR, "viewer_stats.json"))
    return jsonify(data)
```

**Registration in app.py:**
```python
from routes.spotify import spotify_bp
from routes.stats import stats_bp, init_stats_blueprint

app.register_blueprint(spotify_bp, url_prefix='/api/spotify')
app.register_blueprint(stats_bp, url_prefix='/api/stats')

# Initialize blueprints that need app state
init_stats_blueprint(BASE_DIR)
```

### Routes NOT Extracted (and why)

**TTS routes (`/api/tts/*`) — 6 routes:**
- Depends on `_asyncio.new_event_loop()` for edge-tts
- Uses `_run_async()` helper for async/await bridge
- References `_tts_last_at` global rate limiting
- Uses `_check_tts_permission()` function
- **Conclusion:** Too tightly coupled to app internals. Skip unless user explicitly requests.

**Bot routes (`/api/bot/*`) — 4 routes:**
- `start_bot()`, `stop_bot()`, `bot_status()`, `get_logs()`
- Reference `bot_process` (subprocess) and `bot_logs` (shared state)
- **Conclusion:** Tightly coupled to app process management. Skip.

**Profile routes (`/api/profiles/*`) — 6 routes:**
- Reference `PROFILES_DIR`, `CONFIG_FILE`, `get_active_profile()`, `set_active_profile()`
- **Conclusion:** Could be extracted, but low priority (only 6 routes, small functions).

## Critical Pitfalls

### ⛔ CRITICAL: Never use write_file for partial edits
**Incident:** Accidentally overwrote `spotify_handler.py` (974 lines) with only helper functions (102 lines).
**Cause:** Used `write_file` instead of `patch` for targeted edits.
**Fix:** ALWAYS use `patch` for edits to existing files. `write_file` OVERWRITES the entire file.
**Recovery:** Restore from backup:
```bash
tar -xzf backups/backup_pre_refactor_*.tar.gz ./spotify_handler.py
```

### Backup before major refactoring
```bash
tar -czf backups/backup_pre_refactor_$(date +%Y%m%d_%H%M%S).tar.gz \
  app.py minecraftDiamond.py spotify_handler.py actions.py
```

### Test compilation after each change
```bash
C:\Python313\python.exe -m py_compile app.py routes/spotify.py utils.py
```

### Dead code removal
Identify and remove unused globals:
- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` — set but never read
- Duplicate `load_json()` nested inside functions

## Final Metrics (May 2026 Refactoring)

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| app.py lines | 1,088 | 750 | **-338 lines (-31%)** |
| Longest function | 236 lines | 100 lines | **-58%** |
| Duplicate JSON code | 5 copies | 1 utils.py | **Eliminated** |
| Magic numbers | 38 | 0 | **Replaced with constants** |
| Dead code | SPOTIFY globals | Removed | **Cleaned** |

**Files created:**
- `utils.py` (69 lines)
- `constants.py` (43 lines)
- `report_helpers.py` (144 lines)
- `badge_helpers.py` (87 lines)
- `routes/__init__.py` (1 line)
- `routes/spotify.py` (209 lines)
- `routes/stats.py` (158 lines)

**Docstrings added to key functions:**
- `get_active_profile()`, `set_active_profile()`, `ensure_profiles_setup()`
- `load_config()`, `save_config()`
- All route handlers in blueprints
