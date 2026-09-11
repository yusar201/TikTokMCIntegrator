# Song Queue Architecture — Local-Queue Pattern

**Applies to:** TikTokMCIntegrator (`spotify_handler.py`, `minecraftDiamond.py`, `routes/spotify.py`)

## Core Principle

Songs stay in the **local queue file** (`song_queue.json`) until they're ready to play.
**Never** push songs to Spotify's internal queue via `queue_track()` proactively —
Spotify has NO "remove from queue" API, so pushed songs cannot be cleanly revoked.

## Architecture

```
!play → add_to_queue() → song sits in song_queue.json with status "queued"
                            (NO Spotify API call)

Worker (every 5s):
  _sync_playback_state() → detects when current song ended
                         → marks finished song as "played" in queue
                         → adds to history
  If nothing playing AND queue has "queued" songs:
    → play_next_from_queue()
       → play_track_immediate(next_uri)  ← ONLY push at play time
       → marks as "playing"

!skip  → skip_track() + play_next_from_queue()
       → instantly plays next queued song

!revoke → remove from local queue only
        → ALWAYS instant, no Spotify API calls
```

## Key Functions

### `play_next_from_queue()` (`spotify_handler.py`)
- Finds first song with status "queued"
- Calls `play_track_immediate(uri)` — replaces context, starts playing NOW
- Marks previous "playing" as "played", new song as "playing"

### `_sync_playback_state()` (`spotify_handler.py`)
- Gets current playback from Spotify
- **CRITICAL BUG PATTERN**: When a track finishes naturally, Spotify still returns
  the finished track as `item` with `is_playing=False`. The URI is NOT None.
  The `is_playing` flag must be checked to detect natural ends — not just URI changes.
- Marks previous "playing" song as "played" when:
  1. A different track is now playing (`uri != last_seen_uri`), OR
  2. The same track is shown but not playing (`is_playing=False`)

## Common Pitfalls

### 1. Don't proxy-push to Spotify queue

**Wrong:** `queue_track(uri)` on !play → revoke can't remove from Spotify's queue.
**Right:** Keep songs local. Only `play_track_immediate()` at play time.

### 2. Worker race condition with 2s playback cache

`get_current_playback()` uses a 2-second cache. After `!skip` calls
`play_next_from_queue()`, the song gets status `"playing"` in the queue immediately,
but the worker's cached playback may still show "nothing playing".
**Fix:** Worker checks `has_playing` (queue status) separately from `has_queued`.
If queue says "playing" but playback says "nothing" → cache is stale, wait.

### 3. `play_track_immediate()` side effects

`play_track_immediate(uri)` calls:
```python
_spotify_put("/me/player/repeat?state=off")  # disables repeat
_spotify_put("/me/player/play", {"uris": [uri]})  # replaces context
```
This replaces the entire playback context with just `[uri]`. After the song ends
naturally, Spotify has no next track in context and pauses. The worker detects
this within 5s and advances to the next queued song.

### 4. Natural song end detection

Spotify's API behavior: when a track finishes, `GET /me/player` returns the
finished track as `item` with `is_playing=False`. The `progress_ms` may equal
`duration_ms`. This can persist for several seconds.

**`_sync_playback_state` must check `is_playing`**, not just URI changes:
```python
# Correct: mark as "played" when is_playing=False even if same URI
if q.get("status") == "playing":
    same_track = q.get("spotify_uri") == current_uri
    if q.get("spotify_uri") != current_uri or not is_playing:
        q["status"] = "played"
```

## Variables / Config

- `loop_song_uri`: configured in `song_config.json`. Auto-resumed by worker when
  queue is empty and nothing is playing.
- `song_queue.json`: local queue file. Status values: `"queued"`, `"playing"`,
  `"played"`, `"skipped"`.
- Worker sleep: 5 seconds (vs original 30s — changed for snappy transitions).
