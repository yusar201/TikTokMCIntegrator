# Rate-Limit & Cache Architecture (2026-06-06)

Session context: after deploying the gift asset downloader, the bot hit a
54-minute Spotify rate-limit cooldown (`429: retry in 3284s`). Two compounding
bugs surfaced: the rate limit itself, AND a stale-cache race that prevented
auto-advance after `!skip`/natural song end.

## The 54-minute Cooldown — Root Cause

Spotify's rate limit is **burst-sensitive**, not just volume-sensitive. A single
~30s burst of `/me/player` calls can trigger a 30-60 minute global cooldown
even when the long-term rate is well under budget.

**Burst sources** (pre-fix):
- Worker polls every 5s = 12 calls/min on `/me/player`
- `get_current_playback()` from `/api/spotify/status` UI poll = +12 calls/min
- `!play` → search + add + (sometimes) queue update = 3-5 calls in <1s
- `!skip` → `skip_track` + `play_next_from_queue` → `play_track_immediate` = 4 calls in <1s
- Gift bursts: 5 gifts in 1 second = 5× search calls, 5× device/player checks

The combination → 30+ calls in a 1s window during gift bursts. Spotify saw this
as abusive, returned 429 with 30+ min Retry-After.

## The Three Fixes (all in `spotify_handler.py`)

### Fix A: Centralize HTTP via `_spotify_request`

Before: 3 separate functions (`_spotify_get`/`_post`/`_put`), each with a
copy of the 429/401/403/404/204 handling logic. ~100 lines duplicated 3x.

After: one `_spotify_request(method, endpoint, params, data, expect_json)`
that handles all status codes. The 3 method-specific helpers are one-liners.

```python
def _spotify_get(endpoint, params=None):
    result = _spotify_request("GET", endpoint, params=params, expect_json=True)
    # CRITICAL compat shim — old GETs returned error dict for empty 200,
    # new shared helper returns success. Re-wrap so all `if "error" in data`
    # checks in callers continue to work.
    if isinstance(result, dict) and "success" in result and "error" not in result:
        return {"error": "Spotify returned 200 with empty response"}
    return result
```

The compat shim is what makes the refactor non-breaking. Without it, callers
like `_real_get_current_playback` (which does `data.get("is_playing", ...)`)
would hit `AttributeError: 'bool' object has no attribute 'get'` on empty 200
responses.

### Fix B: Per-endpoint throttle

```python
_endpoint_last_call = {}  # endpoint -> last_call_epoch
_endpoint_throttle_lock = threading.Lock()
_ENDPOINT_MIN_INTERVAL = 0.5  # 500ms

def _throttle_endpoint(endpoint):
    with _endpoint_throttle_lock:
        last = _endpoint_last_call.get(endpoint, 0)
        wait = _ENDPOINT_MIN_INTERVAL - (time.time() - last)
        if wait > 0:
            time.sleep(min(wait, 1.0))  # cap at 1s
        _endpoint_last_call[endpoint] = time.time()
```

Called at the top of `_spotify_request` BEFORE the actual HTTP call. Different
endpoints have independent throttle slots, so `/me/player` throttling doesn't
block `/me/player/devices`.

**Why per-endpoint and not global**: a global throttle would serialize all
Spotify calls, making the UI feel sluggish. Per-endpoint throttling targets
the actual 429 trigger (same-endpoint burst) while keeping cross-endpoint
throughput high.

### Fix C: Bump `_PLAYBACK_CACHE_TTL` 2s → 5s

Worker polls every 5s. With 2s cache TTL, the cache NEVER serves a useful
purpose — every worker tick is a cache miss → real API call. Bumping to 5s
makes the cache actually save calls (~60% reduction in `/me/player` hits).

**General rule**: `CACHE_TTL >= worker_poll_cadence`. Otherwise the cache is
decorative. If you want even fewer API calls, bump the cache higher (10s, 30s),
but be aware that user-perceived "current playing" display gets laggier.

## Bug 5: Stale-Cache Race After `play_next_from_queue`

User reported: "after a while, the song stops auto-playing the next song
in the queue even though there's a song in the queue. So I had to do `!skip`
manually to play the next song."

**Why it happens**:

The worker's "is the queue stuck?" branch logic (`process_song_queue`):
```python
if has_playing:
    # Stale cache from !skip — wait
```

This branch fires when:
- `is_playing == False` (Spotify says nothing is playing)
- `has_queued == False` (no songs waiting in local queue)
- `has_playing == True` (one song is in "playing" state in our local queue)

The intent was: "!skip or natural end just started a new track, but our
playback cache hasn't caught up yet. Don't override it."

The flaw: Spotify's playback cache lags 2-5s. If we use a 5s cache TTL
(Fix C above), the cache is even MORE stale right when we need it most —
right after `play_next_from_queue()` just called `play_track_immediate()`.

**Sequence that triggers the bug:**
1. Song A ends naturally. Tick 1: `_sync_playback_state` marks A as played.
   Worker sees `has_queued=True`, calls `play_next_from_queue(B)`. B is marked
   "playing" in queue. `play_track_immediate(B)` returns success.
2. Tick 2 (5s later): `get_current_playback()` returns the cache from tick 1
   OR earlier — showing A as the current item, `is_playing=False`. Queue shows
   B as "playing". Worker: `has_playing=True, has_queued=False, is_playing=False`.
   Falls into "stale cache, waiting" branch. Logs and waits.
3. Tick 3 (5s later): cache is fresh now, showing B playing, `is_playing=True`.
   Worker takes the `if is_playing and current_uri` path (not the has_playing
   branch). All good.

**Where it goes wrong**: between tick 2 and tick 3 (5s window), if the user
sends another `!skip` or `!play` → the marker logic in step 2 collides with
the new action, and the worker gets confused.

**Fix: "freshly started" marker**

```python
# In play_next_from_queue, after successful play_track_immediate(uri):
global _last_worker_play_uri, _last_worker_play_time
_last_worker_play_uri = uri
_last_worker_play_time = time.time()

# In process_song_queue has_playing branch, BEFORE falling through to "wait":
playing_uri = next(
    (q.get("spotify_uri") for q in queue if q.get("status") == "playing"),
    None,
)
recently_started = (
    playing_uri
    and _last_worker_play_uri == playing_uri
    and (time.time() - _last_worker_play_time) < 10
)
if recently_started:
    # Trust the marker — track IS playing, cache just hasn't caught up
    continue
```

10-second lifetime covers worst-case 5s cache lag + worker 5s tick + margin.
If Spotify genuinely never started the track, the marker expires and normal
logic resumes — no permanent deadlock.

**Set only in `play_next_from_queue`**: this function is the single chokepoint
for both natural-end (worker calls it) and `!skip` (handler calls it). Manual
`!play` paths don't set the marker because they're direct user actions; the
worker doesn't need to "trust itself" for those.

## Verification Steps

After deploying all 3 fixes, smoke test:

1. **Burst test**: queue 5 songs back-to-back via `!play` from different users
   in a 1s window. Watch console — no 429s, all songs play in order.
2. **Stale-cache test**: queue 1 song. Wait for natural end. Confirm next song
   plays within 5s WITHOUT manual `!skip`.
3. **Cache test**: open `/api/spotify/status` in a separate tab, refresh every
   1s. Confirm data updates at most every 5s (not instantly). This proves cache
   is working.
4. **Throttle test**: send 3 `!play` requests in 1s from different users.
   Watch console logs — second and third requests should show 500ms gaps
   in HTTP timing (not instant).
5. **Regression test**: pause Spotify manually. Wait 30s. Confirm worker does
   NOT auto-resume the loop song (Bug 4 invariant).

## Files Touched

- `spotify_handler.py` — helpers + globals + worker branch
- `static/script.js` — console scroll fix (separate UX bug, same session)
- `.hermes/plans/2026-06-06-spotify-rate-limit-fix.md` — execution plan
