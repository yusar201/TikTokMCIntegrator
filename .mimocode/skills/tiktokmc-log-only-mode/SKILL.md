---
name: tiktokmc-log-only-mode
description: "Test TikTok connection without triggering actions"
trigger: "test connection; log-only mode; test connection without triggering actions; don't execute anything; DEBUG MODE; just want to test the bot connection"
version: 1.0.0
author: Qoder
license: MIT
metadata.hermes.tags: ["log-only", "testing", "connection-verification"]
metadata.hermes.related_skills: ["tiktokmc-bot-status-wiring", "cloudflare-tunnel-webhook-exposure"]
---

# Log-Only Mode — Pure Connection Testing Without Action Execution

**Purpose:** Test TikTok bot connectivity while suppressing all action execution (Minecraft commands, sounds, webhooks, overlays).

**What It Does:**
- ON: All events fire and log normally, but NO actions execute. Status bar shows `DEBUG MODE` suffix.
- OFF: Normal operation with all actions executing as configured.

**How to Enable:** Settings tab → Options section → toggle "Log-Only Mode (Test Connection)".

**Implementation:** New `bot_flags.py` module + `_should_skip_action_execution()` wrapper function that wraps ALL `execute_actions` calls in `minecraft_main.py`. Config stored in `config/settings.yml` under `Settings.LogOnlyMode`.

**Critical fix discovered 2026-08-13:** The `/api/bot/status` endpoint must return `settings` dict containing `LogOnlyMode`, `DebugMode` values. Without this, frontend can't show "| DEBUG MODE" suffix or know diagnostic modes are active. Patch pattern:
```python
# Load settings for /api/bot/status response
_current_settings = c.get("Settings", {}) if os.path.exists(CONFIG_FILE) else {}
return jsonify({... , "settings": _current_settings})
```

**Frontend pattern:** `updateBotStatusUI(isRunning, meta)` reads `meta.settings.LogOnlyMode` and appends `" | DEBUG MODE"` to the status label text. Idempotent event handlers use `_wired` flag.

**User preference embedded:** User wants "DEBUG MODE" status text regardless of whether Debug Mode OR LogOnlyMode is active — unified branding. Timer must only start on real `Connected` state, not button press (separate but related fix).

**Critical debugging lesson (2026-08-13):** When LogOnlyMode appears enabled but commands still execute, **always check for direct calls to `_orig_execute_actions()` instead of the wrapper**. The dynamic event registration at line 267 in `register_dynamic_events()` was calling `_orig_execute_actions()` directly, creating a bypass path. Even after adding the wrapper and fixing the HTTP endpoints, one hardcoded call would silently defeat the entire feature. Always verify EVERY call site uses `execute_actions()`, never `_orig_...`:

```bash
# Verify no direct _orig calls remain
grep -n '_orig_execute_actions' minecraft_main.py  # Should only find import line
grep -n 'await execute_actions' minecraft_main.py   # Should find 12+ usage sites
```

Fix pattern: Search for `await _orig_execute_actions` and change to `await execute_actions()`. Never assume the wrapper exists just because you added it.

**CRITICAL LESSON (2026-08-13):** Status stuck at "connecting" despite events working? Path resolution mismatch between dashboard and bot subprocess! The dashboard reads from `/source/data/bot_status.json` while the bot writes to `/release/data/bot_status.json`. Both must use identical BASE_DIR resolution. Fixed in `paths.py` by detecting invocation context and preferring release/ when called from there. Pattern:

```python
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    abs_file = os.path.abspath(__file__)
    if 'release' in abs_file.split(os.sep):
        BASE_DIR = os.path.dirname(abs_file)  # Called from release/
    else:
        BASE_DIR = os.path.dirname(os.path.dirname(abs_file))  # Source dir
```

Without this, status file changes are written but dashboard reads stale/nothing from different location.

**Pitfalls:**
- Don't forget to include `settings` in `/api/bot/status` JSON response
- All `execute_actions` calls must go through the wrapper, never direct calls
- Settings toggle uses `!!(chk && chk.checked)` coercion to boolean
- Dynamic event handlers registered at startup won't auto-reload to new functions—verify every code path

**References:** 
- `references/api-bot-status-pattern.md` — detailed pattern for `/api/bot/status` returning `settings`.
- `references/log-only-mode-debugging.md` — grep patterns to find wrapper bypasses (_orig_execute_actions calls that defeat LogOnlyMode).
- `references/timer-reset-pattern.md` — timer reset logic to ensure live duration restarts on new stream, not resume from previous.
*Created 2026-08-13.*