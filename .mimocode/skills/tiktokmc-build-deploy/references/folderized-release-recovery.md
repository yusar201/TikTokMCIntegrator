# Folderized release recovery: loading stuck + root active_profile.txt

## Symptom
- App/native window stays on the loading/splash screen.
- `release/active_profile.txt` appears at release root, or `release/profiles/` gets created there.
- Dashboard APIs may be missing or stale after a bad model/tool edit.

## Root cause pattern
A source file (usually `app.py`) was reverted to the pre-folderized layout or hand-edited with old path assumptions:

```python
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else ...
CONFIG_FILE = os.path.join(BASE_DIR, "config.yml")
PROFILES_DIR = os.path.join(BASE_DIR, "profiles")
ACTIVE_PROFILE_FILE = os.path.join(BASE_DIR, "active_profile.txt")
init_stats_blueprint(BASE_DIR)
```

This breaks the folderized release contract:

```text
release/config/config.yml
release/config/profiles/*.yml
release/config/active_profile.txt
release/data/*.json
release/logs/*.log
release/assets/*
```

It can also break the native window if `/health` is missing: `main.py` waits for `/health` before swapping from splash to dashboard.

## Correct recovery steps
1. Patch `app.py` back to the folderized path helpers:

```python
import paths
BASE_DIR = paths.BASE_DIR
init_stats_blueprint(paths.DATA_DIR)
CONFIG_FILE = paths.config("config.yml")
PROFILES_DIR = os.path.join(paths.CONFIG_DIR, "profiles")
ACTIVE_PROFILE_FILE = paths.config("active_profile.txt")
```

2. Ensure native readiness route exists:

```python
@app.route("/health")
def health():
    return jsonify({"status": "ok"})
```

3. Replace old root path writes in `app.py`:

| Old pattern | Correct helper |
|---|---|
| `os.path.join(BASE_DIR, "viewer_stats.json")` | `paths.data("viewer_stats.json")` |
| `os.path.join(BASE_DIR, "available_gifts.json")` | `paths.data("available_gifts.json")` |
| `os.path.join(BASE_DIR, "active_streaks.json")` | `paths.data("active_streaks.json")` |
| `os.path.join(BASE_DIR, "sim_console.log")` | `paths.logs("sim_console.log")` |
| `os.path.join(BASE_DIR, "tts_debug.log")` | `paths.logs("tts_debug.log")` |
| `os.path.join(BASE_DIR, "gift_assets")` | `paths.assets("gift_assets")` |
| `os.path.join(BASE_DIR, "sounds")` | `paths.assets("sounds")` |
| `os.path.join(BASE_DIR, "tts")` | `paths.assets("tts")` |
| `os.path.join(BASE_DIR, "reports")` | `paths.assets("reports")` |

4. Clean only misplaced duplicate root artifacts after confirming config copies exist:

```bash
printf 'root active: '; [ -f release/active_profile.txt ] && cat release/active_profile.txt || echo '<none>'
printf 'config active: '; [ -f release/config/active_profile.txt ] && cat release/config/active_profile.txt || echo '<none>'
find release/profiles -maxdepth 1 -type f -printf '%f\n' 2>/dev/null || true
find release/config/profiles -maxdepth 1 -type f -printf '%f\n' 2>/dev/null || true

rm -f release/active_profile.txt
rmdir release/profiles 2>/dev/null || true
```

Do **not** delete `release/config/`, `release/data/`, `release/logs/`, or `release/assets/`.

5. Smoke test before deploy:

```bash
python3 -m py_compile app.py main.py minecraft_main.py routes/stats.py paths.py
python3 - <<'PY'
import app
c = app.app.test_client()
for path in ['/', '/health', '/api/config', '/api/stats/viewers', '/api/console/logs']:
    r = c.get(path)
    print(path, r.status_code, r.content_type)
PY
```

6. Deploy via `./deploy.sh` only, then verify root cleanliness:

```bash
./deploy.sh
find release -maxdepth 1 -type f -printf '%f\n' | sort
# Expected: TikTokMCIntegrator.exe only
```
