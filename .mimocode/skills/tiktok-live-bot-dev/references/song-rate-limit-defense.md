# Spotify Rate Limit Defense

Context: TikTokMCIntegrator was hitting Spotify's per-app rate limit (~429 requests per 30s) by polling `/me/player` from multiple sources at the same time. Symptoms: JSON parse errors (`Expecting value: line 1 column 1 (char 0)`) from `requests.Response.json()` receiving HTML/empty bodies from Spotify's rate-limit or server-error responses.

## Architecture

Four-tier defense:

1. **Backend playback state cache** (8s TTL) — single daemon-level cache in `spotify_handler.py` that all callers share. The status poll, worker loop, and overlay endpoint all call the same `get_current_playback()`, which serves cached data for 8 seconds instead of hitting Spotify each time.

2. **Global rate-limit cooldown** (`_rate_limit_until`) — when ANY API call gets 429, a module-level epoch timestamp is set. ALL subsequent calls (`_spotify_get`, `_spotify_post`) check this first and return immediately without hitting Spotify at all. This prevents the "hammering while rate limited" escalation pattern where each successive violation gets a longer Retry-After.

3. **Reduced frontend polling intervals** — Queue: 3s (was 2s), History: 5s (was 3s), Status: 10s (was 3s). The cache handles the actual backpressure; the reduced intervals just reduce unnecessary request load.

4. **Graceful non-JSON response handling** — `_spotify_get()` wraps `resp.json()` in try/except ValueError with a clear error message showing the HTTP status code and first 200 chars of the body.

## Implementation

### Global Cooldown (rate_limit_until)

Module-level variables in `spotify_handler.py`:

```python
_rate_limit_until = 0  # epoch timestamp — skip all API calls until this time

def _parse_retry_after(header_value):
    """Parse Retry-After header: supports both seconds (int) and HTTP-date (RFC 7231)."""
    if not header_value:
        return 30  # default fallback
    try:
        return int(header_value)
    except (ValueError, TypeError):
        pass
    # Try HTTP-date format: "Wed, 22 May 2026 18:00:00 GMT"
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(header_value)
        return int(dt.timestamp() - time.time()) + 1  # +1 for safety margin
    except Exception:
        return 30  # final fallback

def _rate_limited():
    """Check if we're currently in a rate-limit cooldown."""
    return time.time() < _rate_limit_until
```

Both `_spotify_get` and `_spotify_post` must declare `global _rate_limit_until` at the TOP of the function, before any code reads or writes the variable:

```python
def _spotify_get(endpoint, params=None):
    """Make a GET request to the Spotify API."""
    import requests as req
    global _rate_limit_until  # ⚠️ MUST be at top — before any read access

    # Skip if we're in rate-limit cooldown
    if _rate_limited():
        remaining = int(_rate_limit_until - time.time())
        return {"error": f"Waiting for Spotify rate limit ({remaining}s left)."}
    ...
    if resp.status_code == 429:
        seconds = _parse_retry_after(resp.headers.get("Retry-After"))
        _rate_limit_until = time.time() + seconds
        return {"error": f"Spotify rate limited — retry in {int(_rate_limit_until - time.time())}s"}

def _spotify_post(endpoint, data=None):
    """Make a POST request to the Spotify API."""
    import requests as req
    global _rate_limit_until  # ⚠️ Same — at top before any read

    if _rate_limited():
        ...
```

**⛔ Python rule:** `global <name>` applies to the ENTIRE function scope at compile time. If the variable is read on line 5 but `global` is declared on line 15, the entire FILE is un-importable — `SyntaxError: name '_rate_limit_until' is used prior to global declaration`. PyInstaller silently omits the module; the frozen EXE crashes with `ModuleNotFoundError` at `import spotify_handler as sh`. Always verify with syntax check after edits: `C:\Python313\python.exe -c "import py_compile; py_compile.compile('path/file.py', doraise=True); print('OK')"`
```

### Playback State Cache

Add at the module level of `spotify_handler.py`, right before the Public API section:

```python
_playback_cache = {"result": None, "cached_at": 0}
_PLAYBACK_CACHE_TTL = 8  # seconds

def _get_cached_playback():
    global _playback_cache
    now = time.time()
    if now - _playback_cache["cached_at"] < _PLAYBACK_CACHE_TTL:
        return _playback_cache["result"]
    result = _real_get_current_playback()
    # ⚠️ CRITICAL: Don't cache error responses — they NEVER clear from cache otherwise,
    # creating an infinite rate-limit loop. Force retry next cycle by setting cached_at to past.
    if isinstance(result, dict) and "error" in result:
        _playback_cache = {"result": result, "cached_at": now - _PLAYBACK_CACHE_TTL - 1}
        return result
    _playback_cache = {"result": result, "cached_at": now}
    return result

def _real_get_current_playback():
    """Always hits Spotify API (wrapped by the cache above)."""
    data = _spotify_get("/me/player")
    if "error" in data:
        return data
    if not data:
        return {"is_playing": False, "device_name": "", "item": None}
    ...

def get_current_playback():
    """Public API — uses cache."""
    return _get_cached_playback()
```

Note: `get_connection_status()` calls `get_current_playback()` which is now cached. The status dot may lag by up to 8 seconds. Acceptable trade-off vs rate limiting.

### Frontend Polling

In `script.js`'s `init()`:

```javascript
setInterval(fetchSongQueue, 3000);      // was 2000
setInterval(fetchSongHistory, 5000);    // was 3000
setInterval(fetchSpotifyStatus, 10000); // was 3000
```

### Worker Sleep

```python
time_mod.sleep(30)  # was 3 — also doubles as revoke window
```

## Pitfalls

- **⛔ Without the global cooldown, the rate limit ESCALATES.** Each poll cycle (even cached at 8s) hits Spotify and gets a 429. Each 429 has a progressively longer Retry-After. With the cooldown, ZERO requests hit Spotify during the ban — the cooldown timer is the only bound. The old code hit Spotify every single cycle and escalated the ban from 30s to hours.

- **⛔ Cache stores error responses — infinite rate-limit loop** — The 8s cache caches ANY result from `_real_get_current_playback()`, including `{"error": "Spotify returned 429"}`. Once a 429 is cached, it serves it for 8 seconds. After TTL expires, the fresh fetch ALSO gets a 429 (rate limit hasn't cleared yet) → cached again → infinite loop. The dashboard shows "rate limited" forever even after Spotify's Retry-After expires. **Fix:** detect error results and set `cached_at` to the past so the next cycle skips the cache:
  ```python
  result = _real_get_current_playback()
  if isinstance(result, dict) and "error" in result:
      _playback_cache = {"result": result, "cached_at": now - _PLAYBACK_CACHE_TTL - 1}
      return result
  _playback_cache = {"result": result, "cached_at": now}
  ```
  This also means the error message reaches the dashboard (one cycle) instead of being hidden from the user. Combined with the global cooldown, only ONE 429 response is ever cached — subsequent cycles skip both the cache AND the Spotify call.

- **Cache returns `None` on first call** until the first fresh fetch completes. The initial `cached_at: 0` means `time.time() - 0 > 8`, so the first caller always triggers a fetch immediately.

- **`Expecting value: line 1 column 1 (char 0)`** is a `json.JSONDecodeError`, not a Spotify error. Common causes: 429 (HTML body), 502/503 (gateway error page), empty body from connection issues. **Fix:** check `resp.status_code` before trying to parse, and wrap `resp.json()` in try/except ValueError:

  ```python
  if resp.status_code == 429:
      retry_after = resp.headers.get("Retry-After", "60")
      return {"error": f"Spotify rate limited — retry in {retry_after}s"}
  if resp.status_code == 204:
      return {}
  if not resp.text:
      return {"error": f"Spotify returned {resp.status_code} with empty response"}
  try:
      return resp.json()
  except ValueError:
      return {"error": f"Spotify returned {resp.status_code} with non-JSON: {resp.text[:200]}"}
  ```

- **`_parse_retry_after` must import `email.utils.parsedate_to_datetime`** locally or at module level. The HTTP-date format is rare but Spotify sometimes sends it for escalated bans. The parser handles both formats and falls back to 30s default.

- **Rate limit is per Spotify App (Client ID), not per user.** Multiple bots/services sharing the same Client ID share the rate limit budget.

- **Worker logs a failure every 30s** if rate limited continues. Only visible in `song_queue_worker.log`.
