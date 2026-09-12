"""Shared bot connection-state bridge between the bot process and the dashboard.

The bot runs as a separate `--run-bot` subprocess, so the dashboard cannot read
its in-memory state directly. The bot writes a small JSON state file; the
dashboard reads it (via `read_status()`) and merges it with subprocess-liveness
checks to render a truthful connection status.

States: starting, connecting, connected, reconnecting, disconnected, failed,
stopped, ended.
"""

import json
import os
import time as _time

from utils import save_json

# Written by the bot, read by the dashboard. Lives under data/ like other runtime state.
STATUS_FILENAME = "bot_status.json"


def _status_path(paths) -> str:
    """Resolve the status file path using the project's centralized paths helper.

    `paths` is injected lazily so this module never hardcodes a frozen/base-dir
    assumption and both the bot and the dashboard resolve the same file.
    """
    return paths.data(STATUS_FILENAME)


def read_status(paths):
    """Read the last-known bot connection state (never raises).

    Returns a dict, or {} when the file is missing/corrupt. The caller is
    responsible for merging with process-liveness.
    """
    try:
        path = _status_path(paths)
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_status(paths, state, *, room_id=None, username=None, error=None, attempt=None, max_attempts=None, extra=None):
    """Persist the bot's current connection state atomically-ish (never raises).

    `state` is one of the canonical states; optional fields enrich the dashboard
    display. The error string is intentionally capped/redacted by the caller.
    """
    try:
        payload = {
            "state": state,
            "ts": _time.time(),
            "room_id": room_id,
            "username": username,
            "error": error,
            "attempt": attempt,
            "max_attempts": max_attempts,
        }
        if isinstance(extra, dict):
            payload.update(extra)
        save_json(_status_path(paths), payload)
    except Exception:
        pass
