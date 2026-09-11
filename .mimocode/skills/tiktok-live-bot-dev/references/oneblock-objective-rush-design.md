# OneBlock Objective Rush — Phase-Aware Design and Runtime Contract

Use this reference when designing, implementing, or testing randomized objectives for the TikTokMCIntegrator OneBlock add-on.

## Context discipline

Before answering “what next?” for TikTokMCIntegrator or OneBlock, recall the active profile/project state. Do not import similarly named work from another project. If unclear, search prior sessions for `OneBlock`, `Objective Rush`, and `addons/oneblock` before recommending work.

## Locked game model

- Persistent OneBlock world is the arena/resource source, not the victory score.
- Default run target: **10 Wins**.
- The final Win must come from a Finale objective.
- Existing world, inventory, and phase persist between runs.
- Objective progress uses an authoritative baseline captured when the objective starts.
- V1 has **no objective timer** and no time-based TikTok modifiers.
- An objective remains active until completed, manually failed, rerolled, invalidated, surrendered, or aborted.
- Failure adds a Strike. Current draft: 3 Strikes removes 1 Win (floor 0) and resets Strikes; keep configurable until play-tested.

## V1 objective classes

Keep these because they have reliable verification:

- `collect_item`: inventory gain after baseline, preserving peak credited progress if the item is later spent.
- `craft_item`: actual crafted-output counter delta; inventory movement/loot does not count.
- `kill_mob`: player-attributed kill counter delta; environmental/passive deaths do not count.
- `use_item`: completed item-use/consume counter delta.
- `mine_oneblock`: authoritative OneBlock counter delta.
- `reach_next_phase`: authoritative phase-ID change.

Defer survival, no-damage, and place/build objectives. Build verification requires region/pattern/provenance/cleanup semantics and is not suitable for the first reliable version.

## Correct selection pipeline

Randomness chooses only among objectives already proven eligible:

```text
helper capabilities + current phase snapshot
→ tracker-capability filter
→ phase/resource/mob/recipe eligibility
→ Win-based difficulty filter
→ recent-ID exclusion
→ same-type streak guard
→ weighted random selection
```

Never randomly choose first and validate afterward.

## Source of truth for phase availability

Inspect the installed OneBlock mod JAR rather than guessing. For Forge OneBlock `2.6.0.1`, primary phases are:

```text
datapacks/oneblock/data/oneblock/oneblock/phases/00.json ... 13.json
```

Each phase contains weighted block/mob/gift entries. Use these tables to map:

- collection resources;
- hostile mobs suitable for kill objectives;
- materials that justify conservative craft eligibility.

Record the source mod/version in the catalog. Reinspect after OneBlock upgrades.

## 10-Win difficulty curve

| Wins before round | Pool |
|---:|---|
| 0–1 | Easy |
| 2–3 | Easy + Medium |
| 4–6 | Medium |
| 7–8 | Medium + Hard |
| 9 | Finale only |

## Forge helper contract

Expose:

```text
GET /objective/capabilities
GET /objective/snapshot
```

Snapshot includes:

- player UUID/name, alive state, dimension, inventory totals;
- session-monotonic `crafted`, `kills`, and `used` counters;
- OneBlock counter, phase ID, phase progress, and blocks left.

The helper reports facts only. Python owns objective selection, baselines, progress, Wins, Strikes, rerolls, and terminal state.

### Forge event semantics

- Craft: `PlayerEvent.ItemCraftedEvent`; increment by crafted output stack count.
- Kill: `LivingDeathEvent`; count only when damage-source entity is `ServerPlayer`.
- Use: `LivingEntityUseItemEvent.Finish`; count completed uses only.
- Counters are server-session monotonic; the engine calculates `current - baseline`.
- Inventory snapshots alone cannot prove crafting, kills, or consumption.

### Live verification protocol

After deploying a helper JAR, fully restart Minecraft (world switching is insufficient), load the OneBlock world, then isolate each tracker:

1. Query capabilities and initial snapshot.
2. Craft a known output (e.g. 4 sticks); verify exact crafted count.
3. Consume one item; verify `used +1`.
4. Record current mob kill baseline, kill exactly one more personally, verify `kills +1`.
5. Record OneBlock counter, mine once, verify counter `+1`, blocks-left `-1`, and phase progress update.

Do not expect counters to start at zero if gameplay occurred earlier in the same Minecraft session. Baseline/delta behavior is the intended contract.

## Pure Python engine boundaries

Keep Phase 1 independent from Flask/TikTok/Minecraft networking:

```text
objective_models.py   # serializable run/instance/result models
objective_catalog.py  # eligibility and weighted choice
objective_engine.py   # transitions and progress evaluation
objective_store.py    # atomic JSON persistence
```

Required invariants:

- one active objective maximum;
- completion is idempotent;
- terminal runs reject further scoring;
- Wins never drop below zero;
- free reroll adds no Strike;
- final objective at `wins == target - 1` comes from Finale pool;
- save active baseline, progress, recent IDs/types, score, and instance ID;
- persist via temporary file plus `os.replace`.

## TDD and simulation validation

Use failing tests before engine implementation. Cover every tracker delta, peak collect progress, scoring, Strike threshold, reroll, Finale, terminal idempotency, capability filtering, bad snapshots, and restart restoration.

For catalog simulation:

- fixed seed;
- every real phase `00–13`;
- complete 10-Win runs;
- Finale always final;
- no recent-window duplicates;
- same-type streak never exceeds cap;
- no dead-end eligible pool in any phase.

A small simulation can miss rare pool exhaustion. Run a deeper all-phase pass (e.g. 1,000 runs per phase) before approval. Phase-exclusive objectives correctly receive zero picks outside their phase; this is not a coverage failure.

## Current implementation locations

```text
addons/oneblock/objectives.yml
addons/oneblock/finales.yml
addons/oneblock/runtime/
addons/oneblock/tools/simulate_objective_rush.py
tests/test_oneblock_objective_engine.py
tests/test_oneblock_objective_simulation.py
```
