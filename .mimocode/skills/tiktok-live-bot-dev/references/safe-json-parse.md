# Safe `resp.json()` — Catch Non-JSON Responses

## The Problem

Python's `resp.json()` throws `json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)` when the API returns a non-JSON body (empty response, HTML error page, 429 rate-limit page). This cryptic error is useless to end users and breaks the dashboard's error display.

## The Fix: Try/Except with Graceful Fallback

Replace all bare `resp.json()` calls with a try/except that returns human-readable error dicts:

```python
if not resp.text:
    return {"error": f"Spotify returned {resp.status_code} with empty response"}
try:
    return resp.json()
except ValueError:
    return {"error": f"Spotify returned {resp.status_code} with non-JSON: {resp.text[:200]}"}
```

## Where This Is Needed

Every call to `resp.json()` in the codebase. In `spotify_handler.py` this covers:

| Function | Endpoint | What Can Go Wrong |
|----------|----------|-------------------|
| `_spotify_get()` | `/me/player`, `/search` | 429 rate-limit page (HTML), 502 gateway error |
| `_spotify_post()` | `/me/player/queue`, `/me/player/next` | 429, 403, 404 |
| `handle_callback()` | `accounts.spotify.com/api/token` | Empty response after 429, non-JSON error |
| `get_valid_token()` | `accounts.spotify.com/api/token` refresh | Same as above |

## Pre-existing Status Code Guards Are Not Enough

Before the try/except, all functions already checked for 401, 403, 404, 429, 204. But these are **success-like status codes where the body IS JSON**. The non-JSON case happens on:

- **429 on the accounts endpoint** — sometimes returns HTML or empty body, not JSON
- **502/503 gateway errors** — HTML error pages from Spotify's CDN
- **Network proxies** — injecting HTML error pages

The status code check comes first; if it doesn't match any known code, `resp.json()` is still called. That's where the try/except catches the fallthrough cases.

## Impact on Dashboard UX

Before:
- Dashboard shows "Connected" green dot (or no change)
- User sees no error
- Code silently returned `{"error": "Expecting value: line 1 column 1 (char 0)"}` to any caller that checked

After:
- Dashboard surface displays: `⚠ Spotify returned 429 with non-JSON: <html><head>...`
- Or: `⚠ Spotify rate limited — retry in 60s`
- Or: `⚠ Spotify returned 403 (Premium required or no active device)`
- User knows exactly what happened and what to do
