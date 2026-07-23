"""Race-safe helper for TikTok streak-delta gift counting."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Hashable


@dataclass
class _GiftDeltaState:
    count: int
    ended: bool = False
    updated_at: float = 0.0


class GiftDeltaTracker:
    """Track highest seen repeat_count per combo and return only new delta.

    TikTok sends streak gifts as repeat_count snapshots (1, 2, 5, ...), not
    guaranteed single increments. This helper stores the highest count seen and
    returns repeat_count - previous_count. Final/duplicate/out-of-order events
    with a count already seen return 0.
    """

    def __init__(self, ended_ttl_seconds: float = 30.0):
        self.ended_ttl_seconds = ended_ttl_seconds
        self._states: dict[Hashable, _GiftDeltaState] = {}

    def apply(self, key: Hashable, repeat_count: int, is_streaking: bool, now: float | None = None) -> int:
        """Record a streak snapshot and return the positive new gift delta."""
        if key is None:
            key = "__missing_group_id__"
        if now is None:
            now = time.time()
        try:
            repeat_count = int(repeat_count)
        except Exception:
            repeat_count = 1
        repeat_count = max(0, repeat_count)

        state = self._states.get(key)
        prev = state.count if state else 0
        delta = max(0, repeat_count - prev)

        # Always keep the highest count before any awaited action executes.
        # This prevents overlapping GiftEvent handlers from reading stale prev.
        if state is None or repeat_count > prev or (not is_streaking):
            self._states[key] = _GiftDeltaState(
                count=max(prev, repeat_count),
                ended=not is_streaking,
                updated_at=now,
            )
        else:
            state.updated_at = now

        return delta

    def cleanup(self, now: float | None = None) -> None:
        """Remove ended entries after a short TTL, preserving duplicate-final guard."""
        if now is None:
            now = time.time()
        stale_keys = [
            key for key, state in self._states.items()
            if state.ended and now - state.updated_at > self.ended_ttl_seconds
        ]
        for key in stale_keys:
            self._states.pop(key, None)

    def clear(self) -> None:
        self._states.clear()
