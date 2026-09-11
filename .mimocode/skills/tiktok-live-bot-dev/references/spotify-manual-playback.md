# Spotify Web API: Manual Playback Integration

Patterns for integrating TikTokMCIntegrator-style song requests with a Spotify
player that's also controlled manually (e.g. background music started from
Spotify desktop before the stream). Covers the album-context trap, the
3-state decision matrix for `!play`, and auto-resume of a configured loop song.

## The core problem (album context trap)

When the user manually plays a song from an album in Spotify desktop with
`repeat_state="track"` and then the bot does `!play`, two things collide:

1. **Album context persists.** The Spotify player's context is the album URI.
   Calling `/me/player/queue?uri=X` appends X to the queue, but `/me/player/next`
   walks the **album context first**, so the user's song is stuck behind an
   infinite album loop.
2. **`repeat_state="track"` carries over.** Even when something does advance
   (e.g. a manual skip), the new track inherits `repeat_state="track"` from
   the previous one. Result: the wrong song also loops.

The "old behavior" the user remembers (loop song resumes after user song ends)
was **not a feature** — it was this bug working in reverse, because Spotify had
no more queue and the `repeat_state="track"` was still on the loop song. When
the fix lands, that emergent behavior is lost and must be **explicitly
replaced** with an auto-resume mechanism.

## The 3-state decision matrix for `!play`

Every `!play` handler (both the real chat path in `minecraftDiamond.py` and
the `/simulate/play` debug path in `routes/spotify.py`) must branch on:

| State | Action | Why |
|---|---|---|
| **Nothing playing** (`is_playing` False OR `item` None) | `queue_track(uri)` | Spotify is idle; queue will start immediately on next sync |
| **User song already playing** (current URI is in local queue with status `playing`/`pushed`) | `queue_track(uri)` | Just append; do NOT replace — replacing mid-play causes the "auto-skip to queued song" bug the user reported |
| **Loop / non-user song playing** (current URI NOT in local queue) | `play_track_immediate(uri)` | Breaks the album context so `!skip` walks the user queue |

The decision signal is **NOT** "is something playing" — it's "is the playing
track a user request from our queue." Helper:

```python
def _is_user_song_playing():
    """True if the currently playing Spotify track is a user-requested song."""
    playback = get_current_playback()
    if "error" in playback or not playback.get("is_playing"):
        return False
    current_item = playback.get("item")
    if not current_item:
        return False
    current_uri = current_item.get("uri")
    if not current_uri:
        return False
    queue = load_queue()
    return any(
        q.get("spotify_uri") == current_uri and q.get("status") in ("playing", "pushed")
        for q in queue
    )
```

### Pitfall: don't replace context on the 2nd `!play`

First version of the fix branched on `is_playing` alone:

```python
# WRONG — fires on EVERY !play after the first one
if not playback.get("is_playing") and not playback.get("item"):
    sh.queue_track(track["uri"])
else:
    sh.play_track_immediate(track["uri"])  # ← jumps to new track mid-playback
```

User reported: "when i tried to simulate a !play, it auto skip to the song
queued" and "after the queued song played, and i tried to simulate play again,
it acted the same, auto skip the current play song even tho it's not loop song."

The `_is_user_song_playing()` check fixes this. Both `minecraftDiamond.py` and
`routes/spotify.py` need the same 3-branch fix applied.

## `play_track_immediate(uri)` — the context-breaker

```python
def play_track_immediate(uri):
    """Play a track immediately, replacing the current context.

    Disables repeat first so the new track doesn't auto-loop, then calls
    /me/player/play with NO context_uri (just uris=[uri]) so the track plays
    standalone. After this call, /me/player/next goes to the user queue,
    not the previous album context.
    """
    _spotify_put("/me/player/repeat?state=off")
    return _spotify_put("/me/player/play", {"uris": [uri]})
```

Requires `_spotify_put()` helper — same shape as existing `_spotify_post()`,
just `req.put(...)` instead of `req.post(...)`. Mirror the error handling
(401/403/404/429 paths) exactly.

## `skip_track()` — also clear repeat

```python
def skip_track():
    """Skip to next track. Also disables repeat_state='track' so the next song
    doesn't inherit the loop from the previous track."""
    _spotify_put("/me/player/repeat?state=off")
    return _spotify_post("/me/player/next")
```

## Auto-resume loop song (replaces lost emergent behavior)

When all user songs finish and Spotify goes idle, the original (buggy) code
"resumed" the loop because the album context was still active with repeat
on. After the fix, that doesn't happen — so we add an explicit auto-resume
in the queue worker:

```python
# In process_song_queue(), every ~30s after the normal sync steps:
queue = load_queue()
has_active_user_songs = any(
    q.get("status") in ("queued", "pushed", "playing")
    for q in queue
)
if not has_active_user_songs and not playback.get("is_playing"):
    loop_uri = cfg.get("loop_song_uri", "").strip()
    if loop_uri:
        _log_worker(f"Auto-resuming loop song: {loop_uri}")
        play_track_immediate(loop_uri)
```

Add `loop_song_uri` to `get_default_config()` in `spotify_handler.py` (default
to a known loop song URI) and the user's `song_config.json` will be merged
on top via `load_config()`. Set to `""` to disable auto-loop.

## Spotify API fields worth knowing

`GET /me/player` returns (alongside the obvious stuff):

- `repeat_state`: `"off" | "track" | "context"` — transient player state, NOT
  a track property. Persists across `next()` calls within a device. Reset by
  `PUT /me/player/repeat?state=off`.
- `shuffle_state`: `bool` — same story.
- `context.uri`: the **context_uri** the player is currently walking. When
  this is an album URI and you `queue_track`, your song gets stuck behind
  the album's `repeat_state="track"` loop.
- `item.context.uri` (inside the `item` object): same thing at the track level.

**Important:** `repeat_state` is **NOT a property of a track, playlist, or
user profile.** It's transient device state. There is no API to query "is
track X set to loop" ahead of time — only the current player's live state.

## Verification flow after deploying

1. Restart the app (the new `play_track_immediate`, `_is_user_song_playing`,
   and `_spotify_put` won't be loaded until restart).
2. Start Spotify desktop, manually play the loop song from the album, loop on.
3. `Simulate !play <some song>` → should replace and play user's track.
4. `Simulate !play <another song>` → should **just queue** (no mid-play jump).
5. Wait for the user song to end → after ~30s, loop song should auto-resume.
6. `GET /api/spotify/player` → response now includes `repeat_state` and
   `shuffle_state` (add these to `_real_get_current_playback()` return dict
   if not already exposed).

## File touchpoints in TikTokMCIntegrator

- `spotify_handler.py`: add `_spotify_put`, `play_track_immediate`,
  `_is_user_song_playing`, the `loop_song_uri` config field, the auto-resume
  block in `process_song_queue`, and `repeat_state`/`shuffle_state` in
  `_real_get_current_playback()`.
- `minecraftDiamond.py`: 3-branch `if/elif/else` in the real `!play` path
  (around line ~985, in the chat comment handler).
- `routes/spotify.py`: same 3-branch fix in `/simulate/play` (around line ~256).
- `song_config.json`: ensure `loop_song_uri` key exists (idempotent add
  via Python if missing — don't clobber other user settings).

## Build & deploy

Follow the existing `references/build-deploy.md` protocol. This is pure
backend Python (no frontend files changed), so steps 1-3 (build + exe copy
+ _internal copy) are sufficient. The frontend copy steps (4-5) are
belt-and-suspenders and harmless to run anyway.
