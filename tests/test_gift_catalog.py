"""Contract for the union-merged TikTok gift catalog.

Why this module exists (verified against Khito's live data, 2026-09-02):

TikTok's ``/gift/list/`` returns only the **room panel** for the connected
stream and self-reports ``is_full_gift_data: False`` — 701 gifts out of the
2783 that exist. Region-locked gifts (``Game Controller`` 6581/7569) and
creator/event-exclusive gifts (``Super GG`` 12988, ``KhitoFam`` 938882) are
absent, so the dashboard showed no icon and no coin value even though the gift
was received and credited correctly.

Three sources feed ONE catalog. None is complete alone:

* ``panel``  — room panel on connect. Authoritative for the room, has real icons.
* ``region`` — EulerStream regional gift blobs, unioned. 1767 gifts, real icons.
* ``event``  — every GiftEvent teaches the catalog its own gift. The ONLY source
  that can ever know a creator-exclusive gift.

The merge is a UNION that never drops a known gift. The previous code
overwrote the file wholesale on every connect, which is what made learned
entries disappear.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gift_catalog


def panel_gift(gift_id, name, coins, icon_url="", **extra):
    """A gift shaped like TikTok's /gift/list/ and the regional blobs."""
    entry = {
        "id": gift_id,
        "name": name,
        "diamond_count": coins,
        "type": 1,
    }
    if icon_url:
        entry["icon"] = {"url_list": [icon_url], "uri": "webcast-va/abc"}
        entry["image"] = {"url_list": [icon_url]}
    entry.update(extra)
    return entry


class TestNormalizeEntry(unittest.TestCase):
    def test_panel_shape_is_normalized(self):
        e = gift_catalog.normalize_entry(
            panel_gift(6581, "Game Controller", 100, "https://cdn/x.webp", primary_effect_id=7687),
            source="panel",
        )
        self.assertEqual(e["id"], 6581)
        self.assertEqual(e["name"], "game controller")
        self.assertEqual(e["diamond_count"], 100)
        self.assertEqual(e["icon"], "https://cdn/x.webp")
        self.assertEqual(e["primary_effect_id"], "7687")
        self.assertEqual(e["source"], "panel")

    def test_euler_catalog_shape_is_normalized(self):
        """EulerStream's catalog route uses camelCase and a flat imageUri."""
        e = gift_catalog.normalize_entry(
            {
                "giftId": 7569,
                "giftName": "Game Controller",
                "diamondCount": 100,
                "giftType": 2,
                "imageUri": "https://assets.cdn.eulerstream.com/gifts/images/abc?fpsig=v1",
            },
            source="euler",
        )
        self.assertEqual(e["id"], 7569)
        self.assertEqual(e["name"], "game controller")
        self.assertEqual(e["diamond_count"], 100)
        self.assertEqual(e["source"], "euler")

    def test_euler_origin_locked_image_host_is_not_used_as_icon(self):
        """assets.cdn.eulerstream.com returns 403 'Origin not allowed' — verified.

        Storing it would render a broken image in the dashboard, which is worse
        than an empty icon (the UI already hides empty icons via onerror).
        """
        e = gift_catalog.normalize_entry(
            {
                "giftId": 7569,
                "giftName": "Game Controller",
                "diamondCount": 100,
                "imageUri": "https://assets.cdn.eulerstream.com/gifts/images/abc?fpsig=v1",
            },
            source="euler",
        )
        self.assertEqual(e["icon"], "")

    def test_tiktok_cdn_image_uri_is_kept(self):
        e = gift_catalog.normalize_entry(
            {"giftId": 1, "giftName": "X", "diamondCount": 5,
             "imageUri": "https://p16-webcast.tiktokcdn.com/img/x~tplv-obj.webp"},
            source="euler",
        )
        self.assertEqual(e["icon"], "https://p16-webcast.tiktokcdn.com/img/x~tplv-obj.webp")

    def test_entry_without_id_is_rejected(self):
        self.assertIsNone(gift_catalog.normalize_entry({"name": "no id"}, source="panel"))
        self.assertIsNone(gift_catalog.normalize_entry({"id": 0, "name": "zero"}, source="panel"))

    def test_flat_string_icon_from_a_legacy_cache_is_preserved(self):
        """The persisted shape stores icon as a flat URL, not an ImageModel.

        Khito's live cache holds 701 such entries; a round-trip through
        normalize_entry must not blank them.
        """
        e = gift_catalog.normalize_entry(
            {"id": 6064, "name": "gg", "diamond_count": 1, "icon": "https://cdn/gg.webp"},
            source="panel",
        )
        self.assertEqual(e["icon"], "https://cdn/gg.webp")

    def test_has_animation_requires_coins_and_effect_id(self):
        cheap = gift_catalog.normalize_entry(
            panel_gift(1, "cheap", 1, primary_effect_id=999), source="panel")
        rich = gift_catalog.normalize_entry(
            panel_gift(2, "rich", 100, primary_effect_id=999), source="panel")
        self.assertFalse(cheap["has_animation"])
        self.assertTrue(rich["has_animation"])


class TestMerge(unittest.TestCase):
    def test_union_never_drops_a_known_gift(self):
        """The core regression: reconnecting must not delete learned gifts."""
        base = [gift_catalog.normalize_entry(
            panel_gift(12988, "Super GG", 100, "https://cdn/supergg.webp"), source="event")]
        incoming = [gift_catalog.normalize_entry(
            panel_gift(6064, "GG", 1, "https://cdn/gg.webp"), source="panel")]

        merged, stats = gift_catalog.merge_entries(base, incoming)
        ids = {e["id"] for e in merged}

        self.assertIn(12988, ids, "learned exclusive gift was dropped by a panel refresh")
        self.assertIn(6064, ids)
        self.assertEqual(stats["added"], 1)

    def test_incoming_icon_fills_a_gap(self):
        base = [gift_catalog.normalize_entry(panel_gift(5, "x", 10), source="event")]
        incoming = [gift_catalog.normalize_entry(
            panel_gift(5, "x", 10, "https://cdn/x.webp"), source="panel")]

        merged, stats = gift_catalog.merge_entries(base, incoming)

        self.assertEqual(merged[0]["icon"], "https://cdn/x.webp")
        self.assertEqual(stats["updated"], 1)

    def test_existing_icon_is_not_replaced_by_an_empty_one(self):
        base = [gift_catalog.normalize_entry(
            panel_gift(5, "x", 10, "https://cdn/good.webp"), source="event")]
        incoming = [gift_catalog.normalize_entry(panel_gift(5, "x", 10), source="euler")]

        merged, _ = gift_catalog.merge_entries(base, incoming)

        self.assertEqual(merged[0]["icon"], "https://cdn/good.webp")

    def test_panel_coin_value_corrects_a_stale_value(self):
        """Panel/event data is authoritative for price; euler snapshots lag."""
        base = [gift_catalog.normalize_entry(
            {"giftId": 6581, "giftName": "Game Controller", "diamondCount": 99}, source="euler")]
        incoming = [gift_catalog.normalize_entry(
            panel_gift(6581, "Game Controller", 100, "https://cdn/gc.webp"), source="panel")]

        merged, _ = gift_catalog.merge_entries(base, incoming)

        self.assertEqual(merged[0]["diamond_count"], 100)

    def test_euler_does_not_downgrade_a_panel_coin_value(self):
        base = [gift_catalog.normalize_entry(
            panel_gift(6581, "Game Controller", 100, "https://cdn/gc.webp"), source="panel")]
        incoming = [gift_catalog.normalize_entry(
            {"giftId": 6581, "giftName": "Game Controller", "diamondCount": 0}, source="euler")]

        merged, _ = gift_catalog.merge_entries(base, incoming)

        self.assertEqual(merged[0]["diamond_count"], 100)

    def test_merged_output_is_sorted_by_coins(self):
        base = []
        incoming = [
            gift_catalog.normalize_entry(panel_gift(1, "big", 5000), source="panel"),
            gift_catalog.normalize_entry(panel_gift(2, "small", 1), source="panel"),
            gift_catalog.normalize_entry(panel_gift(3, "mid", 100), source="panel"),
        ]
        merged, _ = gift_catalog.merge_entries(base, incoming)
        self.assertEqual([e["diamond_count"] for e in merged], [1, 100, 5000])

    def test_duplicate_ids_within_one_batch_collapse(self):
        incoming = [
            gift_catalog.normalize_entry(panel_gift(9, "dup", 10), source="panel"),
            gift_catalog.normalize_entry(panel_gift(9, "dup", 10, "https://cdn/d.webp"), source="panel"),
        ]
        merged, _ = gift_catalog.merge_entries([], incoming)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["icon"], "https://cdn/d.webp")


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "available_gifts.json")

    def test_catalog_persists_as_a_list_for_backwards_compat(self):
        """gift_card_studio/catalog.py, script.js and get_gift_icon all expect a list."""
        gift_catalog.save_catalog(self.path, [
            gift_catalog.normalize_entry(panel_gift(1, "a", 1), source="panel")])

        with open(self.path, encoding="utf-8") as fh:
            raw = json.load(fh)

        self.assertIsInstance(raw, list)
        self.assertEqual(raw[0]["id"], 1)
        self.assertEqual(raw[0]["name"], "a")

    def test_load_of_missing_file_is_empty_not_an_error(self):
        self.assertEqual(gift_catalog.load_catalog(self.path), [])

    def test_load_of_corrupt_file_is_empty_not_an_error(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertEqual(gift_catalog.load_catalog(self.path), [])

    def test_legacy_entries_survive_a_load_merge_save_round_trip(self):
        """A pre-existing cache written by the old code must not be lost."""
        legacy = [{"id": 6064, "name": "gg", "diamond_count": 1, "icon": "https://cdn/gg.webp"}]
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(legacy, fh)

        stats = gift_catalog.merge_into_catalog(
            self.path, [panel_gift(12988, "Super GG", 100, "https://cdn/s.webp")], source="event")

        ids = {e["id"] for e in gift_catalog.load_catalog(self.path)}
        self.assertEqual(ids, {6064, 12988})
        self.assertEqual(stats["added"], 1)

    def test_merge_into_catalog_is_idempotent(self):
        batch = [panel_gift(6581, "Game Controller", 100, "https://cdn/gc.webp")]
        gift_catalog.merge_into_catalog(self.path, batch, source="region")
        stats = gift_catalog.merge_into_catalog(self.path, batch, source="region")

        self.assertEqual(stats["added"], 0)
        self.assertEqual(stats["updated"], 0)
        self.assertEqual(len(gift_catalog.load_catalog(self.path)), 1)

    def test_save_is_atomic_and_leaves_no_temp_file(self):
        gift_catalog.save_catalog(self.path, [
            gift_catalog.normalize_entry(panel_gift(1, "a", 1), source="panel")])
        leftovers = [f for f in os.listdir(self.dir) if f != "available_gifts.json"]
        self.assertEqual(leftovers, [])


class TestLearnFromGiftEvent(unittest.TestCase):
    """Source C — the only path that can know a creator-exclusive gift."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "available_gifts.json")

    def test_unknown_gift_is_learned_with_its_icon(self):
        changed = gift_catalog.learn_gift(
            self.path, gift_id=12988, name="Super GG", diamond_count=100,
            icon_url="https://p16-webcast.tiktokcdn.com/img/supergg~tplv-obj.webp")

        self.assertTrue(changed)
        entries = gift_catalog.load_catalog(self.path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], 12988)
        self.assertEqual(entries[0]["name"], "super gg")
        self.assertEqual(entries[0]["diamond_count"], 100)
        self.assertTrue(entries[0]["icon"].endswith("~tplv-obj.webp"))
        self.assertEqual(entries[0]["source"], "event")

    def test_already_complete_gift_is_not_rewritten(self):
        gift_catalog.learn_gift(self.path, gift_id=12988, name="Super GG",
                                diamond_count=100, icon_url="https://cdn/s.webp")
        changed = gift_catalog.learn_gift(self.path, gift_id=12988, name="Super GG",
                                          diamond_count=100, icon_url="https://cdn/s.webp")
        self.assertFalse(changed, "a no-op learn must not rewrite the catalog on every gift")

    def test_learning_backfills_a_missing_icon_on_an_existing_entry(self):
        gift_catalog.merge_into_catalog(
            self.path, [{"giftId": 12988, "giftName": "Super GG", "diamondCount": 100}],
            source="euler")

        changed = gift_catalog.learn_gift(self.path, gift_id=12988, name="Super GG",
                                          diamond_count=100, icon_url="https://cdn/s.webp")

        self.assertTrue(changed)
        self.assertEqual(gift_catalog.load_catalog(self.path)[0]["icon"], "https://cdn/s.webp")

    def test_learning_without_an_icon_still_records_name_and_price(self):
        """Better a nameless-but-priced entry than nothing; icon can arrive later."""
        changed = gift_catalog.learn_gift(self.path, gift_id=938882, name="KhitoFam",
                                          diamond_count=1, icon_url="")
        self.assertTrue(changed)
        e = gift_catalog.load_catalog(self.path)[0]
        self.assertEqual(e["id"], 938882)
        self.assertEqual(e["diamond_count"], 1)
        self.assertEqual(e["icon"], "")

    def test_learn_never_raises_on_a_bad_path(self):
        """This runs inside the GiftEvent handler — it must never break a stream."""
        bad = os.path.join(self.dir, "no-such-dir", "nested", "gifts.json")
        try:
            gift_catalog.learn_gift(bad, gift_id=1, name="x", diamond_count=1, icon_url="")
        except Exception as exc:  # pragma: no cover
            self.fail(f"learn_gift raised into the gift handler: {exc!r}")

    def test_learn_ignores_a_junk_gift_id(self):
        self.assertFalse(gift_catalog.learn_gift(self.path, gift_id=0, name="x",
                                                 diamond_count=1, icon_url=""))
        self.assertFalse(gift_catalog.learn_gift(self.path, gift_id=None, name="x",
                                                 diamond_count=1, icon_url=""))


class TestIconLookup(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "available_gifts.json")

    def test_icon_lookup_by_id(self):
        gift_catalog.save_catalog(self.path, [
            gift_catalog.normalize_entry(panel_gift(6581, "Game Controller", 100,
                                                   "https://cdn/gc.webp"), source="panel")])
        self.assertEqual(gift_catalog.icon_for(self.path, 6581), "https://cdn/gc.webp")
        self.assertEqual(gift_catalog.icon_for(self.path, "6581"), "https://cdn/gc.webp")
        self.assertEqual(gift_catalog.icon_for(self.path, 999999), "")

    def test_icon_lookup_picks_up_a_file_change_without_restart(self):
        """Settings and caches must both stay live — no restart to see a new gift."""
        gift_catalog.save_catalog(self.path, [
            gift_catalog.normalize_entry(panel_gift(1, "a", 1, "https://cdn/a.webp"), source="panel")])
        self.assertEqual(gift_catalog.icon_for(self.path, 1), "https://cdn/a.webp")

        gift_catalog.learn_gift(self.path, gift_id=12988, name="Super GG",
                                diamond_count=100, icon_url="https://cdn/s.webp")

        self.assertEqual(gift_catalog.icon_for(self.path, 12988), "https://cdn/s.webp",
                         "icon cache went stale after the catalog grew")


if __name__ == "__main__":
    unittest.main()
