# Combined Rotating OBS Overlays

Use this pattern when two compact overlays occupy similar screen space and can share one Browser Source (for example, Top Gift + Top Streak).

## Goal

Reduce baseline OBS cost by replacing two Chromium documents, pollers, and render contexts with one document and one compact API response, while preserving the settled design of both cards.

## Architecture

- Add a combined core overlay route/type, but keep the standalone routes for compatibility and rollback.
- Render both existing card DOM structures in one page. Reuse their original classes and IDs where practical so existing handlers and styling remain authoritative.
- Add only an outer stage/slot layer for presentation. Do not redesign settled typography, colors, spacing, media, or labels.
- Return both selected records from one compact endpoint payload, e.g. `{topgift: {...}|null, topstreak: {...}|null}`. Cache selection by the source log file signature so polling does not rescan an ever-growing history file.
- Poll once at the normal summary cadence. Deduplicate card rendering with stable render keys.
- If both records exist, alternate every 5 seconds. If only one exists, leave it continuously visible. Do not switch to an empty card.

## Transition recipe

A restrained 600–800 ms handoff works well:

- outgoing: slight left drift, small scale-down, 2–4° depth rotation, soft blur/fade;
- incoming: settle from the right with matching easing;
- use `transform`, `opacity`, and short-lived `filter` only;
- avoid spinning cards, hard cuts, or a full carousel redesign;
- honor `prefers-reduced-motion` with an opacity-only fallback.

Pause infinite CSS animation on inactive slots with `animation-play-state: paused !important`. If media/canvas work exists, make it lifecycle-aware too; hiding an element does not automatically stop video, RAF, or canvas processing.

## Full integration checklist

1. `routes/stats.py`: combined compact summary response.
2. `app.py`: add the type to production and demo route allowlists.
3. `templates/overlay.html`: combined branch, stage CSS, fetch mapping, dispatch handler, and switch timer.
4. `templates/index.html`: dashboard URL/preview card.
5. `static/script.js`: add type to preview lifecycle list.
6. `templates/overlay_demo.html`: either implement the same combined branch or deliberately make the demo wrapper load the production overlay. Do not merely allowlist a type that renders as an empty generic feed.
7. Tests: endpoint shape, 5,000 ms cadence sentinel, both card slots, standalone route compatibility, and template compilation.

## Verification

- Run the complete test suite and Jinja/JS syntax checks.
- Load the production combined URL and inspect DOM classes across at least two switches. Instrument the switch function or timestamps; do not infer timing from a single screenshot.
- Capture the actual OBS source through obs-websocket and verify card completeness, crop, scale, and transparency.
- Migrate safely by changing one existing source in place so its transform is preserved; disable, rather than delete, the redundant legacy source.
- Read back OBS input settings and scene-item enabled state after mutation. Some successful obs-websocket mutation responses contain no `responseData`; success must be determined from `requestStatus.result`, then verified with a separate GET.

## Production migration pattern

- Reuse the better-positioned existing source, set its URL to the combined overlay, and set the intended source dimensions.
- Preserve transform/crop/scene order.
- Rename it to the combined feature name only after settings are verified.
- Disable the second source for rollback.
- Never alter OBS sources blindly while live; validate the route first and inspect current program-scene state through obs-websocket.
