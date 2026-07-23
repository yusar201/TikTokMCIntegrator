import spotify_handler as sh


def test_poll_delay_targets_expected_end_when_next_song_is_queued():
    delay = sh._next_queue_poll_delay(
        is_playing=True,
        progress_ms=176_800,
        duration_ms=180_000,
        has_local_playing=True,
        has_queued=True,
    )
    assert 3.3 <= delay <= 3.5


def test_poll_delay_keeps_normal_cadence_away_from_song_end():
    delay = sh._next_queue_poll_delay(
        is_playing=True,
        progress_ms=120_000,
        duration_ms=180_000,
        has_local_playing=True,
        has_queued=True,
    )
    assert delay == 5.0


def test_poll_delay_does_not_accelerate_when_paused_or_queue_empty():
    paused = sh._next_queue_poll_delay(False, 176_800, 180_000, True, True)
    empty_queue = sh._next_queue_poll_delay(True, 176_800, 180_000, True, False)
    assert paused == 5.0
    assert empty_queue == 5.0
