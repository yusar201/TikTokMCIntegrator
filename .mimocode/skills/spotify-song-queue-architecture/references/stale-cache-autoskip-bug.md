# Stale-Cache Auto-Skip Bug — Fix (2026-06-10)

**Reported flow (live stream):** Loop song playing. `!play A` → A plays immediately (correct). `!play B` → instead of queuing behind A, B auto-skipped A and played immediately. First `!play` works, second one replaces the current song.

This is a **different** bug from the 2026-06-06 post-mortem (`!play-handler-routing-bug.md`). The handler routing (Bug 6 fix) was already correctly in place. The culprit was in the **worker**, two compounding causes.

## Root cause

`spotify_handler.py` caches playback state for `_PLAYBACK_CACHE_TTL = 2` seconds (`_playback_cache`, `_get_cached_playback`).

1. `play_track_immediate(uri)` started track A on Spotify but **did NOT invalidate `_playback_cache`**. So for up to 2s, `get_current_playback()` still returned the OLD loop song.
2. The worker's `_sync_playback_state` (in `process_song_queue`) had a single-tick rule: *if a queue entry is "playing" but Spotify's `current_uri` differs → mark it "played"*. With the stale cache returning the loop URI ≠ A, it wrongly flipped A "playing"→"played" on the very next tick.
3. Now `!play B` arrives. The handler checks `has_local_playing = any(status=="playing")` → **False** (A was wrongly flipped). So it falls through to the "nothing playing locally" branch, sees Spotify "playing", treats A as loop/non-user content, and calls `play_track_immediate(B)` → B replaces A. Auto-skip.

## The fix (two surgical patches)

**1. Invalidate cache in `play_track_immediate()`** so the next `get_current_playback()` reflects the just-started track:
```python
def play_track_immediate(uri):
    _spotify_put("/me/player/repeat?state=off")
    result = _spotify_put("/me/player/play", {"uris": [uri]})
    _playback_cache["cached_at"] = 0   # <-- invalidate; next read is fresh
    return result
```

**2. Remove the premature single-tick mark-as-played in `_sync_playback_state`.** In the local-only architecture, Spotify NEVER advances to a different track on its own — a single-tick `current_uri != playing_uri` mismatch is ALWAYS either (a) stale 2s cache right after `play_track_immediate`, or (b) the loop song. So acting on it is always wrong. Deleted the `for q in queue: if status=="playing" and uri != current_uri: -> "played"` loop. Natural song-end is still handled robustly by the TWO remaining authorities, which were left untouched:
- the clean-204 branch in `_sync_playback_state` (`not current_uri and last_seen_uri` → played)
- the **3-tick idle counter** in `process_song_queue` (15s of local-playing != Spotify-playing while `has_queued=True` → advance)

## Methodology that worked

- Read the ACTUAL code at handler + worker + cache helper before theorizing. The handler was already fixed; jumping to "rewrite the handler" would have wasted a deploy.
- Traced the user's EXACT reported sequence step-by-step through the real code, then re-traced it WITH the fix to confirm each step resolves (loop → !play A plays → !play B hits `pass`/queue branch → A ends → B plays). This is the rule from the 2026-06-06 post-mortem and it paid off.
- The cache TTL is shared infra — the fix targets the two consumers that misread it, not the TTL value itself (bumping TTL was the wrong fix attempted in 2026-06-06).

## Pitfall for next time

Any function that changes Spotify playback state (`play_track_immediate`, `skip_track`, `play_next_from_queue`) should invalidate `_playback_cache["cached_at"] = 0` immediately after the API call, so the worker never routes off a stale snapshot of the PRIOR track. Check the other mutators if a similar race resurfaces.
