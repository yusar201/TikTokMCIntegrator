"""Tests for top gifter/liker amount-visibility toggles and avatar parity.

Covers the corrected design (2026-08-15):

- /api/stats/topgifter folds `show_gift_amounts` / `show_like_amounts` into
  its payload so the overlay applies them on its existing poll.
- /api/stats/overlay/settings GET/POST persists the two flags (both default
  OFF/hidden).
- The overlay templates no longer embed their own toggle UI (no
  `toggle-show-coins` / `toggle-show-likes` inputs); the leaderboard markup
  still has `lb-list` and the two tab ids.
"""
import os
import sys
import json
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask
from routes.stats import stats_bp, init_stats_blueprint
from routes.overlay_settings import init_overlay_settings_blueprint as init_overlay_bp


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


class TestOverlaySettingsEndpoint(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(stats_bp, url_prefix="/api/stats")
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = self.tmp.name
        os.makedirs(self.data_dir, exist_ok=True)
        init_stats_blueprint(self.data_dir)
        init_overlay_bp(self.data_dir)
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_both_hidden(self):
        res = self.client.get("/api/stats/overlay/settings")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertFalse(data["show_gift_amounts"])
        self.assertFalse(data["show_like_amounts"])

    def test_update_gift_persists(self):
        res = self.client.post(
            "/api/stats/overlay/settings",
            json={"show_gift_amounts": True},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["show_gift_amounts"])
        # Persisted: a fresh GET reflects it.
        self.assertTrue(self.client.get("/api/stats/overlay/settings").get_json()["show_gift_amounts"])

    def test_update_like_persists(self):
        res = self.client.post(
            "/api/stats/overlay/settings",
            json={"show_like_amounts": True},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["show_like_amounts"])

    def test_partial_update_preserves_other(self):
        self.client.post("/api/stats/overlay/settings", json={"show_gift_amounts": True},
                         content_type="application/json")
        res = self.client.post("/api/stats/overlay/settings", json={"show_like_amounts": True},
                               content_type="application/json")
        data = res.get_json()
        self.assertTrue(data["show_gift_amounts"])
        self.assertTrue(data["show_like_amounts"])


class TestTopGifterPayload(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(stats_bp, url_prefix="/api/stats")
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = self.tmp.name
        os.makedirs(self.data_dir, exist_ok=True)
        init_stats_blueprint(self.data_dir)
        init_overlay_bp(self.data_dir)
        self.client = self.app.test_client()
        self.gifter_file = os.path.join(self.data_dir, "gifter_ranking.json")
        self.liker_file = os.path.join(self.data_dir, "liker_ranking.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _seed(self):
        write_json(self.gifter_file, [
            {"nick": "Alice", "unique_id": "alice123", "avatar_url": "", "total_coins": 1000},
        ])
        write_json(self.liker_file, [
            {"nick": "Bob", "unique_id": "bob456", "avatar_url": "", "total_likes": 2000},
        ])

    def test_payload_includes_visibility_flags_default_false(self):
        self._seed()
        data = self.client.get("/api/stats/topgifter").get_json()
        self.assertIn("gifters", data)
        self.assertIn("likers", data)
        self.assertFalse(data["show_gift_amounts"])
        self.assertFalse(data["show_like_amounts"])

    def test_flags_follow_settings(self):
        self._seed()
        self.client.post("/api/stats/overlay/settings", json={"show_gift_amounts": True},
                         content_type="application/json")
        data = self.client.get("/api/stats/topgifter").get_json()
        self.assertTrue(data["show_gift_amounts"])
        self.assertFalse(data["show_like_amounts"])

    def test_empty_boards_still_carry_flags(self):
        write_json(self.gifter_file, [])
        write_json(self.liker_file, [])
        data = self.client.get("/api/stats/topgifter").get_json()
        self.assertEqual(data["gifters"], [])
        self.assertEqual(data["likers"], [])
        self.assertIn("show_gift_amounts", data)
        self.assertIn("show_like_amounts", data)


class TestOverlayTemplates(unittest.TestCase):
    """Render-level checks against the two Jinja templates."""

    def _render(self, name, overlay_type):
        from jinja2 import Environment, FileSystemLoader
        env = Environment(loader=FileSystemLoader(os.path.join(REPO, "templates")))
        return env.get_template(name).render(overlay_type=overlay_type)

    def test_overlay_topgifter_renders_and_has_no_toggle_ui(self):
        html = self._render("overlay.html", "topgifter")
        self.assertIn('id="lb-list"', html)
        self.assertIn('id="lb-tab-gifters"', html)
        self.assertIn('id="lb-tab-likers"', html)
        # The toggle UI must live in the dashboard, NOT in the OBS overlay.
        self.assertNotIn("toggle-show-coins", html)
        self.assertNotIn("toggle-show-likes", html)
        # Score hiding is driven by the poll payload flags.
        self.assertIn("lbShowAmounts", html)

    def test_overlay_demo_topgifter_renders_and_has_no_toggle_ui(self):
        html = self._render("overlay_demo.html", "topgifter")
        self.assertIn('id="lb-list"', html)
        self.assertNotIn("toggle-show-coins", html)
        self.assertNotIn("toggle-show-likes", html)
        self.assertIn("lbShowAmounts", html)


class TestAvatarParity(unittest.TestCase):
    """Both boards flow through the SAME enrichment path in stats.py."""

    def test_both_boards_call_same_enrich(self):
        import inspect
        import routes.stats as stats
        src = inspect.getsource(stats.get_top_gifters)
        # The endpoint must enrich both gifters and likers uniformly.
        self.assertIn("_enrich_rank_avatars(gifters)", src)
        self.assertIn("_enrich_rank_avatars(likers)", src)


if __name__ == "__main__":
    unittest.main()
