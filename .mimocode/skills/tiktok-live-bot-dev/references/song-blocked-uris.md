# Revoke of Pushed Songs — Context-Purge Pattern

## Problem

Spotify's Web API provides `POST /me/player/queue?uri=<id>` to add tracks to the playback queue, but **provides no endpoint to remove a track from the queue**. This means:

1. User requests a song → worker pushes it to Spotify (status: `"pushed"`)
2. User revokes the song → removed from local `song_queue.json`
3. Current track ends → Spotify plays the "revoked" song anyway

## Two Approaches

| Approach | Latency | Technique |
|----------|---------|-----------|
| **Context-purge (PRIMARY)** | ~0ms (instant) | Replace context to wipe Spotify's queue, re-push remaining |
| **Blocked-URI fallback** | ~3-30s | Wait for revoked song to start playing, then skip_track() |

## Primary: Context-Purge (`_purge_and_repush`)

### How It Works

`PUT /me/player/play` with `uris` replaces the entire playback context, which **clears Spotify's internal queue** (items added via `queue_track()`). The trick:

1. Get current playback: track URI + `progress_ms` (millisecond position)
2. `PUT /me/player/play` with `uris: [current_uri], position_ms: progress_ms`
   - Current track **keeps playing from current position** (does NOT restart — Spotify docs: "Passing in a position_ms value for a track that is already playing won't affect the current playback state")
   - Spotify's queue is wiped
3. Re-push remaining queued songs (minus revoked one) via `queue_track()`
4. Revoked song **never exists in the new context** → never plays, not even for a millisecond

### Code (`spotify_handler.py`)

```python
def _purge_and_repush(queue, revoked_uri):
    playback = get_current_playback()
    if "error" in playback:
        # Fall through to blocked-URI mechanism
        add_blocked_uri(revoked_uri)
        return

    current_item = playback.get("item")
    current_uri = current_item.get("uri") if current_item else None
    progress_ms = playback.get("progress_ms", 0)

    # Case 1: revoked song is already playing — immediate skip
    if current_uri and current_uri == revoked_uri:
        skip_result = skip_track()
        if "error" in skip_result:
            add_blocked_uri(revoked_uri)
            return
        # Mark as skipped in local queue, add to history
        for q in queue:
            if q.get("spotify_uri") == revoked_uri:
                q["status"] = "skipped"
                add_to_history(dict(q))
        save_queue(queue)
        return

    # Case 2: replace context to clear Spotify's queue
    result = _spotify_put("/me/player/play", {
        "uris": [current_uri],
        "position_ms": progress_ms,
    })
    if "error" in result:
        add_blocked_uri(revoked_uri)  # fallback
        return

    # Re-push remaining queued songs (exclude revoked_uri)
    for entry in queue:
        if entry.get("status") in ("queued", "pushed"):
            q_uri = entry.get("spotify_uri", "")
            if q_uri and q_uri != revoked_uri:
                q_result = queue_track(q_uri)
                if "error" not in q_result:
                    entry["status"] = "pushed"
                    entry["pushed_at"] = time.time()
    save_queue(queue)
```

### Entry Point (`remove_from_queue`)

```python
def remove_from_queue(position, requested_by):
    ...
    removed = queue.pop(position)
    save_queue(queue)

    if removed.get("status") == "pushed":
        uri = removed.get("spotify_uri", "")
        if uri:
            _purge_and_repush(queue, uri)
```

### Key Design Details

- `position_ms` is critical — without it, the current track RESTARTS from 0 (terrible UX)
- The revoked URI is popped BEFORE `_purge_and_repush` is called, so the queue passed in already excludes it
- Re-push loop only pushes entries with status `"queued"` or `"pushed"` — already-played songs stay played
- On any error, falls back to the blocked-URI mechanism

## Fallback: Blocked-URI + Rapid-Poll

### When It Activates

The blocked-URI mechanism activates ONLY when `_purge_and_repush` encounters an error:
- Playback API returns error (no active device, token expired)
- Context replacement fails
- Current track is None (nothing playing)

### Architecture

Three components that work together as a fallback:

### 1. Blocked URIs File

A persistent JSON list of Spotify URIs that should be auto-skipped when detected as playing.

```python
BLOCKED_URIS_FILE = os.path.join(BASE_DIR, "song_blocked_uris.json")

def add_blocked_uri(uri):
    blocked = load_blocked_uris()
    if uri not in blocked:
        blocked.append(uri)
        save_blocked_uris(blocked)
```

### 2. Auto-Skip in Main Worker Cycle

Checks if the currently playing track is blocked:

```python
def _auto_skip_blocked_uris(queue, current_uri):
    if not current_uri:
        return queue, False
    blocked = load_blocked_uris()
    if current_uri not in blocked:
        return queue, False
    # Mark as skipped, skip on Spotify, remove from blocked list
    skip_track()
    remove_blocked_uri(current_uri)
    return queue, True
```

### 3. Rapid-Poll Phase (30s cooldown after error)

After the main 30s cycle, if blocked URIs exist, poll every 3s (cached playback, minimal API cost) until a blocked song is detected and skipped, or 30s elapses:

```python
blocked = load_blocked_uris()
if blocked:
    for _fast in range(10):  # up to 30s
        if not _song_queue_running:
            break
        time.sleep(3)
        playback = get_current_playback()  # 2s cache
        ...
        if current_uri in load_blocked_uris():
            skip_track()
            remove_blocked_uri(current_uri)
            break
```

## Flow Diagram

```
!revoke for a pushed song
  → remove_from_queue()
    → Pop from local queue, save
    → _purge_and_repush(queue, uri)
      ├─ Playback error? → add_blocked_uri → fall through to worker
      ├─ Already playing? → skip_track() → mark skipped → done
      └─ Context replace → re-push remaining → done ✓ INSTANT, NO BLEED

Worker (30s cycle, ONLY if blocked URIs exist):
  → _auto_skip_blocked_uris() → catch already-playing blocked song
  → Rapid-poll (3s×10) → catch newly-started blocked song → skip
```

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Revoked song is already playing (race condition) | `_purge_and_repush` catches this immediately (Case 1: `current_uri == revoked_uri`) and calls `skip_track()` directly |
| Context replace fails (no active device) | Falls through to blocked-URI + rapid-poll. Song plays briefly (~3-6s) before skip |
| Current track finishes between API calls | `current_uri` is None → falls through to blocked-URI. If no current track, blocked-URI catches it when the revoked song starts |
| No remaining queued songs after revoke | Context replaced with just [current_uri]. When current ends, nothing plays until worker auto-resumes loop song (next 30s cycle) |
| Two revoked songs stacked | First revoke does context-purge + re-push (removes first revoked). Second revoke does another context-purge. Both instant. |
| Revoking a QUEUED (not pushed) song | `remove_from_queue` doesn't call `_purge_and_repush` — just pops from local queue. Worker never pushes it. Instant, no API calls. |
| App crashes mid-purge | Queue file saved BEFORE purge call. Song is removed from local queue. If it was already pushed to Spotify before crash, it'll play when current ends. On restart, the blocked-URI file sits empty (purge hadn't called add_blocked_uri yet). Rare edge case — acceptable. |

## File Format

`song_blocked_uris.json`:
```json
[
  "spotify:track:0DiWol3AO6WpXZgp0goxAV"
]
```

Simple array of Spotify URI strings. Created only when context-purge falls back to blocked-URI mechanism.

## Pitfalls

- **⛔ `position_ms` is mandatory.** Omitting it causes the current song to restart from 0. Always pass `position_ms` from `get_current_playback().get("progress_ms", 0)`.
- **⛔ Context-purge is NOT a no-op on the UI.** The context replace momentarily resets Spotify's internal queue state. If the user is looking at the "next up" section in the Spotify app, it will briefly flash. Acceptable trade-off.
- **⛔ Call order matters.** Pop from queue → save queue → call `_purge_and_repush(queue_without_revoked)`. If you call purge before saving, the queue still has the revoked entry and the re-push loop will re-push it.
- **⛔ Blocked-URI is a fallback, not primary.** If you find yourself debugging revoke latency, check whether `_purge_and_repush` is failing. Add logging: the function logs "Purge: ..." lines to `song_queue_worker.log`.
