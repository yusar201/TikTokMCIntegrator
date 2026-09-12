"""Gift Card Studio — Python/JS frame-composition parity.

``gift_card_studio/frame.py`` composes the frames the PNG/GIF exporter
rasterizes; ``static/gift-studio/frame.js`` composes the frames the OBS output
and editor preview paint. A cross-fade, slide, pixel wipe, or scroll seam that
differs between them means the exported GIF is not the animation Khito saw.

Skips (does not fail) when Node is unavailable.
"""

import shutil
from pathlib import Path

import pytest

from gift_card_studio import catalog, frame, models
from tests.js_parity import run_node_with_payload

ROOT = Path(__file__).resolve().parents[1]
JS_FRAME = ROOT / "static" / "gift-studio" / "frame.js"

NODE = shutil.which("node") or ""
pytestmark = pytest.mark.skipif(not NODE, reason="node is not installed")


def _entry(key, label, intent_command="spawnmob {mc} 5 vex {user}"):
    config = {
        "Gifts": {"5487": [intent_command, f"titlecustom '{{user}}' {{mc}} {label}"]},
        "GiftNames": {"5487": "finger heart"},
        "GiftCategories": {"5487": "5 Coins"},
    }
    entry = catalog.build_catalog(config, "/nonexistent", "/nonexistent")[0]
    entry["key"] = key
    entry["name"] = label
    entry["suggested_text"] = {"main": label, "secondary": "5 Coins"}
    entry["icon"] = f"/gift-studio-assets/gift-{key}.png"
    return entry


def _paged(transition, duration=1000, pages=2, canvas=(960, 540), loop=True,
           include_action_icon=True):
    payload = models.new_project(f"Frame {transition}")
    payload["canvas"].update({
        "width": canvas[0], "height": canvas[1], "background": "transparent",
    })
    payload["playback"].update({
        "mode": "pages", "loop": loop,
        "default_page_duration_ms": duration,
        "default_transition": transition,
    })
    payload["pages"][0]["grid"].update({"rows": 1, "columns": 3, "gap_x": 12, "padding": 16})
    project = models.normalize_project(payload)
    project = catalog.apply_catalog_import(
        project, [_entry(f"a{i}", f"A{i}") for i in range(3)],
        include_action_icon=include_action_icon,
    )["project"]

    for index in range(1, pages):
        project["pages"].append(models.default_page(index))
        project = models.normalize_project(project)
        project["pages"][index]["grid"].update(
            {"rows": 1, "columns": 3, "gap_x": 12, "padding": 16}
        )
        project = catalog.apply_catalog_import(
            models.normalize_project(project),
            [_entry(f"p{index}c{i}", f"P{index}C{i}") for i in range(3)],
            include_action_icon=include_action_icon,
        )["project"]
    return project


def _scroll(direction, speed=120.0, loop=True, edge_pause=0, cards=8,
            item_gap=12, canvas=(960, 260)):
    payload = models.new_project(f"Scroll {direction}")
    payload["canvas"].update({
        "width": canvas[0], "height": canvas[1], "background": "transparent",
    })
    payload["playback"]["mode"] = "scroll"
    payload["pages"][0]["grid"].update({"rows": 1, "columns": 4, "gap_x": 12, "padding": 12})
    payload["pages"][0]["scroll"].update({
        "enabled": True, "direction": direction, "speed_px_per_second": speed,
        "loop": loop, "item_gap": item_gap, "edge_pause_ms": edge_pause,
    })
    project = models.normalize_project(payload)
    return catalog.apply_catalog_import(
        project, [_entry(f"s{i}", f"S{i}") for i in range(cards)]
    )["project"]


PROJECTS = {
    "cut": _paged({"type": "cut", "duration_ms": 0}),
    "fade": _paged({"type": "fade", "duration_ms": 400}),
    "slide": _paged({"type": "slide", "duration_ms": 400}),
    "pixel_wipe": _paged({"type": "pixel_wipe", "duration_ms": 500}),
    "wipe_three_pages": _paged({"type": "pixel_wipe", "duration_ms": 300}, pages=3),
    "fade_noloop": _paged({"type": "fade", "duration_ms": 400}, loop=False, pages=3),
    "clamped_transition": _paged({"type": "slide", "duration_ms": 5000}, duration=400),
    "no_action_icons": _paged(
        {"type": "fade", "duration_ms": 400}, include_action_icon=False
    ),
    "solid_background": _paged({"type": "fade", "duration_ms": 400}),
    "scroll_left": _scroll("left"),
    "scroll_right": _scroll("right"),
    "scroll_up": _scroll("up", canvas=(300, 540)),
    "scroll_down": _scroll("down", canvas=(300, 540)),
    "scroll_noloop": _scroll("left", loop=False, edge_pause=400),
    "scroll_paused": _scroll("left", edge_pause=800),
    "scroll_gapless": _scroll("left", item_gap=0),
}
PROJECTS["solid_background"]["canvas"]["background"] = "#101014"
PROJECTS["solid_background"] = models.normalize_project(PROJECTS["solid_background"])

# Sampled densely around transition boundaries, where the two implementations are
# most likely to disagree (rounding, clamping, seam wrap).
SAMPLE_TIMES = [
    0, 1, 33, 66, 99, 199, 200, 201, 299, 300, 399, 400, 401,
    500, 666, 999, 1000, 1001, 1199, 1200, 1399, 1400,
    1999, 2000, 2001, 2500, 2999, 3000, 4000, 5500, 7777, 9999,
    12_345, 15_930, 20_000,
]

NODE_SCRIPT = """
import * as f from %(module)s;
const fixture = %(payload)s;
const out = {};
for (const [name, entry] of Object.entries(fixture.projects)) {
  out[name] = fixture.times.map((t) => f.frameSvg(entry, t));
}
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js_frames():
    payload = {"projects": PROJECTS, "times": SAMPLE_TIMES}
    return run_node_with_payload(NODE_SCRIPT, payload, ROOT, JS_FRAME)


class TestFrameParity:

    @pytest.mark.parametrize("name", list(PROJECTS))
    def test_every_sampled_frame_is_byte_identical(self, js_frames, name):
        project = PROJECTS[name]
        for time_ms, expected in zip(SAMPLE_TIMES, js_frames[name]):
            assert frame.frame_svg(project, time_ms) == expected, (name, time_ms)

    def test_the_parity_suite_actually_produces_markup(self, js_frames):
        """Guard against a vacuous pass where both sides return empty frames."""
        for name in PROJECTS:
            assert all(len(svg) > 200 for svg in js_frames[name]), name

    def test_a_cross_fade_really_emits_two_opacity_groups(self, js_frames):
        mid_fade = js_frames["fade"][SAMPLE_TIMES.index(200)]

        assert mid_fade.count("<g opacity=") == 2

    def test_a_slide_really_emits_two_translated_groups(self, js_frames):
        mid_slide = js_frames["slide"][SAMPLE_TIMES.index(200)]

        assert mid_slide.count('transform="translate(') >= 2

    def test_a_pixel_wipe_really_emits_a_clip_path(self, js_frames):
        mid_wipe = js_frames["pixel_wipe"][SAMPLE_TIMES.index(300)]

        assert "<clipPath id=" in mid_wipe
        assert "clip-path=" in mid_wipe

    def test_a_cut_never_emits_transition_machinery(self, js_frames):
        for svg in js_frames["cut"]:
            assert "opacity=" not in svg or "<g opacity=" not in svg
            assert "<clipPath id=\"wipe\"" not in svg

    def test_a_seamless_scroll_emits_the_trailing_copy(self, js_frames):
        for svg in js_frames["scroll_left"]:
            assert svg.count('transform="translate(') >= 2, "seam copy missing"

    def test_a_non_looping_scroll_emits_only_one_strip(self, js_frames):
        first = js_frames["scroll_noloop"][0]

        # One outer strip translate; card groups have their own translate, so
        # compare against the looping variant instead of an absolute count.
        looping = js_frames["scroll_left"][0]
        assert first.count('transform="translate(') < looping.count('transform="translate(')

    def test_a_transparent_canvas_emits_no_background_rect(self, js_frames):
        assert '<rect x="0" y="0"' not in js_frames["fade"][0].split("<g")[0]

    def test_a_solid_canvas_emits_its_background_rect(self, js_frames):
        assert 'fill="#101014"' in js_frames["solid_background"][0]


class TestFrameComposition:
    """Python-side behaviour that does not need Node."""

    def test_frame_svg_is_deterministic(self):
        project = PROJECTS["pixel_wipe"]

        for time_ms in SAMPLE_TIMES:
            assert frame.frame_svg(project, time_ms) == frame.frame_svg(project, time_ms)

    def test_frame_svg_does_not_mutate_the_project(self):
        import json

        project = PROJECTS["fade"]
        before = json.dumps(project, sort_keys=True)

        for time_ms in SAMPLE_TIMES:
            frame.frame_svg(project, time_ms)

        assert json.dumps(project, sort_keys=True) == before

    def test_a_custom_clip_id_is_honoured(self):
        project = PROJECTS["pixel_wipe"]

        svg = frame.frame_svg(project, 300, clip_id="wipe-7")

        assert 'id="wipe-7"' in svg
        assert "url(#wipe-7)" in svg

    def test_an_empty_project_still_produces_a_valid_svg(self):
        project = models.normalize_project({"pages": []})
        project["pages"] = []

        svg = frame.frame_svg(project, 500)

        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")

    def test_wipe_progress_is_quantized_into_steps(self):
        """A stepped wipe must not slide smoothly."""
        project = PROJECTS["pixel_wipe"]
        widths = set()

        for time_ms in range(0, 500, 7):
            svg = frame.frame_svg(project, time_ms)
            if "<clipPath" not in svg:
                continue
            fragment = svg.split('<clipPath id="wipe"><rect x="0" y="0" width="', 1)[1]
            widths.add(fragment.split('"', 1)[0])

        assert len(widths) <= frame.PIXEL_WIPE_STEPS
