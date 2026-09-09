"""Gift Roulette engine — gift-level random event selector.

Chooses one configured TikTok gift as a spin winner and prepares its ENTIRE
configured action bundle for execution through the existing dispatcher. This is
deliberately NOT the single-line `random` sub-action picker in actions.py.

This module is intentionally free of Flask, TikTokLive, and minecraft_main
imports: both the bot process and the dashboard process use it, and tests stay
cheap without those heavyweight dependencies. The caller supplies everything:
gifts mapping, names, descriptions, catalog rows, clock, rng, state path.

Doctrine (.hermes/plans/roulette-randomizer.md):
- winner bundle is deep-copied at spin start (immutable for that spin);
- winner context uses winner identity, amount=1, winner catalog price;
- state file holds display data only — never commands or secrets;
- at most three atomic writes per spin (start, land, cleanup).
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field

STATE_SCHEMA = 1
MAX_POOL_ENTRIES = 100
MAX_REEL_ROWS = 25
DUPLICATE_FINAL_TTL_SECONDS = 30.0

DEFAULT_ROULETTE_CONFIG = {
    "enabled": False,
    "trigger_gift_id": "",
    "spin_ms": 5000,
    "hold_ms": 4000,
    "cooldown_ms": 2000,
    "pool": [],
}

# (min, max, default) per timing knob, enforced by normalize_config.
_TIMING_LIMITS = {
    "spin_ms": (2000, 10000),
    "hold_ms": (1000, 10000),
    "cooldown_ms": (0, 60000),
}


def _clamp_int(value, lo: int, hi: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < lo:
        return lo
    if number > hi:
        return hi
    return number


def normalize_config(raw: object) -> dict:
    """Coerce a raw profile ``Roulette`` block into the canonical schema.

    Unknown fields are dropped, ids become strings, timing is clamped,
    duplicates removed preserving order, GlobalActions rejected.
    Absent/malformed input returns the disabled default.
    """
    cfg = dict(DEFAULT_ROULETTE_CONFIG)
    cfg["pool"] = []
    if not isinstance(raw, dict):
        return cfg

    cfg["enabled"] = bool(raw.get("enabled", False))

    trigger = str(raw.get("trigger_gift_id", "") or "").strip()
    if trigger == "GlobalActions":
        trigger = ""
    cfg["trigger_gift_id"] = trigger

    for key, (lo, hi) in _TIMING_LIMITS.items():
        raw_value = raw.get(key, DEFAULT_ROULETTE_CONFIG[key])
        if isinstance(raw_value, bool) or raw_value is None:
            # bool is an int subclass; reject it explicitly so True != 1ms
            if raw_value is None:
                cfg[key] = DEFAULT_ROULETTE_CONFIG[key]
                continue
            cfg[key] = DEFAULT_ROULETTE_CONFIG[key]
            continue
        cfg[key] = _clamp_int(raw_value, lo, hi, DEFAULT_ROULETTE_CONFIG[key])

    pool: list = []
    seen = set()
    for item in raw.get("pool", []) or []:
        gift_id = str(item).strip()
        if not gift_id or gift_id == "GlobalActions" or gift_id in seen:
            continue
        seen.add(gift_id)
        pool.append(gift_id)
        if len(pool) >= MAX_POOL_ENTRIES:
            break
    cfg["pool"] = pool
    return cfg


def build_catalog_index(rows: list) -> dict:
    """Map string gift id -> catalog row from the flat available_gifts.json list."""
    index = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        gift_id = row.get("id")
        if gift_id in (None, ""):
            continue
        index[str(gift_id)] = row
    return index


def _resolve_gift_key(gift_id: str, gifts: dict, catalog_by_id: dict) -> str | None:
    """Mirror on_gift's lookup precedence: exact id first, then lowercase name.

    Returns the key present in ``gifts`` or None. Legacy profiles key some
    gifts by lowercase display name instead of numeric id.
    """
    if gift_id in gifts:
        return gift_id
    row = catalog_by_id.get(gift_id)
    if row:
        name_key = str(row.get("name") or "").strip().lower()
        if name_key and name_key in gifts:
            return name_key
    return None


def _display_label(gift_id: str, names: dict, descriptions: dict, catalog_by_id: dict) -> str:
    """GiftDescriptions -> GiftNames -> catalog name -> Gift #id. Never commands."""
    desc = str(descriptions.get(gift_id, "") or "").strip()
    if desc:
        return desc
    name = str(names.get(gift_id, "") or "").strip()
    if name:
        return name
    row = catalog_by_id.get(gift_id)
    if row:
        cat_name = str(row.get("name") or "").strip()
        if cat_name:
            return cat_name
    return f"Gift #{gift_id}"


def _action_label(actions: list, gift_id: str, descriptions: dict,
                 names: dict, catalog_by_id: dict) -> str:
    """Human-readable action name for the reel.

    Khito maintains this text in the gift list as the description — that wins
    whenever present ("the action description"). Otherwise the titlecustom/
    title text (the event he configured), then a minecraft command verb, then
    GiftNames, catalog name, Gift #id. Never leaks raw placeholders like
    {user}/{mc}/{amount} or raw command text.
    """
    desc = str((descriptions or {}).get(gift_id, "") or "").strip()
    if desc:
        return desc
    import re as _re
    best_title = ""
    best_cmd = ""
    for action in actions if isinstance(actions, list) else []:
        if not isinstance(action, dict):
            continue
        cmd = str(action.get("command", "") or "")
        if not best_title and cmd.lower().startswith(("titlecustom", "title")):
            parts = cmd.split()
            # Last non-placeholder token is the title text Khito wrote.
            tokens = [t for t in parts[1:] if not _re.search(r"\{", t)]
            if tokens:
                best_title = " ".join(tokens).strip("'\"")
        if not best_cmd:
            for verb in ("spawnmob", "summon", "execute", "playsound", "effect", "give"):
                if verb in cmd.lower():
                    best_cmd = verb
                    break
    if best_title:
        return best_title
    if best_cmd:
        return best_cmd.capitalize()
    name = str((names or {}).get(gift_id, "") or "").strip()
    if name:
        return name
    row = catalog_by_id.get(gift_id)
    if row:
        cat_name = str(row.get("name") or "").strip()
        if cat_name:
            return cat_name
    return f"Gift #{gift_id}"


def resolve_entries(config: dict, gifts: dict, gift_names: dict,
                    descriptions: dict, catalog_by_id: dict) -> list:
    """Resolve the configured pool into display entries for overlay/dashboard.

    Excludes unconfigured, empty-bundle, and GlobalActions entries. Returns a
    list of {gift_id, label, icon_url, diamond_count} capped at MAX_POOL_ENTRIES.
    Pool identity stays the real TikTok gift ID even when the actions live
    under a legacy lowercase-name key.
    """
    entries = []
    seen = set()
    pool = config.get("pool", []) if isinstance(config, dict) else []
    for gift_id in pool[:MAX_POOL_ENTRIES]:
        if not isinstance(gift_id, str) or not gift_id or gift_id in seen:
            continue
        if gift_id == "GlobalActions":
            # Defense in depth: normalize_config strips it, but resolve must
            # also reject it for un-normalized dicts (dashboard paths).
            continue
        seen.add(gift_id)
        action_key = _resolve_gift_key(gift_id, gifts, catalog_by_id)
        if action_key is None:
            continue
        actions = gifts.get(action_key)
        if not isinstance(actions, list) or not actions:
            continue
        row = catalog_by_id.get(gift_id) or {}
        entries.append({
            "gift_id": gift_id,
            "label": _display_label(gift_id, gift_names or {}, descriptions or {}, catalog_by_id),
            # Action name for the overlay reel: the event Khito configured
            # (title text), not the gift name. Kept separate from `label` so
            # Gift Card Studio text doctrine (descriptions drive visible text)
            # is untouched.
            "action_label": _action_label(
                actions, gift_id, descriptions or {}, gift_names or {}, catalog_by_id
            ),
            "icon_url": str(row.get("icon") or ""),
            "diamond_count": int(row.get("diamond_count") or 0),
        })
        if len(entries) >= MAX_POOL_ENTRIES:
            break
    return entries


# ── Spin preparation ────────────────────────────────────────────────────────


class RouletteValidationError(Exception):
    """Raised when a spin cannot be prepared from the current config."""


@dataclass(frozen=True)
class PreparedSpin:
    spin_id: str
    source: str                      # "live" | "test"
    profile: str
    winner_id: str
    winner_actions: tuple            # deep-copied action dicts, immutable order
    winner_context: dict
    public_state: dict               # the state-file payload (no actions/secrets)
    winner_label: str
    config_snapshot: dict = field(repr=False)


def _build_reel(entry_count: int, winner_index: int, rng) -> list:
    """Decorative reel sequence, always ending on the winner."""
    if entry_count <= 0:
        return []
    if entry_count == 1:
        return [0] * MAX_REEL_ROWS
    rows = []
    for _ in range(MAX_REEL_ROWS - 1):
        idx = rng.randrange(entry_count)
        rows.append(idx)
    rows.append(winner_index)
    return rows


def prepare_spin(config_snapshot: dict, gifts_snapshot: dict,
                 gift_names: dict, descriptions: dict, catalog_by_id: dict,
                 trigger_context: dict, *, source: str = "live",
                 profile: str = "", now: float | None = None, rng=None) -> PreparedSpin:
    """Prepare everything a spin needs, without touching runtime state.

    Deep-copies the winner's full action bundle so profile edits or switches
    during the spin cannot alter the displayed outcome. Winner context follows
    plan §3.4: winner identity, amount=1, winner catalog price as total_coin,
    user/mc preserved from the trigger, trigger_* fields for extra context.
    """
    if not isinstance(config_snapshot, dict):
        raise RouletteValidationError("roulette config must be a mapping")
    if not config_snapshot.get("enabled"):
        raise RouletteValidationError("roulette is disabled")

    entries = resolve_entries(config_snapshot, gifts_snapshot, gift_names,
                              descriptions, catalog_by_id)
    if len(entries) < 2:
        raise RouletteValidationError("pool needs at least 2 valid configured gifts")

    rng = rng or secrets.SystemRandom()
    now = time.time() if now is None else now

    winner = entries[rng.randrange(len(entries))]
    winner_id = winner["gift_id"]
    action_key = _resolve_gift_key(winner_id, gifts_snapshot, catalog_by_id)
    if action_key is None:
        raise RouletteValidationError(f"winning gift {winner_id} is not configured")

    bundle = copy.deepcopy(gifts_snapshot.get(action_key) or [])
    if not isinstance(bundle, list) or not bundle:
        raise RouletteValidationError(f"winning gift {winner_id} has no action bundle")

    trigger_ctx = trigger_context if isinstance(trigger_context, dict) else {}
    spin_ms = int(config_snapshot.get("spin_ms", DEFAULT_ROULETTE_CONFIG["spin_ms"]))
    hold_ms = int(config_snapshot.get("hold_ms", DEFAULT_ROULETTE_CONFIG["hold_ms"]))

    started_at = float(now)
    lands_at = started_at + (spin_ms / 1000.0)
    hide_at = lands_at + (hold_ms / 1000.0)

    winner_context = {
        # winner identity
        "gift_id": winner_id,
        "gift_name": str(winner["label"]),
        "repeat_count": "1",
        "amount": "1",
        "total_coin": str(int(winner.get("diamond_count") or 0)),
        "asset_url": "",
        # preserved from the real trigger
        "user": str(trigger_ctx.get("user", "")),
        "mc": str(trigger_ctx.get("mc", "")),
        # nonbreaking extras
        "trigger_gift_id": str(trigger_ctx.get("gift_id", "")),
        "trigger_gift_name": str(trigger_ctx.get("gift_name", "")),
        "trigger_repeat_count": str(trigger_ctx.get("repeat_count", "")),
        "trigger_total_coin": str(trigger_ctx.get("total_coin", "")),
    }

    reel = _build_reel(len(entries), entries.index(winner), rng)

    public_state = {
        "schema": STATE_SCHEMA,
        "spin_id": uuid.uuid4().hex,
        "source": source if source in ("live", "test") else "live",
        "profile": str(profile or ""),
        "status": "spinning",
        "started_at": started_at,
        "lands_at": lands_at,
        "hide_at": hide_at,
        "trigger": {
            "gift_id": str(trigger_ctx.get("gift_id", "")),
            "gift_name": str(trigger_ctx.get("gift_name", "")),
            "user": str(trigger_ctx.get("user", "")),
        },
        "entries": entries,
        "reel": reel,
        "winner_index": entries.index(winner),
        "dispatch_status": "pending",
    }

    return PreparedSpin(
        spin_id=public_state["spin_id"],
        source=public_state["source"],
        profile=public_state["profile"],
        winner_id=winner_id,
        winner_actions=tuple(copy.deepcopy(bundle)),
        winner_context=winner_context,
        public_state=public_state,
        winner_label=winner["label"],
        config_snapshot=copy.deepcopy(config_snapshot),
    )


# ── Runtime: reservation, state persistence, landing ────────────────────────


class RouletteRuntime:
    """Single active spin per process with cooldown and atomic state file.

    Not a queue: rejected triggers fall back to their normal gift actions.
    Stale state from a prior process never executes actions — a startup sweep
    marks it cancelled before the engine accepts new spins.
    """

    def __init__(self, state_path: str, *, clock=time.time):
        self._state_path = state_path
        self._clock = clock
        self._lock = threading.Lock()
        self._state: dict | None = None      # in-memory current spin state
        self._active_cooldown_ms: int = 0
        self._cooldown_until: float = 0.0    # monotonic wall-clock seconds
        self._last_completed: tuple | None = None  # duplicate-final dedupe
        self._last_completed_at: float = 0.0

    # -- persistence helpers (off-loop callers use asyncio.to_thread) --------

    def _read_state_file(self) -> dict | None:
        try:
            with open(self._state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def _write_state_file(self, state: dict) -> None:
        """Atomic temp+replace write. Never uses utils.save_json (direct write)."""
        tmp_path = self._state_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp_path, self._state_path)

    def _write_active_state(self) -> None:
        if self._state is not None:
            try:
                self._write_state_file(self._state)
            except OSError:
                # State loss must never crash the gift path; overlay simply
                # keeps showing the last good state.
                pass

    # -- lifecycle ----------------------------------------------------------

    def sweep_stale(self) -> bool:
        """Cancel leftover 'spinning' state from a prior process.

        Never executes the pending winner. Returns True when a sweep happened.
        """
        with self._lock:
            disk = self._read_state_file()
            if disk and disk.get("status") == "spinning":
                disk["status"] = "cancelled"
                disk["dispatch_status"] = "cancelled"
                try:
                    self._write_state_file(disk)
                except OSError:
                    pass
                self._state = None
                return True
            self._state = None
            return False

    def try_reserve(self, prepared: PreparedSpin, cooldown_ms: int) -> tuple:
        """Atomically accept or reject a spin reservation. No queue.

        Returns (accepted: bool, reason: str). Reasons: ok, busy, cooldown,
        duplicate_final. On accept the in-memory state is set BEFORE returning
        so a second caller can never win the same slot.
        """
        now = self._clock()
        with self._lock:
            if self._state is not None and self._state.get("status") == "spinning":
                return (False, "busy")
            if now < self._cooldown_until:
                return (False, "cooldown")

            # Duplicate final-summary guard (plan §4.3)
            trigger_ctx = prepared.public_state.get("trigger") or {}
            key = (trigger_ctx.get("gift_id", ""), trigger_ctx.get("user", ""))
            if self._last_completed and self._last_completed == key:
                age = now - self._last_completed_at
                if age < DUPLICATE_FINAL_TTL_SECONDS:
                    return (False, "duplicate_final")

            state = dict(prepared.public_state)
            state["started_at"] = now
            state["lands_at"] = now + (int(prepared.config_snapshot.get("spin_ms", 5000)) / 1000.0)
            state["hide_at"] = state["lands_at"] + (
                int(prepared.config_snapshot.get("hold_ms", 4000)) / 1000.0)
            self._state = state
            self._active_cooldown_ms = int(cooldown_ms)
            return (True, "ok")

    def mark_reserved_started(self) -> None:
        """Persist the freshly reserved state. Called (off-loop) after reserve."""
        with self._lock:
            self._write_active_state()

    def _derive(self, state: dict | None, *, now: float | None = None) -> dict:
        now = self._clock() if now is None else now
        if not state:
            return {"status": "idle"}
        # Expired spinning AND landed states read as idle once hide_at passes.
        if state.get("status") in ("spinning", "landed"):
            hide_at = float(state.get("hide_at", 0) or 0)
            if hide_at and now > hide_at:
                return {"status": "idle"}
        return state

    def public_state(self, *, now: float | None = None) -> dict:
        with self._lock:
            return self._derive(self._state, now=now)

    def public_state_from_disk(self, *, now: float | None = None) -> dict:
        """Read the state file (for the Flask process which cannot see bot memory)."""
        with self._lock:
            return self._derive(self._read_state_file(), now=now)

    # -- landing / status persistence ---------------------------------------

    def _write_land_state(self) -> None:
        now = self._clock()
        with self._lock:
            if self._state is None or self._state.get("status") != "spinning":
                return
            self._state["status"] = "landed"
            self._cooldown_until = now + (self._active_cooldown_ms / 1000.0)
            self._last_completed = (
                (self._state.get("trigger") or {}).get("gift_id", ""),
                (self._state.get("trigger") or {}).get("user", ""),
            )
            self._last_completed_at = now
            self._write_active_state()

    def _write_dispatch_status(self, status: str) -> None:
        with self._lock:
            if self._state is None:
                return
            self._state["dispatch_status"] = status
            if status in ("dispatched", "failed", "cancelled"):
                # Terminal: persist the final state, then free the active slot
                # (cooldown governs the next accept).
                try:
                    self._write_state_file(self._state)
                except OSError:
                    pass
                self._state = None
            else:
                self._write_active_state()

    async def run_reserved(self, prepared: PreparedSpin, execute_bundle,
                           *, sleep=None) -> None:
        """Run a reserved spin: persist, sleep to land, dispatch once, persist.

        ``execute_bundle(actions, context)`` must be awaited; the CALLER binds
        the Minecraft sender (live bot: minecraft_main.execute_actions partial
        with send_minecraft_command — the Log Only-gated wrapper; dashboard
        test: a migrated sender built from gift_simulation).
        """
        if sleep is None:
            sleep = asyncio.sleep
        try:
            await sleep(max(0.0, prepared.public_state["lands_at"] - self._clock()))
            self._write_land_state()
            try:
                await execute_bundle(
                    list(prepared.winner_actions),
                    dict(prepared.winner_context),
                )
                self._write_dispatch_status("dispatched")
            except Exception:
                self._write_dispatch_status("failed")
                raise
        except asyncio.CancelledError:
            self._write_dispatch_status("cancelled")
            raise
