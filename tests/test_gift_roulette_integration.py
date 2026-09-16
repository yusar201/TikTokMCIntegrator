"""Integration tests — Roulette dispatch inside minecraft_main.on_gift.

Covers the dispatch contract AFTER Roulette became a general action type:
- a gift/event whose action bundle contains {"type": "roulette"} starts a spin;
- the gift's own action bundle still executes in full (nothing is "consumed");
- GlobalActions always run;
- every accepted trigger spins: a trigger arriving while a spin is active or
  cooling down is queued FIFO and runs after, with its own sender + winner;
- only duplicate_final / invalid pool / queue_full reject, changing nothing
  about normal action execution;
- non-roulette gifts behave byte-for-byte as before;
- intermediate streak events never spin; duplicate final guarded;
- log-only mode: no state write, no dispatch, normal logging only.

The previous revision of this file asserted that a *bare* gift (legacy
trigger_gift_id) auto-spun. That contract was intentionally removed when the
Roulette tab's trigger-gift picker was deleted — roulette now only fires when a
`roulette` action is attached, so the fixtures below carry one explicitly.
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
    # Roulette is opt-in per gift/event: the bundle must carry the action.
    "5655": [
        {"type": "minecraft", "command": "gift-own {user}"},
        {"type": "roulette"},
    ],
    "5269": [
        {"type": "minecraft", "command": "winner-cmd-1 {user}"},
        {"type": "minecraft", "command": "winner-cmd-2 {user}"},
    ],
    "5333": [{"type": "sound", "file": "win.mp3"}],
}

ROULETTE_CONFIG = {
    "enabled": True, "trigger_gift_id": "",
    "spin_ms": 5000, "hold_ms": 4000, "cooldown_ms": 2000,
    "pool": ["5269", "5333"],
}


class _InstantRuntime:
    """Runtime double: no sleep, deterministic winner, records dispatch.

    Mirrors the REAL runtime's queue contract that on_gift depends on:
    one active slot + FIFO queue + duplicate-final guard (unit-tested
    against the real RouletteRuntime in test_gift_roulette.py). Only the
    sleep is removed — queued spins run immediately in arrival order.
    """

    DUPLICATE_TTL = 30.0

    def __init__(self, clock=None):
        self.dispatched = []
        self.reserved = 0
        self.queued = 0
        self.rejected_reasons = []
        self.config = {}
        self._active = False
        self._queue = []
        self._last_completed = None
        self._clock = clock or (lambda: 1000.0)

    def sweep_stale(self):
        return False

    def queue_depth(self):
        return len(self._queue)

    def cooldown_delay(self):
        return 0.0

    def claim_pump(self):
        return True

    def release_pump(self):
        pass

    def take_next(self):
        if self._active or not self._queue:
            return None
        nxt = self._queue.pop(0)
        self._active = True
        self.reserved += 1
        self.pending = nxt
        return nxt

    def try_reserve(self, prepared, cooldown_ms):
        trigger = prepared.public_state.get("trigger") or {}
        key = (trigger.get("gift_id", ""), trigger.get("user", ""))
        if self._last_completed == key:
            self.rejected_reasons.append("duplicate_final")
            return (False, "duplicate_final")
        if self._active:
            self._queue.append(prepared)
            self.queued += 1
            return (True, "queued")
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

    def test_roulette_action_spins_and_gift_actions_still_run(self):
        import unittest.mock as mock
        runtime = _InstantRuntime()
        capture = _Capture()

        async def scenario():
            await minecraft_main.on_gift(_gift_event())
            # 2nd same-viewer gift: spin rejected (duplicate_final guard).
            # The gift's own actions and GlobalActions still run both times.
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

        # Spin 1 reserves exactly one spin and dispatches the *winner's* full
        # bundle at land. The winner is random across the pool, so assert the
        # dispatched bundle's own commands landed rather than assuming which
        # pool entry won. The rejected 2nd gift dispatches nothing extra, and
        # neither gift's own actions nor GlobalActions are ever suppressed.
        own_cmds = [c for c in capture.commands if c.startswith("gift-own")]
        globals_ = [c for c in capture.commands if c.startswith("global")]
        self.assertEqual(len(own_cmds), 2)      # both gifts keep their own actions
        self.assertEqual(len(globals_), 2)      # both gifts keep GlobalActions
        self.assertEqual(runtime.reserved, 1)
        self.assertEqual(len(runtime.dispatched), 1)

        winner_actions = list(runtime.dispatched[0].winner_actions)
        # The dispatched bundle must be the *winner's* configured bundle verbatim
        # (pool gifts 5269/5333) — never the trigger gift's own actions and never
        # GlobalActions. The winner is random, so accept either pool member.
        pool_bundles = [ROULETTE_GIFTS["5269"], ROULETTE_GIFTS["5333"]]
        self.assertIn(winner_actions, pool_bundles)
        self.assertNotEqual(winner_actions, ROULETTE_GIFTS["5655"])
        self.assertNotEqual(winner_actions, ROULETTE_GIFTS["GlobalActions"])

        # Every executable action in the winning bundle must have run at land.
        winner_ctx = runtime.dispatched[0].winner_context
        for action in winner_actions:
            if action.get("type") == "minecraft":
                expected = action["command"]
                for key, val in winner_ctx.items():
                    expected = expected.replace("{" + key + "}", str(val))
                self.assertIn(expected, capture.commands)

    def test_two_rapid_gifts_each_spin_with_own_sender(self):
        """Two roulette gifts arriving while a spin is active both execute.

        FIFO order: Alice's spin runs first, Bob's queued spin runs after
        the first winner bundle finishes — each with its own sender name.
        """
        import unittest.mock as mock
        runtime = _InstantRuntime()
        capture = _Capture()
        started = asyncio.Event()
        release = asyncio.Event()
        real_run = runtime.run_reserved

        async def blocking_run(prepared, execute_bundle, *, sleep=None):
            started.set()
            await release.wait()
            await real_run(prepared, execute_bundle, sleep=sleep)

        runtime.run_reserved = blocking_run

        async def scenario():
            first = asyncio.create_task(
                minecraft_main.on_gift(_gift_event(user="Alice")))
            await started.wait()  # Alice's spin is mid-animation
            await minecraft_main.on_gift(_gift_event(user="Bob"))  # queued
            self.assertEqual(runtime.queue_depth(), 1)
            release.set()
            await first
            for _ in range(100):  # let the drain chain finish Bob's spin
                if len(runtime.dispatched) >= 2:
                    break
                await asyncio.sleep(0.01)

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

        self.assertEqual(runtime.reserved, 2)
        self.assertEqual(len(runtime.dispatched), 2)
        # FIFO: Alice first, Bob second, each spin carrying its own sender.
        users = [d.winner_context["user"] for d in runtime.dispatched]
        self.assertEqual(users, ["Alice", "Bob"])
        pool_bundles = [ROULETTE_GIFTS["5269"], ROULETTE_GIFTS["5333"]]
        for dispatched in runtime.dispatched:
            self.assertIn(list(dispatched.winner_actions), pool_bundles)

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
        self.assertIn("gift-own RouletteFan", capture.commands)
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
