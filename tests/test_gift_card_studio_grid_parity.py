"""Gift Card Studio — Python/JS grid parity.

``gift_card_studio/grid.py`` and ``static/gift-studio/grid.js`` implement the
same resize contract. If they drift, the PNG/GIF export silently stops matching
the editor preview — the exact failure the plan's shared-renderer decision
exists to prevent. This test runs the JS implementation through Node and
compares it to the Python one on identical inputs.

Skips (does not fail) when Node is unavailable, so the suite still runs in a
Python-only environment.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from gift_card_studio import grid as pygrid
from tests.js_parity import module_url, run_node_module_script

ROOT = Path(__file__).resolve().parents[1]
JS_GRID = ROOT / "static" / "gift-studio" / "grid.js"

NODE = shutil.which("node") or ""
pytestmark = pytest.mark.skipif(not NODE, reason="node is not installed")


# Cases span the presets in the plan plus awkward geometry.
CASES = [
    {"canvas": [1920, 1080], "grid": {"rows": 1, "columns": 1, "gap_x": 0, "gap_y": 0, "padding": 0}},
    {"canvas": [1920, 1080], "grid": {"rows": 1, "columns": 5, "gap_x": 20, "gap_y": 20, "padding": 24}},
    {"canvas": [1920, 1080], "grid": {"rows": 2, "columns": 3, "gap_x": 20, "gap_y": 20, "padding": 24}},
    {"canvas": [1920, 1080], "grid": {"rows": 3, "columns": 3, "gap_x": 12, "gap_y": 12, "padding": 16}},
    {"canvas": [1080, 1920], "grid": {"rows": 4, "columns": 2, "gap_x": 8, "gap_y": 8, "padding": 40}},
    {"canvas": [800, 600], "grid": {"rows": 1, "columns": 3, "gap_x": 0, "gap_y": 0, "padding": 0}},
    {"canvas": [640, 480], "grid": {"rows": 2, "columns": 2, "gap_x": 33, "gap_y": 17, "padding": 7}},
    {"canvas": [500, 500], "grid": {"rows": 1, "columns": 1, "gap_x": 0, "gap_y": 0, "padding": 300}},
]

CARD_SIZES = [(320, 400), (400, 320), (100, 100), (37, 511)]
FITS = ("contain", "cover", "stretch")

NODE_SCRIPT = """
import * as grid from %(module)r;
const cases = %(cases)s;
const out = [];
for (const c of cases) {
  const [w, h] = c.canvas;
  const g = { ...c.grid, fill_order: 'row', fit: 'contain' };
  const size = grid.cellSize(w, h, g);
  const rects = grid.cellRects(w, h, g);
  const fits = {};
  for (const fit of %(fits)s) {
    fits[fit] = %(cards)s.map(([cw, ch]) => {
      const t = grid.cardTransform(cw, ch, rects[0], fit);
      return [t.scaleX, t.scaleY, t.offsetX, t.offsetY, t.clipped];
    });
  }
  out.push({ size: [size.width, size.height], rects: rects.map(r => [r.x, r.y, r.width, r.height]), fits });
}
console.log(JSON.stringify(out));
"""


def _run_node():
    script = NODE_SCRIPT % {
        "module": module_url(JS_GRID),
        "cases": json.dumps(CASES),
        "fits": json.dumps(list(FITS)),
        "cards": json.dumps([list(pair) for pair in CARD_SIZES]),
    }
    return run_node_module_script(script, ROOT)


@pytest.fixture(scope="module")
def js_results():
    return _run_node()


def _close(a, b, tolerance=1e-9):
    return abs(float(a) - float(b)) <= tolerance


class TestGridParity:

    def test_cell_size_matches(self, js_results):
        for case, js in zip(CASES, js_results):
            width, height = pygrid.cell_size(case["canvas"][0], case["canvas"][1], case["grid"])
            assert _close(width, js["size"][0]), case
            assert _close(height, js["size"][1]), case

    def test_cell_rects_match(self, js_results):
        for case, js in zip(CASES, js_results):
            rects = pygrid.cell_rects(case["canvas"][0], case["canvas"][1], case["grid"])
            assert len(rects) == len(js["rects"]), case
            for py_rect, js_rect in zip(rects, js["rects"]):
                assert _close(py_rect["x"], js_rect[0]), case
                assert _close(py_rect["y"], js_rect[1]), case
                assert _close(py_rect["width"], js_rect[2]), case
                assert _close(py_rect["height"], js_rect[3]), case

    def test_card_transforms_match_for_every_fit_mode(self, js_results):
        for case, js in zip(CASES, js_results):
            cell = pygrid.cell_rect(0, case["canvas"][0], case["canvas"][1], case["grid"])
            for fit in FITS:
                for (card_w, card_h), js_transform in zip(CARD_SIZES, js["fits"][fit]):
                    transform = pygrid.card_transform(card_w, card_h, cell, fit)
                    label = (case, fit, card_w, card_h)
                    assert _close(transform["scale_x"], js_transform[0]), label
                    assert _close(transform["scale_y"], js_transform[1]), label
                    assert _close(transform["offset_x"], js_transform[2]), label
                    assert _close(transform["offset_y"], js_transform[3]), label
                    assert transform["clipped"] is js_transform[4], label

    def test_fill_order_indexing_matches(self):
        script = (
            f"import * as g from {module_url(JS_GRID)!r};"
            "const out=[];"
            "for (const order of ['row','column']) {"
            "  for (let i=0;i<12;i++) { const p=g.cellPosition(i,3,4,order); out.push([order,i,p.row,p.column]); }"
            "}"
            "console.log(JSON.stringify(out));"
        )

        for order, index, row, column in run_node_module_script(script, ROOT):
            assert pygrid.cell_position(index, 3, 4, order) == (row, column), (order, index)
