# Code Refactoring Workflow

## Phase-Based Approach
When refactoring TikTokMCIntegrator, follow this proven sequence:

### Phase 1: Extract Shared Utilities
- Create `utils.py` for common functions (`load_json`, `save_json`)
- Create `constants.py` for magic numbers and repeated values
- Update all files to import from utils/constants instead of inline implementations

### Phase 2: Split Giant Functions
Split functions >100 lines into helper functions:
- `on_comment()` (236 lines) → 5-6 helpers (`_extract_user_info`, `_build_tags`, `_check_chat_filter`, `_handle_tts_trigger`)
- `generate_report()` (127 lines) → 8 helpers (one per report section)
- `process_song_queue()` (115 lines) → 3 helpers (`_push_queued_songs`, `_sync_playback_state`, `_auto_skip_blocked_uris`)

### Phase 3: Extract Routes (optional)
- Split Flask routes into separate files by domain

## Critical Pitfall: File Operations

> **⚠️ NEVER use `write_file` to modify existing files!**
> 
> `write_file` **OVERWRITES** the entire file. Always use `patch` for:
> - Adding helper functions before/after existing functions
> - Modifying function bodies
> - Any change to existing files
> 
> Only use `write_file` for:
> - Creating NEW files (utils.py, constants.py, report_helpers.py)
> 
> **Recovery**: If you accidentally overwrite, restore from backup:
> ```bash
> cd D:\Ikhito\Code\TikTokMCIntegrator
> tar -xzf backups/backup_pre_refactor_20260528_181003.tar.gz ./spotify_handler.py
> ```

## Helper Function Patterns

### Pattern 1: Module-level helpers (in same file)
```python
def _push_queued_songs(token, cfg, time_mod):
    """Push queued songs to Spotify. Returns (queue, pushed_any)."""
    # ... helper logic ...
    return queue, pushed_any

def process_song_queue():
    # ...
    queue, pushed_any = _push_queued_songs(token, cfg, time_mod)
```

### Pattern 2: Separate helpers file (for complex domains)
```python
# report_helpers.py
def format_report_header(state, now):
    """Format report header with stream info."""
    lines = ["=" * 50, "  STREAM REPORT", ...]
    return lines

# app.py
from report_helpers import format_report_header, format_report_summary, ...
```

## Compilation Testing
After each phase, verify all files compile:
```bash
C:\Python313\python.exe -m py_compile app.py report_helpers.py minecraftDiamond.py spotify_handler.py
```

## Line Count Tracking
Track reduction per function:
| Function | Before | After | Notes |
|----------|--------|-------|-------|
| on_comment() | 236 lines | 100 lines | +6 helpers |
| generate_report() | 127 lines | 30 lines | +8 helpers (separate file) |
| process_song_queue() | 115 lines | 40 lines | +3 helpers (same file) |
| _extract_badge_icons() | 104 lines | 61 lines | +6 helpers (separate file) |

## Final Review Checklist (Before Rebuild)

Run these checks in order before rebuilding the exe:

### 1. Syntax Check
```bash
C:\Python313\python.exe -m py_compile app.py routes/spotify.py routes/stats.py utils.py constants.py report_helpers.py badge_helpers.py minecraftDiamond.py spotify_handler.py actions.py
```

### 2. Import Check
```python
import sys
sys.path.insert(0, '.')
from utils import load_json, save_json, safe_json_read
from constants import API_PORT, MAX_TTS_HISTORY
from report_helpers import load_stream_state, calculate_stats
from badge_helpers import _extract_scene_type, _extract_badge_level
from routes.spotify import spotify_bp
from routes.stats import stats_bp, init_stats_blueprint
```

### 3. Blueprint Registration Check
```bash
grep -n "register_blueprint" app.py
# Should show: spotify_bp and stats_bp
```

### 4. Duplicate Function Check
```python
import ast
with open('app.py', 'r', encoding='utf-8') as f:
    tree = ast.parse(f.read())
funcs = []
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name in funcs:
            print(f'DUPLICATE: {node.name} at line {node.lineno}')
        funcs.append(node.name)
```

### 5. Sacred Code Verification
```bash
grep -n "amount.split" actions.py
# Must show the math evaluation code
```

### 6. Helper Function Verification
```bash
grep -n "_push_queued_songs\|_sync_playback_state\|_auto_skip_blocked_uris" spotify_handler.py
grep -n "_extract_user_info\|_build_tags\|_check_chat_filter\|_handle_tts_trigger" minecraftDiamond.py
```

### 7. Backup Verification
```bash
ls -la backups/backup_pre_refactor_*.tar.gz
```

### 8. Dead Code Check
Look for globals that are set but never read:
```bash
grep -n "SPOTIFY_CLIENT_ID\|SPOTIFY_CLIENT_SECRET" app.py
# Should be removed (dead code)
```

### 9. Docstring Coverage
```bash
C:\Python313\python.exe -c "
import ast
with open('app.py', 'r', encoding='utf-8') as f:
    tree = ast.parse(f.read())
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if not node.name.startswith('_') or node.name.startswith('__'):
            doc = ast.get_docstring(node)
            if not doc:
                print(f'Line {node.lineno}: {node.name}()')
"
```

### 10. Final Line Count
```bash
wc -l app.py routes/spotify.py routes/stats.py utils.py constants.py report_helpers.py badge_helpers.py
```
