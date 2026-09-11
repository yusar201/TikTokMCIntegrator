# Song Queue Background Worker

## Problem (Original Bug)

The first implementation of the queue worker only pushed songs when it detected `track_ended` (Spotify not playing or no current item). This meant:
- If Spotify was already playing something, new `!play` requests sat in the local queue forever
- Songs only got pushed when Spotify was stopped or between tracks
- No visibility into why queue wasn't moving — silent failure

## Fixed Pattern (v2)

The worker now **scans the local queue every 3 seconds** and immediately pushes any `"queued"` items to Spotify. It tracks playback state to manage status lifecycle: `"queued"` → `"pushed"` → `"playing"` → `"played"`.

### ⚙️ Push Delay Design

The worker's loop sleep duration controls the revocation window:

- **3s (default):** Viewers have ~3 seconds to `!revoke` before the song hits Spotify. Once pushed, it cannot be removed from Spotify's queue. Brief audible bleed when revoking mid-play.
- **30s (extended):** Gives viewers a comfortable 30-second window to change their mind. The overlay shows the song as "Queued" (with a remove button) the whole time. Once the 30s expires and it's pushed, it will play — but the **Blocked URIs Auto-Skip** system can still intercept it when Spotify starts playing. Combined, these make the effective revocation window effectively unlimited: viewers can !revoke at any point before the song actually plays on stream.

Change the delay in `spotify_handler.py`:

```python
def process_song_queue():
    while _song_queue_running:
        try:
            time_mod.sleep(30)  # ← Increase for longer revocation window
            token = get_valid_token()
            ...
```

**Trade-off:** Longer delays mean songs take longer to reach Spotify's queue. If the current track is almost over, the next song may not arrive in time. 30s balances revocation opportunity against perceived queue responsiveness.

### spotify_handler.py — Worker Loop

```python
import threading
import time as time_mod

_song_queue_running = False
_worker_log_path = None

def _worker_log(msg):
    """Write to song_queue_worker.log next to the EXE for debugging."""
    if _worker_log_path is None:
        return
    try:
        ts = datetime.datetime.now().isoformat()
        with open(_worker_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def process_song_queue():
    """Background loop: scan local queue and push queued items to Spotify immediately.
    Also sync playback state: pushed -> playing -> played."""
    import time as time_mod

    last_playing_id = None

    while _song_queue_running:
        try:
            time_mod.sleep(30)  # ← 30s revocation window for !revoke

            token = get_valid_token()
            if not token:
                continue

            cfg = load_config()
            if not cfg.get("enabled", True):
                continue

            # --- 1. Push any newly queued items to Spotify ---
            queue = load_queue()
            for pos, entry in enumerate(queue):
                if entry.get("status") == "queued":
                    uri = entry.get("spotify_uri", "")
                    if uri:
                        result = queue_track(uri)
                        if "error" not in result:
                            entry["status"] = "pushed"
                            entry["pushed_at"] = datetime.datetime.now().isoformat()
                            save_queue(queue)
                            _worker_log(f"PUSHED: {entry.get('track_name')} by {entry.get('artist')} (req: {entry.get('requested_by')})")
                        else:
                            _worker_log(f"PUSH FAILED: {entry.get('track_name')} — {result.get('error')}")

            # --- 2. Sync playback state: detect what's actually playing ---
            playback = get_current_playback()
            if "error" in playback:
                continue

            is_playing = playback.get("is_playing", False)
            current_item = playback.get("item")
            current_id = current_item.get("id") if current_item else None

            queue = load_queue()
            changed = False

            # Mark pushed item as playing when Spotify starts playing it
            if is_playing and current_id:
                for entry in queue:
                    if entry.get("status") == "pushed" and current_id in (entry.get("spotify_uri", ""), entry.get("spotify_id", "")):
                        entry["status"] = "playing"
                        entry["started_at"] = datetime.datetime.now().isoformat()
                        changed = True
                        _worker_log(f"NOW PLAYING: {entry.get('track_name')}")
                        break
                    # Fallback: if pushed item is now playing but IDs don't match exactly,
                    # check if it's the only pushed item and Spotify is playing something
                    elif entry.get("status") == "pushed" and not last_playing_id:
                        entry["status"] = "playing"
                        entry["started_at"] = datetime.datetime.now().isoformat()
                        changed = True
                        _worker_log(f"NOW PLAYING (fallback): {entry.get('track_name')}")
                        break

            # Mark playing item as played when track changes or stops
            if last_playing_id and current_id != last_playing_id:
                for entry in queue:
                    if entry.get("status") == "playing":
                        entry["status"] = "played"
                        entry["ended_at"] = datetime.datetime.now().isoformat()
                        changed = True
                        _worker_log(f"PLAYED: {entry.get('track_name')}")
                        # --- CRITICAL: also add to history so the overlay/history tab reflects it ---
                        add_to_history(entry)
                        break

            if changed:
                save_queue(queue)

            last_playing_id = current_id

        except Exception as e:
            _worker_log(f"WORKER ERROR: {e}")
            time_mod.sleep(10)


def start_song_queue_worker():
    """Start the background song queue worker thread."""
    global _song_queue_running, _worker_log_path
    if _song_queue_running:
        return
    _song_queue_running = True
    _worker_log_path = os.path.join(BASE_DIR, "song_queue_worker.log")
    t = threading.Thread(target=process_song_queue, daemon=True)
    t.start()
    _worker_log("Worker started")


def stop_song_queue_worker():
    """Stop the background song queue worker."""
    global _song_queue_running
    _song_queue_running = False
```

### spotify_handler.py — Hardened `_spotify_post`

```python
def _spotify_post(endpoint, data=None):
    """POST to Spotify Web API with token refresh and structured error logging."""
    token = get_valid_token()
    if not token:
        return {"error": "Not authenticated"}

    headers = {"Authorization": f"Bearer {token['access_token']}"}
    url = f"https://api.spotify.com/v1{endpoint}"

    try:
        if data is not None:
            resp = requests.post(url, headers=headers, json=data)
        else:
            resp = requests.post(url, headers=headers)
        if resp.status_code in (200, 201, 204):
            return {"success": True}
        elif resp.status_code == 403:
            return {"error": "Spotify Premium required or no active device"}
        elif resp.status_code == 404:
            return {"error": "No active Spotify device found"}
        else:
            return {"error": f"HTTP {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"error": str(e)}
```

**Critical fix:** Never pass `json=None` to `requests.post()` — some Spotify endpoints reject it. Only include the `json` kwarg when `data is not None`.

### Startup hook (main.py)

```python
# After ensure_profiles_setup(), before Flask thread:
try:
    from spotify_handler import start_song_queue_worker
    start_song_queue_worker()
except Exception as e:
    print(f"[SONG-QUEUE] Failed to start worker: {e}")
```

### Key behaviors

- Polls every **3 seconds** — fast enough to feel responsive, slow enough to not hammer API
- `"pushed"` status prevents double-push — once queued→pushed, it's locked until playback sync updates it
- Playback sync tracks actual Spotify state — not assumptions about when a track "should" end
- File logging to `song_queue_worker.log` — every push, failure, state change, and error is timestamped. Essential for debugging since `print()` is invisible in a PyInstaller windowed app
- Graceful on errors — sleeps 10s on exception, continues indefinitely
- Daemon thread — dies with parent process, no cleanup needed
- Checks `enabled` config and token validity before every iteration

## Status Lifecycle

| Status | Meaning | Transition Trigger |
|--------|---------|-------------------|
| `queued` | In local queue, not yet on Spotify | `!play` command creates it |
| `pushed` | Added to Spotify's queue | Worker loop pushes it via `queue_track()` |
| `playing` | Currently playing on Spotify | Worker detects `is_playing` + track match |
| `played` | Finished playing | Track ID changed or stopped |
| `skipped` | Manually skipped via `!skip` | `skip_to_next()` + manual mark |
| `revoked` | User cancelled before push | `!revoke` on `queued` item only |

## Edge Cases

- **Spotify plays its own song (not from queue):** Worker still pushes local `"queued"` items. The queue mixes user requests with Spotify's own suggestions — that's correct behavior
- **Queue is empty:** Worker scans, finds nothing, sleeps 3s. No-op.
- **Spotify disconnected mid-poll:** `get_valid_token()` returns None → worker sleeps, waits for reconnect
- **Track already playing when `!play` fires:** New request gets queued, worker pushes it on next cycle (Spotify queues it after current track)
- **Multiple `!play` while one is playing:** All get `"pushed"` in order; Spotify plays them sequentially
