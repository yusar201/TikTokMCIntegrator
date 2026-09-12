"""Contract for backfilling the gift catalog from local history.

``Super GG`` (12988) exists in **no** catalog: not TikTok's room panel, not any
of EulerStream's 20 regional panels, not Euler's 2783-row catalog (404).
Verified 2026-09-02. The only proof it exists is Khito's own history — 25 sends
worth 2500 coins in ``points.db``, and ``gift_log.json`` entries that carry the
icon TikTok shipped with the event.

So history is a real catalog source. It is the LOWEST-trust source: anything the
live panel, a region sync, or a future GiftEvent says overrides it.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gift_catalog
import gift_catalog_backfill


def make_ledger(path, rows):
    """rows: (gift_id, gift_name, coins) — mirrors the real gift_ledger table."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE gift_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "user_id TEXT, ts REAL, coins INTEGER, gift_id TEXT, gift_name TEXT, kind TEXT)"
    )
    conn.executemany(
        "INSERT INTO gift_ledger (user_id, ts, coins, gift_id, gift_name, kind) "
        "VALUES ('u', 1.0, ?, ?, ?, 'gift')",
        [(coins, str(gid), name) for gid, name, coins in rows],
    )
    conn.commit()
    conn.close()


class TestGiftLogBackfill(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.catalog = os.path.join(self.dir, "available_gifts.json")
        self.log = os.path.join(self.dir, "gift_log.json")

    def write_log(self, entries):
        with open(self.log, "w", encoding="utf-8") as fh:
            json.dump(entries, fh)

    def test_gift_log_entry_supplies_name_price_and_icon(self):
        self.write_log([{
            "gift_id": "938882", "gift_name": "KhitoFam", "diamond_count": 1,
            "total_coins": 1,
            "icon": "https://p16-webcast.tiktokcdn.com/img/alisg/webcast-sg/x.webp",
        }])

        stats = gift_catalog_backfill.backfill_from_gift_log(self.catalog, self.log)

        self.assertEqual(stats["added"], 1)
        entry = gift_catalog.load_catalog(self.catalog)[0]
        self.assertEqual(entry["id"], 938882)
        self.assertEqual(entry["name"], "khitofam")
        self.assertEqual(entry["diamond_count"], 1)
        self.assertTrue(entry["icon"].startswith("https://p16-webcast"))

    def test_gift_log_entry_without_an_icon_still_records_name_and_price(self):
        self.write_log([{"gift_id": "12988", "gift_name": "Super GG",
                         "diamond_count": 100, "total_coins": 100, "icon": ""}])

        gift_catalog_backfill.backfill_from_gift_log(self.catalog, self.log)

        entry = gift_catalog.load_catalog(self.catalog)[0]
        self.assertEqual(entry["diamond_count"], 100)
        self.assertEqual(entry["icon"], "")

    def test_repeated_log_entries_collapse_to_one_gift(self):
        self.write_log([
            {"gift_id": "12988", "gift_name": "Super GG", "diamond_count": 100, "icon": ""},
            {"gift_id": "12988", "gift_name": "Super GG", "diamond_count": 100,
             "icon": "https://p16-webcast.tiktokcdn.com/img/s.webp"},
        ])

        gift_catalog_backfill.backfill_from_gift_log(self.catalog, self.log)

        entries = gift_catalog.load_catalog(self.catalog)
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["icon"], "the icon from the later entry should win")

    def test_missing_gift_log_is_not_an_error(self):
        stats = gift_catalog_backfill.backfill_from_gift_log(
            self.catalog, os.path.join(self.dir, "nope.json"))
        self.assertEqual(stats["added"], 0)

    def test_corrupt_gift_log_is_not_an_error(self):
        with open(self.log, "w", encoding="utf-8") as fh:
            fh.write("{{{not json")
        stats = gift_catalog_backfill.backfill_from_gift_log(self.catalog, self.log)
        self.assertEqual(stats["added"], 0)


class TestLedgerBackfill(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.catalog = os.path.join(self.dir, "available_gifts.json")
        self.db = os.path.join(self.dir, "points.db")

    def test_ledger_recovers_a_gift_absent_from_every_catalog(self):
        """The Super GG case, straight from Khito's real data shape."""
        make_ledger(self.db, [("12988", "Super GG", 100)] * 3)

        stats = gift_catalog_backfill.backfill_from_ledger(self.catalog, self.db)

        self.assertEqual(stats["added"], 1)
        entry = gift_catalog.load_catalog(self.catalog)[0]
        self.assertEqual(entry["id"], 12988)
        self.assertEqual(entry["name"], "super gg")
        self.assertEqual(entry["diamond_count"], 100)

    def test_unit_price_is_the_gcd_of_observed_totals(self):
        """Ledger stores repeat*price, so the GCD is the best price estimate."""
        make_ledger(self.db, [("6064", "GG", 11), ("6064", "GG", 29), ("6064", "GG", 100)])

        gift_catalog_backfill.backfill_from_ledger(self.catalog, self.db)

        self.assertEqual(gift_catalog.load_catalog(self.catalog)[0]["diamond_count"], 1)

    def test_manual_adjustment_rows_are_never_treated_as_gifts(self):
        """kind='manual' rows are operator coin repairs, not real gifts."""
        conn = sqlite3.connect(self.db)
        conn.execute(
            "CREATE TABLE gift_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id TEXT, ts REAL, coins INTEGER, gift_id TEXT, gift_name TEXT, kind TEXT)"
        )
        conn.execute("INSERT INTO gift_ledger (user_id, ts, coins, gift_id, gift_name, kind) "
                     "VALUES ('u', 1.0, 500, '', 'manual adjustment', 'manual')")
        conn.commit()
        conn.close()

        stats = gift_catalog_backfill.backfill_from_ledger(self.catalog, self.db)

        self.assertEqual(stats["added"], 0)
        self.assertEqual(gift_catalog.load_catalog(self.catalog), [])

    def test_ledger_never_downgrades_a_known_price(self):
        """History is the lowest-trust source and must not overwrite real data."""
        gift_catalog.merge_into_catalog(
            self.catalog,
            [{"id": 6581, "name": "Game Controller", "diamond_count": 100,
              "icon": {"url_list": ["https://p16-webcast.tiktokcdn.com/img/gc.webp"]}}],
            source="region")
        make_ledger(self.db, [("6581", "Game Controller", 700)])

        gift_catalog_backfill.backfill_from_ledger(self.catalog, self.db)

        entry = gift_catalog.load_catalog(self.catalog)[0]
        self.assertEqual(entry["diamond_count"], 100)
        self.assertEqual(entry["source"], "region")

    def test_missing_database_is_not_an_error(self):
        stats = gift_catalog_backfill.backfill_from_ledger(
            self.catalog, os.path.join(self.dir, "nope.db"))
        self.assertEqual(stats["added"], 0)

    def test_legacy_ledger_without_a_kind_column_still_backfills(self):
        conn = sqlite3.connect(self.db)
        conn.execute(
            "CREATE TABLE gift_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id TEXT, ts REAL, coins INTEGER, gift_id TEXT, gift_name TEXT)"
        )
        conn.execute("INSERT INTO gift_ledger (user_id, ts, coins, gift_id, gift_name) "
                     "VALUES ('u', 1.0, 100, '12988', 'Super GG')")
        conn.commit()
        conn.close()

        stats = gift_catalog_backfill.backfill_from_ledger(self.catalog, self.db)

        self.assertEqual(stats["added"], 1)


class TestCombinedBackfill(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.catalog = os.path.join(self.dir, "available_gifts.json")
        self.log = os.path.join(self.dir, "gift_log.json")
        self.db = os.path.join(self.dir, "points.db")

    def test_log_icon_wins_over_ledger_for_the_same_gift(self):
        with open(self.log, "w", encoding="utf-8") as fh:
            json.dump([{"gift_id": "12988", "gift_name": "Super GG", "diamond_count": 100,
                        "icon": "https://p16-webcast.tiktokcdn.com/img/s.webp"}], fh)
        make_ledger(self.db, [("12988", "Super GG", 100)])

        stats = gift_catalog_backfill.backfill_all(self.catalog, self.log, self.db)

        entries = gift_catalog.load_catalog(self.catalog)
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["icon"].startswith("https://p16-webcast"))
        self.assertEqual(stats["added"], 1)

    def test_backfill_is_idempotent(self):
        make_ledger(self.db, [("12988", "Super GG", 100)])

        gift_catalog_backfill.backfill_all(self.catalog, self.log, self.db)
        stats = gift_catalog_backfill.backfill_all(self.catalog, self.log, self.db)

        self.assertEqual(stats["added"], 0)
        self.assertEqual(stats["updated"], 0)


if __name__ == "__main__":
    unittest.main()
