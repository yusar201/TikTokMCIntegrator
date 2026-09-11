# Song Requests UI Build Pitfalls

Context: TikTokMCIntegrator Song tab + `/overlay/song` implementation.

## User taste signals

- Do not ship raw stacked form UIs. The user strongly dislikes dashboards that look like default HTML scaffolding.
- Avoid visible empty columns/gaps. If a two-column dashboard leaves a big canyon in the middle, extend the main column or rebalance the grid.
- Controls must be readable and aligned. Tiny inputs/buttons are not acceptable for this user's dashboard work.
- Permission matrices should be symmetrical unless there is a clear reason not to be. For song requests, `!play` and `!skip` should expose the same categories, even if defaults differ.

## Recommended Song tab layout

Use a polished dashboard layout:

- Hero/header: Spotify status, active device, connect/disconnect actions.
- Main column: Commands & Spotify credentials, Queue, Test Search.
- Side column: Permissions, History.
- Cards should fill their grid columns (`width: 100%`) and use consistent spacing.
- Prefer class-based CSS over inline style blobs.

## CSS scoping pitfall

The overlay and dashboard both used `.song-card`. The overlay CSS set:

```css
.song-card { width: 340px; }
```

That leaked into the dashboard and caused narrow cards + a huge middle gap.

Fix by scoping overlay selectors:

```css
.song-overlay-wrap .song-card { width: 340px; }
.song-page .song-card { width: 100%; }
```

When sharing generic component names between overlay templates and dashboard panels, always scope by container (`.song-overlay-wrap`, `.song-page`) to prevent cross-surface style leaks.

## Permission matrix standard

For Song Requests, expose the same categories for `!play` and `!skip`:

- Everyone
- Followers
- Friends
- SuperFans
- Members
- Moderators
- VIP
- Whitelist

Recommended defaults:

- `!play`: Everyone enabled.
- `!skip`: Moderators + VIP enabled only.

Backend config should include all keys for both permission blocks, and `load_config()` should deep-merge nested permission defaults so older `song_config.json` files get new keys automatically.

## Release sync reminder

**⛔ NEVER `rm -rf release/TikTokMCIntegrator`.** The release folder is the user's LIVE runtime directory — config.yml, profiles/, song_spotify_token.json, and all runtime JSON logs live there. A full delete-and-replace destroys everything.

Frontend-only UI fixes do not require rebuild, but must be copied to the release `_internal` files:

```bash
cp templates/index.html release/TikTokMCIntegrator/_internal/templates/index.html
cp static/script.js release/TikTokMCIntegrator/_internal/static/script.js
cp static/style.css release/TikTokMCIntegrator/_internal/static/style.css
```

After a full PyInstaller rebuild, deploy by copying only the `.exe` + `_internal/` from `dist/` into `release/`, preserving all runtime config files in the release root.

Backend permission logic changes in `spotify_handler.py` still require a PyInstaller rebuild to affect the exe.

## JS silent render failure — undefined helper in template literals

The song test search rendered NOTHING — no results, no error, no "Searching..." text. Root cause: the song section code calls `esc()` but the function is defined as `escHtml()` at line 1702. Template literals with undefined functions throw `ReferenceError` silently in async try/catch where the catch block also calls `esc()`, creating an unhandled promise rejection with zero DOM output.

**Fix:** Add `const esc = escHtml;` alias after the `escHtml` function definition. Both names now work.

**How to detect:** When a button click shows zero visual reaction, search for calls to helper functions used in template literals and verify function name matches definition. Check the browser console for uncaught ReferenceErrors.

## Spotify token save silently fails after callback

The OAuth callback showed "Connected!" but no `song_spotify_token.json` was written. The token exchange with Spotify succeeded (200 response, valid `access_token`), but `save_token()` either failed silently or was never called.

**Fix pattern — add print() debug logging to both handler and saver:**

```python
# In handle_callback:
if "access_token" not in token:
    print(f"[SPOTIFY] No access_token in response: {token}")
    return {"error": "Spotify did not return an access token"}

try:
    save_token(token)
    print(f"[SPOTIFY] Token saved to {TOKEN_FILE}")
except Exception as e:
    print(f"[SPOTIFY] Failed to save token: {e}")
    return {"error": f"Failed to save token: {e}"}

# In save_token:
try:
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2)
    print(f"[SPOTIFY] Token saved to {TOKEN_FILE}")
except Exception as e:
    print(f"[SPOTIFY] ERROR saving token to {TOKEN_FILE}: {e}")
    raise
```

**Also log the callback itself:**
```python
@app.route("/api/spotify/callback", methods=["GET"])
def spotify_callback():
    code = request.args.get("code")
    error = request.args.get("error")
    print(f"[SPOTIFY] Callback received — code={'present' if code else 'missing'}, error={error}")
```

**Diagnosis:** If the token file is missing after a successful-looking connect, check the console output for `[SPOTIFY]` lines. Possible causes: `TOKEN_FILE` resolves to an unexpected path, file permission denied, or the callback route never received a `code` parameter (redirect URI mismatch between Spotify app settings and `song_config.json`).

## OAuth callback error surfacing (spotify-error postMessage)

When the OAuth callback (`/api/spotify/callback`) fails (token exchange returns error, save_token fails), the original code returned `jsonify(result), 400` — the popup shows raw JSON text. No toast fires on the dashboard. The user closes the popup confused.

**Fix — return HTML with postMessage even on error:**

```python
result = sh.handle_callback(code, client_id, client_secret, redirect_uri)
if "error" in result:
    return f"""
    <!DOCTYPE html>
    <html>
    <body>
    <p>Spotify connection failed: {result['error']}</p>
    <script>
      window.opener.postMessage({{type: 'spotify-error', error: '{result['error']}'}}, '*');
      setTimeout(() => window.close(), 3000);
    </script>
    </body>
    </html>
    """, 400
```

**Dashboard side — listen for spotify-error:**

```javascript
window.addEventListener('message', function handler(event) {
  if (event.data && event.data.type === 'spotify-connected') {
    showToast('Connected to Spotify!', 'success');
    fetchSpotifyStatus();
    window.removeEventListener('message', handler);
  } else if (event.data && event.data.type === 'spotify-error') {
    showToast('Spotify connection failed: ' + event.data.error, 'error');
    fetchSpotifyStatus();
    window.removeEventListener('message', handler);
  }
});
```

This ensures the user always sees feedback — success toast OR red error toast — and never a silent white page with JSON text.

## Connection status false-positive (204 No Content = "Connected" bug)

Spotify's `/me/player` endpoint returns **204 No Content** when there's no active device. `_spotify_get` silently returns `{}` for 204. Then `get_current_playback()` sees empty data and returns `{"is_playing": False, "device_name": "", "item": None}` — no error key. `get_connection_status()` sees no error → returns `connected: True`. Dashboard shows green dot + "Connected" — but the API won't respond to queue/skip.

**Fix — check for empty device + item:**

```python
def get_connection_status():
    token = get_valid_token()
    if not token:
        return {"connected": False, "error": "No token — please connect Spotify"}

    player = get_current_playback()
    if "error" in player:
        return {"connected": False, "error": player["error"]}

    # 204 false-positive: empty data means no active device
    device_name = player.get("device_name", "")
    if not device_name and not player.get("item"):
        return {"connected": False, "error": "No active Spotify device — open Spotify and play something"}

    return {"connected": True, ...}
```

**Dashboard side — surface errors to the user:**

```javascript
if (data.connected) {
  // green dot
} else {
  text.textContent = data.error || (data.has_credentials ? 'Not Connected' : 'Not Configured');
  deviceName.textContent = data.error ? `⚠ ${data.error}` : '';
}
```

Without this, errors are swallowed and the user gets zero information about why Spotify isn't working.
