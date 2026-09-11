# OneBlock Objective Rush — End-to-End Control Loop

Use this when adding or extending Objective Rush. A backend engine alone is not a playable feature.

## Required vertical slice

A shippable control loop includes all four layers:

1. **Authoritative Forge helper**
   - Session-monotonic counters for crafted outputs, player-attributed kills, and completed item use.
   - Inventory and OneBlock phase/counter snapshots.
   - In-game `/rush` commands that call the app, not a second independent game engine.
   - A helper endpoint that accepts app announcements and emits Minecraft chat feedback.

2. **Persistent Python engine/service**
   - One shared state for dashboard and in-game commands.
   - Baseline/delta progress, phase/capability filtering, anti-repeat selection, Wins/Strikes/Finale.
   - Atomic state persistence and idempotent completion.
   - Polling keeps the run intact while the helper is temporarily offline.

3. **Visible dashboard + OBS overlay**
   - Dashboard controls: Start, Status, Fail, Reroll, Surrender, Abort.
   - Current objective, progress, Wins, Strikes, helper connectivity.
   - Add-on overlay under `addons/oneblock/overlays/`, hidden while no run is active.

4. **Build and deployment**
   - Build/deploy the Forge JAR to the active OneBlock instance.
   - Run the bot's `./deploy.sh --full` for Python/backend changes.
   - Verify released add-on, static files, overlay, EXE timestamp, and JAR hashes.
   - Only then instruct the user to restart both Minecraft and TikTokMCIntegrator.

## Minecraft command contract

Commands:

```text
/rush
/rush start
/rush status
/rush fail
/rush reroll
/rush surrender
/rush abort
```

The Forge command handler should make an asynchronous localhost HTTP request to the app and post the result back onto the Minecraft server thread. Never block the server tick thread on HTTP.

## Announcement contract

Whenever start, reroll, failure, or automatic completion selects a new objective, the Python service sends an announcement to the helper. Minecraft chat should show:

```text
[OBJECTIVE] <name> — <description>
Wins X/10 | Strikes Y/3
```

Announcements are best-effort: failure to display chat must not destroy or roll back the persisted run.

## Workflow pitfall: backend-complete is not user-visible complete

Do not tell Khito to restart/test after adding only routes or engine code. He expects a visible, playable artifact. Before saying a feature is shipped, verify:

- dashboard controls exist in the released UI;
- OBS overlay route returns 200;
- in-game command exists in the deployed Forge JAR;
- new objectives produce Minecraft chat feedback;
- both release targets were actually rebuilt and deployed.

A Flask test-client success proves the API, not the released EXE or the user experience.

## TDD checkpoints

- API start chooses and announces an objective.
- Reroll/failure announce the replacement objective.
- `/ingame` actions mutate the same engine state as dashboard endpoints.
- Helper disconnect preserves active state.
- Completion is exact-once and selects/announces the next objective.
- Every real OneBlock phase sustains a complete 10-Win run without invalid selections.
