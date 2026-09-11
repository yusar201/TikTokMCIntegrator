# Offline Gift Action Simulation

## Purpose and boundary

The Gifts-tab simulator tests a configured gift without fabricating a TikTok protobuf event. It should exercise the same action dispatcher as a completed live gift while avoiding fake stream state.

Run:

1. `Gifts.GlobalActions`
2. Every action configured under the selected exact gift key

Use the real dispatcher so Minecraft, sound, webhook, and random actions follow production behavior. Do not duplicate action-type logic in the route.

Do **not** write gift history, points, rankings, streak state, overlay entries, or gift-event analytics. Simulation is an action test, not a fake ingestion event.

## Context contract

Build the same completed-gift template context:

- `{mc}` from the current profile's `Settings.MinecraftUsername`
- `{user}` from a dedicated operator input
- `{amount}` and `{repeat_count}` from a validated whole-number input
- `{gift_name}` and `{gift_id}` from the selected exact key/catalog row
- `{total_coin}` = amount × catalog diamond count
- `{asset_url}` empty unless the simulator deliberately gains an asset test

Validate that the gift key exists and is not `GlobalActions`; require non-empty user and a bounded positive amount.

## Execution architecture

- Backend endpoint live-reads the active profile config per request.
- Build a dashboard-side Minecraft sender from the current connector settings (RCON, Forge, or ServerTap).
- Invoke `execute_actions` for global and gift-specific batches. Preserve existing action concurrency rather than serializing Minecraft commands.
- Return counts/status for operator feedback; connector failures must be visible in the simulation console and HTTP response.

## Picker UX

- Use configured gift keys, not names, as values.
- Show a compact icon plus name and subtle exact ID because TikTok has duplicate names.
- Keep the dropdown tall enough to browse. The Gifts theme applies `overflow:hidden` to cards, so a custom absolutely positioned list needs a specific `overflow:visible` override and stacking context.
- Missing icons use a compact fallback symbol.

## Verification

1. Unit-test context substitution and validation.
2. Exercise the real dispatcher with deterministic random selection and intercepted sound/Minecraft outputs.
3. Confirm global plus gift-specific batches both run.
4. Verify the Flask endpoint rejects an unknown key without causing actions.
5. Pixel-check the closed picker and open scroll list in dark/light themes.
6. Verify released assets/cache-busters, launch the released executable, check `/health`, and exercise endpoint validation.
7. Stop temporary servers and verify their test ports are released.
