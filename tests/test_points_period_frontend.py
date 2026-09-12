"""Frontend period selector contract for the Points tab."""
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PERIOD_JS = ROOT / "static" / "points_period.js"
INDEX = ROOT / "templates" / "index.html"
SCRIPT = ROOT / "static" / "script.js"


def _bounds(period, start="", end=""):
    code = f"""
const {{ getPointsPeriodBounds }} = require({json.dumps(str(PERIOD_JS))});
const result = getPointsPeriodBounds(
  {json.dumps(period)}, {json.dumps(start)}, {json.dumps(end)},
  new Date('2026-08-06T15:30:00Z')
);
console.log(JSON.stringify(result));
"""
    env = dict(os.environ, TZ="UTC")
    result = subprocess.run(["node", "-e", code], check=True, capture_output=True, text=True, env=env)
    return json.loads(result.stdout)


def test_preset_periods_use_local_calendar_day_boundaries():
    assert _bounds("all") == {"since": None, "until": None, "label": "All time"}
    assert _bounds("today") == {
        "since": 1785974400,
        "until": 1786060800,
        "label": "Today",
    }
    assert _bounds("3d") == {
        "since": 1785801600,
        "until": 1786060800,
        "label": "Last 3 days",
    }
    assert _bounds("7d") == {
        "since": 1785456000,
        "until": 1786060800,
        "label": "Last 7 days",
    }


def test_custom_period_is_inclusive_of_both_selected_dates():
    assert _bounds("custom", "2026-08-02", "2026-08-04") == {
        "since": 1785628800,
        "until": 1785888000,
        "label": "Aug 2 - Aug 4, 2026",
    }


def test_custom_period_rejects_missing_or_reversed_dates():
    assert _bounds("custom", "", "2026-08-04")["error"] == "Choose both custom dates"
    assert _bounds("custom", "2026-08-05", "2026-08-04")["error"] == "End date must be on or after start date"


def test_points_panel_contains_period_controls_and_loads_helper_before_main_script():
    html = INDEX.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")

    for element_id in ("points-period", "points-custom-range", "points-start-date", "points-end-date", "points-period-label"):
        assert f'id="{element_id}"' in html
    assert html.index("/static/points_period.js") < html.index("/static/script.js")
    assert "getPointsPeriodBounds(" in script
    assert "params.set('since'" in script
    assert "params.set('until'" in script
