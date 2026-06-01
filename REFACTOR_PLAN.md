# TikTokMCIntegrator Refactoring Plan

## Overview
Codebase: ~3,900 lines across 4 main files (app.py, minecraftDiamond.py, actions.py, spotify_handler.py)

---

## 🔴 Priority 1: Critical Issues

### 1.1 Giant Functions (Break Into Pieces)

**`minecraftDiamond.py` - `on_comment()` (236 lines!)**
- Does 8+ things in one function
- Needs splitting into:
  - `_extract_user_info(event)` - get nick, uid, badges
  - `_build_tags(user_info)` - VIP/follower/superfan logic
  - `_handle_tts(comment, nick, uid)` - TTS trigger
  - `_handle_song_request(comment, nick, uid)` - Spotify commands
  - `_handle_chat_filter(tags, gifter_level, member_level)` - filter logic
  - Keep `on_comment()` as orchestrator calling these

**`minecraftDiamond.py` - `_extract_badge_icons()` (157 lines)**
- Long repetitive code
- Extract into helper: `_get_badge_url(badge_type, level)`

**`app.py` - `generate_report()` (130 lines)**
- Complex report generation
- Split into: `_calculate_gift_stats()`, `_calculate_viewer_stats()`, `_format_report()`

**`spotify_handler.py` - `process_song_queue()` (118 lines)**
- Does queue management + playback + history
- Split into: `_play_next_track()`, `_update_track_status()`, `_handle_blocked_uri()`

### 1.2 Silent Error Swallowing

**29 instances of `except: pass`**
- These hide bugs!
- Replace with:
  - Log the error: `print(f"[ERROR] {e}")`
  - Or use proper logging
  - At minimum, add comment WHY it's okay to ignore

**Files to fix:**
- `app.py`: 11 instances
- `minecraftDiamond.py`: 13 instances
- `spotify_handler.py`: 4 instances
- `actions.py`: 1 instance

---

## 🟡 Priority 2: Code Quality

### 2.1 Magic Numbers

**Current:**
```python
bot_process.wait(timeout=5)
resp = req.get(url, timeout=10)
future.result(timeout=30)
urllib.request.urlopen(req, timeout=5)
```

**Fix: Add constants at top of file**
```python
# app.py
BOT_SHUTDOWN_TIMEOUT = 5
HTTP_REQUEST_TIMEOUT = 10
ASYNC_FUTURE_TIMEOUT = 30
```

### 2.2 Hardcoded URLs/Ports

**9 instances of `127.0.0.1:5000`**

**Fix: Use config or constants**
```python
# At top of file
LOCAL_API_URL = f"http://127.0.0.1:{API_PORT}"
API_PORT = 5000  # from config
```

### 2.3 Duplicate JSON Load/Save

**Pattern repeated 38 times:**
```python
try:
    if os.path.exists(file):
        with open(file, "r") as f:
            data = json.load(f)
except:
    data = default
```

**Fix: Create utility functions in `utils.py`:**
```python
def load_json(file, default=None):
    try:
        if os.path.exists(file):
            with open(file, "r", encoding="utf-8") as f:
                return json.load(f)
    except:
        pass
    return default if default is not None else {}

def save_json(file, data):
    try:
        with open(file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] Failed to save {file}: {e}")
```

---

## 🟢 Priority 3: Organization

### 3.1 File Structure

**Current:** All routes in `app.py` (1,186 lines)

**Proposed:**
```
app.py          → Main Flask app, config, bot process
routes/
  __init__.py
  dashboard.py  → Dashboard routes
  tts.py        → TTS routes
  spotify.py    → Spotify routes
  overlay.py    → Overlay routes
  api.py        → API routes
```

### 3.2 Constants/Config

**Create `constants.py`:**
```python
# All magic numbers, URLs, timeouts
API_PORT = 5000
LOCAL_API_URL = f"http://127.0.0.1:{API_PORT}"

# Timeouts
BOT_SHUTDOWN_TIMEOUT = 5
HTTP_REQUEST_TIMEOUT = 10
ASYNC_FUTURE_TIMEOUT = 30

# Limits
MAX_TTS_HISTORY = 500
MAX_SONG_HISTORY = 500
MAX_BOT_LOGS = 1000
```

### 3.3 Naming Inconsistencies

**Examples:**
- `cmd` vs `command` vs `cmd_str`
- `nick` vs `nickname` vs `nick_name`
- `uid` vs `unique_id` vs `user_id`

**Fix:** Pick one convention and use consistently

---

## 📊 Impact Analysis

### Before Refactoring:
- Functions: 189 total, 10+ over 50 lines
- Error handling: 83 except blocks, 29 silent passes
- Magic numbers: 15+ hardcoded values
- Code duplication: 38+ similar JSON patterns

### After Refactoring:
- Functions: ~250 total, none over 50 lines
- Error handling: All logged or documented
- Constants: All magic numbers named
- Utilities: Shared JSON/HTTP helpers

---

## 🎯 Refactoring Order

### Phase 1: Quick Wins (1-2 hours)
1. Add `utils.py` with `load_json()` / `save_json()`
2. Replace all JSON load/save with utility functions
3. Add constants file, replace magic numbers
4. Fix silent `except: pass` → add logging

### Phase 2: Split Big Functions (2-3 hours)
1. Split `on_comment()` into 5-6 helper functions
2. Split `generate_report()` into 3 helpers
3. Split `process_song_queue()` into 3 helpers
4. Split `_extract_badge_icons()` into smaller pieces

### Phase 3: Organize (Optional, 2-3 hours)
1. Extract routes into separate files
2. Create proper config module
3. Standardize naming conventions
4. Add docstrings to all public functions

---

## ⚠️ What NOT to Touch

- ✋ Math evaluation logic (amount*N fix) - WORKS, don't touch
- ✋ Skript commands (.sk files)
- ✋ Profile configs (.yml files)
- ✋ Spotify OAuth flow (complex, working)
- ✋ TikTok Live connection logic (critical)

---

## 🧪 Testing Strategy

**After each change:**
1. Run `python -m py_compile app.py minecraftDiamond.py actions.py spotify_handler.py`
2. Test basic flow: start bot, receive gift, verify command sent
3. Test TTS: trigger TTS, verify history logs
4. Test Spotify: queue song, verify plays

**Before stream:**
- Full integration test
- Verify all overlays work
- Check RCON connection

---

## 📝 Estimated Time

- Phase 1 (Quick Wins): 1-2 hours
- Phase 2 (Split Functions): 2-3 hours
- Phase 3 (Organize): 2-3 hours (optional)

**Total: 3-5 hours for solid refactoring**

---

## 🚀 Benefits

1. **Easier debugging** - smaller functions = easier to find bugs
2. **Faster development** - add features without touching 200-line functions
3. **Less bugs** - proper error handling catches issues early
4. **Better readability** - future you (or AI) can understand code faster
5. **Safer changes** - modify one function without breaking others
