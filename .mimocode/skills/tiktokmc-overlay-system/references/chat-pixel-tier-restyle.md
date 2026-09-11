# Chat Pixel Tier Restyle Pattern

Use this when restyling the TikTokMCIntegrator **chat** overlay to match the Minecraft/pixel theme while keeping tier styles readable and distinct.

## Context

Chat uses the existing gifter-level tier thresholds in both `templates/overlay.html` and dashboard/demo builders:

| Tier | Threshold | Label |
|---|---:|---|
| Tier 1 | `gifter_level >= 20` | `IRON` |
| Tier 2 | `gifter_level >= 25` | `AMETHYST` |
| Tier 3 | `gifter_level >= 30` | `GOLD` |
| Tier 4 | `gifter_level >= 35` | `LEGEND` |

The user explicitly cares that the chat overlay stays **easy to read** while still looking beautiful. Do not copy the gift overlay card exactly; chat has longer text and tier variety.

## Design recipe

- Base card: dark stone/slate pixel slab, hard border, bevel shadows, no glass blur dependency.
- Width: around `400–410px`; gift feed can be narrower, but chat needs room to avoid ugly wrapping.
- Text: opaque warm white (`#fff8df`-ish), dark pixel shadow, no translucent/low-contrast message text.
- Avatar: square pixel frame, not rounded circle.
- Tier chip: add a small classed chip near the username (`chat-tier-chip`) instead of relying only on colored borders.
- Tags: replace inline tag styles with a classed chip (`chat-tag-chip`) so the CSS can maintain pixel styling.
- Tier identity:
  - Default: stone slab / muted stripe
  - T1: iron-cyan trim
  - T2: amethyst/purple gem frame
  - T3: gold relic card
  - T4: nether/legendary red-gold frame
- Animations: if used, keep them `steps()`/pixel-like and subtle. Avoid full rainbow casino glow over gameplay.

## Implementation pattern

1. Back up `templates/overlay.html`, `templates/overlay_demo.html`, `static/script.js`, and `static/style.css` to `.overlay-backups/<timestamp>/`.
2. Append a reversible scoped block to `templates/overlay.html`:
   - marker: `/* ===== CHAT PIXEL TIER RESTYLE BEGIN ===== */`
   - scope every selector under `.overlay-wrap[data-type="chat"]`
   - neutralize old tier gradient/sparkle behavior only inside chat.
3. Add a small `getChatTierMeta(tierClass)` helper in both live overlay JS and dashboard/demo JS, returning `IRON`, `AMETHYST`, `GOLD`, `LEGEND`.
4. In chat entry builders, render:
   - `<span class="chat-tier-chip chat-tier-chip-${key}">LABEL</span>` when tiered
   - `<span class="chat-tag-chip">...</span>` for tags
5. Remove or suppress random sparkle particle injection for chat tiers. Prefer CSS pseudo-elements for tiny pixel accents.
6. Mirror the same markup/styling in `templates/overlay_demo.html`.
7. Add minimal dashboard CSS in `static/style.css` for `.ticker-entry.comment .chat-tier-chip` and `.chat-tag-chip` so the dashboard log does not show unstyled chips.

## Verification

Run the normal overlay checks:

```bash
python - <<'PY'
from jinja2 import Environment, FileSystemLoader
root='D:\Ikhito\Code\TikTokMCIntegrator'
env=Environment(loader=FileSystemLoader(root+'/templates'))
for name in ['overlay.html','overlay_demo.html']:
    html=env.get_template(name).render(overlay_type='chat')
    print(name, 'compile_ok', 'CHAT PIXEL TIER RESTYLE' in html, 'chat-tier-chip' in html)
PY
node --check static/script.js
python - <<'PY'
import app as a
c=a.app.test_client()
for route in ['/overlay/chat','/overlay-demo/chat','/overlay/gifts','/overlay/follows']:
    print(route, c.get(route).status_code)
PY
git diff --check -- templates/overlay.html templates/overlay_demo.html static/script.js static/style.css
```

Then deploy with `./deploy.sh` and verify the markers exist in both `release/` and `release/_internal/` copies.

## Pitfalls

- Do not make chat as narrow as gift feed by default; chat text needs more horizontal room.
- Do not use low-opacity text over gameplay. Readability beats decoration.
- Do not use broad replacements for tier selectors; `tier-1`/`tier-2` appear in multiple overlay systems.
- Do not leave tier/tag chips unstyled in the dashboard log after adding markup.
- Avoid random JS sparkle spam for chat: it makes repeated live messages visually noisy and can hurt readability.
