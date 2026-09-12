"""Inspect an exported Gift Card Studio PNG and report measurable visual facts.

Written because the vision model was unavailable and "it exported without error"
is not evidence that a card looks right — the plan's own rejected-preview
history (blank glyphs, clipped widgets) came from exactly that assumption.

Checks, all from real pixel data:
  * icon region actually contains a multi-colour image, not a blank box
  * text regions contain ink, and the ink has the high-contrast hard edges of a
    pixel font rather than the smooth ramp of a fallback vector face
  * panel corners are stepped (transparent corner, opaque inset) not square
  * nothing touches the canvas edge (clipping)
  * per-cell occupancy for grid pages
"""
from __future__ import annotations

import sys
from collections import Counter

from PIL import Image


def load(path):
    with Image.open(path) as handle:
        handle.load()
        return handle.convert("RGBA")


def region_stats(image, box):
    """Opacity and colour variety inside a box."""
    x1, y1, x2, y2 = (int(v) for v in box)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(image.width, x2), min(image.height, y2)
    if x2 <= x1 or y2 <= y1:
        return {"pixels": 0, "opaque": 0, "colors": 0, "opaque_ratio": 0.0}

    crop = image.crop((x1, y1, x2, y2))
    pixels = list(crop.getdata())
    opaque = [p for p in pixels if p[3] > 8]
    colors = Counter((p[0], p[1], p[2]) for p in opaque)
    return {
        "pixels": len(pixels),
        "opaque": len(opaque),
        "colors": len(colors),
        "opaque_ratio": len(opaque) / max(1, len(pixels)),
        "top_colors": colors.most_common(4),
    }


def edge_touch(image, margin=1):
    """True if any opaque pixel sits on the outermost rows/columns."""
    w, h = image.size
    for x in range(w):
        for y in list(range(margin)) + list(range(h - margin, h)):
            if image.getpixel((x, y))[3] > 8:
                return True
    for y in range(h):
        for x in list(range(margin)) + list(range(w - margin, w)):
            if image.getpixel((x, y))[3] > 8:
                return True
    return False


def stepped_corner(image, box, step_probe=6):
    """Is the top-left corner of this box stepped rather than square?

    A square panel is opaque at its exact corner. A stepped/pixel-rounded panel
    is transparent at the corner and opaque a few pixels in on both axes.
    """
    x1, y1 = int(box[0]), int(box[1])
    corner = image.getpixel((x1, y1))[3]
    inset_x = image.getpixel((min(image.width - 1, x1 + step_probe), y1))[3]
    inset_y = image.getpixel((x1, min(image.height - 1, y1 + step_probe)))[3]
    diagonal = image.getpixel((
        min(image.width - 1, x1 + step_probe),
        min(image.height - 1, y1 + step_probe),
    ))[3]
    return {
        "corner_alpha": corner,
        "inset_x_alpha": inset_x,
        "inset_y_alpha": inset_y,
        "diagonal_alpha": diagonal,
        "stepped": corner <= 8 and diagonal > 8,
    }


def hard_edge_ratio(image, box, use_luminance=None):
    """Fraction of horizontal edge transitions that are abrupt.

    A pixel font jumps from background to glyph in one step; an antialiased
    vector face produces intermediate values.

    Alpha is the natural signal on a transparent canvas, but a card layer sits on
    an *opaque* panel, where alpha never changes and an alpha-based measurement
    silently reports 0 transitions — which reads as "no text" even when the text
    is clearly there. So the signal auto-selects: luminance when the region is
    fully opaque, alpha otherwise.
    """
    x1, y1, x2, y2 = (int(v) for v in box)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(image.width, x2), min(image.height, y2)
    if x2 <= x1 or y2 <= y1:
        return 0.0

    if use_luminance is None:
        stats = region_stats(image, box)
        use_luminance = stats["opaque_ratio"] > 0.98

    def signal(pixel):
        if use_luminance:
            return int(0.299 * pixel[0] + 0.587 * pixel[1] + 0.114 * pixel[2])
        return pixel[3]

    threshold = 128 if use_luminance else 8
    transitions = 0
    hard = 0
    for y in range(y1, y2):
        previous = signal(image.getpixel((x1, y)))
        for x in range(x1 + 1, x2):
            current = signal(image.getpixel((x, y)))
            if (previous > threshold) != (current > threshold):
                transitions += 1
                if abs(current - previous) > 150:
                    hard += 1
            previous = current
    return hard / transitions if transitions else 0.0


def colorfulness(image, box):
    """Mean saturation-like spread inside a box.

    Separates "a real gift icon was drawn" from "the dark panel is showing
    through": the panel is near-greyscale, a TikTok gift icon is not.
    """
    x1, y1, x2, y2 = (int(v) for v in box)
    crop = image.crop((max(0, x1), max(0, y1), min(image.width, x2), min(image.height, y2)))
    pixels = [p for p in crop.getdata() if p[3] > 8]
    if not pixels:
        return {"mean_spread": 0.0, "colorful_ratio": 0.0}
    spreads = [max(p[0], p[1], p[2]) - min(p[0], p[1], p[2]) for p in pixels]
    colorful = sum(1 for s in spreads if s > 30)
    return {
        "mean_spread": sum(spreads) / len(spreads),
        "colorful_ratio": colorful / len(pixels),
    }


def cell_occupancy(image, rows, columns, padding, gap_x, gap_y):
    """Opaque-pixel ratio per grid cell, to prove every cell got content."""
    cell_w = (image.width - 2 * padding - (columns - 1) * gap_x) / columns
    cell_h = (image.height - 2 * padding - (rows - 1) * gap_y) / rows
    report = []
    for row in range(rows):
        for column in range(columns):
            x = padding + column * (cell_w + gap_x)
            y = padding + row * (cell_h + gap_y)
            stats = region_stats(image, (x, y, x + cell_w, y + cell_h))
            report.append({
                "row": row, "column": column,
                "opaque_ratio": round(stats["opaque_ratio"], 4),
                "colors": stats["colors"],
            })
    return report


def describe(path, label=""):
    image = load(path)
    print(f"\n=== {label or path} ===")
    print(f"size: {image.size}  bbox: {image.getbbox()}")
    print(f"corner alpha (transparency): {image.getpixel((0, 0))[3]}")
    print(f"touches canvas edge (clipping): {edge_touch(image)}")
    return image


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        describe(arg)
