"""Contract for room-scope gift visibility flags in the union catalog.

Khito's picker problem (2026-09-02): the Add/Edit Gift picker now serves all
2,789 catalog gifts, but only two sets are actually usable:

* gifts in his **room panel** — what TikTok can deliver to the room right now
* gifts he has **actually received** — proven real even when absent from every
  panel (Super GG 12988: 25 sends, in no panel anywhere)

This locks down the data model: every catalog entry carries two booleans —

``in_panel``   seen in a live room-panel fetch this stream cycle
``seen``       ever received as a real GiftEvent (event source or history)

and the merge never *clears* them: a gift absent from today's panel keeps its
flag until an explicit reset. Flags are additive metadata only — ``source``,
price, name and icon logic are untouched.
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import gift_catalog


class TestNormalizeCarriesFlags(unittest.TestCase):
    def test_panel_source_defaults_in_panel_true(self):
        entry = gift_catalog.normalize_entry(
            {"id": 1, "name": "rose", "diamond_count": 1}, source="panel")
        self.assertTrue(entry["in_panel"])
        self.assertFalse(entry["seen"])

    def test_event_source_sets_both_flags(self):
        entry = gift_catalog.normalize_entry(
            {"id": 12988, "name": "super gg", "diamond_count": 100}, source="event")
        self.assertTrue(entry["in_panel"])
        self.assertTrue(entry["seen"])

    def test_region_and_euler_sources_are_not_in_panel(self):
        for source in ("region", "euler"):
            entry = gift_catalog.normalize_entry(
                {"id": 2, "name": "x", "diamond_count": 1}, source=source)
            self.assertFalse(entry["in_panel"], source)
            self.assertFalse(entry["seen"], source)

    def test_existing_flags_round_trip_through_the_entry_dict(self):
        entry = gift_catalog.normalize_entry(
            {"id": 3, "name": "x", "diamond_count": 1, "in_panel": False, "seen": True},
            source="euler")
        self.assertFalse(entry["in_panel"])
        self.assertTrue(entry["seen"])


class TestMergeNeverClearsFlags(unittest.TestCase):
    def setUp(self):
        self.base = [{
            "id": 12988, "name": "super gg", "diamond_count": 100, "icon": "",
            "primary_effect_id": "", "resource_id": "", "has_animation": False,
            "source": "event", "in_panel": True, "seen": True,
        }]

    def test_region_merge_keeps_a_learned_gifts_flags(self):
        incoming = gift_catalog.normalize_entry(
            {"id": 12988, "name": "super gg", "diamond_count": 100}, source="region")
        entries, _ = gift_catalog.merge_entries(self.base, [incoming])
        merged = next(e for e in entries if e["id"] == 12988)
        self.assertTrue(merged["in_panel"])
        self.assertTrue(merged["seen"])

    def test_flags_never_flip_a_field_comparison(self):
        """Flag-only differences must not count as an update churn."""
        incoming = gift_catalog.normalize_entry(
            {"id": 12988, "name": "super gg", "diamond_count": 100}, source="euler")
        incoming["in_panel"] = False
        incoming["seen"] = False
        _, stats = gift_catalog.merge_entries(self.base, [incoming])
        self.assertEqual(stats["updated"], 0)


class TestRoomScopeFiltering(unittest.TestCase):
    def setUp(self):
        self.fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(self.fd)
        gift_catalog.save_catalog(self.path, [
            {"id": 1, "name": "rose", "diamond_count": 1, "icon": "u1",
             "primary_effect_id": "", "resource_id": "", "has_animation": False,
             "source": "panel", "in_panel": True, "seen": False},
            {"id": 2, "name": "finger heart", "diamond_count": 5, "icon": "u2",
             "primary_effect_id": "", "resource_id": "", "has_animation": False,
             "source": "region", "in_panel": False, "seen": True},
            {"id": 3, "name": "retired thing", "diamond_count": 99, "icon": "",
             "primary_effect_id": "", "resource_id": "", "has_animation": False,
             "source": "euler", "in_panel": False, "seen": False},
        ])

    def tearDown(self):
        os.unlink(self.path)

    def room_scope(self):
        entries = gift_catalog.load_catalog(self.path)
        return [e for e in entries if e.get("in_panel") or e.get("seen")]

    def test_room_scope_is_panel_plus_seen(self):
        ids = {e["id"] for e in self.room_scope()}
        self.assertEqual(ids, {1, 2})

    def test_room_scope_of_real_catalog_is_useful_sized(self):
        """Sanity: the filter actually excludes the 2000+ extras."""
        self.assertGreater(len(gift_catalog.load_catalog(self.path)), 2)
        self.assertLessEqual(len(self.room_scope()), 2)


if __name__ == "__main__":
    unittest.main()
