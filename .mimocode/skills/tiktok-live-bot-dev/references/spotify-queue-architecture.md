# Spotify Queue Architecture — Final Working Version

## Core Principle
**Songs are NEVER pushed to Spotify's queue via `queue_track()`.** They sit in `song_queue.json` with status `"queued"` until ready to play. This eliminates the root cause of all revoke/skip bugs — Spotify has no "remove from queue" API.

## Why Not queue_track?
`queue_track()` adds a track to Spotify's hidden "next up" queue. Once added, it CANNOT be removed via any API. All workarounds (blocked URIs that get auto-skipped, context-replace to clear the queue) are bandaids with side effects.

## Key Functions (spotify_handler.py)

### `play_next_from_queue()`
- Finds the next `"queued"` song in local `song_queue.json`
- Calls `play_track_immediate(uri)` to play it NOW on Spotify
- Marks previous `"playing"` as `"played"` + adds to history
- Used by: `!skip` handler AND worker (on natural song end)

### `remove_from_queue()`
- **Always instant** — just removes from local JSON file. No Spotify API calls.
- No blocked URIs, no context-purge, no fallback mechanisms needed.

## Worker (process_song_queue)
- Polls every **5 seconds** (previously 30s — more responsive)
- **Step 1**: `_sync_playback_state()` — detects when a song ended naturally
- **Step 2**: Check playback + queue:
  - Nothing playing + queue has `"playing"` → stale cache (from !skip), **wait**
  - Nothing playing + queue has `"queued"` → song ended naturally, **play_next_from_queue()**
  - Nothing playing + queue empty → auto-resume loop song (only on 204 No Content)

## !play Handler (minecraftDiamond.py + routes/spotify.py)
- **Case 1** (nothing playing): `play_track_immediate(uri)` — plays immediately
- **Case 2** (user song playing): **`add_to_queue()` only** — NO `queue_track(uri)`. Status stays `"queued"`.
- **Case 3** (loop/non-user song): `play_track_immediate(uri)` — replaces context

## !skip Handler
- `skip_track()` + `play_next_from_queue()` — instantly plays next from local queue

## Known Pitfalls / Fixed Bugs

### Bug 1: Natural song end deadlock
**Problem**: `_sync_playback_state` didn't mark finished songs as "played". When a track ends, Spotify returns it as `item` with `is_playing=False` but the same URI. Old code only marked DIFFERENT URIs as "played" — same URI was skipped. Song stayed "playing" forever → worker waited forever.

**Fix**: Check `not is_playing`. If queue entry matches current URI but Spotify says not playing → song finished → mark `"played"` + `break`.
```
if q.get("status") == "playing":
    if q.get("spotify_uri") != current_uri or not is_playing:
        q["status"] = "played"
        if q.get("spotify_uri") == current_uri:
            break  # Same track finished — don't re-mark as "playing"
```

### Bug 2: Worker race with !skip
**Problem**: After !skip → B starts → worker's 2s cached playback shows "nothing" → worker auto-resumes loop song, overwriting B.

**Fix**: Distinguish `has_playing` (status "playing" = !skip just fired, cache is stale) from `has_queued` (song ended naturally). Only auto-resume when both are false.

### Bug 3: Context-purge approach (wrong)
**Attempt**: Replace Spotify context to clear its queue. Had side effects: restarted tracks, wrong fallback ordering. **Replaced** by local-only queue architecture.

### Bug 4: Auto-pause interruption
**Problem**: User pauses Spotify → worker auto-resumes loop song every 5s.

**Fix**: Only auto-resume on 204 No Content (truly idle). If a paused track exists (current_uri set, not playing), leave it alone.

## Build & Deploy
- `spotify_handler.py`, `minecraftDiamond.py`, `routes/spotify.py` all modified
- 5 builds deployed 2026-06-03 during debugging
- Build command: `cmd.exe /c build.bat` then copy exe + _internal + frontend to release/
