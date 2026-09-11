# Session 2026-06-21 — Browser-launcher → pywebview native shell conversion

Full narrative of the conversion, kept for the debugging path and the design rationale.

## What was built (in order)
1. `/health` route + first-run routing (`/` serves wizard.html when not configured, else index.html) + `/wizard` + `POST /api/setup` in `app.py`.
2. `templates/splash.html` — self-contained pixel-art Stardew splash (no external fonts/CSS — loads via file:// before Flask is up), animated pip loading bar.
3. Rewrote `main.py` entry block: webview main thread, `tray.run_detached()`, WebView2 try/except + browser fallback, `logs/launcher.log` logging.
4. `pywebview>=5.0` → requirements.txt + build.bat dep check.
5. `.spec` hidden imports for webview/pythonnet/pystray.
6. `templates/wizard.html` — 3-step Stardew-skinned setup (TikTok username → RCON → Spotify toggle).
7. Icons: `logo (2).png` → icon.ico (exe) + static/logo.png (tray) + base64 inline (splash).

## The CORS splash bug — debugging path (the valuable part)
Symptom: window opened, showed splash, stuck on "taking longer than usual", never reached dashboard.

How it was diagnosed WITHOUT a display:
1. Read `release_test/logs/launcher.log` → it showed `Native window created`, `Flask serving on http://localhost:5000`, `System tray started`, `Native window closed by user`. So: window rendered (WebView2 works), Flask started, tray up. Only the SWAP was broken.
2. `curl http://localhost:5000/health` → Flask answered (well, the OLD release exe was answering on :5000 — a confound, see below). Confirmed Flask itself serves fine.
3. Root cause deduced: splash JS does `fetch('http://localhost:5000/health')` from a `file://` origin → Chromium blocks file://→http:// as cross-origin → promise rejects → retry forever.

Fix: moved the swap to Python — `_wait_then_load()` daemon thread polls /health server-side (no CORS), then `_window.load_url(URL + '/')` (top-level nav, no CORS). Added `Access-Control-Allow-Origin: *` to /health as backup.

Confound noticed during debug: PID on :5000 was the user's OLD `release\TikTokMCIntegrator.exe` (still running, he was about to stream). The new release_test build couldn't have bound :5000 anyway. Always check WHICH exe owns the port before trusting a curl result: `powershell.exe -Command 'Get-NetTCPConnection -LocalPort 5000 -State Listen | %% { Get-Process -Id $_.OwningProcess }'`.

## The config-schema trap (the second valuable lesson)
First `_is_configured()` checked `cfg.get("tiktok",{}).get("username")` — a GUESSED key. Tested against Khito's real config and found username actually at `Settings.TikTokUsername` (values seen: `toonzyxd`, `craftedbygewie`). Had it shipped, the wizard would have hijacked his working install on first launch. Caught only because I ran the test_client against the REAL config before declaring done. Lesson: read the actual config.yml keys before writing first-run/migration detection.

## Fusion panel consensus (3 models, unanimous)
DeepSeek-v4-pro + Kimi-K2.7-Code + GPT-5.5 all agreed: pywebview main / pystray run_detached; bundled file:// splash that polls a real /health (NOT socket port-poll); keep waitress; #1 risk = WebView2 runtime absence + pythonnet/CLR PyInstaller chain (fails async in COM at start(), naive try/except misses it; log everything since console=False = no stdout). Kimi uniquely flagged cross-thread GUI marshalling (tray callbacks must not call webview off-thread) — which directly informed driving the swap from Python.

## Settings UI polish (later in same session, via GLM-5.2)
Connector radios → segmented pill; Gift Downloader + Debug Mode bulky cards → one compact "Options" card with two `.opt-row` toggle rows. Routed to GLM per glm-frontend-delegation skill. Critical constraint that made it safe: preserve all JS-bound IDs (`connector-type-rcon/forge`, `name="connector-type"`, `rcon/forge-settings-card`, `gift-asset-downloader(-label)`, `debug-mode(-label)`) — radios visually hidden but still real inputs driven by `<label for>`. Always grep script.js for bound IDs and hand GLM an explicit "DO NOT BREAK THESE IDs" list before a settings restyle.

## pywebview version note
`pip install "pywebview>=5.0"` installed pywebview 6.2.1 + pythonnet 3.1.0 + clr_loader 0.3.1 + bottle + proxy_tools. Bundle verified to contain Python.Runtime.dll and WebView2Loader.dll (win-x64/x86/arm64).
