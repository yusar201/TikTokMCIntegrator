# Top Gift layout variants — dashboard-switchable card arrangement (verified 2026-08-19)

Khito asked for 3 arrangements of the Top Gift card switchable from the dashboard WITHOUT
removing/changing OBS sources: **left** (icon left / name right — the pre-existing default),
**center** (icon centered / name below), **right** (icon right / name left). This is the
"appearance choice lives in the dashboard, not OBS" doctrine (same as the topgifter
show/hide toggles), but for *layout* instead of show/hide flags.

## Pattern: config file + fold into existing poll + body[data-*] CSS

Use this when ONE dashboard switch must affect every live source of that overlay without
touching OBS URLs. (Contrast with the URL-param `?skin=` pattern, which is per-source and
backend-free.) Steps:

1. **State file** `data/topgift_layout.json` = `{"layout": "left", "updated_at": "..."}`.
   Valid values enforced server-side: `{left, center, right}`; anything else falls back to
   `left`. Constants are duplicated in `routes/stats.py` (GET) and `app.py` (POST) — same
   split as coin goal / gift goal.
2. **GET** `@stats_bp.route("/topgift/layout")` in `routes/stats.py` with strict no-store
   headers (OBS/WebView2 cache otherwise).
3. **POST** `@app.route("/api/topgift/layout", methods=["POST"])` in `app.py` — note this
   lives at `/api/topgift/layout` (app-level), NOT under the stats blueprint prefix.
4. **Fold the layout into the existing summary poll** so OBS picks it up with zero extra
   requests: in `get_gift_log()` (`routes/stats.py`), for `summary=topgift` and
   `summary=topshowcase` wrap the result into an object and add `"layout"` + no-store
   headers. **Payload shape change:** topgift summary went from `[{entry}]` (array) to
   `{"topgift": {entry}, "layout": "left"}`; topshowcase dict gained `"layout"`.
   **topstreak summary was intentionally left as a plain array.**
5. **Overlay JS** (`overlay.html`): `handleTopGift(data)` accepts BOTH shapes
   (`Array.isArray(data) ? data : [data.topgift]` for back-compat), validates the layout
   string, and does `document.body.setAttribute('data-tglayout', layout)`.
   `handleTopShowcase()` passes layout through: `handleTopGift({topgift: gift, layout: data.layout})`.
6. **Overlay CSS**: one marked block scoped to `body[data-tglayout="left|center|right"]`
   (begin/end comments, `!important`). Key facts about the live card: the default look comes
   from the Minecraft achievement-toast override (`.tg-card { flex-direction: row }`), and
   animated gifts (`.tg-has-anim`) use an absolutely-positioned 136px icon panel with
   `padding-left:136px`. So the variants are: left = row + panel left; center = column +
   `.tg-has-anim .tg-icon-wrap` back to `position:relative` + symmetric padding; right =
   `row-reverse` + panel `right:0` + `padding-right:136px`. Mirror the block into
   `overlay_demo.html` (simpler version — demo card has no MC override/anim panel).
7. **overlay_demo.html** polls the FULL gift log (`/api/stats/gifts`, no summary), so it gets
   no layout in its data — fetch `/api/stats/topgift/layout` once on load instead.
8. **Dashboard**: Customize buttons (coin-jar style) on BOTH the Top Showcase and Top Gift
   section headers in `templates/index.html` → `topgift-layout-modal` with three visual
   picker cards (`label[data-choice]`, highlighted selection). `static/script.js`:
   `openTopGiftLayoutModal/close/selectLayout/highlightTopGiftLayoutChoice/saveTopGiftLayout`.
   On successful save, refresh BOTH `preview-topgift` and `preview-topshowcase` iframes so
   the switch is visible instantly in the dashboard.

## Verification (no TikTokLive import needed)

`import app` FAILS without the project deps (`ModuleNotFoundError: No module named 'TikTokLive'` —
the full bot deps live in Windows Python). Two-layer check instead:

```bash
cd D:\Ikhito\Code\TikTokMCIntegrator
# 1. Templates compile + markers present (always works):
python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'))
for t in ['overlay.html','overlay_demo.html']:
    env.get_template(t).render(overlay_type='topgift')
print('jinja ok')"
# 2. Routes round-trip via standalone Flask app (no TikTokLive import):
#    register stats_bp with url_prefix='/api/stats', set stats.BASE_DIR to a /tmp fixture
#    dir containing gift_log.json, then test_client GET/POST the endpoints. Assert:
#    layout GET default, summary includes 'layout' + no-store, topstreak still a list,
#    POST center -> GET center -> summary center, invalid value -> 'left'.
```

**Shape-change test trap:** `tests/test_overlay_idle_cost.py` asserts EXACT summary payloads
(`topgift == [entries[2]]`, `topshowcase == {topgift:…, topstreak:…}`). Any intentional
payload-shape change must update those assertions in the same change.

## Data hygiene pitfall

Never seed test fixtures into the repo's `data/` — this session clobbered
`data/gift_log.json` with dummy entries. Runtime state backups live in `release/data/`
(restore with `cp release/data/<file> data/<file>`). Always point `stats.BASE_DIR` at a
`/tmp` fixture dir instead.

## Deploy

Backend files changed (`app.py`, `routes/stats.py`) → `./deploy.sh --full` (PyInstaller
rebuild via Windows Python; blocked while the exe is running). `--fast`/auto only copies
templates/static and would silently ship without the new routes. After deploy, grep
`release/templates/overlay.html` and `release/static/script.js` for the new markers to
confirm. User only needs to restart `release/TikTokMCIntegrator.exe`; OBS picks the layout
up on the next ~3s poll — no source edits.

## Revert

Delete: marked CSS blocks (both templates) + JS layout hooks, the `layout` wrapping in
`get_gift_log()`, GET/POST endpoints + constants (both files), the modal + buttons in
`index.html`, the handlers in `script.js`, and `data/topgift_layout.json`.
