# Spotify Song Requests for TikTokMCIntegrator

Session learning: when adding a TikFinity-style song request feature, build it as a class of dashboard + TikTok chat + Spotify OAuth integration, not as one-off chat command logic.

## Target UX

Add a new dashboard sidebar tab named **Song**. Keep it comparable to TikFinity's Song Requests panel but adapted to TikTokMCIntegrator:

- Spotify connection/status card
- Editable command names
- Per-command permissions
- Queue/history controls
- Testing area
- Compact `/overlay/song` browser source

## Editable Commands

Commands must be user-editable from the Song tab, not hardcoded:

- Play command, default: `!play`
- Skip command, default: `!skip`
- Revoke/cancel command, default: `!revoke`

Normalize command matching carefully: strip leading/trailing whitespace, compare case-insensitively for the command token, and preserve the rest of the message as the song query.

## Permission Model

Use per-command permission blocks. Do not apply one global permission to all song commands.

Recommended defaults:

- `play`: everyone allowed
- `skip`: VIP + whitelist only
- `revoke`: requester can revoke their own pending song

Support categories as OR conditions: if any enabled category matches, access is granted.

Suggested config shape:

```json
{
  "permissions": {
    "play": {
      "everyone": true,
      "followers": false,
      "friends": false,
      "members": false,
      "superfans": false,
      "vip": false,
      "mods": false,
      "whitelist": []
    },
    "skip": {
      "everyone": false,
      "followers": false,
      "friends": false,
      "members": false,
      "superfans": false,
      "vip": true,
      "mods": false,
      "whitelist": ["ikhito"]
    }
  }
}
```

Whitelist entries should match TikTok `unique_id` / @handle, not nickname. Normalize by lowercasing and stripping an optional leading `@`.

## Queue Architecture (LOCAL-FIRST)

**Keep everything in the local queue. NEVER push songs to Spotify's queue via `queue_track()` proactively.**

This is the critical design decision. Spotify has no API to remove an item from its queue — once pushed, it cannot be undone. Previous approaches (blocked URIs with polling, context-purge via `PUT /me/player/play`) all had side effects. The correct solution is to **remove the root cause**: don't push to Spotify at all.

### How it works

- `song_queue.json` stores pending requests with status `"queued"`
- `song_history.json` for completed/skipped requests  
- `song_config.json` for non-secret settings
- `song_spotify_token.json` or equivalent local secret store for OAuth tokens

No `song_blocked_uris.json` needed — it's unused in the local-first architecture.

### Flow

1. **!play → user song already playing**: `add_to_queue()` only. Status stays `"queued"`. NO `queue_track()` call. The song is 100% local until it's actually time to play.

2. **!skip**: Calls `skip_track()` (skips current on Spotify) then immediately `play_next_from_queue()`. This function gets the next `"queued"` song from the local queue and calls `play_track_immediate(uri)` — replacing Spotify's playback context directly. Instant, no waiting.

3. **!revoke**: Removes from local queue. Always instant. No Spotify API calls.

4. **Song ends naturally**: The worker (5s cadence) detects nothing playing, finds `"queued"` songs in local queue, calls `play_next_from_queue()`.

5. **Loop song**: When no user songs are queued and nothing is playing, worker auto-resumes the configured `loop_song_uri`.

### key functions

- `spotify_handler.py::play_next_from_queue()` — reads next `"queued"` entry, calls `play_track_immediate(uri)`, marks as `"playing"`, saves queue. Used by both !skip handler and worker.
- `spotify_handler.py::remove_from_queue()` — just pops from local list. No Spotify API involvement.
- `spotify_handler.py::process_song_queue()` — worker at 5s cadence (not 30s). Syncs playback state, transitions to next queued song or auto-resumes loop song.

### Pitfalls

- **NO `queue_track()` for pre-pushing.** Once in Spotify's queue, it can't be removed.
- **NO blocked URIs (`song_blocked_uris.json`).** Polling-based detection means the wrong song plays for seconds before being skipped. User explicitly rejected this.
- **NO context-purge** (`PUT /me/player/play` with `position_ms`). Replaces the entire playback context, can restart the current track on some devices. Queuing the loop song as a fallback after purge breaks queue ordering.
- **NO fallback loop song in Spotify's queue.** If you `queue_track(loop_uri)` after revoking the last song, that puts the loop song ahead of any future user-requested songs.
- **Worker at 5s** for responsiveness. Cached playback (`_PLAYBACK_CACHE_TTL=2s`) means actual API calls are ~once every 2s even with frequent checks.

### Why this matches TikFinity

TikFinity never pushes to Spotify's queue either. It keeps everything local and uses `play_track_immediate` to start songs directly. Revoke is just removing from their internal list — always instant, always clean.

## Spotify OAuth / API

Use OAuth scopes for playback control:

- `user-read-playback-state`
- `user-modify-playback-state`
- `user-read-currently-playing`

Spotify Premium and an active Spotify device are required for reliable playback/queue control. The dashboard should surface status clearly: connected/disconnected, active device name, playback state, and API errors.

Spotipy is acceptable for token refresh and OAuth convenience; if adding it to TikTokMCIntegrator, update `requirements.txt`, PyInstaller spec hidden imports if needed, and rebuild the exe.

## Compact Song Overlay

Add `/overlay/song` as a separate OBS browser source. It should follow Khito's overlay preferences:

- Compact and corner-friendly, roughly 320-380px wide
- Hidden completely when there is no song data; no placeholder text
- Readable text even when scaled down
- Center-aligned visual feel, without wasting space
- Dark translucent/glass card, rounded corners, subtle border/shadow
- Album art on the left, text/progress on the right
- Two-row Spotify mini-widget style: current song + optional up-next row

Reference layout:

```text
[cover]  NOW PLAYING
         Track Title
         0:30 ━━━━━──── 1:25

[cover]  UP NEXT
         Next Track - Artist
         by requester · starts in 0:55
```

Behavior:

- If only current song exists, show only current row
- If queue exists, show next row too
- If Spotify disconnected/no track/no queue, render nothing
- If album art is unavailable, use a compact gradient/music-note placeholder
- Progress and "starts in" should come from current playback status and remaining duration

## Dashboard Implementation Notes

Song tab sections:

1. Spotify Connection: connect/disconnect, status, active device, playback state
2. Commands: editable play/skip/revoke command strings
3. Permissions: per-command checkboxes + whitelist textarea, one username per line
4. Queue / History: pending list, remove, clear, requester, track metadata
5. Testing: search a song, enqueue a test track, skip test

For TikTokMCIntegrator, frontend/static/profile files must be synced to both source and release `_internal` copies when shipping without rebuild. Backend Python or dependency changes require rebuilding the exe.