"""Gift Roulette engine tests — config normalization, pool resolution, spin
preparation, runtime reservation/persistence.

Engine contract (see .hermes/plans/roulette-randomizer.md):
- gift-level randomization: the winner's ENTIRE configured action bundle runs,
  never the single-line `random` sub-action picker.
- engine module is import-safe without Flask/TikTokLive/minecraft_main.
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gift_roulette


def _gifts():
    return {
        "GlobalActions": [{"type": "minecraft", "command": "chatgift {user}"}],
        "5269": [
            {"type": "minecraft", "command": "spawnmob {mc} {amount} baby husk {user}"},
            {"type": "minecraft", "command": "titlecustom {user} {amount} Baby Husk"},
        ],
        "5333": [{"type": "sound", "file": "silverfish.mp3"}],
        "5487": [],
        "5655": [{"type": "minecraft", "command": "give {mc} diamond {amount}"}],
        "tiktok": [{"type": "minecraft", "command": "legacy name key {user}"}],
    }


def _catalog():
    return {
        "5269": {"id": 5269, "name": "tiktok", "diamond_count": 1, "icon": "https://cdn/icon5269.png"},
        "5333": {"id": 5333, "name": "silverfish platoon", "diamond_count": 10, "icon": ""},
        "5655": {"id": 5655, "name": "rose", "diamond_count": 1, "icon": "https://cdn/rose.png"},
    }


def _names():
    return {"5333": "Silverfish Platoon"}


def _descriptions():
    return {"5269": "A baby husk army appears"}


def _config(**overrides):
    cfg = {
        "enabled": True,
        "trigger_gift_id": "5655",
        "spin_ms": 5000,
        "hold_ms": 4000,
        "cooldown_ms": 2000,
        "pool": ["5269", "5333"],
    }
    cfg.update(overrides)
    return cfg


class NormalizeConfigTest(unittest.TestCase):
    def test_missing_config_returns_disabled_defaults(self):
        for raw in (None, {}, "nope", 42, []):
            cfg = gift_roulette.normalize_config(raw)
            self.assertEqual(cfg["enabled"], False)
            self.assertEqual(cfg["trigger_gift_id"], "")
            self.assertEqual(cfg["spin_ms"], 5000)
            self.assertEqual(cfg["hold_ms"], 4000)
            self.assertEqual(cfg["cooldown_ms"], 2000)
            self.assertEqual(cfg["pool"], [])
        self.assertEqual(
            gift_roulette.normalize_config(None), gift_roulette.DEFAULT_ROULETTE_CONFIG
        )

    def test_ids_normalize_to_strings(self):
        cfg = gift_roulette.normalize_config({"enabled": True, "trigger_gift_id": 5655, "pool": [5269, "5333"]})
        self.assertEqual(cfg["trigger_gift_id"], "5655")
        self.assertEqual(cfg["pool"], ["5269", "5333"])

    def test_timing_values_are_clamped_to_ranges(self):
        cfg = gift_roulette.normalize_config({"spin_ms": 1, "hold_ms": 99999, "cooldown_ms": -5})
        self.assertEqual(cfg["spin_ms"], 2000)
        self.assertEqual(cfg["hold_ms"], 10000)
        self.assertEqual(cfg["cooldown_ms"], 0)

        cfg = gift_roulette.normalize_config({"spin_ms": "not a number", "hold_ms": None})
        self.assertEqual(cfg["spin_ms"], 5000)
        self.assertEqual(cfg["hold_ms"], 4000)

    def test_unknown_fields_are_dropped(self):
        cfg = gift_roulette.normalize_config({"enabled": True, "evil": "drop me", "pool": []})
        self.assertNotIn("evil", cfg)

    def test_duplicate_pool_ids_removed_preserving_order(self):
        cfg = gift_roulette.normalize_config({"pool": ["5269", 5269, "5333", "5269"]})
        self.assertEqual(cfg["pool"], ["5269", "5333"])

    def test_globalactions_never_enters_pool(self):
        cfg = gift_roulette.normalize_config({"pool": ["GlobalActions", "5269"]})
        self.assertEqual(cfg["pool"], ["5269"])

    def test_pool_capped_at_100(self):
        pool = [str(1000 + i) for i in range(150)]
        cfg = gift_roulette.normalize_config({"pool": pool})
        self.assertEqual(len(cfg["pool"]), 100)


class ResolveEntriesTest(unittest.TestCase):
    def test_resolves_labels_icons_and_prices(self):
        entries = gift_roulette.resolve_entries(
            _config(), _gifts(), _names(), _descriptions(), _catalog()
        )
        by_id = {e["gift_id"]: e for e in entries}
        self.assertEqual(
            by_id["5269"]["label"], "A baby husk army appears"
        )  # description wins
        self.assertEqual(by_id["5269"]["icon_url"], "https://cdn/icon5269.png")
        self.assertEqual(by_id["5333"]["label"], "Silverfish Platoon")  # GiftNames next
        self.assertEqual(by_id["5333"]["icon_url"], "")

    def test_label_fallback_order(self):
        # no description -> GiftNames; no names -> catalog name; nothing -> Gift #id
        catalog = dict(_catalog())
        catalog.pop("5655")  # force the final Gift #id fallback
        entries = gift_roulette.resolve_entries(
            _config(pool=["5333", "5655"]), _gifts(), {}, {}, catalog
        )
        by_id = {e["gift_id"]: e for e in entries}
        self.assertEqual(by_id["5333"]["label"], "silverfish platoon")  # catalog name
        self.assertEqual(by_id["5655"]["label"], "Gift #5655")  # catalog miss

    def test_commands_never_become_labels(self):
        entries = gift_roulette.resolve_entries(
            _config(pool=["5269"]), _gifts(), {}, {}, {}
        )
        self.assertEqual(len(entries), 1)
        self.assertNotIn("spawnmob", entries[0]["label"])

    def test_action_label_prefers_description(self):
        # Khito's paper-crane case: description wins over command-derived text.
        entries = gift_roulette.resolve_entries(
            _config(pool=["5269", "5333"]), _gifts(), _names(), _descriptions(), _catalog()
        )
        by_id = {e["gift_id"]: e for e in entries}
        self.assertEqual(by_id["5269"]["action_label"], "A baby husk army appears")
        # 5333 has no description: title/verb path, then GiftNames.
        self.assertEqual(by_id["5333"]["action_label"], "Silverfish Platoon")

    def test_action_label_title_before_verb(self):
        gifts = {"5269": [{"type": "minecraft", "command": "titlecustom {user} {amount} Baby Husk"}]}
        entries = gift_roulette.resolve_entries(
            _config(pool=["5269"]), gifts, {}, {}, {}
        )
        self.assertEqual(entries[0]["action_label"], "Baby Husk")

    def test_action_label_verb_then_name_then_id(self):
        gifts = {"5269": [{"type": "minecraft", "command": "spawnmob {mc} {amount} zombie {user}"}]}
        entries = gift_roulette.resolve_entries(
            _config(pool=["5269"]), gifts, {}, {}, {}
        )
        self.assertEqual(entries[0]["action_label"], "Spawnmob")
        # no usable command at all -> GiftNames -> catalog -> Gift #id
        gifts = {"5269": [{"type": "minecraft", "command": "rtp {mc} {user}"}]}
        entries = gift_roulette.resolve_entries(
            _config(pool=["5269"]), gifts, _names(), {}, {}
        )
        self.assertNotIn("{mc}", entries[0]["action_label"])
        self.assertNotIn("rtp", entries[0]["action_label"])

    def test_invalid_pool_entries_are_excluded(self):
        # 5487 has an empty bundle, 9999 not configured, GlobalActions forbidden
        entries = gift_roulette.resolve_entries(
            _config(pool=["5487", "9999", "GlobalActions", "5269"]),
            _gifts(), _names(), _descriptions(), _catalog(),
        )
        self.assertEqual([e["gift_id"] for e in entries], ["5269"])

    def test_legacy_name_keyed_gift_resolves_via_catalog_name(self):
        # "tiktok" gift is configured under its lowercase name, not its id 5269.
        gifts = dict(_gifts())
        gifts.pop("5269")  # force legacy resolution path
        entries = gift_roulette.resolve_entries(
            _config(pool=["5269"]), gifts, _names(), _descriptions(), _catalog()
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["label"], "A baby husk army appears")

    def test_entries_capped_at_100(self):
        gifts = {str(i): [{"type": "minecraft", "command": f"c{i}"}] for i in range(150)}
        cfg = gift_roulette.normalize_config({"pool": [str(i) for i in range(150)]})
        entries = gift_roulette.resolve_entries(cfg, gifts, {}, {}, {})
        self.assertEqual(len(entries), 100)

    def test_disabled_config_still_resolves_for_preview(self):
        entries = gift_roulette.resolve_entries(
            _config(enabled=False), _gifts(), _names(), _descriptions(), _catalog()
        )
        self.assertEqual(len(entries), 2)


class _FixedRng:
    """Deterministic rng: always picks a fixed index."""

    def __init__(self, pick=0):
        self.pick = pick

    def randrange(self, n):
        return min(self.pick, n - 1)


class _FixedPick:
    def randrange(self, n):
        return 0


def _prepared(*, trigger_gift_id="5655", user="Viewer", spin_ms=5000,
              hold_ms=4000, rng=None, now=1000.0):
    cfg = gift_roulette.normalize_config({
        "enabled": True, "trigger_gift_id": trigger_gift_id,
        "spin_ms": spin_ms, "hold_ms": hold_ms, "cooldown_ms": 2000,
        "pool": ["5269", "5333"],
    })
    gifts = {
        "5269": [{"type": "minecraft", "command": "a {user}"}],
        "5333": [{"type": "sound", "file": "b.mp3"}],
    }
    catalog = {
        "5269": {"id": 5269, "name": "tiktok", "diamond_count": 1, "icon": ""},
        "5333": {"id": 5333, "name": "silverfish platoon", "diamond_count": 10, "icon": ""},
    }
    trigger = {"gift_id": trigger_gift_id, "gift_name": "Rose", "user": user,
               "repeat_count": "3", "total_coin": "3", "mc": "KhitoMC",
               "amount": "3", "asset_url": ""}
    return gift_roulette.prepare_spin(
        cfg, gifts, {}, {}, catalog, trigger,
        source="live", profile="default", now=now, rng=rng or _FixedPick(),
    )


class _FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class PrepareSpinTest(unittest.TestCase):
    def _prepare(self, *, pool=("5269", "5333"), rng=None, trigger_ctx=None,
                 gifts=None, catalog=None, **cfg_overrides):
        cfg = gift_roulette.normalize_config({
            "enabled": True, "trigger_gift_id": "5655",
            "spin_ms": 5000, "hold_ms": 4000, "cooldown_ms": 2000,
            "pool": list(pool), **cfg_overrides,
        })
        return gift_roulette.prepare_spin(
            cfg, gifts or _gifts(), {}, {}, catalog or _catalog(),
            trigger_ctx or self._trigger_ctx(),
            source="live", profile="default", now=1000.0, rng=rng or _FixedRng(0),
        )

    @staticmethod
    def _trigger_ctx():
        return {
            "gift_name": "Rose",
            "repeat_count": "20",      # streaked trigger; must NOT scale the winner
            "user": "StreakyViewer",
            "total_coin": "20",
            "mc": "KhitoMC",
            "amount": "20",
            "gift_id": "5655",
            "asset_url": "http://x/anim.mp4",
        }

    def test_prepared_winner_bundle_is_full_gift_bundle(self):
        spin = self._prepare(rng=_FixedRng(0))  # winner = first entry 5269
        self.assertEqual(spin.winner_id, "5269")
        self.assertEqual(len(spin.winner_actions), 2)  # BOTH commands of 5269
        self.assertEqual(
            spin.winner_actions[0]["command"],
            "spawnmob {mc} {amount} baby husk {user}",
        )
        self.assertEqual(
            spin.winner_actions[1]["command"],
            "titlecustom {user} {amount} Baby Husk",
        )

    def test_winner_context_contract(self):
        spin = self._prepare(rng=_FixedRng(1))  # winner = 5333, 10 coins
        ctx = spin.winner_context
        self.assertEqual(ctx["gift_id"], "5333")
        self.assertEqual(ctx["amount"], "1")           # fixed, NOT trigger's 20
        self.assertEqual(ctx["repeat_count"], "1")
        self.assertEqual(ctx["total_coin"], "10")      # winner catalog price
        self.assertEqual(ctx["user"], "StreakyViewer") # preserved
        self.assertEqual(ctx["mc"], "KhitoMC")         # preserved
        self.assertEqual(ctx["trigger_gift_id"], "5655")
        self.assertEqual(ctx["trigger_repeat_count"], "20")
        self.assertEqual(ctx["asset_url"], "")

    def test_actions_snapshot_is_deep_and_immutable(self):
        gifts = _gifts()
        original = copy.deepcopy(gifts["5269"])
        spin = self._prepare(rng=_FixedRng(0), gifts=gifts)
        # mutate the source config after preparation
        gifts["5269"][0]["command"] = "HACKED {user}"
        # snapshot unchanged
        self.assertEqual(spin.winner_actions[0]["command"], original[0]["command"])
        # mutating the snapshot does not affect the source either
        spin.winner_actions[0]["command"] = "MUTATED"
        self.assertEqual(gifts["5269"][0]["command"], "HACKED {user}")

    def test_reel_invariants(self):
        spin = self._prepare(rng=_FixedRng(0))
        reel = spin.public_state["reel"]
        self.assertEqual(len(reel), gift_roulette.MAX_REEL_ROWS)
        self.assertTrue(all(0 <= i < 2 for i in reel))
        self.assertEqual(reel[-1], spin.public_state["winner_index"])

    def test_public_state_contains_no_actions_or_secrets(self):
        spin = self._prepare()
        blob = spin.public_state
        self.assertNotIn("actions", blob)
        self.assertNotIn("commands", blob)
        self.assertNotIn("winner_actions", blob)
        serialized = str(blob)
        self.assertNotIn("spawnmob", serialized)
        self.assertNotIn("titlecustom", serialized)

    def test_pool_under_two_raises(self):
        with self.assertRaises(gift_roulette.RouletteValidationError):
            self._prepare(pool=["5269"])

    def test_disabled_raises(self):
        with self.assertRaises(gift_roulette.RouletteValidationError):
            self._prepare(enabled=False)

    def test_timing_fields_derive_from_config(self):
        spin = self._prepare(spin_ms=6000, hold_ms=2000)
        st = spin.public_state
        self.assertAlmostEqual(st["lands_at"], 1006.0)  # 1000 + 6.0s
        self.assertAlmostEqual(st["hide_at"], 1008.0)   # lands + 2.0s

    def test_spin_ids_are_unique(self):
        a = self._prepare()
        b = self._prepare()
        self.assertNotEqual(a.spin_id, b.spin_id)

    def test_source_must_be_live_or_test(self):
        spin = self._prepare()  # default live
        self.assertEqual(spin.public_state["source"], "live")


async def _sleep_zero():
    return None


class RouletteRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = str(Path(self.tmp.name) / "roulette_state.json")
        self.clock = _FakeClock()
        self.runtime = gift_roulette.RouletteRuntime(self.state_path, clock=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_reservation_accepted_and_persisted(self):
        p = _prepared()
        accepted, reason = self.runtime.try_reserve(p, cooldown_ms=2000)
        self.assertTrue(accepted, reason)
        self.assertEqual(reason, "ok")
        self.runtime.mark_reserved_started()
        on_disk = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        self.assertEqual(on_disk["status"], "spinning")
        self.assertEqual(on_disk["spin_id"], p.spin_id)
        self.assertNotIn("winner_actions", on_disk)  # never persisted

    def test_second_reservation_while_spinning_is_busy(self):
        self.runtime.try_reserve(_prepared(), cooldown_ms=2000)
        accepted, reason = self.runtime.try_reserve(_prepared(), cooldown_ms=2000)
        self.assertFalse(accepted)
        self.assertEqual(reason, "busy")

    def test_cooldown_rejects_until_elapsed(self):
        p1 = _prepared()
        self.runtime.try_reserve(p1, cooldown_ms=2000)
        # fast-forward: spin done + landed
        self.clock.advance(5.0)
        self.runtime._write_land_state()
        # still inside 2s cooldown after land; different viewer so the
        # duplicate-final guard does not fire first
        accepted, reason = self.runtime.try_reserve(
            _prepared(now=self.clock.t, user="OtherViewer"), cooldown_ms=2000)
        self.assertFalse(accepted)
        self.assertEqual(reason, "cooldown")
        self.clock.advance(2.1)
        accepted, reason = self.runtime.try_reserve(
            _prepared(now=self.clock.t, user="OtherViewer"), cooldown_ms=2000)
        self.assertTrue(accepted, reason)

    def test_landing_sets_state_and_dispatch(self):
        p = _prepared()
        self.runtime.try_reserve(p, cooldown_ms=2000)
        self.runtime.mark_reserved_started()

        dispatched = []

        async def fake_bundle(actions, context):
            dispatched.append((actions, context))

        async def run():
            await self.runtime.run_reserved(p, fake_bundle, sleep=lambda s: _sleep_zero())

        asyncio.run(run())
        self.assertEqual(len(dispatched), 1)
        actions, ctx = dispatched[0]
        self.assertEqual(len(actions), 1)          # full winner bundle
        self.assertEqual(ctx["user"], "Viewer")
        state = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        self.assertEqual(state["dispatch_status"], "dispatched")

    def test_dispatch_failure_marks_failed(self):
        p = _prepared()
        self.runtime.try_reserve(p, cooldown_ms=2000)
        self.runtime.mark_reserved_started()

        async def failing_bundle(actions, context):
            raise RuntimeError("rcon down")

        async def run():
            with self.assertRaises(RuntimeError):
                await self.runtime.run_reserved(p, failing_bundle, sleep=lambda s: _sleep_zero())

        asyncio.run(run())
        state = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        self.assertEqual(state["dispatch_status"], "failed")

    def test_cancellation_marks_cancelled_without_execution(self):
        p = _prepared(spin_ms=10000)
        self.runtime.try_reserve(p, cooldown_ms=2000)
        self.runtime.mark_reserved_started()

        called = []

        async def never(actions, context):
            called.append(1)

        async def run():
            task = asyncio.create_task(self.runtime.run_reserved(p, never))
            await asyncio.sleep(0.01)  # let it start sleeping
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run())
        self.assertEqual(called, [])
        state = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        self.assertEqual(state["dispatch_status"], "cancelled")

    def test_stale_spinning_state_is_swept_cancelled(self):
        Path(self.state_path).write_text(json.dumps({
            "schema": 1, "spin_id": "deadbeef", "source": "live",
            "profile": "default", "status": "spinning",
            "started_at": 1.0, "lands_at": 6.0, "hide_at": 10.0,
            "trigger": {"gift_id": "5655", "gift_name": "Rose", "user": "X"},
            "entries": [], "reel": [], "winner_index": 0,
            "dispatch_status": "pending",
        }), encoding="utf-8")
        swept = self.runtime.sweep_stale()
        self.assertTrue(swept)
        state = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "cancelled")
        self.assertEqual(state["dispatch_status"], "cancelled")

    def test_expired_state_reads_idle(self):
        p = _prepared(now=1000.0)
        self.runtime.try_reserve(p, cooldown_ms=2000)
        self.runtime.mark_reserved_started()
        self.clock.advance(9.1)  # past lands_at(1005) + hold(4) = 1009
        self.assertEqual(self.runtime.public_state(now=self.clock.t)["status"], "idle")
        self.assertEqual(self.runtime.public_state_from_disk(now=self.clock.t)["status"], "idle")

    def test_duplicate_final_guard(self):
        p1 = _prepared()
        self.runtime.try_reserve(p1, cooldown_ms=0)
        self.runtime.mark_reserved_started()
        self.runtime._write_land_state()
        self.runtime._write_dispatch_status("dispatched")
        # same trigger gift+user within TTL
        p2 = _prepared(now=self.clock.t)
        accepted, reason = self.runtime.try_reserve(p2, cooldown_ms=0)
        self.assertFalse(accepted)
        self.assertEqual(reason, "duplicate_final")

    def test_terminal_state_frees_slot_for_next_spin(self):
        p1 = _prepared()
        self.runtime.try_reserve(p1, cooldown_ms=0)
        self.runtime.mark_reserved_started()
        self.clock.advance(0.01)
        self.runtime._write_dispatch_status("dispatched")
        accepted, _ = self.runtime.try_reserve(_prepared(now=self.clock.t), cooldown_ms=0)
        self.assertTrue(accepted)


if __name__ == "__main__":
    unittest.main()
