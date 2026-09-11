# Portable Minecraft asset resolution

## Goal

Turn locally installed vanilla/mod artwork into portable Gift Card Studio Action Icon assets without hard-coding a machine path or leaving projects dependent on an external instance.

## Validated architecture

```text
configured gift commands
  -> extract exact registry IDs
  -> installation-level selected source
  -> one on-demand index of version/mod JARs
  -> confidence-gated match
  -> deterministic copy into Studio-owned assets
  -> Action Icon layer or editable placeholder
```

### Source discovery and persistence

- Discover candidates from runtime environment variables and launcher conventions; never embed a developer path.
- Accept an instance folder or game JAR through the native folder picker.
- A candidate is valid only when at least one bounded JAR contains recognized `assets/<namespace>/textures/{item,block,entity}/...png` members.
- Save source settings atomically under the Studio data root. Invalid replacement attempts must not overwrite the last valid setting.
- Store no external source path in project/card data.

### Catalog/Editor boundary (Khito correction, 2026-09-03)

Catalog stays gift-only. Action-artwork concerns begin when a gift enters the Card Editor:

- Catalog API must not call the resolver; a contract test asserts the resolver throws if the Catalog endpoint touches it, and imported cards keep `asset: ""` + placeholder until the editor resolves them.
- `POST /minecraft-assets/resolve` resolves one card's commands on demand and returns `{match: {status, confidence, asset_url, registry_id, message}}`.
- The frontend loads Minecraft status lazily on first Card Editor open (`state.minecraftLoaded`), resolves only the currently selected card (per-card dedupe key), and re-resolves on source change/rescan or explicit **Match current card**.
- Catalog rows render gift icon + gift status only; the action-match filter options and icon-pair markup belong to the editor flow.

### Index and resolution

- Bound the number of scanned JARs and extracted member size.
- Catch corrupt/unreadable JARs individually, count warnings, and continue scanning usable archives.
- Index keys as `<namespace>:<kind>/<texture-path>` and retain archive/member provenance internally.
- Parse namespaced IDs such as `minecraft:golden_apple` from commands; support conservative vanilla shorthand for known command positions such as `give`.
- Exact item match: eligible for automatic use.
- Nested/ambiguous entity skin or block match: suggestion only unless a renderer produces a verified icon.
- Build the index once per catalog operation. Do not reopen every JAR separately for every catalog row.

### Portable cache

- Copy accepted PNG bytes into `data/gift_card_studio/assets/` using a sanitized semantic stem plus a deterministic source/member digest.
- Reuse the same cached filename on repeat resolution.
- The card layer receives only `/gift-studio-assets/<cached-name>.png`; exports therefore use the existing same-origin inlining pipeline.
- Missing/unconfigured/suggested matches keep `asset: ""` and the standard action placeholder.

## API/UI shape

Recommended local API surface:

- `GET /minecraft-assets/status`
- `GET /minecraft-assets/detect`
- `POST /minecraft-assets/source`
- `POST /minecraft-assets/browse`
- `POST /minecraft-assets/rescan`

Catalog entries expose an `action_match` verdict (`matched`, `suggested`, `missing`, or `unconfigured`), confidence, optional registry ID, human-readable message, and a Studio-owned `action_asset_url` only for accepted matches.

The Studio loads status only on activation. Selecting or rescanning a source refreshes the catalog so thumbnails and match filters update immediately.

## Regression and live verification

1. RED tests for environment-based discovery, manual validation/persistence, exact vanilla + mod indexing, corrupt-JAR continuation, deterministic caching, unavailable mod fallback, and absence of developer-specific literals.
2. Catalog test that a verified cached URL reaches the Action Icon layer and clears its placeholder flag.
3. Route tests for unconfigured status, detection, validation errors, and catalog-import propagation.
4. Frontend contract tests for guided controls, route usage, action-match rendering, and lazy activation.
5. Full Windows-Python Studio suite: `python -m pytest tests/ -k gift_card_studio -q`.
6. All Gift Studio JavaScript tests plus `node --check` on changed modules.
7. Real integration probe against a temporary data directory: scan a real selected JAR, resolve a known registry ID such as `minecraft:golden_apple`, and assert the cached file exists. Never write this probe's selected path into production settings.
8. Real-browser dark/light screenshots plus computed-style/geometry checks; verify the source card and catalog rows remain inside the viewport.
9. Backend changes require canonical full deployment. Verify root EXE freshness, loose and `_internal` frontend copies/hashes, absence of a nested release directory, and stop all temporary servers/processes.

## Pitfalls

- A path verified on the developer machine is evidence, not portable configuration.
- Do not expose raw archive details in the normal UX.
- Do not classify a generic `item`/`mob` intent as proof of a specific texture.
- Entity PNGs are usually UV skin sheets, not ready-to-use icons.
- Avoid a scan-per-card implementation; it multiplies ZIP I/O across large catalogs.
- Do not claim visual completion from DOM/contract tests alone; inspect actual pixels in both themes.
