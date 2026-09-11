# Pause vs Natural Song End — Three-Way Disambiguation

## Why This Is Hard

The Spotify Web API returns `is_playing=False` for **both** of these cases:

1. **User manually paused** — they hit pause, or another media app took focus
2. **Track just ended naturally** — Spotify is about to clear the `item` field

The key difference that emerges over time:
- User pause: `current_uri` stays set indefinitely (minutes, hours, until user un-pauses)
- Natural end: `current_uri` clears within a few seconds (Spotify returns 204 No Content after a brief window)

But within a single 5-second poll cycle, they look identical.

## The Wrong Approach (DO NOT DO)

**"Just check `current_uri` is null before resuming the loop song."**

This produces **dead air forever** after every natural song end, because Spotify keeps the old URI set for several cycles. The bot never resumes the loop song after the queue empties.

This was the original bug. Symptom: queue empties → bot goes silent → user has to manually `!play` something.

**"Wait N seconds of idle, then resume."**

Also wrong. If N is short (e.g. 10s), you override user pauses that need to last longer (a 30-second media clip). If N is long (e.g. 60s), dead air is back. There's no N that satisfies both.

This was Attempt #2 in the 2026-06-04 fix session. User correctly rejected it: *"sometime i wanna pause the song because i also have another media player send by user. and after couple seconds it keeps resuming. that's the problem"*.

## The Right Approach: Three-Way Disambiguation

The worker treats `current_uri=null` as the **only** positive signal that a track truly ended. Manual pause leaves the URI set, so the worker leaves the user alone.

### Code Shape (final, in `spotify_handler.py:process_song_queue`)

```python
if not is_playing or not current_uri:
    has_playing = any(q.get("status") == "playing" for q in queue)
    has_queued  = any(q.get("status") == "queued"  for q in queue)

    if has_playing:
        # Stale cache after !skip — wait
    elif has_queued:
        # Song ended — play next from queue
        play_next_from_queue()
    elif not current_uri:
        # Spotify returned 204 — track truly ended
        # Resume loop song
        play_track_immediate(loop_uri)
    else:
        # current_uri set + paused = USER PAUSED
        # Leave it alone forever
        _log_worker("Worker: track paused by user — waiting")
```

The three terminal cases:
| `has_playing` | `has_queued` | `current_uri` | Action |
|---|---|---|---|
| True | any | any | Stale cache — wait |
| False | True | any | Play next from queue |
| False | False | None | Resume loop song |
| False | False | set | **User paused — do nothing** |

### Critical Companion Fix in `_sync_playback_state`

The sync function must **NOT** mark a queue track as `"played"` on `is_playing=False` alone. Old buggy code:

```python
# WRONG
if q.get("status") == "playing":
    if q.get("spotify_uri") != current_uri or not is_playing:
        q["status"] = "played"
        if q.get("spotify_uri") == current_uri:
            break
```

This marks a paused track as played, then the worker sees `has_playing=False` and resumes the loop song over the user's pause. The correct version only marks as played on (a) URI change (different track now playing) or (b) `current_uri` is null:

```python
# RIGHT
if current_uri and is_playing:
    for q in queue:
        if q.get("status") == "playing" and q.get("spotify_uri") != current_uri:
            q["status"] = "played"
            # ... history add
    # Mark current track as playing if queued
    for i, entry in enumerate(queue):
        if entry.get("spotify_uri") == current_uri and entry.get("status") == "queued":
            queue[i]["status"] = "playing"
            break

# Truly ended (Spotify returned 204)
if not current_uri and last_seen_uri:
    for q in queue:
        if q.get("spotify_uri") == last_seen_uri and q.get("status") == "playing":
            q["status"] = "played"
            # ... history add
```

A paused queue track keeps `status="playing"` indefinitely, so the worker sees `has_playing=True` and waits.

## Generalizable Principle

> **When two states are API-indistinguishable, pick the LESS destructive default.**

For "did the user pause, or did automation end a state?":
- Doing nothing = brief silence, but user retains control
- Resuming automation = user has to fight the bot to keep their state

**Always bias toward passive when the user might have intended the current state.**

This applies to any worker reacting to user-initiated state changes: pause, mute, minimize window, disconnect device, change focus. Default to "wait + log" unless you have positive evidence of automation intent.

## Tradeoff Accepted

If the loop song itself naturally ends and Spotify is slow to return 204, there's a brief dead-air window. Acceptable — user can `!play` something or wait for the next gift. The alternative (auto-resume on pause) is much worse.

## Known Remaining Issue

Song ending naturally with empty queue → no auto-loop resume because Spotify's 204 doesn't always arrive. Status: **known, user accepted**, not fixed as of 2026-06-04.
