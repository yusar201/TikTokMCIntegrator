"""Regression tests for readable TikTok bot reconnect backoff."""

from reconnect_policy import format_reconnect_delay, next_reconnect_delay


def test_retry_delay_is_shown_as_clean_whole_seconds():
    assert format_reconnect_delay(4.981727281) == "5 seconds"
    assert format_reconnect_delay(1.0) == "1 second"


def test_next_retry_delay_keeps_backoff_and_caps_at_five_minutes():
    assert next_reconnect_delay(5, jitter=0) == 8
    assert next_reconnect_delay(5, jitter=2) == 10
    assert next_reconnect_delay(299, jitter=2) == 300
