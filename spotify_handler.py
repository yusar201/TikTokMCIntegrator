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

import base64
import hashlib
import json
import os
import secrets
import time
import threading
import logging

logger = logging.getLogger(__name__)

import sys

# Centralized path layout (config/ data/ logs/ assets/) — single frozen-aware root.
import paths
from spotify_app_config import SPOTIFY_CLIENT_ID

BASE_DIR = paths.BASE_DIR

SPOTIFY_REDIRECT_URI = "http://127.0.0.1:5000/api/spotify/callback"
SPOTIFY_SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"
_PENDING_OAUTH_TTL_SECONDS = 600
_pending_oauth = {}
_pending_oauth_lock = threading.Lock()

TOKEN_FILE = paths.data("song_spotify_token.json")
CONFIG_FILE = paths.data("song_config.json")
QUEUE_FILE = paths.data("song_queue.json")
HISTORY_FILE = paths.data("song_history.json")
WORKER_LOG_FILE = paths.logs("song_queue_worker.log")
BLOCKED_URIS_FILE = paths.data("song_blocked_uris.json")
FEEDBACK_FILE = paths.data("song_feedback.json")

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
    # Optional mirror to Minecraft chat. Off by default; enabled + scoped by
    # mc_feedback config. Never let a chat-mirror failure eat the toast.
    try:
        _mc_feedback_send(nick, feedback_type, title, detail)
    except Exception as e:
        print(f"[SONG MC-FEEDBACK] Failed to mirror to Minecraft: {e}")


# ── Minecraft chat feedback mirror (optional, off by default) ─────────────────
# Mirrors song-queue feedback (queued / skipped / pulled / errors / denied) into
# Minecraft chat via tellraw so players in-game can see what's happening with
# song requests. Zero changes to playback behavior — read-only mirror.

_MC_FEEDBACK_COLORS = {
    "success": "green",
    "error": "red",
    "denied": "gold",
}
_MC_FEEDBACK_ICONS = {
    "success": "✔",
    "error": "✖",
    "denied": "✖",
}
_MC_FEEDBACK_ENABLED_KEYS = {
    "success": "notify_success",
    "error": "notify_errors",
    "denied": "notify_denied",
}


def _mc_feedback_config() -> dict:
    """Live-read the Minecraft feedback mirror config from song_config.json."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f) or {}
        return cfg.get("mc_feedback") or {}
    except Exception:
        return {}


def _mc_feedback_escape(text) -> str:
    """Escape a string for safe inclusion inside a JSON tellraw string."""
    s = str(text or "")
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", " ").replace("\r", " ")
    return s


def _mc_feedback_send(nick, feedback_type, title, detail="") -> None:
    """Send one feedback line to Minecraft chat if enabled for this type.

    Disabled by default and per-type. Silently does nothing when the connector
    is unreachable so the song system never depends on Minecraft being up.
    """
    cfg = _mc_feedback_config()
    if not cfg.get("enabled", False):
        return
    if not cfg.get(_MC_FEEDBACK_ENABLED_KEYS.get(feedback_type, ""), False):
        return

    import minecraft_main

    color = _MC_FEEDBACK_COLORS.get(feedback_type, "white")
    icon = _MC_FEEDBACK_ICONS.get(feedback_type, "•")
    prefix = str(cfg.get("prefix", "[Music]")).strip() or "[Music]"

    # title already starts with "@nick —". Strip the leading @ for chat.
    body = _mc_feedback_escape(title.lstrip().lstrip("@"))
    parts = [
        f'{{"text":"{_mc_feedback_escape(prefix)} ","color":"dark_purple","italic":true}}',
        f'{{"text":"{icon} ","color":"{color}"}}',
        f'{{"text":"{body}","color":"{color}"}}',
    ]
    if detail:
        parts.append(
            f'{{"text":" {_mc_feedback_escape(detail)}","color":"gray","italic":true}}'
        )
    tellraw_cmd = "tellraw @a " + "[" + ",".join(parts) + "]"

    try:
        # Sync twin — spotify_handler has no event loop, and the async wrapper
        # would silently drop the command if called un-awaited.
        minecraft_main.send_minecraft_command_sync(tellraw_cmd)
    except Exception as e:
        print(f"[SONG MC-FEEDBACK] tellraw send failed: {e}")


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
        "enabled": True,
        # Minecraft chat mirror for song feedback. Off by default; when enabled,
        # song events (queued / skipped / pulled / errors / denied) are also said
        # in Minecraft chat via tellraw. Purely a read-only mirror of the toast —
        # it changes no playback behavior.
        "mc_feedback": {
            "enabled": False,
            "prefix": "[Music]",
            "notify_success": True,   # queued / skipped / pulled
            "notify_errors": True,    # search failures, queue full, etc.
            "notify_denied": True,    # permission denied, cooldown
        },
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
        # Developer credentials belonged to the legacy confidential-client flow.
        # Never surface or re-save them now that desktop auth uses bundled PKCE.
        for obsolete in ("spotify_client_id", "spotify_client_secret", "spotify_redirect_uri"):
            merged.pop(obsolete, None)
        for key in ("play_permission", "skip_permission"):
            nested = dict(defaults.get(key, {}))
            nested.update(cfg.get(key, {}) if isinstance(cfg.get(key), dict) else {})
            merged[key] = nested
        if any(key in cfg for key in ("spotify_client_id", "spotify_client_secret", "spotify_redirect_uri")):
            save_config(merged)
        return merged
    except (json.JSONDecodeError, IOError):
        return dict(defaults)


def save_config(data):
    """Save song config without legacy Spotify developer credentials."""
    clean = dict(data)
    for obsolete in ("spotify_client_id", "spotify_client_secret", "spotify_redirect_uri"):
        clean.pop(obsolete, None)
    with _write_lock:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2)
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

    # Tokens issued by the old secret-based flow cannot be refreshed safely once
    # the secret is removed. Force one clean reconnect to establish PKCE tokens.
    if token.get("oauth_flow") != "pkce":
        logger.info("Discarding legacy Spotify token; PKCE reconnect required")
        clear_token()
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

        client_id = get_spotify_client_id()
        if not client_id:
            return None

        try:
            refresh_data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token_val,
                "client_id": client_id,
            }
            resp = req.post(
                "https://accounts.spotify.com/api/token",
                data=refresh_data,
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning(f"Token refresh failed: {resp.status_code} {resp.text}")
                # invalid_grant = refresh token is expired/revoked (Spotify's 6-month
                # expiry, July 2026). DISCARD it and stop retrying — the user must
                # sign in again via the dashboard's "Connect Spotify" button.
                is_invalid_grant = False
                try:
                    is_invalid_grant = resp.json().get("error") == "invalid_grant"
                except ValueError:
                    is_invalid_grant = "invalid_grant" in resp.text
                if is_invalid_grant:
                    logger.warning("Refresh token expired/revoked (invalid_grant). "
                                   "Discarding token — user must reconnect Spotify.")
                    clear_token()
                    _token_refresh_until = 0  # no cooldown; token is gone, nothing to retry
                    return None
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
            new_token["oauth_flow"] = "pkce"
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


# ── OAuth Flow (Authorization Code + PKCE) ─────────────────────────────────────

import urllib.parse


def get_spotify_client_id():
    """Return the public Spotify application ID bundled with the desktop app."""
    return SPOTIFY_CLIENT_ID.strip()


def clear_pending_oauth():
    """Clear temporary in-memory PKCE state (used by disconnect/tests)."""
    with _pending_oauth_lock:
        _pending_oauth.clear()


def _prune_pending_oauth(now=None):
    now = time.time() if now is None else now
    expired = [state for state, item in _pending_oauth.items()
               if now - item.get("created_at", 0) > _PENDING_OAUTH_TTL_SECONDS]
    for state in expired:
        _pending_oauth.pop(state, None)


def begin_pkce_authorization():
    """Create one short-lived PKCE authorization request for Spotify."""
    client_id = get_spotify_client_id()
    if not client_id:
        return {"error": "TikTokMCIntegrator Spotify app is not configured"}

    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    state = secrets.token_urlsafe(32)
    with _pending_oauth_lock:
        _prune_pending_oauth()
        _pending_oauth[state] = {"code_verifier": verifier, "created_at": time.time()}

    params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": SPOTIFY_SCOPES,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    return {"url": "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)}


def handle_pkce_callback(code, state):
    """Validate OAuth state and exchange a Spotify code using its PKCE verifier."""
    import requests as req

    with _pending_oauth_lock:
        _prune_pending_oauth()
        pending = _pending_oauth.pop(state, None) if state else None
    if not pending:
        return {"error": "Spotify authorization state is invalid or expired. Please connect again."}

    try:
        resp = req.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": SPOTIFY_REDIRECT_URI,
                "client_id": get_spotify_client_id(),
                "code_verifier": pending["code_verifier"],
            },
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("Spotify PKCE token exchange failed: %s %s", resp.status_code, resp.text)
            return {"error": f"Spotify returned {resp.status_code}: {resp.text}"}
        if not resp.text:
            return {"error": "Spotify returned an empty response"}
        try:
            token = resp.json()
        except ValueError:
            return {"error": "Spotify returned an invalid response"}
        if "access_token" not in token:
            return {"error": "Spotify did not return an access token"}

        token["expires_at"] = int(time.time()) + token.get("expires_in", 3600)
        token["oauth_flow"] = "pkce"
        save_token(token)
        return {"status": "success", "message": "Connected to Spotify!"}
    except Exception as exc:
        logger.error("Spotify PKCE callback error: %s", exc)
        return {"error": str(exc)}


# Global rate-limit tracking
_rate_limit_until = 0  # epoch timestamp — skip all API calls until this time
_token_refresh_until = 0  # epoch timestamp — skip token refresh attempts until this time
_token_refresh_lock = threading.Lock()  # prevents concurrent refresh
_TOKEN_REFRESH_COOLDOWN = 60  # seconds between token refresh attempts

# Per-endpoint throttle (smoothing) — prevents burst patterns that trigger 429.
# Worker now polls every 5s, so without this we'd hit /me/player ~12x/min plus
# UI status polls, easy to burst into Spotify's rate limit. 500ms min interval
# per endpoint smooths it out. Different endpoints throttle independently.
_endpoint_last_call = {}  # endpoint -> last_call_epoch
_endpoint_throttle_lock = threading.Lock()
_ENDPOINT_MIN_INTERVAL = 0.5  # 500ms between same-endpoint calls


def _throttle_endpoint(endpoint):
    """Block until min interval has passed since last call to this endpoint.
    Returns nothing. Max wait is 1s. No-op on the first call per endpoint."""
    with _endpoint_throttle_lock:
        last = _endpoint_last_call.get(endpoint, 0)
        now = time.time()
        wait = _ENDPOINT_MIN_INTERVAL - (now - last)
        if wait > 0:
            time.sleep(min(wait, 1.0))
        _endpoint_last_call[endpoint] = time.time()


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
    # Per-endpoint throttle — smooth burst patterns
    _throttle_endpoint(endpoint)
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
    # Per-endpoint throttle — smooth burst patterns
    _throttle_endpoint(endpoint)

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


def _spotify_put(endpoint, data=None):
    """Make a PUT request to the Spotify API. (Added for play_track_immediate.)"""
    import requests as req
    global _rate_limit_until

    # Skip if we're in rate-limit cooldown
    if _rate_limited():
        remaining = int(_rate_limit_until - time.time())
        return {"error": f"Waiting for Spotify rate limit ({remaining}s left)."}
    # Per-endpoint throttle — smooth burst patterns
    _throttle_endpoint(endpoint)

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
        resp = req.put(
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
    """Return authorization and active-device status separately."""
    token = get_valid_token()
    if not token:
        return {
            "authorized": False,
            "connected": False,
            "needs_active_device": False,
            "error": "No token - please connect Spotify",
        }

    player = get_current_playback()
    if "error" in player:
        err_msg = player["error"]
        needs_device = "active device" in err_msg.lower()
        return {
            "authorized": True,
            "connected": False,
            "needs_active_device": needs_device,
            "error": err_msg,
        }

    # Spotify returns 204/empty playback until the user activates a device.
    is_playing = player.get("is_playing", False)
    device_name = player.get("device_name", "")
    if not device_name and not player.get("item"):
        return {
            "authorized": True,
            "connected": False,
            "needs_active_device": True,
            "error": "Open Spotify and play something first to activate a device",
        }

    return {
        "authorized": True,
        "connected": True,
        "needs_active_device": False,
        "device": device_name,
        "playing": is_playing,
        "item": player.get("item"),
    }


# ── Playback state cache (avoid rate limiting) ─────────────────────────────

_playback_cache = {"result": None, "cached_at": 0}
_PLAYBACK_CACHE_TTL = 3  # seconds — snappy pause/resume while staying well under Spotify rate limits
_playback_lock = threading.Lock()  # single-flight: collapse concurrent cache-misses into ONE real API call

# Device list cache — devices rarely change mid-stream. Single-flight + TTL so
# dashboard /devices polls and pre-play device checks don't hit /me/player/devices
# raw (the last uncached hot-path GET → sporadic 429 source, fixed 2026-06-16).
_devices_cache = {"result": None, "cached_at": 0}
_DEVICES_CACHE_TTL = 30  # seconds — devices barely change; long TTL = near-zero real calls
_devices_lock = threading.Lock()


def _get_cached_playback():
    """Get cached playback state, refreshing from Spotify if TTL expired.

    Single-flight: when the cache is stale and multiple threads (worker,
    overlay poll, dashboard poll) all miss at once, only the FIRST thread
    hits Spotify. The rest wait on the lock and reuse that fresh result.
    Without this, a cache miss fans out into 2-3 simultaneous /me/player
    calls, bursting against Spotify's rolling window and causing 429s.
    """
    global _playback_cache
    now = time.time()
    # Fast path — fresh cache, no lock needed
    if now - _playback_cache["cached_at"] < _PLAYBACK_CACHE_TTL:
        return _playback_cache["result"]

    with _playback_lock:
        # Re-check inside the lock: a thread that was waiting may now find
        # the cache was just refreshed by whoever held the lock first.
        now = time.time()
        if now - _playback_cache["cached_at"] < _PLAYBACK_CACHE_TTL:
            return _playback_cache["result"]
        # Fresh fetch (this thread is the single flight)
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


def _real_get_active_devices():
    """Get device list from Spotify (always hits API)."""
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


def get_active_devices():
    """Get list of available Spotify devices.

    Single-flight + TTL cache (mirrors get_current_playback). Devices rarely
    change mid-stream, so a 30s cache collapses dashboard /devices polls and
    pre-play device checks into near-zero real /me/player/devices calls — this
    was the last uncached hot-path GET causing sporadic 429s (fixed 2026-06-16).
    Zero added latency: fresh cache returns instantly, never blocks user actions.
    """
    global _devices_cache
    now = time.time()
    # Fast path — fresh cache, no lock
    if _devices_cache["result"] is not None and now - _devices_cache["cached_at"] < _DEVICES_CACHE_TTL:
        return _devices_cache["result"]
    with _devices_lock:
        now = time.time()
        if _devices_cache["result"] is not None and now - _devices_cache["cached_at"] < _DEVICES_CACHE_TTL:
            return _devices_cache["result"]
        result = _real_get_active_devices()
        # Don't cache error responses — retry fresh next time
        if isinstance(result, dict) and "error" in result:
            return result
        _devices_cache = {"result": result, "cached_at": now}
        return result


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
    """Queue a track to Spotify's active player. (Legacy — use play_track_immediate.)"""
    return _spotify_post(f"/me/player/queue?uri={uri}")


def play_track_immediate(uri):
    """Play a track IMMEDIATELY, replacing the current context.

    This is the correct way to start a song for our local-only queue architecture.
    Spotify's PUT /me/player/play with `uris` and NO `context_uri` replaces the
    entire playback context with just this track, so /me/player/next falls through
    to the user's queue (and our local queue has no items anyway). It also
    disables repeat so the new track doesn't auto-loop.

    Returns success dict or error dict.
    """
    # Disable repeat so the new track doesn't auto-loop
    _spotify_put("/me/player/repeat?state=off")
    result = _spotify_put("/me/player/play", {
        "uris": [uri],
    })
    # Invalidate the playback cache so the very next get_current_playback()
    # reflects the track we just started — NOT the stale previous track.
    # Without this, the worker's _sync_playback_state can see the old (loop)
    # URI for up to _PLAYBACK_CACHE_TTL seconds and wrongly conclude our new
    # "playing" song already ended, auto-skipping the next request on top of it.
    _playback_cache["cached_at"] = 0
    return result


def play_next_from_queue():
    """Play the next queued song from our LOCAL queue via play_track_immediate.

    Used by the worker (song ended naturally) and the !skip handler. This is the
    right way to advance — never push to Spotify's queue, always start the next
    track explicitly with play_track_immediate. That way, !revoke is always
    instant (just remove from local file) and we never have to "undo" what we
    pushed to Spotify.

    Returns True if a song was played, False if queue is empty or error.
    """
    queue = load_queue()
    pos, entry = None, None
    for i, q in enumerate(queue):
        if q.get("status") == "queued":
            pos, entry = i, q
            break
    if pos is None or entry is None:
        return False

    uri = entry.get("spotify_uri", "")
    if not uri:
        return False

    result = play_track_immediate(uri)
    if "error" in result:
        _log_worker(f"play_next_from_queue failed: {result['error']}")
        return False

    # Mark previous "playing" as "played", mark new one as "playing"
    queue = load_queue()
    for q in queue:
        if q.get("status") == "playing":
            q["status"] = "played"
            try:
                add_to_history(dict(q))
            except Exception:
                pass
        if q.get("spotify_uri") == uri and q.get("status") == "queued":
            q["status"] = "playing"
    save_queue(queue)

    _log_worker(f"Playing next from queue: {entry.get('track_name')}")
    return True


def skip_track():
    """Skip to next track.

    For local-only architecture: skip_track() is just Spotify's /me/player/next.
    Callers (worker, !skip handler) should call play_next_from_queue() AFTER
    skip_track() to start the next song immediately (otherwise Spotify would
    skip into silence until it reaches the next track in its own queue — and
    we don't push to Spotify's queue anymore)."""
    _spotify_put("/me/player/repeat?state=off")
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


def remove_from_queue(position, requested_by, allow_any=False):
    """Remove a queued/pushed track by position.

    Viewer pulls must match requested_by. Dashboard removals pass allow_any=True
    because the dashboard X button is an operator/admin control, not a viewer
    permission path. Currently playing songs are intentionally protected here;
    use skip for the active track.
    """
    queue = load_queue()
    if position < 0 or position >= len(queue):
        return {"error": "Invalid queue position"}

    entry = queue[position]
    if entry.get("status") not in ("queued", "pushed"):
        return {"error": "Cannot remove the currently playing song. Use skip instead."}

    if not allow_any and entry.get("requested_by", "").lower() != requested_by.lower():
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
    """Sync Spotify playback state with our queue. Returns (queue, last_seen_uri, state_changed, playback)."""
    playback = get_current_playback()
    if "error" in playback:
        return queue, last_seen_uri, False, playback

    is_playing = playback.get("is_playing", False)
    current_item = playback.get("item")
    current_uri = current_item.get("uri") if current_item else None

    state_changed = False

    # If something is currently playing, mark it in our queue
    if current_uri:
        # NOTE: We intentionally do NOT mark a "playing" song as "played" just
        # because Spotify reports a different current_uri on a single tick.
        # In the local-only architecture, Spotify never advances to a different
        # track on its own — a mismatch here is ALWAYS either (a) a stale 2s
        # playback cache right after play_track_immediate(), or (b) the loop
        # song. Acting on a single-tick mismatch caused the auto-skip bug:
        # song A would be flipped to "played" off a stale loop-song reading,
        # so the next !play B fell through the handler's "nothing playing
        # locally" branch and replaced A instead of queuing behind it.
        # Natural song-end is handled robustly elsewhere: the clean-204 branch
        # below (current_uri=None) and the 3-tick idle counter in
        # process_song_queue(). Those are the only authorities for "played".

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

    return queue, current_uri, state_changed, playback


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


def _next_queue_poll_delay(is_playing, progress_ms, duration_ms,
                           has_local_playing, has_queued):
    """Return a rate-limit-safe delay that wakes just after the expected end.

    Normal polling remains at five seconds.  We only shorten a single sleep
    when a local song is actively playing, another song is waiting, and the
    current track is less than five seconds from its reported end.
    """
    normal_delay = 5.0
    if not (is_playing and has_local_playing and has_queued):
        return normal_delay
    if duration_ms <= 0 or progress_ms < 0 or progress_ms >= duration_ms:
        return normal_delay
    remaining_seconds = (duration_ms - progress_ms) / 1000.0
    if remaining_seconds >= normal_delay:
        return normal_delay
    # Wake just after the boundary, avoiding an early stale playback sample.
    return max(0.25, remaining_seconds + 0.2)


def process_song_queue():
    """Background loop: continuously push queued songs to Spotify and sync playback state."""
    import time as time_mod

    last_seen_uri = None
    consecutive_idle_ticks = 0  # Bug 6: track how long we've been in idle state
    PLAYING_URI = ""  # Bug 6: track who the local "playing" song is
    poll_delay = 5.0

    while _song_queue_running:
        try:
            scheduled_end_probe = poll_delay < 5.0
            time_mod.sleep(poll_delay)
            poll_delay = 5.0

            # An adaptive wake can occur inside the normal playback-cache TTL.
            # Force exactly this boundary probe fresh; otherwise it could reuse
            # the pre-end snapshot and buy no latency improvement.
            if scheduled_end_probe:
                _playback_cache["cached_at"] = 0

            token = get_valid_token()
            if not token:
                continue

            cfg = load_config()
            if not cfg.get("enabled", True):
                continue

            # Load the current local queue
            queue = load_queue()

            # Sync playback state
            queue, last_seen_uri, state_changed, playback = _sync_playback_state(queue, last_seen_uri)
            if state_changed:
                save_queue(queue)
                _log_worker(f"Worker sync: state changed, queue updated")
                # If we just marked a song as played, advance the local queue
                # by starting the next one with play_track_immediate. This is
                # the local-only architecture: never push to Spotify's queue.
                if any(q.get("status") == "queued" for q in queue):
                    if not play_next_from_queue():
                        _log_worker("Worker sync: no next song to play")

            # Bug 6: detect stuck state — local queue has a "playing" song but
            # Spotify's playback has been idle for many ticks. This happens when
            # a user song ends naturally but Spotify is slow to return 204, so
            # _sync_playback_state can't mark it as played. Without this, the
            # next song never plays because we think the current one is still
            # "playing".
            # Reuse the playback dict from _sync_playback_state above — no
            # second API call. (get_current_playback is cached, but reusing
            # avoids even a cache lookup and guarantees both checks see the
            # exact same snapshot within this tick.)
            if "error" in playback:
                continue
            is_playing = playback.get("is_playing", False)
            spotify_current_uri = (playback.get("item") or {}).get("uri")
            progress_ms = playback.get("progress_ms", 0)
            duration_ms = (playback.get("item") or {}).get("duration_ms", 0)

            # Find local "playing" song (if any)
            local_playing = next(
                (q for q in queue if q.get("status") == "playing"),
                None
            )
            local_playing_uri = local_playing.get("spotify_uri") if local_playing else ""
            has_queued = any(q.get("status") == "queued" for q in queue)

            # Keep the rate-limit-safe five-second cadence, but when Spotify's
            # own position says this song will end sooner, wake once just after
            # that boundary. This removes the random remainder of the poll
            # interval without adding continuous API traffic.
            poll_delay = _next_queue_poll_delay(
                is_playing, progress_ms, duration_ms,
                bool(local_playing), has_queued,
            )

            # Distinguish a USER PAUSE from a NATURAL SONG END.
            # Both report is_playing=False, so position is the discriminator.
            # A real user-pause is ALWAYS meaningfully into the song and frozen
            # somewhere in the middle. A natural end looks different:
            #   - Spotify returns 204 / clears the item (uri differs), OR
            #   - the finished track is left loaded but progress is reset to ~0
            #     (single track ended, repeat off, nothing else in context), OR
            #   - progress sits at/near duration_ms.
            # So we treat it as a USER PAUSE only when: paused, same track still
            # loaded, progress is past MIN_PAUSE_PROGRESS_MS (not a reset-to-0
            # natural end) AND not within END_GRACE_MS of the track end.
            # Everything else advances to the next queued song as before.
            END_GRACE_MS = 12000          # within 12s of the end = treat as ended
            MIN_PAUSE_PROGRESS_MS = 5000  # must be >5s in to count as a real pause
            same_track = bool(local_playing_uri) and spotify_current_uri == local_playing_uri
            near_end = (
                duration_ms > 0 and progress_ms > 0
                and (duration_ms - progress_ms) <= END_GRACE_MS
            )
            paused_mid_song = (
                (not is_playing)
                and same_track
                and progress_ms > MIN_PAUSE_PROGRESS_MS
                and not near_end
            )

            # If local says one song is playing, but Spotify says nothing/other,
            # and this has persisted across multiple ticks → mark local playing
            # as played and start the next one via play_next_from_queue.
            # BUT: never advance while the user is paused mid-song.
            if local_playing and not paused_mid_song and (not is_playing or spotify_current_uri != local_playing_uri):
                if PLAYING_URI == local_playing_uri and local_playing_uri:
                    consecutive_idle_ticks += 1
                else:
                    PLAYING_URI = local_playing_uri
                    consecutive_idle_ticks = 1
                # How many idle ticks before we conclude the song ended and
                # advance. near_end is an UNAMBIGUOUS end (progress sat at/near
                # the track's full duration — impossible to confuse with a
                # pause-at-start), so we fast-path it on the very next poll
                # (1 tick, ~5s). The ambiguous case (track cleared or progress
                # reset to ~0) keeps a short safety wait (2 ticks, ~10s) so we
                # never misfire on a genuine mid-song pause.
                required_ticks = 1 if (near_end or scheduled_end_probe) else 2
                if consecutive_idle_ticks >= required_ticks:
                    _log_worker(
                        f"Worker: local playing '{local_playing_uri[:20]}...' "
                        f"ended (near_end={near_end}, ticks={consecutive_idle_ticks}). "
                        f"Advancing to next song."
                    )
                    local_playing["status"] = "played"
                    try:
                        add_to_history(dict(local_playing))
                    except Exception:
                        pass
                    save_queue(queue)
                    consecutive_idle_ticks = 0
                    PLAYING_URI = ""
                    # Advance the local queue — start the next song now
                    if not play_next_from_queue():
                        # No next song → fall back to loop song
                        loop_uri = cfg.get("loop_song_uri", "").strip()
                        if loop_uri:
                            _log_worker("Worker: no next in queue, resuming loop song")
                            play_track_immediate(loop_uri)
                    continue
            else:
                consecutive_idle_ticks = 0
                PLAYING_URI = local_playing_uri

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
