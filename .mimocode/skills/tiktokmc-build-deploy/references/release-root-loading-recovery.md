# Release-root + Native Loading Recovery

Use this when TikTokMCIntegrator launches to a stuck loading/splash screen, the dashboard APIs return nothing, or runtime files appear in `release/` root.

## Root cause pattern

A rolled-back or stale `app.py` can bypass the folderized `paths.py` layout and use `BASE_DIR = release/` directly. Symptoms:

- Native pywebview splash stays loading because `main.py` polls `GET /health`, but stale `app.py` has no `/health` route.
- `release/active_profile.txt` appears at root instead of `release/config/active_profile.txt`.
- `release/profiles/` appears at root instead of `release/config/profiles/`.
- Runtime JSON/log/assets may scatter into release root instead of `data/`, `logs/`, `assets/`.

## Investigation checklist

Run these before fixing:

```bash
cd D:\Ikhito\Code\TikTokMCIntegrator
python3 -m py_compile app.py main.py minecraft_main.py routes/stats.py paths.py
find release -maxdepth 1 -type f -printf '%f\n' | sort
find release -maxdepth 1 -type d -printf '%f\n' | sort
```

Expected release root files: only `TikTokMCIntegrator.exe` (plus dirs: `_internal`, `templates`, `static`, `config`, `data`, `logs`, `assets`). `active_profile.txt`, `*.json`, `*.log`, `profiles`, `sounds`, `reports`, `tts`, `gift_assets` at root are layout regressions.

Smoke test Flask before deploy:

```bash
python3 - <<'PY'
import app
c = app.app.test_client()
for p in ['/', '/health', '/api/config', '/api/stats/viewers', '/api/console/logs']:
    r = c.get(p)
    print(p, r.status_code, r.content_type)
PY
node --check static/script.js
```

## Fix pattern

Patch stale `app.py` to use `paths.py`:

```python
import paths
BASE_DIR = paths.BASE_DIR
init_stats_blueprint(paths.DATA_DIR)
CONFIG_FILE = paths.config("config.yml")
PROFILES_DIR = os.path.join(paths.CONFIG_DIR, "profiles")
ACTIVE_PROFILE_FILE = paths.config("active_profile.txt")
```

Add native launcher readiness route:

```python
@app.route("/health")
def health():
    return jsonify({"status": "ok"})
```

Replace old runtime paths:

| Old pattern | New helper |
|---|---|
| `os.path.join(BASE_DIR, "config.yml")` | `paths.config("config.yml")` |
| `os.path.join(BASE_DIR, "active_profile.txt")` | `paths.config("active_profile.txt")` |
| `os.path.join(BASE_DIR, "viewer_stats.json")` and runtime JSON | `paths.data("...")` |
| `os.path.join(BASE_DIR, "sim_console.log")`, `tts_debug.log` | `paths.logs("...")` |
| `os.path.join(BASE_DIR, "sounds")`, `reports`, `tts`, `gift_assets` | `paths.assets("...")` |

After patching, remove only proven-misplaced duplicates:

```bash
# only when config/active_profile.txt exists and root active_profile.txt is duplicate
rm -f release/active_profile.txt
# only when empty or migrated; never delete populated profiles without preserving
rmdir release/profiles 2>/dev/null || true
rmdir release/release 2>/dev/null || true
```

Then deploy through protocol:

```bash
powershell.exe -Command 'Get-Process | Where-Object { $_.Name -like "*TikTokMCIntegrator*" -or $_.Name -eq "python" } | Select-Object Name, Id'
./deploy.sh
stat -c '%y' dist/TikTokMCIntegrator/TikTokMCIntegrator.exe release/TikTokMCIntegrator.exe
test ! -d release/TikTokMCIntegrator && echo NO_NESTED
find release -maxdepth 1 -type f -printf '%f\n' | sort
```

## User-facing behavior

Khito is sensitive to app-breaking model/tool mistakes. When this happens, investigate/fix directly, verify with route smoke tests and release-root scan, deploy, and report concise facts. No excuses, no asking him to run commands.