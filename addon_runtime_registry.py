"""Live lifecycle registry for add-on-owned background runtimes."""
from __future__ import annotations

from threading import RLock
from typing import Any

_lock = RLock()
_runtimes: dict[str, Any] = {}
_enabled: dict[str, bool] = {}


def register(addon_id: str, runtime: Any, *, enabled: bool) -> Any:
    """Register one authoritative runtime and apply its current enabled state."""
    addon_id = str(addon_id)
    enabled = bool(enabled)
    with _lock:
        current = _runtimes.get(addon_id)
        if current is runtime:
            return runtime
        if current is not None:
            current.set_runtime_enabled(False)
        _runtimes[addon_id] = runtime
        _enabled[addon_id] = enabled
        runtime.set_runtime_enabled(enabled)
        return runtime


def unregister(addon_id: str) -> Any | None:
    with _lock:
        runtime = _runtimes.pop(str(addon_id), None)
        _enabled.pop(str(addon_id), None)
        if runtime is not None:
            runtime.set_runtime_enabled(False)
        return runtime


def set_enabled(addon_id: str, enabled: bool) -> bool:
    """Apply a persisted enable change immediately; false means no runtime owns it."""
    addon_id = str(addon_id)
    enabled = bool(enabled)
    with _lock:
        runtime = _runtimes.get(addon_id)
        if runtime is None:
            return False
        if _enabled.get(addon_id) == enabled:
            return True
        runtime.set_runtime_enabled(enabled)
        _enabled[addon_id] = enabled
        return True


def set_config(addon_id: str, config: dict) -> bool:
    """Apply add-on configuration live when its runtime supports it."""
    addon_id = str(addon_id)
    with _lock:
        runtime = _runtimes.get(addon_id)
        if runtime is None:
            return False
        setter = getattr(runtime, "set_runtime_config", None)
        if setter is None:
            return False
        setter(dict(config or {}))
        return True


def get(addon_id: str) -> Any | None:
    with _lock:
        return _runtimes.get(str(addon_id))


def is_enabled(addon_id: str) -> bool:
    with _lock:
        return bool(_enabled.get(str(addon_id), False))


def clear() -> None:
    """Stop and forget all runtimes. Primarily used for deterministic teardown."""
    with _lock:
        ids = list(_runtimes)
    for addon_id in ids:
        unregister(addon_id)
