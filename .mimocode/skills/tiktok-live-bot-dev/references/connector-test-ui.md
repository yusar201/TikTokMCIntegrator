# Connector settings + Test Connection UI pattern

Use this when adding or debugging Minecraft connector options in TikTokMCIntegrator settings.

## Known connector types
- `rcon`: legacy Minecraft server RCON, default port `25575`.
- `forge`: local Forge mod HTTP endpoint, default port `5942`, endpoint `/command`.
- `servertap`: ServerTap plugin on Paper/Spigot, default port `4567`, command endpoint currently wired as `/api/execute`.

## UI rule
The **Test Connection** button belongs **inside each connector's config card**, not as a loose element between cards. A loose button can inherit layout/card sizing weirdness and appear as a giant blank white panel.

Good HTML pattern:

```html
<div class="form-card" id="forge-settings-card" style="display:none;">
  ... fields ...
  <button type="button" class="btn btn-primary btn-sm connector-test-btn" onclick="testConnection()">
    <i class="fa-solid fa-plug-circle-check"></i> Test Connection
  </button>
</div>
```

Add the same themed button to each connector card (`rcon`, `forge`, `servertap`) so only the visible card shows its own test action.

## Test endpoint rule
Do **not** test only the saved `config.yml` connector. The user may select a different connector or edit host/port fields without saving yet. The UI must POST the selected connector and current form values.

Bad pattern:

```js
fetch('/api/test-connection', { method: 'POST' })
```

Good pattern:

```js
const payload = {
  connector_type: selectedType,
  rcon: { Host, Port, Password },
  forge: { Host, Port, Password },
  servertap: { Host, Port, ApiKey }
};
fetch('/api/test-connection', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload)
});
```

Backend should prefer posted values and only fall back to config.yml:

```python
payload = request.get_json(silent=True) or {}
ctype = payload.get("connector_type") or cfg.get("Settings", {}).get("ConnectorType", "rcon")

if ctype == "forge":
    fg = payload.get("forge") or cfg.get("Forge", {})
elif ctype == "servertap":
    st = payload.get("servertap") or cfg.get("ServerTap", {})
else:
    rc = payload.get("rcon") or cfg.get("Rcon", {})
```

## Verification
Use Flask test client to prove the selected connector controls the tested port:

```bash
python3 - <<'PY'
import app
c = app.app.test_client()
for payload in [
    {'connector_type':'forge','forge':{'Host':'127.0.0.1','Port':5942,'Password':''}},
    {'connector_type':'servertap','servertap':{'Host':'127.0.0.1','Port':4567,'ApiKey':''}},
    {'connector_type':'rcon','rcon':{'Host':'127.0.0.1','Port':25575,'Password':''}},
]:
    r = c.post('/api/test-connection', json=payload)
    data = r.get_json()
    print(payload['connector_type'], r.status_code, data.get('message'))
PY
```

Expected error messages on a machine with no Minecraft server running should mention the respective ports: Forge `5942`, ServerTap `4567`, RCON `25575`.
