# Complete Bug Journey — Spotify Queue (Jun 3, 2026)

## Timeline (in order of attempts)

### Attempt 1: Blocked URI + 30s worker
**Problem**: Revoked song already in Spotify's queue (via queue_track). Can't remove from queue.
**Fix**: Add blocked URI list → worker checks every 30s → skip_track() when detected.
**Result**: Wrong song plays for 20-30 seconds before skipping. ❌

### Attempt 2: Rapid-poll blocked URIs (3s cadence)  
**Fix**: After 30s main cycle, enter 3s rapid-poll if blocked URIs exist.
**Result**: Still 3-6 seconds of wrong song. User: "even only couple seconds" unacceptable. ❌

### Attempt 3: Context-purge (replace playback context)
**Fix**: `PUT /me/player/play { "uris": [current_uri], "position_ms": progress_ms }` to clear Spotify's queue, then re-push remaining songs.
**Problems**: Caused side effects (track restarts, wrong fallback ordering).
**User reaction**: "it piss me off man" ❌

### Attempt 4: Skip safety + fallback loop song
**Fix**: After !skip, check playback → if nothing playing, play loop song.
**Result**: Mitigated some edge cases but context-purge still broke things. ❌

### Attempt 5 (FINAL): Local-only queue (correct approach)
**Fix**: Remove `queue_track()` entirely. Songs sit in local `song_queue.json` until played via `play_track_immediate()`.
- `remove_from_queue()` — just remove from local file. No Spotify calls. Instant.
- `play_next_from_queue()` — new function. Calls `play_track_immediate(uri)`.
- Worker polls 5s, manages transitions only (no push).
- !skip = `skip_track()` + `play_next_from_queue()`.

**Then discovered Bug A**: Natural song end deadlock
- `_sync_playback_state` never marked finished songs as "played"
- Spotify returns finished track as `item` with `is_playing=False` (URI still set)
- Old check only matched URI mismatch → same URI silently skipped → song stayed "playing" forever

**Fix**: Check `not is_playing` for same-track match → mark as "played" + break.

**Then discovered Bug B**: Worker race with !skip  
- 2s cache stale after `play_next_from_queue`
- Worker saw idle playback + "playing" in queue → thought cache stale, waited
- Then saw no "queued" songs → auto-resumed loop song overwriting current

**Fix**: Worker checks `"playing"` status in queue before auto-resuming loop song.

**Then discovered Bug C**: Paused-song aggression
- Worker auto-resumed loop song every 5s when user paused Spotify

**Fix**: Only auto-resume on 204 No Content (no item). Leave paused tracks alone.

### Key Lesson
Never try to undo what Spotify's queue API does. Instead, never use `queue_track()` at all.
Use `play_track_immediate()` at the moment the song should play. This eliminates ALL revoke/skip/end bugs.
