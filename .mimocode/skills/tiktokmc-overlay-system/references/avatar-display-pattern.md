# Avatar Display in Overlays — TikTok URL Expiry Pattern

TikTok profile picture URLs expire/rotate regularly (typically every few hours to days). Any overlay that displays user avatars MUST handle this gracefully — never show a broken-image icon or tiny empty frame.

## The Pattern (used by chat, follow, podium)

```javascript
const frame = document.getElementById('av-1');
const img = frame.querySelector('img');
const fb = frame.querySelector('.avatar-fallback');

// ALWAYS set fallback text first (prevents flash of empty/`?`)
const initial = (nickname || '?').charAt(0).toUpperCase();
if (fb) fb.textContent = initial;

if (avatar_url) {
  // Image starts hidden — only show on successful load
  img.onload = function() {
    this.style.display = '';       // show the loaded image
    if (fb) fb.style.display = 'none';  // hide fallback
  };
  img.onerror = function() {
    this.style.display = 'none';   // hide broken image
    if (fb) fb.style.display = ''; // show fallback letter
  };
  img.src = avatar_url;
  img.style.display = 'none';      // always start hidden
  if (fb) fb.style.display = '';   // show fallback while loading
} else {
  // No URL at all — show fallback permanently
  if (img) { img.style.display = 'none'; img.onerror = null; img.onload = null; }
  if (fb) { fb.textContent = initial; fb.style.display = ''; }
}
```

## State Machine

onload → show img, hide letter
onerror (or no URL) → hide img, show letter

## Why start img hidden + show on onload?

If you set `img.style.display = ''` upfront and the URL is dead, the browser still shows a tiny broken-image icon in the corner of the frame before the `onerror` fires (or it never fires if the browser caches a 404). Starting hidden prevents this visual glitch entirely.

## Why always set initial letter?

TikTok sets `display_id` / `nickname` reliably — it's the `avatar_url` that expires. Always having the first letter as the fallback means the frame is never empty, regardless of the image state.

## Which overlays need this?

- **topgifter** (podium) — uses this full pattern since 2026-06-24 fix
- **chat** — uses `onerror="this.style.display='none'"` inline, less explicit but functional
- **follows** — uses `onerror` to toggle to `<i>` icon fallback
- **gifts** — gift icons, not user avatars (different CDN domain, same expiry risk)

If adding a new overlay that shows user profile pics, follow the full pattern above, not the inline `onerror` approach.
