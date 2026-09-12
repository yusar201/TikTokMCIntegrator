"""Contract tests for the per-stream Top Gifters / Top Likers ranking store."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stream_ranking


class StreamRankingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.gifter_file = os.path.join(self.tmp.name, "gifter_ranking.json")
        self.liker_file = os.path.join(self.tmp.name, "liker_ranking.json")
        self.token_file = os.path.join(self.tmp.name, "ranking_reset_token.json")
        # Isolate module-level state for every test.
        stream_ranking._state.clear()
        stream_ranking._last_flush.clear()
        stream_ranking._last_reset_ts = 0.0
        stream_ranking._last_token_check = 0.0
        self._token_patch = mock.patch.object(stream_ranking, "RESET_TOKEN_FILE", self.token_file)
        self._token_patch.start()

    def tearDown(self):
        self._token_patch.stop()
        self.tmp.cleanup()
        stream_ranking._state.clear()
        stream_ranking._last_flush.clear()
        stream_ranking._last_reset_ts = 0.0
        stream_ranking._last_token_check = 0.0

    def test_accumulate_and_sort(self):
        stream_ranking.update(self.gifter_file, "Alice", "a", 100, unique_id="u1", force=True)
        stream_ranking.update(self.gifter_file, "Bob", "b", 300, unique_id="u2", force=True)
        stream_ranking.update(self.gifter_file, "Alice", "a", 50, unique_id="u1", force=True)
        top = stream_ranking.top(self.gifter_file, "total_coins")
        self.assertEqual([e["nick"] for e in top], ["Bob", "Alice"])
        self.assertEqual(top[1]["total_coins"], 150)
        self.assertEqual(top[1]["gift_count"], 2)

    def test_same_uid_different_nick_stays_one_entry(self):
        stream_ranking.update(self.gifter_file, "OldName", "a", 10, unique_id="u1", force=True)
        stream_ranking.update(self.gifter_file, "NewName", "a", 20, unique_id="u1", force=True)
        top = stream_ranking.top(self.gifter_file, "total_coins")
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0]["total_coins"], 30)
        self.assertEqual(top[0]["nick"], "NewName")

    def test_liker_board_uses_likes_keys(self):
        stream_ranking.update(self.liker_file, "Carol", "c", 25, unique_id="u3",
                              amount_key="total_likes", count_key="like_batches", force=True)
        top = stream_ranking.top(self.liker_file, "total_likes")
        self.assertEqual(top[0]["total_likes"], 25)
        self.assertEqual(top[0]["like_batches"], 1)

    def test_ignores_zero_and_negative_and_bad_amounts(self):
        stream_ranking.update(self.gifter_file, "X", "x", 0)
        stream_ranking.update(self.gifter_file, "X", "x", -5)
        stream_ranking.update(self.gifter_file, "X", "x", "abc")
        stream_ranking.update(self.gifter_file, "", "x", 10)
        self.assertEqual(stream_ranking.top(self.gifter_file, "total_coins"), [])

    def test_top_serves_max_10_but_keeps_more_history(self):
        for i in range(15):
            stream_ranking.update(self.gifter_file, f"v{i}", "", (i + 1) * 10,
                                  unique_id=f"u{i}", force=True)
        top = stream_ranking.top(self.gifter_file, "total_coins")
        self.assertEqual(len(top), 10)
        self.assertEqual(top[0]["nick"], "v14")

    def test_throttled_flush_not_forced(self):
        # First update ever flushes immediately (nothing on disk yet).
        stream_ranking.update(self.liker_file, "D", "d", 1, unique_id="u9")
        self.assertTrue(os.path.exists(self.liker_file))
        mtime = os.path.getmtime(self.liker_file)
        # Updates within LIKE_FLUSH_INTERVAL must not rewrite the file.
        stream_ranking.update(self.liker_file, "E", "e", 2, unique_id="u10")
        stream_ranking.update(self.liker_file, "F", "f", 3, unique_id="u11")
        self.assertEqual(mtime, os.path.getmtime(self.liker_file),
                         "flush must be throttled within the interval")
        # Force flush lands everything.
        stream_ranking.flush_all()
        import json
        with open(self.liker_file, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 3)

    def test_preserves_local_avatar_enrichment_on_flush(self):
        stream_ranking.update(self.gifter_file, "G", "https://cdn.example/x.jpg", 5,
                              unique_id="u20", force=True)
        # Dashboard enriches the on-disk avatar to a local cache URL.
        import json
        with open(self.gifter_file, encoding="utf-8") as fh:
            disk = json.load(fh)
        disk[0]["avatar_url"] = "/avatar_cache/u20.jpg"
        with open(self.gifter_file, "w", encoding="utf-8") as fh:
            json.dump(disk, fh)
        # Bot flushes again with the expiring CDN URL — local URL must survive.
        stream_ranking.update(self.gifter_file, "G", "https://cdn.example/expired.jpg", 5,
                              unique_id="u20", force=True)
        top = stream_ranking.top(self.gifter_file, "total_coins")
        self.assertEqual(top[0]["avatar_url"], "/avatar_cache/u20.jpg")

    def test_reset_clears_board_and_disk(self):
        stream_ranking.update(self.gifter_file, "H", "", 7, unique_id="u30", force=True)
        stream_ranking.reset(self.gifter_file)
        self.assertEqual(stream_ranking.top(self.gifter_file, "total_coins"), [])
        import json
        with open(self.gifter_file, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), [])

    def test_init_from_disk_reloads_state(self):
        stream_ranking.update(self.gifter_file, "I", "", 9, unique_id="u40", force=True)
        stream_ranking._state.clear()  # simulate process restart / reconnect
        stream_ranking.init_from_disk(self.gifter_file)
        top = stream_ranking.top(self.gifter_file, "total_coins")
        self.assertEqual(top[0]["nick"], "I")
        self.assertEqual(top[0]["total_coins"], 9)

    def test_manual_reset_token_clears_in_memory_boards(self):
        stream_ranking.update(self.gifter_file, "J", "", 4, unique_id="u50", force=True)
        # Mirror the reset endpoint: clear disk files AND write the token.
        stream_ranking.reset(self.gifter_file)
        stream_ranking.request_reset()
        # Force the throttled token check to run now.
        stream_ranking._last_token_check = 0.0
        stream_ranking.update(self.gifter_file, "K", "", 6, unique_id="u51", force=True)
        top = stream_ranking.top(self.gifter_file, "total_coins")
        self.assertEqual([e["nick"] for e in top], ["K"],
                         "token reset must wipe prior in-memory entries")

    def test_ack_reset_token_baselines_without_clearing(self):
        stream_ranking.request_reset()  # stale token from a previous live
        stream_ranking.ack_reset_token()
        stream_ranking.update(self.gifter_file, "L", "", 8, unique_id="u60", force=True)
        top = stream_ranking.top(self.gifter_file, "total_coins")
        self.assertEqual([e["nick"] for e in top], ["L"],
                         "stale token must not wipe a fresh live's entries")

    def test_token_check_is_throttled(self):
        stream_ranking.request_reset()
        stream_ranking._last_token_check = time.time()  # just checked
        before = stream_ranking._last_token_check
        stream_ranking.update(self.gifter_file, "M", "", 1, unique_id="u70")
        self.assertEqual(stream_ranking._last_token_check, before,
                         "token file must not be re-read inside the throttle window")
        self.assertEqual(stream_ranking._last_reset_ts, 0.0,
                         "throttled check must not apply the reset")
        top = stream_ranking.top(self.gifter_file, "total_coins")
        self.assertEqual([e["nick"] for e in top], ["M"])


if __name__ == "__main__":
    unittest.main()
