# Spotify Context-Purge Technique

## Problem
When a song is queued via Spotify's `queue_track()` API and later revoked, it's already in Spotify's internal queue. Spotify has no "remove from queue" API endpoint, so the song WILL play when the current track ends.

## Solution: Context Replace + Re-Push
Replace the playback context with just the current track (at the same position), which clears Spotify's internal queue. Then re-push remaining queued songs.

### Implementation

```python
def _purge_and_repush(queue, revoked_uri):
    playback = get_current_playback()
    if "error" in playback:
        # fallback: add to blocked-URI list for worker to auto-skip
        add_blocked_uri(revoked_uri)
        return

    current_uri = playback.get("item", {}).get("uri")
    progress_ms = playback.get("progress_ms", 0)

    # Case 1: revoked song already started — skip immediately
    if current_uri == revoked_uri:
        skip_track()
        return

    # Case 2: replace context at same position — clears Spotify's queue
    _spotify_put("/me/player/play", {
        "uris": [current_uri],
        "position_ms": progress_ms,
    })

    # Re-push remaining queued songs (excluding revoked)
    for entry in queue:
        if entry.get("status") in ("queued", "pushed"):
            q_uri = entry.get("spotify_uri", "")
            if q_uri != revoked_uri:
                queue_track(q_uri)
    
    # If nothing re-pushed, queue loop song as fallback
    if no_songs_re_pushed:
        queue_track(loop_song_uri)
```

## Key Insight
`position_ms` prevents the current track from restarting. Spotify's API docs: "Passing in a position_ms value for a track that is already playing won't affect the current playback state."

## Fallback
If the context-purge fails (no active device, token expired, API error), fall back to blocked-URI mechanism: add the URI to a persistent blocked list, and the background worker polls every 3s to auto-skip when it starts playing.

## Edge Cases
- **Revoked song already playing**: Call `skip_track()` immediately
- **No current track**: Can't purge — fall back to blocked-URI
- **No remaining songs after purge**: Queue loop_song_uri as fallback for !skip
- **!skip in empty queue**: !skip handler checks if anything is playing after skip; if not, immediately plays loop song
