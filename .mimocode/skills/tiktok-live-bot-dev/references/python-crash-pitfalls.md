# Python `global` + `resp.json()` Crash Pitfalls

Two pure-Python bugs that bricked the TikTokMCIntegrator frozen EXE on 2026-05-22.

## 1. `global` must come BEFORE any read access

When you add a `global _rate_limit_until` to a function that ALSO reads the variable, Python's compiler sees the ENTIRE function as using the global. If the `global` declaration appears after any read:

```python
def _spotify_get(endpoint, params=None):
    if _rate_limited():              # reads _rate_limit_until
        remaining = int(_rate_limit_until - time.time())  # reads again
        ...
    ...
    if resp.status_code == 429:
        global _rate_limit_until      # TOO LATE — 50 lines after first read
        _rate_limit_until = time.time() + seconds
```

Result: `SyntaxError: name '_rate_limit_until' is used prior to global declaration`

The ENTIRE file (`spotify_handler.py`) becomes un-importable. PyInstaller silently skips the module. The frozen EXE can't import it and crashes with `ModuleNotFoundError: No module named 'spotify_handler'`.

**Correct pattern:** `global` at the VERY TOP of the function:

```python
def _spotify_get(endpoint, params=None):
    import requests as req
    global _rate_limit_until  # <— FIRST THING, before any read

    if _rate_limited():
        remaining = int(_rate_limit_until - time.time())
        ...
    if resp.status_code == 429:
        seconds = _parse_retry_after(resp.headers.get("Retry-After"))
        _rate_limit_until = time.time() + seconds
        return {"error": f"Spotify rate limited — retry in {int(_rate_limit_until - time.time())}s"}
```

**Verification:** Always syntax-check `.py` files after edits that touch globals:

```bash
C:\Python313\python.exe -c "import py_compile; py_compile.compile('D:\Ikhito\Code\TikTokMCIntegrator\spotify_handler.py', doraise=True); print('OK')"
```

## 2. Every `resp.json()` call is a frozen-EXE crash risk

`requests.Response.json()` throws `json.JSONDecodeError` if the response body is:
- HTML (Spotify rate-limit page, gateway error)
- Empty (502/503 server errors)
- Malformed JSON

In a PyInstaller-frozen EXE, this is an unhandled exception — the app dies silently with a traceback in the console.

**Affected functions that were unprotected:**

| Function | Line | What it does |
|----------|------|-------------|
| `_spotify_get()` | ~353 | GET `/me/player` — already had try/except |
| `_spotify_post()` | ~395 | POST `/me/player/queue` — already had try/except |
| `get_valid_token()` | ~204 | Token refresh via `accounts.spotify.com/api/token` — **was unprotected** |
| `handle_callback()` | ~253 | OAuth code exchange via `accounts.spotify.com/api/token` — **was unprotected** |

**Safe pattern (applies to ALL Spotify API callers):**

```python
if resp.status_code != 200:
    logger.warning(f"Request failed: {resp.status_code}")
    return None  # or {"error": "..."}

if not resp.text:
    logger.warning("Empty response body")
    return None  # or {"error": "..."}

try:
    data = resp.json()
except ValueError:
    logger.warning(f"Non-JSON response: {resp.text[:200]}")
    return None  # or {"error": "..."}

# Now safe to use data
```

**Check status codes BEFORE calling `.json()`:**
- 204 → empty dict (handled separately)
- 401 → token invalid
- 429 → rate limited (set `_rate_limit_until`)
- Non-200 → don't even try `.json()`
