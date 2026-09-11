# Stream Baseline Performance Regression Audit

Use this when Khito says the streaming setup has become heavier **across recent app additions**, rather than merely slowing during one long stream.

## Establish the time axis first

Do not collapse these into one theory:

- **Within-stream accumulation:** logs, DOM nodes, queues, or leaked timers grow over hours.
- **Cross-release baseline regression:** every newly added overlay/widget adds permanent polling, rendering, or browser-process cost from stream start.

If the user says the latter, audit persistent work introduced by features. Do not blame a current event animation unless its active path is confirmed.

## Measure process trees, not executable names

A native TikTokMCIntegrator desktop window is Python + child `msedgewebview2.exe` processes. The parent EXE may look quiet while a renderer consumes a full CPU core.

1. Sample CPU *deltas* over 10–20 seconds, not Task Manager’s single instant.
2. Aggregate all WebView2 children whose command line identifies `TikTokMCIntegrator.exe`.
3. Separately sample OBS (`obs64.exe` + `obs-browser-page.exe`), Minecraft client, and Mohist server.
4. Re-measure after each restart/deploy. Do not treat a screenshot as causal proof.

## OBS source truth

Scene JSON is inventory, not runtime truth. Use OBS WebSocket's current program scene plus `GetSourceActive` for each Browser Source to determine `videoActive` / `videoShowing`.

Audit every browser source in the program scene, including third-party widgets. A stream can have Tikfinity/SociaBuzz pages alongside TikTokMC overlays; OBS's shared Chromium GPU process combines their cost.

For inactive local overlays, enable OBS's shutdown-when-hidden behavior if they are not needed. Do not assume a hidden source is unloaded from its scene JSON alone.

## Persistent-cost checklist per overlay

For every browser overlay, find and classify:

- polling endpoint and cadence;
- `requestAnimationFrame` loops;
- CSS `animation: ... infinite`, especially animated gradients, filters, `box-shadow`, backdrop blur, and large pseudo-elements;
- DOM rebuilds, image reassignment, counter timers, or layout reads when the fetched state did not change;
- full-history API payloads used only to choose one summary item.

### Proven low-baseline patterns

- **Event-idle canvas:** schedule a frame only while value easing or particle physics is active; clear the scheduler token when idle.
- **Render key dedupe:** compare a stable key of displayed state before DOM/image/counter work.
- **Summary API:** Top Gift / Top Streak should fetch one selected entry, not a growing event log. Cache summary selection on the server until source-file signature changes.
- **Static retained history:** dashboard history may keep tier color/badges, but retained cards must not carry permanent gradient/glow/crown/aura CSS animations after the event has passed.
- **Cache bust after CSS changes:** bump the dashboard stylesheet version when shipping a frontend performance fix, otherwise WebView2 may keep the expensive old CSS.

## Static vs animated gift distinction

A static Top Gift icon does not enter the packed-alpha video compositor. If a report says the top gift was static, do not attribute the spike to the compositor. Verify the actual `asset_url` / video branch first, then inspect the static poll/render and dashboard-history paths.

## OneBlock scope check

Objective Rush's service poller can wake on an interval but should immediately return while the run is inactive. The meaningful OneBlock overhead normally comes from an active OBS overlay polling the helper, not from inactive game logic. Confirm both run state and OBS source state before blaming OneBlock.

## Verification contract

1. Add regression tests for event-idle scheduling, summary endpoints, and stable-state render dedupe.
2. Run the full test suite plus Jinja and JavaScript syntax checks.
3. Deploy through the canonical script and restart the desktop app so its WebView2 loads the new frontend.
4. Confirm live HTML/CSS contains the shipped markers/cache version.
5. Measure app WebView2 CPU deltas again. Only then report a before/after conclusion.

## Session result that motivated this reference

The 2026-07-21 audit found separate causes: a packed-alpha gift compositor, an idle Coin Jar frame loop, Top Gift/Top Streak full-log polling and repeated static rendering, and permanent flashy tier CSS on retained dashboard chat history. The last item alone could make an offline dashboard WebView2 renderer consume roughly a CPU core; changing dashboard history to event-idle static effects eliminated that measured renderer burn after restart.
