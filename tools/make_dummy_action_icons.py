"""Generate placeholder action icons for Gift Card Studio.

Action icons are optional and Khito will supply the real artwork later. Until
then a card with ``include_action_icon=True`` renders an empty badge, which makes
the layout impossible to judge. These placeholders fill that slot with something
legible and obviously provisional.

Deliberately crude pixel glyphs on a 16x16 grid, scaled with nearest neighbour so
they stay hard-edged like the rest of the overlay art. No antialiasing, no
gradients.

Glyph alphabet (explicit, because an implicit "filler" character silently
produced solid opaque squares on the first attempt):

    ``.``  transparent — nothing is drawn
    ``#``  outline / darkest shade
    ``b``  body fill
    ``o``  ink / highlight

Run:  python tools/make_dummy_action_icons.py [--size 64] [--force]
Writes to data/gift_card_studio/assets/action-<name>.png
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

GRID = 16
TRANSPARENT = "."

ICONS = {
    "mob": {
        "colors": {"#": "#1d2a18", "b": "#4b8b3b", "o": "#0a0a0a"},
        "rows": [
            "................",
            "..############..",
            ".##bbbbbbbbbb##.",
            ".#bbbbbbbbbbbb#.",
            ".#bboobbbboobb#.",
            ".#bboobbbboobb#.",
            ".#bbbbbbbbbbbb#.",
            ".#bbbbboobbbbb#.",
            ".#bbbboooobbbb#.",
            ".#bbbboooobbbb#.",
            ".#bbbboobboobb#.",
            ".#bbbboobboobb#.",
            ".##bbbbbbbbbb##.",
            "..############..",
            "................",
            "................",
        ],
    },
    "item": {
        "colors": {"#": "#2e2313", "b": "#8a6a3a", "o": "#d8c07a"},
        "rows": [
            "................",
            "................",
            "..############..",
            ".##bbbbbbbbbb##.",
            ".#bbbbbbbbbbbb#.",
            ".#bbbbboobbbbb#.",
            ".##############.",
            ".#bbbbboobbbbb#.",
            ".#bbbbbobbbbbb#.",
            ".#bbbbbbbbbbbb#.",
            ".#bbbbbbbbbbbb#.",
            ".##bbbbbbbbbb##.",
            "..############..",
            "................",
            "................",
            "................",
        ],
    },
    "potion": {
        "colors": {"#": "#241a33", "b": "#7a5aa8", "o": "#c8a8f0"},
        "rows": [
            "................",
            "......####......",
            "......#oo#......",
            "......#oo#......",
            ".....##bb##.....",
            "....##bbbb##....",
            "...##bbbbbb##...",
            "...#bbbbbbbb#...",
            "...#bboooobb#...",
            "...#bboooobb#...",
            "...#bbbbbbbb#...",
            "....##bbbb##....",
            ".....######.....",
            "................",
            "................",
            "................",
        ],
    },
    "tnt": {
        "colors": {"#": "#3a1010", "b": "#b03a3a", "o": "#f0e0c0"},
        "rows": [
            ".......o........",
            "......o.........",
            "................",
            "..############..",
            "..#bbbbbbbbbb#..",
            "..#bbbbbbbbbb#..",
            "..#oooooooooo#..",
            "..#obbbbbbbbo#..",
            "..#obboooobbo#..",
            "..#obbbbbbbbo#..",
            "..#oooooooooo#..",
            "..#bbbbbbbbbb#..",
            "..#bbbbbbbbbb#..",
            "..############..",
            "................",
            "................",
        ],
    },
    "world": {
        "colors": {"#": "#12262b", "b": "#3a7a8a", "o": "#a0d8e8"},
        "rows": [
            "................",
            "....########....",
            "..##bbbbbbbb##..",
            ".#bbbboooobbbb#.",
            ".#bb##bbbb##bb#.",
            "#bb#bbbbbbbb#bb#",
            "#b#bbbbbbbbbb#b#",
            "#ooooooooooooo o",
            "#b#bbbbbbbbbb#b#",
            "#bb#bbbbbbbb#bb#",
            ".#bb##bbbb##bb#.",
            ".#bbbboooobbbb#.",
            "..##bbbbbbbb##..",
            "....########....",
            "................",
            "................",
        ],
    },
    "trophy": {
        "colors": {"#": "#3d3009", "b": "#c8a032", "o": "#f0d878"},
        "rows": [
            "................",
            "..############..",
            "..#oooooooooo#..",
            "###bbbbbbbbbb###",
            "#b#bbbbbbbbbb#b#",
            "#b#bbbbbbbbbb#b#",
            "###bbbbbbbbbb###",
            "..##bbbbbbbb##..",
            "....########....",
            "......#bb#......",
            "......#bb#......",
            "....##bbbb##....",
            "..#oooooooooo#..",
            "..############..",
            "................",
            "................",
        ],
    },
    "portal": {
        "colors": {"#": "#2b1030", "b": "#8a3a9a", "o": "#d8a0f0"},
        "rows": [
            "................",
            "....########....",
            "..##bbbbbbbb##..",
            "..#bbbbbbbbbb#..",
            ".##bb######bb##.",
            ".#bb##oooo##bb#.",
            ".#bb#oooooo#bb#.",
            ".#bb#oooooo#bb#.",
            ".#bb#oooooo#bb#.",
            ".#bb##oooo##bb#.",
            ".##bb######bb##.",
            "..#bbbbbbbbbb#..",
            "..##bbbbbbbb##..",
            "....########....",
            "................",
            "................",
        ],
    },
    "clock": {
        "colors": {"#": "#1b2029", "b": "#d0d8e8", "o": "#2f3a4d"},
        "rows": [
            "................",
            "....########....",
            "..##bbbbbbbb##..",
            ".#bbbbbbbbbbbb#.",
            ".#bbbbbobbbbbb#.",
            "#bbbbbbobbbbbb b",
            "#bbbbbbobbbbbbb#",
            "#bbbbbbooooobbb#",
            "#bbbbbbbbbbbbbb#",
            "#bbbbbbbbbbbbbb#",
            ".#bbbbbbbbbbbb#.",
            ".#bbbbbbbbbbbb#.",
            "..##bbbbbbbb##..",
            "....########....",
            "................",
            "................",
        ],
    },
    "chat": {
        "colors": {"#": "#1a2029", "b": "#e0e8f0", "o": "#4a5a6a"},
        "rows": [
            "................",
            "..############..",
            ".##bbbbbbbbbb##.",
            ".#bbbbbbbbbbbb#.",
            ".#bboooooooobb#.",
            ".#bbbbbbbbbbbb#.",
            ".#bboooooooobb#.",
            ".#bbbbbbbbbbbb#.",
            ".#bbooooooobbb#.",
            ".#bbbbbbbbbbbb#.",
            ".##bbbbbbbbbb##.",
            "..####bb######..",
            "....##bb........",
            "....#bb.........",
            "................",
            "................",
        ],
    },
}


def build_icon(spec, size):
    """Render one 16x16 glyph as a hard-edged RGBA image of ``size``."""
    base = Image.new("RGBA", (GRID, GRID), (0, 0, 0, 0))
    colors = spec["colors"]
    for y, row in enumerate(spec["rows"][:GRID]):
        for x, char in enumerate(row[:GRID]):
            if char in (TRANSPARENT, " "):
                continue
            hex_color = colors.get(char)
            if not hex_color:
                continue
            value = hex_color.lstrip("#")
            rgb = tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
            base.putpixel((x, y), rgb + (255,))
    # NEAREST keeps every edge hard — the whole point of pixel art.
    return base.resize((size, size), Image.Resampling.NEAREST)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=64)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    from gift_card_studio import storage

    out_dir = args.out or storage.assets_dir("data")
    os.makedirs(out_dir, exist_ok=True)

    written = 0
    for name, spec in ICONS.items():
        path = os.path.join(out_dir, f"action-{name}.png")
        if os.path.exists(path) and not args.force:
            print(f"skip (exists): {path}")
            continue
        icon = build_icon(spec, args.size)
        icon.save(path, format="PNG")

        pixels = list(icon.getdata())
        opaque = sum(1 for pixel in pixels if pixel[3] > 0)
        ratio = opaque / len(pixels)
        distinct = len({p[:3] for p in pixels if p[3] > 0})
        flag = "" if 0.15 < ratio < 0.95 and distinct >= 2 else "  <-- CHECK"
        print(
            f"wrote {os.path.basename(path)} {icon.size} "
            f"opaque={ratio:.0%} colours={distinct}{flag}"
        )
        written += 1

    print(f"\n{written} icon(s) written to {out_dir}")
    print("opaque should be well under 100%: a solid square means the glyph "
          "filler is painting the background.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
