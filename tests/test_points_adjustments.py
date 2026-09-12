"""Manual coin-adjustment contract for the long-term viewer points store.

Khito's use case: gifts sometimes never reach the DB (app crash, disconnect),
so an operator must be able to set/add/remove a viewer's coins by hand from the
Points tab without corrupting gift counts or period aggregates.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import points_store


class PointsAdjustmentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "points.db")
        points_store.init(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    # ------------------------------------------------------------------
    # add / remove / set
    # ------------------------------------------------------------------
    def test_add_increases_total_without_inflating_gift_count(self):
        points_store.record_gift("1", nickname="Alice", coins=100, gift_name="Rose")

        result = points_store.adjust_coins("1", "add", 250, note="crash recovery")

        self.assertEqual(result["applied_delta"], 250)
        self.assertEqual(result["total_coins"], 350)
        viewer = points_store.list_viewers()["viewers"][0]
        self.assertEqual(viewer["total_coins"], 350)
        self.assertEqual(viewer["gift_count"], 1, "manual coins must not count as a gift")

    def test_remove_decreases_total_and_floors_at_zero(self):
        points_store.record_gift("1", nickname="Alice", coins=100)

        result = points_store.adjust_coins("1", "remove", 400)

        self.assertEqual(result["total_coins"], 0)
        self.assertEqual(result["applied_delta"], -100, "clamped delta is reported honestly")
        self.assertEqual(points_store.list_viewers()["viewers"][0]["total_coins"], 0)

    def test_set_writes_the_exact_total_as_a_delta(self):
        points_store.record_gift("1", nickname="Alice", coins=100)

        result = points_store.adjust_coins("1", "set", 1000)

        self.assertEqual(result["applied_delta"], 900)
        self.assertEqual(result["total_coins"], 1000)

    def test_set_to_current_value_is_a_noop_with_no_ledger_row(self):
        points_store.record_gift("1", nickname="Alice", coins=100)

        result = points_store.adjust_coins("1", "set", 100)

        self.assertEqual(result["applied_delta"], 0)
        self.assertEqual(result["total_coins"], 100)
        history = points_store.viewer_detail("1")["history"]
        self.assertEqual(len(history), 1, "no zero-delta adjustment row")

    # ------------------------------------------------------------------
    # Period consistency
    # ------------------------------------------------------------------
    def test_adjustment_coins_land_in_period_totals_but_not_period_gift_counts(self):
        points_store.record_gift("1", nickname="Alice", coins=100, ts=500.0)

        points_store.adjust_coins("1", "add", 400, ts=600.0)

        data = points_store.list_viewers(since=400.0, until=700.0)
        self.assertEqual(data["total_coins"], 500)
        self.assertEqual(data["total_gifts"], 1)
        self.assertEqual(data["viewers"][0]["total_coins"], 500)
        self.assertEqual(data["viewers"][0]["gift_count"], 1)

    def test_adjustment_outside_period_is_excluded_from_period_totals(self):
        points_store.record_gift("1", nickname="Alice", coins=100, ts=500.0)
        points_store.adjust_coins("1", "add", 400, ts=9_000.0)

        data = points_store.list_viewers(since=400.0, until=700.0)

        self.assertEqual(data["total_coins"], 100)

    def test_negative_only_period_viewer_still_aggregates(self):
        points_store.record_gift("1", nickname="Alice", coins=100, ts=100.0)
        points_store.adjust_coins("1", "remove", 40, ts=500.0)

        data = points_store.list_viewers(since=400.0, until=700.0)

        self.assertEqual(data["total_coins"], -40)
        self.assertEqual(data["total_gifts"], 0)

    # ------------------------------------------------------------------
    # History / detail
    # ------------------------------------------------------------------
    def test_history_marks_manual_entries_and_keeps_the_note(self):
        points_store.record_gift("1", nickname="Alice", coins=100, gift_name="Rose")
        points_store.adjust_coins("1", "add", 250, note="missed gift during crash")

        history = points_store.viewer_detail("1")["history"]

        self.assertEqual(history[0]["kind"], "manual")
        self.assertEqual(history[0]["coins"], 250)
        self.assertEqual(history[0]["gift_name"], "missed gift during crash")
        self.assertEqual(history[1]["kind"], "gift")
        self.assertEqual(history[1]["gift_name"], "Rose")

    def test_manual_entry_without_note_uses_a_readable_default(self):
        points_store.record_gift("1", nickname="Alice", coins=100)
        points_store.adjust_coins("1", "remove", 10)

        self.assertEqual(points_store.viewer_detail("1")["history"][0]["gift_name"],
                         "Manual adjustment")

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def test_unknown_viewer_is_rejected(self):
        with self.assertRaises(LookupError):
            points_store.adjust_coins("nope", "add", 10)

    def test_invalid_operation_is_rejected(self):
        points_store.record_gift("1", nickname="Alice", coins=10)
        with self.assertRaises(ValueError):
            points_store.adjust_coins("1", "multiply", 10)

    def test_negative_and_non_numeric_amounts_are_rejected(self):
        points_store.record_gift("1", nickname="Alice", coins=10)
        for bad in (-5, "abc", None):
            with self.assertRaises(ValueError):
                points_store.adjust_coins("1", "add", bad)

    def test_blank_user_id_is_rejected(self):
        with self.assertRaises(ValueError):
            points_store.adjust_coins("", "add", 10)

    # ------------------------------------------------------------------
    # Schema migration
    # ------------------------------------------------------------------
    def test_legacy_ledger_without_kind_column_is_migrated_in_place(self):
        legacy = os.path.join(self.tmp.name, "legacy.db")
        conn = sqlite3.connect(legacy)
        conn.executescript(
            """
            CREATE TABLE viewers (
              user_id TEXT PRIMARY KEY, username TEXT NOT NULL DEFAULT '',
              nickname TEXT NOT NULL DEFAULT '', avatar_url TEXT NOT NULL DEFAULT '',
              total_coins INTEGER NOT NULL DEFAULT 0, gift_count INTEGER NOT NULL DEFAULT 0,
              first_seen REAL NOT NULL, last_gift_ts REAL NOT NULL);
            CREATE TABLE gift_ledger (
              id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
              ts REAL NOT NULL, coins INTEGER NOT NULL,
              gift_id TEXT NOT NULL DEFAULT '', gift_name TEXT NOT NULL DEFAULT '');
            INSERT INTO viewers VALUES ('7','old','Old','',80,2,1.0,2.0);
            INSERT INTO gift_ledger (user_id, ts, coins, gift_id, gift_name)
                 VALUES ('7', 2.0, 80, '1', 'Rose');
            """
        )
        conn.commit()
        conn.close()

        points_store.init(legacy)
        result = points_store.adjust_coins("7", "add", 20)

        self.assertEqual(result["total_coins"], 100)
        history = points_store.viewer_detail("7")["history"]
        self.assertEqual(history[0]["kind"], "manual")
        self.assertEqual(history[1]["kind"], "gift", "pre-existing rows default to gift")


if __name__ == "__main__":
    unittest.main()
