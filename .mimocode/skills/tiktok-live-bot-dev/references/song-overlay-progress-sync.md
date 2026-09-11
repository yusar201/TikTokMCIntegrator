# Song Overlay Progress Bar Sync

Reusable pattern for smooth, accurate media progress bars in browser-source overlays that consume a third-party API (Spotify, YouTube, etc.) via a backend cache.

## Problem

Polling the backend every 1s but the backend caches the third-party API causes:
- Progress bar freezes while cache is stale, then glitches forward on refresh
- Fast-forward/seek on the source doesn't reflect in the overlay
- Pause → resume shows stale progress (jumps back behind reality)
- Repeat-same-track (song restarts) doesn't reset the bar to 0

## Root Cause: Resetting Timer on Every Poll

The classic broken pattern:

```javascript
// WRONG — resets baseline every poll, bar never runs freely
syncSongProgress(data.progress_ms, data.duration_ms, data.is_playing);
```

This makes the local timer useless — the bar only advances when fresh server data arrives, causing stuttering.

## Solution: Four-Trigger Re-Sync

The overlay runs a **local 250ms interpolation timer** between polls. It only re-syncs its baseline `progress_ms` from the server on four specific events:

1. **Track changed** — new song, switch to a different track
2. **Play/pause state flipped** — user hit pause or resume
3. **Card re-appeared after being hidden** — overlay was hidden during pause, now visible
4. **User seeked/jumped** — server-reported position jumped >5s from the last synced position (catches fast-forward, rewind, and repeat-same-track)

> **User preference:** This pattern started as a 3-rule system (no seek detection). The user explicitly rejected proactive drift detection/heuristics — "just only sync if: track change, play/pause state change, card re-appear. That's it." Seek detection was only added as a 4th rule after the user explicitly asked for fast-forward handling. Start with the minimal 3-rule version; add seek detection only if the user requests it.

### Backend Cache

```python
# spotify_handler.py
_PLAYBACK_CACHE_TTL = 2  # seconds
```

Spotify's Web API allows ~180 req/min. At 2s TTL = 30 req/min — safe headroom. The overlay polls the backend every 1s; only the backend→Spotify call is throttled.

### Frontend State

```javascript
let songProgressBaseMs = 0;      // baseline progress at sync time
let songDurationMs = 0;
let songProgressSyncedAt = Date.now();  // when we last synced
let songIsPlaying = false;
let lastSyncedTrackId = null;    // last track we synced from
let lastSyncedIsPlaying = null;  // last play state we synced from
let lastSyncedProgressMs = 0;    // LAST SERVER-REPORTED position we synced from
```

### Sync Function

```javascript
function syncSongProgress(progressMs, durationMs, isPlaying) {
  songProgressBaseMs = Number(progressMs || 0);
  songDurationMs = Number(durationMs || 0);
  songProgressSyncedAt = Date.now();
  songIsPlaying = Boolean(isPlaying);
  updateSongProgressDisplay();
}

function getSongProgressNow() {
  if (!songIsPlaying) return songProgressBaseMs;
  return Math.min(songDurationMs || songProgressBaseMs,
                  songProgressBaseMs + (Date.now() - songProgressSyncedAt));
}
```

### The Handler — Capture Visibility BEFORE Modifying DOM

```javascript
function handleSong(data) {
  const card = document.getElementById('song-card');
  const spotifyPlaying = data.spotify_playing;
  const nowPlaying = data.now_playing;
  const upcoming = data.upcoming || [];
  const spotifyEnded = spotifyPlaying && !data.is_playing && !nowPlaying;
  const hasAnyData = (spotifyPlaying && !spotifyEnded) || nowPlaying || upcoming.length > 0;

  // ⛔ CAPTURE BEFORE MODIFYING — card.style.display changes below
  const cardWasHidden = card.style.display === 'none';

  if (!hasAnyData) {
    card.style.display = 'none';
    songIsPlaying = false;
    lastSyncedIsPlaying = false;
    lastSyncedTrackId = null;
    lastSyncedProgressMs = 0;
    return;
  }

  if (cardWasHidden) {
    card.style.display = '';
    // ... animation trigger ...
  }

  // NOW PLAYING
  if ((spotifyPlaying && !spotifyEnded) || nowPlaying) {
    const trackId = spotifyPlaying?.id || nowPlaying?.uri || null;
    const isPlayingNow = !!(data.is_playing && spotifyPlaying?.duration_ms);
    const serverProgressMs = data.progress_ms || 0;

    // Detect seek: server progress jumped from last synced position
    const progressJump = Math.abs(serverProgressMs - lastSyncedProgressMs);
    const userSeeked = isPlayingNow && progressJump > 5000;

    const mustSync = cardWasHidden ||                    // visibility change
                     (trackId !== lastSyncedTrackId) ||  // track change
                     (isPlayingNow !== lastSyncedIsPlaying) || // play/pause flip
                     userSeeked;                          // seek/rewind/repeat

    if (isPlayingNow) {
      progressEl.style.display = 'flex';
      if (mustSync) {
        syncSongProgress(serverProgressMs, spotifyPlaying.duration_ms, true);
        lastSyncedTrackId = trackId;
        lastSyncedIsPlaying = true;
        lastSyncedProgressMs = serverProgressMs;
      }
    } else {
      progressEl.style.display = 'none';
      if (mustSync) {
        syncSongProgress(serverProgressMs, spotifyPlaying?.duration_ms || 0, false);
        lastSyncedTrackId = trackId;
        lastSyncedIsPlaying = false;
        lastSyncedProgressMs = serverProgressMs;
      }
      songIsPlaying = false;
    }
  }
}
```

### Why `lastSyncedProgressMs` instead of drift detection

An earlier version compared the server's `progress_ms` against the **local timer's estimate** (`getSongProgressNow()`). This caused periodic jumps every cache cycle — the local timer would run slightly ahead, hit the drift threshold, and snap back to the stale cached position. Disaster.

The fix: compare server-reported `progress_ms` against **`lastSyncedProgressMs`** (the last server position we actually accepted). This only detects **real changes** in the server's story — user seeks, rewinds, or repeat-same-track where the position suddenly resets.

### Why `cardWasHidden` must be captured BEFORE modifying `display`

```javascript
// WRONG — always false because we just set it to ''
if (card.style.display === 'none') { card.style.display = ''; ... }

// RIGHT — capture old state, then use it for sync logic
const cardWasHidden = card.style.display === 'none';
if (cardWasHidden) { card.style.display = ''; ... }
```

Without this, resuming from pause never triggers a re-sync. The overlay resumes from its frozen pause baseline and jumps back seconds behind reality.

## Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| Resetting timer on EVERY poll | Bar stalls/glitches, never runs smoothly | Only call `syncSongProgress` inside `mustSync` guards |
| Drift detection vs local timer | Bar jumps every 2–3s as cache refreshes | Compare against `lastSyncedProgressMs`, not local estimate |
| No `lastSyncedProgressMs` tracking | Seek, rewind, repeat-same-track don't sync | Track the last accepted server position |
| `cardWasHidden` checked AFTER setting `display = ''` | Pause → resume jumps back behind reality | Capture `cardWasHidden` before any DOM mutation |
| No state reset when card hides | Stale trackId prevents sync on next show | Reset `lastSyncedTrackId`, `lastSyncedIsPlaying`, `lastSyncedProgressMs` when hiding |
| Overlay poll rate = backend cache rate | Bar only moves once every cache cycle | Decouple: overlay polls fast (1s), backend caches slower (2s) |

## Numbers That Work

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Backend cache TTL | 2s | Fast pause/resume response, safe under ~180 req/min |
| Overlay poll interval | 1000ms | Responsive UI updates (queue, upcoming) |
| Local timer interval | 250ms | Silky smooth bar animation |
| Seek jump threshold | 5000ms | Catches real seeks without false-triggering on cache lag |
