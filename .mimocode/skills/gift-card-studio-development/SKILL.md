---
name: gift-card-studio-development
description: "Use when developing TikTokMC Gift Card Studio."
trigger: "Gift Card Studio catalog imports, global card editor, page assignments, image placeholders, rendering, PNG/GIF export, project migration"
---

# Gift Card Studio Development

Production workflow for TikTokMCIntegrator's Gift Card Studio. Keep the model, browser editor, Python renderer/exporters, persistence, and old saved projects consistent.

## Core architecture

- Catalog imports into a canonical project-level `card_library`.
- Card Editor edits this library independently of page selection.
- Pages contain ordered card IDs/references. Materialized `page.cards` remain compatibility snapshots for existing backend renderers and exporters.
- Editing one global card updates every page placement that references it.
- Removing a card from a page does not delete it from the library.
- Auto-build assigns library IDs across pages; never clone independent cards.
- Normalize old page-owned projects without requiring users to recreate them.
- Preserve legacy callers that consume or mutate materialized `page.cards`; customized legacy copies may require precedence during normalization.

## Image-layer fallback rule

Never invent an asset URL for a file that has not been verified to exist. Missing `<image href>` resources show browser broken-image indicators.

For normal Catalog imports, every card receives an editable Action Icon layer. If no real action artwork exists:

- Keep `asset` empty.
- Render a built-in SVG pixel placeholder rather than an `<image>` element.
- Use the same placeholder in JavaScript preview and Python PNG/GIF rendering.
- Keep Browse/Replace, visibility, position, size, rotation, and opacity controls layer-local.
- Migrate obsolete generated references such as `/gift-studio-assets/action-*.png` to the placeholder.
- Preserve explicit `include_action_icon=false`; deliberately gift-only cards must round-trip unchanged.

Classifier intents such as `mob`, `item`, `effect`, and `explosive` may provide semantic suggestions, but classification alone is not evidence that artwork exists.

## Catalog, action text, and manual artwork contract

- Keep Catalog gift-only: it chooses gifts to import and shows only gift artwork/status. Do not expose Minecraft setup, action previews, action-match status, command parsing, or action filters.
- The selected main app profile is live Catalog context. After a successful profile switch, notify an already-loaded Studio, clear selected gift keys, and reload Catalog with `no-store`; otherwise stale keys may be imported against a different profile and legitimately produce zero cards.
- Normalize both supported profile action shapes for internal metadata: legacy command strings and typed objects such as `{"command": "...", "type": "minecraft"}`. Never use those commands to produce visible action text.
- **Visible action text comes exclusively from the selected profile's `GiftDescriptions` value.** Do not derive, repair, or fall back from command text, title commands, classifier labels, registry IDs, prior labels, or the TikTok gift name. If the description is absent, leave the action text blank. Preserve user-edited/customized card text according to the existing refresh policy.
- Every normal imported card keeps an editable Action Icon layer as an empty placeholder. The user supplies that artwork manually through layer-local Browse/Replace/upload controls.
- Do not add automatic action-artwork pulling: no Minecraft source discovery, folder picker, scanning/indexing, command-to-texture resolver, matching endpoint, selection-triggered refresh, or automatic cached action asset. Removing automation does **not** mean removing the Action Icon layer.
- Keep gift artwork and action artwork separate. Catalog/import may cache the TikTok gift icon into Studio-owned storage; it must never populate the manual Action Icon layer.
- Project management belongs beside the Studio project selector. Expose deletion with confirmation, use the project DELETE route, then load a remaining project or create a clean default when the last one is removed.
- Keep layouts dense, unclipped, keyboard-readable, responsive, and verified in dark and light themes. Follow Khito's Minecraft UI doctrine: stepped/square geometry, no glass, blur, glow, gradients, or decorative technical jargon. Gold accent text that reads on the dark theme is unreadable on the cream light theme — every new gold/secondary text element needs a `[data-theme="light"]` dark-bronze override.

## Page-assignment picker

The "Cards on this page" picker must show every library card as a rich row — gift icon thumbnail, gift name, and the card's visible action text — never a bare `<select>` of gift names alone. Picker action text follows the same doctrine as the card face: read it from the card's Main Text layer (main-role text layer first, then any text layer), never from commands, intents, or the gift name. Cards with no action text show a muted "No action text" hint, never a blank or invented line.

- Provide a filter box matching gift name and action text (every word must match), with a visible `N of M` count so filtering never reads as data loss.
- Persist row selection in workspace state across re-renders (filter typing, assign/unassign, reorder) so typing never wipes a pending selection.
- Keep rows keyboard-operable (checkbox role, Space/Enter toggles) with visible selected state in both themes.
- Square wood-framed rows per the Minecraft UI doctrine: no glass, blur, glow, or gradients.

See `references/manual-action-artwork-and-description-text.md` for the correction history and regression boundaries.

## Workflow boundaries and edit safety

- Auto-build eligibility comes from `card_library`, not existing page placements: a freshly imported, unassigned library must work.
- “All cards” exports each canonical library card once, including unassigned cards. “All pages” exports compositions. Single-card export targets a stable `card_id`, not an editor index or the first page placement.
- Card-content edits (text, geometry, visibility, added layers, uploaded/replaced artwork) must mark that card customized before saving or refreshing. Selection-only changes must not mark the project dirty. Page-layout changes must not accidentally mark the currently selected card customized.
- Catalog import operates on saved state: reconcile/save pending editor changes before importing. Verify custom text AND uploaded artwork survive save → import/refresh → reload. Do not assume old cards were correctly marked customized; inspect real data before choosing a migration.
- Ordinary Save must preserve selected page/card/layer and undo history. Capture export intent before asynchronous saving, and guard against stale responses overwriting edits made while requests are in flight.
- Reopening Studio must retain unsaved workspace state; project replacement needs an explicit unsaved-change decision. Resuming a background export needs job reconnection, not just retained job ID.
- Removal of a subsystem includes obsolete callbacks and wording: test the actual editor render path for undefined functions, not just absence of endpoints. Manual action artwork must not promise automatic resolution.
- Test complete action sequences even when component suites pass. See `references/workflow-boundary-regressions.md` for concrete reproduction recipes and verification limits.

## Testing and verification

Follow RED-GREEN-REFACTOR for behavior changes.

1. Add RED tests for the exact model and rendering behavior.
2. Test unknown intent, missing asset, obsolete fake URL migration, and explicit omission.
3. Maintain JavaScript/Python renderer parity. Renderer formatting helpers may return strings; keep numeric geometry separate from serialized formatting.
4. Run focused catalog, model, renderer parity, PNG, and GIF tests.
5. Run the full Studio Python suite: `pytest tests/ -k gift_card_studio` with the project's Windows Python.
6. Run all `tests/js/gift-studio-*.test.js` tests. Extract pure DOM-free helpers into their own ES module (the `page-composer.js` pattern) so `node --test` imports them directly — the workflow-test vm harness strips every import line, so helpers buried in `studio.js` are unresolvable there and cannot be unit-tested.
7. Pixel-check visible UI changes in dark and light themes. For Studio UI, execute the shipped JS modules in a standalone harness against the user's real saved project (real `card_library`, real gift icons inlined as data URLs), screenshot both themes via headless Chrome, and assert in-DOM row counts, action-text values, and filter results — never eyeball pixels alone.
8. For runtime regressions, inspect the user's actual released projects—not only fixtures. Identify the active project and compare `card_library`, materialized `page.cards`, stable gift key, saved commands, main text, and action asset before choosing a fix.
9. After deployment, launch the released executable and exercise its real API with the user's saved configuration. Assert that removed automatic-artwork endpoints return `404` and no automatic artwork UI or event trigger remains.
10. Verify the full released flow across at least two real app profiles: switch profile → fetch Catalog → create temporary project → import one described gift → require one library card → require a non-empty Studio-owned gift icon → require main text exactly equal to `GiftDescriptions` → require an empty, uploadable Action Icon placeholder → save/reload → delete the temporary project → restore the original active profile.
11. Include a negative description test: a gift without `GiftDescriptions` must not fall back to command text, classifier output, registry ID, or gift name.
12. Manually upload/replace an Action Icon and verify preview, persistence, and export retain it. This guards against accidentally deleting the layer while removing automation.
13. When import caches gift icons, ensure the entries passed to drafting carry the rewritten Studio-owned URL. A successful cache report alone does not prove the drafted card references the cached asset.
14. Backend/model changes require the full canonical deploy path; inspect the running app first and never interrupt an active stream.

## Execution discipline for Khito

Respect Khito's current execution choice: when he says “just do it yourself,” stop delegation setup and implement directly; leave any failed worker non-runnable to avoid concurrent writes. An expensive-model concern calls for bounded reads and focused tests, not an unsolicited orchestration detour. Do not treat an approved review as permission to silently drop the remaining items: maintain an acceptance checklist and continue until all agreed work is verified or a genuine external gate exists. A passing subset or a successful deploy is not completion of the whole review.

Do not stop after architecture confirmation or a progress explanation. Continue through implementation, regression tests, deployment, and released-artifact verification unless a genuine external gate exists. If the executable is running, finish every safe step, state only that specific deployment gate, and do not request unrelated restarts.

## Detailed references

- `references/global-library-and-action-placeholders.md` — ownership compatibility, action-placeholder cause, and verified regression boundaries.
