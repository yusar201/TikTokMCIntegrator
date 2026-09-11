# PyInstaller Build & Deploy for TikTokMCIntegrator

## Build Process

PyInstaller lives on the project interpreter. Build with:

```bash
cd D:\Ikhito\Code\TikTokMCIntegrator
cmd.exe /c "py -3 -m PyInstaller TikTokMCIntegrator.spec --noconfirm 2>&1"
```

Build takes ~2-5 minutes. Output goes to `dist/TikTokMCIntegrator/`.

## Deploy to Release

**CRITICAL**: Deploy to `release/` ROOT, not a subfolder. The app runs from `release/TikTokMCIntegrator.exe`.

```bash
# Copy exe
cp dist/TikTokMCIntegrator/TikTokMCIntegrator.exe release/

# Copy _internal (use rsync for speed, robocopy as fallback)
rsync -a dist/TikTokMCIntegrator/_internal/ release/_internal/
# OR: cmd.exe /c "robocopy dist\TikTokMCIntegrator\_internal release\_internal /E /NFL /NDL /NJH /NJS /nc /ns /np"

# Copy frontend
cp templates/index.html release/templates/
cp static/script.js release/static/
```

**NEVER**:
- `rm -rf release/` — destroys config, profiles, runtime data
- Deploy to `release/TikTokMCIntegrator/` subfolder — wrong location
- Touch `config.yml`, `profiles/`, or runtime JSON files

## Hidden Imports

When adding new Python modules, add to `TikTokMCIntegrator.spec`:
```python
hiddenimports=['spotipy', 'spotipy.oauth2', 'spotipy.client', 'spotify_handler', 'edge_tts', 'tts_effects'],
```

Without this, PyInstaller won't bundle the module and imports will fail silently at runtime.

## Verification

After deploy:
```bash
# Check exe date (should be current)
ls -la release/TikTokMCIntegrator.exe

# Verify frontend changes
grep -c "expected_string" release/templates/index.html
grep -c "expected_function" release/static/script.js
```

## Common Issues

1. **Permission denied on exe copy**: App is still running. Close it first.
2. **Build timeout**: Use `background=true` with `notify_on_complete=true` for long builds.
3. **Missing module at runtime**: Add to `hiddenimports` in .spec file and rebuild.
4. **robocopy empty output**: Exit code 0-7 means success, not failure.
