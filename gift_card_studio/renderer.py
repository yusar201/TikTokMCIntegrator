"""SVG renderer (Python mirror of ``static/gift-studio/renderer.js``).

Why two implementations rather than one? The browser needs JS (editor preview,
OBS output) and the exporter needs Python (the frozen Windows exe cannot depend
on Node being installed). Shelling out to a browser for export would also mean
the export blocks on a WebView2 process during a live stream — exactly what the
plan forbids.

So both exist, and ``tests/test_gift_card_studio_renderer_parity.py`` asserts
they emit byte-identical SVG for the same project. If they ever drift the test
fails, instead of an export silently not matching the preview.

Pure module: stdlib only, no I/O, no rasterizer import.
"""
from __future__ import annotations

import re

from .grid import cell_rects, card_transform, layout_page, strip_layout
from .numeric import js_round

XML_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;"}

_HTTPS_URL = re.compile(r"^https://[^\s\"'<>]+$", re.IGNORECASE)
_ABS_PATH = re.compile(r"^/[^/\s\"'<>]([^\s\"'<>]*)?$")
_DATA_IMAGE = re.compile(
    r"^data:image/(png|jpeg|jpg|webp|gif);base64,[a-z0-9+/=\s]+$", re.IGNORECASE
)
_HEX_COLOR = re.compile(r"^#[0-9a-f]{3,8}$", re.IGNORECASE)

ANCHORS = {"left": "start", "center": "middle", "right": "end"}
IMAGE_FIT_MAP = {"contain": "xMidYMid meet", "cover": "xMidYMid slice", "fill": "none"}


def escape_xml(value) -> str:
    """Escape text for SVG content or an attribute value."""
    if value is None:
        return ""
    return "".join(XML_ESCAPES.get(ch, ch) for ch in str(value))


def sanitize_asset_url(value) -> str:
    """Allowlist an asset reference.

    Permitted: same-origin absolute paths, https URLs, data:image base64.
    Rejected: javascript:/vbscript:, data:text/html, protocol-relative //host,
    plain http, and anything else that could execute or phone out.
    """
    if not isinstance(value, str):
        return ""
    url = value.strip()
    if not url or url.startswith("//"):
        return ""
    if _DATA_IMAGE.match(url):
        return url
    if _HTTPS_URL.match(url):
        return url
    if _ABS_PATH.match(url):
        return url
    return ""


def _num(value, fallback=0.0) -> float:
    try:
        if isinstance(value, bool):
            raise TypeError
        parsed = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return float(fallback)
    return parsed


def _js_round(value: float) -> int:
    """Round half up, matching JS ``Math.round``. See ``numeric.js_round``."""
    return js_round(value)


def _round(value) -> str:
    """Round to 3dp and format like JS Number->string (no trailing .0)."""
    rounded = js_round(_num(value) * 1000) / 1000
    if rounded == int(rounded):
        return str(int(rounded))
    return repr(rounded)


def _color_or_none(value) -> str:
    if not isinstance(value, str) or value == "" or value == "transparent":
        return "none"
    return value if _HEX_COLOR.match(value) else "none"


def _opacity_attr(layer) -> str:
    opacity = _num(layer.get("opacity"), 1.0)
    return "" if opacity >= 1 else f' opacity="{_round(opacity)}"'


def _rotation_transform(layer) -> str:
    rotation = _num(layer.get("rotation"), 0.0)
    if rotation == 0:
        return ""
    cx = _round(_num(layer.get("x")) + _num(layer.get("width")) / 2)
    cy = _round(_num(layer.get("y")) + _num(layer.get("height")) / 2)
    return f' transform="rotate({_round(rotation)} {cx} {cy})"'


# ---- Shapes --------------------------------------------------------------

def _corner_staircase(cx, cy, sx, sy, tiers, unit):
    """Points tracing one stepped corner as a right-angled staircase.

    ``(cx, cy)`` is the notional sharp corner; ``sx``/``sy`` are +1/-1 unit
    vectors pointing inward along each axis. The returned run starts on the
    ``sy`` edge and ends on the ``sx`` edge, and never includes the sharp corner
    itself — that is the whole point: the corner square is removed and the
    outline detours around it in axis-aligned steps.

    For ``tiers=1, unit=u`` this is ``(0,u) -> (u,u) -> (u,0)``: one square
    notched out. For ``tiers=2`` it is a two-step staircase, and so on. A single
    diagonal segment (the previous behaviour) renders as a smooth 45-degree
    bevel — an octagon, not pixel art.
    """
    points = []
    for index in range(tiers):
        tread = cy + sy * (tiers - index) * unit
        points.append((cx + sx * index * unit, tread))
        points.append((cx + sx * (index + 1) * unit, tread))
    points.append((cx + sx * tiers * unit, cy))
    return points


def _stepped_polygon(x, y, w, h, unit, tiers=1) -> str:
    """Panel outline with stepped pixel corners on all four sides."""
    unit = max(0.0, float(unit))
    tiers = max(1, int(tiers))

    # Never let the corner treatment eat more than a third of the shorter side,
    # or opposite corners would meet and the panel would collapse.
    budget = min(w, h) / 3.0
    while tiers > 1 and tiers * unit > budget:
        tiers -= 1
    if tiers * unit > budget and budget > 0:
        unit = budget / tiers

    if unit <= 0:
        points = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    else:
        # Clockwise from the top-left. Each corner's staircase runs from its
        # vertical edge to its horizontal edge, so alternate corners are
        # reversed to keep one continuous path.
        points = []
        points += _corner_staircase(x, y, 1, 1, tiers, unit)          # left -> top
        points += _corner_staircase(x + w, y, -1, 1, tiers, unit)[::-1]  # top -> right
        points += _corner_staircase(x + w, y + h, -1, -1, tiers, unit)   # right -> bottom
        points += _corner_staircase(x, y + h, 1, -1, tiers, unit)[::-1]  # bottom -> left

    # Consecutive duplicates add nothing and just bloat the markup.
    deduped = [points[0]]
    for point in points[1:]:
        if point != deduped[-1]:
            deduped.append(point)
    if len(deduped) > 1 and deduped[0] == deduped[-1]:
        deduped.pop()

    return " ".join(f"{_round(px)},{_round(py)}" for px, py in deduped)


def render_shape(layer) -> str:
    kind = layer.get("kind") or "panel"
    x = _num(layer.get("x"))
    y = _num(layer.get("y"))
    w = _num(layer.get("width"))
    h = _num(layer.get("height"))
    fill = _color_or_none(layer.get("fill"))
    stroke = _color_or_none(layer.get("border_color"))
    stroke_width = _round(_num(layer.get("border_width"), 0.0))
    common = f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"'

    if kind == "divider":
        mid_y = _round(y + h / 2)
        line_stroke = fill if stroke == "none" else stroke
        width_value = stroke_width if _num(layer.get("border_width"), 0.0) > 0 else "2"
        return (
            f'<line x1="{_round(x)}" y1="{mid_y}" x2="{_round(x + w)}" y2="{mid_y}" '
            f'stroke="{line_stroke}" stroke-width="{width_value}"'
            f"{_opacity_attr(layer)}{_rotation_transform(layer)} />"
        )

    if kind == "pixel_border":
        unit = max(1.0, round(_num(layer.get("pixel_steps"), 3.0) * 1000) / 1000)
        tiers = max(1, int(_num(layer.get("pixel_tiers"), 3.0)))
        points = _stepped_polygon(x, y, w, h, unit, tiers)
        return (
            f'<polygon points="{points}" {common} stroke-linejoin="miter"'
            f"{_opacity_attr(layer)}{_rotation_transform(layer)} />"
        )

    unit = _num(layer.get("pixel_steps"), 0.0)
    if unit > 0:
        tiers = max(1, int(_num(layer.get("pixel_tiers"), 1.0)))
        points = _stepped_polygon(x, y, w, h, unit, tiers)
        return (
            f'<polygon points="{points}" {common} stroke-linejoin="miter"'
            f"{_opacity_attr(layer)}{_rotation_transform(layer)} />"
        )

    radius = _num(layer.get("corner_radius"), 0.0)
    rx = f' rx="{_round(radius)}"' if radius > 0 else ""
    return (
        f'<rect x="{_round(x)}" y="{_round(y)}" width="{_round(w)}" height="{_round(h)}"'
        f"{rx} {common}{_opacity_attr(layer)}{_rotation_transform(layer)} />"
    )


# ---- Images --------------------------------------------------------------

def render_image(layer, context=None) -> str:
    context = context or {}
    source = layer.get("asset")
    if layer.get("type") == "gift_icon" and layer.get("auto_link") is not False and not source:
        source = (context.get("gift_ref") or {}).get("icon")
    if layer.get("type") == "action_icon" and not source and context.get("resolve_action_icon"):
        source = context["resolve_action_icon"](layer.get("intent"))

    href = sanitize_asset_url(source)
    if not href and layer.get("type") == "action_icon":
        return _render_action_placeholder(layer)
    if not href:
        return ""

    preserve = IMAGE_FIT_MAP.get(layer.get("fit"), IMAGE_FIT_MAP["contain"])
    rendering = "" if layer.get("pixelated") is False else ' image-rendering="pixelated"'

    return (
        f'<image x="{_round(layer.get("x"))}" y="{_round(layer.get("y"))}" '
        f'width="{_round(layer.get("width"))}" height="{_round(layer.get("height"))}" '
        f'href="{escape_xml(href)}" preserveAspectRatio="{preserve}"'
        f"{rendering}{_opacity_attr(layer)}{_rotation_transform(layer)} />"
    )


def _render_action_placeholder(layer) -> str:
    x, y = _num(layer.get("x")), _num(layer.get("y"))
    w, h = _num(layer.get("width")), _num(layer.get("height"))
    unit = max(2.0, round(min(w, h) * 0.045, 3))
    cx, cy = x + w / 2, y + h / 2
    icon = max(unit * 3, round(min(w, h) * 0.22, 3))
    return (
        f'<g data-action-placeholder="true"{_opacity_attr(layer)}{_rotation_transform(layer)}>'
        f'<rect x="{_round(x)}" y="{_round(y)}" width="{_round(w)}" height="{_round(h)}" fill="#20242d" '
        f'stroke="#697386" stroke-width="{_round(unit)}" stroke-dasharray="{_round(unit * 2)} {_round(unit)}" />'
        f'<rect x="{_round(cx-icon/2)}" y="{_round(cy-unit/2)}" width="{_round(icon)}" height="{_round(unit)}" fill="#aeb8ca" />'
        f'<rect x="{_round(cx-unit/2)}" y="{_round(cy-icon/2)}" width="{_round(unit)}" height="{_round(icon)}" fill="#aeb8ca" />'
        '</g>'
    )


# ---- Text ----------------------------------------------------------------

def _text_lines(layer) -> list[str]:
    raw = str(layer.get("text") or "")
    if layer.get("uppercase"):
        raw = raw.upper()
    return raw.split("\n")


def _effective_font_size(layer) -> float:
    size = _num(layer.get("font_size"), 32.0)
    if not layer.get("responsive_text"):
        return size
    lines = _text_lines(layer)
    longest = max((len(line) for line in lines), default=0)
    if longest == 0:
        return size
    box_width = _num(layer.get("width"), 0.0)
    estimated = longest * size * 0.58
    if estimated <= box_width or box_width <= 0:
        return size
    return max(1.0, size * (box_width / estimated))


def render_text(layer) -> str:
    lines = _text_lines(layer)
    if len(lines) == 1 and lines[0] == "":
        return ""

    font_size = _effective_font_size(layer)
    line_height = font_size * _num(layer.get("line_height"), 1.2)
    anchor = ANCHORS.get(layer.get("align"), "middle")

    x = _num(layer.get("x"))
    w = _num(layer.get("width"))
    if anchor == "start":
        text_x = x
    elif anchor == "end":
        text_x = x + w
    else:
        text_x = x + w / 2

    y = _num(layer.get("y"))
    h = _num(layer.get("height"))
    block_height = line_height * len(lines)
    vertical = layer.get("vertical_align")
    if vertical == "top":
        first_baseline = y + font_size
    elif vertical == "bottom":
        first_baseline = y + h - block_height + font_size
    else:
        first_baseline = y + (h - block_height) / 2 + font_size

    stroke = _color_or_none(layer.get("stroke_color"))
    stroke_width = _num(layer.get("stroke_width"), 0.0)
    if stroke != "none" and stroke_width > 0:
        stroke_attrs = (
            f' stroke="{stroke}" stroke-width="{_round(stroke_width)}" paint-order="stroke"'
        )
    else:
        stroke_attrs = ""

    spacing = _num(layer.get("letter_spacing"), 0.0)
    spacing_attr = "" if spacing == 0 else f' letter-spacing="{_round(spacing)}"'
    weight = ' font-weight="bold"' if layer.get("font_weight") == "bold" else ""

    tspans = "".join(
        f'<tspan x="{_round(text_x)}" y="{_round(first_baseline + index * line_height)}">'
        f"{escape_xml(line)}</tspan>"
        for index, line in enumerate(lines)
    )

    return (
        f'<text font-family="{escape_xml(layer.get("font_family") or "Minecraft")}" '
        f'font-size="{_round(font_size)}"{weight} fill="{_color_or_none(layer.get("color"))}" '
        f'text-anchor="{anchor}"{spacing_attr}{stroke_attrs}'
        f"{_opacity_attr(layer)}{_rotation_transform(layer)}>{tspans}</text>"
    )


def render_layer(layer, context=None) -> str:
    if not layer or layer.get("visible") is False:
        return ""
    layer_type = layer.get("type")
    if layer_type == "shape":
        return render_shape(layer)
    if layer_type == "text":
        return render_text(layer)
    if layer_type in ("image", "gift_icon", "action_icon"):
        return render_image(layer, context)
    return ""


def render_card_body(card, context=None) -> str:
    if not card:
        return ""
    context = dict(context or {})
    context["gift_ref"] = card.get("gift_ref") or {}
    layers = sorted(card.get("layers") or [], key=lambda item: _num(item.get("z_index"), 0.0))
    return "".join(render_layer(layer, context) for layer in layers)


def render_card_svg(card, context=None) -> str:
    width = _round(_num((card or {}).get("width"), 320.0))
    height = _round(_num((card or {}).get("height"), 400.0))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">{render_card_body(card, context)}</svg>'
    )


# ---- Pages ---------------------------------------------------------------

def _canvas_background(canvas) -> str:
    background = _color_or_none((canvas or {}).get("background"))
    if background == "none":
        return ""
    return (
        f'<rect x="0" y="0" width="{_round(canvas.get("width"))}" '
        f'height="{_round(canvas.get("height"))}" fill="{background}" />'
    )


def _render_placements(placements, cards, context, fit_cover) -> str:
    parts = []
    for placement in placements:
        if not placement["visible"]:
            continue
        card = cards[placement["index"]]
        transform = placement["transform"]
        body = render_card_body(card, context)
        if not body:
            continue
        group = (
            f'<g transform="translate({_round(transform["offset_x"])} '
            f'{_round(transform["offset_y"])}) scale({_round(transform["scale_x"])} '
            f'{_round(transform["scale_y"])})">{body}</g>'
        )
        if not fit_cover or not transform["clipped"]:
            parts.append(group)
            continue
        clip_id = f'clip-{escape_xml(str(placement["index"]))}'
        cell = placement["cell"]
        parts.append(
            f'<clipPath id="{clip_id}"><rect x="{_round(cell["x"])}" y="{_round(cell["y"])}" '
            f'width="{_round(cell["width"])}" height="{_round(cell["height"])}" /></clipPath>'
            f'<g clip-path="url(#{clip_id})">{group}</g>'
        )
    return "".join(parts)


def render_page_body(page, canvas, context=None) -> str:
    """Render a page's cards into the grid, each scaled into its cell."""
    if not page:
        return ""
    cards = page.get("cards") or []
    fit_cover = (page.get("grid") or {}).get("fit") == "cover"
    placements = layout_page(page, canvas or {})
    return _render_placements(placements, cards, context, fit_cover)


def render_page_svg(page, canvas, context=None) -> str:
    """Full page SVG — page preview, page PNG export, and GIF frames."""
    width = _num((canvas or {}).get("width"), 1920.0)
    height = _num((canvas or {}).get("height"), 1080.0)
    resolved = {"width": width, "height": height, "background": (canvas or {}).get("background")}
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_round(width)}" '
        f'height="{_round(height)}" viewBox="0 0 {_round(width)} {_round(height)}">'
        f"{_canvas_background(resolved)}{render_page_body(page, resolved, context)}</svg>"
    )


def render_strip_body(page, canvas, context=None, horizontal=True, item_gap=None) -> str:
    """Render a scrolling strip: every card, laid out past the canvas edge."""
    if not page:
        return ""
    cards = page.get("cards") or []
    placements = strip_layout(page, canvas or {}, horizontal, item_gap)
    fit_cover = (page.get("grid") or {}).get("fit") == "cover"
    return _render_placements(placements, cards, context, fit_cover)


def render_grid_guides(page, canvas, stroke="#4a4a55") -> str:
    """Editor-only grid guides. Never included in an export."""
    rects = cell_rects(
        _num((canvas or {}).get("width"), 0.0),
        _num((canvas or {}).get("height"), 0.0),
        (page or {}).get("grid") or {},
    )
    return "".join(
        f'<rect x="{_round(cell["x"])}" y="{_round(cell["y"])}" '
        f'width="{_round(cell["width"])}" height="{_round(cell["height"])}" '
        f'fill="none" stroke="{_color_or_none(stroke)}" stroke-width="1" '
        'stroke-dasharray="4 4" />'
        for cell in rects
    )


__all__ = [
    "escape_xml",
    "sanitize_asset_url",
    "render_layer",
    "render_card_body",
    "render_card_svg",
    "render_page_body",
    "render_page_svg",
    "render_strip_body",
    "render_grid_guides",
    "card_transform",
    "cell_rects",
    "layout_page",
]
