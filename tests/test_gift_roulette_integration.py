"""Integration tests — Roulette reservation inside minecraft_main.on_gift.

Covers the plan's dispatch contract:
- accepted trigger: GlobalActions run, trigger-specific bundle consumed,
  winner bundle executes at land via ROULETTE_RUNTIME.run_reserved;
- rejected (busy/cooldown/invalid pool): normal trigger-specific actions run;
- non-trigger gifts behave byte-for-byte as before;
- intermediate streak events never spin; duplicate final guarded;
- log-only mode: no state write, no dispatch, normal logging only.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import minecraft_main
import gift_roulette


def _gift_event(gift_id="5655", name="rose", *, gift_type=0, repeat_count=1,
                repeat_end=1, group_id=None, user="RouletteFan"):
    return SimpleNamespace(
        user=SimpleNamespace(id=777, id_str="777", unique_id=user.lower(),
                             nickname=user),
        gift=SimpleNamespace(id=gift_id, name=name, diamond_count=1,
                             type=gift_type, group_id=group_id),
        repeat_count=repeat_count, repeat_end=repeat_end, group_id=group_id,
    )


ROULETTE_GIFTS = {
    "GlobalActions": [{"type": "minecraft", "command": "global {user}"}],
    "5655": [{"type": "minecraft", "command": "trigger-specific {user}"}],
    "5269": [
        {"type": "minecraft", "command": "winner-cmd-1 {user}"},
        {"type": "minecraft", "command": "winner-cmd-2 {user}"},
    ],
    "5333": [{"type": "sound", "file": "win.mp3"}],
}

ROULETTE_CONFIG = {
    "enabled": True, "trigger_gift_id": "5655",
    "spin_ms": 5000, "hold_ms": 4000, "cooldown_ms": 2000,
    "pool": ["5269", "5333"],
}


class _InstantRuntime:
    """Runtime double: no sleep, deterministic winner, records dispatch.

    Mirrors the REAL runtime's accept/reject contract that on_gift depends on:
    single active slot + duplicate-final guard (unit-tested against the real
    RouletteRuntime in test_gift_roulette.py). Only the sleep is removed.
    """

    DUPLICATE_TTL = 30.0

    def __init__(self, clock=None):
        self.dispatched = []
        self.reserved = 0
        self.rejected_reasons = []
        self.config = {}
        self._active = False
        self._last_completed = None
        self._clock = clock or (lambda: 1000.0)

    def sweep_stale(self):
        return False

    def try_reserve(self, prepared, cooldown_ms):
        trigger = prepared.public_state.get("trigger") or {}
        key = (trigger.get("gift_id", ""), trigger.get("user", ""))
        if self._active:
            self.rejected_reasons.append("busy")
            return (False, "busy")
        if self._last_completed == key:
            self.rejected_reasons.append("duplicate_final")
            return (False, "duplicate_final")
        self._active = True
        self.reserved += 1
        self.pending = prepared
        return (True, "ok")

    def mark_reserved_started(self):
        pass

    async def run_reserved(self, prepared, execute_bundle, *, sleep=None):
        await execute_bundle(list(prepared.winner_actions),
                             dict(prepared.winner_context))
        self.dispatched.append(prepared)
        self._active = False
        trigger = prepared.public_state.get("trigger") or {}
        self._last_completed = (trigger.get("gift_id", ""), trigger.get("user", ""))


def _patch_all(patch, runtime=None, log_only=False):
    runtime = runtime or _InstantRuntime()
    return (
        patch.object(minecraft_main, "send_minecraft_command",
                     _async_capture := _Capture()),
        patch.object(minecraft_main, "_should_skip_action_execution",
                     return_value=log_only),
        patch.object(minecraft_main, "_is_gift_downloader_enabled", return_value=False),
        patch.object(minecraft_main, "resolve_avatar_url", return_value=""),
        patch.object(minecraft_main, "append_gift_log", return_value=""),
        patch.object(minecraft_main, "update_gifter_ranking", return_value=None),
        patch.object(minecraft_main, "add_coins_to_jar", return_value=None),
        patch.object(minecraft_main, "add_to_gift_goal", return_value=None),
        patch.object(minecraft_main, "GIFT_ACTIONS", ROULETTE_GIFTS),
        patch.object(minecraft_main, "GIFTS_WITH_STREAK_DELTA", set()),
        patch.object(minecraft_main, "ROULETTE_CONFIG", ROULETTE_CONFIG),
        patch.object(minecraft_main, "ROULETTE_RUNTIME", runtime),
    )


class _Capture:
    def __init__(self):
        self.commands = []

    async def __call__(self, command):
        self.commands.append(command)


class RouletteGiftDispatchTest(unittest.TestCase):
    def setUp(self):
        minecraft_main.streak_tracker.clear()
        minecraft_main.active_streaks.clear()

    def test_accepted_trigger_runs_global_and_winner_not_trigger_specific(self):
        import unittest.mock as mock
        runtime = _InstantRuntime()
        capture = _Capture()

        async def scenario():
            await minecraft_main.on_gift(_gift_event())
            # 2nd same-viewer trigger: rejected (duplicate_final guard), normal actions
            await minecraft_main.on_gift(_gift_event())

        with mock.patch.object(minecraft_main, "send_minecraft_command", capture), \
             mock.patch.object(minecraft_main, "_should_skip_action_execution", return_value=False), \
             mock.patch.object(minecraft_main, "_is_gift_downloader_enabled", return_value=False), \
             mock.patch.object(minecraft_main, "resolve_avatar_url", return_value=""), \
             mock.patch.object(minecraft_main, "append_gift_log", return_value=""), \
             mock.patch.object(minecraft_main, "update_gifter_ranking", return_value=None), \
             mock.patch.object(minecraft_main, "add_coins_to_jar", return_value=None), \
             mock.patch.object(minecraft_main, "add_to_gift_goal", return_value=None), \
             mock.patch.object(minecraft_main, "GIFT_ACTIONS", ROULETTE_GIFTS), \
             mock.patch.object(minecraft_main, "GIFTS_WITH_STREAK_DELTA", set()), \
             mock.patch.object(minecraft_main, "ROULETTE_CONFIG", ROULETTE_CONFIG), \
             mock.patch.object(minecraft_main, "ROULETTE_RUNTIME", runtime):
            asyncio.run(scenario())

        # Spin 1: global + winner bundle only. Trigger-specific consumed on
        # the accepted spin; the rejected 2nd gift falls back to normal actions.
        winner_cmds = [c for c in capture.commands if c.startswith("winner-cmd")]
        trigger_cmds = [c for c in capture.commands if c.startswith("trigger-specific")]
        globals_ = [c for c in capture.commands if c.startswith("global")]
        self.assertEqual(len(winner_cmds), 2)   # full bundle (2 commands)
        self.assertEqual(len(trigger_cmds), 1)  # only from the rejected 2nd gift
        self.assertEqual(len(globals_), 2)      # both real gifts keep GlobalActions
        self.assertEqual(runtime.reserved, 1)
        self.assertEqual(len(runtime.dispatched), 1)

    def test_non_trigger_gift_unchanged(self):
        import unittest.mock as mock
        runtime = _InstantRuntime()
        capture = _Capture()
        with mock.patch.object(minecraft_main, "send_minecraft_command", capture), \
             mock.patch.object(minecraft_main, "_should_skip_action_execution", return_value=False), \
             mock.patch.object(minecraft_main, "_is_gift_downloader_enabled", return_value=False), \
             mock.patch.object(minecraft_main, "resolve_avatar_url", return_value=""), \
             mock.patch.object(minecraft_main, "append_gift_log", return_value=""), \
             mock.patch.object(minecraft_main, "update_gifter_ranking", return_value=None), \
             mock.patch.object(minecraft_main, "add_coins_to_jar", return_value=None), \
             mock.patch.object(minecraft_main, "add_to_gift_goal", return_value=None), \
             mock.patch.object(minecraft_main, "GIFT_ACTIONS", ROULETTE_GIFTS), \
             mock.patch.object(minecraft_main, "GIFTS_WITH_STREAK_DELTA", set()), \
             mock.patch.object(minecraft_main, "ROULETTE_CONFIG", ROULETTE_CONFIG), \
             mock.patch.object(minecraft_main, "ROULETTE_RUNTIME", runtime):
            asyncio.run(minecraft_main.on_gift(_gift_event("5269", "tiktok")))

        self.assertEqual(runtime.reserved, 0)  # not the trigger: no spin
        self.assertIn("winner-cmd-1 RouletteFan", capture.commands)
        self.assertIn("winner-cmd-2 RouletteFan", capture.commands)  # gift's own actions
        self.assertIn("global RouletteFan", capture.commands)

    def test_disabled_roulette_executes_normally(self):
        import unittest.mock as mock
        runtime = _InstantRuntime()
        capture = _Capture()
        with mock.patch.object(minecraft_main, "send_minecraft_command", capture), \
             mock.patch.object(minecraft_main, "_should_skip_action_execution", return_value=False), \
             mock.patch.object(minecraft_main, "_is_gift_downloader_enabled", return_value=False), \
             mock.patch.object(minecraft_main, "resolve_avatar_url", return_value=""), \
             mock.patch.object(minecraft_main, "append_gift_log", return_value=""), \
             mock.patch.object(minecraft_main, "update_gifter_ranking", return_value=None), \
             mock.patch.object(minecraft_main, "add_coins_to_jar", return_value=None), \
             mock.patch.object(minecraft_main, "add_to_gift_goal", return_value=None), \
             mock.patch.object(minecraft_main, "GIFT_ACTIONS", ROULETTE_GIFTS), \
             mock.patch.object(minecraft_main, "GIFTS_WITH_STREAK_DELTA", set()), \
             mock.patch.object(minecraft_main, "ROULETTE_CONFIG", {**ROULETTE_CONFIG, "enabled": False}), \
             mock.patch.object(minecraft_main, "ROULETTE_RUNTIME", runtime):
            asyncio.run(minecraft_main.on_gift(_gift_event()))

        self.assertEqual(runtime.reserved, 0)
        self.assertIn("trigger-specific RouletteFan", capture.commands)
        self.assertIn("global RouletteFan", capture.commands)

    def test_streak_intermediate_never_spins_final_spins_once(self):
        import unittest.mock as mock
        runtime = _InstantRuntime()
        capture = _Capture()
        with mock.patch.object(minecraft_main, "send_minecraft_command", capture), \
             mock.patch.object(minecraft_main, "_should_skip_action_execution", return_value=False), \
             mock.patch.object(minecraft_main, "_is_gift_downloader_enabled", return_value=False), \
             mock.patch.object(minecraft_main, "resolve_avatar_url", return_value=""), \
             mock.patch.object(minecraft_main, "append_gift_log", return_value=""), \
             mock.patch.object(minecraft_main, "update_gifter_ranking", return_value=None), \
             mock.patch.object(minecraft_main, "save_active_streaks", return_value=None), \
             mock.patch.object(minecraft_main, "add_coins_to_jar", return_value=None), \
             mock.patch.object(minecraft_main, "add_to_gift_goal", return_value=None), \
             mock.patch.object(minecraft_main, "GIFT_ACTIONS", ROULETTE_GIFTS), \
             mock.patch.object(minecraft_main, "GIFTS_WITH_STREAK_DELTA", set()), \
             mock.patch.object(minecraft_main, "ROULETTE_CONFIG", ROULETTE_CONFIG), \
             mock.patch.object(minecraft_main, "ROULETTE_RUNTIME", runtime):
            asyncio.run(minecraft_main.on_gift(_gift_event(
                gift_type=1, repeat_count=1, repeat_end=0, group_id="g1")))
            asyncio.run(minecraft_main.on_gift(_gift_event(
                gift_type=1, repeat_count=5, repeat_end=1, group_id="g1")))
            # duplicate final summary
            asyncio.run(minecraft_main.on_gift(_gift_event(
                gift_type=1, repeat_count=5, repeat_end=1, group_id="g1")))

        self.assertEqual(runtime.reserved, 1)   # only the completed event
        self.assertEqual(len(runtime.dispatched), 1)

    def test_log_only_mode_no_spin_no_dispatch(self):
        import unittest.mock as mock
        runtime = _InstantRuntime()
        capture = _Capture()
        with mock.patch.object(minecraft_main, "send_minecraft_command", capture), \
             mock.patch.object(minecraft_main, "_should_skip_action_execution", return_value=True), \
             mock.patch.object(minecraft_main, "_is_gift_downloader_enabled", return_value=False), \
             mock.patch.object(minecraft_main, "resolve_avatar_url", return_value=""), \
             mock.patch.object(minecraft_main, "append_gift_log", return_value=""), \
             mock.patch.object(minecraft_main, "update_gifter_ranking", return_value=None), \
             mock.patch.object(minecraft_main, "save_active_streaks", return_value=None), \
             mock.patch.object(minecraft_main, "add_coins_to_jar", return_value=None), \
             mock.patch.object(minecraft_main, "add_to_gift_goal", return_value=None), \
             mock.patch.object(minecraft_main, "GIFT_ACTIONS", ROULETTE_GIFTS), \
             mock.patch.object(minecraft_main, "GIFTS_WITH_STREAK_DELTA", set()), \
             mock.patch.object(minecraft_main, "ROULETTE_CONFIG", ROULETTE_CONFIG), \
             mock.patch.object(minecraft_main, "ROULETTE_RUNTIME", runtime):
            asyncio.run(minecraft_main.on_gift(_gift_event()))

        self.assertEqual(runtime.reserved, 0)
        self.assertEqual(capture.commands, [])
        self.assertEqual(runtime.dispatched, [])


if __name__ == "__main__":
    unittest.main()
