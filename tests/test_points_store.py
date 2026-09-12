"""Contract tests for the long-term viewer points store."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import points_store


class PointsStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        points_store.init(os.path.join(self.tmp.name, "points.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_and_aggregate(self):
        points_store.record_gift("111", username="alice", nickname="Alice",
                                 avatar_url="a", coins=100, gift_id="1", gift_name="Rose")
        points_store.record_gift("111", username="alice", nickname="Alice",
                                 coins=50, gift_id="2", gift_name="Heart")
        data = points_store.list_viewers()
        self.assertEqual(data["total"], 1)
        v = data["viewers"][0]
        self.assertEqual(v["user_id"], "111")
        self.assertEqual(v["total_coins"], 150)
        self.assertEqual(v["gift_count"], 2)
        self.assertEqual(data["total_coins"], 150)
        self.assertEqual(data["total_gifts"], 2)

    def test_identity_survives_rename(self):
        """Same permanent id, changed username/nickname -> one viewer, names refreshed."""
        points_store.record_gift("222", username="oldhandle", nickname="Old Name", coins=10)
        points_store.record_gift("222", username="newhandle", nickname="New Name", coins=20)
        data = points_store.list_viewers()
        self.assertEqual(data["total"], 1)
        v = data["viewers"][0]
        self.assertEqual(v["username"], "newhandle")
        self.assertEqual(v["nickname"], "New Name")
        self.assertEqual(v["total_coins"], 30)

    def test_missing_fields_do_not_blank_existing(self):
        points_store.record_gift("333", username="bob", nickname="Bob", avatar_url="img", coins=5)
        points_store.record_gift("333", username="", nickname="", avatar_url="", coins=5)
        v = points_store.list_viewers()["viewers"][0]
        self.assertEqual(v["username"], "bob")
        self.assertEqual(v["nickname"], "Bob")
        self.assertEqual(v["avatar_url"], "img")

    def test_zero_and_invalid_coins_ignored(self):
        points_store.record_gift("444", coins=0)
        points_store.record_gift("444", coins="abc")
        self.assertEqual(points_store.list_viewers()["total"], 0)

    def test_search_and_sort(self):
        points_store.record_gift("1", nickname="Zeta", username="z", coins=500)
        points_store.record_gift("2", nickname="Alpha", username="a", coins=10)
        points_store.record_gift("3", nickname="Mid", username="m", coins=100)

        by_coins = points_store.list_viewers(sort="coins")["viewers"]
        self.assertEqual([v["nickname"] for v in by_coins], ["Zeta", "Mid", "Alpha"])

        by_name = points_store.list_viewers(sort="name")["viewers"]
        self.assertEqual([v["nickname"] for v in by_name], ["Alpha", "Mid", "Zeta"])

        hits = points_store.list_viewers(q="alph")
        self.assertEqual(hits["total"], 1)
        self.assertEqual(hits["viewers"][0]["user_id"], "2")

        hits_by_id = points_store.list_viewers(q="3")
        self.assertEqual(hits_by_id["total"], 1)
        self.assertEqual(hits_by_id["viewers"][0]["user_id"], "3")

    def test_pagination(self):
        for i in range(7):
            points_store.record_gift(str(100 + i), nickname=f"u{i}", coins=i + 1)
        page = points_store.list_viewers(limit=3, offset=0, sort="coins")
        self.assertEqual(len(page["viewers"]), 3)
        self.assertEqual(page["viewers"][0]["total_coins"], 7)
        page2 = points_store.list_viewers(limit=3, offset=6, sort="coins")
        self.assertEqual(len(page2["viewers"]), 1)

    def test_period_aggregates_only_gifts_inside_half_open_range(self):
        points_store.record_gift("1", nickname="Alice", coins=10, ts=100.0)
        points_store.record_gift("1", nickname="Alice", coins=20, ts=200.0)
        points_store.record_gift("2", nickname="Bob", coins=30, ts=299.999)
        points_store.record_gift("3", nickname="Outside", coins=40, ts=300.0)

        data = points_store.list_viewers(since=200.0, until=300.0)

        self.assertEqual(data["total"], 2)
        self.assertEqual(data["total_viewers"], 2)
        self.assertEqual(data["total_coins"], 50)
        self.assertEqual(data["total_gifts"], 2)
        self.assertEqual(
            [(v["nickname"], v["total_coins"], v["gift_count"]) for v in data["viewers"]],
            [("Bob", 30, 1), ("Alice", 20, 1)],
        )
        self.assertEqual(data["viewers"][0]["last_gift_ts"], 299.999)
        self.assertEqual(data["since"], 200.0)
        self.assertEqual(data["until"], 300.0)

    def test_period_search_filters_rows_but_not_period_summary(self):
        points_store.record_gift("1", nickname="Alice", coins=20, ts=200.0)
        points_store.record_gift("2", nickname="Bob", coins=30, ts=250.0)

        data = points_store.list_viewers(q="ali", since=100.0, until=300.0)

        self.assertEqual(data["total"], 1)
        self.assertEqual(data["viewers"][0]["nickname"], "Alice")
        self.assertEqual(data["total_viewers"], 2)
        self.assertEqual(data["total_coins"], 50)
        self.assertEqual(data["total_gifts"], 2)

    def test_detail_history(self):
        points_store.record_gift("9", nickname="D", coins=10, gift_name="Rose")
        points_store.record_gift("9", nickname="D", coins=25, gift_name="Cap")
        detail = points_store.viewer_detail("9")
        self.assertIsNotNone(detail["viewer"])
        self.assertEqual(len(detail["history"]), 2)
        self.assertEqual(detail["history"][0]["gift_name"], "Cap")  # newest first

    def test_no_user_id_or_no_coins_is_noop(self):
        points_store.record_gift("", nickname="X", coins=10)
        points_store.record_gift(None, nickname="X", coins=10)
        self.assertEqual(points_store.list_viewers()["total"], 0)


if __name__ == "__main__":
    unittest.main()
