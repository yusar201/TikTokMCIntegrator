# Gift Studio workflow regression recipes

## Why component tests are insufficient
A review found real frontend/backend boundary failures while the existing Python and JavaScript suites were green. Add action-sequence tests, not merely source-string assertions.

## Reproduction matrix

1. **Fresh import:** library contains cards, every page has empty card_ids. Auto-build must populate pages without demanding another import.
2. **Canonical export:** library A/B, A placed on two pages, B unassigned. All-cards estimate is two; exporter visits A and B once each. Single-card export can target B. Page exports retain both placements.
3. **Dirty selected-page export:** select page two, edit, Generate. Assert actual POST settings still target page two after Save resolves.
4. **Refresh protection:** edit main text and upload action artwork; save; re-import the gift; reload. Both manual values survive. Test page edits separately so they do not protect unrelated cards.
5. **Selection:** selecting card/layer changes selection only, not dirty state or undo history.
6. **Save:** preserve selection and history. Also exercise delayed save response while user edits or changes project; never overwrite newer state blindly.
7. **Lifecycle:** leave and reopen Studio with unsaved work and with a running job. Test recovery and error paths through actual event bindings.
8. **Export controls:** if two selectors temporarily coexist, supported option sets must agree. Assigning an absent option such as pages can empty a select value. Consolidation needs interaction tests, not just matching labels.
9. **Preview completion:** ZIP exports are downloads, not image URLs. Do not insert ZIP bytes into an img preview.
10. **Removed automation:** opening/editing a card must not call removed resolveCurrentCard logic. Clearing manual artwork should say placeholder/clear, not promise automatic artwork.

## Efficient probes
A Node vm harness can evaluate the real Studio controller with DOM and fetch boundaries stubbed, then assert real outgoing payloads and state transitions. Keep actual model/page-composer/history functions where practical. Add targeted Python exporter-selection tests separately from real PNG/GIF decoding tests.

Do not let a test stub renderAll and then claim it verifies rendering, binding, or undefined callbacks. A dummy byte payload verifies selection only, not a valid PNG. Add browser interaction and real raster/export verification for those claims. A missing-function ReferenceError in test setup is not a valid RED assertion for unrelated behavior.

## Verified boundaries versus remaining work
The session exercised fixes for canonical library export selection, fresh-library Auto-build, dirty-state selection, save target preservation, customized marking, and saving before import. Undo/lifecycle changes had weaker interaction coverage; export-panel consolidation and targeted rendering were not completed. Treat these as acceptance checks requiring current verification, not as finished implementations or proven performance improvements.
