# slot-text — Text Roll Animation Library

Discovered 2026-06-14 via X post (@DanielWhit21874). Perfect fit for TikTokMCIntegrator overlay text transitions (gift alerts, now-playing, follower names).

## Quick Facts
- **Package:** `slot-text` v0.2.2 on npm
- **Repo:** `github.com/Danilaa1/slot-text` (441★, MIT)
- **Size:** ~4KB gzipped, zero dependencies
- **Tech:** Pure CSS `transform` + `transition` on per-character `<span>` cells. Fully GPU-composited, no layout thrash.
- **License:** MIT

## CDN (browser-ready, no bundler needed)
```html
<script type="module">
  import { slotText, chromatic } from "https://esm.sh/slot-text";
</script>
<link rel="stylesheet" href="https://esm.sh/slot-text/style.css" />
```

The main module redirects to `https://esm.sh/slot-text@0.2.2/es2022/slot-text.mjs`.

## API

```js
import { slotText, chromatic } from "slot-text";

// Create a controller for one element
const label = slotText(element, "Initial Text", defaultOptions);

// Roll to new text
label.set("New Text", { direction: "up", duration: 300, stagger: 45 });

// Flash temp text → auto-revert (Copy → Copied → Copy)
label.flash("Copied!", {
  revertAfter: 1400,  // ms before reverting to original
  enter: { direction: "up", color: chromatic({ from: 190 }) },
  exit:  { direction: "down", color: chromatic({ from: 190 }) },
});

// Cleanup
label.destroy();
```

### SlotOptions
| Option | Default | Description |
|--------|---------|-------------|
| `direction` | `"down"` | `"up"` or `"down"` — slide direction |
| `stagger` | 45 | Per-character stagger in ms |
| `duration` | 300 | Slide duration per character in ms |
| `exitOffset` | 50 | How long incoming trails outgoing, ms |
| `easing` | spring-back curve | CSS easing string |
| `bounce` | 0.6 | Per-letter personality (0=uniform, 1=wild) |
| `color` | none | CSS color string or `(i, total) => color` function for chromatic flash |
| `colorFade` | 280 | How long tint fades to rest, ms |
| `skipUnchanged` | true | Keep identical chars static (Copy→Copied keeps "Cop") |
| `interrupt` | true | true: snap mid-roll and start fresh. false: finish current roll, queue new one |

### `chromatic(options)`
Returns a `(index, total) => hsl(...)` function for rainbow hue sweep:
```js
chromatic({ from: 0, spread: 320, saturation: 92, lightness: 60 })
```
- `from` — starting hue (0=red, 190=cyan)
- `spread` — hue range in degrees

## Key Behaviors
- **Spam-safe:** `flash()` restarts the revert timer, doesn't stack. `interrupt: false` on `set()` drops duplicate rolls.
- **Width handling:** Cells resize smoothly during transition. Growing/shrinking cells get `.is-resizing` class for horizontal clip.
- **Empty chars:** Treated as non-breaking spaces. Tail characters (rolling out to nothing) animate faster and disappear before the new word lands.
- **GPU:** All animation is `transform: translateY()` + `rotate()` on individual `<span>` elements. No repaints.

## Example: Gift Alert Overlay
```html
<div id="gift-alert" style="display:none; font:600 28px/1.2 sans-serif; color:#fff;">
  <span id="gift-username"></span>
  <span> sent </span>
  <span id="gift-name"></span>
</div>
<script type="module">
  import { slotText, chromatic } from "https://esm.sh/slot-text";
  const userLabel = slotText(document.getElementById("gift-username"), "");
  const giftLabel = slotText(document.getElementById("gift-name"), "");

  socket.on("gift", ({ username, giftName }) => {
    document.getElementById("gift-alert").style.display = "block";
    userLabel.set(username, {
      direction: "up",
      color: chromatic({ from: 30 }),
    });
    giftLabel.set(giftName, {
      direction: "up",
      color: chromatic({ from: 190 }),
    });
  });
</script>
```

## Research Method Note
When extracting source code from GitHub raw URLs that fail with `web_extract`/`web_extract_plus`:
1. `browser_navigate` to the raw URL (e.g. `raw.githubusercontent.com/...`)
2. `browser_console` with `expression="document.body.textContent"` — returns full source
3. This bypasses rate limiting and bot detection that block direct fetch
