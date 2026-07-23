"""Reconnect delay helpers shared by the TikTok bot loop and tests."""

import math


INITIAL_RECONNECT_DELAY = 5
MAX_RECONNECT_DELAY = 300
MAX_RECONNECT_RETRIES = 20


def format_reconnect_delay(delay: float) -> str:
    """Return a clean operator-facing retry duration."""
    seconds = max(1, int(math.ceil(delay)))
    unit = "second" if seconds == 1 else "seconds"
    return f"{seconds} {unit}"


def next_reconnect_delay(current_delay: float, jitter: float = 0) -> int:
    """Apply 1.5x exponential backoff plus jitter, rounded to whole seconds."""
    return min(int(math.ceil(current_delay * 1.5 + jitter)), MAX_RECONNECT_DELAY)
