# OneBlock Objective Rush — in-game UX and delivery contract

## Objective semantics

Objectives are predefined catalog entries, not generated dynamically. Randomness only chooses among entries remaining after phase, capability, difficulty, recent-history, and same-type-streak filters.

Catalog copy must be self-explanatory. Every player-facing description must contain:

- a concrete verb (`Collect`, `Craft`, `Kill`, `Eat`, `Mine`, `Reach`);
- an exact quantity;
- the exact item, entity, or phase action.

Reject flavor-only descriptions and descriptions that merely duplicate the flavor name. Example:

```text
Bad:  Climb Supply
Good: Craft 12 Ladders using a crafting table
```

Add automated catalog assertions so regressions fail tests.

## Required in-game controls

A dashboard-only implementation is incomplete. The Forge companion should expose a shared command surface such as:

```text
/rush
/rush start
/rush status
/rush fail
/rush reroll
/rush surrender
/rush abort
```

Commands must invoke the same persisted Python engine as dashboard/API actions. Do not create a second Forge-side run state.

## Required objective feedback

Whenever a new objective becomes active—start, reroll, replacement after failure, or automatic completion—send both:

1. Minecraft chat with objective, instruction, Wins, and Strikes.
2. Center-screen Minecraft title/subtitle with a large concise instruction.

Recommended title pattern:

```text
NEW OBJECTIVE
Craft 12 Ladders using a crafting table
```

Forge 1.20.1 packet path:

- `ClientboundSetTitlesAnimationPacket`
- `ClientboundSetTitleTextPacket`
- `ClientboundSetSubtitleTextPacket`

Enqueue all player messaging on the Minecraft server thread.

## Delivery pitfall: backend-only is not a visible feature

Do not tell the user to restart the released app after only adding source routes or engine code. A visible feature is complete only after:

- backend/service;
- dashboard controls;
- OBS overlay if applicable;
- Forge command/effect integration when requested;
- tests;
- full EXE build and deploy;
- helper JAR build/deploy when Java changed;
- verification of files inside both release root and `_internal` packaging locations.

Only then ask the user to restart the components whose artifacts actually changed.
