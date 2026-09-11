---
name: tiktokmc-overlay-system
description: "TikTokMCIntegrator OBS overlay system — structure of templates/overlay.html (single Jinja template, overlay_type branch), the 11 overlay types, preview=true dashboard mode, restyling/theming overlays reversibly, scroll-in-preview-only, and verifying overlays via Flask test_client without a running server. Use for any overlay visual redesign, new overlay type, or preview/dashboard overlay change."
trigger: "TikTokMCIntegrator overlay, overlay.html, OBS overlay, overlay redesign, restyle overlay, top gift overlay, top streak overlay, gift feed overlay, chat feed overlay, overlay preview, overlay theme, live overlay setting, stale overlay label, overlay not updating, WebView2 cache, OBS cache, coin goal jar, minecraft overlay, overlay font, standalone OBS overlay, McPY overlay, diamondCounter.html, winOverlay.html, slot text overlay"
related_skills: ["media-progress-overlay", "tiktokmc-build-deploy", "spotify-song-queue-architecture"]
---

# TikTokMCIntegrator Overlay System

All OBS browser-source overlays are served from **one Jinja template**: `templates/overlay.html`,
routed by `@app.route("/overlay/<overlay_type>")` in `app.py`. CSS lives partly inline in
`overlay.html`'s `<style>` block and partly in `static/style.css` (the gift-feed entry base
styles + the dashboard `.overlay-preview-frame` / `.overlay-iframe` rules).

## Core overlay types

overlay_type includes chat, gifts, follows, superfan, topgift, topstreak, **topshowcase**, topgifter, song, coingoal, and giftgoal. `topshowcase` is the production combined Top Gift + Top Streak source; standalone topgift/topstreak remain supported for rollback. Treat this list as live architecture and verify both route allowlists before relying on an exact count.
The template branches {% if overlay_type == 'superfan' %} … {% elif 'topgift' %} … {% elif 'topgifter' %} … {% elif 'giftgoal' %} … {% else %}
where the {% else %} is the generic feed (chat/gifts/follows) using

**Add-on overlays are separate from this core list.** After Add-on System v1, game-specific overlays such as OneBlock must live under `addons/<addon_id>/overlays/` and route via `/overlay/addon/<addon_id>/<overlay_id>`, not the core `/overlay/<type>` tab/template. If a prototype game overlay still appears as a core dashboard overlay card, remove that card and its `initOverlayPreviews()` entry after moving it to an add-on.

- **Feeds** (chat, gifts, follows): bottom-anchored, scroll-up, justify-content:flex-end,
  overflow:hidden, fixed max-height:100vh. JS in overlay.html (renderEntries,
  renderGiftEntry, renderChatEntry, renderFollowEntry) appends entries; MAX_GIFTS=999999
  (gifts never trimmed), MAX_CHAT=8, MAX_FOLLOWS=5.
  - **Chat pixel tier restyles:** preserve the existing gifter-level thresholds (`20/25/30/35`) but make each tier visually distinct inside the pixel theme: default stone slab, T1 iron/cyan, T2 amethyst, T3 gold relic, T4 nether/legendary. Chat should be wider than gifts (~400–410px) because messages wrap; keep text opaque/bright with dark pixel shadow, use square avatar frames, classed `.chat-tier-chip` + `.chat-tag-chip`, and avoid random sparkle spam that makes messages hard to read. **Do not use repeating/checker/diagonal texture fills on chat cards** — Khito said it looks like metal and hurts the style. Keep the card backgrounds mostly flat; let tiers affect border, side bar, chip color, and a small controlled glow only. Normalize `.chat-tier-chip` sizing (`height:18px`, `width/min-width:64px`) so GOLD/IRON/LEGEND/AMETHYST do not look mismatched. Dashboard chat overlay category pills should be multi-select subset semantics: when all pills are active it means show everything; first click starts a subset with only that category; additional clicks add/remove categories (e.g. Follower + Newbie); removing the last selected category restores all. See `references/chat-pixel-tier-restyle.md` for the full recipe and verification commands.
  - **Follow feed:** Current follow feed should match the gift feed's Minecraft achievement-toast proportions: **360px centered cards, ~64px min-height, 10px/12px padding, compact line-height (~1.25)**, grey pixel card, cyan left bar, yellow follower name, cyan @unique_id. Do **not** add a right-side FOLLOW badge — it wastes width and makes the card feel unlike the gift feed. Do **not** show a fallback person icon — if avatar_url is missing or fails, remove/hide the avatar block entirely. If an avatar is present, use a 44×44 pixel frame (`box-sizing:border-box`, `padding:4px`, black border + inset bevel, `overflow:hidden`) and force the child image square (`width/height/min-width/max-width:100%`, `flex:0 0 100%`, `aspect-ratio:1/1`, `object-fit:contain`, `border-radius:0`, `image-rendering:pixelated`).
- **Cards** (topgift .tg-card, topstreak .ts-card, superfan, song): single popup card,
  display:none until data arrives. Centered via .tg-wrap/.ts-wrap fixed positioning.
- **Rotating leaderboard** (topgifter `.lb-wrap`, 2026-08-05 — replaced the old `.podium-wrap` triple podium): ONE overlay rotates every ~5s between Top Gifters (🪙 coins) and Top Likers (❤️ likes); top-10 lists from `/api/stats/topgifter` (returns `{gifters, likers}`), reset each fresh live. Backed by `stream_ranking.py` (per-stream JSON stores + throttled flush + manual-reset token). **Full recipe in `references/topgifter-liker-leaderboard.md`.**
  - **Avatar parity pitfall (2026-08-15):** the liker board MUST resolve avatars through the SAME `resolve_avatar_url(user, nick, uid)` path the gifter/chat/follow handlers use. `on_like` was feeding `getattr(user, "avatar", "")` — a field TikTokLive's like-event payload does NOT populate — so every liker row had an empty avatar and fell back to initials even when a usable avatar existed. `resolve_avatar_url` extracts `avatar_thumb`/`avatarThumb`/etc., seeds the local cache, and falls back to last-known. Also short-circuit the `_cache_avatar_url` write when the URL is unchanged so bursty like events don't rewrite `avatar_cache.json` on every tap.
  - **Appearance toggles live in the dashboard, NOT in OBS (2026-08-15).** When a streamer wants a show/hide switch (e.g. coin/like amounts), the checkbox must render in `templates/index.html` (the dashboard card), POST to a settings endpoint, and the overlay reads the flag from its existing poll payload — never render toggle UI inside `overlay.html` (it would appear on-stream). Fold the flags into `/api/stats/topgifter` (`show_gift_amounts`/`show_like_amounts`) so the overlay applies them on its normal poll with no extra fetch. Include the flags in the render hash so a toggle repaints even when board data is unchanged.
  - **Gift Goal** (giftgoal .gg-wrap): compact corner card — gift media + progress text "0/100"
    below it + customizable header. Bot increments via
    `add_to_gift_goal(gift_id, repeat_count, asset_url="")` — matches incoming gift_id against configured
    goal gift_id, locked read-add-write on `gift_goal.json`. Dashboard modal loads the gift
    picker from `/api/gifts/available` (a DIFFERENT endpoint than the overlay's own
    `/api/stats/giftgoal` poll). Use an icon picker with search + A-Z/Z-A/coin sorting,
    not a bland native `<select>`. **Animation reality:** `/webcast/gift/list/` / `/api/gifts/available`
    exposes `primary_effect_id` / `resource_id` / `has_animation` for high-value gifts, but it does
    **NOT** expose a playable ZIP/MP4 URL. The actual animation still comes from `GiftEvent.asset`
    and the cached `assets/gift_assets/manifest.json`. Gift Goal should read `gift_asset_url` from
    `/api/stats/giftgoal` and render it from page load with the same packed-alpha canvas compositor
    as Top Gift; if the selected gift has not been cached yet, fallback to `gift_icon`. `routes/stats.py`
    should also look up the manifest by `gift_id` on each poll so an async download becomes visible
    without another dashboard save. **Important visual pitfalls:** `.gg-progress` must be
    structurally OUTSIDE `.gg-icon-wrap` or it will not truly sit below the gift icon; and
    small Minecraft text should be pure white with `-webkit-text-fill-color:#fff` and
    NO stroke (`-webkit-text-stroke:0 transparent`) because even a 1px dark stroke makes it
    look grey/dark in OBS. See `references/gift-goal-overlay.md` for the full recipe.
  **Layout pitfall (2026-06-26):** do NOT put `.gg-progress` inside `.gg-icon-wrap`. If the counter is nested in the icon wrapper, CSS `order`/`position:static` still keeps it visually attached to the gift and OBS may show it beside/over the icon. Structure must be:
  `gg-header` → `gg-icon-wrap` (only img + fallback) → `gg-progress` as a sibling after the icon wrapper. Khito explicitly wants the counter below the gift icon, all-white text (no green number), no black/pill text background, Minecraft font (`var(--font-mc)`) with a small dark stroke/text-shadow for readability. Center the overlay horizontally with `left:50%; transform:translateX(-50%)` unless he asks for a corner anchor.
- Data source: fetchData() maps each core type to an /api/stats/<x> endpoint
  (topgift/topstreak both read /api/stats/gifts; topgifter reads /api/stats/topgifter).
  **Do not add external/game-helper calls directly to core `overlay.html`.** Add-on overlays should fetch same-origin from `/api/addons/<addon_id>/proxy/<endpoint>` and let the Flask app talk to helpers such as `http://127.0.0.1:5943`. This avoids CORS pain, keeps OBS pointed only at TikTokMCIntegrator, and puts helper health/auth/config in the Add-ons tab.
- **PITFALL — addon-id namespace trap (2026-09-05, broke frozen-hands + keep-inventory).** An add-on has TWO id namespaces on the Flask side: the game service API registers under the DASH id (`/api/addons/survival-rush/objective-rush/*` via `create_survival_rush_blueprint` in app.py), while the addon proxy/overlay/asset routes use the real UNDERSCORE id (`/api/addons/survival_rush/proxy/<ep>`, `/overlay/addon/survival_rush/<id>`, `/addon-assets/survival_rush/...` via `addon_loader._endpoint_url`). A dash-id proxy fetch returns Flask 404 `{"error":"Add-on not found"}` and the overlay's error handler hides it forever — while sibling overlays that use service routes keep working, so only SOME add-on overlays break and the app looks healthy. Always mirror the exact addon id from `addon.yml` into overlay fetch URLs (proxy and addon-assets alike), and pin the id in contract tests.

## Combining compatible overlays into one OBS source

When two compact cards occupy the same stream region, prefer one real document over two Browser Sources or two iframes. Preserve each card's settled design and add only an outer switch stage. Share one compact API payload/poller, avoid switching to empty states, pause inactive visual loops, verify timing in the browser, then migrate OBS by updating one source in place and disabling—not deleting—the redundant source. Read `references/combined-rotating-overlays.md` for the implementation, verification, and obs-websocket migration recipe.

## preview=true dashboard mode

For dashboard-wide preview resource control, lazy iframe loading, per-overlay Live preview toggles, panel suspension, and WebView2 validation, read `references/dashboard-preview-resource-gating.md`.

The dashboard (`templates/index.html`) embeds each overlay in an `<iframe id="preview-<type>">`.
`updateOverlayUrl(type)` in `static/script.js` builds the URL and appends `&preview=true`.
Inside `overlay.html`, `const isPreview = params.get('preview')==='true'` drives a
`DOMContentLoaded` block that re-centers overlays for preview. **This is the hook for any
preview-only behavior** — OBS sources never carry the param, so changes gated on `isPreview`
do not affect the live overlay.

### Scroll-in-preview pattern (verified 2026-06-10)
To let the streamer scroll back through the full chat/gift feed in the dashboard (e.g.
end-of-stream gift showcase) WITHOUT changing OBS behavior:
- In `overlay.html`'s `if (isPreview)` block, for `TYPE==='chat'||'gifts'`: set the wrap to
  `justifyContent='flex-start'; alignItems='center'; overflowY='auto'; pointerEvents='auto'`
  and the feed to `maxHeight='none'; overflow='visible'`.
- In `static/style.css`, give `#preview-chat, #preview-gifts` a taller height (e.g. 420px).
- OBS (no `preview` param) keeps the fixed bottom-anchored, non-scrolling feed. Verified: live
  overlay unchanged.

**PITFALL — JS inline-style beats CSS, so it controls horizontal alignment (2026-06-10):**
Use `alignItems='center'`, NOT `'stretch'`. The feeds have a fixed width (gifts = 360px). With
`alignItems='stretch'` on a fixed-width child, flex falls back to left-packing → the feed hugs
the LEFT edge of the preview, ignoring any `align-items:center` you set in CSS. The `isPreview`
JS runs at `DOMContentLoaded`, AFTER stylesheet parse, so its inline `el.style.alignItems` wins
the cascade. Symptom the user reports: "the gift feed is still on the left." Fix is the one-word
change `'stretch'` → `'center'` in that JS block — not a CSS edit (CSS can't win against the
inline style). General rule: when a `preview=true` inline-style block governs layout, that block
is the source of truth for centering — edit the JS, not the CSS.

## Selectable skin pattern — keep BOTH designs, let the streamer choose (verified 2026-06-17, song 8-bit skin)

When Khito wants a NEW look for an overlay but does NOT want to lose the current one ("don't
replace the current design, make it so i can choose from a dropdown"), do NOT restyle in place.
Add the new look as an **additive, selectable skin**. Default stays byte-for-byte untouched and is
the fallback. 4 surgical edits, all reversible:

1. **CSS skin block** — append to the END of `static/style.css` (NOT overlay.html's `<style>` for a
   big block) wrapped in begin/end comment markers, scoped to `body[data-skin="<name>"] .selector`
   with `!important`. Reuse the EXISTING markup/IDs — the song card already had album art, title,
   artist, progress + both time labels, and the UP NEXT list, so the 8-bit skin was pure CSS over
   the same DOM (zero markup changes). Check the existing element inventory before adding any HTML.
2. **Font load** — add the webfont `<link>` in overlay.html `<head>` (e.g. Press Start 2P from
   Google Fonts) so the skin font is available. Default skin doesn't reference it, so no impact.
3. **JS skin hook** — in overlay.html's script, right after `const isPreview = ...`, read
   `params.get('skin')` and if set+non-'default' do `document.body.setAttribute('data-skin', skin)`.
   That single attribute flips the whole scoped CSS block on. No skin param = default, untouched.
4. **Dashboard dropdown** — add a `<select id="<type>-skin-select" onchange="updateOverlayUrl('<type>')">`
   inside the overlay section's `.overlay-url-bar` (give it `style="max-width:160px;flex:0 0 auto;"`
   and class `overlay-url-input` to match the bar). Then in `static/script.js` `updateOverlayUrl()`
   add an `else if (type === '<type>')` branch that does
   `params.set('skin', sel.value)` only when value !== 'default'. The live preview iframe + Copy URL
   both pick it up automatically because they're built from the same `params`.

Retro feel: use `animation: … steps(N)` (not smooth cubic-bezier) and `image-rendering: pixelated`
for 8-bit skins; `clip-path: polygon(...)` gives the stepped pixel-rounded corners and
`filter: drop-shadow(Npx Npx 0 #000)` the hard 8-bit shadow (see the Gemini prototype recipe:
6px border + 6px clip corners on the card, 4px on album art, 2px on tag chips).
Revert = delete the marked CSS block + font link + the ~6-line JS hook + the dropdown. Verify with
the Flask test_client check below, hitting both `/overlay/<type>` and `/overlay/<type>?skin=<name>`.

## Reversible restyle / theming pattern (IMPORTANT)

When the user asks to redesign overlays, do NOT rewrite the existing per-overlay CSS blocks.
Instead **append an isolated override block** at the END of `overlay.html`'s `<style>`, wrapped
in clear begin/end comment markers, using high-specificity selectors + `!important`. Benefits:
- Revert = delete the one marked block. No risk to the original styling.
- Original animations/gradients are neutralized inside the override
  (`animation:none !important`, `background:none !important`, `::before/::after { display:none }`).
- Always back up `overlay.html` + `style.css` first (e.g. `.overlay-backups/<ts>/`) so the user
  can ask to revert even after a deploy.

### Custom webfonts (Minecraft, etc.)
- Add `@font-face` at the top of the `<style>` block; expose via a CSS var like `--font-mc`.
- **Verify the CDN URL is live with `curl -sI` before using it** (a dead font = invisible text on
  stream). A known-good Minecraft pixel font: jsDelivr `@south-paw/typeface-minecraft@1.0.0`
  (`files/minecraft.woff2` + `.woff`), `access-control-allow-origin: *`.
- See `references/minecraft-achievement-toast.md` for the full achievement-popup recipe
  (pixel border via layered box-shadows, square icons, `steps()` animation, tier color bars).
- **Official Minecraft textures as overlay icons** (mob heads, item icons, block faces — all
  tracker types): extract real textures from the Mojang client.jar, crop/composite as needed,
  embed as base64 — full recipe, verified crop boxes, item/block search order, override table,
  and vision-QA workflow in `references/minecraft-texture-icon-extraction.md`.

## Verifying overlays WITHOUT a running server (no port, no TikTok connection)

Use Flask's test client — fast, no port conflicts, no live bot:
```bash
cd D:\Ikhito\Code\TikTokMCIntegrator && timeout 60 python -c "
import app as a
c = a.app.test_client()
for t in ['topgift','topstreak','gifts','chat']:
    r = c.get('/overlay/'+t)
    html = r.get_data(as_text=True)
    print(t, r.status_code, {
        'font': 'Minecraftia' in html,
        'override_block': 'MINECRAFT ACHIEVEMENT-TOAST' in html,
        'scroll_js': 'end-of-stream gift' in html,
    })
"
```
Render-only check: assert HTTP 200 + grep for your new markers (font name, override-block comment,
JS sentinel string) in the returned HTML. This catches Jinja/template breakage instantly. It does
NOT verify pixel appearance — for that, ask the user to open the dashboard preview after restart.
**Gap this missed (2026-09-05):** file:// mock-fetch verification overrides `fetch`, so a WRONG
fetch URL in the overlay passes every visual check while the live overlay shows nothing. When the
change touches what an overlay fetches (endpoint, addon id, payload shape), prove the whole chain
instead: mock helper bridge + real exe + headless Chrome against the real OBS URLs — recipe in
`references/addon-overlay-live-update-and-mock-verification.md` §5.

## Adding a NEW overlay type (full checklist, verified 2026-06-16 — coingoal jar; 2026-06-24 — topgifter podium)

A new overlay type touches **8 spots across 6 files** — miss any and it 404s, stays blank, or
doesn't appear in the dashboard. **Don't rely on memory; read this checklist.**

| # | File | Change |
|---|------|--------|
| 1a | `app.py` | Add type to `overlay_page()`'s `valid_types` list |
| 1b | `app.py` | Add type to `overlay_demo_page()`'s `valid_types` list |
| 2 | `overlay_demo.html` | Add `{% elif overlay_type == 'newtype' %}` branch + markup + CSS + JS handler |
| 3 | `overlay.html` template | Add `{% elif overlay_type == 'newtype' %}` branch BEFORE the `{% else %}` |
| 4 | `overlay.html` CSS | Append `/* ===== NEWTYPE ===== */ … /* END */` block |
| 5 | `overlay.html` JS | Add to `fetchData()` URL ternary + dispatch `else if` + write `handleNewType()` |
| 6a | `routes/stats.py` | Add GET endpoint (read JSON state or compute on the fly) |
| 6b | `routes/stats.py` (POST) | If adding a POST endpoint (reset, clear, toggle) — the route decorator is `@stats_bp.route("/topgifter/reset", methods=["POST"])` but the blueprint is registered with `url_prefix='/api/stats'` in `app.py`. The JS must call `/api/stats/topgifter/reset`, NOT `/api/topgifter/reset`. Bitten 2026-06-24 (Reset button returned "Reset failed" because JS used wrong prefix). |
| 7 | `templates/index.html` | Add `.overlay-section` block (url input + Copy URL + iframe + size hint) |
| 8 | `static/script.js` | Add type string to **`initOverlayPreviews()`** hardcoded array |
| 9 | `static/style.css` | Add `#preview-<type>` override with a custom height if the overlay is taller than 250px (default iframe height clips tall overlays — podium needs 400px, coin-goal jar needed 480px) |
| 10 | `overlay.html` JS | **If the overlay shows user profile pictures**, use the `onload`/`onerror` avatar state machine from `references/avatar-display-pattern.md` instead of a bare `img.src = url`. TikTok avatar URLs expire — without this the frame shows a broken icon corner. Chat/follow overlays use inline `onerror` (simpler but less robust); the podium uses the full pattern.

**PITFALL — new tall overlays get cropped in the dashboard preview.** The default `.overlay-iframe` is 250px tall, set in `static/style.css`. A tall overlay like the podium (banner + avatar + block + bottom margin ≈ 450+ px) will appear clipped. The fix is a CSS override: `#preview-<type> { height: <N>px; }` in `static/style.css`. For the Stardew podium (triple column with ~140px block + 80px avatar + banner + gaps) use 600px. For the coin-goal jar use 480px. Bitten 2026-06-24 (podium) and 2026-06-16 (jar).

**Quick verify after all edits** (catches missing spots in ~2s):
```bash
cd D:\Ikhito\Code\TikTokMCIntegrator && python -c "
from jinja2 import Environment,FileSystemLoader; env=Environment(loader=FileSystemLoader('templates'))
for t in ['overlay.html','overlay_demo.html']: env.get_template(t).render(overlay_type='chat'); print(t+': ok')
import app as a; c=a.app.test_client()
for t in ['topgifter','topstreak','coingoal','chat']:
    r=c.get('/overlay/'+t); r2=c.get('/overlay-demo/'+t)
    print(t, r.status_code, r2.status_code)
"
```

**PITFALL — Avatar URLs expire OR TikTokLive may send blank profile pictures — handle both layers.** TikTok avatar URLs rotate regularly, and TikTokLive can also intermittently omit profile-picture fields. Overlay-side fix: never set bare `img.src = avatar_url; img.style.display = ''`; start hidden, set fallback initial first, then `onload → show img + hide fallback`, `onerror → hide img + show fallback`. See `references/avatar-display-pattern.md`. Backend-side missing-field fix: keep a persistent last-known avatar cache keyed by `unique_id`/nickname and enrich top-gifter state/API responses when a new event has empty `avatar_url`. **Important distinction:** `data/avatar_cache.json` that stores TikTok URLs is only a URL cache, not a local image cache; it does NOT solve later expiry/blocking of `p16/p19-common-sign.tiktokcdn...` URLs. A real local cache must download the image while the signed URL is still valid, store it under `assets/avatar_cache/`, and serve a same-origin URL like `/avatar_cache/<key>.webp`; alternatively use Euler Stream Image CDN to mirror the signed TikTok URL to a stable CDN URL. Also include `avatar_url` in the topgifter render hash or a repaired avatar won't paint until the coin count changes. See `references/tiktok-avatar-cache-workaround.md`, `references/local-avatar-image-cache.md`, and `references/avatar-url-vs-image-cache-and-euler-cdn.md`. Bitten 2026-06-24 (expired URL broken icon), 2026-06-30 (TikTokLive blank profile pic made podium fall back to initials), and 2026-07-08 (confirmed previous “local cache” failed because it cached URLs, not image files).

**PITFALL — Flask Blueprint URL prefix — any new POST endpoint in routes/stats.py must use the blueprint prefix in JS calls.** The stats blueprint is registered in `app.py` with `url_prefix='/api/stats'`. So `@stats_bp.route("/topgifter/reset", methods=["POST"])` lives at `/api/stats/topgifter/reset`, NOT `/api/topgifter/reset`. If the JS calls the wrong prefix, the HTTP request returns HTML 404 → `.json()` parse fails → "Reset failed" toast with no useful error. Always check `app.register_blueprint(stats_bp, url_prefix=...)` to get the prefix before writing the JS fetch URL. Bitten 2026-06-24.
**PITFALL — #8 script.js is the MOST commonly missed spot** (bitten 2026-06-24). The
`initOverlayPreviews()` function in `static/script.js` has a hardcoded core-overlay array:
`['chat', 'gifts', 'follows', 'superfan', 'topshowcase', 'topgift', 'topstreak', 'song', 'coingoal', 'topgifter', 'giftgoal', 'roulette']` — the live array is `OVERLAY_PREVIEW_TYPES` at the top of script.js; verify against the file, not this list.
**Every new CORE overlay type must be appended here.** But if the feature is an add-on/game module, do the opposite: keep it OUT of this array and render/copy its overlay URL from the Add-ons tab. The symptom if you miss this for a core type: the overlay section card exists in the dashboard's HTML, the Copy URL button works (it calls `copyOverlayUrl()` which builds the URL dynamically), but the preview iframe is blank because `updateOverlayUrl(type)` was never called for that type. This is separate from `app.py`'s valid_types — script.js is client-side only and lives outside the Python route system, so there's no 404 to tip you off.

**PITFALL — contract tests assert verbatim JS lines in shared template code.** Before editing a shared line in overlay.html's `fetchData()` (URL ternary, cache-mode condition, dispatch chain), grep the test tree for the exact string — contract tests pin whole lines (e.g. the coingoal no-store fetch line), and adding a new type to that condition fails an unrelated test file. Update the test's expectation in the same change as the template. Grep for the FUNCTION name too, not just the file: pytest collection loads every `test_*.py` that imports `app`, so a test class in a sibling file (e.g. a cache-contract test inside a coingoal test module) can pin the same line twice.

**PITFALL — overlay_demo.html and overlay.html are independent copies.** They have their own
template branches, CSS blocks, and JS handler functions. After patching `overlay.html`, you MUST
make the **same changes** in `overlay_demo.html`. The demo template also has its own
`</style>` preceding `</head>` boundary and its own `// ========== INIT ==========` section at
the bottom. Watch out for: (a) the two templates may have different Jinja structure — always
verify BOTH compile (see quick verify above); (b) `overlay_demo.html` has nesting quirks;
a second `{% endif %}` from a past edit can cause
`TemplateSyntaxError: Encountered unknown tag 'endif'` — caught 2026-06-24 when the demo page
returned 500 while the main overlay page returned 200.

**PITFALL — `:root` variables in overlay.html's `<style>` block.** If you add `:root { ... }`
inside the overlay-specific style block (e.g. Stardew palette CSS vars for the podium), those
are scoped to the page, not the overlay type. Since each overlay type loads alone it's safe,
but if you load two overlay types in the same frame (not currently done), they'd conflict.
Keep `:root` variables that are specific to one overlay's section inside a `.podium-wrap` /
`.cg-wrap` / etc. scope when possible, or accept the page-level scope since each overlay is
its own page.

- **PITFALL — `clip-path` corner cuts clip `box-shadow` too.** When giving a card pixel-cut corners via `clip-path: polygon(...)`, any outer drop shadow declared in `box-shadow` is clipped away with the corners — move it to `filter: drop-shadow(Npx Npx 0 #000)` (filters apply post-clip) and keep only inset rings in `box-shadow` (insets survive clipping). Set `border-radius: 0` explicitly so no rounding softens the cuts. Apply the same cut polygon to nested window/panel elements at their own scale (e.g. 6px card, 4px window) and mirror every change into both `overlay.html` and `overlay_demo.html`.
that predates a recently-added overlay type, BOTH valid_types lists lose the new entry. The
symptom is a 404 on the OBS overlay route even though the template and JS are correct. Check
both lists explicitly, not just one — a restore may have patched only `overlay_page()` from a
partial diff. (Bitten 2026-06-16: coingoal overlay 404'd post-restore because `overlay_demo_page()`
was still missing it.)

### Data pipeline backing: server-side accumulator vs direct log read

- **Direct log read** (topgift, topstreak): reads from an existing event log (gift_log.json)
  and computes the top entry in JS. No server-side state to maintain. Simpler, but you're
  filtering/sorting N log entries every poll.
- **Server-side accumulator** (topgifter, coingoal): maintain a separate state file
  (gifter_ranking.json, coin_goal.json) that the bot updates per-event, and the overlay just
  reads it. More efficient (no scan per poll), but requires:
  - A function in minecraft_main.py (e.g. update_gifter_ranking()) called from the event
    handler to accumulate state
  - A JSON file in the data/ directory as single source of truth
  - Locked read-add-write (with _log_lock) when the bot and dashboard both mutate the file
  - The API endpoint just reads the file and returns it

For the topgifter leaderboard pattern (2026-08-05, supersedes the old direct-file podium):
- **minecraft_main.py**: `update_gifter_ranking(nick, avatar_url, total_coins, unique_id="")`
  delegates to `stream_ranking.py` (NOT a direct load/write of gifter_ranking.json). Called
  from on_gift() after the streaking gate. `on_like` accumulates likers the same way.
- **routes/stats.py**: GET /api/stats/topgifter returns `{gifters:[top10], likers:[top10]}`.
- JSON files `data/gifter_ranking.json` / `data/liker_ranking.json` remain the on-disk
  source of truth (reconnect reload), but all reads/writes go through stream_ranking's
  locked + throttled accessors. See `references/topgifter-liker-leaderboard.md`.

### Configurable overlays: live state via a JSON file + locked read-add-write
For an overlay the streamer edits live (e.g. coin-goal jar label/goal/current) AND that the bot
mutates per-event:
- **One JSON state file** (`coin_goal.json`) is the single source of truth. Overlay polls
  `/api/stats/<type>`; dashboard popup POSTs to `/api/<type>`.
- **Bot side** (`minecraftDiamond.py`): event handler does a **locked read-add-write**
  (`with _log_lock: data = load(); data['current'] += delta; safe_json_write(data)`) so the
  streamer's manual edits from the dashboard are never clobbered by an in-memory counter. Do NOT
  keep the running total in a module global — always read the file fresh, add, write back.
- **POST endpoint** supports `mode: "set"` (absolute) vs `"adjust"` (delta +/-) plus a
  `reset:true` flag. Khito wanted all three (set exact value, quick +/- adjust, reset to 0).
  **Backend must explicitly branch on `reset:true` before `mode` handling.** A real bug happened
  where the dashboard sent `{reset:true}` but `/api/coingoal` only handled `mode:"set"`, so the
  Reset button did not change `current`. Regression-test with Flask test_client: seed
  `coin_goal.json` with `current:123`, POST `/api/coingoal` `{reset:true}`, assert
  `current == 0` while `goal`, `label`, and `sublabel` are preserved. Also test
  `mode:"adjust"` adds/subtracts and floors at 0.
- Persistence is intentional: the jar carries across stream sessions/restarts; reset is manual
  only (Khito uses it for multi-stream milestones). Never auto-reset on startup.
- Changes are live (overlay polls every 1.5s) — no bot restart needed for config edits, only the
  usual rebuild+restart for code changes.
- **Do not trust same-URL polling to bypass OBS/WebView2 caches.** If the state file and a fresh
  Flask GET contain the new value but the overlay remains stale, protect both layers: return
  strict no-cache headers from the mutable stats endpoint and poll with a timestamp query plus
  `fetch(..., {cache:'no-store'})`. Test the full POST → file → GET → rendered-DOM path. See
  `references/live-polled-overlay-cache-control.md` for the diagnostic and verification recipe.

### Outcome-reveal overlays: server picks the winner, backend executes, overlay only presents

When an overlay animation reveals an outcome that ALSO fires a real action (Minecraft command, sound, webhook — roulette/randomizer spins, giveaway draws):
- Pick the outcome server-side upfront and persist `{entries, winner_idx, lands_at}` in the polled JSON state file; the overlay reads the winner and lands its animation on that row, never rolling its own random.
- Execute the winning action from a backend timer keyed to the land timestamp, never from overlay JS — OBS browser sources only run while visible, so overlay-driven execution silently drops the action whenever the source is hidden while the stream still sees a winner.
- Derive dashboard status, console log, and overlay from the same state file so all three agree.
- Schedule the landing with `asyncio.create_task(...)` from inside the TikTok event handler, awaiting sleep to the land timestamp — never `threading.Timer`: the action dispatcher is async (a timer thread cannot await it) and outlives reconnect loops with no event loop to marshal back to.
- Execute through the Log Only-gated dispatcher wrapper (`minecraft_main.execute_actions`), never raw `actions.execute_actions` — the wrapper re-checks the toggle at land time, so flipping Log Only mid-spin still suppresses output.
- Deep-copy (snapshot) the winner's action bundle at spin start: config edits or profile switches mid-spin must not change the outcome viewers already watched.
- Define rejection semantics up front: busy/cooldown/invalid pool → run the trigger gift's normal gift-specific actions so the viewer keeps their reward; never queue delayed actions.
- Winner context replaces identity and pins amount/repeat to 1 — never inherit the trigger's repeat count (a streaked cheap trigger would scale destructive commands) or its gift_name.
- Gate the trigger on the completed-gift branch so streak gifts spin once on the final event; sweep stale `spinning` state to cancelled at startup — never replay a half-finished spin after a restart.
- **Roulette timing knobs (spin/hold/cooldown):** spin = roll showmanship only (winner is picked upfront — longer spins need MORE ticks, never slower ones, see audio rule); hold = winner dwell on screen before the card hides (long enough to read the result, ~4s); cooldown = quiet window after a spin where the trigger is ignored (raise to 5–10s if chat spams the trigger into back-to-back spins). Keep the trigger gift out of the prize pool unless a trigger self-win is intended.
- Dashboard and bot are separate processes with separate in-memory locks: an executable test spin from the dashboard must be refused (HTTP 409) while the bot runs, not coordinated through the shared state file.
- **Reel content = the action, not the gift.** Khito's reels show what the winner's bundle DOES in Minecraft — his gift-list description text first (that IS the action name he maintains), then the `titlecustom` title text, then the minecraft command verb capitalized — never the gift name, gift icon, `#id`, or raw command text. Derive it from the winner's snapshot bundle plus the live GiftNames/GiftDescriptions snapshots (keep the field separate from the display-label field so the GiftDescriptions doctrine is untouched), and render reel rows text-only, centered, larger than alert body text. Cover label precedence with a test that seeds real names/descriptions — tests passing `{}` for both stay green while production labels silently degrade to catalog gift names.
- **Pass the real GiftNames/GiftDescriptions snapshots into EVERY spin-prep/resolve call site.** The bot's trigger path passed empty dicts for both, silently degrading every label to catalog gift names on stream while tests (which seed fixture names) stayed green. When a label field renders wrong, grep the production call site for `{}` placeholder snapshots before touching the display code.
- **Config panels that edit the feature's block must NEVER reject-and-discard a save.** On invalid enable (missing trigger, too-small pool) persist everything the user entered, force `enabled=false`, and return a `warnings` array the panel renders inline + toast; a 400 that throws away the whole PUT is how "no matter what I changed, nothing saved" happens. Also: every configurable field needs an actual input control — shipping a display-only "current value" row for a settable field is a design gap the user cannot work around.
- **Slot-machine audio without asset files: Web Audio.** Ticks run on a FIXED absolute rhythm — open at ~70ms rat-a-tat with gaps growing ~12% per tick, stop at land; spin length decides tick COUNT (5s ≈ 20, 2s ≈ 14), never laziness. Never sync ticks to row count or stretch a fixed tick count across the duration: 14 ticks over 5s ≈ 357ms gaps sounds slow and tension-less next to ~143ms over 2s. Overlay loop: requestAnimationFrame against elapsed time (`nextTickAt += gap; gap *= 1.12`). Dashboard preview/mirror: a scheduled synth sharing tick/chime/roll-scheduler helpers. Play a rising 3-note triangle chime the moment the winner locks. **Autoplay policy: `ctx.resume()` at spin start is NOT enough.** A plain browser tab that never got a click keeps the AudioContext suspended and silently drops every sound (shipped this way once; user heard nothing and reported it) — OBS browser sources allow autoplay, so the stream path works while the user's own test tab doesn't, which hides the bug during development. Arm `pointerdown`/`keydown` unlock listeners at page load; make the land chime the detector (if `ctx.state !== 'running'` after a ~250ms resume race, show a one-time "click once for sound" message in an EXISTING slot such as the header text — never a new DOM element, which breaks the fixed-geometry contract); and give the dashboard panel a "Test sound" button running the same synth (the click IS the gesture) so audio is verifiable without the overlay. **Dashboard iframe previews are separate documents with their own suspended AudioContext** — a Test Sound button proves the SYNTH works but says nothing about the overlay path, and a test action triggered from the dashboard still sounds only inside the iframed overlay page, so it stays silent in a plain tab while OBS (autoplay allowed) would have sounded. Mirror test-triggered audio in the dashboard document itself: share the synth helpers (tick/chime/roll-scheduler) between preview and mirror, stretch the mirrored roll to the real land delay from the test response (`lands_at - now`), and verify the scheduler math headlessly (e.g. a 5000ms spin must schedule the roll across ~5.00s with widening tick gaps). **Note for headless verification: AudioContext exists but produces no output in headless Chrome/Edge — probe for constructor + state, never for sound.**
- Verify mid-flight pixels with the real-pixel harness (see `real-pixel-ui-verification`), and mind two harness traps learned on the roulette reel: **`--virtual-time-budget` IS the animation timeline** — CSS animations, transitions, AND hide timers all run inside it, so a hidden-when-idle card captured at a late budget has already popped, held, and squashed away; capture per-state budgets (e.g. ~350ms for the mid-pop squash frame, a full-hold budget for the settled winner) and assert the idle state renders empty. And **inject the mock fetch BEFORE the overlay's own script** (right after `<body>`), since a `file://` page cannot fetch relative `/api/*` URLs — the mock returns a page-relative state so the animation timeline is deterministic.
- **Deliver motion previews to Khito as MP4, not GIF.** Telegram flattens animated GIFs sent via the photo path to their first frame — he sees a still image and asks "where's the gif". Render the frame sequence, assemble with Pillow, then `ffmpeg -i preview.gif -movflags faststart -pix_fmt yuv420p preview.mp4`; MP4s play inline with motion. Keep the GIF for artifact storage, send the MP4.

### Pop/bounce entrance for hidden-when-idle cards

Khito wants popup cards to POP, not blink: bouncy squash-and-stretch entrance, quick squash-out on hide. Contract, verified on the roulette overlay (reference implementation: the roulette branches in `templates/overlay.html` + `overlay_demo.html` — mirror both):
- Run the CSS animation on the card CHILD (`transform-origin` at its stream-facing edge — bottom for a bottom-anchored card), keyed off wrapper classes (`<x>-visible` in / `<x>-hiding` out). Size/position stay on the wrapper, keyframes only transform — the card's fixed geometry is untouched when settled.
- Restart a CSS animation on re-trigger by removing the class, forcing a reflow (`void el.offsetWidth`), then re-adding it. Re-adding alone does NOT restart a finished animation — the second spin pops in frozen.
- Hide = add the squash-out class (≤~340ms) BEFORE `display:none`, tracked in its own timer variable that a new trigger MUST cancel — a spin arriving mid-squash-out otherwise silently loses its entrance. Clear both the hide-timer and the hide-anim-timer at the top of the show path.
- Keyframes shape: scale flat/wide → overshoot tall → two diminishing bounces → settle; exit is the reverse squash with opacity 0 at the end.
- Verify mid-flight pixels with the real-pixel harness (short virtual-time-budget frame; see `real-pixel-ui-verification`).

### Canvas rendering for "filling" / particle overlays (fusion-panel verdict 2026-06-16)
For an overlay with accumulating visual elements (coins filling a jar, liquid rising, particles),
use **HTML canvas, NOT pure CSS fill** — CSS height-clip looks fake and can't show real
accumulation. For packed RGB+alpha TikTok gift videos, also read `references/packed-alpha-performance-budget.md`: the compositor must be frame-budgeted and completely disabled in dashboard `preview=true` contexts. The performance-safe canvas recipe (must survive a multi-hour always-on OBS source):
- **Event-idle scheduler**: do not keep a `requestAnimationFrame` chain alive merely to check a dirty flag. Schedule the first frame only when state changes; set the RAF handle back to `null` when rendering begins; schedule another frame only while fill interpolation or particle physics still has work. A perpetual no-op RAF can still keep Chromium's renderer/compositor awake.
- **Offscreen sprite cache**: pre-render one pixel-art sprite to a tiny offscreen canvas once
  (`cgBuildSprite()`), then `ctx.drawImage(sprite, x, y)` to blit — never redraw vector art per
  frame per particle.
- **Capped particle pool**: hard cap (e.g. 600) on total coins; on a +5000 event spawn only a
  small visual delta (e.g. `Math.min(40, delta/5)` falling coins), don't instantiate thousands of
  sprites. Settled coins bake into a static layer; only falling coins run physics.
- **Clip to interior**: `ctx.save(); ctx.rect(jar interior); ctx.clip();` so fill/coins never
  bleed past the pixel walls. Draw the chunky pixel frame OVER the fill afterward.
- **CSS handles the chrome**: jar glass shimmer (`@keyframes` + `mix-blend-mode`), the label
  plate, the counter text, slot/count-roll animation, and goal-reached celebration all live in
  CSS — keep them off the canvas. Canvas does coins only.
- On first data load, **snap** the fill/counter to the current value (don't rain 1000s of coins on
  page load); only animate the delta on subsequent increases.

**PITFALL — CSS shimmer/shine overlay must be position-pinned to the jar interior, not `inset:0`
(2026-06-16):** A `.cg-shine` div with `position:absolute; inset:0` covers the ENTIRE canvas box,
so the glass shimmer bleeds across the whole overlay (symptom Khito reported: "the glass effects
is affecting even outside the jar, like the entire canvas"). Fix: pin the shine div to the exact
jar-interior rect with explicit `left/top/width/height` matching the canvas `CG_JAR` coords (e.g.
`left:38px; top:70px; width:164px; height:210px`) + `overflow:hidden`. General rule: any decorative
CSS overlay on a canvas overlay must be sized to the drawn region, never the full element box.

**Text legibility (2026-06-16; refined 2026-06-26 giftgoal):** Khito puts overlays in a screen corner over arbitrary gameplay
backgrounds. Counter/goal/sublabel text at low opacity (`rgba(255,255,255,0.45)`) blends into the
background — he asked for solid `#fff`. Default overlay text to opaque white with a dark
`text-shadow`, not translucent white. Apply the Minecraft font (`var(--font-mc)`) to ALL text
elements in a pixel-art overlay (counter, label, AND sublabel) for consistency, not just the
headline number. **For small pixel/Minecraft text, do NOT use a visible `-webkit-text-stroke`:**
in OBS it can make the fill look grey/dark because the stroke consumes the small glyph. Prefer
`color:#fff !important; -webkit-text-fill-color:#fff !important; -webkit-text-stroke:0 transparent;`
plus a tiny `1px 1px` shadow.

## Stream baseline performance regressions

When Khito says the streaming setup became heavier **over days as features were added**, first distinguish that cross-release baseline regression from a workload that grows during one stream. Do not over-attribute a point-in-time CPU sample to the newest visual feature: confirm whether the actual static or animated code path was active, then measure process-tree CPU deltas over 10–20 seconds.

- The native dashboard EXE is not the full app cost; include its child `msedgewebview2.exe` renderers.
- OBS's shared `obs-browser-page.exe` / GPU process combines all active third-party and TikTokMC Browser Sources. Use OBS WebSocket runtime `videoActive` / `videoShowing` state rather than scene JSON alone to identify what is actually running.
- Audit every retained overlay/history feature for permanent polling, `requestAnimationFrame`, CSS infinite animation, and repeated DOM work while state is unchanged.
- Prefer event-idle work: compact summary endpoints, render-key deduplication, scheduler teardown when canvas physics ends, and static styling for retained dashboard history.
- Bump the dashboard stylesheet version after CSS performance changes so WebView2 cannot retain old expensive styling.

Read `references/stream-baseline-performance.md` for the full audit and validation procedure.

## Pitfalls
- **TikTok high-value gift animations are often packed RGB+alpha videos (2026-07-03; corrected 2026-07-24).** The downloaded file can show RGB on the left half and alpha/matte data on the right. Do **not** render it directly in `<video>` for OBS. Compose it through canvas: draw the left half as RGB, the right half as mask, and set output alpha from mask luminance/max channel. Portrait assets are commonly 1440×1280 (720×1280 per half), so detect packed alpha with a half-width check such as `(vw % 2 === 0) && (vw >= vh * 0.9)`, not only a wide aspect-ratio threshold. **Crop-learning pitfall:** never freeze the crop after an arbitrary early-frame count. Many gifts begin near the bottom and expand upward later; production analysis found **27 of 40** cached assets exceeded their first-10-frame crop. At the existing bounded 20 FPS compositor rate, scan the alpha mask throughout the **first complete video loop**, grow a padded union bbox, detect the first `currentTime` wrap, and then stop crop scanning permanently. **Sizing pitfall:** draw the learned bbox into the fixed 128×96 Top Gift panel with contain scaling (`Math.min(outW/cropW, outH/cropH)`), centered horizontally and bottom-anchored (`dy = outH - drawH`). Do not use cover scaling: it deliberately overflows the canvas and crops tall gifts at the top. Static icons stay 56×56; animated sizing must not leak into normal icons. Keep cards compact and clamp text rather than forcing broad card dimensions. Apply shared compositor changes to **Top Gift, Top Showcase, and Gift Goal** so changing a common constant cannot silently break one renderer. Attach `asset_url` to `gift_log.json`; if no cached animation or the gift is below the animation threshold, use the static icon. First-time downloads must stay off the TikTok event loop and patch the log entry when ready. See `references/packed-alpha-performance-budget.md` for the bounded first-loop recipe and asset-level verification method.
- **Gift Goal layout must be structural, not CSS-only (2026-06-26).** Khito corrected this twice from OBS screenshots: counter BELOW gift icon means `.gg-progress` must be a sibling after `.gg-icon-wrap`, not a child inside it. If a screenshot shows the counter beside/over the icon after a CSS patch, inspect the markup before tweaking more CSS. For this overlay's current desired look: centered horizontally; header above/over the icon; gift icon in the middle; counter below; text all white, no text-background pill, Minecraft font + small dark stroke/shadow.
- **Song overlay anchoring:** keep the Now Playing card visually stable when the queue length changes. If `.song-overlay-wrap` is bottom-anchored (`bottom:16px`), adding/removing queued songs makes the whole card grow upward, so the Now Playing section moves around. Anchor the song overlay from the top (`top:16px; right:16px`) so only the UP NEXT / queue area expands downward. Verify both source and deployed CSS (`release/static/style.css` and `release/_internal/static/style.css`) contain `top: 16px` and no `bottom:` in `.song-overlay-wrap`.
- The `--font-heading` var (Outfit/Inter) drives the default overlay look; a custom font needs its
  own var + explicit `font-family … !important` on every text element, or the old font wins.
- Gift-feed entry base styles live in `static/style.css` (`.gift-log-entry .gift-name` etc.), but
  the `data-type="gifts"` layout + tier `::before` glows live in `overlay.html`. Override both.
- After ANY core overlay change, deploy via `./deploy.sh` (see `tiktokmc-build-deploy`) and remind the
  user to restart `release/TikTokMCIntegrator.exe`. Templates are bundled into the exe — editing
  source files does nothing live until rebuild + restart.
  **EXCEPTION — add-on overlays (`addons/<id>/overlays/*.html`):** these are NOT bundled; `routes/addons.py`
  serves them via `send_file` from `release/addons/` on EVERY request. Overwriting the copy in
  `release/addons/<id>/overlays/` + `release/_internal/addons/<id>/overlays/` takes effect on the next
  OBS refresh with the exe still running — no rebuild, no restart, stream-safe. Verify with a live
  `curl` of `/overlay/addon/<id>/<overlay_id>` + md5 compare. Full recipe + visual mock-verification:
  `references/addon-overlay-live-update-and-mock-verification.md`.
  For boolean/status widgets, icon exclusivity, offline transparency, and deterministic Chromium
  probes, also read `references/addon-status-overlay-verification.md`.
- Khito wants overlays compact, corner-friendly, center-aligned, and empty/hidden when no data.
  Honor this for any new overlay or restyle. If he says “use the gift overlay as the example,” match the gift overlay’s **proportions and density** first; do not invent a bigger card unless he explicitly asks.
- **Fixed-geometry rule (2026-09-05):** counter/status cards must keep ONE constant size regardless of config values — never render N-segment bars or element counts that scale with a config number (the deaths-until-strike cycle went 10 → 20 and turned the card into a rectangle; Khito had the bar removed and the card locked to a fixed 190×190 square). A config change may alter TEXT only, never the card's box. For geometry-critical changes, prove it: headless-render the overlay at ≥2 config values and measure the card's dark-pixel bbox — NOT the alpha bbox (headless Chrome screenshots carry an opaque white canvas background outside the card, so an alpha bbox reports the full window) — plus a frame-ring hash across configs.
- **Follower overlay redesign pitfall (2026-06-29):** The correct follow-alert target is gift-feed parity, not a large profile-card design. Keep the follow card compact (360px wide, ~64px min-height, 10px/12px padding), remove the right-side FOLLOW badge, and never show a fallback person icon. If the avatar URL is missing or fails, remove/hide the avatar block entirely. If an avatar is present, use a small pixel frame and accept that real TikTok photos will not look like clean gift icons without canvas preprocessing.
- **Scoped CSS patching pitfall:** When tuning overlay CSS, do not run broad string replacements like `width: 430px` → `width: 360px` across the whole template — it can corrupt unrelated chat/gift/song/top-card CSS. Patch only the exact overlay block with surrounding selector context, then inspect the diff for unrelated selectors before deploy. If a patch goes sideways, restore from `.overlay-backups/<timestamp>/` immediately and re-apply narrowly.

- **PITFALL — overlay_demo.html can have a different Jinja structure than overlay.html.** The
  demo template uses a nested `{% if %} … {% endif %} … {% endif %}` pattern (the second endif
  is a false twin from an earlier edit). Always verify BOTH templates compile with Jinja2 after
  changes, not just overlay.html. Use: `python -c "from jinja2 import Environment,FileSystemLoader; env=Environment(loader=FileSystemLoader('templates')); tpl=env.get_template('overlay_demo.html'); tpl.render(overlay_type='chat')"`. If this throws `TemplateSyntaxError: Encountered unknown tag 'endif'`, the template has an endif count mismatch.

## Text Animation

For animated text transitions in overlays (gift alerts, now-playing, follower names), see
`references/slot-text.md` — a tiny (~4KB) dependency-free text roll animation library
available via esm.sh CDN. GPU-composited per-character vertical slide with spring bounce.
Perfect for vanilla HTML overlays: `import { slotText, chromatic } from "https://esm.sh/slot-text"`.

For Khito's standalone Minecraft OBS overlays outside the bot repo (e.g.
`C:\\Users\\yusar\\Documents\\Code\\Live\\McPY\\overlay\\diamondCounter.html` and
`winOverlay.html`), prefer the dependency-free local implementation in
`references/local-slot-text-overlays.md`: per-character slot roll, skip unchanged digits, up/down
movement, and a gold jackpot variant for win counters. This avoids npm/CDN/bundler assumptions in
single-file OBS sources while preserving the slot-text feel.
