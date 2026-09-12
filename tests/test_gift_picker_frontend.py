"""Frontend contract for the room-scope gift picker.

The Add/Edit Gift picker used to serve the entire 2,789-gift union catalog,
which buried the ~700 gifts TikTok can actually deliver to Khito's room. This
locks the new behavior: the picker fetches ``?scope=room`` first (panel gifts +
everything ever received), keeps the full catalog as a search fallback, and
still feeds the icon/name maps from the full catalog so overlays and previews
never lose data.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "static", "script.js")
INDEX = os.path.join(ROOT, "templates", "index.html")


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def block_between(source, start_marker, end_marker):
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


class TestPickerFetchesRoomScope(unittest.TestCase):
    def setUp(self):
        self.js = read(SCRIPT)

    def test_picker_requests_current_panel_scope_first(self):
        fn = block_between(self.js, "async function fetchAvailableGifts()", "\nfunction ")
        self.assertIn("'/api/gifts/available?scope=panel'", fn)

    def test_picker_still_fetches_the_full_catalog(self):
        fn = block_between(self.js, "async function fetchAvailableGifts()", "\nfunction ")
        self.assertIn("fetch('/api/gifts/available')", fn)
        # Both requests go out together, not sequentially.
        self.assertIn("Promise.all", fn)

    def test_full_catalog_feeds_the_icon_and_name_maps(self):
        fn = block_between(self.js, "async function fetchAvailableGifts()", "\nfunction ")
        self.assertIn("giftNameMap[gid]", fn)
        self.assertIn("giftIconMap[gid]", fn)

    def test_icon_preload_does_not_poison_the_current_room_pool(self):
        fn = block_between(self.js, "async function loadGiftIconMap()", "\n// Rebuild the catalog")
        self.assertIn("cachedAllGifts = gifts", fn)
        self.assertNotIn("cachedAvailableGifts = gifts", fn)

    def test_room_gifts_are_the_default_chip_pool(self):
        fn = block_between(self.js, "async function fetchAvailableGifts()", "\nfunction ")
        self.assertIn("cachedAvailableGifts = roomGifts", fn)
        self.assertIn("cachedAllGifts = allGifts", fn)

    def test_search_never_silently_falls_back_to_full_catalog(self):
        fn = block_between(self.js, "function showGiftPickerChips", "\nfunction renderGiftChips")
        self.assertIn("cachedAllGifts", fn)
        self.assertIn("scopeSelect?.value === 'all'", fn)
        self.assertNotIn("inRoom.length === 0", fn)

    def test_cache_buster_was_bumped(self):
        match = re.search(r"/static/script\.js\?v=(\d+)", read(INDEX))
        self.assertIsNotNone(match)
        self.assertGreaterEqual(int(match.group(1)), 43)


class TestPickerLabelsTheScope(unittest.TestCase):
    def test_search_placeholder_tells_the_operator_what_the_pool_is(self):
        html = read(INDEX)
        self.assertIn('id="gift-search-input"', html)
        self.assertIn('id="gift-picker-scope"', html)
        self.assertIn("Current room only", html)


if __name__ == "__main__":
    unittest.main()
