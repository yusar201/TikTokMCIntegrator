# Objective Rush — In-Game Sidebar + Headless Runtime

Use this pattern when Minecraft gameplay depends on a Python objective engine, but the player must not need to watch an OBS overlay or open the full streaming dashboard while testing/playing.

## Ownership boundary

Keep one authoritative Objective Rush engine:

- **Python service:** objective selection, baselines, progress, Wins, Strikes, persistence, lifecycle.
- **Forge helper:** reads authoritative OneBlock phase/counter, displays state in Minecraft, forwards `/rush` actions.
- **Minecraft scoreboard:** presentation only. Never duplicate objective evaluation or counters in Java/Skript.

The Forge helper polls the existing Objective Rush status response and combines it with local OneBlock phase data. This prevents split-brain state between overlay, dashboard, and game.

## Native sidebar contract

Use a single reusable scoreboard objective (for example `ob_rush`) in the sidebar slot. Keep within Minecraft's 15-line sidebar limit.

Recommended compact rows:

```text
ACTIVE / IDLE / APP OFFLINE
Wins 4/10
Strikes 2/3
────────────
Objective
Mine OneBlocks
Mine 15 OneBlocks
Progress 7/15
────────────
OneBlock
Tutorial
Next phase: 39
```

Rules:

1. Show status, Wins, Strikes, objective name, description, progress/target, phase, and blocks remaining.
2. Poll about once per second, not every tick.
3. Perform HTTP off the Minecraft server thread.
4. Enqueue scoreboard mutations back onto the server thread.
5. Reuse one objective; do not leak new scoreboard objectives each refresh.
6. Snapshot and restore any unrelated sidebar when the controller stops.
7. On transient app loss, show `APP OFFLINE` while retaining the last known objective values.
8. Read OneBlock phase/remaining directly from the Forge companion so that data stays useful even when Python is offline.

### Duplicate-line pitfall

Scoreboard entries are keyed by their full string. Duplicate visible rows collapse. Append invisible formatting-code suffixes (`§0`…`§f`) until every internal entry is unique while preserving what the player reads.

### Formatting tests

Test pure formatting before runtime code:

- active state contains every essential field;
- idle/offline fallbacks are explicit;
- values clamp safely;
- no line exceeds the chosen readable width;
- all internal entries are unique;
- total rows stay at or below 15.

Test the JSON parser separately against the actual Python state shape, including `active: null` and malformed payloads.

## Headless Objective Rush mode

Minecraft-only play should not require the desktop shell, TikTok connection, Spotify, TTS, tray, or dashboard window.

Provide an explicit process mode such as:

```text
TikTokMCIntegrator.exe --objective-rush
```

This mode should serve only:

- `GET /health` identifying `mode: objective-rush`;
- the Objective Rush Blueprint/API;
- the Objective Rush service and poller;
- persistent state through normal `paths.*` helpers.

Bind to `127.0.0.1`, not `0.0.0.0`, because this is a local game companion.

### Critical import-order rule

Dispatch process modes at the very top of the PyInstaller entry script, after stdlib imports but **before** importing:

- `app.py` / dashboard routes;
- `minecraft_main` except for `--run-bot`;
- Spotify/TTS modules;
- `pywebview`, `pystray`, PIL/native shell code.

Otherwise `--objective-rush` still pays the full app startup cost or triggers unwanted side effects merely through imports.

Pattern:

```python
if __name__ == '__main__' and len(sys.argv) > 1:
    if sys.argv[1] == '--run-bot':
        import minecraft_main
        minecraft_main.run_bot()
        sys.exit(0)
    if sys.argv[1] == '--objective-rush':
        from objective_rush_headless import run
        run()
        sys.exit(0)

# heavy dashboard/native-shell imports only below this point
```

## One-click launcher

Place an idempotent launcher beside the Minecraft server's normal `run.bat`:

1. Probe `http://127.0.0.1:5000/health`.
2. If healthy, exit without spawning a duplicate.
3. Otherwise start the released EXE with `--objective-rush`, preferably minimized.
4. Poll `/health` for readiness and report failure clearly.

Prefer an explicit launcher until shutdown/orphan handling is proven. Do not silently spawn hidden long-lived processes from `/rush start` without lifecycle ownership.

## Verification ladder

1. **Pure tests:** formatting and parser tests fail first, then pass.
2. **Focused Python tests:** headless `/health`, Objective API lifecycle, and import-isolation test.
3. **Compile/build:** Windows Python compile and full PyInstaller build.
4. **Release proof:** root EXE + `_internal` exist, no nested release artifact, runtime state preserved.
5. **Headless proof:** `/health` returns `{"status":"ok","mode":"objective-rush"}` and process command line contains only `--objective-rush` (no bot subprocess).
6. **Minecraft proof:** real `/rush start` selects an objective and sidebar shows authoritative progress.
7. **Cleanup:** abort the synthetic test run so the user's next run starts clean. Stop only the test/headless process if the user does not want it left running.

## Common pitfalls

- Starting the full dashboard just to expose the Objective API wastes resources and may encourage accidental TikTok connection.
- Putting the mode dispatch below `from app import app` defeats isolation because `app.py` initializes services on import.
- Testing `/rush start` from RCON without player context fails because the command requires a player. Execute as an online player or call the API only for an isolated engine test.
- A `409 run already active` after a Minecraft `/rush start` attempt is evidence the first start succeeded; inspect state before trying again.
- Offline sidebar mode intentionally retains stale values. After injecting synthetic state, restart/clear it or abort the test run before handoff.
