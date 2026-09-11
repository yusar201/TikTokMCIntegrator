# OneBlock Objective Rush — End-to-End Delivery Lessons

## Visible features are not complete at backend-only

For any user-visible Objective Rush change, completion means all applicable layers are delivered and verified:

1. Engine/service and API.
2. Dashboard controls and live state rendering.
3. OBS overlay, hidden while idle.
4. Minecraft-facing controls and feedback when requested.
5. Full PyInstaller build and deployment to `release/`.
6. Verify both root and `_internal` copies plus the release EXE timestamp.

Never tell Khito to restart the released app after changing only source routes. A restart cannot expose UI that was not built, packaged, and deployed.

## Minecraft control contract

Use the companion Forge helper as a bidirectional bridge:

- In-game `/rush start|status|fail|reroll|surrender|abort` sends an HTTP action to the Flask app.
- Dashboard and Minecraft commands mutate the same persisted engine state.
- Every newly selected objective should send both chat and center-screen title/subtitle feedback.
- Objective copy must be concrete: action + quantity + exact item/entity. Flavor names may accompany instructions but cannot replace them.

Example:

- Bad: `Climb Supply`
- Good name: `Craft 12 Ladders`
- Good description: `Craft 12 Ladders using a crafting table`

Objective definitions remain predefined in YAML. Random selection happens only after phase, capability, difficulty, recent-history, and type-streak filtering.

## Catalog quality gate

Tests should reject objectives when:

- description equals the flavor name;
- quantity is absent;
- description does not begin with an explicit verb;
- timer fields reappear in the timer-free mode.

Generate descriptions from the objective target where practical, then manually improve awkward grammar and important UX text.

## Add-on discovery boundary

An add-on directory is valid only if it contains `addon.yml` or `addon.json`. Filter at directory discovery before validating the folder name or entering exception-to-error-card logic. This prevents `__pycache__`, tooling directories, and random folders from appearing as disabled/error add-ons.

Regression fixture: create `__pycache__/`, `random-folder/`, and one valid manifest directory; assert only the manifest-backed add-on is listed.

## TikTok connection debugging after rebuilds

Do not blame a newly added feature solely because failure appeared after its rebuild. Trace the TikTok connection stages independently:

1. room ID resolution;
2. gift list retrieval;
3. Euler signed WebSocket request;
4. live-check/preflight;
5. confirmed `ConnectEvent` against a known-live account.

`JSONDecodeError: Expecting value: line 1 column 1` can come from an empty/non-JSON live-check response even when room resolution and WebSocket signing are healthy. Verify each boundary before changing hosts or usernames. If the preflight alone is flaky, `fetch_live_check=False` can bypass only that check while preserving real room/WebSocket event delivery. Confirm with a real `ConnectEvent`, not merely a non-throwing task.

Improve reconnect logs to include exception type and print a traceback when Debug Mode is enabled.
