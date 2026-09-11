---
name: tiktokmc-build-deploy
description: "TikTokMCIntegrator build + deploy protocol — run deploy.sh, exe goes to release/ ROOT (not subfolder), preserve all runtime state, never rm -rf release/."
trigger: "TikTokMCIntegrator build or deploy — also triggers on: deploy; release; build.bat; deploy.sh; did you rebuild; rebuild it; ship it; build it; deploy it; compile it; make the exe; release it; rebuilt it"

related_skills: ["tiktok-live-bot-dev", "spotify-song-queue-architecture", "tiktok-live-event-handling", "minecraft-forge-mod-development"]
---

# TikTokMCIntegrator — Build + Deploy Protocol

> **Session-start note:** If this session started with an OSError, model switch, FD exhaustion, or any context-loss event, slow down and re-read the Pre-Action Gate below before touching `release/`. The 4-fumbling-deploys failure mode this skill prevents is exactly the cold-start mistake that prompted its creation.

## TL;DR

Khito only ever needs to click `release\\TikTokMCIntegrator.exe`. All building, copying, and verifying is your job via one command:

```bash
cd D:\Ikhito\Code\TikTokMCIntegrator && ./deploy.sh
```

`deploy.sh` is now **smart/mtime-based** (2026-06-26):
- Default `./deploy.sh` does a **fast static/template deploy** when only `templates/` or `static/` changed. It skips PyInstaller and copies source `templates/` + `static/` into both `release/` and `release/_internal/` in ~1s.
- It also merges bundled source add-ons from `addons/` into `release/addons/` without deleting user-installed add-ons. Add-on packs must survive deploys like runtime state.
- It does a **full PyInstaller build** automatically when backend/build inputs changed (`*.py`, `routes/**/*.py`, `assets/**/*.py`, `*.spec`, `requirements.txt`, `config.example.yml`, `icon.ico`, `build.bat`) or when dist is missing.
- `./deploy.sh --full` forces full PyInstaller build.
- `./deploy.sh --fast` forces static/template-only deploy.
- Full build now calls Windows Python/PyInstaller directly instead of `build.bat`, avoiding `build.bat`'s redundant nested `release/TikTokMCIntegrator/` deploy. Verified full deploy time dropped to ~52s and fast overlay deploy to ~1s.

## Feature-completeness gate before restart/deploy

When Khito asks for a feature that should be visible in TikTokMCIntegrator, **backend completion alone is not the deliverable**. Before saying “restart the app” or calling it shipped, verify the complete user-facing vertical slice:

1. Backend/service/API exists and is tested.
2. Dashboard controls/display exist where Khito will look.
3. OBS overlay exists when stream presentation is part of the feature.
4. Frontend cache-bust versions are bumped.
5. Flask routes and rendered HTML return 200.
6. `node --check` passes for changed JavaScript.
7. `./deploy.sh` actually ran (full build whenever Python changed).
8. Released EXE and loose + `_internal` frontend/add-on copies are fresh.

**Never tell Khito to restart after source-only or backend-only work when he expects a visible feature.** Restarting an old released EXE cannot expose source changes, and even a correctly rebuilt backend-only feature still looks like “nothing changed.” Either state clearly that the work is intentionally backend-only, or continue through UI and deployment before handing it to him.

## Pre-Action Gate (READ THIS BEFORE TOUCHING `release/`)

**If you are about to type any of: `cp` / `rm` / `mkdir` / `xcopy` against the `release/` directory, OR run `cmd.exe /c build.bat`, OR suggest Khito run `build.bat`, OR do "just one more `cp` to fix the subfolder issue" — STOP.** Run `./deploy.sh` instead. The script is the only correct path on this project. Improvisation is what produced every previous deploy failure (subfolder, half-copied `_internal/`, timed-out `cp` mid-deploy, asking the user to run the build).

### Mandatory command choice and filesystem proof

Before any release build, classify the change and choose exactly one command:

- Backend/Python/spec/dependency/helper packaging changed, or Khito asks for a definite rebuild: `./deploy.sh --full`
- Only dashboard templates/static changed: `./deploy.sh --fast`
- Unsure: `./deploy.sh` and let its mtime logic decide

**Never use `build.bat` as the deploy command.** It is a legacy/manual PyInstaller wrapper whose own deployment target is the known-wrong nested `release\\TikTokMCIntegrator\\` directory. A successful `build.bat` console message proves only that PyInstaller built `dist/`; it does not prove the user-facing release was deployed correctly.

After deploy, do not merely quote the success banner. Inspect the actual filesystem and require:

```text
release/TikTokMCIntegrator.exe                    exists
release/_internal/                               exists
release/addons/<bundled-id>/...                  exists when relevant
release/_internal/addons/<bundled-id>/...        exists when relevant
release/TikTokMCIntegrator/                      ABSENT
```

When add-on/helper artifacts changed, verify the exact loose and `_internal` files and compare hashes where applicable. Only then report completion. If a wrong nested deployment already exists, immediately run the canonical full deploy and verify its removal; do not stop after explaining the protocol.

### Bot-must-be-closed check (the gap that cost a deploy this session)

`deploy.sh` does `rm -rf release/{_internal,templates,static}` then `cp -r` from `dist/`. Under Git Bash on Windows, a running exe locks its files — **if `release\TikTokMCIntegrator.exe` is still running, every `rm` of a `*.pyd` / `*.dll` under `_internal/` will fail with `Input/output error`** (and the `cp` will fail with `Permission denied` on `base_library.zip`). The deploy silently half-fails: `dist/` is rebuilt but `release/TikTokMCIntegrator.exe` keeps its old mtime.

**Before running `deploy.sh`, check the running process from PowerShell:**
```bash
powershell.exe -Command 'Get-Process | Where-Object { $_.Name -like "*TikTokMCIntegrator*" -or $_.Name -eq "python" } | Select-Object Name, Id'
```
**Quoting pitfall:** keep inline PowerShell in **single quotes** when calling it from Git Bash. If you wrap it
in double quotes, Bash expands `$_`/`$_.Name` before PowerShell sees it, producing nonsense like
`D:\...Name : The term ... is not recognized` repeated for every process. That is a shell
quoting bug, not a process-list result.
- **If found and Khito is actively streaming/using the bot:** do NOT auto-kill. Ask him to close/Exit it and wait.
- **If Khito explicitly authorizes autonomous shutdown and confirms nothing is in use (including when away from home):** handle it yourself. Prefer a graceful close first (`CloseMainWindow()` / tray Exit when accessible), wait briefly, then `Stop-Process -Force` only if the tray/background process remains. Re-check that no `TikTokMCIntegrator` process exists before deploy. Do not bounce the task back to him after he delegated control.
  - A closed window is not proof the tray/background process exited. Query the process again; an empty `MainWindowTitle` commonly means the app is still alive in the tray.
  - If the user is away and has delegated control, do not ask them to operate the tray. Stop the residual process yourself, deploy, and verify.
  - Do not relaunch automatically after deploy unless the user asked to run/test it. If you launch solely for a health smoke test and the user does not need it left running, close it after verification.
- If clear: run `deploy.sh` and verify the exe mtime moved to within 60s of deploy start.

**Verify-after-deploy mtime check** (the canary that catches the half-deploy):
```bash
stat -c '%y' dist/TikTokMCIntegrator/TikTokMCIntegrator.exe release/TikTokMCIntegrator.exe
```
If the two timestamps differ by more than 60s, the rm step failed mid-flight — bot was running. Don't ship.

**Verify no stale nested release artifact** (especially if `build.bat` was wrongly run earlier in the session):
```bash
test ! -d release/TikTokMCIntegrator && echo NO_NESTED
```
If `release/TikTokMCIntegrator/` exists, it is not the user's launcher target. Remove only that nested artifact after root deploy is verified:
```bash
rm -rf release/TikTokMCIntegrator
```
Never remove `release/` root.

**The retry pattern (2026-06-06):** if the deploy half-fails with `Input/output error` on `*.pyd`, do NOT panic, do NOT try creative workarounds. Ask Khito to close the exe, wait for confirmation, then re-run `deploy.sh`. The `rm -rf` will succeed and the deploy will complete cleanly. Windows file locks release when the process exits — there's no race window to race. Verified: deploy that failed with I/O errors succeeded on the exact same script after the exe was closed.

The user has said: *"bro tf, you always mess up the build protocol, took you a while to finally did it"* and *"you're supposed to be a self evolving agent, but you're devolving"*. This skill exists because of repeated fumbles. Don't be the next one.

## Path layout — FOLDERIZED (2026-06-19, see references/folderize-path-layout.md)

If the app is stuck on the native loading/splash screen, or `release/active_profile.txt` / root runtime files appear, immediately use `references/release-root-loading-recovery.md`. The usual root cause is a stale/rolled-back `app.py` bypassing `paths.py` and missing `/health`; fix paths + health route, smoke-test routes, clean only misplaced duplicates, then deploy.

The release dir was restructured from a flat junk-drawer (20+ loose files at root) into four subdirs. **`paths.py` is now the single source of truth for all on-disk paths** — it holds the ONE `sys.frozen` check and exposes `paths.config(name)`, `paths.data(name)`, `paths.logs(name)`, `paths.assets(name)`, plus `paths.resolve(name)` (auto-routes by type). Layout under `release/` (or project root in dev):

```
release/
  TikTokMCIntegrator.exe          ← the only thing Khito clicks
  _internal/ templates/ static/   ← swappable build artifacts (stay at ROOT)
  config/   config.yml, profiles/, active_profile.txt
  data/     all runtime JSON (queue, history, tokens, streaks, stats, .reload_signal)
  logs/     all *.log (sim_console, song_queue_worker, tts_debug, superfan_debug)
  assets/   gift_assets/, sounds/, tts/, reports/
  addons/   installable add-on packs (manifests, overlays, actions, optional helper jars)
```

**Migration is automatic on exe launch** — `paths.py` runs an idempotent shim on import that sweeps any legacy root files into their subdir (never clobbers an existing dest, leaves build artifacts + exe + `.reload_signal` rules per references). So right after a deploy the root may still look flat; it tidies itself the first time the exe runs.

**Adding any new runtime file path: ALWAYS go through a `paths.*` helper — never `os.path.join(BASE_DIR, "x.json")` and never a bare `open("x.json")`.** This is what permanently killed the recurring frozen-path bug (see Past Mistakes). `routes/stats.py` is the one module that takes its base via `init_stats_blueprint(DATA_DIR)` — it's pointed at `data/`, so its internal `os.path.join(BASE_DIR, ...)` are correct.

## Native desktop window (pywebview) — planned launcher rework

If the task is "make the exe a native window instead of opening a browser" / pywebview / WebView2 /
splash screen / setup wizard, read `references/native-window-pywebview-architecture.md` FIRST. It
captures the 3-model-fusion-validated design: the Windows threading rule (pywebview on MAIN thread,
pystray via `run_detached()`), the bundled-`splash.html` + `/health`-poll pattern, the #1 risk
(WebView2 runtime absence + pythonnet/CLR PyInstaller chain that fails async in COM at `run()`), the
spec hidden-imports starting list, and Khito's safety rule (validate the new exe in isolation /
`release_test/`, never touch the working `release/` until blessed; tar both source + working release
to `.hermes/backups/` first).

## The 4 Rules (never break these)

1. **Build output goes to `release/` ROOT**, not `release/TikTokMCIntegrator/`. The exe lives at `release/TikTokMCIntegrator.exe`.

2. **Preserve runtime state** across deploys. With the folderized layout, `deploy.sh` preserves the 5 state dirs wholesale (`config/ data/ logs/ assets/ addons/`) AND still preserves legacy root files (for pre-folderize installs mid-migration). Never delete these.

3. **Replace ONLY the 4 deployable artifacts**: `TikTokMCIntegrator.exe`, `_internal/`, `templates/`, `static/`. Source: `dist/TikTokMCIntegrator/`.

4. **Never `rm -rf release/`**. Only `rm -rf release/{_internal,templates,static}` — the 3 subdirs we're swapping.

5. **Runtime asset folders live under `assets/`** now (`sounds/`, `tts/`, `reports/`, `gift_assets/`) — accessed via `paths.assets("...")`. NOT swapped by deploy; cached binaries survive every build.

## Validating a risky build in isolation — `release_test/` (don't touch `release/`)

When Khito wants to test a big/risky change (new launcher, native window, schema change)
**without endangering his working `release/`** — especially when he's about to stream off the
current exe — build to `dist/` and promote to a parallel **`release_test/`** dir instead of `release/`:

```bash
# build straight from the spec (NOT deploy.sh — that copies into release/)
C:\Python313\python.exe -m PyInstaller TikTokMCIntegrator.spec --noconfirm
# promote to the isolated test dir
rm -rf release_test && mkdir -p release_test
cp -r dist/TikTokMCIntegrator/. release_test/
```

For a re-promote that PRESERVES already-imported runtime state in release_test/, swap only the
4 artifacts (same rule as release/): `rm -rf release_test/{_internal,templates,static} release_test/TikTokMCIntegrator.exe`
then copy fresh from `dist/`, leaving `release_test/{config,data,assets}` intact.

**Import the user's live config so he doesn't reconfigure to test:**
```bash
cp -r release/config/. release_test/config/
cp -r release/data/.   release_test/data/
cp -r release/assets/. release_test/assets/
```
This brings over config.yml, profiles, the Spotify token (`data/song_spotify_token.json`),
queue/history, and gift assets — so the test exe launches as his exact setup.

**Always confirm `release/` stayed untouched** after a release_test build: `stat -c '%y' release/TikTokMCIntegrator.exe`
should show the OLD mtime. He clicks `release_test\TikTokMCIntegrator.exe` to test; his real
`release/` remains the rollback. Only promote into `release/` (via deploy.sh) once he blesses it live.

Building directly from the spec also lets you skip build.bat's release-copy step — that's the
whole point, since `build.bat` sets `RELEASE_DIR=release\TikTokMCIntegrator` and would write the
wrong place anyway.

## Why this matters

- The exe reads templates/static via `sys._MEIPASS` which points to `_internal/` at runtime — so both `release/templates/` AND `release/_internal/templates/` must exist (PyInstaller puts them in both places).
- The exe is at `release/TikTokMCIntegrator.exe` (ROOT), not in a subfolder. Khito's shortcut/laucher points there.
- Runtime state is precious — losing `config.yml` or `song_history.json` breaks the bot.

## Renaming a Python source module (rename-safety, verified 2026-06-18)

`minecraftDiamond.py` was renamed to `minecraft_main.py` this session. Renaming any core `.py` module is low-risk IF you trace the real entry points first. What actually breaks vs. what's just noise:

**The bot's process boundary (why most refs are safe):** the dashboard does NOT `import` the bot module directly. `app.py` spawns it as a subprocess via `--run-bot` (`bot_cmd = [sys.executable, '--run-bot']` when frozen, else `[sys.executable, '-u', 'main.py', '--run-bot']`). That flag re-enters `main.py`, whose entry block does `import <bot_module>; <bot_module>.run_bot()`. So the ONLY hard import of the bot module is that one line in `main.py`.

**Rename checklist:**
1. `git mv old.py new.py` (preserves history; falls back to plain `mv` if not tracked).
2. Grep ALL refs: `grep -rn "OldName" --include="*.py" --include="*.spec" .`
3. Fix the real breakers:
   - `main.py` entry block — the `import <module>` under `if sys.argv[1] == '--run-bot'`.
   - Any `.spec` whose `Analysis([...])` names the file as an entry script. Note there are TWO specs: `TikTokMCIntegrator.spec` (ACTIVE — entry = `main.py`, so unaffected by a bot-module rename) and `bot.spec` (entry = the bot module directly; unused by deploy.sh but fix it anyway so it's not a landmine).
4. The rest of the hits (`README.md`, `project_overview.md`, `*.bak`, plan/*.md, comments in `app.py`/`routes/spotify.py`/`gift_assets/manifest.py`) are docs/comments — non-breaking. Freshen comments for consistency; skip `.bak` files.
5. Verify: `C:\Python313\python.exe -m py_compile new.py main.py app.py spotify_handler.py actions.py routes/spotify.py routes/stats.py` then re-grep to confirm zero code/spec refs remain. `py_compile` is the correctness gate — Pyright/LSP diagnostics on files you only touched a comment in are pre-existing, not introduced by the rename.
   - Pitfall: don't smoke-test by reading the renamed UTF-8 file through a one-liner that defaults to cp1252 on Windows Python (`UnicodeDecodeError: charmap codec`). That's the test harness's codec, not a file problem. Use `py_compile` / `ast.parse(open(p, encoding='utf-8').read())`.
6. A pure rename has no behavior change but DOES need a rebuild to ship — run `./deploy.sh` per this skill.

## What `deploy.sh` does (smart/mtime-based, 2026-06-26)

**Mode detection:** compares latest mtime of backend/build inputs (`*.py`, `routes/**/*.py`, `assets/**/*.py`, `gift_assets/**/*.py`, `*.spec`, `requirements.txt`, `config.example.yml`, `icon.ico`, `build.bat`) against `dist/TikTokMCIntegrator/TikTokMCIntegrator.exe`. If backend is newer → full build. If only `templates/` or `static/` changed → fast deploy. Override with `--full` or `--fast`.

**Full build path** (~52s):
1. Calls Windows Python/PyInstaller directly: `$WIN_PY -m PyInstaller TikTokMCIntegrator.spec --noconfirm` (NOT `build.bat` — avoids build.bat's redundant nested `release/TikTokMCIntegrator/` deploy)
2. Verifies `dist/TikTokMCIntegrator/{TikTokMCIntegrator.exe,_internal}` exist
3. `rm -rf` the 3 swappable subdirs (`release/{_internal,templates,static}`)
4. Copies fresh `_internal/`, `templates/`, `static/` from `dist/` (templates/static go to BOTH `release/` and `release/_internal/` since exe reads via `sys._MEIPASS`)
5. Copies/merges bundled source add-ons from `addons/` into `release/addons/` without deleting user-installed add-ons
6. Copies fresh exe to `release/TikTokMCIntegrator.exe`
7. Removes any stale nested `release/TikTokMCIntegrator/` dir
8. Verifies all deployable artifacts exist AND have fresh mtime (within 60s of deploy start), plus bundled add-ons landed in `release/addons/`

**Fast deploy path** (~1s):
1. Skips PyInstaller entirely
2. `rm -rf` `release/{templates,static,_internal/templates,_internal/static}`
3. Copies source `templates/` + `static/` into both `release/` and `release/_internal/`
4. Verifies templates/static have fresh mtime in BOTH locations

**BOT MUST BE CLOSED** for either path (full build's `rm -rf _internal/` fails on running exe; fast deploy's `rm -rf _internal/templates/` can also fail on file locks). Check process first, stat-verify after.

**`build.bat` is now legacy** — deploy.sh no longer calls it. It still exists for manual/emergency builds but `deploy.sh` calls PyInstaller directly. If you must use `build.bat`, remember it deploys to `release/TikTokMCIntegrator/` (wrong nested path) and you'd need to manually fix. Prefer `./deploy.sh` always.

**Add-on deploy rule (2026-07-07):** `release/addons/` is runtime/add-on state and must survive deploys like `config/ data/ logs/ assets/`. `deploy.sh` merges bundled source add-ons from `addons/` into `release/addons/` without deleting user-installed packs. When adding bundled add-ons, verify both `release/addons/<id>/addon.yml` and `_internal/addons/<id>/addon.yml` after full builds.

## Past mistakes (NEVER REPEAT)

- ❌ Put output in `release/TikTokMCIntegrator/` subfolder (Khito's exe shortcut points to `release/` root)
- ❌ Forgot to copy templates/static to `release/_internal/` (exe reads via sys._MEIPASS)
- ❌ Did `rm -rf release/` to "start fresh" — nuked his config & history
- ❌ Half-populated `_internal/` from a timed-out `cp` and didn't notice
- ❌ Asked Khito to run `build.bat` himself — **that's my job, always**
- ❌ Took 4+ round-trips to deploy — should be 1 command, every time
- ❌ Suggested Khito "could run build.bat" instead of just doing it — caused a full back-and-forth where I had to apologize and do it anyway. **Default to executing, never delegate the build to the user.**
- ❌ Used `__file__`-based BASE_DIR in a new source-tree package (`gift_assets/manifest.py`) without the `sys.frozen` check. When frozen by PyInstaller, `os.path.dirname(os.path.dirname(__file__))` resolves inside `_internal/` or stays at the source tree — never the release dir. This is the **3rd recurrence** of this exact bug (previous: `report_helpers.py` June 1, `constants.py` was already correct). **New packages that need runtime file paths MUST use the same pattern as `minecraft_main.py`:** `os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))`.
- ❌ **Deployed a song-system fix from a wrong mental model (2026-06-06).** I wrote a 3-part plan claiming the bug was a worker stale-cache race. Deployed it. User tested on stream, fix didn't work, had to be reverted. Real bugs were elsewhere (see spotify-song-queue-architecture skill Bug 6/7). **Rule: before deploying any song-system fix, trace through the user's exact reported flow and verify the fix would resolve each step. If you can't show the fix working at each step, do NOT deploy.** Even a "low-risk refactor" that won't fix the actual bug wastes a stream's worth of testing time. The deploy itself worked perfectly; the failure was in the planning step that came before deploy.
- ❌ Half-deploy from a running exe (recurring, 2026-06-06). `deploy.sh` silently half-fails if `release\\TikTokMCIntegrator.exe` is running. The `rm -rf` of `_internal/*.pyd` returns `Input/output error` (Windows file lock), the `cp` after that gets the old stale files, and `release/TikTokMCIntegrator.exe` keeps its old mtime while `dist/` shows a fresh build. Always check the running process BEFORE deploy, and always stat-verify the mtime AFTER deploy. If the mtime didn't move, the deploy didn't ship.
- ❌ Ran `build.bat` directly and then manually copied nested output to root (2026-06-09). `build.bat` deploys to `release/TikTokMCIntegrator/` because `RELEASE_DIR=release\\TikTokMCIntegrator`, while Khito launches `release/TikTokMCIntegrator.exe` at the root. Manual root-copy fixed that session but violated this skill's rule. **Future rule: for "rebuild and deploy" use `./deploy.sh` first, not `cmd.exe /c build.bat`. If forced to use `build.bat`, explicitly verify root exe mtime moved and treat nested-only output as not deployed.**
- ❌ Reverted `app.py` to pre-folderized path layout (2026-06-24). This made the native window stick on the loading splash because `/health` disappeared, and recreated `release/active_profile.txt` / `release/profiles/` at root because `CONFIG_FILE`, `PROFILES_DIR`, and `ACTIVE_PROFILE_FILE` used `BASE_DIR` directly. **Also lost the `'coingoal'` entry from `valid_types` in both overlay routes** — the coin-jar overlay returned 404 silently. Recovery checklist after an app.py revert: (a) ensure all runtime paths use `paths.*` helpers, not `BASE_DIR`; (b) add `/health` route if missing; (c) verify `valid_types` in both `overlay_page()` and `overlay_demo_page()` include the full set (see `tiktokmc-overlay-system` skill's overlay type checklist); (d) smoke-test `('/', '/health', '/api/config', '/api/stats/viewers', '/api/console/logs', '/overlay/coingoal')` before deploy.

## Session-load note (for future me)

The `tiktokmc-build-deploy` skill exists precisely because of these past mistakes. If you find yourself about to type a `cp` or `rm` command against the `release/` directory, or about to ask the user "want me to build it?", STOP. Run `./deploy.sh` instead. The script is the only correct path on this project.

## When to use

- Every time source code is edited and a release build is needed
- When the user says "rebuild", "deploy", "build it", "ship it"
- After any code change to `*.py` files in the project

## Out of scope: Minecraft mod deployment

`deploy.sh` ships the **bot** only. The Minecraft mod (currently `tiktokbridge`, built from `C:\Users\yusar\Documents\Code\Minecraft\forge-mod-khito\`) is a **separate build target** with its own gradle build, its own deploy path (drop the JAR into `<curseforge-instance>/mods/`), and its own pitfalls (Java 21 vs 17, MDK scaffold, reflection on `Minecraft.singleplayerServer`).

**Do NOT try to add the mod build to `deploy.sh`.** Different toolchain, different deliverable, different deploy location. Build and install the mod separately — see the `minecraft-forge-mod-development` skill for the full workflow.

If Khito asks "rebuild + deploy" and the change is in mod code, the answer is:
1. `cd C:\Users\yusar\Documents\Code\Minecraft\forge-mod-khito && JAVA_HOME=C:\Program\ Files/Java/jdk-17 ./gradlew build --no-daemon`
2. `cp build/libs/<mod_id>-<version>.jar C:\Users\yusar\curseforge\minecraft\Instances\Mohist\mods\`

If the change is in the bot (Python) — use `deploy.sh` as normal.

## WebView2 Cache: Stale Dashboard After Deploy

After deploying a new EXE, if the user reports that profile switching doesn't change data or a blank profile still shows old events/gifts, the most likely cause is **WebView2's embedded browser cache** serving stale `script.js` or `index.html`. The backend API works fine (test via curl/browser on `localhost:5000`), but the frozen WebView2 window runs cached JS from the old deploy.

**First diagnostic:** test the EXE's API via curl — `curl http://localhost:5000/api/profiles` and `curl http://localhost:5000/api/config` should show correct data. If they do, the bug is in the frontend cache, not the backend.

**Fix:** Bump the cache-busting version string in `templates/index.html` (`?v=N+1`) and rebuild. See `references/webview2-cache-stale-dashboard.md` for full details, forced-workarounds, and prevention.

If the API also shows wrong data, it's not a cache issue — investigate profile paths, file permissions, or a half-deployed EXE (see the bot-must-be-closed check above).

## Self-Evolution Contract (2026-06-04)
The user explicitly said: *"bro tf, you always mess up the build protocol, took you a while to finally did it. but seriously? i gotta do this every single day in new session?"* and called out that I should be a **self-evolving agent, not devolving**.

This skill EXISTS BECAUSE of repeated fumbles. The previous session-by-session pattern was:
- Memory said "BUILD & DEPLOY: 1) build.bat 2) cp exe..."
- Each new session re-derived the steps from memory
- Each session made different mistakes (subfolder, half-copied _internal, timeout blindness)

The new contract:
- **Never improvise.** If `deploy.sh` exists at the project root, run it. Don't recreate the steps.
- **Never re-explain the protocol to the user.** They don't want to think about it. They click the exe.
- **If you need a new step the script doesn't cover, update the script first**, then run it. Don't just do it once.
- **In a new session, if you find yourself re-deriving the build steps, STOP and check this skill first.** That's the failure mode this skill was created to prevent.

## Khito's Communication Style (for this project)

When Khito issues terse imperatives like *"now just log everything man"* or *"deploy"*, the right response is:
1. **Execute immediately.** No "got it, I'll do X, Y, Z" preamble.
2. **One short confirmation when done.** "Logged. Deployed. Click the exe."
3. **Don't explain your reasoning unless asked.** Especially don't re-state the problem you just solved.

Long session-log requests like *"log today's activities"* are the ONE exception — he does want a structured log. But still: no editorializing, no apologies for past mistakes, no "next time I'll do better". Just the facts.

Anti-pattern to avoid: a sequence of [greeting] + [re-statement of what was asked] + [action] + [confirmation] + [suggested next step] = 5 messages for a 1-step task. Khito reads the first message, does the action, ignores the rest. Wastes tokens.

## What to Test After Deploy (for the user's common scenarios)

When Khito says "I made a change, ship it" — after running deploy.sh, he tests:
1. **Queue song ends naturally** — should auto-advance to next queued song OR fall back to loop song
2. **User manually pauses Spotify** — should stay paused indefinitely (worker MUST NOT auto-resume)
3. **Loop song ends naturally** — should auto-resume after Spotify clears the item

**Test Connection per-connector edge case (2026-06-24):** The Test Connection button MUST send
the currently selected connector's form values (host/port/password/apikey) from the UI, NOT
read from saved config.yml. If it reads saved config instead of form values, the test will target
the saved connector's port (e.g. RCON's 25575) even when the user just switched to ServerTap
without saving first. The backend endpoint accepts a JSON payload with the connector type + its
form values: `{"connector_type":"servertap","servertap":{"Host":"...","Port":4567,"ApiKey":"..."}}`.
When the UI sends the currently-displayed form fields rather than saved config, the test correctly
exercises the connector the user intends to use.

If any of these regresses, the `spotify-song-queue-architecture` skill's "Worker logic" section is the source of truth.
