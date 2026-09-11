# !play Handler Routing Bug — Post-Mortem (2026-06-06)

**This document is the full writeup of the failed fix attempt on 2026-06-06. Read it before touching the song system's !play handler again.**

## TL;DR

The user reported: "this song system never work man, there's always bug." Specifically:

1. Loop song playing.
2. `!play A` → A plays (replaces loop).
3. `!play B` → **B replaces A. SHOULD HAVE just queued B behind A.**
4. `!play C` → C correctly queues.
5. B ends naturally → **C never plays.**

I wrote a fix plan based on a wrong mental model (claimed it was a worker stale-cache race). Deployed the fix. User had to test on stream and discovered the fix didn't work.

The fix was reverted (stashed). Real bugs identified (see below).

## The failed plan

I wrote a 3-part plan:
1. Centralize 429 handling in `_spotify_request` helper.
2. Bump `_PLAYBACK_CACHE_TTL` 2s → 5s.
3. Add "freshly started" marker in `play_next_from_queue` for the worker to trust over stale cache.

The marker fix would not have fixed the reported flow. The "stale cache race after `play_next_from_queue`" theory was wrong. The actual reported bug was in the `!play` handler, not the worker.

## Real Bug 6: !play handler uses Spotify's stale state for routing decision

**Location:** `minecraftDiamond.py:1011-1040`

**Symptom chain:**
1. Loop playing on Spotify. Queue: `[]`.
2. `!play A` → A added: `[A: queued]`. `playback` from cache shows loop. `_is_user_song_playing()` checks if loop URI is in our local queue with status playing/pushed → NO → returns False. Falls into **else** branch (line 1032-1040). `play_track_immediate(A)` plays A. `mark_as_playing(0)` marks A as playing. Queue: `[A: playing]`. ✓ (Looks correct.)
3. `!play B` (issued before cache updates): B added: `[A: playing, B: queued]`. Cache STILL shows loop (lag 2-5s). `_is_user_song_playing()` returns False. Falls into **else** branch. `play_track_immediate(B)` REPLACES A with B. `mark_as_playing(1)` marks A as played, B as playing. Queue: `[A: played, B: playing]`. **BUG: A is now gone from playing state.**
4. `!play C` (cache now updated to B): C added: `[A: played, B: playing, C: queued]`. `_is_user_song_playing()` returns True. Takes **pass** branch. C stays queued. ✓
5. B ends naturally. Worker tick: `_sync_playback_state` should mark B as played → advance to C. **But it didn't, because of Bug 7 (see SKILL.md).**

**Why I missed it:** I jumped straight to "worker can't advance" (the visible symptom in step 5) without tracing backward to figure out why B got marked as "playing" when A should have been. Step 3 looks like a successful transition (A is replaced by B) — but it shouldn't have happened.

**The correct fix:** Read from the **local queue** (source of truth, updated synchronously by `mark_as_playing()`) for the routing decision, not from Spotify's playback state.

```python
# CORRECT
queue = sh.load_queue()
has_user_song_playing = any(q.get("status") == "playing" for q in queue)

if has_user_song_playing:
    pass  # user song already playing locally; just queue, don't touch Spotify
elif not sh.get_current_playback().get("is_playing"):
    # nothing playing anywhere — push to Spotify directly
    sh.queue_track(track["uri"])
    # ... mark_as_playing, add_to_history
else:
    # Spotify playing non-user content (loop, manual) — replace context
    sh.play_track_immediate(track["uri"])
    # ... mark_as_playing, add_to_history
```

## Real Bug 7: Worker can't detect natural song end when Spotify is slow to return 204

**Location:** `spotify_handler.py:_sync_playback_state` and `process_song_queue`

**Symptom:** Song ends naturally on Spotify. Worker ticks 5s, 10s, 15s — never advances to next queued song.

**Root cause:** `_sync_playback_state` only marks a "playing" song as "played" when:
- A different track is now playing on Spotify, OR
- Spotify's 204 (cleared the item — `current_uri=None`)

Spotify keeps `current_uri=old_track, is_playing=False` for many seconds after natural song end. Both conditions stay FALSE on every tick → `_sync_playback_state` does nothing → worker has no signal to advance.

**Fix (proposed, not yet deployed):** 3-tick idle counter (15s) in the worker. If `has_playing=True AND has_queued=True AND (is_playing=False or current_uri=None)` for 3 consecutive ticks → mark current as played, call `play_next_from_queue()`.

**Critical conflict with Bug 4 (user-pause respect):** the 3-tick threshold ONLY triggers when `has_queued=True`. Reasoning:
- `has_queued=False`: user might be pausing for any reason. Respect indefinitely.
- `has_queued=True`: someone is waiting for current to end. 15s of idle is positive evidence song actually ended.

## Methodology lessons (from this failed attempt)

1. **When the user says "system is fundamentally broken", do NOT write a fix plan from a mental model.** Read the actual code paths in the handler where the user interacts, find where the routing decision is actually being made wrong.

2. **Trace backward from the visible symptom to the source.** I saw "song doesn't auto-advance" and assumed the worker was wrong. The real cause was earlier: the `!play` handler was replacing songs incorrectly, and the worker's natural-end detection was a separate (compounding) issue.

3. **Before deploying, ask: "would this fix actually fix the exact flow the user reported?"** If you can't trace through the user's exact sequence and show the fix works at each step, don't deploy.

4. **The user tests live on stream.** Broken fixes frustrate. Get it right or communicate the blocker honestly. Don't ship and hope.

5. **Local queue is the source of truth for song system routing decisions.** Spotify can lie about state for 2-5s due to caching. The local queue cannot.

## Flow chart of the correct fix

```
!play X
   │
   ├─ load local queue
   │
   ├─ is any entry status="playing"?
   │     │
   │     ├─ YES → user song already playing locally
   │     │        → just queue X locally
   │     │        → don't touch Spotify
   │     │        → X plays when current song ends
   │     │
   │     └─ NO → no user song in our queue
   │              │
   │              ├─ is Spotify playing anything?
   │              │     │
   │              │     ├─ NO → push X to Spotify's queue directly
   │              │     │      → mark X as "playing" locally
   │              │     │
   │              │     └─ YES (loop/manual) → play_track_immediate(X)
   │              │                            → mark X as "playing" locally
   │              │
   │              └─ X is now "playing" locally
   │
   └─ done

Worker tick (every 5s):
   │
   ├─ _sync_playback_state
   │     → marks "playing" song as "played" if:
   │         (a) different track now playing, OR
   │         (b) current_uri=None (Spotify 204)
   │
   ├─ if (a) or (b) fired → save queue, continue
   │
   ├─ if (a) or (b) did NOT fire but:
   │     - has_playing=True (still showing "playing" in queue)
   │     - has_queued=True (someone waiting)
   │     - is_playing=False (Spotify says idle)
   │     → for 3 consecutive ticks (15s) → assume song ended
   │       → mark "playing" as "played"
   │       → call play_next_from_queue()
   │
   └─ if (a) or (b) did NOT fire AND has_queued=False:
         → user might be pausing; respect indefinitely
```

## Files & line numbers

- `minecraftDiamond.py:1011-1040` — `!play` handler routing (Bug 6 fix site)
- `spotify_handler.py:_sync_playback_state` — natural-end detection (Bug 7 partial)
- `spotify_handler.py:process_song_queue` — worker branch logic (Bug 7 fix site)
- `plan file: .hermes/plans/2026-06-06-song-system-real-fix.md` — execution plan
