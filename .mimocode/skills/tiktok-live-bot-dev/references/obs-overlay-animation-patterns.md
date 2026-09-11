# OBS Overlay Animation Patterns — McPY + TikTokMC

Session-derived patterns for lightweight browser-source overlays under `C:\Users\yusar\Documents\Code\Live\McPY\overlay\`.

## Counter animation choices

Use distinct animation semantics per overlay so the visual language stays consistent without feeling copy-pasted:

- **Diamond/resource counter**: slot-machine digit roll.
  - Per-character vertical roll.
  - Up direction for gains, down direction for losses.
  - Skip unchanged digits so `11 -> 12` only rolls the last digit.
  - Keep normal gain/loss color states outside the character keyframes.

- **Win counter**: jackpot slot style.
  - Similar per-character roll, slower/gold bounce for increases.
  - Apply temporary gold only to the score span, not the whole `text-container`, otherwise `/ 20` also turns gold.
  - When `current >= goal`, make the score green like the goal text.
  - Pitfall: if keyframes set `color`, multi-digit numbers can mix colors (`1` white, `2` yellow). Fix by making `.slot-char`, `.slot-char-inner`, and inner spans `color: inherit`; control color through parent state classes only.

- **Coin/fundraiser overlay**: cash-register count tween + coin sparks.
  - Avoid per-digit slot roll for large coin jumps; it gets noisy.
  - Tween displayed value toward target using `requestAnimationFrame` + ease-out.
  - Add brief gold glow on the number and small spark particles near the coin icon on increases.
  - Avoid initial-load bursts by tracking `lastCoins = null` and only bursting when `lastCoins !== null && coins > lastCoins`.

## Implementation pitfalls

- Never color individual slot keyframes if unchanged digits must visually match changed digits.
- Scope animated state classes to the exact number span (`#curr-win`, `#current-coins`), not a shared container that also includes goal text.
- For browser-source overlays, no build step needed; edit HTML directly and tell user to refresh OBS browser source.
- If using `innerHTML` for digits, keep inputs numeric/static. For user-provided text, escape before inserting.
