# Add-on boolean/status overlay verification

Use this pattern for compact OBS widgets that present a helper-authoritative boolean or small enum.
It was validated on a 360×190 Minecraft-style status card.

## Data and polling contract

- Read the authoritative helper field through the same-origin add-on proxy; never infer gameplay
  state from presentation or prior events.
- Validate the exact type (`typeof data.flag === 'boolean'`) rather than normalizing strings.
- Use a timestamp query plus `cache:'no-store'` for mutable state.
- Prevent overlapping requests with an in-flight guard and schedule the next poll from `.finally()`.
- Missing/invalid fields, non-2xx responses, and fetch failures must all enter the same hidden state.
- Reset the last-rendered state when hiding so recovery repaints correctly.

## Mutually exclusive image/fallback state

Do not let image `load` handlers write `img.style.display='block'`. Inline display overrides
state CSS and can leave both state icons visible once both files have loaded.

Use two independent class dimensions:

1. Widget state: `.state-on` / `.state-off` on the panel.
2. Asset health: `.icon-ok` on a decoded image or `.icon-bad` on its matching fallback.

CSS must require both dimensions, for example:

```css
.panel.state-on #icon-on.icon-ok { display:block }
.panel.state-off #icon-off.icon-ok { display:block }
.panel.state-on #fallback-on.icon-bad { display:flex }
.panel.state-off #fallback-off.icon-bad { display:flex }
```

Derive health from `img.complete && img.naturalWidth > 0`, update classes on both `load` and
`error`, and run the sync once for already-cached images. Add contract tests that ban inline
`.style.display = ...` writes and require state-gated visibility selectors.

## Deterministic real-pixel probe

Serve the **real overlay HTML and real bundled assets** from a tiny local HTTP fixture. Its status
endpoint should switch among `on`, `off`, and `offline` using a small state file. Render with real
Chromium at the manifest's recommended viewport and inject only:

```css
* { transition:none!important; animation:none!important }
```

This removes transition timing from measurements without changing the production artifact.
For each state, record computed styles, DOM geometry, decoded image sizes, font readiness, and a
transparent PNG screenshot.

Required assertions:

- ON/OFF text and exact computed colors match the design tokens.
- Exactly one state icon has non-`none` display.
- Bundled font reports loaded and the expected font family is computed.
- Card rectangle stays inside the viewport; right-aligned cards may end exactly at viewport width.
- ON and OFF screenshots have a non-empty alpha bounding box fully within the canvas.
- Offline screenshot has no alpha bounding box (zero visible pixels), not merely off-color text.

Stop the fixture server, delete scratch files/screenshots, and verify its port is released.

## Deployment proof

For add-on-only changes, use the canonical fast deploy or the documented stream-safe live-copy
path. Hash the source, `release/addons`, and `release/_internal/addons` copies of the manifest,
HTML, and assets. If the app is running, additionally fetch the exact live overlay route and compare
its body/hash. If it is closed, report that live-route verification is deferred until launch; do
not imply an active route was probed.
