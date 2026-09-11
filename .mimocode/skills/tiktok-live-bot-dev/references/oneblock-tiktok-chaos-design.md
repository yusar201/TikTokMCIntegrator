# OneBlock TikTok Gift Chaos — Design Doctrine

Use this reference when brainstorming or implementing TikTok gift interactions for Khito's OneBlock Objective Rush.

## Do not underestimate the chaos target

Khito's viewers enjoy catastrophic interactions from Diamond Hunter: nukes, death rays, full inventory clears, world-eater effects, and similar high-impact sabotage. Do not default to mild, family-safe party-game effects or overprotect the player. The desired spectacle is **total chaos with a recoverable game foundation**.

## Core invariant

```text
Permanent:
- OneBlock registered anchor position
- OneBlock phase and progression counter
- Save integrity

Valid destruction targets:
- player and life
- inventory and equipment
- player-built island
- containers and resources
- mobs/helpers
- current Objective Rush objective/score, when explicitly priced and approved
```

The right mental model is **destroy eras of the island without bricking the world**. Catastrophes may erase everything the player built, but the source OneBlock and its progression remain usable so play can restart from one block.

## Strong OneBlock-specific chaos categories

1. **Inventory catastrophe** — clear inventory, inventory rain, random deletion, hotbar/armor/resource purge, container ejection.
2. **Island destruction** — delete 25%, half, or all player-built blocks; island decay; erase everything except the OneBlock.
3. **Explosive spectacle** — nuclear TNT, death ray, TNT rain, lava ocean, meteor shower, disintegrating TNT, world eater. Restore/validate the OneBlock anchor afterward.
4. **Void/gravity events** — extreme sky launch, inventory launched midair, void vacuum, event horizon, sky prison.
5. **Sky-world attacks** — ghast ring, phantom apocalypse, Vex swarm, Warden drop, ravager/creeper/mob rain, anvils/arrows/lightning.
6. **Anchor-hostage effects** — cage or surround the OneBlock, make each mined block trigger punishment, laser cage. Never mutate the mod's registered anchor state.
7. **Premium chains** — Rebirth, Apocalypse, Floor Is Gone, Death-Ray Carousel, World Eater, Void God.
8. **Absurd rescue gifts** — golem army, Totem storm, Netherite rain, fortress drop, Creative burst, Divine Reconstruction. Encourage gift wars between destruction and recovery.

## Objective Rush interaction

Physical chaos should be the main interaction layer. Score attacks are more frustrating than world destruction and should be rare/expensive:

- reset objective progress;
- force failure/Strike;
- hard reroll;
- temporary progress freeze/reversal;
- Win theft only if Khito explicitly selects it.

Do not let ordinary gifts directly rewrite Wins. Reserve score damage for premium gifts and make it visible.

## Ideation output format

When Khito asks for interaction ideas:

- Generate a broad, unapologetically destructive catalog, not only a safe starter set.
- Organize by cheap/medium/large/premium and sabotage/help.
- Include signature named events with step-by-step spectacle.
- State the permanent anchor invariant once; do not dilute every idea with excessive safety disclaimers.
- For selection, create an Obsidian Markdown checklist (`- [ ]`) under `Agent-Hermes/projects/tiktok-mc-integrator/`, grouped by category with empty shortlist sections for chosen cheap, medium, large, premium, and counter-gifts.

## Implementation requirements

- Prototype catastrophic effects against a copied world first.
- Back up the live OneBlock world before enabling premium destruction.
- Tag or otherwise identify spawned entities when cleanup is intended.
- Define repeat semantics per effect: simultaneous, queued, stacked, extended, or replaced.
- Restoration logic must preserve source progression rather than resetting the OneBlock phase/counter.
- Full Minecraft restart is required after deploying Forge changes.
