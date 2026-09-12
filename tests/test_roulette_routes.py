"""Roulette API route tests — stats endpoint, config endpoints, test spin.

Covers:
- GET /api/stats/roulette: idle default, full payload while spinning/landed,
  expired -> idle, cancelled -> idle, no-cache headers;
- GET/PUT /api/roulette/config: normalization, selective replace (other config
  sections survive), enable validation;
- POST /api/roulette/test: bot-running 409, disabled 400, accepted 202.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as app_module
import gift_roulette


def _base_config():
    return {
        "Settings": {"MinecraftUsername": "KhitoMC", "TikTokUsername": "khito"},
        "Gifts": {
            "GlobalActions": [{"type": "minecraft", "command": "chatgift {user}"}],
            "5269": [{"type": "minecraft", "command": "winner-a {user}"}],
            "5333": [{"type": "minecraft", "command": "winner-b {user}"}],
            "5655": [{"type": "minecraft", "command": "trigger {user}"}],
        },
        "Roulette": {
            "enabled": False, "trigger_gift_id": "5655",
            "spin_ms": 5000, "hold_ms": 4000, "cooldown_ms": 2000,
            "pool": ["5269", "5333"],
        },
    }


class _Env:
    """Isolated app environment: temp data dir, stubbed config/catalog."""

    def __init__(self, monkeypatched):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.client = app_module.app.test_client()
        monkeypatched("app_module", "BASE_DIR", str(self.data_dir))

    def close(self):
        self.tmp.cleanup()

    def write_state(self, state):
        (self.data_dir / "roulette_state.json").write_text(
            json.dumps(state), encoding="utf-8")

    def write_config(self, cfg):
        self._config = cfg

    _config = None


def _spin_state(status="spinning", *, now=None):
    now = now or time.time()
    return {
        "schema": 1, "spin_id": "abc123", "source": "live", "profile": "default",
        "status": status,
        "started_at": now, "lands_at": now + 5.0, "hide_at": now + 9.0,
        "trigger": {"gift_id": "5655", "gift_name": "Rose", "user": "Viewer"},
        "entries": [
            {"gift_id": "5269", "label": "A", "icon_url": "", "diamond_count": 1},
            {"gift_id": "5333", "label": "B", "icon_url": "", "diamond_count": 10},
        ],
        "reel": [0, 1, 0, 1], "winner_index": 1, "dispatch_status": "pending",
    }


class RouletteStatsRouteTest(unittest.TestCase):
    def setUp(self):
        import unittest.mock as mock
        self.env = _Env(lambda mod, name, val: mock.patch.object(
            app_module, name, val, create=True).__enter__().__setattr__("_p", None)
        ) if False else None
        # Simpler: patch module attributes directly per-test with mock.patch
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def _patch_base_dir(self, mock):
        return mock.patch.object(app_module, "BASE_DIR", str(self.data_dir)) if hasattr(
            app_module, "BASE_DIR") else None

    def _get(self):
        return self.client.get("/api/stats/roulette")

    def test_idle_when_no_state_file(self):
        with unittest.mock.patch.object(
            app_module.stats_bp, "", create=True
        ) if False else unittest.mock.patch(
            "routes.stats.BASE_DIR", str(self.data_dir)
        ):
            resp = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"status": "idle"})
        self.assertIn("no-store", resp.headers["Cache-Control"])

    def test_spinning_state_returns_full_payload(self):
        self._write(_spin_state("spinning"))
        with unittest.mock.patch("routes.stats.BASE_DIR", str(self.data_dir)):
            resp = self._get()
        body = resp.get_json()
        self.assertEqual(body["status"], "spinning")
        self.assertEqual(body["winner_index"], 1)
        self.assertEqual(len(body["entries"]), 2)
        self.assertEqual(body["reel"], [0, 1, 0, 1])
        self.assertNotIn("winner_actions", body)

    def test_expired_state_reads_idle(self):
        now = time.time()
        stale = _spin_state("spinning", now=now)
        stale["lands_at"] = now - 10
        stale["hide_at"] = now - 5
        self._write(stale)
        with unittest.mock.patch("routes.stats.BASE_DIR", str(self.data_dir)):
            resp = self._get()
        self.assertEqual(resp.get_json(), {"status": "idle"})

    def test_cancelled_reads_idle(self):
        self._write(_spin_state("cancelled"))
        with unittest.mock.patch("routes.stats.BASE_DIR", str(self.data_dir)):
            resp = self._get()
        self.assertEqual(resp.get_json(), {"status": "idle"})

    def _write(self, state):
        (self.data_dir / "roulette_state.json").write_text(
            json.dumps(state), encoding="utf-8")


class RouletteConfigRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.client = app_module.app.test_client()
        self._patches = [
            unittest.mock.patch.object(app_module, "BASE_DIR", str(self.data_dir)),
            unittest.mock.patch.object(app_module, "load_config", _base_config),
            unittest.mock.patch.object(app_module, "save_config", self._capture_save),
            unittest.mock.patch.object(app_module, "is_any_bot_running", lambda: (False, None)),
        ]
        for p in self._patches:
            p.start()
        self.saved = None

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def _capture_save(self, cfg):
        self.saved = cfg

    def test_get_returns_normalized_with_warnings(self):
        resp = self.client.get("/api/roulette/config")
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["roulette"]["pool"], ["5269", "5333"])
        self.assertEqual(len(body["resolved_entries"]), 2)
        # disabled -> no enable warnings
        self.assertEqual([w for w in body["warnings"] if "Enable requires" in w], [])

    def test_put_replaces_only_roulette_block(self):
        resp = self.client.put("/api/roulette/config", json={
            "enabled": True, "trigger_gift_id": 5655,
            "spin_ms": 6000, "hold_ms": 4000, "cooldown_ms": 2000,
            "pool": ["5269", "5333"],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(self.saved)
        self.assertEqual(self.saved["Roulette"]["trigger_gift_id"], "5655")
        self.assertEqual(self.saved["Roulette"]["spin_ms"], 6000)
        # untouched sections survive
        self.assertIn("Gifts", self.saved)
        self.assertIn("Settings", self.saved)
        self.assertEqual(self.saved["Settings"]["MinecraftUsername"], "KhitoMC")

    def test_put_enable_without_two_valid_entries_saves_disabled_with_warning(self):
        # NEVER discard the user's save: invalid-enable persists everything,
        # forces enabled=False, and returns an explanatory warning.
        resp = self.client.put("/api/roulette/config", json={
            "enabled": True, "trigger_gift_id": "5655", "pool": ["9999"],
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertTrue(body["warnings"])
        self.assertIsNotNone(self.saved)
        self.assertFalse(self.saved["Roulette"]["enabled"])
        self.assertEqual(self.saved["Roulette"]["pool"], ["9999"])  # pool kept

    def test_put_enable_without_trigger_succeeds(self):
        # Trigger is now a Roulette action on gifts/events — not a Roulette-tab gift.
        resp = self.client.put("/api/roulette/config", json={
            "enabled": True, "pool": ["5269", "5333"],
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["warnings"], [])
        self.assertIsNotNone(self.saved)
        self.assertTrue(self.saved["Roulette"]["enabled"])
        self.assertEqual(self.saved["Roulette"]["pool"], ["5269", "5333"])

    def test_get_warns_about_legacy_trigger_gift(self):
        resp = self.client.get("/api/roulette/config")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(any("Legacy trigger" in w for w in body["warnings"]))

    def test_put_valid_enable_succeeds_without_warnings(self):
        resp = self.client.put("/api/roulette/config", json={
            "enabled": True, "pool": ["5269", "5333"],
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["warnings"], [])
        self.assertTrue(self.saved["Roulette"]["enabled"])


class RouletteTestSpinRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.client = app_module.app.test_client()
        self._patches = [
            unittest.mock.patch.object(app_module, "BASE_DIR", str(self.data_dir)),
            unittest.mock.patch.object(app_module, "_ROULETTE_STATE_PATH",
                                       str(self.data_dir / "roulette_state.json")),
            unittest.mock.patch.object(app_module, "load_config", _base_config),
            unittest.mock.patch.object(app_module, "save_config", lambda cfg: None),
            unittest.mock.patch.object(app_module, "is_any_bot_running", lambda: (False, None)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def test_bot_running_returns_409(self):
        with unittest.mock.patch.object(app_module, "is_any_bot_running", lambda: (True, None)):
            resp = self.client.post("/api/roulette/test", json={})
        self.assertEqual(resp.status_code, 409)

    def test_disabled_returns_400(self):
        resp = self.client.post("/api/roulette/test", json={})
        self.assertEqual(resp.status_code, 400)

    def test_valid_config_accepted_202_with_payload(self):
        cfg = _base_config()
        cfg["Roulette"]["enabled"] = True
        with unittest.mock.patch.object(app_module, "load_config", lambda: cfg):
            resp = self.client.post("/api/roulette/test", json={"user": "TestViewer"})
        self.assertEqual(resp.status_code, 202)
        body = resp.get_json()
        self.assertEqual(body["status"], "accepted")
        self.assertTrue(body["spin_id"])
        self.assertTrue(body["winner"])
        state_file = self.data_dir / "roulette_state.json"
        self.assertTrue(state_file.exists())
        state = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertEqual(state["source"], "test")
        self.assertEqual(state["status"], "spinning")
        self.assertNotIn("winner_actions", state)


if __name__ == "__main__":
    unittest.main()
