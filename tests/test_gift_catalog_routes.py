"""Contract for the gift-catalog Flask routes.

``/api/gifts/available`` must serve the union cache, and ``/api/gifts/refresh``
must be a UNION rebuild. The bug being locked down: the old code overwrote
``available_gifts.json`` from TikTok's room panel, deleting every gift that only
exists in Khito's own room (``Super GG`` 12988, ``KhitoFam`` 938882).
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flask

import gift_catalog
import gift_catalog_sync


def build_app(gifts_file):
    """Minimal Flask app carrying just the two catalog routes.

    Importing the real ``app.py`` boots Spotify, add-ons and the Survival Rush
    service; this mirrors the route bodies against the same modules instead.
    """
    app = flask.Flask(__name__)
    app.config["GIFTS_FILE"] = gifts_file

    @app.route("/api/gifts/available", methods=["GET"])
    def available():
        cached = gift_catalog.load_catalog(app.config["GIFTS_FILE"])
        if not cached:
            return flask.jsonify([])
        if flask.request.args.get("scope") == "panel":
            cached = [e for e in cached if e.get("in_panel")]
        elif flask.request.args.get("scope") == "room":
            cached = [
                e for e in cached
                if e.get("in_panel") or e.get("seen")
            ]
        return flask.jsonify(cached)

    @app.route("/api/gifts/refresh", methods=["POST"])
    def refresh():
        path = app.config["GIFTS_FILE"]
        before = len(gift_catalog.load_catalog(path))
        result = {"before": before, "panel": {}, "regions": {}, "errors": []}
        panel = app.config.get("FAKE_PANEL") or []
        if panel:
            result["panel"] = gift_catalog.merge_into_catalog(path, panel, source="panel")
        result["regions"] = gift_catalog_sync.sync_regions(
            path, api_key=app.config.get("FAKE_KEY", ""),
            regions=app.config.get("FAKE_REGIONS"), client=app.config.get("FAKE_CLIENT"),
        )
        if result["regions"].get("error"):
            result["errors"].append(result["regions"]["error"])
        result["after"] = len(gift_catalog.load_catalog(path))
        result["added"] = result["after"] - before
        result["status"] = "ok" if result["after"] else "error"
        return flask.jsonify(result), (200 if result["after"] else 500)

    return app


class TestGiftRoutes(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "available_gifts.json")
        self.app = build_app(self.path)
        self.client = self.app.test_client()

    def test_available_serves_the_cache_as_a_list(self):
        gift_catalog.learn_gift(self.path, gift_id=12988, name="Super GG",
                                diamond_count=100, icon_url="https://cdn/s.webp")

        resp = self.client.get("/api/gifts/available")
        body = json.loads(resp.data)

        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(body, list)
        self.assertEqual(body[0]["id"], 12988)
        self.assertEqual(body[0]["diamond_count"], 100)

    def test_available_on_empty_cache_is_an_empty_list_not_an_error(self):
        resp = self.client.get("/api/gifts/available")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.data), [])

    def test_refresh_merges_the_panel_without_dropping_exclusive_gifts(self):
        gift_catalog.learn_gift(self.path, gift_id=12988, name="Super GG",
                                diamond_count=100, icon_url="https://cdn/s.webp")
        self.app.config["FAKE_PANEL"] = [
            {"id": 6064, "name": "GG", "diamond_count": 1,
             "icon": {"url_list": ["https://p16-webcast.tiktokcdn.com/img/gg.webp"]}},
        ]

        resp = self.client.post("/api/gifts/refresh")
        body = json.loads(resp.data)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["before"], 1)
        self.assertEqual(body["after"], 2)
        self.assertEqual(body["added"], 1)

        ids = {e["id"] for e in gift_catalog.load_catalog(self.path)}
        self.assertEqual(ids, {6064, 12988})

    def test_refresh_reports_a_missing_api_key_without_failing_the_panel_merge(self):
        self.app.config["FAKE_PANEL"] = [{"id": 6064, "name": "GG", "diamond_count": 1}]
        self.app.config["FAKE_KEY"] = ""

        resp = self.client.post("/api/gifts/refresh")
        body = json.loads(resp.data)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["errors"])
        self.assertEqual(len(gift_catalog.load_catalog(self.path)), 1)

    def test_refresh_with_no_source_available_reports_error_status(self):
        resp = self.client.post("/api/gifts/refresh")
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(json.loads(resp.data)["status"], "error")

    def test_refresh_is_safe_to_call_repeatedly(self):
        self.app.config["FAKE_PANEL"] = [{"id": 6064, "name": "GG", "diamond_count": 1}]

        self.client.post("/api/gifts/refresh")
        body = json.loads(self.client.post("/api/gifts/refresh").data)

        self.assertEqual(body["added"], 0)
        self.assertEqual(len(gift_catalog.load_catalog(self.path)), 1)


class TestRoomScopeEndpoint(unittest.TestCase):
    """The picker fetches ?scope=room; overlay/lookups keep the full catalog."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "available_gifts.json")
        gift_catalog.save_catalog(self.path, [
            {"id": 1, "name": "rose", "diamond_count": 1, "icon": "u1",
             "primary_effect_id": "", "resource_id": "", "has_animation": False,
             "source": "panel", "in_panel": True, "seen": False},
            {"id": 2, "name": "super gg", "diamond_count": 100, "icon": "u2",
             "primary_effect_id": "", "resource_id": "", "has_animation": False,
             "source": "event", "in_panel": False, "seen": True},
            {"id": 3, "name": "region-only", "diamond_count": 10, "icon": "u3",
             "primary_effect_id": "", "resource_id": "", "has_animation": False,
             "source": "region", "in_panel": False, "seen": False},
        ])
        self.client = build_app(self.path).test_client()

    def _ids(self, query=""):
        body = json.loads(self.client.get(f"/api/gifts/available{query}").data)
        return {e["id"] for e in body}

    def test_room_scope_returns_panel_plus_seen(self):
        self.assertEqual(self._ids("?scope=room"), {1, 2})

    def test_panel_scope_returns_only_current_room_panel(self):
        self.assertEqual(self._ids("?scope=panel"), {1})

    def test_default_scope_still_returns_everything(self):
        self.assertEqual(self._ids(), {1, 2, 3})

    def test_unknown_scope_value_falls_back_to_the_full_catalog(self):
        self.assertEqual(self._ids("?scope=nonsense"), {1, 2, 3})


class TestLegacyCacheMigration(unittest.TestCase):
    """Khito's live cache has 701 entries in the old id/name/coins/icon shape."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "available_gifts.json")

    def test_legacy_cache_is_served_and_upgraded_in_place(self):
        legacy = [
            {"id": 6064, "name": "gg", "diamond_count": 1, "icon": "https://cdn/gg.webp"},
            {"id": 5655, "name": "rose", "diamond_count": 1, "icon": "https://cdn/rose.webp"},
        ]
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(legacy, fh)

        app = build_app(self.path)
        app.config["FAKE_PANEL"] = [
            {"id": 6581, "name": "Game Controller", "diamond_count": 100,
             "icon": {"url_list": ["https://p16-webcast.tiktokcdn.com/img/gc.webp"]}},
        ]
        body = json.loads(app.test_client().post("/api/gifts/refresh").data)

        self.assertEqual(body["before"], 2)
        self.assertEqual(body["after"], 3)

        entries = {e["id"]: e for e in gift_catalog.load_catalog(self.path)}
        self.assertEqual(entries[6064]["icon"], "https://cdn/gg.webp")
        self.assertEqual(entries[6581]["diamond_count"], 100)
        self.assertIn("source", entries[6581])


if __name__ == "__main__":
    unittest.main()
