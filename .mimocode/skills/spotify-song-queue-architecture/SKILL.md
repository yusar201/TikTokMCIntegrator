---
name: spotify-song-queue-architecture
description: "TikTokMCIntegrator Spotify song queue — local-only architecture (no queue_track), play_track_immediate + play_next_from_queue, worker natural-end detection via 3-tick idle counter, !play handler reads local queue for routing (not stale Spotify state). Lesson: skill description was once aspirational, code was the opposite — always read the actual code before planning a fix. Stability > optimization per user."
trigger: "TikTokMCIntegrator spotify queue, song queue bugs, spotify revoke, spotify skip, song queue architecture, play_track_immediate, play_next_from_queue, queue_track, !play handler, song worker"
---

# Spotify Song Queue — Working Architecture

## Core Principle
**Songs are NEVER pushed to Spotify's queue via `queue_track()`.** 
They sit in the local `song_queue.json` with status `"queued"` until they're ready to play. This eliminates the root cause of all revoke/skip bugs (Spotify has no "remove from queue" API).

## Key Functions

### `play_next_from_queue()` (spotify_handler.py)
- Finds the next song with status `"queued"` in the local queue
- Calls `play_track_immediate(uri)` to play it immediately on Spotify
- Marks previous "playing" song as "played" + adds to history
- Marks new song as "playing"
- Used by: `!skip` handler AND worker (on natural song end)

### `remove_from_queue()` (spotify_handler.py)
- **Always instant** — just removes from the local JSON file. No Spotify API calls.
- No blocked URIs, no context-purge, no fallback mechanisms needed.

### Worker `process_song_queue()` (spotify_handler.py)
- Polls every **5 seconds** (not 30s — more responsive)
- **Step 1**: `_sync_playback_state()` — detects when a song ended naturally
- **Step 2**: Check playback state + queue status:
  - If nothing playing + queue has `"playing"` → stale cache (from !skip), wait
  - If nothing playing + queue has `"queued"` → song ended naturally, call `play_next_from_queue()`
  - If nothing playing + queue empty → auto-resume loop song

### `!play` handlers (minecraftDiamond.py + routes/spotify.py)
- Case 1 (nothing playing): `play_track_immediate(uri)` — plays immediately
- Case 2 (user song playing): **`add_to_queue()` only** — NO `queue_track(uri)`. Song stays local.
- Case 3 (loop song): `play_track_immediate(uri)` — replaces context

### `!skip` handler
- `skip_track()` + `play_next_from_queue()` — instantly plays next from local queue

## ⚠️ REALITY CHECK — Read This Before Doing Anything (2026-06-06)

**This skill describes the ASPIRATIONAL architecture, not necessarily what the code does today.**

The skill was written after the song system was conceptually redesigned. But the code is in a **half-migrated state**:
- `play_track_immediate()` and `play_next_from_queue()` **may not exist** in `spotify_handler.py`. They were described as the "right way" but never actually written.
- The worker (`process_song_queue`) **may still call `_push_queued_songs()`** which uses `queue_track()` to push to Spotify's queue — the OPPOSITE of what this skill says.
- The `!play` handler in both `minecraftDiamond.py` and `routes/spotify.py` **may still call `queue_track()`** in the "nothing playing" branch.
- Comments in the code claim local-only architecture, but the actual implementation may still push to Spotify.

**Symptom of half-migrated state:** `!revoke`/`!pull` doesn't work as advertised. Songs removed from the local queue still play on Spotify for a few seconds (because they were already pushed). `!play B` after `!play A` replaces A (because the worker pushed B, Spotify's queue has B, and A gets skipped to B).

**The fix is the architecture itself**, applied in three places:
1. Add `play_track_immediate(uri)` (PUT `/me/player/play` with `{"uris": [uri]}` + disable repeat).
2. Add `play_next_from_queue()` (find next `status="queued"` in local queue, call `play_track_immediate`).
3. Worker stops calling `_push_queued_songs`. Instead, after `_sync_playback_state` marks a song as played, call `play_next_from_queue()`.
4. `!play` handler "nothing playing" branch uses `play_track_immediate`, not `queue_track`.

After this refactor, the worker only uses `play_track_immediate()` to start songs, never pushes to Spotify's queue, and `!revoke` becomes truly instant (just remove from local file).

**ALWAYS read the actual `spotify_handler.py` to verify these functions exist before assuming the skill's architecture is in place.** Check the worker's `process_song_queue` to see if it calls `_push_queued_songs` or `play_next_from_queue`. The skill is a target, not a description of current state.

---

## Critical Bug Fixes

### Bug 1: Natural song end deadlock
**Problem**: `_sync_playback_state` didn't mark finished songs as "played". Spotify returns finished track as `item` with `is_playing=False`. The URI is still non-None. The old check only matched songs with DIFFERENT URIs — same URI was skipped.

**Fix**: Add `not is_playing` check. If a "playing" queue entry matches the current URI but Spotify says it's NOT playing → song finished → mark as "played" + break.

```python
if q.get("status") == "playing":
    if q.get("spotify_uri") != current_uri or not is_playing:
        q["status"] = "played"
        if q.get("spotify_uri") == current_uri:
            break  # Same track finished — don't re-mark as "playing" below
```

### Bug 2: Worker race with !skip
**Problem**: After !skip → `play_next_from_queue(B)`, B is marked "playing" in queue. Worker's 2s cached playback still shows "nothing playing". Worker would auto-resume loop song, overwriting B.

**Fix**: If playback is idle but queue has a `"playing"` song, worker knows cache is stale and waits.

### Bug 3: Context-purge was wrong
**Attempted fix**: Replace Spotify context to clear its queue. Had side effects (restarted tracks, wrong fallback order). **Replaced** with local-only queue approach (Bug 1's architecture).

### Bug 4: Paused-song auto-resume aggression (2026-06-04, user-reported)
**Problem**: User pauses Spotify to switch to a different media player (e.g. user-requested video/audio on stream). The bot's worker auto-resumed the loop song every 5s, killing the user's other media.

**User intent**: Manual pause = respected **indefinitely**. Loop song only auto-resumes when the track has *actually* finished. Some dead air is acceptable; overriding a manual pause is NOT.

**Fix**: Distinguish three idle states in `process_song_queue`:
- `not is_playing, has_queued` → song ended, play next from queue
- `not is_playing, !current_uri, queue empty` → track truly ended (Spotify returned 204), resume loop song
- `not is_playing, current_uri set, queue empty` → USER PAUSED, leave it alone forever

Also in `_sync_playback_state`: never mark a "playing" queue track as "played" just because `is_playing=False`. Only mark it on (a) a different URI is now playing, or (b) `current_uri` is null. This way a paused song keeps `status="playing"` in the local queue, so the worker sees `has_playing=True` and waits instead of auto-resuming the loop.

**Tradeoff**: If the loop song itself naturally ends and Spotify is slow to return 204, there's a brief dead-air window. Acceptable — user can `!play` something or wait for the next gift. The alternative (auto-resume on pause) is much worse because it overrides user-initiated pauses.

**Reverted bad fix**: An earlier attempt used an `idle_ticks >= 2 cycles` threshold to "disambiguate" pause vs end. User correctly pushed back: 10 seconds of grace is still too short when they need to keep the pause for a whole media clip. The 204-clear-based approach is the only one that gives infinite pause tolerance.

**Principle: when two states are API-indistinguishable, pick the LESS destructive default.**
User-pause vs natural-end both look like `is_playing=False`. A worker that "resolves the ambiguity by overriding the pause" will frustrate the user constantly. A worker that "resolves it by waiting" only causes brief silence on the rare natural-end case. **Always bias toward doing nothing when the user might have intended the current state.** This principle generalizes to any worker that reacts to user-initiated state changes (pause, mute, minimize, disconnect, etc.) — when in doubt, do nothing and let the user resolve.

**Where to surface this principle in your work**: Whenever you see a worker that calls an action in response to "X stopped happening", first ask "could X-stopped-happen be user-initiated?" If yes, your default should be passive (wait + log) unless you have positive evidence of automation intent.

### Bug 5: Stale-cache race after `play_next_from_queue` (2026-06-06, user-reported)
**Status: REVERTED 2026-06-06.** The marker fix was deployed and reverted the same day. The reported "song doesn't auto-play next" symptom was actually caused by Bug 6 (`!play` handler routing bug) and Bug 7 (worker natural-end detection), not by a stale-cache race after `play_next_from_queue`. See `references/!play-handler-routing-bug.md` for the full post-mortem. Do not re-deploy the marker fix without re-validating the user's exact flow first.

### Bug 6: !play handler uses Spotify's stale state for routing decision (2026-06-06)

**Symptom:** `!play B` while A is playing causes B to REPLACE A (should just queue behind A). After 2-3 `!play`s, A is gone from "playing" state and the system is in an unexpected state.

**Root cause:** `minecraftDiamond.py:1011-1040` calls `sh._is_user_song_playing()`, which reads `get_current_playback()`. The 2-5s playback cache means Spotify's response still shows the OLD track (e.g., loop song) for 2-5s after `play_track_immediate(A)` returns. `_is_user_song_playing()` returns False because the stale track isn't in our local queue → handler falls into "loop playing" branch → `play_track_immediate(B)` REPLACES A.

**Fix:** Read from the **local queue** for routing decisions — it is the source of truth, updated synchronously by `mark_as_playing()`. Spotify can lie about state for 2-5s; the local queue cannot.

```python
# CORRECT — local queue is the source of truth
queue = sh.load_queue()
has_user_song_playing = any(q.get("status") == "playing" for q in queue)

if has_user_song_playing:
    pass  # user song playing locally; just queue, don't touch Spotify
elif not sh.get_current_playback().get("is_playing"):
    # nothing playing anywhere — push to Spotify directly
    sh.queue_track(track["uri"])
    pos, entry = sh.get_next_to_play()
    if pos is not None:
        sh.mark_as_playing(pos)
    if entry:
        sh.add_to_history(dict(entry))
else:
    # Spotify playing non-user content (loop, manual) — replace context
    sh.play_track_immediate(track["uri"])
    pos, entry = sh.get_next_to_play()
    if pos is not None:
        sh.mark_as_playing(pos)
    if entry:
        sh.add_to_history(dict(entry))
```

**General principle:** local queue is the source of truth for routing decisions. Spotify's `/me/player` is for end-detection only.

### Bug 7: Worker can't detect natural song end when Spotify is slow to return 204 (2026-06-06, DEPLOYED + USER-ACCEPTED)

**Symptom:** Song ends naturally. Worker ticks 5s, 10s, 15s — never advances to next queued song.

**Root cause:** `_sync_playback_state` only marks a "playing" song as "played" when (a) a different track is now playing, or (b) Spotify returns 204 (`current_uri=None`). Spotify keeps `current_uri=old_track, is_playing=False` for many seconds after natural end. Both conditions stay FALSE → nothing happens.

**Fix (deployed 2026-06-06, user accepted):** 3-tick idle counter (15s max, ~5-10s typical) in the worker. If `has_local_playing=True AND is_playing=False AND spotify_current_uri != local_playing_uri` for 3 consecutive ticks → mark current as played, call `play_next_from_queue()` (or `play_track_immediate(loop_uri)` if queue empty).

**User-accepted tradeoff:** ~5-10s of silence between songs is the cost of not misfiring on user pauses. User said: *"i'll keep with this one for now as long as it works 😭"* after explicitly accepting the delay. **Do not reduce the 3-tick threshold** without checking with the user first — they got tired of the song system eating tokens and want stability, not optimization.

**Critical: must NOT conflict with Bug 4 (user-pause respect).** The 3-tick threshold ONLY triggers when `has_local_playing` actually mismatches Spotify's reported current URI for consecutive ticks. Reasoning:
- `has_local_playing=False`: user might be pausing for any reason. Respect indefinitely.
- `has_local_playing=True AND spotify URI matches`: track is actually playing, no action.
- `has_local_playing=True AND spotify URI mismatches for 3+ ticks`: song ended but Spotify's 204 didn't arrive yet — safe to advance.

**General principle:** "presence of a queued song" combined with "sustained state mismatch" is positive evidence of automation intent. No queued song = user might be pausing. Queued song + idle = current one must have ended eventually.

### Bug 8: Stale playback cache after `play_track_immediate` → auto-skip on 2nd !play (2026-06-10, DEPLOYED)

**Symptom (user-reported, live stream):** Loop song playing. `!play A` → A plays immediately. ✓ Then `!play B` to queue behind A → **B did NOT queue, it auto-skipped to B, killing A mid-song.** Exactly the "2nd !play replaces the 1st" symptom Bug 6 was supposed to fix — but Bug 6's handler fix was already in place and correct. The cause was downstream, in the worker.

**Root cause — two compounding issues:**
1. `play_track_immediate()` started the new track on Spotify but did **NOT invalidate `_playback_cache`** (TTL=2s). So for up to 2s after `!play A`, `get_current_playback()` still returned the OLD loop song.
2. `_sync_playback_state` had a single-tick mark-as-played loop: `if status=="playing" and spotify_uri != current_uri: mark "played"`. A worker tick landing in that 2s stale window saw A="playing" locally but cache="loop song" → **wrongly flipped A to "played"**.
3. Then `!play B` arrives: handler's `has_local_playing = any(status=="playing")` is now **False** (A got flipped), so it falls through to the Spotify branch, sees something playing, treats it as "loop/non-user content," and calls `play_track_immediate(B)` → **B replaces A.**

So the handler routing (Bug 6 fix) was correct; the worker corrupted the local-queue state out from under it via a stale read.

**Fix (deployed 2026-06-10, two surgical patches in `spotify_handler.py`):**
1. In `play_track_immediate()`: after the PUT `/me/player/play`, set `_playback_cache["cached_at"] = 0` so the very next `get_current_playback()` re-fetches and reflects the track just started. Kills the 2s stale window.
2. In `_sync_playback_state()`: **removed the single-tick mark-as-played loop entirely.** In the local-only architecture Spotify never advances to a *different* track on its own — a "playing-local URI ≠ spotify current URI" mismatch is ALWAYS either (a) stale cache, or (b) the loop song. Acting on it single-tick is unsafe. Natural-end detection is left to the two robust authorities that remain: the clean-204 branch (`current_uri=None`) and the 3-tick idle counter in `process_song_queue()` (Bug 7). No regression to the accepted ~5-10s natural-end delay.

**General principle (reinforces Bug 6):** any function that changes Spotify playback state (`play_track_immediate`, `skip_track`, pause/resume) MUST invalidate the playback cache immediately, or a worker tick can read stale state and corrupt the local queue. The local queue is the source of truth for routing — but only if the worker's reads of Spotify aren't lying to it. Cache invalidation on write is the bridge between those two facts.

**Trace-the-fix discipline paid off:** before deploying, traced the full flow loop→`!play A`→`!play B`→A-ends→B-plays and confirmed each step. Per the deploy skill's hard rule, no song-system fix ships without that trace.

### Bug 9: Mid-song pause auto-skipped to next queued song (2026-06-10, DEPLOYED)

**Symptom (user-reported):** A song is playing with another song queued behind it. User pauses the current song mid-track to play other media on stream. After ~15s the worker **auto-skips to the next queued song** instead of staying paused.

**Root cause:** The Bug 7 3-tick idle counter advances whenever `is_playing=False` for 3 consecutive ticks AND a local song is "playing". It could NOT distinguish a user-pause from a natural song-end — both report `is_playing=False`. The Bug 4 "respect pause" logic only held when the queue was *empty*; with a song queued, the idle counter fired and skipped. So the exact scenario (paused with something queued) was precisely when it misfired.

**Fix (deployed 2026-06-10, one surgical patch in `process_song_queue`):** use playback **position** as the discriminator. Both `progress_ms` (from `/me/player`) and `duration_ms` (from `item`) are available.

```python
END_GRACE_MS = 12000  # within 12s of end = treat as actually ended
same_track = bool(local_playing_uri) and spotify_current_uri == local_playing_uri
near_end = (duration_ms > 0 and progress_ms > 0
            and (duration_ms - progress_ms) <= END_GRACE_MS)
paused_mid_song = (not is_playing) and same_track and not near_end
# gate the 3-tick advance on: ... and not paused_mid_song and ...
```

- **Paused mid-song** = paused + same track still loaded + NOT near end → HOLD indefinitely, never advance.
- **Actually ended** = track cleared/changed (uri differs or 204) OR position within 12s of the end → advance as Bug 7 does.

This preserves Bug 7's flawless natural-advance while restoring Bug 4's infinite-pause tolerance — even with a song queued.

**Known edge (told to user):** pausing within the last 12s of a track is treated as "ended" and advances. That grace window is required so genuine song-ends still auto-advance when Spotify is slow to return 204. If it ever bites, tighten the window or add an explicit hold toggle.

**Bug 9 regression + re-fix (2026-06-10, same day):** the FIRST version of this fix broke natural-end advance — songs ended and just stopped, next never played. Root cause: when a single track ends naturally with repeat off and nothing else in Spotify's context, **Spotify does NOT always return 204 — it often pauses on the SAME track and resets `progress_ms` to ~0.** The first discriminator (`paused_mid_song = paused + same_track + not near_end`) then saw "same track + paused + not near end" and classified a natural end as a user-pause → held forever → next song never played. The `progress_ms ≈ 0` reset is ambiguous: it's either "natural end, Spotify reset to zero" OR "user paused at the very start."\n\n**Re-fix:** a real user-pause is ALWAYS meaningfully *into* the song, so add a progress floor:\n```python\nMIN_PAUSE_PROGRESS_MS = 5000  # must be >5s in to count as a real pause\npaused_mid_song = (\n    (not is_playing) and same_track\n    and progress_ms > MIN_PAUSE_PROGRESS_MS   # excludes reset-to-0 natural end\n    and not near_end\n)\n```\nNatural end resets to ~0 → below the floor → advances. Genuine mid-song pause is well past 5s → holds. **Lesson: natural song-end on Spotify has THREE shapes, not two — (a) 204/item cleared, (b) progress at/near duration, (c) same track left loaded with progress RESET TO ~0. Any pause-vs-end discriminator must handle all three or it misclassifies (c).**

**Near-end fast-path — variable advance latency (2026-06-10, user-requested speedup):** the flat 3-tick (15s) advance wait was too slow for the common case. User asked to shorten it. Key insight: `near_end` (progress sat at/near the track's full `duration_ms`) is an UNAMBIGUOUS end — physically impossible to confuse with a pause-at-start. So the advance threshold is now variable: `required_ticks = 1 if near_end else 2` (was a flat 3).
- **Song played to the end** (`near_end=True`): advances after **1 tick (~5s)** — the normal song-to-song transition.
- **Ambiguous end** (track cleared, or progress reset to ~0): advances after **2 ticks (~10s)** — short safety wait so a genuine mid-song pause is never misfired into a skip.

Result: most transitions dropped from 10-15s to ~5s with ZERO change to pause protection. **Do NOT also shorten the 5s poll interval** to speed this up further — that interval is load-bearing for the rate-limit single-flight design (3 concurrent pollers on `/me/player`); shrinking it reintroduces random 429s. Poll cadence and advance latency are INDEPENDENT levers — tune advance via `required_ticks`, never via the poll sleep.

**Refines the Bug 4 / Bug 7 guidance above:** the skill previously said "do not reduce the 3-tick threshold without asking." That still holds — but the threshold was never the real problem; the *missing pause/end discriminator* was. Position-based detection is the correct disambiguation the earlier idle-tick-only approach lacked. The Bug 4 principle ("when two states are API-indistinguishable, pick the less destructive default") is now *implemented* via position: we have positive evidence (near_end) of a real end, so we no longer have to guess.

**Pitfall:** `playback.get("item")` may be a dict OR None. Always read duration via `(playback.get("item") or {}).get("duration_ms", 0)`. Pyright flags `.get` on a possibly-str/None item — that's inference noise as long as you guard with `or {}`; the runtime value is always an int.

## Rate-Limit Architecture (2026-06-06)

The worker poll cadence + UI status poll + `!play`/`!skip` burst patterns were burning through Spotify's burst-sensitive rate limit (54-min cooldown triggered by single burst).

**Three changes**, all in `spotify_handler.py`:

1. **Centralize 429 handling in one helper** — `_spotify_request(method, endpoint, params, data, expect_json)`. The three old HTTP helpers (`_spotify_get`/`_post`/`_put`) are now one-liners that delegate. New endpoints auto-protect. **Critical compat note**: old `_spotify_get` returned `{"error": "..."}` for an empty 200 body. The new shared helper returns `{"success": True}` for non-JSON success. `_spotify_get` wrapper catches this case and re-wraps as `{"error": "..."}` so all existing `if "error" in data` checks continue to work without modification.

2. **Per-endpoint throttle (500ms min interval)** — `_endpoint_last_call[endpoint]` dict + `_throttle_endpoint(endpoint)` helper. Smooths burst patterns before they hit 429. Different endpoints throttle independently so parallel reads (`/me/player` + `/me/player/devices`) aren't blocked. Max wait is 1s even if drift is large. Use a per-endpoint lock, not a global one.

3. **Bump `_PLAYBACK_CACHE_TTL` from 2s to 5s** — worker polls every 5s, so 2s cache = cache miss on every worker tick. 5s cache = ~1 cache hit per worker tick. UI `/api/spotify/status` serves up-to-5s-stale data; acceptable. User actions (`!play`, `!skip`, `!revoke`) still feel snappy because they go through `play_track_immediate` / local queue removal, not the cache.

**Bump rule for any worker with a cache**: `CACHE_TTL` should match or exceed the worker poll cadence. If they're equal, the cache always hits; if cache is shorter, the cache never serves a useful purpose (every poll is a cache miss).

### Single-flight the cache (2026-06-10) — the fix for SPORADIC 429s

Bumping TTL + throttling is NOT enough on its own. `/me/player` is read by THREE
concurrent pollers: the worker (every 5s), the song overlay (`/api/stats/song`
every **1s**), and the dashboard (every 3s + status every 10s). The TTL cache and
the 500ms throttle did NOT coordinate: on a cache miss, all three threads could
blow past the stale cache *simultaneously*, each firing a real `/me/player` call.
The throttle only spaced them 500ms apart — it didn't dedupe. So one cache miss
fanned out into 2-3 real calls/sec, bursting Spotify's rolling window → random
429s with no obvious trigger ("sometimes it hits limit, weirdly").

**Fix:** wrap the real fetch in a `threading.Lock` with double-checked locking.
Concurrent misses collapse into ONE real call; the rest wait and reuse it.

```python
_playback_lock = threading.Lock()

def _get_cached_playback():
    global _playback_cache
    now = time.time()
    if now - _playback_cache["cached_at"] < _PLAYBACK_CACHE_TTL:
        return _playback_cache["result"]          # fast path, no lock
    with _playback_lock:
        now = time.time()
        if now - _playback_cache["cached_at"] < _PLAYBACK_CACHE_TTL:
            return _playback_cache["result"]       # refreshed while we waited
        result = _real_get_current_playback()      # single flight
        if isinstance(result, dict) and "error" in result:
            _playback_cache = {"result": result, "cached_at": now - _PLAYBACK_CACHE_TTL - 1}
            return result
        _playback_cache = {"result": result, "cached_at": now}
        return result
```

**Worker double-fetch dedupe (shipped alongside):** the worker called
`get_current_playback()` twice per tick (sync step + stuck-detect step). Made
`_sync_playback_state` RETURN the playback dict it already fetched — now a 4-tuple
`(queue, last_seen_uri, state_changed, playback)` — and the stuck-detector reuses
it. One fetch per tick, and both checks see the same snapshot.
**Pitfall:** when you change a function's return arity, BOTH return paths must
match — the error-early return AND the normal end-of-function return. Pyright
flags the size mismatch immediately; fix both or the worker's unpack throws.

**Net:** real `/me/player` calls drop from bursty ~50+/min to smooth ~20/min.
No added latency — user actions invalidate the cache directly (Bug 8 fix), so
`!play`/`!skip` stay instant.

**Generalizes:** any cache read by 3+ concurrent pollers needs single-flight, not
just a TTL. TTL dedupes *sequential* reads inside the window; it does nothing for
*simultaneous* misses. The lock is what caps real calls to one-per-miss.

**Do NOT** remove the global `_rate_limit_until` cooldown as a safety net even with the throttle in place. The throttle reduces 429 likelihood; the cooldown is the hard fallback when Spotify does hard-block.

### Bug 11: Dashboard queue-card X did nothing because it reused viewer revoke permissions (2026-07-09, DEPLOYED)

**Symptom (user-reported):** On the Song System tab, each queued song card has an X button intended to manually delete queued songs before they play. Clicking the X visually did nothing.

**Root cause:** The frontend called `DELETE /api/spotify/queue/<position>`, but the route passed `requested_by="dashboard"` into `remove_from_queue()`. That helper enforced viewer ownership (`entry.requested_by == requested_by`), so any viewer-requested song failed with `{"error": "You can only remove your own requests."}`. The frontend swallowed/under-displayed the 400, so the button appeared dead.

**Fix pattern:** Keep viewer `!pull` / `!revoke` ownership rules intact, but make the dashboard endpoint an explicit operator/admin path:

```python
def remove_from_queue(position, requested_by, allow_any=False):
    entry = queue[position]
    if entry.get("status") not in ("queued", "pushed"):
        return {"error": "Cannot remove the currently playing song. Use skip instead."}
    if not allow_any and entry.get("requested_by", "").lower() != requested_by.lower():
        return {"error": "You can only remove your own requests."}
    removed = queue.pop(position)
```

and in `routes/spotify.py`:

```python
result = sh.remove_from_queue(position - 1, "dashboard", allow_any=True)
```

**Important behavior contract:**
- Dashboard X is an operator control: can remove any `queued` / `pushed` song regardless of requester.
- Viewer `!pull` / `!revoke` remains per-user and cannot remove other users' songs.
- Currently `playing` song is intentionally protected from X removal; use skip for the active track.

**Regression test shape:** Use a Flask test client with a temp `song_queue.json`; assert dashboard DELETE removes a queued song requested by a different user, and assert deleting a `playing` song returns 400 with a “currently playing” error. This catches both the dead-button bug and accidental permission broadening.

### Bug 10: `/me/player/devices` was the last uncached hot-path GET → sporadic 429s (2026-06-16, DEPLOYED)

**Symptom (user-reported):** Even after the single-flight `/me/player` fix, the bot STILL hit rare/sporadic 429s. "I thought we are already efficient enough."

**Root cause:** `get_active_devices()` → `GET /me/player/devices` was the ONLY remaining
hot-path Spotify GET with **no cache and no single-flight** — it had only the 500ms
per-endpoint throttle. The dashboard `/devices` route + any pre-play device check hit it
raw. Because `/me/player` was already locked down (single-flight + 3s TTL), this was the
last leak — which is exactly why the 429s were *sporadic* not constant. The 500ms throttle
is PER-endpoint, so `/me/player/devices` calls could still stack up across time and, combined
with `/me/player` + `/me/player/play` firing in the same window, burst Spotify's rolling window.

**Fix (deployed 2026-06-16):** wrapped `get_active_devices()` in the SAME single-flight +
TTL pattern as `_get_cached_playback` — split into `_real_get_active_devices()` (always hits
API) + `get_active_devices()` (cache wrapper with `_devices_lock` + `_devices_cache` +
`_DEVICES_CACHE_TTL = 30`). Devices barely change mid-stream so 30s TTL is safe and collapses
polls into near-zero real calls. Errors are NOT cached (retry fresh next call, so a disconnect
recovers instantly). **Zero added latency** — fresh cache returns instantly, never blocks; the
user-action paths (`!play`/`!skip`/`!revoke`) don't touch the device path at all.

**Model-fusion validated (2026-06-16):** fanned the diagnosis out to a panel (DeepSeek v4-pro +
GPT-5.5; Kimi was down on billing). BOTH independently picked "cache + single-flight
`/me/player/devices`" over the alternative "global cross-endpoint token bucket" — and both
explicitly rejected the token-bucket because it adds latency to user actions, which violates
Khito's hard "no more delay" constraint. Consensus + matched the code reading.

**General principle (generalizes the single-flight lesson):** after fixing the single-flight on
your highest-frequency endpoint, AUDIT every other Spotify GET in the hot path. Any uncached
read polled by the dashboard or hit on a user action is a latent sporadic-429 source. The fix is
always the same shape: `_real_X()` + cached `X()` wrapper with a per-resource lock + TTL sized to
how often the resource actually changes (devices = 30s, playback = 3s). The remaining independent
429 source after this is the token-refresh path (`_token_refresh_until`), which self-recovers.

### Bug 10: `/me/player/devices` was the last uncached hot-path GET → sporadic 429s (2026-06-16, DEPLOYED)

**Symptom (user-reported):** "rare but sometimes I still get rate limited" *after* all the single-flight/TTL/throttle work on `/me/player` was already shipped. Not constant — sporadic.

**Root cause:** `get_active_devices()` → `GET /me/player/devices` was the ONLY remaining hot-path Spotify GET with **no cache and no single-flight** — only the 500ms per-endpoint throttle. The dashboard `/api/spotify/devices` route + pre-play device checks hit it raw. Because the per-endpoint throttle is *per-endpoint*, `/me/player` + `/me/player/devices` + `/me/player/play` can all fire inside the same ~500ms window → a cross-endpoint burst against Spotify's rolling rate window → the rare 429. `/me/player` being single-flighted is exactly why the 429s were only *sporadic* (the protected endpoint wasn't the leak; the unprotected sibling was).

**Fix (deployed 2026-06-16):** wrap `get_active_devices()` in the SAME single-flight + TTL pattern as `_get_cached_playback`. Split into `_real_get_active_devices()` (always hits API) + `get_active_devices()` (cached). Use a dedicated `_devices_lock` + `_devices_cache` + `_DEVICES_CACHE_TTL = 30` (devices barely change mid-stream, so a long TTL collapses polls into near-zero real calls). Don't cache error responses (so a disconnect recovers instantly). **Zero added latency** — fresh cache returns instantly, never blocks `!play`/`!skip`/`!revoke`.

**How it was found (model-fusion):** fanned the question to a DeepSeek + GPT-5.5 panel. Both *independently* picked "cache + single-flight `/me/player/devices`" over the alternative (a global cross-endpoint token bucket), and both rejected the token bucket for the same reason the user gave — it adds latency to user actions. Two diverse models converging on the same minimal-latency fix = high confidence before touching the live song system.

**General principle (the rate-limit corollary):** single-flighting ONE hot endpoint doesn't fix bursts — audit EVERY uncached GET on a poll/pre-action path. The per-endpoint throttle does not coordinate across endpoints, so N uncached endpoints can still burst together. When 429s are *sporadic* after you've protected the obvious endpoint, the leak is almost always a sibling endpoint that shares the rolling window but not the cache. The only other independent 429 source left after this is the token-refresh path (rare, self-recovers).

**User constraint that shaped the fix:** "set aside the solution if it makes more delay — I don't want any more delay to my system." Any rate-limit fix for this user must be latency-neutral on user actions. Caching reads is fine; spacing/queuing writes is NOT.

## Pitfalls & User Preferences

### Deployment
- **ALWAYS restart the app** after deploying new code. The old process runs with old code.
- User tests LIVE on stream — fix must work FIRST TRY. Broken fixes frustrate quickly.
- Even 1-2 seconds of wrong song playing is unacceptable ("even couple seconds" = too much).
- **Before deploying any song-system fix, trace through the user's exact reported flow and verify the fix would resolve each step.** If you can't show the fix working at each step, do NOT deploy. The Bug 5/6/7 sequence (2026-06-06) was a fix deployed from a wrong mental model — the user had to discover on stream that it didn't work, costing an entire stream's worth of testing time. See `references/!play-handler-routing-bug.md`.
- **ALWAYS** before merging helpers that consolidate duplicated status-code handling, trace every caller's expectations. An empty 200 body returning `{"success": True}` vs `{"error": "..."}` is invisible until a caller does `data.get(...)` and hits `AttributeError: 'bool' object has no attribute 'get'`. Trust nothing — verify with a real import + grep for `if "error" in data` patterns.

### Stability over optimization (2026-06-06)
The user has explicitly said: *"i'm tired burning a LOT of tokens just to fix this spotify system"* and *"i'll keep with this one for now as long as it works 😭"*. Translation: **do not touch the song system without an explicit ask.** The 3-tick idle threshold (~5-10s delay between songs) is the accepted tradeoff for not misfiring on user pauses. Resist the urge to "optimize" it. The user prefers a working system with a known wart over a tweaked system that might break. If a new song-system bug appears, trace from real symptoms (paste from console / queue dump) — never from this skill's text alone, since the skill was once aspirational.

### This user (Khito)
- Tests immediately on stream. Wants working results, not analysis or explanation.
- Expects TikFinity-level behavior: instant revoke, instant skip, no dead air.
- Prefers you just fix it rather than explain why the fix is hard.
- "make a plan to fix it" with a stream coming up = write the plan to `.hermes/plans/`, do NOT execute. Execute only when user says "go ahead" or "execute". No permission asking once they say "go".

### UX: Console auto-scroll
Dashboard console (`static/script.js` `fetchLogs`) used to force `scrollTop = scrollHeight` on every poll, so scrolling up to read older logs snapped back to bottom on next poll. **Fix**: capture `isAtBottom = scrollHeight - scrollTop - clientHeight < 30` BEFORE updating textContent, then only auto-scroll if `isAtBottom` was true. The 30px threshold means "close enough to bottom that the user is actively following."

### Architecture Lesson
The WRONG approach was trying to undo `queue_track()` after the fact (blocked URIs, context-purge).
The RIGHT approach is to never call `queue_track()` in the first place — keeps songs in local
queue until `play_track_immediate()` is called at the moment they should play.
## Reference Files

- `references/debugging-journey.md` — Full timeline of all attempted fixes and what was learned
- `references/pause-vs-natural-end.md` — Three-way disambiguation (pause vs natural end vs truly ended), the 2026-06-04 fix and its trade-offs
- `references/rate-limit-and-cache-architecture.md` — 2026-06-06 rate-limit fixes + Bug 5 stale-cache race (added after this session)
- `references/!play-handler-routing-bug.md` — 2026-06-06 post-mortem: Bug 5 marker fix was wrong theory. Real bugs are Bug 6 (`!play` handler routing reads stale Spotify state) and Bug 7 (worker can't detect natural song end without queued-song disambiguation). **Read this before touching the song system again.**
- `references/skill-vs-code-reconciliation.md` — cross-cutting lesson: when a skill describes an architecture that doesn't match the actual code, patch the skill to match reality BEFORE planning a fix. Avoids deploying fixes from a wrong mental model.
- `references/stale-cache-autoskip-bug.md` — 2026-06-10 Bug 8: `play_track_immediate` didn't invalidate `_playback_cache`, so the worker's single-tick mark-as-played read stale loop state and corrupted the local queue → 2nd `!play` auto-skipped the 1st. Fix: invalidate cache on every playback-state write + delete the single-tick mark-as-played loop.