# Top 3 Gifter Podium Overlay Recipe

Session: 2026-06-24. Added the `topgifter` overlay type — a podium-style ranking of top 3 gifters per stream. Revised from a basic podium to a full Stardew-Valley-inspired design using a Gemini reference file.

## Design rules (Stardew Valley pixel aesthetic — v2, Gemini-inspired)

The current design uses the **Stardew palette** defined as `:root` CSS variables:

```css
--gold-p: #e5a93b; --gold-d: #9e661b; --gold-l: #f7d57c;
--stone-p: #a3a7b2; --stone-d: #646872; --stone-l: #d1d5e0;
--wood-p: #aa6f46; --wood-d: #6d3b19; --wood-l: #cf9b74;
--border-dark: #311405;
--font-pixel: 'Press Start 2P', monospace;
```

- **Banner** at top: cream `#f3cca1` background, skewed slightly, with decorative side-tabs (`::before`/`::after`). Red text with white + dark-red text-shadow. Text: "⭐ GIFTER'S STAND ⭐"
- **Podium blocks** — each rank has a distinct texture via `repeating-linear-gradient`:

| Rank | Texture | Height | Decorations |
|------|---------|--------|-------------|
| 1st (Netherite) | Dark charcoal grid (#444a52 base, #2a2e33 grid lines every 30px, 45deg texture noise) | 140px | None |
| 2nd (Diamond) | Cyan grid (#5dd3d7 base, #2e8a93 grid lines every 30px, 45deg texture noise) | 100px | None |
| 3rd (Gold Block) | Yellow grid (#fcee4d base, #b88115 grid lines every 30px, 45deg texture noise) | 70px | None |

Updated 2026-06-25: reworked from Stardew (gold/stone/wood) to Minecraft blocks (netherite/diamond/gold). Removed all emoji decorations (🌿 vines, 🐈 cat). Added `image-rendering: pixelated` on each block. Avatar frame outlines match block border colors. Plaques are rank-specific (netherite-light bg for 1st, diamond-light for 2nd, goldblock-light for 3rd).

- **Block border**: 3px `var(--border-dark)` on all sides
- **Inner shadow**: 6px of the light variant at the top, 8px hard drop-shadow at the bottom

- **Avatar frames**: 80×80px (#1) or 72×72px (#2, #3), double-bordered:
  - #1: `border: 6px solid var(--border-dark)` + `outline: 4px solid var(--gold-p)`
  - #2: `border: 6px solid var(--stone-d)` + `outline: 4px solid var(--stone-l)`
  - #3: `border: 6px solid var(--border-dark)` + `outline: 4px solid var(--wood-p)`
  - Fallback: `?` in 28px pixel font on dark `#111` background, centered

- **Crown**: NOT an emoji — pixel-art SVG (11×8 viewBox, ~44×32px rendered) using crispEdges rendering. Dark brown + gold + blue sapphire rectangles. Bounces up/down with `crownBob` keyframe animation. Drop-shadow for depth.

- **Username**: `Press Start 2P` at 10px, white, max 140px with ellipsis, hard pixel text-shadow (2px 2px black)

- **Score badge**: dark semi-transparent `rgba(0,0,0,0.65)` pill with 2px border-dark, 9px pixel font, gold text `#ffeb54` with a ⭐ star icon

- **Plaque** on each podium block: `background: #e5b075` with inset bevel shadows (dark bottom-right + light top-left), pixel font at 9px, dark brown `#442003` text. Text: "1st PLACE" / "2nd" / "3rd"

- **Staggered entrance**: columns animate in (bottom: col-2 at 0s, col-1 at 0.08s, col-3 at 0.16s) with a cubic-bezier slide-up bounce.

- **Pulse on data change**: username scales to 1.12× and turns gold briefly

## Layout (HTML injection order)

```
col-2 (left, 2nd place) | col-1 (center, 1st place) | col-3 (right, 3rd place)
```

HTML order intentionally 2→1→3 so the crown sits on the center column naturally. Each column uses `opacity` (not `visibility`) to show/hide, so the entrance animation works on first data.

## States

| State | `.podium-wrap` | `#col-*` |
|-------|---------------|----------|
| No data | `opacity: 0`, `.visible` removed | all `opacity: 0` |
| 1 gifter | `opacity: 1`, visible | col-1 visible, col-2/3 hidden |
| 2 gifters | `opacity: 1`, visible | col-1 + col-2 visible, col-3 hidden |
| 3 gifters | `opacity: 1`, visible | all visible |
| Same data (no change) | already visible, re-show | skip re-render (hash unchanged) |

## JS pattern

```js
let prevGifterHash = '';

function handleTopGifter(data) {
  const wrap = document.getElementById('podium-wrap');
  if (!wrap) return;
  if (!data || !Array.isArray(data) || data.length === 0) {
    wrap.classList.remove('visible'); return;
  }
  const hash = JSON.stringify(data.map(g => g.nick + ':' + g.total_coins));
  if (hash === prevGifterHash) { wrap.classList.add('visible'); return; }
  prevGifterHash = hash;

  for (let i = 0; i < 3; i++) {
    const entry = data[i] || null;
    const idx = i + 1;
    const col = document.getElementById('col-' + idx);
    const nameEl = document.getElementById('name-' + idx);
    const scoreEl = document.getElementById('score-' + idx);
    const frame = document.getElementById('av-' + idx);
    if (!col || !nameEl || !scoreEl || !frame) continue;
    if (!entry) { col.style.opacity = '0'; continue; }
    col.style.opacity = '1';
    nameEl.textContent = entry.nick || '???';
    scoreEl.textContent = entry.total_coins ? entry.total_coins.toLocaleString() : '0';
    // Avatar: use the onload/onerror state machine from references/avatar-display-pattern.md
    // Pulse: col.classList.remove('pulse'); void col.offsetWidth; col.classList.add('pulse');
  }
  wrap.classList.add('visible');
}
```

Key: the hash comparison prevents unnecessary DOM updates on every poll (poll is every 1.5s, data rarely changes). Only the `visible` class toggle runs when data is identical. Avatars use explicit `<img>` inside a `.avatar-frame` container (not `innerHTML` replacement) so the old image is hidden while the new one loads, avoiding flash.

## Backend pipeline

- `minecraft_main.py`: `update_gifter_ranking(nick, avatar_url, total_coins)` called once per completed gift event, writes to JSON
- State file: `data/gifter_ranking.json` — array of `{nick, avatar_url, total_coins, gift_count}` sorted desc by total_coins, trimmed to top 10
- Endpoint: `GET /api/stats/topgifter` returns `data[:3]`
- **Reset endpoint**: `POST /api/stats/topgifter/reset` writes `[]` to `gifter_ranking.json`. IMPORTANT: the stats blueprint is registered in `app.py` with `url_prefix='/api/stats'`, so `@stats_bp.route("/topgifter/reset", methods=["POST"])` lives at `/api/stats/topgifter/reset`, NOT `/api/topgifter/reset`. The 2026-06-24 build initially used the wrong prefix and the Reset button returned "Reset failed" with a 404 HTML page. See `python-dashboard-feature` Pattern A for the general admin-reset pattern.
- Gifter data persists across streams (no auto-reset). Only the Reset button clears it.

## Robustness requirement

Khito expects ALL new overlays to match existing ones (chat/follow) in reliability. The key failure mode caught during this session: the podium avatar `<img>` had no `onerror` handler, so when TikTok rotated the avatar URL (which happens regularly), the frame showed a tiny broken-image icon instead of a graceful fallback. Chat/follow overlays didn't have this problem because they used inline `onerror`. The fix: always use the full `onload`/`onerror` state machine from `references/avatar-display-pattern.md` for any new overlay that shows profile pictures. Never ship an overlay that shows any broken state.
