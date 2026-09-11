# Minecraft Achievement-Toast Overlay Recipe

Verified 2026-06-10 on TikTokMCIntegrator (Top Gift, Top Streak, Gift Feed redesign).
This is the reusable recipe for skinning any overlay card/feed entry as a Minecraft
achievement popup ("Type: Minecraft achievement notification (toast popup)").

## Target look
- Dark gray rectangular box (`#3a3a3a`)
- Pixelated black/white beveled border (NOT a flat 1px border)
- Minecraft pixel font, retro game-UI feel
- Yellow achievement text (`#ffff55`) with a dark drop shadow
- Square (non-rounded) pixelated icons
- Choppy step-based slide-in animation, no smooth bounce/scale

## 1. Pixel font (@font-face)
```css
@font-face {
  font-family: 'Minecraftia';
  src: url('https://cdn.jsdelivr.net/npm/@south-paw/typeface-minecraft@1.0.0/files/minecraft.woff2') format('woff2'),
       url('https://cdn.jsdelivr.net/npm/@south-paw/typeface-minecraft@1.0.0/files/minecraft.woff') format('woff');
  font-display: swap;
}
:root { --font-mc: 'Minecraftia', 'Outfit', monospace; }
```
**Verify the CDN is live first:** `curl -sI <woff2-url>` → expect `HTTP/2 200` and
`access-control-allow-origin: *`. A dead font URL = invisible text on a live stream.

## 2. The pixel border (the signature look)
Do NOT use `border: 1px`. Use layered box-shadows for the beveled MC border:
```css
.mc-box {
  background: #3a3a3a;
  border: none;
  border-radius: 0;            /* sharp corners are essential */
  image-rendering: pixelated;
  box-shadow:
    0 0 0 2px #000,            /* black outer ring */
    inset 0 0 0 2px #1d1d1d,   /* dark inner line */
    inset 4px 4px 0 0 #545454, /* top-left light bevel */
    inset -4px -4px 0 0 #2b2b2b,/* bottom-right dark bevel */
    4px 4px 0 0 rgba(0,0,0,0.55); /* drop shadow */
  backdrop-filter: none;       /* kill any glassmorphism */
}
```

## 3. Achievement text
```css
.mc-title { font-family: var(--font-mc); color: #ffff55;
            text-shadow: 2px 2px 0 #3f3f00; font-weight: 400; letter-spacing: 0; }
.mc-sub   { font-family: var(--font-mc); color: #e0e0e0; font-weight: 400; }
```
`font-weight:400` always — pixel fonts have no bold weight; bolding renders blurry.

## 4. Square pixel icons
```css
.mc-icon { border-radius: 0; image-rendering: pixelated; background: #2b2b2b;
           box-shadow: inset 2px 2px 0 0 #545454, inset -2px -2px 0 0 #1d1d1d; }
```

## 5. Step-based slide-in (retro feel)
```css
@keyframes mcToastIn { 0% { opacity:0; transform:translateX(40px); } 100% { opacity:1; transform:translateX(0); } }
/* apply with steps() for the choppy MC feel: */
animation: mcToastIn 0.35s steps(4, end);
```

## 6. Neutralizing the original styling (when overriding, not rewriting)
The override block must cancel the old card's gradients/glows/animations:
```css
.tg-card::before, .tg-card::after { display: none !important; }   /* gradient border + glow */
.tg-name { -webkit-text-fill-color: #ffff55 !important; background: none !important;
           -webkit-background-clip: border-box !important; animation: none !important; }
.tg-sparkle-wrap { display: none !important; }                    /* particle effects */
```

## 7. Tier rarity → colored left pixel bar (instead of glow)
```css
.gift-tier-2 { border-left: 4px solid #55ff55 !important; }  /* green */
.gift-tier-3 { border-left: 4px solid #ff55ff !important; }  /* purple */
.gift-tier-4 { border-left: 4px solid #ffaa00 !important; }  /* orange */
.gift-tier-5 { border-left: 4px solid #ff5555 !important; }  /* red */
```

## Where this was applied
`templates/overlay.html` — appended ONE override block at the end of the `<style>`,
marked with `/* ===== MINECRAFT ACHIEVEMENT-TOAST REDESIGN ===== */ … /* ===== END ===== */`.
Touched `.tg-card` (Top Gift), `.ts-card` (Top Streak), and
`.overlay-wrap[data-type="gifts"] .gift-log-entry` (Gift Feed). Revert = delete that block.
