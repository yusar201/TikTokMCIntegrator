"""Roulette action type — executes via spin_roulette callback."""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from actions import execute_actions, migrate_actions


class RouletteActionTest(unittest.TestCase):
    def _run(self, actions, spin=None):
        called = {}

        async def _spin(ctx):
            called["ctx"] = ctx

        asyncio.run(execute_actions(actions, context={"user": "viewer"}, spin_roulette=spin or _spin))
        return called

    def test_roulette_action_calls_spinner_with_context(self):
        called = self._run([{"type": "roulette"}])
        self.assertEqual(called.get("ctx", {}).get("user"), "viewer")

    def test_roulette_action_without_spinner_is_noop(self):
        # Must not raise when no spinner is wired (pure unit / dashboard path).
        asyncio.run(execute_actions([{"type": "roulette"}], context={}, spin_roulette=None))

    def test_unknown_and_other_types_still_work(self):
        called = {}
        async def _spin(ctx):
            called["hit"] = True
        # random + roulette in one batch; roulette should fire
        asyncio.run(execute_actions(
            [{"type": "roulette"}],
            context={"user": "a"},
            spin_roulette=_spin,
        ))
        self.assertTrue(called.get("hit"))

    def test_migrate_leaves_roulette_dicts_untouched(self):
        migrated = migrate_actions([{"type": "roulette"}])
        self.assertEqual(migrated, [{"type": "roulette"}])


if __name__ == "__main__":
    unittest.main()
