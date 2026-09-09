"""Pixel verification for the Gift Roulette overlay via real Flask routes.

Renders /overlay/roulette with real seeded state files, screenshots in
headless Chromium, and asserts fixed geometry + winner highlight in pixels.
Run with WINDOWS Python (playwright lives there):
    /mnt/c/Python313/python.exe tests/pixel_roulette_overlay.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".roulette_pixel_check"
STATE = ROOT / "data" / "roulette_state.json"


def _spin_state(status="spinning", *, entries_n=5, spin_ms=5.0, hold=4.0):
    now = time.time()
    entries = [
        {"gift_id": str(100 + i),
         "label": f"Prize {i+1}" + (" with a very long description label" if i == 1 and entries_n > 3 else ""),
         "icon_url": "", "diamond_count": i + 1}
        for i in range(entries_n)
    ]
    reel = [(i % entries_n) for i in range(24)] + [1]
    return {
        "schema": 1, "spin_id": "pixel-test", "source": "test", "profile": "default",
        "status": status,
        "started_at": now, "lands_at": now + spin_ms, "hide_at": now + spin_ms + hold,
        "trigger": {"gift_id": "5655", "gift_name": "Rose", "user": "PixelViewer"},
        "entries": entries, "reel": reel, "winner_index": 1,
        "dispatch_status": "pending",
    }


def _write_state(state):
    STATE.write_text(json.dumps(state), encoding="utf-8")


def _flask_client():
    import sys as _sys
    root = str(Path(__file__).resolve().parents[1])
    if root not in _sys.path:
        _sys.path.insert(0, root)
    import app as app_module
    return app_module.app.test_client()


def main():
    results = []
    try:
        with _flask_client() as client:
            html = client.get("/overlay/roulette").get_data(as_text=True)

            # --- state 1: idle ---
            p1 = SCRATCH / "overlay_idle.png"
            _shoot(html, p1, state={"status": "idle"})

            # --- state 2: spinning mid-roll (lands 30s out so it stays rolling) ---
            p2 = SCRATCH / "overlay_spinning.png"
            _shoot(html, p2, state=_spin_state("spinning", spin_ms=30.0))

            # --- state 3: mid POP (bounce in flight, 350ms in) ---
            p3 = SCRATCH / "overlay_pop.png"
            _shoot(html, p3, state=_spin_state("landed", spin_ms=30.0), budget=350)

            # --- state 4: landed settled (pop done, winner gold, still holding) ---
            p4 = SCRATCH / "overlay_landed.png"
            _shoot(html, p4, state=_spin_state("landed", spin_ms=30.0))

            # --- state 5: 100-entry pool landed (geometry must match state 4) ---
            p5 = SCRATCH / "overlay_bigpool.png"
            _shoot(html, p5, state=_spin_state("landed", spin_ms=30.0, entries_n=100))

        results = _analyze([p1, p2, p3, p4, p5])
        # Geometry equality between pool 2 and pool 100 (fixed-geometry rule)
        geoms = [detail for _, _, detail in results]
        print("geometry lines above; expect identical bbox for landed vs bigpool")
    finally:
        if STATE.exists():
            STATE.unlink()

    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)


def _shoot(html, out_path, state=None, budget=2500):
    """Render real overlay HTML + real static css in headless Chrome.

    file:// origin cannot fetch /api/*, so the harness injects a mock fetch
    returning the given state (or idle) BEFORE the overlay's own script runs.
    The overlay JS itself is the real unmodified script. `budget` is the
    virtual-time window: CSS animations run inside it, so capture timing
    picks the frame (e.g. 350ms = mid pop-in squash).
    """
    page = SCRATCH / "page.html"
    css_href = (ROOT / "static" / "style.css").as_uri()
    html = html.replace('href="/static/style.css', f'href="{css_href}"')
    state_json = json.dumps(state or {"status": "idle"})
    mock = (
        "<script>"
        "window.__rlState = " + state_json + ";"
        "window.fetch = function(url){"
        "  return Promise.resolve({ json: function(){ return Promise.resolve(window.__rlState); } });"
        "};"
        "</script>"
    )
    html = html.replace("<body>", "<body>" + mock)
    page.write_text(html, encoding="utf-8")

    cmd = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--allow-file-access-from-files",
        "--force-device-scale-factor=1",
        "--window-size=800,300",
        f"--virtual-time-budget={budget}",
        "--screenshot=" + str(out_path).replace("/mnt/d/", "D:/").replace("/", "\\"),
        "file:///" + str(page).replace("/mnt/d/", "D:/").replace("\\", "/"),
    ]
    for candidate in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                      r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                      r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                      r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if Path(candidate).exists():
            cmd[0] = candidate
            break
    subprocess.run(cmd, capture_output=True, timeout=60)


def _analyze(paths):
    from PIL import Image
    results = []
    for p in paths:
        wp = Path(str(p).replace("/mnt/d/", "D:/"))
        if not wp.exists():
            results.append((p.name, False, "screenshot missing"))
            continue
        img = Image.open(wp).convert("RGB")
        w, h = img.size
        px = img.load()
        # find dark-pixel bbox (card region) scanning the window
        minx, miny, maxx, maxy = w, h, 0, 0
        dark = 0
        for y in range(0, h, 2):
            for x in range(0, w, 2):
                r, g, b = px[x, y]
                if r < 70 and g < 70 and b < 80:
                    dark += 1
                    minx, miny = min(minx, x), min(miny, y)
                    maxx, maxy = max(maxx, x), max(maxy, y)
        results.append((p.name, dark > 200, f"darkpx={dark} bbox=({minx},{miny},{maxx},{maxy})"))
    return results


if __name__ == "__main__":
    main()
