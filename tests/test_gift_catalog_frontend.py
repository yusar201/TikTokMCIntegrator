"""Frontend contract for the Sync Gift Catalog control.

TikTok's room panel is only ~700 of 2783 gifts, so the dashboard needs an
explicit way to pull the rest. This locks the wiring down: the button exists in
the Gifts panel, calls ``POST /api/gifts/refresh``, and reloads the icon map
afterwards so newly-synced gifts appear without a page refresh.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "templates", "index.html")
SCRIPT = os.path.join(ROOT, "static", "script.js")


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class TestSyncButtonMarkup(unittest.TestCase):
    def setUp(self):
        self.html = read(INDEX)

    def test_sync_button_exists(self):
        self.assertIn('id="btn-refresh-gift-catalog"', self.html)

    def test_sync_button_lives_in_the_gifts_panel(self):
        panel_start = self.html.index('id="panel-gifts"')
        panel_end = self.html.index('id="panel-gift-studio"')
        panel = self.html[panel_start:panel_end]
        self.assertIn("btn-refresh-gift-catalog", panel)

    def test_sync_button_explains_itself_on_hover(self):
        match = re.search(
            r'id="btn-refresh-gift-catalog"[^>]*title="([^"]+)"', self.html)
        self.assertIsNotNone(match, "sync button needs a title tooltip")
        self.assertIn("region", match.group(1).lower())


class TestSyncWiring(unittest.TestCase):
    def setUp(self):
        self.js = read(SCRIPT)

    def test_handler_is_defined(self):
        self.assertIn("async function refreshGiftCatalog()", self.js)

    def test_handler_is_bound_to_the_button(self):
        self.assertRegex(
            self.js,
            r"getElementById\('btn-refresh-gift-catalog'\)[\s\S]{0,160}"
            r"addEventListener\('click', refreshGiftCatalog\)",
        )

    def test_handler_posts_to_the_refresh_endpoint(self):
        block = self.js[self.js.index("async function refreshGiftCatalog()"):]
        block = block[:block.index("\n}\n")]
        self.assertIn("'/api/gifts/refresh'", block)
        self.assertIn("method: 'POST'", block)

    def test_handler_reloads_the_icon_map_so_new_gifts_show_immediately(self):
        block = self.js[self.js.index("async function refreshGiftCatalog()"):]
        block = block[:block.index("\n}\n")]
        self.assertIn("cachedAvailableGifts = []", block)
        self.assertIn("loadGiftIconMap()", block)

    def test_handler_reenables_the_button_even_on_failure(self):
        block = self.js[self.js.index("async function refreshGiftCatalog()"):]
        block = block[:block.index("\n}\n")]
        self.assertIn("finally", block)
        self.assertIn("btn.disabled = false", block)

    def test_handler_reports_outcome_to_the_operator(self):
        block = self.js[self.js.index("async function refreshGiftCatalog()"):]
        block = block[:block.index("\n}\n")]
        self.assertIn("showToast", block)


class TestCacheBusting(unittest.TestCase):
    def test_script_cache_buster_was_bumped_past_v41(self):
        """v41 shipped the points modal; the sync button needs a new version."""
        match = re.search(r"/static/script\.js\?v=(\d+)", read(INDEX))
        self.assertIsNotNone(match)
        self.assertGreaterEqual(int(match.group(1)), 42)


if __name__ == "__main__":
    unittest.main()
