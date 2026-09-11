# Standalone Add-on Counters and Timers

Use this pattern when a game add-on needs independent OBS sources beside its main panel, such as a large numeric counter and a transient effect timer.

## Ownership

- **App-adjustable run values:** render the add-on Python state field. Never substitute a helper's lifetime Minecraft statistic for a run-scoped value corrected through app/admin commands.
- **Helper-owned transient effects:** expose rounded remaining time in the helper's immutable snapshot and read it through `/api/addons/<addon_id>/proxy/status`. The browser must not maintain or decrement a parallel timer.

## Manifest and overlay behavior

1. Add each source as a separate `overlays:` entry in the add-on manifest. The Add-ons tab discovers entries and generates copyable URLs automatically; do not hardcode them into the core Overlays panel.
2. Keep the canvas transparent and center the widget within it.
3. Use a non-overlapping poller, timestamp query, and `cache:'no-store'`.
4. Hide run counters outside active/paused state. Hide effect timers at zero or on helper failure.
5. For simple counters/timers, avoid permanent RAF and infinite CSS animation; update DOM text only when the value changes.

## Cross-runtime verification

- Test manifest discovery and authoritative field semantics.
- Test helper serialization/defaults when adding a snapshot field.
- Require HTTP 200 for every add-on overlay route.
- Verify source, `release/addons`, and `release/_internal/addons` overlay copies match.
- Build the full helper JAR and compare hashes across build output, bundled source add-on, both release copies, and the verified live Minecraft profile.
- Restart only the components whose packaged code changed, then probe the live app routes. Gameplay/visual verification remains separate from build/hash proof.
