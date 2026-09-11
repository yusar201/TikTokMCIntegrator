# Dashboard vs Bot Sub-Process Boundary — Build-Time Implications

## TL;DR

The TikTokMCIntegrator exe runs as **two processes**:
1. **Dashboard** — `main.py` (Flask + tray icon). This is the parent process.
2. **Bot** — `main.py --run-bot` (spawned via subprocess.Popen when the user clicks "Start Bot").

PyInstaller's `hiddenimports` only bundles modules reached by the **dashboard's** import graph. The bot's heavy modules (TikTokLive, mcrcon, minecraftDiamond) live ONLY in the bot sub-process. The dashboard cannot import them at request time.

**If you find yourself writing `from minecraftDiamond import ...` inside a Flask route handler — STOP.** That import will fail at runtime, surface as a bare 500, and cost a 2-3 hour debug session.

## The Two-Process Architecture

```
┌─────────────────────────┐   subprocess.Popen(...)
│   main.py (dashboard)   │ ─────────────────────►┐
│   Flask + tray icon     │                        │
│   sys._MEIPASS root     │                        │
│                         │                        │
│   imports: app.py,      │                        ▼
│   spotify_handler,      │            ┌──────────────────────┐
│   tts_effects           │            │ main.py --run-bot    │
│                         │            │ (sub-process)        │
│   /api/* routes live    │            │                      │
│   here                  │            │ imports: minecraftDia│
└─────────────────────────┘            │ -mond.py, TikTokLive │
                                       │ -handler, etc.      │
                                       └──────────────────────┘
```

## What Belongs Where

| Concern | Where it lives | Why |
|---------|----------------|-----|
| Flask routes (`/api/*`) | Dashboard | Web UI + tray |
| Config save / load (`config.yml`) | **Both** (read-only OK in dashboard) | Dashboard writes, bot reads live |
| RCON / Forge mod connector | Bot | The actual outbound action |
| `sim_console.log` writes | **Bot** | Captures real event-driven commands |
| `sim_console.log` reads | Dashboard | File-based IPC — see python-dashboard-feature/references/process-boundary-pykiller.md |
| `send_minecraft_command` dispatcher | Bot | Has the heavy deps |
| User clicks "Send /say hello" in sim console | Dashboard | But dashboard re-implements forge POST, doesn't import bot's dispatcher |

## When to Add a Module to `hiddenimports`

**Default: don't.** The dashboard should not need to import bot modules. The escape hatches in order of preference:

1. **File-based IPC** (e.g. `sim_console.log`) — works for one-way shared state
2. **Re-implement the small piece** in the dashboard — read `config.yml` directly, POST to the mod yourself
3. **Named pipe / local socket** — overkill for a debug log
4. **Add to `hiddenimports`** — only if the dashboard genuinely needs substantial bot logic AND the deps are light. Test build size doesn't balloon.

**Symptoms you imported a bot module in a Flask route:**
- `/api/.../send` returns 500 with empty body
- Bot's stdout doesn't show the error (it's the dashboard that crashed, not the bot)
- `python app.py` works fine in dev (sys.path has the module), but `release/TikTokMCIntegrator.exe` fails

**Diagnostic recipe:**
```bash
# 1. Test the mod directly (if relevant)
curl -X POST http://127.0.0.1:5942/ping

# 2. Wrap the route in try/except that returns the error
# (Bare 500 with empty body is Flask's way of suppressing exceptions)
# Add this:
except Exception as e:
    return jsonify({"error": str(e), "type": type(e).__name__,
                    "trace": traceback.format_exc().splitlines()[-5:]}), 500

# 3. Re-trigger and read the actual exception
# Pattern: "ImportError: cannot import name 'X' from 'Y'" = bot module leak
```

## Real Example: 2026-06-08 sim console /api/console/send

**Original (broken):**
```python
# In app.py
@app.route("/api/console/send", methods=["POST"])
def sim_console_send_endpoint():
    data = request.get_json() or {}
    cmd = (data.get("command") or "").strip()
    from minecraftDiamond import send_minecraft_command  # <-- BROKEN in exe
    _asyncio.run(send_minecraft_command(cmd))
    return jsonify({"ok": True})
```

When packaged: 500 with empty body. The `from minecraftDiamond import ...` failed at request time. The user's mod was working fine (verified via direct `curl`). The bug was 100% in the dashboard's request handler.

**Fix:** Re-implement the small piece the dashboard needs (read `config.yml`, POST to mod for forge mode, log-only for RCON mode). Don't import the bot's module. See `python-dashboard-feature/references/simulated-debug-console.md` for the full code.

## PyInstaller Spec — Current `hiddenimports`

The spec currently includes modules used by the dashboard's import graph. **Do NOT add `minecraftDiamond`, `tiktok_live_handler`, etc. just to make Flask route imports work.** The dashboard should not need those modules. If you find yourself wanting to add them, that's a code smell — refactor to file-based IPC or re-implement.

If a legitimate use case arises where the dashboard genuinely needs a piece of the bot's logic AND the deps are light, add it carefully:

```python
# TikTokMCIntegrator.spec
hiddenimports=[
    'spotipy', 'spotipy.oauth2', 'spotipy.client',
    'spotify_handler', 'edge_tts', 'tts_effects',
    # 'minecraftDiamond',  # NO — heavy deps (TikTokLive, mcrcon)
    # 'actions',           # NO — re-implement the small piece in dashboard
],
```

## See Also

- `python-dashboard-feature/references/process-boundary-pykiller.md` — Full diagnostic recipe
- `python-dashboard-feature/references/simulated-debug-console.md` — Worked example of the file-based IPC + re-implement pattern
- `python-dashboard-feature/references/connector-dispatch-pattern.md` — Bot-side dispatcher that the dashboard mirrors (not imports)
