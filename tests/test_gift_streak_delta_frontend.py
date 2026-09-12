"""Regression contract for the gift modal's immediate-processing toggle."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "static" / "script.js"
INDEX = ROOT / "templates" / "index.html"


def test_gift_modal_commits_streak_delta_to_current_config_before_rerender():
    """Reopening a just-saved gift must keep the toggle state before API save."""
    script = SCRIPT.read_text(encoding="utf-8")
    save_modal = script[script.index("function saveGiftModal()") : script.index("function deleteGiftModal()")]

    commit = "currentConfig.StreakDeltaGifts = [...streakDeltaSelected];"
    assert commit in save_modal
    assert save_modal.index(commit) < save_modal.index("populateGifts();")


def test_dashboard_cache_busts_the_fixed_gift_modal_script():
    html = INDEX.read_text(encoding="utf-8")
    match = re.search(r'/static/script\.js\?v=(\d+)', html)
    assert match is not None
    assert int(match.group(1)) >= 39
