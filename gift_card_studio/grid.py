"""Pure grid geometry for Gift Card Studio pages.

Single source of truth for the resize contract in the plan:

    cell_width  = (W - 2P - (C - 1)Gx) / C
    cell_height = (H - 2P - (R - 1)Gy) / R

Cards keep their own logical coordinate system (``card_width`` x
``card_height``) and are transformed uniformly into their cell, so a 1x5 page
scales five cards down to fit without any card re-authoring. The same functions
back the JS renderer (``static/gift-studio/grid.js``), the PNG/GIF exporters,
and the OBS output — one contract, no visual drift.

No I/O, no side effects, stdlib only.
"""
from __future__ import annotations

from .validation import (
    DEFAULT_FILL_ORDER,
    DEFAULT_FIT,
    FILL_ORDERS,
    FIT_MODES,
    MAX_CELLS_PER_PAGE,
)


class GridOverflow(ValueError):
    """Raised when a requested grid cannot hold the cards it was given."""


def cell_count(rows: int, columns: int) -> int:
    """Number of cells a rows x columns grid exposes."""
    return max(0, int(rows)) * max(0, int(columns))


def exceeds_cell_budget(rows: int, columns: int, budget: int = MAX_CELLS_PER_PAGE) -> bool:
    """True when rows x columns would exceed the per-page visible cell budget."""
    return cell_count(rows, columns) > budget


def cell_size(canvas_width, canvas_height, grid) -> tuple[float, float]:
    """Return ``(cell_width, cell_height)`` for a page grid.

    Never returns a negative size: an over-padded grid collapses to 0 rather
    than producing inverted geometry that would flip rendered content.
    """
    rows = max(1, int(grid.get("rows", 1)))
    columns = max(1, int(grid.get("columns", 1)))
    padding = float(grid.get("padding", 0) or 0)
    gap_x = float(grid.get("gap_x", 0) or 0)
    gap_y = float(grid.get("gap_y", 0) or 0)

    usable_w = float(canvas_width) - 2.0 * padding - (columns - 1) * gap_x
    usable_h = float(canvas_height) - 2.0 * padding - (rows - 1) * gap_y

    return max(0.0, usable_w / columns), max(0.0, usable_h / rows)


def cell_index(row: int, column: int, rows: int, columns: int, fill_order: str = DEFAULT_FILL_ORDER) -> int:
    """Flat index of a (row, column) position under the given fill order."""
    order = fill_order if fill_order in FILL_ORDERS else DEFAULT_FILL_ORDER
    if order == "column":
        return int(column) * int(rows) + int(row)
    return int(row) * int(columns) + int(column)


def cell_position(index: int, rows: int, columns: int, fill_order: str = DEFAULT_FILL_ORDER) -> tuple[int, int]:
    """Inverse of :func:`cell_index` — flat index to ``(row, column)``."""
    order = fill_order if fill_order in FILL_ORDERS else DEFAULT_FILL_ORDER
    rows = max(1, int(rows))
    columns = max(1, int(columns))
    index = max(0, int(index))
    if order == "column":
        return index % rows, index // rows
    return index // columns, index % columns


def cell_rect(index: int, canvas_width, canvas_height, grid) -> dict:
    """Absolute canvas rect for a flat cell index.

    Returns ``{"row", "column", "x", "y", "width", "height"}`` in canvas units.
    """
    rows = max(1, int(grid.get("rows", 1)))
    columns = max(1, int(grid.get("columns", 1)))
    padding = float(grid.get("padding", 0) or 0)
    gap_x = float(grid.get("gap_x", 0) or 0)
    gap_y = float(grid.get("gap_y", 0) or 0)
    fill_order = grid.get("fill_order", DEFAULT_FILL_ORDER)

    width, height = cell_size(canvas_width, canvas_height, grid)
    row, column = cell_position(index, rows, columns, fill_order)

    return {
        "row": row,
        "column": column,
        "x": padding + column * (width + gap_x),
        "y": padding + row * (height + gap_y),
        "width": width,
        "height": height,
    }


def cell_rects(canvas_width, canvas_height, grid) -> list[dict]:
    """Every cell rect for a page, ordered by flat index."""
    rows = max(1, int(grid.get("rows", 1)))
    columns = max(1, int(grid.get("columns", 1)))
    return [cell_rect(i, canvas_width, canvas_height, grid) for i in range(rows * columns)]


def fit_scale(card_width, card_height, cell_width, cell_height, fit: str = DEFAULT_FIT) -> tuple[float, float]:
    """Return ``(scale_x, scale_y)`` mapping a card's logical box into a cell.

    * ``contain`` — uniform scale, nothing clipped (default).
    * ``cover``   — uniform scale, cell fully covered, overflow clipped.
    * ``stretch`` — independent axes; explicit opt-in only.
    """
    mode = fit if fit in FIT_MODES else DEFAULT_FIT
    cw = float(card_width)
    ch = float(card_height)
    if cw <= 0 or ch <= 0:
        return 0.0, 0.0

    sx = float(cell_width) / cw
    sy = float(cell_height) / ch
    if mode == "stretch":
        return max(0.0, sx), max(0.0, sy)
    scale = min(sx, sy) if mode == "contain" else max(sx, sy)
    scale = max(0.0, scale)
    return scale, scale


def card_transform(card_width, card_height, cell, fit: str = DEFAULT_FIT) -> dict:
    """Placement of one card inside one cell rect.

    Returns the scale plus the absolute offset that centres the scaled card in
    its cell, so a renderer only needs
    ``translate(offset_x, offset_y) scale(scale_x, scale_y)``.
    """
    scale_x, scale_y = fit_scale(card_width, card_height, cell["width"], cell["height"], fit)
    scaled_w = float(card_width) * scale_x
    scaled_h = float(card_height) * scale_y
    return {
        "scale_x": scale_x,
        "scale_y": scale_y,
        "scaled_width": scaled_w,
        "scaled_height": scaled_h,
        "offset_x": cell["x"] + (cell["width"] - scaled_w) / 2.0,
        "offset_y": cell["y"] + (cell["height"] - scaled_h) / 2.0,
        "clipped": scaled_w > cell["width"] + 1e-9 or scaled_h > cell["height"] + 1e-9,
    }


def layout_page(page: dict, canvas: dict) -> list[dict]:
    """Resolve every card on a page to an absolute placement.

    Cards beyond the cell count are returned with ``"visible": False`` and no
    transform — the Studio surfaces them as overflow and only moves them when
    the user explicitly runs Auto-paginate. Nothing is silently dropped.
    """
    grid = page.get("grid") or {}
    cards = page.get("cards") or []
    canvas_width = canvas.get("width", 0)
    canvas_height = canvas.get("height", 0)
    fit = grid.get("fit", DEFAULT_FIT)

    rects = cell_rects(canvas_width, canvas_height, grid)
    placements: list[dict] = []

    for index, card in enumerate(cards):
        if index >= len(rects):
            placements.append({
                "card_id": card.get("id"),
                "index": index,
                "visible": False,
                "overflow": True,
                "cell": None,
                "transform": None,
            })
            continue
        cell = rects[index]
        card_w = float(card.get("width") or 0)
        card_h = float(card.get("height") or 0)
        placements.append({
            "card_id": card.get("id"),
            "index": index,
            "visible": True,
            "overflow": False,
            "cell": cell,
            "transform": card_transform(card_w, card_h, cell, fit),
        })

    return placements


def overflow_count(page: dict) -> int:
    """How many cards on this page currently have no cell."""
    grid = page.get("grid") or {}
    cards = page.get("cards") or []
    return max(0, len(cards) - cell_count(grid.get("rows", 1), grid.get("columns", 1)))


def content_extent(page: dict, canvas: dict) -> tuple[float, float]:
    """Bounding size of the laid-out content, used for scroll loop seams.

    Falls back to the canvas size when a page has no visible cards, so a
    scrolling empty page cannot produce a zero-length (infinite-speed) loop.
    """
    placements = [p for p in layout_page(page, canvas) if p["visible"]]
    if not placements:
        return float(canvas.get("width", 0) or 0), float(canvas.get("height", 0) or 0)
    grid = page.get("grid") or {}
    padding = float(grid.get("padding", 0) or 0)
    right = max(p["cell"]["x"] + p["cell"]["width"] for p in placements) + padding
    bottom = max(p["cell"]["y"] + p["cell"]["height"] for p in placements) + padding
    return right, bottom


# ---- Scroll strip layout -------------------------------------------------
#
# In scroll mode the grid means something different: rows/columns describe the
# *visible window* (a 1x5 grid shows five cards at a time) while every card in
# the page is laid out in one continuous strip that extends past the canvas.
# That is what makes scrolling worth having — a plain grid layout is always
# canvas-sized, so scrolling it would reveal nothing new and overflow cards
# would stay invisible forever.

def strip_track_count(card_count: int, rows: int, columns: int, horizontal: bool) -> int:
    """How many columns (horizontal) or rows (vertical) the strip needs."""
    card_count = max(0, int(card_count))
    if card_count == 0:
        return 0
    across = max(1, int(rows if horizontal else columns))
    return -(-card_count // across)  # ceil division


def strip_layout(page: dict, canvas: dict, horizontal=True, item_gap=None) -> list[dict]:
    """Absolute placements for every card in a scrolling strip.

    Cell size still comes from the grid (so a card looks the same scrolling as
    it does in a static page), but positions continue past the canvas edge
    instead of being clipped to the visible cell count.
    """
    g = page.get("grid") or {}
    cards = page.get("cards") or []
    rows = max(1, int(g.get("rows", 1) or 1))
    columns = max(1, int(g.get("columns", 1) or 1))
    padding = float(g.get("padding", 0) or 0)
    gap_x = float(g.get("gap_x", 0) or 0)
    gap_y = float(g.get("gap_y", 0) or 0)
    fit = g.get("fit", DEFAULT_FIT)

    cell_w, cell_h = cell_size(canvas.get("width", 0), canvas.get("height", 0), g)

    # The gap along the scroll axis may be overridden by scroll.item_gap so a
    # ticker can be spaced differently from a static page.
    advance_gap = gap_x if horizontal else gap_y
    if item_gap is not None:
        advance_gap = float(item_gap)
    cross_gap = gap_y if horizontal else gap_x

    across = rows if horizontal else columns
    placements: list[dict] = []

    for index, card in enumerate(cards):
        # A horizontal strip fills each column top-to-bottom before advancing
        # right; a vertical strip fills each row left-to-right before advancing
        # down. Either way the scroll axis is the one that grows without bound.
        track, slot = divmod(index, max(1, across))

        if horizontal:
            x = padding + track * (cell_w + advance_gap)
            y = padding + slot * (cell_h + cross_gap)
        else:
            x = padding + slot * (cell_w + cross_gap)
            y = padding + track * (cell_h + advance_gap)

        cell = {"row": slot if horizontal else track,
                "column": track if horizontal else slot,
                "x": x, "y": y, "width": cell_w, "height": cell_h}
        placements.append({
            "card_id": card.get("id"),
            "index": index,
            "visible": True,
            "overflow": False,
            "cell": cell,
            "transform": card_transform(
                float(card.get("width") or 0), float(card.get("height") or 0), cell, fit
            ),
        })

    return placements


def strip_extent(page: dict, canvas: dict, horizontal=True, item_gap=None) -> float:
    """Length of the scrolling strip along its scroll axis, in canvas units.

    Returns 0 for an empty page so a scroll cycle cannot become zero-length
    (which would mean infinite speed).
    """
    cards = page.get("cards") or []
    if not cards:
        return 0.0

    g = page.get("grid") or {}
    rows = max(1, int(g.get("rows", 1) or 1))
    columns = max(1, int(g.get("columns", 1) or 1))
    padding = float(g.get("padding", 0) or 0)
    gap = float((g.get("gap_x") if horizontal else g.get("gap_y")) or 0)
    if item_gap is not None:
        gap = float(item_gap)

    cell_w, cell_h = cell_size(canvas.get("width", 0), canvas.get("height", 0), g)
    size = cell_w if horizontal else cell_h
    tracks = strip_track_count(len(cards), rows, columns, horizontal)

    return max(0.0, tracks * size + max(0, tracks - 1) * gap + 2 * padding)
