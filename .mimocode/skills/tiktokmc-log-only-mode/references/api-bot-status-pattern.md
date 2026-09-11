# LogOnlyMode API Pattern - /api/bot/status must return settings

## Problem Discovered 2026-08-13

Frontend needed `LogOnlyMode` state to show "| DEBUG MODE" status suffix, but `/api/bot/status` endpoint was only returning bot lifecycle state (`running`, `state`, `room_id`, etc.) without current settings.

## Solution

**Backend patch (app.py):**

```python
@app.route("/api/bot/status", methods=["GET"])
def bot_status():
    _running, local_running, external = is_any_bot_running()
    running = bool(local_running or external)
    
    # Load current settings for diagnostic mode indicators
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                c = yaml.safe_load(f) or {}
            _current_settings = c.get("Settings", {})
        else:
            _current_settings = {}
    except Exception:
        _current_settings = {}
    
    status = bot_status_mod.read_status(paths)
    
    # ... derive state ...
    
    return jsonify({
        "running": running,
        "state": derived,
        # ... other fields ...
        "settings": _current_settings,  # NEW: Include LogOnlyMode/DebugMode
    })
```

**Frontend consumption (script.js):**

```javascript
async function checkBotStatus() {
  const res = await fetch('/api/bot/status');
  const data = await res.json();
  updateBotStatusUI(data.running, data);  // data.settings now available
}

function updateBotStatusUI(isRunning, meta = {}) {
  // ...
  if (isRunning && meta.settings.LogOnlyMode) {
    text.textContent = `${m.label} | DEBUG MODE`;
  }
}
```

**Key insight:** Settings are live-read from `config/settings.yml` on every status poll (~1s), so no restart needed when user toggles options mid-stream.

**Related pattern:** Same approach used for `_is_debug_mode_enabled()`, `_is_log_only_mode_enabled()` functions in `minecraft_main.py`.