# WebView2 `display:none` Panel Rendering Quirk (2026-06-25)

## Symptom

After switching profiles on the Settings tab, the **Settings fields update** correctly (TikTokUsername, Rcon, etc.), but the **Events and Gifts tabs still show old data** — even though `switchProfile()` calls `loadConfig()`, which fetches `/api/config`, updates `currentConfig`, and calls `renderEventsGrid()` + `populateGifts()`. Creating a blank profile also shows no change on these tabs.

The backend API works correctly — `GET /api/config` returns the right data after a switch. The JS `currentConfig` variable has the right data. The render functions execute without errors.

## Root Cause

The Events and Gifts panels have `display:none` (via CSS class `.panel:not(.active)`). When `renderEventsGrid()` or `populateGifts()` assign `innerHTML` to a `display:none` container, **WebView2 (Edge WebView2, used by pywebview in the frozen EXE) may not trigger a re-layout for the hidden element**. The DOM is updated in memory, but when the user clicks the Events/Gifts tab and `switchPanel()` shows the panel (adding `.active` class), WebView2 doesn't re-paint the content — it shows whatever was there before the hidden `innerHTML` was set.

Settings tab **works** because `populateSettings()` sets `<input>.value` directly — form elements have different rendering hooks that WebView2 updates even when hidden.

This does **not** reproduce in regular Chrome/Edge browsers — only in the embedded WebView2 control inside the PyInstaller EXE. Likely because WebView2's layout engine aggressively optimizes `display:none` subtrees.

## Fix

In `switchPanel()` in `static/script.js`, explicitly re-render the Events and Gifts panels whenever their tab is clicked:

```javascript
function switchPanel(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const panel = document.getElementById('panel-' + name);
  const nav = document.querySelector(`[data-panel="${name}"`);
  if (panel) panel.classList.add('active');
  if (nav) nav.classList.add('active');
  // Re-render dynamic content when switching tabs (WebView2 display:none quirk)
  if (name === 'events') renderEventsGrid();
  if (name === 'gifts') populateGifts();
  if (name === 'overlays') initOverlayPreviews();
  if (name === 'tts') loadTtsConfig();
}
```

The `overlays` and `tts` tabs already had this pattern — they call init/load functions on tab switch. Events and Gifts were missing it.

## Investigation Steps

1. **Confirm the backend works** — test API endpoints directly with curl:
   ```bash
   curl http://localhost:5000/api/profiles/switch -X POST \
     -H "Content-Type: application/json" \
     -d '{"profile":"Survival"}'
   curl http://localhost:5000/api/config | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('Settings',{}).get('TikTokUsername'))"
   ```

2. **Split the bug** — check if it reproduces in a regular browser (Chrome/Edge) vs the EXE. If it works in the browser but not the EXE, it's a WebView2-specific issue.

3. **Check `currentConfig` in the JS console** after switching profiles:
   ```javascript
   JSON.stringify({
     user: currentConfig.Settings?.TikTokUsername,
     events: Object.keys(currentConfig.Events||{}),
     gifts: Object.keys(currentConfig.Gifts||{}).length
   })
   ```

4. **Test re-rendering on tab switch** — call `renderEventsGrid()` and `populateGifts()` manually after clicking the Events/Gifts tab. If that fixes it, apply the same to `switchPanel()`.

## Related Patterns

- Settings tab works because `<input>.value` is updated via form element APIs
- Overlays/TTS already re-render on tab switch (historical fixes for similar issues)
- This does NOT affect the OBS overlay HTML pages (they are independent pages, not tab panels)
- If adding new panels in the future, always add re-render calls in `switchPanel()`
