"""
Spotify integration module for TikTokMCIntegrator.

Handles:
- OAuth flow (login, callback, token persistence)
- Track search
- Queue management (local queue before Spotify push)
- Playback control (skip, current status)
- Token refresh

Token stored in: song_spotify_token.json
Queue stored in:  song_queue.json
History stored in: song_history.json
Config stored in:  song_config.json
"""

import json
import os
import time
import threading
import logging

logger = logging.getLogger(__name__)

import sys

# Resolve BASE_DIR — works both as .py script and as packaged .exe
# When imported from a frozen app, sys.executable is the exe path
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) \
           else os.path.dirname(os.path.abspath(__file__))

TOKEN_FILE = os.path.join(BASE_DIR, "song_spotify_token.json")
CONFIG_FILE = os.path.join(BASE_DIR, "song_config.json")
QUEUE_FILE = os.path.join(BASE_DIR, "song_queue.json")
HISTORY_FILE = os.path.join(BASE_DIR, "song_history.json")
WORKER_LOG_FILE = os.path.join(BASE_DIR, "song_queue_worker.log")
BLOCKED_URIS_FILE = os.path.join(BASE_DIR, "song_blocked_uris.json")
FEEDBACK_FILE = os.path.join(BASE_DIR, "song_feedback.json")

SPOTIFY_API_BASE = "https://api.spotify.com/v1"
# Thread lock for file writes
_write_lock = threading.Lock()


def _log_worker(msg):
    """Write a timestamped message to the worker log file."""
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(WORKER_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


# ── Song Feedback Queue (cross-process — file-based) ─────────────────────────
# File-based so the bot subprocess and Flask web process share state.
# Bot writes (push_song_feedback) → Flask reads (get_and_clear_feedback) on overlay poll.

def _load_feedback():
    """Load feedback entries from file. Returns list of dicts."""
    if not os.path.exists(FEEDBACK_FILE):
        return []
    try:
        with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def _save_feedback(entries):
    """Atomically write feedback entries to file."""
    with _write_lock:
        tmp = FEEDBACK_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp, FEEDBACK_FILE)


def push_song_feedback(nick, feedback_type, icon, title, detail=""):
    """Push a feedback entry for the overlay toast.

    Args:
        nick: Username who triggered the command (e.g. "koolguy99")
        feedback_type: "success", "error", or "denied"
        icon: Emoji icon (e.g. "✓", "⏭", "↩", "✗", "⊘")
        title: Main message line (e.g. "@koolguy99 queued Song — Artist")
        detail: Subtle hint line (e.g. "Use !pull to remove your request")
    """
    entry = {
        "nick": nick,
        "type": feedback_type,
        "icon": icon,
        "title": title,
        "detail": detail,
        "timestamp": time.time(),
    }
    try:
        entries = _load_feedback()
        entries.append(entry)
        # Cap to last 50 entries to prevent unbounded growth
        if len(entries) > 50:
            entries = entries[-50:]
        _save_feedback(entries)
    except Exception as e:
        print(f"[SONG FEEDBACK] Failed to write: {e}")
    print(f"[SONG FEEDBACK] {feedback_type}: {title}")


def get_and_clear_feedback():
    """Return all feedback entries. Drop entries older than 5s.
    Persists unexpired entries back to file so they remain visible on next poll.
    """
    now = time.time()
    entries = _load_feedback()
    if not entries:
        return []
    fresh = [e for e in entries if now - e.get("timestamp", 0) < 5]
    # Only rewrite the file if we actually expired something (saves I/O on hot poll)
    if len(fresh) != len(entries):
        try:
            _save_feedback(fresh)
        except Exception as e:
            print(f"[SONG FEEDBACK] Failed to prune: {e}")
    return fresh


# ── Config Management ──────────────────────────────────────────────────────────

def get_default_config():
    """Return the default song config."""
    return {
        "play_command": "!play",
        "skip_command": "!skip",
        "revoke_command": "!revoke",
        "allow_explicit": True,
        "max_queue_total": 10,
        "max_queue_per_user": 2,
        "play_permission": {
            "everyone": True,
            "followers": False,
            "friends": False,
            "superfans": False,
            "members": False,
            "mods": False,
            "vip": False,
            "whitelist": []
        },
        "skip_permission": {
            "everyone": False,
            "followers": False,
            "friends": False,
            "superfans": False,
            "members": False,
            "mods": True,
            "vip": True,
            "whitelist": ["ikhito"]
        },
        "revoke_permission": "requestor",
        "overlay_enabled": True,
        "spotify_client_id": "",
        "spotify_client_secret": "",
        "spotify_redirect_uri": "http://127.0.0.1:5000/api/spotify/callback",
        "enabled": True
    }


def load_config():
    """Load song config from file, merging with defaults for missing keys."""
    defaults = get_default_config()
    if not os.path.exists(CONFIG_FILE):
        save_config(defaults)
        return dict(defaults)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # Merge defaults for any missing keys, including nested permission blocks
        merged = dict(defaults)
        merged.update(cfg)
        for key in ("play_permission", "skip_permission"):
            nested = dict(defaults.get(key, {}))
            nested.update(cfg.get(key, {}) if isinstance(cfg.get(key), dict) else {})
            merged[key] = nested
        return merged
    except (json.JSONDecodeError, IOError):
        return dict(defaults)


def save_config(data):
    """Save song config to file."""
    with _write_lock:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info("Song config saved")


# ── Token Management ───────────────────────────────────────────────────────────

def load_token():
    """Load Spotify token from file. Returns None if not found or expired."""
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            token = json.load(f)
        # Check expiry
        expires_at = token.get("expires_at", 0)
        if expires_at and time.time() >= expires_at - 60:
            logger.info("Token expired, needs refresh")
            return None
        return token
    except (json.JSONDecodeError, IOError):
        return None


def save_token(token_data):
    """Save Spotify token to file."""
    with _write_lock:
        try:
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                json.dump(token_data, f, indent=2)
            print(f"[SPOTIFY] Token saved to {TOKEN_FILE}")
            logger.info("Spotify token saved")
        except Exception as e:
            print(f"[SPOTIFY] ERROR saving token to {TOKEN_FILE}: {e}")
            raise


def clear_token():
    """Remove the token file."""
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
        logger.info("Spotify token cleared")


def get_valid_token():
    """Get a valid token, refreshing if needed. Returns dict or None."""
    import requests as req

    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE, "r") as f:
            token = json.load(f)
    except Exception:
        return None

    expires_at = token.get("expires_at", 0)
    if expires_at and time.time() < expires_at - 60:
        return token  # Still valid

    # Try refresh — but respect cooldown to avoid pounding auth endpoint
    refresh_token_val = token.get("refresh_token")
    if not refresh_token_val:
        return None

    global _token_refresh_until
    now = time.time()
    if now < _token_refresh_until:
        # In cooldown — return expired token, callers will get 401 and tell user
        logger.info(f"Token refresh cooldown: {int(_token_refresh_until - now)}s remaining")
        return token  # Return expired; callers get 401 which shows reconnect message

    # Acquire lock to prevent concurrent refresh calls
    if not _token_refresh_lock.acquire(blocking=False):
        logger.info("Token refresh already in progress by another caller")
        return token  # Another thread is already refreshing
    try:
        # Double-check cooldown in case another thread just refreshed
        if time.time() < _token_refresh_until:
            return token

        cfg = load_config()
        client_id = cfg.get("spotify_client_id", "")
        client_secret = cfg.get("spotify_client_secret", "")
        if not client_id or not client_secret:
            return None

        try:
            resp = req.post(
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token_val,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning(f"Token refresh failed: {resp.status_code} {resp.text}")
                # Hit rate limit? Respect Retry-After from Spotify
                if resp.status_code == 429:
                    retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                    _token_refresh_until = time.time() + retry_after
                else:
                    _token_refresh_until = time.time() + _TOKEN_REFRESH_COOLDOWN
                return None

            if not resp.text:
                logger.warning("Token refresh returned empty body")
                _token_refresh_until = time.time() + _TOKEN_REFRESH_COOLDOWN
                return None
            try:
                new_token = resp.json()
            except ValueError:
                logger.warning(f"Token refresh returned non-JSON: {resp.text[:200]}")
                _token_refresh_until = time.time() + _TOKEN_REFRESH_COOLDOWN
                return None
            new_token["expires_at"] = int(time.time()) + new_token.get("expires_in", 3600)
            if "refresh_token" not in new_token:
                new_token["refresh_token"] = refresh_token_val

            save_token(new_token)
            return new_token
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            _token_refresh_until = time.time() + _TOKEN_REFRESH_COOLDOWN
            return None
    finally:
        _token_refresh_lock.release()


# ── OAuth Flow ─────────────────────────────────────────────────────────────────

import urllib.parse


def get_auth_url(client_id, redirect_uri):
    """Generate the Spotify authorization URL."""
    scopes = "user-read-playback-state user-modify-playback-state user-read-currently-playing"
    return (
        f"https://accounts.spotify.com/authorize"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&scope={urllib.parse.quote(scopes)}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
    )


def handle_callback(code, client_id, client_secret, redirect_uri):
    """Exchange authorization code for token."""
    import requests as req

    try:
        resp = req.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"[SPOTIFY] Token exchange failed: {resp.status_code} {resp.text}")
            return {"error": f"Spotify returned {resp.status_code}: {resp.text}"}

        if not resp.text:
            print("[SPOTIFY] Token exchange returned empty body")
            return {"error": "Spotify returned empty response"}

        try:
            token = resp.json()
        except ValueError:
            print(f"[SPOTIFY] Token exchange returned non-JSON: {resp.text[:200]}")
            return {"error": f"Spotify returned non-JSON response: {resp.text[:200]}"}

        if "access_token" not in token:
            print(f"[SPOTIFY] No access_token in response: {token}")
            return {"error": "Spotify did not return an access token"}

        token["expires_at"] = int(time.time()) + token.get("expires_in", 3600)
        try:
            save_token(token)
            print(f"[SPOTIFY] Token saved to {TOKEN_FILE}")
        except Exception as e:
            print(f"[SPOTIFY] Failed to save token: {e}")
            return {"error": f"Failed to save token: {e}"}

        return {"success": True, "message": "Connected to Spotify!"}
    except Exception as e:
        print(f"[SPOTIFY] Callback error: {e}")
        return {"error": str(e)}


# Global rate-limit tracking
_rate_limit_until = 0  # epoch timestamp — skip all API calls until this time
_token_refresh_until = 0  # epoch timestamp — skip token refresh attempts until this time
_token_refresh_lock = threading.Lock()  # prevents concurrent refresh
_TOKEN_REFRESH_COOLDOWN = 60  # seconds between token refresh attempts


def _parse_retry_after(header_value):
    """Parse Retry-After header: could be seconds (int) or HTTP-date (RFC 7231)."""
    if not header_value:
        return 60
    try:
        return int(header_value)
    except ValueError:
        pass
    # Try HTTP-date format
    try:
        from email.utils import parsedate_to_datetime
        retry_at = parsedate_to_datetime(header_value)
        return max(1, int(retry_at.timestamp() - time.time()))
    except Exception:
        return 60


def _rate_limited():
    """Check if we're in a global rate-limit cooldown."""
    return time.time() < _rate_limit_until


def _spotify_headers(token):
    """Build common headers for Spotify API requests."""
    return {
        "Authorization": f"Bearer {token.get('access_token', '')}",
        "Content-Type": "application/json",
    }


def _spotify_get(endpoint, params=None):
    """Make a GET request to the Spotify API."""
    import requests as req
    global _rate_limit_until

    # Skip if we're in rate-limit cooldown
    if _rate_limited():
        remaining = int(_rate_limit_until - time.time())
        return {"error": f"Waiting for Spotify rate limit ({remaining}s left)."}
    token = get_valid_token()
    if not token:
        return {"error": "Not connected to Spotify"}
    try:
        resp = req.get(
            f"{SPOTIFY_API_BASE}{endpoint}",
            headers=_spotify_headers(token),
            params=params,
            timeout=10,
        )
        if resp.status_code == 401:
            # Token might be stale even after refresh attempt
            return {"error": "Token invalid, please reconnect"}
        if resp.status_code == 204:
            return {}
        if resp.status_code == 429:
            seconds = _parse_retry_after(resp.headers.get("Retry-After"))
            _rate_limit_until = time.time() + seconds
            return {"error": f"Spotify rate limited — retry in {int(_rate_limit_until - time.time())}s"}
        if not resp.text:
            return {"error": f"Spotify returned {resp.status_code} with empty response"}
        try:
            return resp.json()
        except ValueError:
            return {"error": f"Spotify returned {resp.status_code} with non-JSON: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def _spotify_post(endpoint, data=None):
    """Make a POST request to the Spotify API."""
    import requests as req
    global _rate_limit_until

    # Skip if we're in rate-limit cooldown
    if _rate_limited():
        remaining = int(_rate_limit_until - time.time())
        return {"error": f"Waiting for Spotify rate limit ({remaining}s left)."}

    token = get_valid_token()
    if not token:
        return {"error": "Not connected to Spotify"}
    try:
        kwargs = {
            "headers": _spotify_headers(token),
            "timeout": 10,
        }
        if data is not None:
            kwargs["json"] = data
        resp = req.post(
            f"{SPOTIFY_API_BASE}{endpoint}",
            **kwargs,
        )
        if resp.status_code in (200, 201, 202, 204):
            return {"success": True}
        if resp.status_code == 401:
            return {"error": "Token invalid, please reconnect"}
        if resp.status_code == 403:
            return {"error": f"Spotify returned 403 (Premium required or no active device): {resp.text}"}
        if resp.status_code == 404:
            return {"error": f"Spotify returned 404 (No active device): {resp.text}"}
        if resp.status_code == 429:
            seconds = _parse_retry_after(resp.headers.get("Retry-After"))
            _rate_limit_until = time.time() + seconds
            return {"error": f"Spotify rate limited — retry in {int(_rate_limit_until - time.time())}s"}
        return {"error": f"Spotify returned {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"error": str(e)}


# ── Public API ─────────────────────────────────────────────────────────────────

def get_connection_status():
    """Return a dict with connection status info."""
    token = get_valid_token()
    if not token:
        return {"connected": False, "error": "No token — please connect Spotify"}

    player = get_current_playback()
    if "error" in player:
        # If the error message contains "No active device" we treat it differently
        err_msg = player["error"]
        return {"connected": False, "error": err_msg}

    # If player data is empty (204) or has no item/device, there's no active device
    is_playing = player.get("is_playing", False)
    device_name = player.get("device_name", "")
    if not device_name and not player.get("item"):
        return {"connected": False, "error": "No active Spotify device — open Spotify and play something"}

    return {
        "connected": True,
        "device": device_name,
        "playing": is_playing,
        "item": player.get("item"),
    }


# ── Playback state cache (avoid rate limiting) ─────────────────────────────

_playback_cache = {"result": None, "cached_at": 0}
_PLAYBACK_CACHE_TTL = 2  # seconds — fast pause/resume response while staying under Spotify rate limits


def _get_cached_playback():
    """Get cached playback state, refreshing from Spotify if TTL expired."""
    global _playback_cache
    now = time.time()
    if now - _playback_cache["cached_at"] < _PLAYBACK_CACHE_TTL:
        return _playback_cache["result"]  # Return cached, even if None = no data yet
    # Fresh fetch
    result = _real_get_current_playback()
    # Don't cache error responses — retry fresh next time
    if isinstance(result, dict) and "error" in result:
        _playback_cache = {"result": result, "cached_at": now - _PLAYBACK_CACHE_TTL - 1}  # Force retry immediately next cycle
        return result
    _playback_cache = {"result": result, "cached_at": now}
    return result


def _real_get_current_playback():
    """Get current playback state from Spotify (always hits API)."""
    data = _spotify_get("/me/player")
    if "error" in data:
        return data
    if not data:
        return {"is_playing": False, "device_name": "", "item": None}

    item = data.get("item", None)
    device = data.get("device", {})
    return {
        "is_playing": data.get("is_playing", False),
        "device_name": device.get("name", ""),
        "device_id": device.get("id", ""),
        "device_type": device.get("type", ""),
        "progress_ms": data.get("progress_ms", 0),
        "item": _simplify_track(item) if item else None,
    }


# ── Public API ─────────────────────────────────────────────────────────────────


def get_current_playback():
    """Get current playback state. Uses 8s cache to avoid Spotify rate limits."""
    return _get_cached_playback()


def get_active_devices():
    """Get list of available Spotify devices."""
    data = _spotify_get("/me/player/devices")
    if "error" in data:
        return data
    devices = data.get("devices", [])
    return [
        {
            "id": d.get("id"),
            "name": d.get("name"),
            "type": d.get("type"),
            "is_active": d.get("is_active", False),
            "volume_percent": d.get("volume_percent", 0),
        }
        for d in devices
    ]


def search_track(query, limit=5):
    """Search for a track on Spotify. Returns list of simplified tracks."""
    data = _spotify_get("/search", {"q": query, "type": "track", "limit": limit})
    if "error" in data:
        return data
    tracks = data.get("tracks", {}).get("items", [])
    return [_simplify_track(t) for t in tracks]


def _simplify_track(track):
    """Convert a Spotify track object to a simplified dict."""
    if not track:
        return None
    artists = [a.get("name", "") for a in track.get("artists", [])]
    return {
        "id": track.get("id"),
        "name": track.get("name"),
        "uri": track.get("uri"),
        "artists": ", ".join(artists),
        "artist_names": artists,
        "album": track.get("album", {}).get("name", ""),
        "album_image": (
            track.get("album", {}).get("images", [{}])[0].get("url", "")
            if track.get("album", {}).get("images")
            else ""
        ),
        "duration_ms": track.get("duration_ms", 0),
        "explicit": track.get("explicit", False),
        "preview_url": track.get("preview_url", ""),
    }


def queue_track(uri):
    """Queue a track to Spotify's active player."""
    return _spotify_post(f"/me/player/queue?uri={uri}")


def skip_track():
    """Skip to next track."""
    return _spotify_post("/me/player/next")


def transfer_playback(device_id):
    """Transfer playback to a specific device."""
    return _spotify_post("/me/player", {"device_ids": [device_id]})


# ── Local Song Queue Management ────────────────────────────────────────────────

def load_queue():
    """Load the local song queue from file."""
    with _write_lock:
        if not os.path.exists(QUEUE_FILE):
            return []
        try:
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []


def save_queue(queue):
    """Save the local song queue to file."""
    with _write_lock:
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2)


def add_to_queue(track, requested_by):
    """Add a track to the local song queue. Returns dict with success/error."""
    cfg = load_config()
    queue = load_queue()

    # Check for duplicate — same URI already in active queue
    new_uri = track.get("uri", "")
    if new_uri:
        for q in queue:
            if q.get("spotify_uri") == new_uri and q.get("status") in ("queued", "pushed", "playing"):
                return {"error": f"That song is already in the queue!"}

    # Check max queue total (active entries only — queued, pushed, playing)
    max_total = cfg.get("max_queue_total", 10)
    active_count = sum(1 for q in queue if q.get("status") in ("queued", "pushed", "playing"))
    if active_count >= max_total:
        return {"error": f"Queue is full (max {max_total} active). Try again later."}

    # Check per-user limit
    max_per_user = cfg.get("max_queue_per_user", 2)
    user_count = sum(1 for q in queue if q.get("requested_by", "").lower() == requested_by.lower() and q.get("status") in ("queued", "pushed", "playing"))
    if user_count >= max_per_user:
        return {"error": f"You already have {max_per_user} songs in the queue."}

    # Check explicit content
    if track.get("explicit") and not cfg.get("allow_explicit", True):
        return {"error": "Explicit songs are not allowed."}

    entry = {
        "track_name": track.get("name", "Unknown"),
        "artist": track.get("artists", "Unknown"),
        "spotify_uri": track.get("uri", ""),
        "album_image": track.get("album_image", ""),
        "duration_ms": track.get("duration_ms", 0),
        "explicit": track.get("explicit", False),
        "requested_by": requested_by,
        "requested_at": time.time(),
        "status": "queued"  # queued, playing, played, skipped
    }
    queue.append(entry)
    save_queue(queue)
    return {"success": True, "entry": entry, "position": len(queue)}


def remove_from_queue(position, requested_by):
    """Remove a track from queue by position. Checks permissions."""
    queue = load_queue()
    if position < 0 or position >= len(queue):
        return {"error": "Invalid queue position"}

    entry = queue[position]
    # Allow removal by the requestor or by anyone with skip permission
    if entry.get("requested_by", "").lower() == requested_by.lower():
        # Requestor can always revoke their own
        pass
    else:
        return {"error": "You can only remove your own requests."}

    removed = queue.pop(position)
    save_queue(queue)

    # If the song was already pushed to Spotify, add its URI to blocked list
    # so the worker auto-skips it when it starts playing
    if removed.get("status") == "pushed":
        uri = removed.get("spotify_uri", "")
        if uri:
            add_blocked_uri(uri)
            _log_worker(f"Revoked pushed song blocked: {removed.get('track_name')}")

    return {"success": True, "removed": removed}


def clear_queue():
    """Clear the entire song queue."""
    save_queue([])
    return {"success": True}


def mark_as_playing(position):
    """Mark a queue entry as currently playing."""
    queue = load_queue()
    # Set all to non-playing
    for q in queue:
        if q.get("status") == "playing":
            q["status"] = "played"
    if position >= 0 and position < len(queue):
        queue[position]["status"] = "playing"
    save_queue(queue)
    return queue


def get_next_to_play():
    """Get the next queued track to play. Returns position and entry or None."""
    queue = load_queue()
    for i, q in enumerate(queue):
        if q.get("status") == "queued":
            return i, q
    return None, None


# ── History Management ─────────────────────────────────────────────────────────

def load_history(limit=50):
    """Load song history, newest first. Auto-trims to limit."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        return history[:limit]
    except (json.JSONDecodeError, IOError):
        return []


def add_to_history(entry):
    """Add a completed song to history."""
    history = load_history(200)
    entry["completed_at"] = time.time()
    history.insert(0, entry)
    history = history[:200]
    with _write_lock:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)


def clear_history():
    """Clear song history."""
    if os.path.exists(HISTORY_FILE):
        os.remove(HISTORY_FILE)
    return {"success": True}


# ── Blocked URIs (revoked songs already pushed to Spotify) ──────────────────

def load_blocked_uris():
    """Load the list of blocked Spotify URIs (revoked tracks that were already pushed)."""
    if not os.path.exists(BLOCKED_URIS_FILE):
        return []
    try:
        with open(BLOCKED_URIS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def save_blocked_uris(uris):
    """Save the blocked URIs list to file."""
    with _write_lock:
        with open(BLOCKED_URIS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(set(uris)), f, indent=2)


def add_blocked_uri(uri):
    """Add a URI to the blocked list (revoked track that was already pushed to Spotify)."""
    if not uri:
        return
    blocked = load_blocked_uris()
    if uri not in blocked:
        blocked.append(uri)
        save_blocked_uris(blocked)
        _log_worker(f"Blocked URI added (revoked): {uri}")


def remove_blocked_uri(uri):
    """Remove a URI from the blocked list after skipping past it."""
    blocked = load_blocked_uris()
    if uri in blocked:
        blocked = [u for u in blocked if u != uri]
        save_blocked_uris(blocked)
        _log_worker(f"Blocked URI removed (skipped): {uri}")


# ── Song Queue Background Worker ────────────────────────────────────────────────

_song_queue_running = False


def _push_queued_songs(token, cfg, time_mod):
    """Push all queued songs to Spotify. Returns (queue, pushed_any)."""
    queue = load_queue()
    pushed_any = False
    for i, entry in enumerate(queue):
        if entry.get("status") != "queued":
            continue
        uri = entry.get("spotify_uri", "")
        if not uri:
            continue

        result = queue_track(uri)
        if "error" not in result:
            queue[i]["status"] = "pushed"
            queue[i]["pushed_at"] = time_mod.time()
            pushed_any = True
            _log_worker(f"Pushed to Spotify: {entry.get('track_name')} by {entry.get('artist')}")
        else:
            err = result.get("error", "")
            _log_worker(f"Push failed: {entry.get('track_name')} — {err}")
            # Stop trying if no active device or auth issue
            if "No active device" in err or "404" in err or "403" in err or "Token invalid" in err:
                break

    return queue, pushed_any


def _sync_playback_state(queue, last_seen_uri):
    """Sync Spotify playback state with our queue. Returns (queue, last_seen_uri, state_changed)."""
    playback = get_current_playback()
    if "error" in playback:
        return queue, last_seen_uri, False

    is_playing = playback.get("is_playing", False)
    current_item = playback.get("item")
    current_uri = current_item.get("uri") if current_item else None

    state_changed = False

    # If something is currently playing, mark it in our queue
    if current_uri:
        # Mark previous playing as played if it's a different track
        for q in queue:
            if q.get("status") == "playing" and q.get("spotify_uri") != current_uri:
                q["status"] = "played"
                state_changed = True
                try:
                    add_to_history(dict(q))
                except Exception as hist_err:
                    _log_worker(f"History add error: {hist_err}")

        # Mark current track as playing if it's in our queue
        for i, entry in enumerate(queue):
            if entry.get("spotify_uri") == current_uri and entry.get("status") in ("queued", "pushed"):
                queue[i]["status"] = "playing"
                state_changed = True
                break

    # If playback stopped and we had a playing track, mark it played
    if not current_uri and last_seen_uri:
        for q in queue:
            if q.get("spotify_uri") == last_seen_uri and q.get("status") == "playing":
                q["status"] = "played"
                state_changed = True
                try:
                    add_to_history(dict(q))
                except Exception as hist_err:
                    _log_worker(f"History add error: {hist_err}")

    return queue, current_uri, state_changed


def _auto_skip_blocked_uris(queue, current_uri):
    """Auto-skip blocked URIs (revoked songs already pushed to Spotify)."""
    if not current_uri:
        return queue, False

    blocked = load_blocked_uris()
    if current_uri not in blocked:
        return queue, False

    _log_worker(f"Auto-skipping blocked URI: {current_uri}")
    # Mark in our queue as skipped too
    for q in queue:
        if q.get("spotify_uri") == current_uri:
            q["status"] = "skipped"
            try:
                add_to_history(dict(q))
            except Exception:
                pass

    # Skip on Spotify
    skip_result = skip_track()
    if "error" in skip_result:
        _log_worker(f"Auto-skip failed: {skip_result['error']}")
    # Remove from blocked list — we've dealt with it
    remove_blocked_uri(current_uri)

    return queue, True


def process_song_queue():
    """Background loop: continuously push queued songs to Spotify and sync playback state."""
    import time as time_mod

    last_seen_uri = None

    while _song_queue_running:
        try:
            time_mod.sleep(30)

            token = get_valid_token()
            if not token:
                continue

            cfg = load_config()
            if not cfg.get("enabled", True):
                continue

            # Push any queued songs to Spotify
            queue, pushed_any = _push_queued_songs(token, cfg, time_mod)
            if pushed_any:
                save_queue(queue)

            # Sync playback state
            queue, last_seen_uri, state_changed = _sync_playback_state(queue, last_seen_uri)
            if state_changed:
                save_queue(queue)

            # Auto-skip blocked URIs (revoked songs already pushed to Spotify)
            playback = get_current_playback()
            if "error" not in playback:
                current_item = playback.get("item")
                current_uri = current_item.get("uri") if current_item else None
                queue, skipped = _auto_skip_blocked_uris(queue, current_uri)
                if skipped:
                    save_queue(queue)

        except Exception as e:
            _log_worker(f"Worker error: {e}")
            time_mod.sleep(10)


def start_song_queue_worker():
    """Start the background song queue worker thread."""
    global _song_queue_running
    if _song_queue_running:
        return
    _song_queue_running = True
    t = threading.Thread(target=process_song_queue, daemon=True)
    t.start()
    _log_worker("Worker started")


def stop_song_queue_worker():
    """Stop the background song queue worker."""
    global _song_queue_running
    _song_queue_running = False


# ── Permission Check ───────────────────────────────────────────────────────────

def check_permission(permission_type, user, tags, gifter_level, member_level):
    """
    Check if a user has permission for a command.
    
    Args:
        permission_type: "play", "skip", or "revoke"
        user: dict with keys unique_id, is_vip, is_superfan, is_member, is_friend, is_follower, is_mod
        tags: list of category tags
    
    Returns:
        True if allowed, False if denied
    """
    cfg = load_config()
    uid = user.get("unique_id", "").lower()
    
    if permission_type == "play":
        perm = cfg.get("play_permission", {})
        if perm.get("everyone", True):
            return True
        # Check specific groups
        if perm.get("superfans") and user.get("is_superfan"):
            return True
        if perm.get("members") and user.get("is_member"):
            return True
        if perm.get("mods") and user.get("is_mod"):
            return True
        if perm.get("vip") and user.get("is_vip"):
            return True
        if perm.get("followers") and user.get("is_follower"):
            return True
        if perm.get("friends") and user.get("is_friend"):
            return True
        # Check whitelist
        whitelist = [w.lower() for w in perm.get("whitelist", [])]
        if uid in whitelist:
            return True
        return False
    
    elif permission_type == "skip":
        perm = cfg.get("skip_permission", {})
        if perm.get("everyone"):
            return True
        if perm.get("followers") and user.get("is_follower"):
            return True
        if perm.get("friends") and user.get("is_friend"):
            return True
        if perm.get("superfans") and user.get("is_superfan"):
            return True
        if perm.get("members") and user.get("is_member"):
            return True
        if perm.get("mods") and user.get("is_mod"):
            return True
        if perm.get("vip") and user.get("is_vip"):
            return True
        # Check whitelist
        whitelist = [w.lower() for w in perm.get("whitelist", [])]
        if uid in whitelist:
            return True
        return False
    
    elif permission_type == "revoke":
        # Default: the requestor can always revoke their own
        return True  # Handled in remove_from_queue
    
    return False
