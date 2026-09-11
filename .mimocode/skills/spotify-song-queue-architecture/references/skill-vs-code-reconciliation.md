# When the Skill Says X but the Code Says Y — Reconciliation Workflow

**Lesson source:** 2026-06-06 Spotify song system fix attempt. I wrote a 3-part fix plan based on the `spotify-song-queue-architecture` skill, deployed it, user tested on stream, fix didn't work, had to revert.

## TL;DR

**Skills are descriptions of intent, not ground truth for the current code.** When planning a fix:

1. **Always read the actual code FIRST** to verify the skill's claims still match reality.
2. **If skill and code disagree: code wins.** Patch the skill to match reality.
3. **If the skill is wrong about a core architectural claim** (e.g. "we never call `queue_track()`" when the worker clearly does), treat the entire skill as suspect for the area you're about to touch.
4. **Don't deploy a fix from a skill that you haven't cross-checked against the actual code at the specific lines the fix will touch.**

## Concrete symptoms to look for

- Skill describes an "ideal architecture" with words like "always", "never", "must" but you can find counterexamples in the code via grep.
- Skill references functions that don't exist, or describes flows that don't match the actual function bodies.
- The user reports "the bug came back" for something the skill claims is fixed.
- You're about to write a fix plan and you haven't read the actual code in the function you're patching.

## What to do when you find the disagreement

1. **Stop the plan.** Don't write more steps based on a wrong mental model.
2. **Read the actual code at the site of the reported bug** — both the handler the user interacts with AND the worker/background process. Bug chains often span both.
3. **Trace backward from the visible symptom.** "Song doesn't auto-advance" might look like a worker problem but actually be a `!play` handler problem that put the queue in a weird state.
4. **Patch the skill to match reality** (BEFORE deploying any fix), so future sessions don't repeat the mistake. Use `skill_manage` action=patch.
5. **Then plan the fix from the actual code, not the skill.**

## Reusable principle

The most expensive kind of agent failure is **fixing the wrong bug**. The user has to discover this on stream. They have to take time to test your fix. They get frustrated. The fix has to be reverted. The plan has to be rewritten.

**Cost of pre-deploy verification:** ~5 minutes of reading the code.
**Cost of a wrong fix deployed:** an entire stream of testing, user frustration, revert + re-plan.

Always pick the 5-minute verification.

## Related: the "trace the user's exact flow" rule

When the user reports a specific flow that breaks (e.g. "!play A → !play B → wait → song doesn't auto-advance"), your fix plan MUST be able to walk through that exact flow and show the fix working at each step. If you can't, the fix is wrong.

This is true even for "low-risk refactors." A refactor that doesn't fix the actual bug is wasted work that pushes the real fix further out.

## Cross-references

- `references/!play-handler-routing-bug.md` — concrete example of the 2026-06-06 failure
- `spotify-song-queue-architecture` SKILL.md — Bug 5 status: REVERTED. Real bugs are Bug 6 and Bug 7.
- `tiktokmc-build-deploy` SKILL.md "Past mistakes" — "Deployed a song-system fix from a wrong mental model" entry
