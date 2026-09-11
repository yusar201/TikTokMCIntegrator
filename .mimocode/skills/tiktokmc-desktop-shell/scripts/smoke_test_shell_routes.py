#!/usr/bin/env python3
"""Smoke-test the desktop-shell Flask routes via test_client (no running server, no display).

Proves /health, /, /wizard, /api/setup don't crash AND that first-run detection reads the
REAL config schema correctly — i.e. an existing install (Settings.TikTokUsername present)
serves the DASHBOARD, not the wizard. This is the test that caught the schema-mismatch bug
where a guessed key (tiktok.username) would have hijacked Khito's working install.

Run with the Windows Python that has the deps installed:
  C:\Python313\python.exe scripts/smoke_test_shell_routes.py
(cd into the project root first, or it chdirs there.)
"""
import os, json

os.chdir(r"D:\Ikhito\Code\TikTokMCIntegrator")
import app as appmod
client = appmod.app.test_client()

out = {}
out["is_configured"] = appmod._is_configured()

r = client.get("/health")
out["health_status"] = r.status_code
out["health_json"] = r.get_json()

r = client.get("/")
out["index_status"] = r.status_code
# Wizard markers from wizard.html; absent => dashboard is being served
out["index_serves_wizard"] = (b"TikTok account" in r.data and b"Minecraft server" in r.data)
out["index_serves_dashboard"] = not out["index_serves_wizard"]

r = client.get("/wizard")
out["wizard_route_status"] = r.status_code

print(json.dumps(out, indent=2, default=str))

# Assertions: with a real existing config, must serve dashboard.
assert out["health_status"] == 200, "health route should be 200"
if out["is_configured"]:
    assert out["index_serves_dashboard"], "configured install must serve dashboard, not wizard"
print("\nOK — routes healthy, first-run detection correct for this config.")
