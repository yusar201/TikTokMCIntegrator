"""Rasterize Gift Card Studio SVG to PNG bytes.

**Import cost:** this module is imported only by the exporter, which itself is
imported only when an export actually runs. Nothing here loads at app start.

**Rasterizer choice (Phase 4 spike, verified 2026-08-28):** ``resvg_py``.
The plan required proving font/image parity before committing. Results on this
machine:

* ``cairosvg`` — installs, then fails at runtime: ``no library called "cairo-2"
  was found``. It needs a native GTK/cairo DLL that is not present and would
  have to be shipped with the frozen exe. Rejected.
* ``resvg_py`` — a self-contained prebuilt wheel (no external DLL), renders
  RGBA with real alpha, and draws the project's actual ``Minecraft.otf`` when
  passed via ``font_files`` (verified: correct glyph bbox, not a fallback
  smear). Chosen.

Fonts are passed explicitly with ``skip_system_fonts=True`` so an export looks
identical on any machine — a system font substitution would silently change
every card's metrics between Khito's PC and a rebuild.
"""
from __future__ import annotations

import io
import os

import paths

# Fonts the renderer may reference. Resolved lazily and cached; a missing file is
# skipped rather than fatal, so an export still succeeds with the remaining ones.
FONT_RELPATHS = (
    os.path.join("addons", "survival_rush", "static", "fonts", "Minecraft.otf"),
    os.path.join("static", "fonts", "ChakraPetch-Regular.ttf"),
    os.path.join("static", "fonts", "ChakraPetch-Bold.ttf"),
    os.path.join("static", "fonts", "ChakraPetch-Medium.ttf"),
    os.path.join("static", "fonts", "ChakraPetch-SemiBold.ttf"),
)

DEFAULT_FONT_FAMILY = "Minecraft"

_font_cache: list[str] | None = None


class RasterizeError(RuntimeError):
    """Raised when SVG could not be turned into pixels."""


def font_files(base_dir: str | None = None) -> list[str]:
    """Absolute paths of the fonts to hand the rasterizer."""
    global _font_cache
    if base_dir is None and _font_cache is not None:
        return list(_font_cache)

    root = base_dir or paths.BASE_DIR
    found = []
    for relpath in FONT_RELPATHS:
        candidate = os.path.join(root, relpath)
        if os.path.exists(candidate):
            found.append(os.path.abspath(candidate))

    if base_dir is None:
        _font_cache = found
    return list(found)


def rasterizer_available() -> bool:
    """True when SVG can actually be rendered on this build."""
    try:
        import resvg_py  # noqa: F401
    except Exception:
        return False
    return True


def svg_to_png_bytes(svg: str, width=None, height=None, background=None,
                     base_dir: str | None = None) -> bytes:
    """Render an SVG string to PNG bytes with alpha preserved.

    ``width``/``height`` scale the output (2x export etc.); omit them to render
    at the SVG's intrinsic size.
    """
    if not isinstance(svg, str) or not svg.strip():
        raise RasterizeError("empty SVG")

    try:
        import resvg_py
    except ImportError as exc:
        raise RasterizeError(
            "SVG rasterizer unavailable: resvg-py is not installed in this build"
        ) from exc

    fonts = font_files(base_dir)
    options = {
        "svg_string": svg,
        "font_files": fonts,
        # Deterministic output: never silently substitute a system font.
        "skip_system_fonts": bool(fonts),
        "text_rendering": "geometric_precision",
        "shape_rendering": "crisp_edges",
        "image_rendering": "optimize_quality",
    }
    if width is not None:
        options["width"] = int(width)
    if height is not None:
        options["height"] = int(height)
    if background:
        options["background"] = background

    try:
        raw = resvg_py.svg_to_bytes(**options)
    except Exception as exc:
        raise RasterizeError(f"SVG render failed: {exc}") from exc

    data = bytes(raw)
    if not data:
        raise RasterizeError("rasterizer produced no data")
    return data


def svg_to_image(svg: str, width=None, height=None, background=None,
                 base_dir: str | None = None):
    """Render an SVG to a PIL RGBA image."""
    from PIL import Image

    data = svg_to_png_bytes(svg, width, height, background, base_dir)
    image = Image.open(io.BytesIO(data))
    image.load()
    return image.convert("RGBA")
