# Folderized Release Layout + `paths.py` (2026-06-19)

The release dir went from a flat junk-drawer (20+ loose JSON/log files beside the
exe) to four subdirs, driven by one new module: `paths.py`.

## paths.py — single source of truth

- Holds the **ONE** frozen-aware root resolution for the whole app:
  `BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))`
- Exposes `CONFIG_DIR / DATA_DIR / LOGS_DIR / ASSETS_DIR` and helper fns:
  - `paths.config(name)` → `config/`  (config.yml, profiles/, active_profile.txt)
  - `paths.data(name)`   → `data/`    (all runtime JSON + `.reload_signal`)
  - `paths.logs(name)`   → `logs/`    (anything `*.log`)
  - `paths.assets(name)` → `assets/`  (gift_assets/, sounds/, tts/, reports/)
  - `paths.resolve(name)` → auto-route by type: known config files → config/,
    `*.log` → logs/, everything else → data/. Use to replace bare cwd opens.
- On import it (1) `makedirs` the four dirs, (2) runs `_migrate_legacy_layout()`.

## Migration shim (idempotent, runs on every import / exe launch)

- Lists `BASE_DIR`, classifies each entry, `shutil.move`s into the right subdir
  **only when the destination does not already exist** (never clobbers live state).
- Classification:
  - dirs `gift_assets/ sounds/ tts/ reports/` → assets/
  - dir `profiles/` → config/
  - files `config.yml`, `active_profile.txt` → config/
  - `*.log` → logs/
  - `*.json` → data/
- **Stays at ROOT** (never migrated): `_internal templates static config data logs
  assets` dirs, the exe, and anything that isn't a json/log/known-config file
  (e.g. `.reload_signal` lives in `data/` because the code writes it there
  explicitly, NOT via the shim's root sweep).
- Safe to run from both the dashboard and bot processes concurrently (move is
  best-effort, wrapped in try/except).

## Why this killed the recurring frozen-path bug

Before, each module rolled its own `BASE_DIR` with the `sys.frozen` check — and
`gift_assets/manifest.py` (June 18), `report_helpers.py` (June 1) each got it
wrong at least once (resolving inside `_internal/` or the source tree when
frozen). Centralizing the check in `paths.py` means there is exactly one place
it can be wrong, and it's tested. **Rule: new runtime file paths go through a
`paths.*` helper, never a fresh `os.path.join(BASE_DIR, ...)` or bare
`open("x.json")`.**

## Conversion scope (what got touched)

~70 references across `minecraft_main.py`, `app.py`, `spotify_handler.py`,
`routes/stats.py` (via `init_stats_blueprint(DATA_DIR)`), `report_helpers.py`,
`gift_assets/manifest.py`. Most files use named path constants, so repointing the
constant fixes all its call sites at once. The riskiest were the bare
cwd-relative opens in `minecraft_main.py` (`load_json("available_gifts.json")`,
`save_json("stream_state.json")`, the on_connect clear-logs loop) — those rely on
the process cwd and silently write to the wrong place once cwd differs.

**Critical cross-process gotcha:** `.reload_signal` path MUST match between the
dashboard writer (`app.py signal_reload()`) and the bot reader
(`minecraft_main.py RELOAD_SIGNAL_FILE`). Both must point at
`os.path.join(DATA_DIR, ".reload_signal")` or hot-reload silently breaks.

## Verification harness (reuse for any path refactor)

Before deploying a path change, validate the migration in an **isolated temp dir
simulating frozen mode** — do NOT test against the real `release/`:

1. `tempfile.mkdtemp()`, create fake legacy files + dirs + a fake
   `TikTokMCIntegrator.exe`.
2. Set `sys.frozen = True; sys.executable = <tmp>/TikTokMCIntegrator.exe`, then
   `import paths` (triggers migration).
3. Assert each file/dir landed in its expected subdir, and that build artifacts +
   exe + `.reload_signal` stayed at root.
4. `shutil.rmtree(tmp)`.

**Path gotcha:** the project `python.exe` can't read a `/tmp/...` script path
(`can't open file 'D:\tmp\...'`). Copy the test into the project dir (D: drive,
Windows-visible), run it, then `rm`. Same reason the rename smoke-test failed with
a cp1252 `UnicodeDecodeError` — that's the Windows-Python codec, not a file
problem; read UTF-8 files with `encoding="utf-8"` or just use `py_compile`.
