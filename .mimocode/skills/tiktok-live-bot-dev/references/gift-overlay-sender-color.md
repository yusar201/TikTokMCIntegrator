# Gift overlay sender-name color

Session learning: when the user asks to change the **gift overlay** text like `user sent Rose`, the OBS/browser-source renderer is in `templates/overlay.html`, not just the dashboard gift log in `static/script.js`.

## Where to edit

- `templates/overlay.html`
- Function: `renderGiftEntry(entry)`
- Line/section: generated `.gift-meta` markup

## Pattern

Wrap only the escaped sender:

```html
<div class="gift-meta"><span class="gift-sender">${esc(entry.sender)}</span> sent ${entry.repeat_count||1}x = <strong>${entry.total_coins||0}</strong> coins</div>
```

Add scoped CSS in the gifts overlay CSS block:

```css
.overlay-wrap[data-type="gifts"] .gift-log-entry .gift-sender {
  color: #55ffff !important;
  text-shadow: 1px 1px 0 #003f3f;
}
```

## Pitfall

`static/script.js` has a similar Recent Gifts renderer for the dashboard. For overlay/browser-source requests, update `templates/overlay.html` first. Dashboard-only changes will not affect the OBS overlay.
