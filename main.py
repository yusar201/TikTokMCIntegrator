"""
main.py — TikTok MC Integrator launcher
Runs the Flask dashboard via waitress and shows a system tray icon.
Double-click TikTokMCIntegrator.exe to start.
"""
import os
import sys
import threading
import webbrowser

from PIL import Image, ImageDraw, ImageFont
import pystray
from waitress import serve

# Import the Flask app and setup function
from app import app, ensure_profiles_setup


# ── Tray icon image (drawn with PIL, no external file needed) ──────────────────
def create_icon_image():
    size = 64
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Background circle — teal/cyan gradient approximation
    d.ellipse([2, 2, size - 2, size - 2], fill=(0, 200, 180, 255))

    # Inner diamond shape — white
    cx, cy = size // 2, size // 2
    pts = [(cx, 8), (size - 8, cy), (cx, size - 8), (8, cy)]
    d.polygon(pts, fill=(255, 255, 255, 230))

    # Dark diamond core
    offset = 14
    inner = [(cx, 8 + offset), (size - 8 - offset, cy),
             (cx, size - 8 - offset), (8 + offset, cy)]
    d.polygon(inner, fill=(0, 160, 145, 255))

    return img


# ── Tray menu actions ──────────────────────────────────────────────────────────
def open_dashboard(icon, item):
    webbrowser.open('http://localhost:5000')


def exit_app(icon, item):
    """Gracefully shut down — show confirmation if bot is running."""
    try:
        from app import bot_process
        import app as app_module
        bot_running = (app_module.bot_process is not None and
                       app_module.bot_process.poll() is None)
    except Exception:
        bot_running = False

    if bot_running:
        try:
            import tkinter.messagebox
            root = tkinter.Tk()
            root.withdraw()
            result = tkinter.messagebox.askyesnocancel(
                "Bot Still Running",
                "The TikTok bot is still connected.\n\n"
                "Yes  → Stop bot & close\n"
                "No   → Close without stopping (bot runs)\n"
                "Cancel → Keep the app open"
            )
            root.destroy()
        except Exception:
            result = True  # fallback: just stop and close

        if result is None:  # Cancel
            return
        if result:  # Yes — stop bot
            print("Stopping bot and generating report...")
            try:
                from app import generate_report
                app_module.bot_process.terminate()
                app_module.bot_process.wait()
                app_module.bot_process = None
                try:
                    generate_report()
                    print("Report saved!")
                except Exception as e:
                    print(f"Report generation failed: {e}")
            except Exception as e:
                print(f"Error during shutdown: {e}")
        # No — just close, leave bot running
    else:
        print("Shutting down TikTok MC Integrator...")

    icon.stop()
    os._exit(0)


# ── Flask runner (background thread) ──────────────────────────────────────────
def run_flask():
    serve(app, host='0.0.0.0', port=5000, threads=4)


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--run-bot':
        import minecraftDiamond
        minecraftDiamond.run_bot()
        sys.exit(0)

    # Ensure profiles/config exist before Flask starts
    ensure_profiles_setup()

    # Start song queue worker
    try:
        from spotify_handler import start_song_queue_worker
        start_song_queue_worker()
    except Exception as e:
        print(f"[SONG-QUEUE] Failed to start worker: {e}")

    # Start Flask in background daemon thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Auto-open browser after a short delay so Flask is ready
    threading.Timer(1.8, lambda: webbrowser.open('http://localhost:5000')).start()

    # Build tray menu
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

    print("TikTok MC Integrator running — http://localhost:5000")
    print("Check your system tray to manage the app.")

    # pystray.run() MUST be on the main thread (Windows requirement)
    tray.run()
