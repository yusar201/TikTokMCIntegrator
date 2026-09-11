# Global library and action placeholders

## Verified ownership transition

The original Studio treated `page.cards` as ownership. That made Catalog imports land on one page and made Card Editor depend on page selection. The compatible transition is:

- Canonical cards: top-level `card_library`.
- Page composition: ordered `card_ids`.
- Compatibility: materialize full `page.cards` snapshots before backend save/render/export.
- Legacy migration: collect and deduplicate old page cards into the library; preserve page order.
- Customized legacy page copies can be authoritative over an uncustomized library snapshot.

Auto-pagination must partition IDs from the library. For 56 cards in a 4×6 layout, the invariant is 24 + 24 + 8 with no lost, duplicated, or cloned identities.

## Action-icon root cause

The classifier maps command behavior to intents and suggested names. The old draft path interpolated those names into `/gift-studio-assets/action-<name>.png`. No matching source files existed, so the browser rendered a broken-image indicator. Unknown/custom intents omitted the layer entirely.

The corrected contract is:

- Normal UI import requests `include_action_icon=true` and every draft receives the slot.
- Do not assign a URL unless the file is verified to exist.
- Empty action assets render a deterministic inline SVG placeholder, never `<image href="missing">`.
- JavaScript preview and Python exporters produce byte-equivalent geometry.
- Old generated `action-*.png` references normalize to `asset: ""`, `placeholder: true`.
- Explicit `include_action_icon=false` remains authoritative and must survive save/load unchanged.

## Regression boundaries discovered

- Do not augment all cards inside low-level `normalize_card`; generic renderer fixtures and deliberately gift-only cards must remain unchanged.
- Do not add placeholder layers indiscriminately on project load. Only migrate known obsolete fake URLs; normal UI imports create the universal slot at draft time.
- Keep numeric calculations numeric. Python renderer `_round()` serializes values to strings, so compute geometry using numeric helpers and format only at SVG emission.
- Test PNG and GIF exporters after renderer changes; browser-only success is insufficient.

## Verification set

- Catalog draft tests: recognized and unknown intents, explicit omission.
- Model tests: obsolete URL migration and idempotence.
- JavaScript renderer test: placeholder emits `<g data-action-placeholder="true">`, shapes, and no `<image>`.
- Python/JavaScript renderer parity.
- PNG and GIF export tests.
- Full `pytest tests/ -k gift_card_studio` plus all JavaScript Gift Studio tests.
