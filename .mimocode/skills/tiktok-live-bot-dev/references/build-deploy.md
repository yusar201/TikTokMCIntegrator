# TikTokMCIntegrator Build & Deploy Protocol

## Who Runs What (CRITICAL — user corrected 2026-06-04)

**The agent runs the build AND flattens the release layout. The user only clicks the exe to test.**

- **Agent**: runs `cmd.exe /c build.bat`, then flattens `release/TikTokMCIntegrator/` → `release/` root, verifies timestamps, tells user the release is ready.
- **User**: closes the running app, double-clicks `release/TikTokMCIntegrator.exe` (at root, not in a subfolder).

If you (the agent) tell the user "the build/deploy process is on your side" — **WRONG**.
Run it. The user has better things to do than babysit PyInstaller.

## Canonical Release Layout (user corrected 2026-06-04)

```
release/                          ← user clicks exe HERE (at root, not in a subfolder)
  TikTokMCIntegrator.exe
  _internal/
    templates/
    static/
    ... (PyInstaller DLLs)
  config.yml                      ← preserved
  profiles/                       ← preserved
  song_*.json                     ← preserved
  ...
```

`build.bat` is wrong — it dumps output to `release/TikTokMCIntegrator/` (a subfolder).
**The agent must flatten it to `release/` root after every build.** This is non-optional.

## The Full Build + Flatten Sequence

```bash
cd D:\Ikhito\Code\TikTokMCIntegrator
cmd.exe /c build.bat                # builds to release/TikTokMCIntegrator/

# Then flatten: move new build artifacts up to release/ root, keep user data in place
cd release
cp -f TikTokMCIntegrator/TikTokMCIntegrator.exe ./TikTokMCIntegrator.exe
rm -rf _internal templates static
cp -r TikTokMCIntegrator/_internal .
cp -r TikTokMCIntegrator/templates .
cp -r TikTokMCIntegrator/static .
rm -rf TikTokMCIntegrator
```

`cp -r` of `_internal/` can take 30-60s under Git Bash — don't time out at 30s. If a previous
timed-out cp left `_internal/` half-populated (e.g. 53 entries instead of ~124),
`rm -rf _internal` and recopy.

**Preserve at `release/` root (do not touch):**
- `config.yml`, `profiles/`, `active_profile.txt`
- All `song_*.json`, `stream_state.json`, `active_streaks.json`, `superfan_log.json`
- `tts/`, `tts_*.json/log`, `reports/`, `available_gifts.json`
- Any user-created runtime data

**Templates + static** live at `release/_internal/templates/` and `release/_internal/static/`
(where `sys._MEIPASS` points at runtime). They MUST be in `_internal/` for the exe to find them.

## Post-Build Verification (do this, then report to user)

```bash
# Exe timestamp should be "now" (within last few minutes)
stat -c '%Y %n' release/TikTokMCIntegrator.exe

# Templates + static should also be fresh
ls -la release/_internal/templates/ release/_internal/static/

# _internal should have ~124 entries (full PyInstaller output)
ls release/_internal | wc -l

# Config files should have been preserved
ls -la release/config.yml release/profiles/
```

If exe timestamp is stale, build silently failed — re-run with more verbose output.
If `_internal/` has <100 entries, a previous cp timed out mid-copy — `rm -rf _internal` and recopy from `dist/`.

## Pitfalls

- **Locked exe**: App stays running in memory after closing the window. If the
  build's cp step fails with "Permission denied" or "file in use", the user
  forgot to close the running app. Remind them: "close the running app, then
  I'll rebuild."
- **Stale frontend**: If HTML/JS/CSS changes aren't visible after a rebuild,
  the exe loaded old files from `sys._MEIPASS`. Confirm `_internal/templates/`
  and `_internal/static/` got the new files (check `mtime`).
- **Config loss**: `build.bat` does its own backup/restore, but only inside the
  subfolder it created. After flattening, the user data at `release/` root is
  untouched. Always verify `release/config.yml` is the real one, not a placeholder.
- **User runs build instead of you**: They CAN run `build.bat` themselves in an
  emergency, but it's a legacy wrapper — awkward to verify. Default to running it
  yourself via `cmd.exe /c build.bat`.
- **System FD exhaustion**: If terminal / read / grep all fail with
  `[Errno 24] Too many open files`, the shell FD limit is hit. Restart the shell
  (or raise the FD limit) before continuing.
  This is an environment issue, not a project issue.
- **build.bat uses `rmdir /S /Q` on the whole subfolder** (line 89). It only
  destroys `release/TikTokMCIntegrator/`, NOT `release/` root. Safe in itself,
  but be aware it nukes any data that ended up in the subfolder from a previous
  bad flatten.

## After You Tell the User "Build Done"

User will:
1. Close the running app (Task Manager if needed)
2. Double-click `release/TikTokMCIntegrator.exe` (AT ROOT)
3. Test the feature you just fixed

**Always remind them to restart the app.** The old process runs with old code —
they will report "it didn't work" if they don't restart.
