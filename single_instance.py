"""Windows single-instance guard for the desktop launcher.

The first launcher owns a named mutex and listens on a named auto-reset event.
A later launcher signals that event, restores/focuses the existing native window,
and exits before importing the heavy dashboard stack.
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from typing import Any

APP_MUTEX_NAME = r"Local\TikTokMCIntegrator.SingleInstance.v1"
ACTIVATION_EVENT_NAME = r"Local\TikTokMCIntegrator.Activate.v1"
WINDOW_TITLE = "TikTok MC Integrator"

_ERROR_ALREADY_EXISTS = 183
_EVENT_MODIFY_STATE = 0x0002
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_SW_SHOW = 5
_SW_RESTORE = 9
_SW_MAXIMIZE = 3


class _WindowsApi:
    """Small ctypes boundary kept injectable for deterministic tests."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)

        self._kernel32.CreateMutexW.argtypes = (
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        self._kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._kernel32.CreateEventW.argtypes = (
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        self._kernel32.CreateEventW.restype = wintypes.HANDLE
        self._kernel32.OpenEventW.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        self._kernel32.OpenEventW.restype = wintypes.HANDLE
        self._kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
        self._kernel32.SetEvent.restype = wintypes.BOOL
        self._kernel32.WaitForSingleObject.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
        )
        self._kernel32.WaitForSingleObject.restype = wintypes.DWORD
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL

        self._user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
        self._user32.FindWindowW.restype = wintypes.HWND
        self._user32.IsIconic.argtypes = (wintypes.HWND,)
        self._user32.IsIconic.restype = wintypes.BOOL
        self._user32.IsWindowVisible.argtypes = (wintypes.HWND,)
        self._user32.IsWindowVisible.restype = wintypes.BOOL
        self._user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
        self._user32.ShowWindow.restype = wintypes.BOOL
        self._user32.BringWindowToTop.argtypes = (wintypes.HWND,)
        self._user32.BringWindowToTop.restype = wintypes.BOOL
        self._user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
        self._user32.SetForegroundWindow.restype = wintypes.BOOL

    def create_mutex(self, name: str) -> tuple[int, bool]:
        self._ctypes.set_last_error(0)
        handle = self._kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise self._ctypes.WinError(self._ctypes.get_last_error())
        return int(handle), self._ctypes.get_last_error() == _ERROR_ALREADY_EXISTS

    def create_event(self, name: str) -> int:
        # Auto-reset means one activation request wakes exactly one listener wait.
        handle = self._kernel32.CreateEventW(None, False, False, name)
        if not handle:
            raise self._ctypes.WinError(self._ctypes.get_last_error())
        return int(handle)

    def open_event(self, name: str) -> int:
        handle = self._kernel32.OpenEventW(
            _EVENT_MODIFY_STATE | _SYNCHRONIZE,
            False,
            name,
        )
        return int(handle) if handle else 0

    def set_event(self, handle: int) -> bool:
        return bool(self._kernel32.SetEvent(handle))

    def wait_for_event(self, handle: int, timeout_ms: int) -> int:
        return int(self._kernel32.WaitForSingleObject(handle, timeout_ms))

    def close_handle(self, handle: int) -> None:
        if handle:
            self._kernel32.CloseHandle(handle)

    def activate_window(self, title: str) -> bool:
        """Restore, maximize, and foreground the exact pywebview window."""
        hwnd = self._user32.FindWindowW(None, title)
        if not hwnd:
            return False
        if self._user32.IsIconic(hwnd):
            self._user32.ShowWindow(hwnd, _SW_RESTORE)
        elif not self._user32.IsWindowVisible(hwnd):
            self._user32.ShowWindow(hwnd, _SW_SHOW)
        self._user32.ShowWindow(hwnd, _SW_MAXIMIZE)
        self._user32.BringWindowToTop(hwnd)
        self._user32.SetForegroundWindow(hwnd)
        return True


def focus_existing_window(title: str = WINDOW_TITLE) -> bool:
    """Best-effort Win32 restore/maximize/foreground. Never raises."""
    try:
        return _WindowsApi().activate_window(title)
    except Exception:
        return False


class SingleInstanceGuard:
    def __init__(
        self,
        *,
        is_primary: bool,
        mutex_handle: int = 0,
        event_handle: int = 0,
        api: Any = None,
    ) -> None:
        self.is_primary = is_primary
        self._mutex_handle = mutex_handle
        self._event_handle = event_handle
        self._api = api
        self._listener_started = False
        self._stop = threading.Event()

    def start_listener(self, on_activate: Callable[[], Any]) -> None:
        """Listen for later launches without touching the pywebview main loop."""
        if not self.is_primary or not self._event_handle or self._listener_started:
            return
        self._listener_started = True

        def listen() -> None:
            while not self._stop.is_set():
                result = self._api.wait_for_event(self._event_handle, 500)
                if result == _WAIT_OBJECT_0:
                    try:
                        on_activate()
                    except Exception:
                        pass
                elif result != _WAIT_TIMEOUT:
                    return

        threading.Thread(
            target=listen,
            name="single-instance-activation",
            daemon=True,
        ).start()

    def close(self) -> None:
        self._stop.set()
        if self._event_handle:
            self._api.close_handle(self._event_handle)
            self._event_handle = 0
        if self._mutex_handle:
            self._api.close_handle(self._mutex_handle)
            self._mutex_handle = 0


def acquire_single_instance(
    on_activate: Callable[[], Any] | None = None,
    *,
    _platform: str | None = None,
    _api: Any = None,
    _sleep: Callable[[float], None] = time.sleep,
    _notify_timeout: float = 2.0,
    _start_listener: bool = True,
) -> SingleInstanceGuard:
    """Acquire the app mutex, or notify/focus the already-running launcher."""
    platform = os.name if _platform is None else _platform
    if platform != "nt":
        return SingleInstanceGuard(is_primary=True)

    api = _api or _WindowsApi()
    mutex_handle, already_exists = api.create_mutex(APP_MUTEX_NAME)
    if not already_exists:
        event_handle = api.create_event(ACTIVATION_EVENT_NAME)
        guard = SingleInstanceGuard(
            is_primary=True,
            mutex_handle=mutex_handle,
            event_handle=event_handle,
            api=api,
        )
        if on_activate is not None and _start_listener:
            guard.start_listener(on_activate)
        return guard

    # The existing process owns the mutex. Signal its listener, then use the
    # foreground rights granted to this user-launched process to focus directly.
    deadline = time.monotonic() + max(0.0, _notify_timeout)
    event_handle = 0
    while True:
        event_handle = api.open_event(ACTIVATION_EVENT_NAME)
        if event_handle or time.monotonic() >= deadline:
            break
        _sleep(0.05)

    if event_handle:
        try:
            api.set_event(event_handle)
        finally:
            api.close_handle(event_handle)

    while True:
        if api.activate_window(WINDOW_TITLE):
            break
        if time.monotonic() >= deadline:
            break
        _sleep(0.05)

    api.close_handle(mutex_handle)
    return SingleInstanceGuard(is_primary=False)
