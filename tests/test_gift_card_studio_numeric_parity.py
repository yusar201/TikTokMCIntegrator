"""Gift Card Studio — Python/JS numeric tie-breaking parity.

Python and JS round half-values in opposite directions
(``round(2.5) == 2`` vs ``Math.round(2.5) === 3``). Every shared coordinate,
opacity, and frame timestamp crosses that boundary, so a tie value would render
or time differently in the exporter than in the OBS overlay. This suite pins the
convention directly rather than waiting for a downstream parity test to trip on
it by luck.

Skips (does not fail) when Node is unavailable.
"""

import shutil
from pathlib import Path

import pytest

from gift_card_studio import playback, renderer
from gift_card_studio.numeric import js_round
from tests.js_parity import run_node_with_payload

ROOT = Path(__file__).resolve().parents[1]
JS_RENDERER = ROOT / "static" / "gift-studio" / "renderer.js"

NODE = shutil.which("node") or ""

# Values that land exactly on a tie at 3dp, plus ordinary and negative cases.
TIE_VALUES = [
    0.0005, 0.0015, 0.0025, 0.0035, 0.0045, 0.0055,
    -0.0005, -0.0015, -0.0025,
    2.5, 3.5, -2.5, -3.5, 0.5, 1.5,
    0.1235, 0.1245, 12.3455, 99.9995,
    1 / 3, 2 / 3, 0.0001, 1e-9, 0,
]


class TestJsRoundConvention:

    def test_ties_go_up_not_to_even(self):
        assert js_round(2.5) == 3
        assert js_round(3.5) == 4
        assert js_round(0.5) == 1

    def test_python_builtin_round_disagrees(self):
        """Documents exactly why this helper exists."""
        assert round(2.5) == 2 != js_round(2.5)

    def test_negative_ties_go_toward_positive_infinity(self):
        """JS Math.round(-2.5) === -2, not -3."""
        assert js_round(-2.5) == -2
        assert js_round(-3.5) == -3

    def test_ordinary_values_round_normally(self):
        assert js_round(1.4) == 1
        assert js_round(1.6) == 2
        assert js_round(-1.6) == -2

    def test_non_numeric_input_is_zero_rather_than_an_exception(self):
        assert js_round(None) == 0
        assert js_round("nope") == 0

    def test_infinities_and_nan_are_zero(self):
        assert js_round(float("inf")) == 0
        assert js_round(float("-inf")) == 0
        assert js_round(float("nan")) == 0


class TestRendererFormatting:

    def test_whole_numbers_lose_their_decimal_point(self):
        assert renderer._round(12.0) == "12"
        assert renderer._round(0) == "0"

    def test_fractions_keep_up_to_three_places(self):
        assert renderer._round(12.3456) == "12.346"
        assert renderer._round(0.1) == "0.1"

    def test_a_tie_at_three_places_rounds_up(self):
        assert renderer._round(0.0025) == "0.003"


class TestFrameTimingUsesTheSameRule:

    def test_frame_times_are_tie_up(self):
        """At 24fps, frame 12 is exactly 500.0 — no tie — but 3fps hits .5 ties."""
        from gift_card_studio import models

        project = models.normalize_project({
            "playback": {"default_page_duration_ms": 3000}, "pages": [{}],
        })
        times = playback.frame_times(project, 16)

        # 1000/16 = 62.5 -> ties on every odd frame; each must round up.
        assert times[1] == 63
        assert times[3] == 188


@pytest.mark.skipif(not NODE, reason="node is not installed")
class TestCrossLanguageRounding:

    NODE_SCRIPT = """
    import * as r from %(module)s;
    const fixture = %(payload)s;
    console.log(JSON.stringify(fixture.values.map((v) => String(r.round(v)))));
    """

    def test_every_tie_value_formats_identically_in_both_languages(self):
        js_values = run_node_with_payload(
            self.NODE_SCRIPT, {"values": TIE_VALUES}, ROOT, JS_RENDERER
        )

        for value, expected in zip(TIE_VALUES, js_values):
            assert renderer._round(value) == expected, value
