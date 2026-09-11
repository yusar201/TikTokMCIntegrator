---
name: tiktokmc-desktop-shell
description: "Native desktop shell for the TikTokMCIntegrator Flask app — turning the open-a-browser launcher into a pywebview native window with an instant splash, a first-run setup wizard, bot-running close guard, single-instance second-launch focus, and real app icons, bundled via PyInstaller. Covers the pywebview+pystray threading model, the file:// splash CORS trap and its Python-driven load_url fix, real-config-schema first-run detection, bot subprocess orphan prevention, icon asset generation, and the required PyInstaller hidden imports. Load before touching main.py launcher, splash.html, wizard.html, or the app/tray/splash icons."
trigger: "native window; pywebview; desktop app; splash screen; loading screen; setup wizard; first-run; app icon; tray icon; make it a real app; not a browser; window stuck on starting; single instance; second launch; already running; focus existing window; no double instances"
related_skills: ["tiktokmc-build-deploy", "python-dashboard-feature", "tiktok-live-bot-dev", "glm-frontend-delegation"]
---

# TikTokMCIntegrator — Native Desktop Shell

Turns the Flask dashboard from "opens a browser tab" into real desktop software: a
pywebview native window (Edge WebView2 on Windows), an instant pixel-art splash, a
first-run setup wizard, and the user's logo as app/tray/splash icon. The backend
(Flask, SocketIO, Spotify, RCON, TikTok, OBS overlays) is untouched — this is purely
the launcher/shell layer in `main.py` + a couple of templates + the `.spec`.

**OBS overlays never change.** They stay HTTP browser-sources at `localhost:5000/overlay`.
pywebview only replaces the *dashboard window the user looks at*.

## Architecture (the threading model — get this right)

On Windows BOTH `webview.start()` and `pystray.Icon.run()` want the MAIN thread.
The resolution (verified, and unanimous across a 3-model fusion panel):

- **pywebview owns the MAIN thread** — `webview.start()` blocks there. WebView2 HWNDs
  MUST be created on the thread that pumps the Win32 message loop.
- **pystray runs on its OWN thread via `Icon.run_detached()`** — its documented coexistence path.
- **Flask (waitress) + the song-queue worker run on daemon threads.**
- **NEVER** do the inverse (tray main, webview from a worker) → focus ghosts, DPI desync,
  COM/OLE init failures, undebuggable paint artifacts.
- Tray menu callbacks fire on pystray's thread — only touch the window via thread-safe
  pywebview APIs (`window.show()/restore()`), or fall back to `webbrowser.open`. Never
  create a webview window off the main thread.

Launch sequence in `main.py`:
0. Single-instance guard acquire (before ALL heavy imports — see below)
1. `import paths` (dirs ready) → `ensure_profiles_setup()`
2. `start_song_queue_worker()` (daemon thread)
3. Flask via `serve(app, ...)` (daemon thread)
4. `tray.run_detached()` (own thread)
5. `webview.create_window(title, splash_file_url, ...)` then `webview.start()` (MAIN, blocks)

## THE splash bug (the one that bit us) — file:// → localhost is CORS-blocked

The splash loads from a `file://` origin (bundled `splash.html`, shown BEFORE Flask is up).
If the splash's JS does `fetch('http://localhost:5000/health')`, **Chromium blocks it as
cross-origin** — the promise rejects, the poll retries forever, and the window sits stuck
on "taking longer than usual". The window/WebView2/Flask are all fine; only the *swap* is broken.

**Fix: drive the splash→dashboard swap from PYTHON, not JS.** A background thread polls
`/health` server-side (no CORS in Python), then calls `window.load_url(URL + '/')` — a
top-level navigation, which is NOT subject to CORS. Add `Access-Control-Allow-Origin: *`
to `/health` as belt-and-suspenders, but the Python-driven `load_url` is the reliable path.

```python
def _wait_then_load():
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(URL + "/health", timeout=2) as r:
                if r.status == 200:
                    _window.load_url(URL + "/"); return
        except Exception:
            pass
        time.sleep(0.25)
    webbrowser.open(URL)  # fallback
# started as a daemon thread right after create_window, before webview.start()
```

Readiness detection: poll a real `/health` route, **NOT a socket port-poll** — the listen
socket opens before Flask's route handlers register, so a port poll reports "up" too early and lies.

## First-run wizard — read the REAL config schema or it hijacks existing installs

The wizard shows only on first run, gated by `_is_configured()`. **The trap that bit us:**
I wrote `_is_configured()` against guessed generic keys (`tiktok.username`), but this
project's real schema is different — so an existing, working install read as "not configured"
and the wizard would have hijacked it on launch.

**Always read the actual `config.yml` and confirm the real key paths before writing first-run
detection.** TikTokMCIntegrator's real schema (verified):
- TikTok username → `Settings.TikTokUsername` (also `Settings.MinecraftUsername`)
- RCON → `Rcon.Host`, `Rcon.Port`, `Rcon.Password` (capitalized, top-level `Rcon:` block)
- Forge connector → `Forge.Host/Port/Password`; connector choice → `Settings.ConnectorType` ("rcon"|"forge")
- Spotify enable → **NOT in config.yml** — it lives in `song_config.json` via `spotify_handler.load_config()/save_config()`

`_is_configured()` returns True if `configured: true` flag set OR a real
`Settings.TikTokUsername`/`MinecraftUsername` exists (legacy installs predate the wizard →
treat as configured so it never hijacks them). On unreadable config, return True (don't trap
the user in the wizard). `/` serves `wizard.html` when not configured, else `index.html`;
`/wizard` stays reachable for re-runs; `POST /api/setup` merges onto existing config (never
clobbers unrelated keys) and flips `configured: true`.

**Verification that proves the fix:** run the Flask test_client against Khito's REAL config and
assert `_is_configured() == True` and `/` serves the dashboard (not the wizard). See
`scripts/smoke_test_shell_routes.py`.

## Icons — one logo → app .ico + tray .png + splash base64

User drops a logo (e.g. `Downloads/logo (2).png`, 1024² RGBA transparent). Generate three
assets with PIL (`scripts/make_icons.py`):
- `icon.ico` — multi-size `[(16,16)...(256,256)]`, referenced in the `.spec` EXE block as `icon='icon.ico'`
- `static/logo.png` — 256px, loaded by pystray for the tray (with drawn-diamond fallback if missing)
- splash logo — a **base64 data URI** inlined into `splash.html` (NOT a file path — the splash
  loads via `file://` and a relative/absolute path is fragile; an inline data URI always renders)

The data URI is ~38KB of text — generate it with PIL and inject via a Python re.sub into
`splash.html`, don't hand-paste it.

## PyInstaller bundling (the runtime-resolved imports PyInstaller can't trace)

pywebview's WebView2 backend loads .NET via pythonnet/CLR at RUNTIME, so PyInstaller misses
the chain statically. Required `hiddenimports` in the `.spec` Analysis block:
```
'webview', 'webview.platforms.edgechromium', 'webview.platforms.winforms',
'webview.platforms.cef', 'webview.platforms.mshtml',
'clr', 'clr_loader', 'pythonnet',
'pystray._win32', 'engineio.async_drivers.threading',
```
Add `splash.html` + `wizard.html` to the existing `datas=[('templates','templates'),('static','static')]`
(they ride along with the templates dir). After build, verify the bundle contains
`_internal/webview/`, `_internal/pythonnet/runtime/Python.Runtime.dll`, and
`_internal/webview/lib/runtimes/win-x64/native/WebView2Loader.dll`.

`pip install "pywebview>=5.0"` pulls pythonnet + clr_loader + bottle + proxy_tools. Add the
dep check to `build.bat` (mirror the spotipy pattern) and `pywebview>=5.0` to `requirements.txt`.

## Graceful degradation (never worse than the old browser launcher)

Wrap `create_window` AND `start()` in try/except. The #1 real-world failure is the WebView2
runtime missing on a clean Win10 box — and it can surface ASYNC deep in COM at `start()`, so
a naive try/except around create_window alone may miss it. On any failure: log it, `webbrowser.open(URL)`,
and keep Flask + tray alive (so OBS overlays keep serving). Worst case = exactly the old behavior.

With `console=False` there is ZERO stdout — **log every startup step + any exception to
`logs/launcher.log`** (via `paths.logs(...)`). A silently-dead app gets uninstalled, not debugged.
The launcher log is the first thing to read when the window misbehaves (it's what revealed the
CORS splash bug: "Native window created" + "Flask serving" both logged, so the swap was the only suspect).

## Debugging a frozen startup crash (dies before launcher.log exists)

`launcher.log` only helps once `main.py` runs far enough to log. A crash in the import
chain (`main.py` → `app.py` → addon/service constructors at module top level) dies before
the first log line — the only symptom is PyInstaller's "Unhandled exception in script"
dialog (the windowed bootloader shows it because `disable_windowed_traceback=False`).
That dialog names no module; never guess the culprit from it.

Recipe — console twin spec, hidden launch, output to files, no windows on the user's screen:
1. Generate a console twin — never edit the real spec in place:
   `sed -e "s/name='TikTokMCIntegrator'/name='TikTokMCIDebug'/" -e "s/console=False/console=True/" TikTokMCIntegrator.spec > TikTokMCIDebug.spec`
2. Build it, then stage to an isolated dir with FULL deploy parity: exe + `_internal/` +
   loose `templates/` + `static/` + the loose `addons/` merge from source, plus imported
   live `config/`/`data/`. A hand-staged dir missing the loose `addons/` merge crashes with
   FileNotFoundError inside the addon import chain — identical dialog, wrong culprit.
3. Launch hidden with stdout/stderr redirected to files:
   `Start-Process -FilePath <dir>/TikTokMCIDebug.exe -WorkingDirectory <dir> -WindowStyle Hidden -RedirectStandardOutput <dir>/stdout.txt -RedirectStandardError <dir>/stderr.txt`
4. Read stderr — the real traceback lands there.
5. Delete the debug spec, its `dist/`/`build/` outputs, and the staging dir afterward so
   they can never leak into a real deploy.

Why each step matters: `console=True` restores the traceback that `console=False` discards;
Hidden + redirect keeps the user's screen clean; deploy parity keeps the diagnosis honest.

## Window sizing and selectable logs

Khito expects the desktop shell to feel like a real dashboard, not a small browser popup:

- Create the pywebview window with `maximized=True` so the app opens maximized by default.
- When bringing an existing window forward from tray or close-warning code, prefer `window.maximize()` over `window.restore()`. `restore()` can visibly shrink a maximized window before showing the warning modal.
- Enable text selection globally with `text_select=True` in `webview.create_window(...)`.
- For console/log panes, also allow selection in CSS (`user-select: text; -webkit-user-select: text; cursor: text;`) because dashboard styles may set `user-select: none` on nearby interactive elements.

## Single instance — a second double-click focuses the open window, never a second app

The first launcher owns a named mutex and listens on a named auto-reset activation
event; a later launch signals that event, restores/focuses the existing native window,
and exits before starting anything (no second Flask, tray, or webview).

Order matters — get this wrong and the bot subprocess looks like a second launch:
1. `--run-bot` / `--objective-rush` dispatch FIRST — those modes re-enter the same
   script and must never touch the guard.
2. Acquire the guard BEFORE the heavy imports (`app`, `webview`, `pystray`) so a
   second double-click exits fast.
3. The primary starts a daemon listener on the activation event that re-runs the same
   bring-forward path as the tray Open Dashboard action (`window.show()` +
   `window.maximize()` plus a Win32 restore/maximize/foreground fallback).
4. The second launch signals the event AND attempts direct Win32 focus itself (a
   user-launched process holds foreground rights the primary may lack), then exits 0.

Rules:
- Keep the window title in ONE constant shared by `create_window` and the focus
  call — `FindWindowW` matches the exact title, and a mismatch silently focuses nothing.
- Fail open: if the guard raises, log it and continue normally. A broken guard must
  never make the app unlaunchable. Non-Windows is a no-op primary.
- Expose a public `focus_existing_window()` helper; never import the private ctypes
  boundary from `main.py`.
- Keep the ctypes boundary injectable so tests prove the ordering with a fake API:
  second launch signals the event → attempts focus → closes both handles → exits;
  primary launch holds the mutex → creates the event.
- Packaging: a module statically imported by `main.py` needs no new spec hiddenimport,
  but verify it in `build/.../PYZ-00.toc` (and the `PYZ-00.pyz` bytes) — onedir
  pure-Python modules live in the PYZ archive, never as loose `_internal/*.pyc` and
  never in `base_library.zip`, so listing `_internal/` proves nothing.
- Live proof goes in `release_test/`, never `release/`: launch, note the PID, launch
  again, and require exactly one process with the same PID. Log tails repeat across
  runs — match `=== starting ===` markers and timestamps before concluding anything.
- Launching the test exe opens REAL windows on the user's screen — announce it first,
  and stop every test process afterward, verifying no `TikTokMCIntegrator` process remains.

## WebView2 downloads — explicitly enable them before window creation

pywebview disables downloads by default. A dashboard export implemented with a blob-backed
`<a download>` link can work perfectly in Chrome/Firefox yet do nothing in the desktop app:
no save dialog, no visible error, and the JavaScript conversion pipeline still completes.

Before `webview.create_window(...)`, set:

```python
webview.settings['ALLOW_DOWNLOADS'] = True
```

This applies to gift-icon PNG exports and any future dashboard download/export action. Diagnose
this browser-vs-desktop asymmetry at the shell policy layer before rewriting working canvas/blob
JavaScript or adding a custom Python save bridge. Add a regression assertion that the setting
exists and appears before `webview.create_window(`. See
`references/webview2-dashboard-downloads.md` for the reproduction path and verification pattern.

## Never probe the app with `python app.py --help`

`app.py` has no `--help` handler: the flag is ignored and a full Flask dev
server boots on port 5000 and never exits. That rogue process squats :5000,
so `release/TikTokMCIntegrator.exe` can never bind — the symptom is the
splash stuck on "Starting up..." for 60s followed by a stray
`localhost:5000` browser tab (the launcher's 60s readiness fallback, not the
normal path). Diagnose with `Get-NetTCPConnection -LocalPort 5000` +
`Win32_Process.CommandLine` to find the squatter, `Stop-Process` it, then
relaunch the exe. Read source files instead of running the app to inspect it.

## Validation without a display

The native window can't be clicked headlessly (no display to drive). Prove the Flask layer with the
test_client (`scripts/smoke_test_shell_routes.py`): asserts `/health` 200, `/` serves
dashboard vs wizard correctly for a given config, `/wizard` reachable, `/api/setup` writes the
right schema. The window/WebView2 rendering itself needs the user's eyes on first click — say so.

For download fixes, automated source-level regression tests can prove the pywebview policy is
set before window creation and that the frontend still builds a named download link. The final
native save-dialog behavior remains a Windows/WebView2 interaction check.

## Supporting files
- `scripts/make_icons.py` — generate icon.ico + static/logo.png + splash base64 data URI from one source PNG
- `scripts/smoke_test_shell_routes.py` — Flask test_client smoke test for /health, /, /wizard, /api/setup
- `references/session-2026-06-21-pywebview-conversion.md` — full conversion narrative, the CORS-bug debugging path, and the fusion-panel consensus
- `references/bot-running-close-guard.md` — pywebview `window.events.closing` guard that blocks the X button when the TikTok bot subprocess is still running; includes the styled in-app warning modal + tray fallback pattern
- `references/webview2-dashboard-downloads.md` — diagnose and verify browser-only downloads that WebView2 silently suppresses when pywebview downloads remain disabled
- `references/self-hosted-dashboard-typography.md` — replace decorative fonts across every dashboard text surface with offline, legally redistributable Monocraft; includes escape-path audit and browser/deploy verification

## Build/deploy
This shell ships via the normal build. **Validate in `release_test/`, never `release/`** — see
the `tiktokmc-build-deploy` skill (release_test isolation section). Import the user's live config
from `release/{config,data,assets}` into `release_test/` so they don't reconfigure to test.

## Static-only fixes land live — verify before asking for a restart

The released exe serves dashboard `static/` from disk (loose `release/static/`), so a
template/static-only change shipped via `./deploy.sh --fast` while the exe runs takes effect
on the next page load — no restart needed. The catch: the OPEN dashboard/WebView2 page still
holds the old script in memory and the old `?v=` cache-bust in its served HTML, so Khito sees
nothing change until he hard-refreshes (Ctrl+Shift+R / Ctrl+F5).

Before telling him to restart: prove the new code is actually served live with
`curl http://127.0.0.1:5000/static/script.js | grep -c <new-symbol>` — nonzero means the
fix is live and the answer is a hard refresh, not a restart. Only Python/backend changes
ever require an exe restart. Never kill his running exe to ship a template/static-only fix.
