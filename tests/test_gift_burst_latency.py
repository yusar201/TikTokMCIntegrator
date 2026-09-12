"""Regression tests for low-latency alternating gift bursts."""
from __future__ import annotations

import asyncio
import sys
import time
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import minecraft_main
import points_store


def _gift_event(
    name: str,
    gift_id: str,
    *,
    gift_type: int = 0,
    repeat_count: int = 1,
    repeat_end: int = 1,
    group_id=None,
):
    user = SimpleNamespace(
        id=12345,
        id_str="12345",
        unique_id="burst_viewer",
        nickname="Burst Viewer",
    )
    gift = SimpleNamespace(
        id=gift_id,
        name=name,
        diamond_count=1,
        type=gift_type,
        group_id=group_id,
    )
    return SimpleNamespace(
        user=user,
        gift=gift,
        repeat_count=repeat_count,
        repeat_end=repeat_end,
        group_id=group_id,
    )


class GiftBurstLatencyTest(unittest.TestCase):
    def setUp(self):
        minecraft_main.streak_tracker.clear()
        minecraft_main.active_streaks.clear()

    def test_active_streak_snapshots_cannot_overwrite_newer_state(self):
        """A slower old persistence worker must not regress the dashboard JSON."""
        writes = []

        minecraft_main.active_streaks["combo-1"] = {
            "count": 1,
            "last_updated": time.time(),
        }
        old_snapshot, old_version = minecraft_main.snapshot_active_streaks()

        minecraft_main.active_streaks["combo-1"]["count"] = 2
        new_snapshot, new_version = minecraft_main.snapshot_active_streaks()

        with patch.object(
            minecraft_main,
            "safe_json_write",
            side_effect=lambda data, _path: writes.append(data),
        ):
            minecraft_main.save_active_streaks(new_snapshot, new_version)
            minecraft_main.save_active_streaks(old_snapshot, old_version)

        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["combo-1"]["count"], 2)

    def test_alternating_gifts_dispatch_before_slow_points_persistence(self):
        """Rose/TikTok actions must start immediately even when SQLite is backed up."""
        starts: list[tuple[str, float]] = []

        async def capture_command(command: str):
            starts.append((command, time.perf_counter()))

        def slow_record_gift(*args, **kwargs):
            time.sleep(0.20)

        gift_actions = {
            "GlobalActions": [
                {"type": "minecraft", "command": "global {gift_name}"},
            ],
            "5655": [
                {"type": "minecraft", "command": "rose-action"},
            ],
            "5269": [
                {"type": "minecraft", "command": "tiktok-action"},
            ],
        }

        async def run_burst():
            started = time.perf_counter()
            events = [
                _gift_event("rose", "5655") if i % 2 == 0
                else _gift_event("tiktok", "5269")
                for i in range(20)
            ]
            await asyncio.gather(*(minecraft_main.on_gift(event) for event in events))
            return started

        with (
            patch.object(minecraft_main, "send_minecraft_command", capture_command),
            patch.object(minecraft_main, "_should_skip_action_execution", return_value=False),
            patch.object(minecraft_main, "_is_gift_downloader_enabled", return_value=False),
            patch.object(minecraft_main, "resolve_avatar_url", return_value=""),
            patch.object(minecraft_main, "append_gift_log", return_value=""),
            patch.object(minecraft_main, "update_gifter_ranking", return_value=None),
            patch.object(minecraft_main, "add_coins_to_jar", return_value=None),
            patch.object(minecraft_main, "add_to_gift_goal", return_value=None),
            patch.object(points_store, "record_gift", side_effect=slow_record_gift),
            patch.object(minecraft_main, "GIFT_ACTIONS", gift_actions),
            patch.object(minecraft_main, "GIFTS_WITH_STREAK_DELTA", set()),
        ):
            started = asyncio.run(run_burst())

        commands = [command for command, _ in starts]
        self.assertEqual(
            Counter(commands),
            Counter({
                "global rose": 10,
                "rose-action": 10,
                "global tiktok": 10,
                "tiktok-action": 10,
            }),
        )
        self.assertLess(max(timestamp - started for _, timestamp in starts), 0.075)

    def test_streak_delta_does_not_change_global_action_amount(self):
        """Final global action keeps total count; gift action receives only the delta."""
        commands: list[str] = []

        async def capture_command(command: str):
            commands.append(command)

        gift_actions = {
            "GlobalActions": [
                {"type": "minecraft", "command": "global amount={amount}"},
            ],
            "5827": [
                {"type": "minecraft", "command": "specific amount={amount}"},
            ],
        }

        async def run_streak():
            await minecraft_main.on_gift(_gift_event(
                "Ice Cream Cone", "5827", gift_type=1,
                repeat_count=4, repeat_end=0, group_id="combo-1",
            ))
            commands.clear()
            await minecraft_main.on_gift(_gift_event(
                "Ice Cream Cone", "5827", gift_type=1,
                repeat_count=5, repeat_end=1, group_id="combo-1",
            ))

        with (
            patch.object(minecraft_main, "send_minecraft_command", capture_command),
            patch.object(minecraft_main, "_should_skip_action_execution", return_value=False),
            patch.object(minecraft_main, "_is_gift_downloader_enabled", return_value=False),
            patch.object(minecraft_main, "resolve_avatar_url", return_value=""),
            patch.object(minecraft_main, "append_gift_log", return_value=""),
            patch.object(minecraft_main, "update_gifter_ranking", return_value=None),
            patch.object(minecraft_main, "save_active_streaks", return_value=None),
            patch.object(minecraft_main, "add_coins_to_jar", return_value=None),
            patch.object(minecraft_main, "add_to_gift_goal", return_value=None),
            patch.object(points_store, "record_gift", return_value=None),
            patch.object(minecraft_main, "GIFT_ACTIONS", gift_actions),
            patch.object(minecraft_main, "GIFTS_WITH_STREAK_DELTA", {"5827"}),
        ):
            asyncio.run(run_streak())

        self.assertEqual(
            Counter(commands),
            Counter({"global amount=5": 1, "specific amount=1": 1}),
        )


if __name__ == "__main__":
    unittest.main()
