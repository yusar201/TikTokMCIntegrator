# Refactoring Plan for TikTokMCIntegrator

## Status: COMPLETED (2026-05-28)

## Codebase Stats (as of 2026-05-28)

| File | Lines | Functions | Issues |
|------|-------|-----------|--------|
| app.py | 1,186 | 77 | Long report func (130 lines), 11 silent errors |
| minecraftDiamond.py | 1,219 | 35 | **236-line on_comment()!** |
| actions.py | 503 | 16 | 100-line build_context() |
| spotify_handler.py | 974 | 45 | 118-line queue processor |

**Total:** ~3,900 lines, 189 functions

## Key Issues Found

### 1. Giant Functions (Break Into Pieces)

**minecraftDiamond.py - on_comment() (236 lines!)**
- Does 8+ things in one function
- Needs splitting into:
  - `_extract_user_info(event)` - get nick, uid, badges
  - `_build_tags(user_info)` - VIP/follower/superfan logic
  - `_handle_tts(comment, nick, uid)` - TTS trigger
  - `_handle_song_request(comment, nick, uid)` - Spotify commands
  - `_handle_chat_filter(tags, gifter_level, member_level)` - filter logic
  - Keep `on_comment()` as orchestrator calling these

**app.py - generate_report() (130 lines)**
- Split into: `_calculate_gift_stats()`, `_calculate_viewer_stats()`, `_format_report()`

**spotify_handler.py - process_song_queue() (118 lines)**
- Split into: `_play_next_track()`, `_update_track_status()`, `_handle_blocked_uri()`

### 2. Silent Error Swallowing

**29 instances of `except: pass`** across all files
- These hide bugs!
- Replace with logging: `print(f"[ERROR] {e}")`

### 3. Magic Numbers

**15+ hardcoded values:**
- Timeouts: 5, 10, 30
- URLs: 127.0.0.1:5000 (9 instances)
- Limits: 500, 200, 100

**Fix:** Add constants at top of file

### 4. Duplicate JSON Load/Save

**38+ instances of same pattern:**
```python
try:
    if os.path.exists(file):
        with open(file, "r") as f:
            data = json.load(f)
except:
    data = default
```

**Fix:** Create `utils.py` with shared `load_json()` / `save_json()`

## Refactoring Phases

### Phase 1: Quick Wins (1-2 hours)
1. Add `utils.py` with JSON utilities
2. Replace all JSON load/save with utility functions
3. Add constants file, replace magic numbers
4. Fix silent `except: pass` → add logging

### Phase 2: Split Big Functions (2-3 hours)
1. Split `on_comment()` into 5-6 helper functions
2. Split `generate_report()` into 3 helpers
3. Split `process_song_queue()` into 3 helpers

### Phase 3: Organize (Optional, 2-3 hours)
1. Extract routes into separate files
2. Standardize naming (cmd vs command)
3. Add docstrings to all public functions

## What NOT to Touch

- ✋ Math evaluation logic (amount*N) - WORKS
- ✋ Skript commands (.sk files)
- ✋ Profile configs (.yml files)
- ✋ Spotify OAuth flow
- ✋ TikTok Live connection logic

## Benefits After Refactoring

1. **Easier debugging** - smaller functions = easier to find bugs
2. **Faster development** - add features without touching 200-line functions
3. **Less bugs** - proper error handling catches issues early
4. **Better readability** - future you (or AI) can understand code faster
5. **Safer changes** - modify one function without breaking others
