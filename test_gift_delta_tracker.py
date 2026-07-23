from gift_delta import GiftDeltaTracker


def test_delta_tracker_counts_snapshot_gaps_once():
    tracker = GiftDeltaTracker()

    assert tracker.apply("group-a", 1, is_streaking=True) == 1
    assert tracker.apply("group-a", 2, is_streaking=True) == 1
    assert tracker.apply("group-a", 5, is_streaking=False) == 3


def test_delta_tracker_ignores_duplicate_final_event():
    tracker = GiftDeltaTracker()

    assert tracker.apply("group-a", 1, is_streaking=True) == 1
    assert tracker.apply("group-a", 5, is_streaking=False) == 4
    assert tracker.apply("group-a", 5, is_streaking=False) == 0


def test_delta_tracker_ignores_out_of_order_lower_snapshot():
    tracker = GiftDeltaTracker()

    assert tracker.apply("group-a", 5, is_streaking=True) == 5
    assert tracker.apply("group-a", 2, is_streaking=True) == 0


def test_delta_tracker_clears_old_ended_entries_only_after_ttl():
    tracker = GiftDeltaTracker(ended_ttl_seconds=30)

    assert tracker.apply("group-a", 5, is_streaking=False, now=100) == 5
    assert tracker.apply("group-a", 5, is_streaking=False, now=120) == 0
    tracker.cleanup(now=131)
    assert tracker.apply("group-a", 5, is_streaking=False, now=132) == 0
    tracker.cleanup(now=163)
    assert tracker.apply("group-a", 5, is_streaking=False, now=164) == 5
