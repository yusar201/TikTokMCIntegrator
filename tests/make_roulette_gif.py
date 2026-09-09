"""Build an animated GIF preview of the Gift Roulette overlay lifecycle.

Renders /overlay/roulette in headless Edge at stepped virtual-time budgets
(real overlay HTML + real CSS + real JS, mock-fetched state with a page-
relative 2.0s roll + 1.5s hold), captures ~27 frames, and assembles them
into a looping GIF with Pillow.

Run (Windows Python):
    /mnt/c/Python313/python.exe tests/make_roulette_gif.py
Output:
    C:/Users/yusar/Pictures/RoulettePreview/roulette_preview.gif
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import pixel_roulette_overlay as px  # noqa: E402  (reuses SCRATCH/_spin_state/_flask_client)

OUT_DIR = Path("C:/Users/yusar/Pictures/RoulettePreview")
ROLL_S = 2.0    # page-relative roll duration
HOLD_S = 1.5    # hold after land
END_MS = int((ROLL_S + HOLD_S + 0.5) * 1000)  # +0.5s to include squash-out
STEP_MS = 150


def build_page() -> Path:
    client = px._flask_client()
    html = client.get("/overlay/roulette").get_data(as_text=True)
    css_href = (px.ROOT / "static" / "style.css").as_uri()
    html = html.replace('href="/static/style.css', f'href="{css_href}"')
    base = px._spin_state("spinning", spin_ms=ROLL_S)
    # Page-relative timeline: each poll's lands_at is ROLL_S ahead of the
    # page's own clock, so the roll always starts at first fetch regardless
    # of how long Chrome took to launch.
    mock = (
        "<script>"
        "window.__rlBase = " + json.dumps(base) + ";"
        "window.fetch = function(url){"
        "  const s = Object.assign({}, window.__rlBase);"
        f"  s.lands_at = Date.now()/1000 + {ROLL_S};"
        f"  s.hide_at = s.lands_at + {HOLD_S};"
        "  return Promise.resolve({ json: function(){ return Promise.resolve(s); } });"
        "};"
        "</script>"
    )
    html = html.replace("<body>", "<body>" + mock)
    page = px.SCRATCH / "gif_page.html"
    page.write_text(html, encoding="utf-8")
    return page


def frame_budgets():
    return list(range(100, END_MS + 1, STEP_MS))


def shoot(page: Path, out_png: Path, budget: int) -> None:
    cmd = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--allow-file-access-from-files",
        "--force-device-scale-factor=1",
        "--window-size=800,300",
        f"--virtual-time-budget={budget}",
        "--screenshot=" + str(out_png).replace("/mnt/d/", "D:/").replace("/", "\\"),
        "file:///" + str(page).replace("/mnt/d/", "D:/").replace("\\", "/"),
    ]
    subprocess.run(cmd, capture_output=True, timeout=60)


def main():
    px.SCRATCH.mkdir(parents=True, exist_ok=True)
    frames_dir = px.SCRATCH / "gif_frames"
    frames_dir.mkdir(exist_ok=True)
    page = build_page()
    budgets = frame_budgets()
    t0 = time.time()
    for i, budget in enumerate(budgets):
        shoot(page, frames_dir / f"f{i:03d}.png", budget)
        print(f"frame {i+1}/{len(budgets)} (budget={budget}ms)", flush=True)
    print(f"captured {len(budgets)} frames in {time.time()-t0:.0f}s")

    from PIL import Image
    frames = []
    for i in range(len(budgets)):
        p = frames_dir / f"f{i:03d}.png"
        if p.exists():
            frames.append(Image.open(p).convert("RGB"))
    if len(frames) < 5:
        print("FAIL: too few frames captured")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gif_path = OUT_DIR / "roulette_preview.gif"
    frames[0].save(
        gif_path, save_all=True, append_images=frames[1:],
        duration=STEP_MS, loop=0, optimize=True,
    )
    size_mb = gif_path.stat().st_size / 1e6
    print(f"GIF written: {gif_path} ({size_mb:.1f} MB, {len(frames)} frames)")
    sys.exit(0 if size_mb < 20 else 1)


if __name__ == "__main__":
    main()
