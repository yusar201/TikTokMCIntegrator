# Dashboard overlay preview resource gating

Use this when the native WebView2 dashboard consumes significant memory/CPU after the Overlays panel has been opened.

## Root cause pattern

Hiding the Overlays panel does not stop an iframe. If its `src` remains an overlay URL, every preview keeps its own JavaScript, polling, canvas/video animation, timers, and DOM alive. Ten hidden previews can therefore behave like ten active browser sources.

## Correct lifecycle

Treat each dashboard preview as an explicitly managed resource:

1. Default every preview iframe to `about:blank`.
2. Add a per-overlay **Live preview** toggle; default it off.
3. Load an overlay URL only when both are true:
   - its Live preview toggle is enabled;
   - the Overlays panel is currently active.
4. When leaving the panel, immediately set loaded preview iframes back to `about:blank`.
5. Remember toggle choices locally, but restore the iframe only after the panel becomes active again.
6. Keep Copy URL behavior independent of preview loading.
7. Never change standalone OBS Browser Sources; they run in separate browser contexts and must remain live.

A reusable manager module is preferable to one-off handlers in `static/script.js`. It should expose load, unload, suspend-all, restore-enabled, and toggle operations so lifecycle tests can drive it without the whole dashboard.

## Polling audit

Preview gating removes the largest hidden cost, but also audit dashboard-wide high-frequency polling. Relax non-critical intervals when sub-second updates add no visible value; the active-streak dashboard poll was safely changed from 300 ms to 1000 ms.

Do not claim that disabling previews makes WebView2 memory zero. Chromium/WebView2 retains a baseline main-page renderer, GPU process, network/storage utilities, and caches. The goal is to remove overlay-specific hidden work.

## Regression tests

Test the manager contract:

- initial state: every iframe is `about:blank`;
- enable one while panel active: only that iframe loads;
- disable it: it unloads;
- leave panel: all loaded previews unload;
- return: only locally enabled previews reload;
- copy URL remains available while preview is disabled.

Also run `node --check` on changed JavaScript.

## Real browser verification

Use the actual dashboard, not only DOM unit tests:

1. Open dashboard and inspect all preview iframe `src` values before visiting Overlays.
2. Enter Overlays: confirm all remain blank by default.
3. Enable one preview: confirm exactly one iframe loads and updates.
4. Navigate to another dashboard panel: confirm it returns to `about:blank`.
5. Return to Overlays: confirm only the enabled preview restores.
6. Check the browser console for failed polls or lifecycle exceptions.

After verification, stop any temporary Flask server and confirm the alternate test port is closed.

## Deployment

This is normally frontend-only and can ship with `./deploy.sh --fast`, provided only templates/static files changed. Verify both `release/{templates,static}` and `release/_internal/{templates,static}` match the source deployment.
