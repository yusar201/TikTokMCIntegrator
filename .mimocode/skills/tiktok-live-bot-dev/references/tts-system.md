# TTS System — edge-tts + Flask + Pygame

## Architecture

```
TikTok Chat → minecraftDiamond.py on_comment
  → detect `.` prefix (configurable via tts_config.json)
  → permission check (everyone/followers/friends/superfans/members/vip/mods/whitelist)
  → HTTP POST to Flask /api/tts/speak with {text, nick, user_info}
  → Flask: global + per-user cooldown check
  → Flask: edge_tts generates .mp3 to tts/ folder
  → Flask: pygame.mixer.Sound plays audio (captured by OBS desktop audio)
  → Response: {status: "ok"}
```

## Config File: tts_config.json

```json
{
  "enabled": true,
  "command": ".",
  "voice": "en-US-AriaNeural",
  "speed": "+0%",
  "pitch": "+0Hz",
  "max_length": 200,
  "global_cooldown": 2,
  "per_user_cooldown": 10,
  "member_min_level": 0,
  "permission": {
    "everyone": true,
    "followers": false,
    "friends": false,
    "superfans": false,
    "members": false,
    "vip": false,
    "mods": false,
    "whitelist": []
  }
}
```

## Flask Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | /api/tts/config | Read TTS configuration |
| POST | /api/tts/config | Save TTS configuration |
| GET | /api/tts/voices | List available edge_tts voices |
| POST | /api/tts/speak | Trigger TTS speech |
| GET | /api/tts/history | Get TTS history (last 500 entries) |
| POST | /api/tts/history/clear | Clear TTS history |

## minecraftDiamond.py Integration

In `on_comment`, AFTER chat is sent to Minecraft:

```python
tts_cfg_path = os.path.join(BASE_DIR, "tts_config.json")
tts_cfg = json.load(open(tts_cfg_path)) if os.path.exists(tts_cfg_path) else {}
if tts_cfg.get("enabled", True):
    tts_cmd = tts_cfg.get("command", ".")
    if comment.strip().startswith(tts_cmd):
        tts_text = comment.strip()[len(tts_cmd):].strip()
        if tts_text:
            # POST to Flask with user_info for permission check
```

## edge_tts Integration

- Install: `pip install edge-tts`
- 400+ voices, 100+ languages, free, no API key
- Voice format: `en-US-AriaNeural` (ShortName from list_voices())
- Rate: e.g. `"+20%"` or `"-10%"` (without % for Communicate constructor)
- Pitch: e.g. `"+5Hz"` or `"-3Hz"`
- Generate: `asyncio.run(edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(out_file))`
- PyInstaller: add `edge_tts` to hiddenimports in spec file

## pygame Playback

- Already initialized in actions.py via `_ensure_mixer()`
- Flask endpoint imports pygame separately, checks `pygame.mixer.get_init()`, inits if needed
- `pygame.mixer.Sound(path).play()` — non-blocking
- Output goes to desktop audio → OBS captures it

## Dashboard Frontend (TTS Tab)

- Reuses Song tab's CSS classes (song-card, song-form-grid, song-side-column, song-permission-block)
- Voice dropdown populated from /api/tts/voices on tab activation
- Speed/pitch sliders with live value display
- Permissions checkboxes + whitelist textarea — layout mirrors Song permissions
- Test section: text input + Speak button → /api/tts/speak with nick="Dashboard Test" (bypasses permission check)

## TTS History Logging

TTS history is persisted to `tts_history.json` for dashboard display. Follows the same pattern as Song history.

### Backend Implementation

```python
TTS_HISTORY_FILE = os.path.join(BASE_DIR, "tts_history.json")

def _load_tts_history():
    """Load TTS history from JSON file."""
    try:
        if os.path.exists(TTS_HISTORY_FILE):
            with open(TTS_HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []

def _save_tts_history(history):
    """Save TTS history to JSON file (keep last 500 entries)."""
    try:
        history = history[-500:]  # Keep last 500
        with open(TTS_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
```

### Logging in _tts_speak_impl

After successful TTS generation and playback, log the entry:

```python
# Log to TTS history for dashboard
uid = data.get("user_info", {}).get("unique_id", "") or nick or "unknown"
entry = {
    "user": uid,
    "nick": nick or uid,
    "text": text[:500],  # Cap stored text
    "timestamp": _time.time(),
    "voice": voice,
}
hist = _load_tts_history()
hist.append(entry)
_save_tts_history(hist)
```

### Frontend (index.html)

History section in the TTS side panel:

```html
<!-- TTS History -->
<section class="song-card" style="margin-top:16px;">
  <div class="song-card-header compact">
    <div>
      <h3><i class="fa-solid fa-clock-rotate-left"></i> History</h3>
      <p>Recent TTS usage</p>
    </div>
    <button class="btn btn-ghost btn-sm" onclick="clearTtsHistory()"><i class="fa-solid fa-trash"></i> Clear</button>
  </div>
  <div id="tts-history-list" class="tts-history-list">
    <div class="tts-history-empty">No TTS history yet</div>
  </div>
</section>
```

### JavaScript Functions

```javascript
async function fetchTtsHistory() {
  try {
    const r = await fetch('/api/tts/history');
    const data = await r.json();
    renderTtsHistory(data);
  } catch(e) {
    console.error('Failed to fetch TTS history:', e);
  }
}

function renderTtsHistory(entries) {
  const el = document.getElementById('tts-history-list');
  if (!el) return;
  if (!entries || !entries.length) {
    el.innerHTML = '<div class="tts-history-empty">No TTS history yet</div>';
    return;
  }
  // Show newest first
  const sorted = [...entries].reverse().slice(0, 100);
  el.innerHTML = sorted.map(e => {
    const initial = (e.nick || e.user || '?')[0].toUpperCase();
    const ts = e.timestamp ? new Date(e.timestamp * 1000) : new Date();
    const timeStr = ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const dateStr = ts.toLocaleDateString([], { month: 'short', day: 'numeric' });
    const text = (e.text || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const nick = (e.nick || e.user || 'unknown').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return `<div class="tts-history-item">
      <div class="tts-history-avatar">${initial}</div>
      <div class="tts-history-content">
        <div class="tts-history-meta">
          <span class="tts-history-user">${nick}</span>
          <span class="tts-history-time">${dateStr} ${timeStr}</span>
        </div>
        <div class="tts-history-text">${text}</div>
      </div>
    </div>`;
  }).join('');
}

async function clearTtsHistory() {
  if (!confirm('Clear all TTS history?')) return;
  try {
    await fetch('/api/tts/history/clear', { method: 'POST' });
    showToast('History cleared', 'success');
    fetchTtsHistory();
  } catch(e) {
    showToast('Failed to clear history', 'error');
  }
}

// Auto-fetch TTS history on load (with polling)
document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('panel-tts')) {
    fetchTtsHistory();
    setInterval(fetchTtsHistory, 10000);  // Refresh every 10 seconds
  }
});
```

### CSS Styles

```css
/* TTS History */
.tts-history-list {
  max-height: 400px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 0;
}
.tts-history-empty {
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
  padding: 20px;
  opacity: 0.6;
}
.tts-history-item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 10px 12px;
  background: var(--bg-elevated);
  border-radius: 8px;
  border: 1px solid var(--border-default);
}
.tts-history-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--bg-inset);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  color: #8B5CF6;
  flex-shrink: 0;
}
.tts-history-content { flex: 1; min-width: 0; }
.tts-history-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.tts-history-user { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.tts-history-time { font-size: 11px; color: var(--text-muted); }
.tts-history-text {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.4;
  word-break: break-word;
}
```

### .gitignore

Add `tts_history.json` to `.gitignore` (runtime file, not source).

## Pitfalls

- **⛔ PyInstaller `console=False` makes thread errors invisible** — Background threads like `_play_tts()` that catch exceptions with bare `except: print(...)` produce NO visible output because stdout is discarded in windowed mode. Flask returns HTTP 200 (thread was spawned before the exception), the dashboard shows success, but no audio plays and the error is unknowable. **Fix:** write thread-level errors to a file (`tts_debug.log`) with `traceback.format_exc()`. See `references/pyinstaller-windowed-debug-logging.md` for the full pattern.
- **⛔ Missing `time` import = silent 500** — `_tts_speak_impl()` calls `time.time()` for cooldowns but only imports `threading, asyncio`. `time` must be in the function's import line: `import threading, asyncio, time`. Otherwise `NameError: name 'time' is not defined` kills the endpoint with a 500. This is particularly nasty because `time` is usually available at module level in most Python files — but if the module's only `import time` is inside a different function, this function won't have it in scope.
- **⛔ Flask `debug=True` hides JSON error responses** — When Flask runs with `debug=True` and a request handler raises an exception, Flask replaces the response body with an HTML debug error page, even if your try/except already caught the exception and returned `jsonify({"status":"error",...}), 500`. The frontend receives HTML not JSON → `resp.json()` throws → error swallowed. **Fix:** return 200 status from caught exceptions (`return jsonify({"status":"error"...}), 200`), or run with `debug=False` in production. Also verify by fetching the endpoint with `.then(r => r.text())` during debugging to see the raw response body.
- **⛔ Frontend fetch doesn't check HTTP status** — `await fetch('/api/tts/speak', ...)` resolves on ANY HTTP status (200, 400, 500). The test button's `testTts()` shows "TTS sent!" toast even when the backend returns 500. User sees success but hears nothing. **Fix:** check `response.ok` before showing success toast, or inspect `response.status`. Without this, all backend errors are invisible to the dashboard user.
- **Command must be checked BEFORE song commands** — TTS runs on chat text, song commands run on specific `!command` syntax. Order: send to MC → TTS check → song commands.
- **Whitelist bypasses all permissions** — check whitelist FIRST in `_check_tts_permission()`
- **Test button bypasses permission** — `_test: true` flag skips permission check entirely. Dashboard sends this so admins can preview without matching a viewer role.
- **TTS config is separate from song_config.json** — different file, different panel, no cross-dependency
- **Member minimum level** — `member_min_level` gates TTS by member heart level. If permissions.members is checked, the viewer's `member_level` must be >= `member_min_level`. Set to 0 to allow any member. Level check happens in `_check_tts_permission()` after the `is_member` flag passes.
- **_test flag pattern** — Flask `/api/tts/speak` checks `data.get("_test")` before permission enforcement. When `_test` is truthy, permission check is skipped entirely. The frontend `testTts()` function sets `{ _test: true }`. This is safe because the test endpoint is only accessible from the local dashboard, not from external viewers.
