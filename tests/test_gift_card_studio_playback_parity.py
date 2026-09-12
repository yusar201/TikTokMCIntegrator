"""Gift Card Studio — Python/JS playback parity.

``gift_card_studio/playback.py`` and ``static/gift-studio/playback.js`` must
agree frame-for-frame: the editor preview and OBS output run the JS timeline
while the PNG/GIF exporter walks the Python one. A divergence means the exported
GIF is not the animation Khito previewed.

Skips (does not fail) when Node is unavailable.
"""

import json
import shutil
from pathlib import Path

import pytest

from gift_card_studio import models, playback
from tests.js_parity import module_url, run_node_module_script

ROOT = Path(__file__).resolve().parents[1]
JS_PLAYBACK = ROOT / "static" / "gift-studio" / "playback.js"

NODE = shutil.which("node") or ""
pytestmark = pytest.mark.skipif(not NODE, reason="node is not installed")


def _pages_project(count, duration, transition, loop):
    return models.normalize_project({
        "name": "Parity Pages",
        "canvas": {"width": 1920, "height": 1080},
        "playback": {
            "mode": "pages",
            "loop": loop,
            "default_page_duration_ms": duration,
            "default_transition": transition,
        },
        "pages": [
            {
                "name": f"P{i}",
                "grid": {"rows": 1, "columns": 5, "gap_x": 20, "gap_y": 20, "padding": 24},
                "cards": [{"name": f"c{i}", "width": 320, "height": 400}],
            }
            for i in range(count)
        ],
    })


def _scroll_project(direction, speed, loop, edge_pause, cards, item_gap, canvas):
    return models.normalize_project({
        "name": "Parity Scroll",
        "canvas": {"width": canvas[0], "height": canvas[1]},
        "playback": {"mode": "scroll", "loop": True},
        "pages": [{
            "grid": {"rows": 1, "columns": 3, "gap_x": 0, "gap_y": 0, "padding": 0},
            "scroll": {
                "enabled": True,
                "direction": direction,
                "speed_px_per_second": speed,
                "loop": loop,
                "edge_pause_ms": edge_pause,
                "item_gap": item_gap,
            },
            "cards": [{"name": f"c{i}", "width": 300, "height": 300} for i in range(cards)],
        }],
    })


PROJECTS = {
    "pages_cut": _pages_project(3, 1000, {"type": "cut", "duration_ms": 0}, True),
    "pages_fade": _pages_project(3, 1000, {"type": "fade", "duration_ms": 400}, True),
    "pages_wipe_noloop": _pages_project(4, 750, {"type": "pixel_wipe", "duration_ms": 300}, False),
    "pages_clamped": _pages_project(2, 400, {"type": "slide", "duration_ms": 4000}, True),
    "scroll_left": _scroll_project("left", 100.0, True, 0, 6, 0, (900, 300)),
    "scroll_right_gap": _scroll_project("right", 250.0, True, 0, 8, 20, (900, 300)),
    "scroll_up_paused": _scroll_project("up", 60.0, True, 1000, 5, 10, (300, 300)),
    "scroll_noloop": _scroll_project("left", 120.0, False, 500, 6, 0, (900, 300)),
}

SAMPLE_TIMES = [0, 1, 199, 200, 399, 400, 750, 999, 1000, 1200, 1399, 1400,
                2000, 2999, 3000, 4500, 9000, 12_345, 18_000, 25_000]

FPS_CASES = [10, 15, 20, 30]

NODE_SCRIPT = """
import * as pb from %(module)r;
const projects = %(projects)s;
const times = %(times)s;
const fpsCases = %(fps)s;
const out = {};
for (const [name, project] of Object.entries(projects)) {
  const states = times.map((t) => {
    const s = pb.stateAt(project, t);
    return {
      mode: s.mode,
      timeMs: s.timeMs,
      loopMs: s.loopMs,
      pageIndex: s.pageIndex,
      previousIndex: s.previousIndex,
      transitionType: s.transitionType,
      transitionProgress: s.transitionProgress,
      scroll: s.scroll ? [s.scroll.distance, s.scroll.offsetX, s.scroll.offsetY, s.scroll.progress, s.scroll.travel] : null,
    };
  });
  out[name] = {
    loopMs: pb.loopDurationMs(project),
    windows: pb.pageWindows(project).map((w) => [w.index, w.startMs, w.endMs, w.durationMs, w.transitionType, w.transitionMs]),
    states,
    frames: Object.fromEntries(fpsCases.map((f) => [f, pb.frameTimes(project, f)])),
    scrollTravel: pb.scrollTravelPx(project),
  };
}
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js_results():
    script = NODE_SCRIPT % {
        "module": module_url(JS_PLAYBACK),
        "projects": json.dumps(PROJECTS),
        "times": json.dumps(SAMPLE_TIMES),
        "fps": json.dumps(FPS_CASES),
    }
    return run_node_module_script(script, ROOT)


def _close(a, b, tolerance=1e-6):
    return abs(float(a) - float(b)) <= tolerance


class TestPlaybackParity:

    def test_loop_duration_matches(self, js_results):
        for name, project in PROJECTS.items():
            assert playback.loop_duration_ms(project) == js_results[name]["loopMs"], name

    def test_page_windows_match(self, js_results):
        for name, project in PROJECTS.items():
            windows = playback.page_windows(project)
            js_windows = js_results[name]["windows"]
            assert len(windows) == len(js_windows), name
            for window, js in zip(windows, js_windows):
                assert window["index"] == js[0], name
                assert window["start_ms"] == js[1], name
                assert window["end_ms"] == js[2], name
                assert window["duration_ms"] == js[3], name
                assert window["transition_type"] == js[4], name
                assert window["transition_ms"] == js[5], name

    def test_state_matches_at_every_sample_time(self, js_results):
        for name, project in PROJECTS.items():
            for time_ms, js in zip(SAMPLE_TIMES, js_results[name]["states"]):
                state = playback.state_at(project, time_ms)
                label = (name, time_ms)
                assert state["mode"] == js["mode"], label
                assert _close(state["time_ms"], js["timeMs"]), label
                assert state["loop_ms"] == js["loopMs"], label
                assert state["page_index"] == js["pageIndex"], label
                assert state["previous_index"] == js["previousIndex"], label
                assert state["transition_type"] == js["transitionType"], label
                assert _close(state["transition_progress"], js["transitionProgress"]), label

    def test_scroll_offsets_match(self, js_results):
        for name, project in PROJECTS.items():
            if (project["playback"]["mode"]) != "scroll":
                continue
            assert _close(playback.scroll_travel_px(project), js_results[name]["scrollTravel"]), name
            for time_ms, js in zip(SAMPLE_TIMES, js_results[name]["states"]):
                scroll = playback.state_at(project, time_ms)["scroll"]
                label = (name, time_ms)
                assert scroll is not None and js["scroll"] is not None, label
                assert _close(scroll["distance"], js["scroll"][0]), label
                assert _close(scroll["offset_x"], js["scroll"][1]), label
                assert _close(scroll["offset_y"], js["scroll"][2]), label
                assert _close(scroll["progress"], js["scroll"][3]), label
                assert _close(scroll["travel"], js["scroll"][4]), label

    def test_frame_times_match_for_every_fps(self, js_results):
        for name, project in PROJECTS.items():
            for fps in FPS_CASES:
                expected = js_results[name]["frames"][str(fps)]
                assert playback.frame_times(project, fps) == expected, (name, fps)
