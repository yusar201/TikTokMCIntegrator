# Add-on overlay live updates + mock visual verification

Two techniques proven 2026-08-10 while restyling the Survival Rush objective-rush overlay
(`addons/survival_rush/overlays/objective-rush.html`) into a Minecraft advancement panel —
deployed and visually verified LIVE with the exe running, mid-stream-safe, zero restarts.

## 1. Add-on overlays hot-deploy while the exe is running

Core overlays (`templates/overlay.html`) are bundled into the exe and need rebuild + restart.
**Add-on overlays are different:**

- `routes/addons.py` → `addon_overlay()` serves via `send_file(addon_loader.resolve_overlay_file(...))`
  — the file is read from disk on EVERY request, never cached in memory or bundled into `_internal`.
- `resolve_overlay_file()` resolves against `paths.ADDONS_DIR` = `<BASE_DIR>/addons/`, which in a
  frozen exe is `release/addons/` (also mirrored to `release/_internal/addons/` by deploy.sh).
- The running exe holds NO open handles on add-on HTML files (unlike `_internal/*.pyd`), so a plain
  `cp` overwrite succeeds while the process runs. Verified live with bot PID 9352 running.

**Live-copy recipe (mid-stream safe):**

```bash
cd D:\Ikhito\Code\TikTokMCIntegrator
SRC="addons/<addon_id>/overlays/<overlay>.html"
cp "$SRC" "release/addons/<addon_id>/overlays/<overlay>.html"
cp "$SRC" "release/_internal/addons/<addon_id>/overlays/<overlay>.html"
md5sum "$SRC" "release/addons/<addon_id>/overlays/<overlay>.html" "release/_internal/addons/<addon_id>/overlays/<overlay>.html"
```

**Prove the RUNNING exe serves it** (don't trust the cp banner):

```bash
# find the exe's port from PowerShell
PORTS=$(powershell.exe -Command 'Get-NetTCPConnection -State Listen -OwningProcess <pid> | Select -Exp LocalPort' | tr -d '\r' | sort -u)
curl -s -o /tmp/live.html "http://localhost:<port>/overlay/addon/<addon_id>/<overlay_id>"
md5sum /tmp/live.html "$SRC"   # must match
# plus content greps: new marker strings present, forbidden ones absent (e.g. no requestAnimationFrame)
```

Rules:
- Add-on-only file change + exe running → use this live copy. It's the ONLY deploy safe mid-stream.
- Exe closed → `./deploy.sh --fast` (~1s) also merges bundled add-ons — fine then.
- Never `rm -rf` anything under `release/_internal/` while the exe runs (file-lock I/O errors).
- OBS picks the change up on the overlay's next poll cycle / refresh — no OBS source edit needed.
- Add-on overlays have no `overlay_demo.html` twin — only the source file plus the two release copies need md5-sync.

## 2. Visual verification WITHOUT a server: mock-fetch + headless screenshot

The Flask test_client check only proves the route returns 200 — it can't see pixels. To actually
SEE the overlay (fonts, borders, alignment, colors) without starting the app or a TikTok session:

1. Build a mock HTML from the real overlay source:
   - read the overlay file;
   - inject a mock that overrides `fetch` with a Promise resolving to a **live-shaped state payload**
     (copy the real fields from `runtime/api.py` / the addon's state endpoint), and force any
     `display:none` card to `display:block` so it renders in the shot:

```js
var MOCK = {state:{status:"active",wins:4,win_target:20,strikes:1, /* ...all real fields... */ }};
// ok:true is REQUIRED — overlays gate on if(!r.ok) throw. A bare {json:...} stub makes the
// render silently never run: blank screenshot, NO console error, DOM shows the card
// without .show. Three blank renders were burned on this before the cause was found.
fetch = function(){ return Promise.resolve({ok:true, json:function(){return Promise.resolve(MOCK);}}); };
```

   - Insert the mock immediately before the overlay's `poll()`/init code. Write the result to
     `/tmp/<overlay>_mock.html`.
2. Open it with the browser tool (`browser_navigate` to `file:///tmp/...`), then inspect with
   `browser_vision` / `vision_analyze` asking specific layout questions (border style, icon
   alignment, progress bar fill, text clipping, font fallback).
3. Iterate on CSS and re-screenshot until the design matches the reference (e.g. Minecraft
   advancement toast: dark #202020 panel, layered beveled gray border, pixel font).

**Keep the overlay's real show-gate — do NOT force `display:block` on hidden cards.** If the
mock renders blank, that is a real signal (render never ran or errored), not mock noise.
Two more blank-render traps proven 2026-09-05:
- **`document.fonts.ready.then(poll)` can stall forever under `file://`** when the bundled
  font (`font-display:block`, absolute `/addon-assets/...` URL) cannot resolve — the poll never
  starts and nothing renders. In file:// mocks, point `@font-face` at an absolute `file://`
  copy of the .otf and call `poll()` directly instead of awaiting fonts.ready. (Over http the
  font resolves fine — this is a file:// mock-only trap, not an overlay bug.)
- **Overlay-JS vs mock-bug triage:** append a probe `<script>` that calls
  `render({state:{...}})` directly and sets `document.title='RENDERED:'+counter.className+' '+value.textContent`,
  then `--dump-dom` and read the title. Direct-render works + fetch-mock blank = mock bug
  (missing `ok:true`, wrong payload shape). Direct-render fails too = overlay JS broken —
  e.g. a surgical deletion that removed a helper function and took its `var` declarations
  with it (ReferenceError kills render). After any deletion edit, sweep for
  referenced-but-undeclared variables.
- **Geometry regression proof:** when a change must NOT alter card size, render the mock at
  ≥2 config values and compare the card's DARK-pixel bbox (low-saturation dark pixels), not
  the alpha bbox — headless Chrome screenshots carry an opaque white canvas background
  outside the card, so the alpha bbox always reports the full window. Same bbox + identical
  frame-ring hash across configs = geometry stable.

Notes:
- Keep the mock's field names exactly as the real endpoint returns them — a wrong field makes the
  render silently fall back to placeholders and hides real layout bugs.
- This does not verify the live fetch/parse path; the 81 frontend contract tests + the live curl
  md5 check (section 1) cover that.
- Google Fonts (`Pixelify Sans`, Minecraftia woff2) load fine from `file://`; verify the font URL
  is live before shipping (dead font = invisible/wrong text on stream).

## 3. Contract tests before touching the overlay

`tests/test_survival_rush_frontend_routes.py` (81 tests) enforces hard overlay contracts: no
`requestAnimationFrame`, no infinite CSS animations, ≤420px width, Pixelify Sans, `esc()` escaping
of all injected strings, exact state field names, required status strings. Run
`python -m pytest tests/test_survival_rush_frontend_routes.py -x -q` first and keep every asserted
string/behavior intact during any restyle. A restyle that breaks these = stream-visible regression.

Pitfall found during the 2026-08-10 restyle: don't double-escape — build name HTML as
`(x.definition ? esc(x.definition.name || x.definition.id || 'Objective') : 'Objective')`,
NOT `esc(x.definition ? esc(...) : ...)` (esc of an already-escaped string corrupts entities).

## 4. Headless-Chrome verification when the browser tool has no Chrome (proven 2026-09-05)

If `browser_exec` fails with `chrome-not-running`, don't stall: render the mock with the Windows Chrome binary directly — no server, no port:

```bash
# file:// needs a Windows-side path: copy the mock to C:\Users\<user>\ first
"C:\Program Files/Google/Chrome/Application/chrome.exe" --headless=new --disable-gpu \
  --window-size=460,300 --screenshot="C:\\Users\\yusar\\or_mock.png" "file:///C:/Users/yusar/or_mock.html"
# DOM verification:
"C:\Program Files/Google/Chrome/Application/chrome.exe" --headless=new --disable-gpu \
  --dump-dom "file:///C:/Users/yusar/or_mock.html" > /tmp/or_dom.html
```

- **Pixel assertions without eyes (Windows Python + Pillow):** Counter the PNG's colors and assert fractions — dark panel (low-saturation RGB 20–48), yellow title pixels, green progress fills, red strike numbers, and the *absence* of orange pause-pill pixels. Enough to prove the card drew; deliver the PNGs to Khito as MEDIA previews (he reviews visual work before sign-off).
- **`--dump-dom` includes inline `<script>` source.** Strings existing only in the fetch-mock payload (e.g. `dark_forest`, `waiting`) appear in the dump even when nothing rendered them. Strip scripts before asserting: `re.sub(r'<script>.*?</script>', '', dom, flags=re.S)`, then assert against the remaining markup. Otherwise you chase false FAILs.
- Render the `active` AND `paused` mocks. After the 2026-09-05 overlay simplification both produce identical pixels (no pause badge) — identical PNG size is expected; use DOM assertions to differentiate states.
- Deliberately keep ALL removed/optional state fields in the mock payload (`world_mismatch`, `world_context`, `progression_tier`, `director_diagnostics`) so a pass proves the render ignores them, not that they were absent from the data.
- Copy keeper PNGs into the repo backup dir, then delete Windows-side temp files (mock HTML + PNGs in `C:\Users\<user>\`).
- Shell gotcha: `pytest -q | tail -5` reports tail's exit code (0) and can mask a red suite — run pytest unpiped and read the summary line.

## 5. Proving the whole chain: live exe + mock helper bridge (proven 2026-09-05)

The file:// mock (§2) overrides `fetch` — it can pass every visual check while the overlay's real fetch URL 404s in production, and the live overlay hides itself forever (this shipped: frozen-hands/keep-inventory fetched a dash-id proxy URL that never existed). When a change touches WHAT an overlay fetches (proxy endpoint, addon id, payload field names), verify the full OBS chain:

1. **Mock helper bridge** — ~30-line `http.server` on the helper port (5943) returning a live-shaped snapshot (`/ping`, `/objective/snapshot`, `/objective/capabilities`); add per-path request logging (`override log_message` → append to a file) so you can prove the app actually hit the bridge vs. failed client-side.
2. **Real exe against the mock** — `Start-Process` the release exe; verify `/health`, then probe the exact endpoint the overlay polls (`/api/addons/<id>/proxy/status`). Diagnosis order that worked: probe the helper port directly first (distinguishes bridge-down from route-wrong) → probe the app's proxy URL under BOTH id spellings; a 404 with body `{"error":"Add-on not found"}` means wrong addon id (dash vs underscore trap), not a bridge problem.
3. **Render the REAL OBS URLs** — headless Chrome with `--virtual-time-budget=4000` (so the 200 ms poll cycle actually lands) against `http://127.0.0.1:5000/overlay/addon/survival_rush/<overlay_id>`; assert via `--dump-dom` (scripts stripped) + pixel fractions, never screenshot-file-size alone. Live DOM proof beats mock proof: it exercises addon_loader routing, the proxy, and the overlay's error handling in one shot.
4. **Cleanup is part of the proof** — Stop-Process the exe + python mock, verify ports 5000/5943 show zero listeners, delete Windows-side temp files. A mock left listening on 5943 poisons the next real Minecraft session.

