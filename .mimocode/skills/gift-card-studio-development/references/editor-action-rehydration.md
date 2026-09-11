# Card Editor action rehydration

## Failure class

A project card can outlive the gift-action configuration from which it was imported. If Card Editor trusts only the saved card snapshot, missing or stale `action_ref.commands` causes action-label fallback to the TikTok gift name. That also prevents registry-based artwork resolution even though the live mapping is correct.

Concrete regression shape:

- Gift identity: `9463`, display name `fairy wings`.
- Current action commands include `give {mc} minecraft:golden_apple {amount}` and a title ending in `Golden Apple`.
- Broken editor displays `Fairy Wings` and leaves Action Icon unresolved.
- Correct editor preserves the Fairy Wings gift badge while displaying `Golden Apple` as action text and resolving the golden-apple action icon.

## Repair contract

1. Card Editor sends the stable gift mapping key with saved commands and current label.
2. The resolve endpoint builds the current gift catalog from live configuration and looks up that key.
3. If found, live commands replace stale/empty snapshot commands for resolution.
4. Action label priority is: classifier title label → suggested action main text → configured description → submitted prior label.
5. Response includes both the artwork match and normalized action metadata.
6. Browser updates `card.action_ref`, the role=`main` text layer, and—on an exact match—the Action Icon asset.
7. Trigger this on initial editor entry and every card-selection change. Do not require the artwork source to be ready before rehydrating text/action semantics.
8. Do not rewrite `gift_ref.name`; gift identity and action semantics are separate.
9. Do not move action metadata or artwork controls into Catalog.

## Launcher split-storage pitfall

A selected modpack directory may not contain vanilla assets. CurseForge commonly stores profile mods in `minecraft/Instances/<name>/mods` and vanilla game JARs in sibling `minecraft/Install/versions/<version>/<version>.jar`. Scanning only the instance can return thousands of mod textures yet zero `minecraft:` entries, making exact commands such as `give ... minecraft:golden_apple` fail despite apparently healthy scan totals.

Treat the chosen instance as a launcher context: include its bounded, recognized shared vanilla-version location without hard-coding a username or drive. Verify the resulting index contains the expected `minecraft:item/<id>` target, not merely a large asset count.

## Profile/action-shape failure class

The dashboard profile and Studio project are independent selectors, but the Studio Catalog must always reflect the currently active dashboard profile. A loaded Studio can retain old Catalog rows across a profile switch; importing those stale selected keys runs against the new live configuration and may add zero cards. Clear selections and reload the Catalog immediately after profile switching.

Profiles also contain two valid Minecraft-action representations:

- plain strings: `give {mc} minecraft:golden_apple {amount}`
- typed objects: `{"command": "diamondpick {mc} {amount}", "type": "minecraft"}`

Normalize both before classification, drafting, rehydration, and artwork matching. Ignore sound/webhook/random objects for Minecraft semantics. Mixed symptoms—some gifts show correct action text while others show only gift names—are a strong signal that typed action objects were dropped.

## Regression coverage

- Endpoint test: submit `gift_key=9463`, empty commands, and label `fairy wings`; assert resolver receives the live `give ... minecraft:golden_apple` command and `Golden Apple` label.
- Assert response returns refreshed action commands and label.
- Existing one-card resolver tests must continue passing without a gift key, preserving backward compatibility.
- Add a launcher-layout test where the instance contains only a mod texture and vanilla `golden_apple.png` exists in the launcher's shared version directory; require both assets in the scan.
- Test the card-selection trigger separately from endpoint correctness. A passing endpoint fixture does not prove the active editor calls it.
- Add classifier/catalog coverage for typed Minecraft action objects and require their command/title fields to produce action text and registry targets.
- Test dashboard profile-switch notification, Studio Catalog reload, and stale-selection clearing.
- Inspect real saved projects when reproducing: stale projects can have empty commands and gift-name text even when another similarly named project is already repaired.
- Exercise a fresh temporary project through real released routes: import one gift with page assignment enabled, require populated `card_library` and `page.cards`, a Studio-owned gift-icon URL, normalized commands, and action-derived main text; delete the temporary project and restore the original profile.
- Run the focused endpoint tests, full Gift Card Studio route/catalog/asset/frontend-contract selection, and JavaScript syntax checks.
- Backend changes require a full deploy; bump both the dynamic Studio module query version and its parent script query version, then verify loose and `_internal` released frontend copies.
