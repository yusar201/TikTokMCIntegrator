# Gift Goal Overlay — UI + Dashboard Picker Lessons

Session: 2026-06-26

## Feature shape

`giftgoal` is a compact OBS overlay for tracking one selected TikTok gift toward a count target:

- State file: `gift_goal.json`
- Overlay poll: `GET /api/stats/giftgoal`
- Dashboard save: `POST /api/giftgoal`
- Dashboard gift list source: `GET /api/gifts/available`
- Bot increment: `add_to_gift_goal(gift_id, repeat_count)` inside the completed-gift block, after streak finalization. Match by **gift_id**, not name.

State shape:

```json
{
  "gift_id": "5655",
  "gift_name": "rose",
  "gift_icon": "https://...",
  "goal": 100,
  "current": 0,
  "header": "Goal Today"
}
```

## Overlay layout pitfall: counter must be structurally outside icon wrapper

Khito explicitly wanted:

1. header above / slightly overlapping top of the gift icon
2. gift icon centered
3. counter **below** the gift icon

Do **not** put `.gg-progress` inside `.gg-icon-wrap`. If it is inside the icon wrapper, OBS/Chromium will keep positioning it as part of the icon area, and CSS `order` / `position: static` will not visually separate it reliably.

Correct markup:

```html
<div class="gg-wrap" id="gg-wrap">
  <div class="gg-header" id="gg-header">Goal Today</div>
  <div class="gg-icon-wrap">
    <img class="gg-icon" id="gg-icon" src="" alt="" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
    <div class="gg-icon-ph" style="display:none"><i class="fa-solid fa-gift"></i></div>
  </div>
  <div class="gg-progress" id="gg-progress"><span class="gg-current" id="gg-current">0</span>/<span class="gg-goal" id="gg-goal">100</span></div>
</div>
```

## Text color pitfall: pixel font + stroke looks grey/dark in OBS

Khito asked for white text. With small Minecraft/pixel font, a `-webkit-text-stroke: 1px ...` made the text look grey/dark in OBS screenshots because the stroke ate most of the glyph fill.

Use **no stroke** and a tiny shadow only:

```css
.gg-header,
.gg-progress,
.gg-current,
.gg-goal {
  font-family: var(--font-mc), var(--font-heading), sans-serif !important;
  font-weight: 900 !important;
  color: #fff !important;
  -webkit-text-fill-color: #fff !important;
  -webkit-text-stroke: 0 transparent;
  text-shadow: 1px 1px 0 rgba(0,0,0,0.85) !important;
}
```

Do not use green for `.gg-current`; Khito wanted the full counter white.

## Dashboard picker pattern

A plain `<select>` for gifts is too bland and hard to use. Use an icon picker:

- hidden fields for `gift_id`, `gift_name`, `gift_icon`
- selected gift preview with icon + name + ID/coins
- search input by name, ID, or coin value
- sort dropdown: A-Z, Z-A, coins ascending, coins descending
- clickable gift cards with icon/name/coins
- cap rendered results (e.g. first 160) and ask user to search to narrow

This avoids a massive native select and makes the gift choice visually obvious.

## Cache busting

Dashboard changes touched both `templates/index.html`, `static/script.js`, and `static/style.css`; bump both query params (`style.css?v=N`, `script.js?v=N`) so WebView2 dashboard reloads the picker UI.

## Verification checklist

```bash
node --check static/script.js
python - <<'PY'
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'))
for t in ['overlay.html','overlay_demo.html']:
    html = env.get_template(t).render(overlay_type='giftgoal')
    assert 'id="gg-icon"' in html and 'id="gg-progress"' in html
    assert html.index('id="gg-icon"') < html.index('id="gg-progress"')
    assert '-webkit-text-stroke: 0 transparent' in html
    assert '-webkit-text-fill-color: #fff !important' in html
print('giftgoal templates ok')
import app as a
c = a.app.test_client()
for url in ['/overlay/giftgoal','/overlay-demo/giftgoal','/api/stats/giftgoal','/api/gifts/available']:
    r = c.get(url)
    print(url, r.status_code)
    assert r.status_code == 200
PY
```

After deploy, verify both `release/templates/overlay.html` and `release/_internal/templates/overlay.html` contain the corrected structure and no-stroke white text CSS.
