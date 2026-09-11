# Spotify Playback Gotchas — TikTokMCIntegrator

Three related bugs that kept biting the song-request system (June 2026). All stem from the same misunderstanding: **Spotify's Web API has a "playing context" (album/playlist/standalone) and a device-level `repeat_state` flag, both of which silently override what `/me/player/next` does.**

## Background: how the user starts a stream

Khito starts streams by manually clicking play on a single song from an album in Spotify desktop, with `repeat_state="track"` (loop the one song). The bot (`minecraftDiamond.py`) runs as a subprocess; Flask runs in the parent. Both write to `song_queue.json` to share state.

The bot listens for `!play <query>`, searches Spotify, adds the track to a local queue, and pushes it to Spotify. The dashboard `/api/spotify/simulate/play` endpoint does the same for the overlay debug UI.

---

## Bug 1: Album context hijacks `!skip` and queue order

**Symptom:** Viewer uses `!play never gonna give you up`. The song gets pushed to Spotify's queue (via `/me/player/queue`) but **never plays**. `!skip` advances to the *next album track*, not the user's request. The viewer is stuck behind the album forever.

**Root cause:** Manually playing a song from an album in Spotify desktop makes Spotify store the album URI as the player's **context**. Two facts about contexts:

1. `/me/player/queue?uri=...` appends the track to Spotify's queue, but the queue plays **after** the context exhausts.
2. `/me/player/next` walks the context first, not the queue.

With `repeat_state="track"` on the loop song, the context **never exhausts** — the loop song repeats forever and the queue is unreachable.

**The "loop song resumes after user song ends" behavior Khito relied on was also a side effect of this bug** — Spotify fell through to the next album track (the loop song) after the user's track ended. Once fixed, Spotify just stops. We had to add explicit auto-loop-back.

**Fix:** Replace context on `!play` from a non-user state. Use `/me/player/play` with `{"uris": [track_uri]}` and **no `context_uri`**. The track plays standalone, so `next` falls through to the queue.

```python
def play_track_immediate(uri):
    _spotify_put("/me/player/repeat?state=off")  # see Bug 2
    return _spotify_put("/me/player/play", {"uris": [uri]})
```

---

## Bug 2: `repeat_state="track"` carries across skips

**Symptom:** Even after Bug 1's fix, the next song after a skip also loops. So `!skip` on the loop song → plays the user's queued song → that song loops forever.

**Root cause:** `repeat_state` is **device state**, not track state. It persists across `/me/player/next` calls. If a track was looped, the next track inherits the loop.

**Fix:** Always disable repeat immediately before `next` for workflow-driven skips:

```python
def skip_track():
    _spotify_put("/me/player/repeat?state=off")  # critical
    return _spotify_post("/me/player/next")
```

Khito wants `repeat_state` exposed in the dashboard so he can see it (and reset it from a button if Spotify's desktop app leaves it stuck on). Field added to `_real_get_current_playback()` return.

---

## Bug 3: `!play` is a 3-way decision, not 2-way

**Symptom:** After Bug 1+2 fixes, the first `!play A` correctly replaces the loop song with A. But the second `!play B` (while A is playing) **auto-skips to B**, instead of just queueing it behind A.

**Root cause:** My initial fix was a 2-way branch:
- Nothing playing → `queue_track`
- Something playing → `play_track_immediate` (replace context)

The "something playing" branch is **also taken when A is already playing** — replacing context mid-A is what the user perceived as "auto-skip".

**Fix:** Three branches. Use a helper that checks if the currently-playing track is already a user request (in the local queue with status `playing` or `pushed`):

```python
def _is_user_song_playing():
    playback = get_current_playback()
    if not playback.get("is_playing"):
        return False
    current_uri = (playback.get("item") or {}).get("uri")
    if not current_uri:
        return False
    queue = load_queue()
    return any(
        q.get("spotify_uri") == current_uri and q.get("status") in ("playing", "pushed")
        for q in queue
    )
```

Then in the `!play` handler:

```python
if not playback.get("is_playing") and not playback.get("item"):
    # (a) nothing playing → queue + mark as now-playing
    sh.queue_track(track["uri"])
    sh.mark_as_playing(new_pos)
elif sh._is_user_song_playing():
    # (b) a user-requested song is already playing → just append, stay "pushed"
    sh.queue_track(track["uri"])
    # (do NOT call mark_as_playing — worker promotes later)
else:
    # (c) loop / non-user song playing → replace context
    sh.play_track_immediate(track["uri"])
    sh.mark_as_playing(new_pos)
```

**Critical detail:** In branch (b), set the new track's status to `pushed`, **not** `playing`. Manually setting `playing` produces a second `playing` entry while the previous one is still `playing` → the dashboard/overlay drops the new track. The 30s `_sync_playback_state` worker promotes `pushed` → `playing` when Spotify actually starts the track.

**This logic must live in BOTH `minecraftDiamond.py:handle_song_request` AND `routes/spotify.py:simulate_play`.** If only one is patched, the other path produces inconsistent state.

---

## Bug 4 (follow-on): `!revoke` must NOT call `skip_track()`

**Symptom:** After Bug 3's fix, `!revoke` on a `pushed` song now does the wrong thing — it skips the **currently playing** track (which may be a different viewer's request or the loop song), instead of just removing the revoked song from the queue.

**Root cause:** The original `!revoke` handler did:
```python
sh.remove_from_queue(i, uid)
if was_pushed:
    sh.skip_track()  # WRONG with new context-less play model
```

When the playing track was album-context (old behavior), `skip_track()` was harmless — it walked the album. After the switch to `play_track_immediate` (no context), `skip_track()` skips whatever is currently playing. If viewer A is mid-song and viewer B revokes, A's song gets skipped.

**Fix:** Don't call `skip_track()` in the revoke handler. The **Blocked URIs Auto-Skip** pattern (`remove_from_queue` already adds the URI to `song_blocked_uris.json`) is the correct mechanism. The 30s `_auto_skip_blocked_uris` worker handles it when Spotify reaches the song in the queue.

```python
# CORRECT revoke handler
sh.remove_from_queue(i, uid)  # also adds URI to blocked list internally
# do NOT skip — worker handles it
```

If the revoked song is the one **currently playing** (not just pushed), the worker skips it on the next 30s tick. If it's still in Spotify's queue waiting, the worker skips it when reached. Either way, the revoke completes within 30s without disrupting other viewers' songs.

---

## State machine after all fixes

```
              ┌─ nothing playing
              │
   !play X ───┼─ user song playing ────→ queue_track, status="pushed"
              │
              └─ loop/non-user song playing → play_track_immediate, mark_as_playing

   !skip ────→ (disable repeat) → /me/player/next

   !revoke ──→ remove_from_queue (URI → blocked list) → return
              └─ worker auto-skips within 30s when Spotify reaches it

   queue empty + nothing playing (worker) → play_track_immediate(loop_song_uri)
```

## Key code locations (post-fix)

- `spotify_handler.py:play_track_immediate()` — context-replace on `!play`
- `spotify_handler.py:skip_track()` — repeat off + next
- `spotify_handler.py:_is_user_song_playing()` — branch decision helper
- `spotify_handler.py:_real_get_current_playback()` — exposes `repeat_state`
- `spotify_handler.py:process_song_queue()` — worker: pushes queue, syncs state, auto-skips blocked URIs, auto-resumes loop song
- `minecraftDiamond.py:handle_song_request` — 3-way branch on `!play`, no-skip on `!revoke`
- `routes/spotify.py:simulate_play` — same 3-way branch (kept in sync with bot)
- `routes/spotify.py:simulate_pull` — no-skip revoke (kept in sync with bot)
- `song_config.json:loop_song_uri` — background music URI for auto-resume (set to "" to disable)

## Why this is in the skill, not memory

This is a class of bugs that will recur whenever someone:
- Adds a new "play" action (overlay, command, scheduled event)
- Changes the player context (album → standalone → playlist)
- Touches the queue worker (auto-skip logic, status sync)
- Tries to "skip" from any new code path

The Spotify Web API's context model is non-obvious — devs who haven't been bitten will reach for `next` and `queue` and not realize they're walking the wrong graph. This reference is the institutional memory of the trap.
