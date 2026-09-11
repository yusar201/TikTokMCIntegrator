# Close guard when bot subprocess is still running (2026-06-22)

## Problem

User closed the native app window while the TikTok bot subprocess (`TikTokMCIntegrator.exe --run-bot`) was still connected to a streamer. The dashboard disappeared but the bot kept running as an orphan child process.

This is worse than a normal close because the stream integration continues without visible controls.

## Detection

From PowerShell:

```powershell
Get-CimInstance Win32_Process -Filter 'ProcessId=<pid>' |
  Select-Object ProcessId,ParentProcessId,CommandLine
```

A bot subprocess looks like:

```text
D:\...\release\TikTokMCIntegrator.exe --run-bot
```

In code, check the app module’s subprocess handle:

```python
def _is_bot_running() -> bool:
    try:
        import app as app_module
        return app_module.bot_process is not None and app_module.bot_process.poll() is None
    except Exception:
        return False
```

## Correct pywebview close-guard pattern

pywebview exposes a blocking `closing` event:

```text
window.events.closing = Event(window, True)
```

On WinForms backend, if any handler returns `False`, the close is cancelled (`args.Cancel = True`). Use this to block the X button while the bot is running.

```python
def _show_close_warning_async(source="window"):
    # IMPORTANT: do not call evaluate_js synchronously inside WebView2's
    # blocking closing callback — it can deadlock/freeze the whole app.
    # Cancel the close, return to the UI loop, then show the modal shortly after.
    def _show():
        try:
            if _window is not None:
                _window.show()
                _window.restore()
                _window.evaluate_js(
                    f"window.showBotCloseWarning && window.showBotCloseWarning('{source}')"
                )
        except Exception as e:
            _log(f"Could not show in-app close warning: {e}")
    threading.Timer(0.1, _show).start()


def _on_window_closing():
    if not _is_bot_running():
        return True
    _show_close_warning_async("window")
    return False

_window = webview.create_window(
    'TikTok MC Integrator',
    url=start_target,
    js_api=CloseApi(),
    confirm_close=False,
    ...
)
_window.events.closing += _on_window_closing
```

## In-app modal, not native messagebox

For the main window close, show a styled HTML/CSS modal that matches the dashboard (Stardew/cozy wood-frame style). The modal should offer:

- **Keep App Open** — just hides modal
- **Close App Only** — exits launcher and leaves bot subprocess running intentionally
- **Stop Bot & Close** — terminates bot subprocess, generates report if possible, then exits

Expose the close actions through `js_api`:

```python
class CloseApi:
    def close_app(self, action: str = "keep") -> dict:
        if action == "stop":
            threading.Thread(target=_close_process, args=(True,), daemon=True).start()
            return {"status": "closing", "mode": "stop"}
        if action == "leave":
            threading.Thread(target=_close_process, args=(False,), daemon=True).start()
            return {"status": "closing", "mode": "leave"}
        return {"status": "kept_open"}
```

Run `os._exit(0)` in the close worker after optional bot termination because the launcher has daemon Flask/worker/tray threads.

## Tray Exit behavior

Tray callbacks run on pystray’s thread. Prefer re-showing/restoring the native window and triggering the same JS modal:

```python
_window.show()
_window.restore()
_window.evaluate_js("window.showBotCloseWarning && window.showBotCloseWarning('tray')")
```

If the window bridge fails, fall back to a native `tkinter.messagebox.askyesnocancel`. On exception/fallback, **keep safe** (cancel close) rather than silently orphaning the bot.

## Pitfalls

- **Never call `window.evaluate_js(...)` synchronously from `window.events.closing` on WebView2/WinForms.** The closing event is a blocking UI-thread callback; synchronous JS evaluation there can deadlock the app. Return `False` to cancel close, then use `threading.Timer(0.1, ...)` to show the modal after the close callback returns.
- When showing the warning from a maximized dashboard, do **not** call `window.restore()` before the modal. It visibly shrinks the app and feels broken. Use `window.show()` + `window.maximize()` before `evaluate_js(...)` so the warning appears over the same maximized dashboard.
- Detect orphan bot subprocesses, not just `app.bot_process`. If the native window is force-closed, the next launcher has a fresh `app.bot_process = None` while the old `TikTokMCIntegrator.exe --run-bot` may still be connected. Status/start/stop routes must scan for external `--run-bot` processes, show `Streaming (Background)`, block Start, and let Stop terminate the background PID. **Regression pitfall (2026-07-04):** `main.py`'s close guard may call `app.is_any_bot_running()` / `app.stop_all_bots()`. If those helpers are missing or raise, `_is_bot_running()` falls back to `False`, the X button silently closes, and the bot is orphaned. Always verify these helpers exist and `/api/bot/status` returns `{running:true, external:true}` when a fake/orphan `--run-bot` process is present.
- **Hide every Windows helper subprocess used by orphan detection.** Polling `/api/bot/status` or `/api/bot/logs` every 1–3s must not visibly spawn PowerShell/CMD windows. Any `powershell.exe`, `taskkill`, `wmic`, etc. launched from the frozen app needs `creationflags=subprocess.CREATE_NO_WINDOW` plus `startupinfo.dwFlags |= STARTF_USESHOWWINDOW; startupinfo.wShowWindow = SW_HIDE`.
- Do not rely only on `confirm_close=True`; it shows a generic native OK/Cancel and cannot offer “Stop Bot & Close” vs “Close App Only”.
- Do not let the X button close and then try to warn after `webview.start()` returns — by then the window is gone.
- Do not create a new pywebview window from a tray callback thread. Only show/restore the existing one or fall back to browser/native dialog.
- If the current running app predates the guard and is already closed, stop orphan bot process before deploying; otherwise `release/_internal` may be locked.
