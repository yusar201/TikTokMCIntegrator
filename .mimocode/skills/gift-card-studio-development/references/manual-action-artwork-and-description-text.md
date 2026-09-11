# Manual action artwork and description-only text

## Durable product decision

Gift Card Studio cards separate three concepts:

1. **Gift identity/artwork** — comes from the profile Catalog and may be cached into Studio-owned storage.
2. **Visible action text** — comes only from the selected profile's `GiftDescriptions` entry.
3. **Action artwork** — remains an editable Action Icon layer, but the user supplies its image manually.

Commands remain internal action metadata where other app behavior needs them. They must not generate or override Studio display text.

## Removed automation boundary

The automatic Minecraft artwork workflow was intentionally removed. Do not restore source discovery, folder selection, JAR scanning, texture indexing, registry matching, resolver routes, selection-triggered matching, or automatic action-asset caching unless Khito explicitly reverses this decision.

The Action Icon layer itself was **not** removed. New cards should contain it with `asset: ""` and `placeholder: true`, and the normal layer upload/replace controls must accept it.

## Regression checks

- A described gift's role=`main` text equals its `GiftDescriptions` value exactly.
- A gift with no description has blank action text; no fallback appears.
- A fresh import has a real gift icon and an empty manual Action Icon placeholder.
- A manually uploaded action icon survives save/reload and export.
- Automatic artwork endpoints return `404` and the Card Editor has no Minecraft setup/match controls.
- Changing the main profile clears selected Catalog keys and reloads profile-specific gifts/descriptions.

## Pitfall that caused rework

Do not interpret “remove action icon pulling” as “remove the action-icon layer.” Confirm the boundary between removing automation and removing the editable data/UI primitive. Here the user wanted automation gone but manual composition preserved.
