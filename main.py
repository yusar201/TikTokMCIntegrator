"""
main.py — TikTok MC Integrator launcher

Boots the Flask dashboard (via waitress) and presents it in a NATIVE desktop
window using pywebview (Edge WebView2 on Windows) instead of opening a browser
tab. A bundled pixel-art splash shows instantly while Flask warms up, then the
same window swaps to the dashboard. A system-tray icon runs alongside.

Threading model (per multi-model fusion consensus, 2026-06-21):
  - pywebview owns the MAIN thread (webview.start() blocks there). WebView2
    HWNDs MUST be created on the thread that pumps the Win32 message loop.
  - pystray runs on its OWN thread via Icon.run_detached().
  - Flask (waitress) + the song-queue worker run on daemon threads.

Graceful degradation: if the WebView2 runtime is missing or pywebview fails to
initialize, we fall back to opening the default browser (the legacy behavior)
and keep the tray icon alive — so a failure is never worse than before.

Double-click TikTokMCIntegrator.exe to start.
"""
import os
import sys
import time
import threading
import traceback
import webbrowser
import urllib.request

# Process-mode dispatch MUST happen before dashboard/media/native-shell imports.
# The frozen EXE re-enters this same script for isolated runtimes.
if __name__ == '__main__' and len(sys.argv) > 1:
    if sys.argv[1] == '--run-bot':
        import minecraft_main
        minecraft_main.run_bot()
        sys.exit(0)
    if sys.argv[1] == '--objective-rush':
        from objective_rush_headless import run
        run()
        sys.exit(0)

# Default desktop mode is single-instance. This check stays above the heavy app
# imports so a second double-click can wake the existing window and exit quickly.
from single_instance import acquire_single_instance

_single_instance_guard = None
_single_instance_error = None
if __name__ == '__main__':
    try:
        _single_instance_guard = acquire_single_instance(_start_listener=False)
    except Exception as exc:
        # Fail open: a broken Windows API call must not make the app unlaunchable.
        _single_instance_error = exc
    else:
        if not _single_instance_guard.is_primary:
            raise SystemExit(0)

from PIL import Image, ImageDraw
import pystray
from waitress import serve

# Import the Flask app and setup function
from app import app, ensure_profiles_setup, start_tts_warmup_once

# Centralized, frozen-aware paths (config/ data/ logs/ assets/).
import paths

PORT = 5000
URL = f"http://localhost:{PORT}"

# Module-level handle so tray callbacks can reach the native window.
_window = None


def _is_bot_running() -> bool:
    """True when the TikTok bot subprocess is still connected/running."""
    try:
        import app as app_module
        running, _local, _external = app_module.is_any_bot_running()
        return running
    except Exception:
        return False


def _stop_bot_and_report() -> None:
    """Terminate the bot subprocess and write the post-stream report if possible."""
    try:
        import app as app_module
        from app import generate_report
        app_module.stop_all_bots()
        try:
            generate_report()
            _log("Report saved.")
        except Exception as e:
            _log(f"Report generation failed: {e}")
    except Exception as e:
        _log(f"Error stopping bot: {e}")


def _close_process(stop_bot: bool) -> None:
    """Exit the launcher process; optionally stop the bot first."""
    if stop_bot:
        _log("Stopping bot and closing app...")
        _stop_bot_and_report()
    else:
        _log("Closing app while leaving bot subprocess running.")
    os._exit(0)


class CloseApi:
    """pywebview bridge used by the in-app close warning modal."""

    def close_app(self, action: str = "keep") -> dict:
        if action == "stop":
            threading.Thread(target=_close_process, args=(True,), daemon=True).start()
            return {"status": "closing", "mode": "stop"}
        if action == "leave":
            threading.Thread(target=_close_process, args=(False,), daemon=True).start()
            return {"status": "closing", "mode": "leave"}
        return {"status": "kept_open"}


# ── Startup logging (console=False ⇒ no stdout; log everything to logs/) ──────
def _log(msg):
    """Append a line to logs/launcher.log and best-effort echo to stdout.

    With console=False there is NO visible output, so a silent failure looks
    like a dead app. Every startup step + any exception lands in this file so a
    broken launch is diagnosable instead of mysterious.
    """
    try:
        line = f"[launcher] {msg}"
        with open(paths.logs("launcher.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(f"[launcher] {msg}")
    except Exception:
        pass


# ── Tray icon image (load logo.png, fall back to drawn diamond) ────────────────
def _logo_path():
    """Locate static/logo.png in dev and frozen layouts."""
    base = sys._MEIPASS if getattr(sys, 'frozen', False) \
        else os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(base, 'static', 'logo.png')
    return candidate if os.path.exists(candidate) else None


def create_icon_image():
    # Prefer the user's real logo for the tray icon.
    lp = _logo_path()
    if lp:
        try:
            return Image.open(lp).convert('RGBA')
        except Exception as e:
            _log(f"Failed to load logo.png for tray ({e}); using drawn icon.")

    # Fallback: drawn teal diamond (no external file needed).
    size = 64
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([2, 2, size - 2, size - 2], fill=(0, 200, 180, 255))
    cx, cy = size // 2, size // 2
    pts = [(cx, 8), (size - 8, cy), (cx, size - 8), (8, cy)]
    d.polygon(pts, fill=(255, 255, 255, 230))
    offset = 14
    inner = [(cx, 8 + offset), (size - 8 - offset, cy),
             (cx, size - 8 - offset), (8 + offset, cy)]
    d.polygon(inner, fill=(0, 160, 145, 255))
    return img


# ── Tray menu actions ──────────────────────────────────────────────────────────
def _bring_window_forward():
    """Show/maximize the pywebview window, with a Win32 focus fallback."""
    global _window
    brought_forward = False
    try:
        if _window is not None:
            try:
                _window.show()
                brought_forward = True
            except Exception:
                pass
            try:
                _window.maximize()
                brought_forward = True
            except Exception:
                pass
    except Exception:
        pass

    # A second user-launched process usually has foreground permission, but its
    # direct Win32 attempt can race WebView startup. The primary repeats it here
    # after receiving the named activation event.
    try:
        from single_instance import focus_existing_window
        brought_forward = focus_existing_window() or brought_forward
    except Exception:
        pass
    return brought_forward


def open_dashboard(icon=None, item=None):
    """Bring the native window forward, or fall back to a browser tab.

    NOTE: this fires on pystray's thread, not the webview main thread. We only
    touch pywebview through its own thread-safe APIs (show/maximize), and if the
    window is gone we open a browser — never create a webview window off-thread.
    """
    if _bring_window_forward():
        return
    webbrowser.open(URL)


def exit_app(icon, item):
    """Gracefully shut down — warn if the bot is still running."""
    global _window
    if _is_bot_running():
        # Prefer the styled in-app warning over a native Tk dialog.
        try:
            if _window is not None:
                _show_close_warning_async("tray")
                return
        except Exception as e:
            _log(f"Could not show in-app close warning from tray: {e}")

        try:
            import tkinter
            import tkinter.messagebox
            root = tkinter.Tk()
            root.withdraw()
            result = tkinter.messagebox.askyesnocancel(
                "Bot Still Running",
                "The TikTok bot is still connected.\n\n"
                "Yes  -> Stop bot & close\n"
                "No   -> Close without stopping (bot runs)\n"
                "Cancel -> Keep the app open"
            )
            root.destroy()
        except Exception:
            result = None

        if result is None:  # Cancel / fallback: keep safe
            return
        _close_process(stop_bot=bool(result))
    else:
        _log("Shutting down TikTok MC Integrator...")
        try:
            icon.stop()
        except Exception:
            pass
        os._exit(0)


# ── Flask runner (background thread) ──────────────────────────────────────────
def run_flask():
    try:
        serve(app, host='0.0.0.0', port=PORT, threads=4)
    except Exception as e:
        _log(f"Flask/waitress crashed: {e}")
        _log(traceback.format_exc())


# ── Splash path resolution (works in dev AND frozen) ──────────────────────────
def _splash_url():
    """Return a file:// URL to the bundled splash.html, or None if missing.

    Frozen: templates/ is extracted under sys._MEIPASS. Dev: it sits next to
    this file. Shown via file:// so it renders BEFORE Flask is reachable.
    """
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(base, 'templates', 'splash.html')
    if os.path.exists(candidate):
        # webview accepts a plain absolute path or a file URL; normalize to URL.
        return 'file:///' + candidate.replace('\\', '/')
    _log(f"splash.html not found at {candidate} — will load {URL} directly")
    return None


# ── Tray bootstrap (own thread, via run_detached) ─────────────────────────────
def _start_tray():
    menu = pystray.Menu(
        pystray.MenuItem('Open Dashboard', open_dashboard, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Exit', exit_app),
    )
    tray = pystray.Icon(
        name='TikTokMCIntegrator',
        icon=create_icon_image(),
        title='TikTok MC Integrator',
        menu=menu,
    )
    try:
        # run_detached() pumps the tray's message loop on its OWN thread so the
        # main thread is free for pywebview. Documented pystray coexistence path.
        tray.run_detached()
        _log("System tray started (detached).")
    except Exception as e:
        _log(f"Tray run_detached failed ({e}); falling back to a daemon thread.")
        threading.Thread(target=tray.run, daemon=True).start()
    return tray


# ── Server-side readiness poll → swap splash to dashboard ─────────────────────
def _wait_then_load():
    """Poll /health from PYTHON (no CORS), then navigate the window to the app.

    The splash loads from a file:// origin, so a JS fetch() to http://localhost
    is cross-origin and Chromium blocks it — that was the "stuck on starting"
    bug. Polling here in Python sidesteps CORS entirely, and window.load_url()
    is a top-level navigation (also not subject to CORS). This is the reliable
    swap path.
    """
    global _window
    deadline = time.time() + 60  # generous; cold start can unpack for a while
    url = URL + "/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    _log("Flask /health OK — loading dashboard into window.")
                    try:
                        if _window is not None:
                            _window.load_url(URL + "/")
                            return
                    except Exception as e:
                        _log(f"window.load_url failed ({e}); opening browser.")
                        webbrowser.open(URL)
                        return
        except Exception:
            pass  # not up yet
        time.sleep(0.25)
    _log("Flask did not become ready within 60s; opening browser as fallback.")
    try:
        webbrowser.open(URL)
    except Exception:
        pass


def _register_gift_studio_folder_picker(webview_module):
    """Expose the native Windows folder dialog to the local Studio API.

    The HTTP request handling `/output-folder/browse` runs on a waitress worker,
    but pywebview's `create_file_dialog` marshals the native dialog to its UI
    thread. Registration itself starts no worker, timer, or polling loop, so the
    unopened Studio keeps zero idle cost.
    """
    from gift_card_studio import output as gift_studio_output

    if _window is None:
        gift_studio_output.register_folder_picker(None)
        return

    def choose_folder():
        chosen = _window.create_file_dialog(
            webview_module.FOLDER_DIALOG,
            allow_multiple=False,
        )
        if not chosen:
            return None
        # pywebview returns a tuple/list even for a single directory.
        if isinstance(chosen, (tuple, list)):
            return chosen[0]
        return chosen

    gift_studio_output.register_folder_picker(choose_folder)



def _clear_gift_studio_folder_picker():
    """Browser fallback has no native dialog; prevent a stale window closure."""
    try:
        from gift_card_studio import output
        output.register_folder_picker(None)
    except Exception:
        pass


def _show_close_warning_async(source="window"):
    """Show close warning after the native closing event returns.

    Calling evaluate_js synchronously inside WebView2's closing callback can
    deadlock the UI thread. Timer returns control first, then JS opens the modal.
    """
    def _show():
        try:
            if _window is not None:
                _window.show()
                _window.maximize()
                _window.evaluate_js(f"window.showBotCloseWarning && window.showBotCloseWarning('{source}')")
        except Exception as e:
            _log(f"Could not show in-app close warning: {e}")
    threading.Timer(0.1, _show).start()


# ── Native window close guard ─────────────────────────────────────────────────
def _on_window_closing():
    """Cancel window close while the bot is running and show styled app modal."""
    if not _is_bot_running():
        return True

    _show_close_warning_async("window")
    return False


# ── Native window with browser fallback ───────────────────────────────────────
def _launch_window():
    """Open the pywebview native window. Returns True on success.

    The whole point: if WebView2 / pywebview can't initialize, we DON'T crash —
    we return False so the caller opens a browser tab instead (legacy behavior).
    The biggest documented failure mode is the runtime missing on a clean
    machine, where the error can surface async deep in COM at start(); we wrap
    both create_window and start() and treat any failure as "use the browser".
    """
    global _window
    try:
        import webview
    except Exception as e:
        _log(f"pywebview import failed ({e}); using browser fallback.")
        return False

    # pywebview disables downloads by default. The gift editor exports its PNG
    # through a blob-backed <a download> link, so WebView2 silently ignored the
    # click even though the same code worked in a normal browser.
    webview.settings['ALLOW_DOWNLOADS'] = True

    start_target = _splash_url() or URL
    try:
        _window = webview.create_window(
            'TikTok MC Integrator',
            url=start_target,
            width=1180,
            height=780,
            min_size=(900, 600),
            maximized=True,
            confirm_close=False,
            js_api=CloseApi(),
            text_select=True,
        )
        _window.events.closing += _on_window_closing
        _register_gift_studio_folder_picker(webview)
        _log(f"Native window created (target={start_target}).")
    except Exception as e:
        _log(f"webview.create_window failed ({e}); using browser fallback.")
        _log(traceback.format_exc())
        _window = None
        _clear_gift_studio_folder_picker()
        return False

    # Kick off the Python-side readiness poll that swaps splash → dashboard.
    # Only needed when we actually showed the splash; if we loaded URL directly
    # (splash missing) the page is already the app.
    if start_target != URL:
        threading.Thread(target=_wait_then_load, daemon=True).start()

    try:
        # Blocks on the MAIN thread until the window closes. Prefer the
        # edgechromium (WebView2) backend; pywebview auto-selects on Windows.
        webview.start()
        _log("Native window closed by user.")
        return True
    except Exception as e:
        _log(f"webview.start failed ({e}); using browser fallback.")
        _log(traceback.format_exc())
        _window = None
        _clear_gift_studio_folder_picker()
        return False


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    _log("=== TikTok MC Integrator starting ===")
    if _single_instance_error is not None:
        _log(f"Single-instance guard unavailable; continuing normally: {_single_instance_error}")
    elif _single_instance_guard is not None:
        def _on_second_launch():
            _log("Second launch detected; bringing existing window forward.")
            _bring_window_forward()
        _single_instance_guard.start_listener(_on_second_launch)
        _log("Single-instance guard active.")

    # Ensure profiles/config exist before Flask starts.
    try:
        ensure_profiles_setup()
    except Exception as e:
        _log(f"ensure_profiles_setup failed: {e}")

    # Start song queue worker.
    try:
        from spotify_handler import start_song_queue_worker
        start_song_queue_worker()
        _log("Song queue worker started.")
    except Exception as e:
        _log(f"Failed to start song queue worker: {e}")

    # One-time TTS cold-start warmup. No audio playback, no recurring timer.
    try:
        if start_tts_warmup_once():
            _log("TTS warmup started.")
    except Exception as e:
        _log(f"TTS warmup failed to start: {e}")

    # Start Flask (waitress) in a background daemon thread.
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    _log(f"Flask serving on {URL} (background thread).")

    # Start the tray icon on its own (detached) thread.
    try:
        _start_tray()
    except Exception as e:
        _log(f"Tray failed to start: {e}")

    _log("Opening native window...")
    ok = _launch_window()

    if not ok:
        # Fallback path: behave like the old launcher — open a browser tab and
        # keep the process alive so Flask + tray keep serving (incl. OBS overlays).
        _log("Falling back to browser; keeping server alive.")
        try:
            webbrowser.open(URL)
        except Exception as e:
            _log(f"webbrowser.open failed: {e}")
        # Park the main thread so daemons keep running.
        try:
            flask_thread.join()
        except KeyboardInterrupt:
            _log("Interrupted; exiting.")
            os._exit(0)
    else:
        # Native window closed = user wants out. Exit the whole process so the
        # daemon threads (Flask, worker) and tray don't linger.
        _log("Window closed; shutting down process.")
        os._exit(0)
