# 2026-06-03: Song Queue Architecture Migration

## What Changed

The entire Spotify song queue system was rewritten. The old architecture pushed songs to
Spotify's queue via `queue_track()` — which CANNOT be undone (no "remove from queue" API).
This caused persistent bugs with revoke (song still played), skip (glitchy transitions),
and natural song endings (deadlock).

## Old Architecture (deprecated Jun 2026)

- `queue_track(uri)` called immediately on !play → status "pushed"
- Revoke → blocked URI list → worker auto-skips when song starts playing (up to 30s delay)
- Context-purge approach attempted (replaced playback context to clear queue) — caused side effects

## New Architecture (current)

Songs are NEVER pushed to Spotify's queue. See `spotify-song-queue-architecture` skill.

**Key functions:**
- `play_next_from_queue()` — Finds next "queued" song, calls `play_track_immediate()` to play it NOW
- `remove_from_queue()` — Just removes from local `song_queue.json`. Always instant.
- `process_song_queue()` — Worker polls every 5s. Detects natural end via `_sync_playback_state()`.

**!play handler changes:**
- Case 2 (user song playing): `add_to_queue()` only. NO `queue_track()`. Song stays local.

**!skip handler changes:**
- `skip_track()` + `play_next_from_queue()` — instantly plays next from local queue.

## Critical Bug Fixes Discovered

### 1. Natural end deadlock
`_sync_playback_state()` must check `is_playing=False` for the same-track URI match.
Spotify returns finished track as `item` with `is_playing=False` (URI non-None).
Old code only matched URI mismatch — same URI was silently skipped → song stayed "playing" forever.

### 2. Worker race with !skip
`get_current_playback()` uses 2s cache. After !skip calls `play_next_from_queue()`, cache
may still be stale. Worker checks queue for `"playing"` status before deciding to auto-resume
loop song.

### 3. Paused-song aggression
Worker only auto-resumes loop song on 204 No Content (no item). If a paused track exists
(current_uri is set but is_playing=False), the worker leaves it alone.

## Deprecated Files (keep for now, no longer used)
- `song_blocked_uris.json` — unused (no songs pushed to Spotify queue)
- `_auto_skip_blocked_uris()` — replaced by play_next_from_queue
- `_push_queued_songs()` — obsolete, songs not pushed pre-emptively
- `_purge_and_repush()` — removed, caused side effects
