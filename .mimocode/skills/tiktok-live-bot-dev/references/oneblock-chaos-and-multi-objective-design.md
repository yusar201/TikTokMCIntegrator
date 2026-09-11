# OneBlock Chaos Gifts and Multi-Objective Design

Use this reference when brainstorming or implementing TikTok gift interactions for OneBlock Objective Rush.

## User workflow and approval boundary

Khito prefers this sequence:

1. Broad idea bank in an Obsidian Markdown checklist.
2. Khito checks candidates and adds notes.
3. Produce a deduplicated shortlist for another elimination pass.
4. Reconcile notes, overlaps, and feasibility.
5. Write separate implementation plans.
6. Do not execute until Khito explicitly approves.

Treat words such as “implementation” inside a brainstorming note as design input, not authorization to modify the game.

## Chaos doctrine

Do not default to sanitized party-game effects. Khito’s audience enjoys catastrophic, persistent consequences: inventory deletion, nuclear destruction, island wipes, death rays, boss attacks, and score sabotage.

Sacred OneBlock state:

- registered anchor position;
- phase;
- progression counter.

Valid chaos targets:

- player and position;
- inventory and equipment;
- all constructed island infrastructure;
- spawned entities;
- active Objective Rush progress/score where explicitly selected.

Island destruction is permanent until rebuilt unless an effect explicitly says otherwise.

## Implementation routing

- **Skript-first:** ordinary commands, mob/TNT spawning, inventory effects, potion/launch effects, block placement loops.
- **Skript + anchor guard:** destructive world edits that must exclude the OneBlock coordinate.
- **Existing mod experiment:** test a suitable mod before recreating behavior (for example, Void Totem).
- **Forge helper/plugin:** authoritative anchor protection, structure placement, custom entity/block behavior that Skript cannot reliably express.
- **Python Objective Rush engine:** score/progress mutation, objective baseline resets, simultaneous-objective state, persistence, API, dashboard, and OBS.

For Skript prototypes, use direct commands with player, quantity, and TikTok sender. Quantity should naturally scale intensity. Test manually before gift mapping and use the `ikhito-skript` refactor-safety protocol.

## Multi-objective core contract

- Engine supports 1–3 simultaneous objectives.
- Default remains 1 for backward compatibility.
- First live trial uses 2; Khito controls the count himself.
- Minecraft command: `/rush objectives <1|2|3>`; changing count mid-set applies to the next set.
- Objective IDs within a set must differ; prefer different types when eligible without dead-ending selection.
- Each objective has an independent baseline/progress/resolved state.
- Completing one leaves it visibly completed; no replacement until the set resolves.
- Completing the whole set awards exactly one Win.
- Fail/reroll applies once to the whole set, never once per objective.
- Finale remains one objective even if configured count is 2 or 3.
- Persistence must migrate legacy `active` state to `active_objectives` safely.
- Minecraft status/chat/title, API, dashboard, and OBS must display every slot.

## Clarified gimmick semantics

- **Obsidian Hostage:** permanent 3×3×3 obsidian shell centered on the OneBlock, skipping the exact center coordinate.
- **Sky Launch:** approximately +250 Y from current level, no fall protection.
- **Levitation Stack:** repeated gifts add duration with no cap; pair with a void-rescue counter-gift.
- **Mob Rain:** reuse random-mob behavior, fall from sky, suppress mob fall damage.
- **Ghast:** one per quantity/repetition rather than a fixed ring.
- **Island Decay:** draft radius 100 around player, 20 seconds, roughly two blocks removed per second, preserve containers and anchor.
- **Clear Inventory:** irreversible deletion; distinct from Inventory Rain, which launches recoverable stacks.
- **Delete the Island:** merge into Rebirth rather than maintain as a duplicate.
- **Golem Guardian/Army:** merge into scalable Golem Reinforcement where quantity controls count.
- **Guardian Angel:** merge into Void Totem if the tested mod provides equivalent rescue.

## Objective sabotage semantics

- **Double Trouble:** stackable and allowed during Finale.
- **Objective Theft:** reset/reduce credited progress and capture a fresh baseline. Do not pretend to reverse historical crafts, kills, uses, mined counter, or phase. For collect objectives, target items may also be removed separately.
- **Finale Early:** currently awards one normal Win.
- **Win Theft:** floor zero and reroll/create a new set.
- **Two Objectives:** implement as the general 1–3 objective core, not a one-off gift hack.

## Planning artifacts

Plans may live in project `.hermes/plans/`; brainstorming checklists and routing notes belong in the Obsidian project folder. Keep source checklist, shortlist, and implementation plan separate so elimination edits do not silently become production requirements.
