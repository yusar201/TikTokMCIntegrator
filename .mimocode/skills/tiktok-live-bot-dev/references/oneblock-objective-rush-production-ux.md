# OneBlock Objective Rush — Production UX and Event Contract

Use with `oneblock-objective-rush-design.md` when shipping or modifying the complete player-facing feature.

## Product semantics

- Objectives are predefined catalog entries; randomness only selects from the eligible filtered pool.
- Player copy must begin with a concrete verb and name the amount plus exact item/entity/action. Flavor labels cannot carry the instruction. Example: replace `Climb Supply` with `Craft 12 Ladders` and `Craft 12 Ladders using a crafting table`.
- A visible feature is not complete at backend level: ship dashboard controls, OBS presentation, in-game controls, and released artifacts together.

## Shared controls

The dashboard/API and Minecraft commands control the same persisted run:

```text
/rush
/rush start
/rush status
/rush fail
/rush reroll
/rush surrender
/rush abort
```

Action presets in `addons/oneblock/actions.yml` should reflect the current `/rush` command surface. Remove obsolete mechanics from the preset list instead of retaining historical commands just because they still exist.

## New-objective and transition feedback

Every newly active objective must provide:

- Minecraft chat: concrete name/instruction plus Wins and Strikes;
- title: event label;
- subtitle: concrete instruction;
- OBS overlay state update.

Typed transition events should be preserved end-to-end rather than collapsed into a generic announcement:

| Kind | Title | Suggested particles | Suggested sound |
|---|---|---|---|
| `objective` | NEW OBJECTIVE | enchant | XP pickup |
| `completed` | OBJECTIVE COMPLETE | happy villager | player level-up |
| `failed` | OBJECTIVE FAILED | angry villager | villager no |
| `rerolled` | OBJECTIVE REROLLED | portal | Enderman teleport |
| `victory` | RUSH COMPLETE | firework + totem | challenge complete |
| `surrendered` | RUN SURRENDERED | smoke | beacon deactivate |
| `aborted` | RUN ABORTED | smoke | beacon deactivate |

Python owns transition semantics and sends `kind`; the Forge helper owns Minecraft rendering/effects. Completion should announce before selecting/announcing the next objective. Victory is terminal and must not announce another objective.

## Overlay consistency

Objective Rush should visually inherit the OneBlock Status overlay rather than form a disconnected design:

- same pixel frame, dark/green palette, typography, shadows, and progress gradient;
- compact corner-safe dimensions;
- hidden while no run is active;
- entrance animation and a short pulse when objective instance changes;
- smooth progress interpolation without moving the primary card anchor.

## Add-on discovery rule

A directory under `addons/` is an add-on only when it contains `addon.yml` or `addon.json`. Filter at the discovery boundary before ID validation. Never turn `__pycache__`, tooling, docs, random folders, or runtime artifacts into disabled/error add-on cards.

## Verification

- Focused Python engine/API/add-on tests pass.
- Forge helper compiles.
- Exact helper JAR is deployed to the Minecraft instance and bundled add-on; compare hashes.
- Verify objective overlay and helper JAR in both `release/addons/...` and `release/_internal/addons/...` after canonical deployment.
- Fully restart Minecraft to load helper-code changes; refresh the OBS browser source for overlay changes.
