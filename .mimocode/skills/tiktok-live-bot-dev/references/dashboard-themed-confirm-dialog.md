# Dashboard Themed Confirm Dialog (appConfirm)

`window.appConfirm({title, subtitle, message, confirmText, tone, icon})` in `static/script.js` is the ONLY sanctioned confirmation dialog in the dashboard/Gift Studio. Native `confirm()` is banned — Khito called it ugly (2026-09-11); all 14 former native sites were converted.

## Pattern
- Reuses the Stardew close-guard shell classes (`bot-close-warning-overlay/box/corner/header/icon`) + `app-confirm-*` additions in `style.css` (overlay z-index 2100, 460px box, `.app-confirm-icon-danger` red icon variant).
- Returns a Promise<boolean>; OK resolves true, Cancel/backdrop/Escape resolve false.
- `tone: 'danger'` → `btn-danger` + red icon; otherwise `btn-warning` + gold icon (default). Buttons: `btn-ghost` Cancel / tone-colored confirm.
- For NEW confirmation prompts, always call `appConfirm`; never reintroduce `confirm()`.

## Converting sync confirm() call sites
- Inline `onclick="fn()"` callers are fire-and-forget → making `fn` async is safe.
- If the function must stay sync-declared (or patch tooling fights you), wrap the body: `function fn(){ return (async () => { ... })(); }` and add `await`-based guard: `if (!(await window.appConfirm({...}))) return;`.
- `static/gift-studio/studio.js` (ES module) calls `window.appConfirm` — it runs inside the same dashboard page.
- Cache-bust after edits: `style.css?v=N`, `script.js?v=N` in `templates/index.html`, and `gift-studio/studio.js?v=N` in the dynamic `import()` inside script.js.

## Verification (real-pixel doctrine)
Headless Edge on extracted-real-CSS + extracted-real-impl harness: assert computed styles (z-index 2100, boxBorder rgb(139,90,43), ok button rgb(232,116,92) dark / rgb(217,97,76) light, title font Chakra Petch) AND PIL pixel-sample the screenshot (wood/gold/danger token counts > threshold in BOTH themes). Probe promise behavior via `--dump-dom` + `document.title` JSON (resolved true/false, overlay closed, dialog reuse, tone class switch).