"""Regression tests for resource-safe dashboard overlay previews."""

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANAGER = ROOT / "static" / "overlay_previews.js"


def run_node(script: str) -> dict:
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_previews_default_off_and_only_load_when_enabled_on_active_panel():
    script = f"""
const manager = require({json.dumps(str(MANAGER))});
const values = new Map();
const storage = {{
  getItem: key => values.has(key) ? values.get(key) : null,
  setItem: (key, value) => values.set(key, value),
}};
const frame = {{ src: '' }};

const defaultEnabled = manager.isEnabled('chat', storage);
manager.syncFrame('chat', frame, 'http://localhost:5000/overlay/chat', true, storage);
const disabledSrc = frame.src;

manager.setEnabled('chat', true, storage);
manager.syncFrame('chat', frame, 'http://localhost:5000/overlay/chat', true, storage);
const enabledSrc = frame.src;

manager.syncFrame('chat', frame, 'http://localhost:5000/overlay/chat', false, storage);
const hiddenPanelSrc = frame.src;

console.log(JSON.stringify({{
  defaultEnabled,
  disabledSrc,
  enabledSrc,
  hiddenPanelSrc,
  persisted: JSON.parse(values.get(manager.STORAGE_KEY)).chat,
}}));
"""
    data = run_node(script)

    assert data == {
        "defaultEnabled": False,
        "disabledSrc": "about:blank",
        "enabledSrc": "http://localhost:5000/overlay/chat?preview=true",
        "hiddenPanelSrc": "about:blank",
        "persisted": True,
    }


def test_preview_query_is_appended_without_dropping_overlay_filters():
    script = f"""
const manager = require({json.dumps(str(MANAGER))});
console.log(JSON.stringify({{
  plain: manager.buildPreviewUrl('/overlay/gifts'),
  filtered: manager.buildPreviewUrl('/overlay/gifts?min_coins=100&sort=high'),
}}));
"""
    data = run_node(script)

    assert data["plain"] == "/overlay/gifts?preview=true"
    assert data["filtered"] == "/overlay/gifts?min_coins=100&sort=high&preview=true"
