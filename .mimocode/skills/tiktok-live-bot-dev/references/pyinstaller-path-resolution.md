# PyInstaller Path Resolution for TikTokMCIntegrator

## The Problem

When TikTokMCIntegrator is packaged with PyInstaller (`build.bat`), path resolution breaks:

| Expression | Dev Mode | Frozen Exe |
|-----------|----------|-----------|
| `os.path.abspath(__file__)` | `D:\Ikhito\Code\TikTokMCIntegrator\app.py` | `C:\...\dist\TikTokMCIntegrator\_internal\app.pyc` |
| `sys.executable` | `C:\Python313\python.exe` | `D:\Ikhito\Code\TikTokMCIntegrator\dist\TikTokMCIntegrator\TikTokMCIntegrator.exe` |

In frozen mode, `__file__` resolves to `_internal/` (where PyInstaller extracts bundled modules), while `sys.executable` resolves to the actual exe location.

## The Pattern

```python
# app.py — module-level BASE_DIR (CORRECT for both modes)
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) \
           else os.path.dirname(os.path.abspath(__file__))
```

## Bug: Function-Level Shadowing

The `generate_report()` function had this:
```python
def generate_report():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # ❌ SHADOWS module-level
    reports_dir = os.path.join(BASE_DIR, "reports")
    # → writes to dist/_internal/reports/ instead of project root
```

**Fix:** Remove the local `BASE_DIR` declaration. Use the module-level one.

```python
def generate_report():
    # No local BASE_DIR — uses module-level one
    reports_dir = os.path.join(BASE_DIR, "reports")
    # → writes to dist/TikTokMCIntegrator/reports/ (correct)
```

## Gotcha: When This Surfaces

- Only manifests after `build.bat` → run the exe
- Works perfectly in dev mode (`python app.py`)
- Report files, log files, config files all end up in `_internal/` instead of next to the exe
- User sees "report not generated" but the file exists in the wrong location

## Debugging

```bash
# Check if report exists somewhere in dist/
find dist/ -name "*.txt" -path "*/reports/*"
# If found in _internal/reports/, it's the __file__ shadowing bug
```

## Cross-Process Test Gotcha (separate-process path mismatch)

When verifying cross-process file bridges (e.g. testing that the bot's `song_feedback.json` reaches Flask), your test script's working directory may differ from where the exe writes:

| Test environment | Path to use |
|------------------|-------------|
| Separate Python script | `D:\Ikhito\Code\TikTokMCIntegrator\release\song_feedback.json` |
| Windows Python (or cmd) | `D:\Ikhito\Code\TikTokMCIntegrator\release\song_feedback.json` |
| Project root (dev mode) | `D:\Ikhito\Code\TikTokMCIntegrator\song_feedback.json` |

If you write to the wrong path, the exe won't see your test data and you'll think the bridge is broken when it actually works.

**Tip:** use `os.getcwd()` in your test script to confirm which directory it sees, then write to `release/` (where the frozen exe lives) not project root.

## Rules

1. **Never redeclare `BASE_DIR` inside functions** — use the module-level one
2. **When adding new file I/O to app.py**, always use `BASE_DIR` (not `__file__`)
3. **Test both modes**: `python app.py` AND the packaged exe after `build.bat`
