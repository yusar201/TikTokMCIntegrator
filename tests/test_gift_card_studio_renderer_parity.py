"""Gift Card Studio — Python/JS renderer parity.

``gift_card_studio/renderer.py`` (used by the PNG/GIF exporter) and
``static/gift-studio/renderer.js`` (used by the editor preview and OBS output)
must emit byte-identical SVG. If they drift, an export stops matching what Khito
designed — the exact failure the shared-renderer decision exists to prevent.

Skips (does not fail) when Node is unavailable.
"""

import shutil
from pathlib import Path

import pytest

from gift_card_studio import models, renderer
from tests.js_parity import run_node_with_payload

ROOT = Path(__file__).resolve().parents[1]
JS_RENDERER = ROOT / "static" / "gift-studio" / "renderer.js"

NODE = shutil.which("node") or ""
pytestmark = pytest.mark.skipif(not NODE, reason="node is not installed")


def _card(layers, width=320, height=400, gift_icon=""):
    return models.normalize_card({
        "name": "Parity Card",
        "width": width,
        "height": height,
        "gift_ref": {"gift_id": "5487", "name": "finger heart", "icon": gift_icon},
        "layers": layers,
    })


CARDS = {
    "panel_and_text": _card([
        {"type": "shape", "kind": "panel", "x": 0, "y": 0, "width": 320, "height": 400,
         "fill": "#16161a", "border_color": "#3a3a42", "border_width": 3, "pixel_steps": 3},
        {"type": "text", "role": "main", "text": "Vex", "x": 26, "y": 210,
         "width": 268, "height": 64, "font_size": 30, "align": "center", "color": "#ffffff"},
    ]),
    "every_layer_type": _card([
        {"type": "shape", "kind": "pixel_border", "x": 4, "y": 4, "width": 312, "height": 392,
         "fill": "#101014", "border_color": "#5a5a66", "border_width": 2, "pixel_steps": 4},
        {"type": "gift_icon", "auto_link": True, "x": 80, "y": 26, "width": 160, "height": 160},
        {"type": "action_icon", "intent": "mob", "asset": "/gift-studio-assets/mob.png",
         "x": 250, "y": 26, "width": 58, "height": 58},
        {"type": "image", "asset": "https://p16-webcast.tiktokcdn.com/img/x.png",
         "x": 20, "y": 300, "width": 60, "height": 60, "fit": "cover", "pixelated": False},
        {"type": "text", "role": "secondary", "text": "200 Coins", "x": 26, "y": 280,
         "width": 268, "height": 44, "font_size": 20, "align": "right", "color": "#ffd479",
         "stroke_color": "#000000", "stroke_width": 2, "letter_spacing": 1.5},
        {"type": "shape", "kind": "divider", "x": 40, "y": 270, "width": 240, "height": 8,
         "fill": "#3a3a42", "border_width": 2},
    ], gift_icon="/gift_assets/5487.png"),
    "text_edge_cases": _card([
        {"type": "text", "text": "line one\nline two\nline three", "x": 10, "y": 10,
         "width": 300, "height": 120, "font_size": 24, "align": "left",
         "vertical_align": "top", "line_height": 1.4},
        {"type": "text", "text": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "x": 10, "y": 140,
         "width": 120, "height": 40, "font_size": 40, "responsive_text": True},
        {"type": "text", "text": "<script>&\"'", "x": 10, "y": 200, "width": 300,
         "height": 40, "font_size": 18, "vertical_align": "bottom"},
        {"type": "text", "text": "wither", "uppercase": True, "x": 10, "y": 250,
         "width": 300, "height": 40, "font_weight": "bold", "font_family": "Minecraft"},
    ]),
    "transforms": _card([
        {"type": "shape", "kind": "panel", "x": 20, "y": 20, "width": 100, "height": 60,
         "rotation": 15, "opacity": 0.5, "fill": "#ff0000", "corner_radius": 8},
        {"type": "text", "text": "rotated", "x": 20, "y": 120, "width": 200, "height": 40,
         "rotation": -7.5, "opacity": 0.25},
        {"type": "shape", "kind": "panel", "x": 0, "y": 0, "width": 50, "height": 50,
         "fill": "url(#evil)", "border_color": "not-a-color"},
    ]),
    "stepped_corners": _card([
        # Multi-tier staircase corners: the Minecraft panel look. Each tier
        # count and step size must produce identical vertex lists on both sides.
        {"type": "shape", "kind": "pixel_border", "x": 0, "y": 0, "width": 320, "height": 320,
         "fill": "#16161a", "border_color": "#3a3a42", "border_width": 4,
         "pixel_steps": 6, "pixel_tiers": 3},
        {"type": "shape", "kind": "panel", "x": 20, "y": 20, "width": 100, "height": 100,
         "fill": "#22222a", "pixel_steps": 4, "pixel_tiers": 2},
        {"type": "shape", "kind": "panel", "x": 140, "y": 20, "width": 60, "height": 60,
         "fill": "#22222a", "pixel_steps": 8, "pixel_tiers": 1},
        # Deliberately over-budget: tiers must clamp identically in both.
        {"type": "shape", "kind": "pixel_border", "x": 220, "y": 20, "width": 30, "height": 30,
         "fill": "#22222a", "pixel_steps": 12, "pixel_tiers": 4},
    ]),
    "hidden_and_ordered": _card([
        {"type": "text", "text": "TOP", "z_index": 90, "x": 0, "y": 0, "width": 100, "height": 30},
        {"type": "shape", "kind": "panel", "z_index": 5, "x": 0, "y": 0, "width": 100, "height": 100},
        {"type": "text", "text": "HIDDEN", "visible": False, "z_index": 50},
        {"type": "image", "asset": "javascript:alert(1)", "z_index": 60},
        {"type": "text", "text": "", "z_index": 70},
    ]),
}


def _page(cards, grid_overrides=None, canvas=None):
    payload = {
        "grid": {"rows": 1, "columns": 5, "gap_x": 20, "gap_y": 20, "padding": 24,
                 "fill_order": "row", "fit": "contain", **(grid_overrides or {})},
        "cards": cards,
    }
    return models.normalize_page(payload)


PAGES = {
    "one_by_five": (_page([CARDS["panel_and_text"]] * 5), {"width": 1920, "height": 1080, "background": "transparent"}),
    "overflow": (_page([CARDS["panel_and_text"]] * 7), {"width": 1920, "height": 1080, "background": "transparent"}),
    "cover_clip": (_page([CARDS["every_layer_type"]] * 2, {"rows": 1, "columns": 2, "fit": "cover"}),
                   {"width": 1920, "height": 1080, "background": "transparent"}),
    "solid_bg_portrait": (_page([CARDS["text_edge_cases"]] * 3, {"rows": 3, "columns": 1}),
                          {"width": 1080, "height": 1920, "background": "#101014"}),
    "stretch_grid": (_page([CARDS["transforms"]] * 6, {"rows": 2, "columns": 3, "fit": "stretch"}),
                     {"width": 1280, "height": 720, "background": "transparent"}),
    "empty": (_page([]), {"width": 800, "height": 600, "background": "transparent"}),
}


NODE_SCRIPT = """
import * as r from %(module)s;
const fixture = %(payload)s;
const { cards, pages } = fixture;
const out = { cards: {}, pages: {}, guides: {} };
for (const [name, card] of Object.entries(cards)) {
  out.cards[name] = r.renderCardSvg(card);
}
for (const [name, entry] of Object.entries(pages)) {
  out.pages[name] = r.renderPageSvg(entry.page, entry.canvas);
  out.guides[name] = r.renderGridGuides(entry.page, entry.canvas);
}
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js_output():
    payload = {
        "cards": CARDS,
        "pages": {
            name: {"page": page, "canvas": canvas}
            for name, (page, canvas) in PAGES.items()
        },
    }
    return run_node_with_payload(NODE_SCRIPT, payload, ROOT, JS_RENDERER)


class TestRendererParity:

    @pytest.mark.parametrize("name", list(CARDS))
    def test_card_svg_is_byte_identical(self, js_output, name):
        assert renderer.render_card_svg(CARDS[name]) == js_output["cards"][name]

    @pytest.mark.parametrize("name", list(PAGES))
    def test_page_svg_is_byte_identical(self, js_output, name):
        page, canvas = PAGES[name]
        assert renderer.render_page_svg(page, canvas) == js_output["pages"][name]

    @pytest.mark.parametrize("name", list(PAGES))
    def test_grid_guides_are_byte_identical(self, js_output, name):
        page, canvas = PAGES[name]
        assert renderer.render_grid_guides(page, canvas) == js_output["guides"][name]

    def test_the_parity_suite_actually_produces_markup(self, js_output):
        """Guard against a vacuous pass where both sides return empty strings."""
        for name in CARDS:
            assert len(js_output["cards"][name]) > 100, name
        assert "<image" in js_output["cards"]["every_layer_type"]
        assert "<polygon" in js_output["cards"]["every_layer_type"]
        assert "<line" in js_output["cards"]["every_layer_type"]
        assert "<tspan" in js_output["cards"]["text_edge_cases"]
        assert "<clipPath" in js_output["pages"]["cover_clip"]
