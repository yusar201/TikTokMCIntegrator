# Objective Rush Native Minecraft Sidebar

Use when the streamer needs authoritative Objective Rush state visible in-game rather than repeatedly checking an OBS overlay or second monitor.

## Data ownership

The sidebar is a projection only. Keep Objective Rush state authoritative in the Python service/API. Minecraft must not maintain duplicate Wins, Strikes, objective selection, or progress counters.

A Forge companion may poll the existing lightweight status response and merge it with local authoritative OneBlock phase data.

## Runtime pattern

- Poll at about once per second, not every server tick.
- Perform HTTP/network work on a daemon worker thread.
- Perform all `ServerScoreboard` mutations through `server.execute(...)` on the server thread.
- Guard against overlapping polls with an `AtomicBoolean` or equivalent.
- Reuse one fixed objective ID; never create a new scoreboard objective per update.
- Capture any pre-existing sidebar objective at startup and restore it on shutdown.
- On transient app loss, show `APP OFFLINE` while retaining the last known objective values; update immediately when the app reconnects.
- Read OneBlock phase/blocks remaining directly from the Forge helper, so useful local data remains visible while the app is offline.

## Compact information contract

Stay within Minecraft's 15-line sidebar limit. Include, in priority order:

1. connection/run status;
2. Wins / target;
3. Strikes / 3;
4. objective name;
5. short description;
6. progress / target;
7. OneBlock phase;
8. blocks to next phase.

Clamp malformed negative values and truncate long text before publishing it.

## Scoreboard entry uniqueness

Minecraft identifies sidebar rows by entry string. Repeated visible text collapses into one row. Ensure every internal entry is unique by appending an invisible color-code suffix when duplicate strings occur; keep the player-visible text unchanged.

Clear the old objective's scores before writing the new ordered set, and assign descending scores to preserve top-to-bottom order.

## TDD and verification ladder

Test pure formatting and JSON parsing before runtime integration:

- active run contains all essential fields;
- idle and app-offline states are explicit;
- malformed/empty JSON safely becomes offline;
- values clamp correctly;
- no line exceeds the chosen readable width;
- duplicate visible labels remain separate entries;
- total lines never exceed 15.

Then verify the deployed server through RCON:

```text
scoreboard objectives list
scoreboard objectives setdisplay sidebar <objective_id>
scoreboard players list
```

Expected evidence:

- objective exists once;
- display slot already shows it;
- offline rows contain local OneBlock data;
- active fixture changes Wins/Strikes/objective/progress without restart;
- stopping the fixture returns to `APP OFFLINE` without restart.

## Synthetic-state hygiene

Do not start or mutate a real Objective Rush run merely to test rendering. Use a temporary local fake HTTP response with clearly synthetic state. Stop it afterward and restart or explicitly reset the controller so stale fixture values are not left visible under `APP OFFLINE`.

Forge JAR deployment still requires a Minecraft/server restart. App reconnect/disconnect after deployment must update live without a Minecraft restart.
