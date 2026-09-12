"""Offline gift-event simulation for the dashboard Gifts tab.

The simulator intentionally uses the same action dispatcher as live TikTok gift
handling, while building its context from explicit dashboard inputs. It does
not write gift history, points, rankings, streak state, or overlays.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import requests
from mcrcon import MCRcon

from actions import execute_actions


SendMinecraftCommand = Callable[[str], Awaitable[None]]


def _gift_actions(config: dict, gift_key: str) -> tuple[list, list]:
    gifts = config.get("Gifts") or {}
    key = str(gift_key).strip()
    if key.lower() == "globalactions":
        raise ValueError("GlobalActions is not a gift")
    if key not in gifts:
        raise ValueError(f"Gift {key!r} is not configured")

    global_actions = gifts.get("GlobalActions") or []
    specific_actions = gifts.get(key) or []
    if not isinstance(global_actions, list) or not isinstance(specific_actions, list):
        raise ValueError("Configured gift actions must be lists")
    return global_actions, specific_actions


def _context(config: dict, gift_key: str, user: object, amount: object, gift_meta: dict | None) -> dict:
    clean_user = str(user).strip()
    if not clean_user:
        raise ValueError("User is required")
    if len(clean_user) > 100:
        raise ValueError("User must be 100 characters or fewer")

    try:
        repeat_count = int(str(amount))
    except (TypeError, ValueError) as exc:
        raise ValueError("Amount must be a whole number") from exc
    if repeat_count < 1 or repeat_count > 10_000:
        raise ValueError("Amount must be between 1 and 10000")

    meta = gift_meta or {}
    names = config.get("GiftNames") or {}
    gift_name = str(meta.get("name") or names.get(gift_key) or gift_key)
    try:
        diamond_count = max(0, int(meta.get("diamond_count") or 0))
    except (TypeError, ValueError):
        diamond_count = 0
    settings = config.get("Settings") or {}

    return {
        "gift_name": gift_name,
        "repeat_count": str(repeat_count),
        "user": clean_user,
        "total_coin": str(repeat_count * diamond_count),
        "mc": str(settings.get("MinecraftUsername") or ""),
        "amount": str(repeat_count),
        "gift_id": str(gift_key),
        "asset_url": "",
    }


async def simulate_gift(
    config: dict,
    gift_key: str,
    user: object,
    amount: object,
    gift_meta: dict | None = None,
    send_mc_command: SendMinecraftCommand | None = None,
) -> dict:
    """Run one completed gift exactly through global + gift-specific actions."""
    key = str(gift_key).strip()
    global_actions, specific_actions = _gift_actions(config, key)
    ctx = _context(config, key, user, amount, gift_meta)

    batches = [actions for actions in (global_actions, specific_actions) if actions]

    # A roulette spin is the one action type the simulator cannot run: it needs
    # the live bot's RouletteRuntime, and firing one from the dashboard while the
    # bot is live would double-fire its state writes — the exact hazard
    # /api/roulette/test refuses with a 409. Report it instead of counting it as
    # executed, so a simulated gift never looks like it spun when it did not.
    skipped = [
        action.get("type")
        for batch in batches
        for action in batch
        if isinstance(action, dict) and action.get("type") == "roulette"
    ]

    await asyncio.gather(*(
        execute_actions(actions, dict(ctx), send_mc_command)
        for actions in batches
    ))

    result = {
        "status": "success",
        "gift": ctx["gift_name"],
        "actions": sum(len(actions) for actions in batches),
        "batches": len(batches),
        "context": ctx,
    }
    if skipped:
        result["skipped_actions"] = skipped
        result["note"] = (
            "Roulette spins are not started by the simulator. Use the Roulette "
            "tab's Test Spin, or trigger a live Roulette action."
        )
    return result


def build_dashboard_sender(config: dict, log: Callable[[str], None] | None = None) -> SendMinecraftCommand:
    """Build an async Minecraft sender from a live config snapshot."""
    settings = config.get("Settings") or {}
    connector = str(settings.get("ConnectorType") or "rcon").lower()

    def emit(message: str) -> None:
        if log:
            log(message)

    def send_sync(command: str) -> None:
        emit(f"[→] {command}")
        if connector == "forge":
            cfg = config.get("Forge") or {}
            host = str(cfg.get("Host") or "127.0.0.1")
            port = int(cfg.get("Port") or 5942)
            response = requests.post(
                f"http://{host}:{port}/command",
                json={"password": str(cfg.get("Password") or ""), "command": command},
                timeout=5,
            )
            response.raise_for_status()
            try:
                output = response.json().get("output", "")
            except ValueError:
                output = response.text
            emit(output or "[ok]")
            return

        if connector == "servertap":
            cfg = config.get("ServerTap") or {}
            host = str(cfg.get("Host") or "127.0.0.1")
            port = int(cfg.get("Port") or 4567)
            response = requests.post(
                f"http://{host}:{port}/api/execute",
                json={"apiKey": str(cfg.get("ApiKey") or ""), "command": command},
                timeout=5,
            )
            response.raise_for_status()
            try:
                body = response.json()
                output = body.get("output", "") or body.get("response", "")
            except ValueError:
                output = response.text
            emit(output or "[ok]")
            return

        cfg = config.get("Rcon") or {}
        host = str(cfg.get("Host") or "127.0.0.1")
        port = int(cfg.get("Port") or 25575)
        password = str(cfg.get("Password") or "")
        with MCRcon(host, password, port=port) as client:
            output = client.command(command)
        if output:
            emit(output)

    async def send(command: str) -> None:
        try:
            await asyncio.to_thread(send_sync, command)
        except Exception as exc:
            emit(f"[ERR] gift simulation: {exc}")
            raise

    return send
