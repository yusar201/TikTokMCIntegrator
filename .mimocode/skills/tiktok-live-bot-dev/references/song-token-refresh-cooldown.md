# Song Token Refresh Cooldown Defense

Spotify has **two separate rate limits**: the data API (`api.spotify.com`) and the accounts API (`accounts.spotify.com`). The accounts API rate limit is MUCH harsher — bans can be hours long (>25,000 seconds). A single unthrottled token refresh path can trigger this ban within minutes.

## Root Cause Pattern

When `get_valid_token()` encounters an expired token:
1. Every caller (dashboard status poll, worker loop, overlay poll, queue/skip API) independently calls `get_valid_token()`
2. If refresh fails (429, network error, invalid credentials), EVERY caller retries on its next cycle
3. Dashboard polls at 3s, worker at 30s, overlay at 1s → ~20-30 refresh calls/min
4. Spotify interprets this as credential abuse → 7+ hour ban on the accounts endpoint

## The Fix: Global Cooldown + In-Progress Flag

```python
import threading as _threading
import time as _time

_TOKEN_REFRESH_COOLDOWN = 60  # seconds — shared by all callers
_token_refresh_until = 0       # epoch timestamp, skip refreshes until this
_is_token_refreshing = False   # prevents concurrent refresh calls
_refresh_lock = _threading.Lock()

def get_valid_token():
    """Get a valid token, refreshing if needed. Returns dict or None."""
    global _token_refresh_until, _is_token_refreshing

    if not os.path.exists(TOKEN_FILE):
        return None

    # Enforce cooldown — ALL callers blocked for _TOKEN_REFRESH_COOLDOWN
    now = _time.time()
    if now < _token_refresh_until:
        return None  # silently skip, don't even try

    try:
        with open(TOKEN_FILE, "r") as f:
            token = json.load(f)
    except Exception:
        return None

    expires_at = token.get("expires_at", 0)
    if expires_at and now < expires_at - 60:
        return token  # Still valid

    refresh_token_val = token.get("refresh_token")
    if not refresh_token_val:
        return None

    # Prevent concurrent refreshes (two callers hit this simultaneously)
    with _refresh_lock:
        if _is_token_refreshing:
            return None  # another caller is already refreshing
        _is_token_refreshing = True

    try:
        cfg = load_config()
        client_id = cfg.get("spotify_client_id", "")
        client_secret = cfg.get("spotify_client_secret", "")
        if not client_id or not client_secret:
            return None

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
            logger.warning(f"Token refresh failed: {resp.text}")
            # Set cooldown on ANY failure (not just 429) — network errors count too
            _token_refresh_until = now + _TOKEN_REFRESH_COOLDOWN
            return None

        if not resp.text:
            logger.warning("Token refresh returned empty body")
            _token_refresh_until = now + _TOKEN_REFRESH_COOLDOWN
            return None

        try:
            new_token = resp.json()
        except ValueError:
            logger.warning(f"Token refresh non-JSON: {resp.text[:200]}")
            _token_refresh_until = now + _TOKEN_REFRESH_COOLDOWN
            return None

        # If Spotify sends 429 on the accounts endpoint, respect Retry-After
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", str(_TOKEN_REFRESH_COOLDOWN))
            seconds = _parse_retry_after(retry_after)
            _token_refresh_until = now + seconds
            return None

        new_token["expires_at"] = int(now) + new_token.get("expires_in", 3600)
        if "refresh_token" not in new_token:
            new_token["refresh_token"] = refresh_token_val
        save_token(new_token)
        _token_refresh_until = 0  # reset cooldown on success
        return new_token

    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        _token_refresh_until = now + _TOKEN_REFRESH_COOLDOWN
        return None
    finally:
        with _refresh_lock:
            _is_token_refreshing = False
```

## Key Points

- **Cooldown blocks EVERYTHING** — `_token_refresh_until` gates the entire function. All callers (dashboard, worker, overlay) see the same gate.
- **Cooldown on ANY failure** — Not just 429. Network errors, bad credentials, empty responses — all trigger the cooldown. A single failure per minute is fine; 30/min is a ban.
- **In-progress flag** — Prevents two callers from both trying to refresh simultaneously (race condition between Flask + subprocess).
- **Retry-After on accounts 429** — Spotify's accounts API also sends Retry-After headers. Respect them — they may be longer than our local cooldown.

## Rate Limit Comparison

| Endpoint | Ban Duration | Trigger |
|----------|-------------|---------|
| `api.spotify.com` (data) | 30-60s | ~30 req/min |
| `accounts.spotify.com` (auth) | 7+ hours | ~30 req/min |

The accounts ban is ~400x longer than the data ban. Never let the token refresh run unthrottled.
