from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FakeWinApi:
    def __init__(self, *, already_exists: bool):
        self.already_exists = already_exists
        self.calls: list[tuple] = []

    def create_mutex(self, name: str):
        self.calls.append(("create_mutex", name))
        return 101, self.already_exists

    def create_event(self, name: str):
        self.calls.append(("create_event", name))
        return 202

    def open_event(self, name: str):
        self.calls.append(("open_event", name))
        return 303

    def set_event(self, handle: int):
        self.calls.append(("set_event", handle))
        return True

    def close_handle(self, handle: int):
        self.calls.append(("close_handle", handle))

    def activate_window(self, title: str):
        self.calls.append(("activate_window", title))
        return True


def test_second_launch_signals_primary_focuses_window_and_exits():
    from single_instance import (
        ACTIVATION_EVENT_NAME,
        APP_MUTEX_NAME,
        WINDOW_TITLE,
        acquire_single_instance,
    )

    api = FakeWinApi(already_exists=True)

    guard = acquire_single_instance(
        _platform="nt",
        _api=api,
        _sleep=lambda _seconds: None,
        _notify_timeout=0,
        _start_listener=False,
    )

    assert guard.is_primary is False
    assert ("create_mutex", APP_MUTEX_NAME) in api.calls
    assert ("open_event", ACTIVATION_EVENT_NAME) in api.calls
    assert ("set_event", 303) in api.calls
    assert ("activate_window", WINDOW_TITLE) in api.calls
    assert ("close_handle", 303) in api.calls
    assert ("close_handle", 101) in api.calls


def test_primary_launch_holds_mutex_and_creates_activation_event():
    from single_instance import ACTIVATION_EVENT_NAME, APP_MUTEX_NAME, acquire_single_instance

    api = FakeWinApi(already_exists=False)

    guard = acquire_single_instance(
        _platform="nt",
        _api=api,
        _start_listener=False,
    )

    assert guard.is_primary is True
    assert ("create_mutex", APP_MUTEX_NAME) in api.calls
    assert ("create_event", ACTIVATION_EVENT_NAME) in api.calls

    guard.close()
    assert ("close_handle", 202) in api.calls
    assert ("close_handle", 101) in api.calls


def test_main_checks_single_instance_before_loading_dashboard_stack():
    source = (ROOT / "main.py").read_text(encoding="utf-8")

    acquire = source.index("acquire_single_instance(")
    dashboard_import = source.index("from app import app")

    assert acquire < dashboard_import
