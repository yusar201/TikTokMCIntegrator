# Native Desktop Window (pywebview) — Architecture + Build Notes

**Status:** Design approved by a 3-model fusion panel (DeepSeek-v4-pro + Kimi-K2.7-Code +
GPT-5.5), UNANIMOUS on the core. **Not yet implemented/verified on the real build as of
2026-06-21.** Treat the threading rule and the PyInstaller/WebView2 pitfalls below as durable
(they're general truths the panel agreed on); treat exact hidden-import lists as a starting point to
verify on a clean machine, not gospel.

Goal of the change: replace "launch opens the default browser at localhost:5000" with a native
borderless window (Edge WebView2 via pywebview) so it feels like real software, not a webpage.
OBS overlays are UNAFFECTED — they keep hitting `localhost:5000/overlay` over HTTP. pywebview only
replaces the dashboard/control window Khito personally looks at.

## The threading rule (the one thing to get right)

On Windows BOTH `webview.start()` (pywebview GUI loop) AND `pystray.Icon.run()` demand the MAIN
thread. They conflict. Resolution:

- **pywebview owns the MAIN thread** (`webview.start()` blocks there).
- **pystray runs on a worker via `icon.run_detached()`** — this is pystray's *documented*
  coexistence path, not a hack. `run_detached()` spawns its own Win32 message pump and returns.
- **NEVER** do the inverse (tray on main, webview created from a worker). WebView2 creates real
  HWNDs that MUST be created on the thread pumping the message loop. Worker-thread windows →
  focus ghosts, DPI scaling desync, OLE/COM init failures, undebuggable paint artifacts.
- **Don't drop pystray** — streamers rely on the tray during gameplay; cutting it is a UX regression.
- **Cross-thread GUI calls:** pystray menu callbacks fire on the tray thread. Do NOT call
  `webview.windows[0].load_url(...)` directly from there. Marshal via a `queue.Queue` the webview
  polls, or use `evaluate_js`, or keep the tray action trivial (focus window / `webbrowser.open`).

## Splash screen (avoid the cheap blank-window look)

- The amateur tell is a blank white window while Flask boots — NOT a loading screen.
- Show a **bundled local `splash.html` via `file://` BEFORE Flask is up** (resolved through
  `sys._MEIPASS` when frozen). The SAME window morphs splash → dashboard (zero visual jank).
- The splash's own JS polls readiness and redirects itself:
  `setInterval(() => fetch('http://localhost:5000/health')...→ window.location='http://localhost:5000', 200)`
  with a ~15s soft timeout that keeps retrying and shows a "still starting…" state (never frozen).
- This keeps all polling in the WebView2's JS — no Python-side polling/threading headache.

## Readiness detection: health endpoint, NOT port-poll

A socket port-poll LIES — the listen socket opens before Flask's route handlers register. Add a real
`GET /health` route returning `{"ready": true}` 200 and poll THAT. (Route registered = ready.)

## #1 RISK: WebView2 runtime absence + the pythonnet/CLR PyInstaller chain

All three models flagged this as the single biggest break/feel-cheap risk:

- pywebview's `edgechromium` backend loads the .NET CLR via `pythonnet` (`clr`), then instantiates a
  WinForms `WebView2` control. PyInstaller cannot statically trace this chain.
- WebView2 Evergreen runtime is preinstalled on Win11 but MISSING on a chunk of Win10 gaming
  machines (the target audience). Bundle works on the dev box, breaks on a clean VM.
- **The trap:** `import webview` succeeds and `webview.create_window(...)` succeeds constructing the
  object, but actual window creation fails deep in COM at `run()` — ASYNC, so a naive try/except
  around `create_window` may NEVER catch it.
- **Mitigations:**
  - Proactive WebView2 probe BEFORE `webview.start()`; on failure → log + `webbrowser.open()` +
    keep tray alive (degrades to exactly the current browser behavior — never worse).
  - `console=False` means ZERO diagnostic output on failure → **log everything to `logs/` on
    startup** (use `paths.logs(...)`), especially the webview init exception. A silently-dead app
    gets uninstalled, not debugged.
  - Optionally bundle the WebView2 Evergreen bootstrapper (~2MB) in `_internal/` to auto-offer install.
  - `mshtml` (Trident/IE) is a possible degraded middle-fallback but renders the pixel-art skin
    badly — prefer a clean browser fallback over mshtml.

## PyInstaller spec changes (verify on a clean VM, don't trust the dev box)

Starting point for `TikTokMCIntegrator.spec` (the ACTIVE spec, entry = `main.py`):
- `datas`: add `('templates/splash.html', 'templates')` (and `wizard.html` when Phase 3 lands).
- hidden imports to add: `webview.platforms.edgechromium`, `webview.platforms.winforms` (and/or
  `webview.platforms.win32`), `clr`, `clr_loader`, `pythonnet`, `pystray._win32`,
  `engineio.async_drivers.threading`.
- Brute-force start: `--collect-all webview`, then prune.
- If pythonnet native DLLs aren't collected, add them via `--add-binary` into the onedir root.
- Add `pywebview` to `requirements.txt` AND the `build.bat` dependency check (mirror the spotipy
  `pip show` pattern).
- Keep **waitress** — overlays need HTTP; pywebview is just a window pointing at localhost.

## Portable layout (already correct)

Use `paths.py` (`os.path.dirname(sys.executable)` when frozen) — config/data/logs/assets next to the
exe, NEVER `%APPDATA%`, no admin/installer. Program Files is read-only for normal users and would
break config writes (silent VirtualStore redirect). Portable IS the premium choice for streamers.

## First-run setup wizard (rides on top of the native window)

The native window is the perfect vehicle: first-run detection in `app.py` (no `config/config.yml` or
no `configured: true` flag) → Flask serves `/wizard` at root instead of the dashboard. Multi-step
Stardew-skinned flow (TikTok username → Spotify OAuth → RCON host/port/pass → paths) → save → flip
flag → redirect to dashboard. Next launch skips it. Feels like a real installer inside the native window.

## Safety convention for risky launcher rewrites (Khito)

Khito's rule when reworking the launcher/exe: **do NOT deploy to `release/`** until the new build is
validated live. Build/validate the new exe in isolation (`dist/` or a parallel `release_test/`), keep
the working `release/` as the rollback. Always tar both source and the current working `release/` into
`.hermes/backups/` (+ a `git tag backup-pre-<feature>-<ts>` via `git stash create` to capture WIP)
BEFORE starting. Rollback = untar the working-release tar over `release/`, click the exe.
