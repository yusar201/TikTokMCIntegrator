# WebView2 Cache: Stale Dashboard After EXE Update

## Symptom

User deploys a new EXE (via `deploy.sh`), launches it, and:
- Profile switching doesn't change displayed data (Events, Gifts, Settings)
- Creating a blank profile still shows old content
- The API backend is confirmed working (test via curl/browser)
- The frontend JS is confirmed correct (test via browser console)
- All code files (app.py, script.js, paths.py) are identical between dev and release

## Root Cause

The WebView2 control embedded in the app has its **own browser cache** separate from the user's regular browser. When `deploy.sh` replaces `templates/` and `static/` (including `script.js` and `index.html`), WebView2 does NOT automatically reload these files — it serves the cached versions from its local storage.

This explains why:
- Testing `localhost:5000` in a regular browser works perfectly (regular browser sees fresh files)
- The API endpoints work correctly (server-side, no caching)
- The EXE still shows old data (WebView2 cache is stale)

The user reports "nothing changes" when switching profiles because the **old JS code** is running — it may have an old `switchProfile()` implementation that calls a different endpoint, or may not properly re-render on data change.

## Detection

1. Open the EXE's embedded window
2. Open DevTools in WebView2 (right-click → Inspect or `Ctrl+Shift+I` — may need to enable via registry)
3. Check the Network tab to see if `script.js` is loaded from cache
4. Compare the loaded script.js version string (`?v=22` in `<script src="/static/script.js?v=22">`)

## Fix

### Option A: Bump the cache-busting version string (recommended)

In `templates/index.html`, increment the version parameter:
```html
<script src="/static/script.js?v=23"></script>
```
Each deploy should bump this version. WebView2 sees a new URL → fresh fetch.

### Option B: Clear WebView2 cache programmatically

Add this to `main.py` before `webview.start()`:
```python
# Clear WebView2 cache on every launch to prevent stale JS from old deploys
import webview
try:
    webview.start(private_mode=True)  # private mode = no cache persistence
except:
    pass
```

Or add a more targeted cache-clear route in `routes/` that the JS calls on load.

### Option C: User does a hard refresh

Within the WebView2 window, `Ctrl+F5` or right-click → Reload. This forces a full page refresh from the server, bypassing the cache. *(Least reliable — depends on user remembering to do it.)*

## Prevention

Add a cache-busting mechanism to `deploy.sh`:
```bash
# Bump script.js version in templates/index.html
CURRENT_VER=$(grep -oP 'script\.js\?v=\K\d+' templates/index.html)
NEXT_VER=$((CURRENT_VER + 1))
sed -i "s|script.js?v=${CURRENT_VER}|script.js?v=${NEXT_VER}|g" templates/index.html
```

This ensures every deploy auto-bumps the version, and WebView2 always fetches fresh JS.

## Also Check

If profile switching still doesn't work after cache clearing:
1. **Old EXE still running** — Check Task Manager for zombie `TikTokMCIntegrator.exe` processes
2. **`config/profiles/` directory** — Verify the new profile was actually created (can't switch to a profile that doesn't exist)
3. **`_internal/` mismatch** — If `release/static/` was updated but `release/_internal/static/` is stale, WebView2 may read from `_internal/` depending on how `sys._MEIPASS` resolves. The deploy script should copy to BOTH locations
