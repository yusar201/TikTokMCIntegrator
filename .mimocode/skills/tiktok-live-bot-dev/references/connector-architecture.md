# Connector Architecture — RCON · Forge · ServerTap

## Overview

TikTokMCIntegrator supports 3 Minecraft connector types. The dashboard selects one, the bot dispatches every command to it.

| Connector | Protocol | Default Port | Use Case |
|-----------|----------|-------------|----------|
| **RCON** | TCP (mcrcon) | 25575 | Classic dedicated servers (Paper, Mohist, Spigot) |
| **Forge Mod** | HTTP POST | 5942 | Single-player / client-side mod integration |
| **ServerTap** | HTTP REST | 4567 | Paper/Spigot with ServerTap plugin |

## Code Architecture (minecraft_main.py)

### 1. Config reader
Each connector has a live-read config function that reads from `config.yml` every call:
- `_get_rcon_config()` → `{Host, Port, Password}`
- `_get_forge_config()` → `{Host, Port, Password}`
- `_get_servertap_config()` → `{Host, Port, ApiKey}`

Live-read means config toggles take effect immediately (no restart), matching Khito's streaming workflow.

### 2. Send function
Each connector has a synchronous send function:
- `__send_rcon_command(cmd)` — connects via MCRcon, sends `cmd`, returns response.
- `__send_forge_command(cmd)` — POSTs to `http://<host>:<port>/command` with `{password, command}`.
- `__send_servertap_command(cmd)` — POSTs to `http://<host>:<port>/api/execute` with `{apiKey, command}`.

### 3. Dispatcher
```python
def __send_sync_command(command):
    ctype = _get_connector_type()  # "rcon", "forge", or "servertap"
    if ctype == "servertap":
        return __send_servertap_command(command)
    elif ctype == "forge":
        return __send_forge_command(command)
    else:
        return __send_rcon_command(command)
```

The connector type is validated in `_get_connector_type()` against `("rcon", "forge", "servertap")`.

### 4. Connector type validation
In `_get_connector_type()`:
```python
v = c.get("Settings", {}).get("ConnectorType", "rcon")
return v if v in ("rcon", "forge", "servertap") else "rcon"
```

## Dashboard UI

### Settings tab — Connector selection
- Segmented radio buttons: RCON | Forge | ServerTap
- Each option shows its corresponding config card (host/port/password or apikey)
- CSS toggles card visibility via `display: none/block`

### Test Connection — use live form values, not saved config

**BIG LESSON (2026-06-24):** The original test endpoint only read `config.yml`. When the user selected "Forge" without saving, the endpoint still tested RCON (the previously saved type) and always reported port 25575 errors.

**Fix:** The `/api/test-connection` endpoint accepts a JSON body with the current UI state:

```python
payload = request.get_json(silent=True) or {}
ctype = payload.get("connector_type") or cfg.get("Settings", {}).get("ConnectorType", "rcon")
# Per-connector config: payload field wins, saved config is fallback
st = payload.get("servertap") or cfg.get("ServerTap", {})
```

On the JS side, the `testConnection()` function reads the radio selection + all 3 connectors' form field values and sends them in one payload. The backend only uses the matching connector's values.

## Adding a New Connector

The 4 files to touch (every time):
1. **`minecraft_main.py`** — config reader + send function + dispatcher
2. **`config.example.yml`** — config section with defaults
3. **`templates/index.html`** — radio button + config card
4. **`static/script.js`** — load/save/toggle for the new fields

If adding test-connection support, also update:
- **`app.py`** — extend `/api/test-connection` endpoint dispatch
- **`static/script.js`** — include new connector's fields in the test-connection payload

## API Test Patterns

When verifying a connector change, smoke-test these Flask routes:
```
/  → 200 HTML
/health → 200 JSON
/api/config → 200 JSON
/api/test-connection (POST with payload) → 200 JSON with "{connector} connected! (host:port)" or error
```

The test-connection POST test script shape:
```python
r = c.post('/api/test-connection', json={
    'connector_type': 'forge',
    'forge': {'Host': '127.0.0.1', 'Port': 5942, 'Password': ''}
})
data = r.get_json()
assert "5942" in data.get('message', '')
```
