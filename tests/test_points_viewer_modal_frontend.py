"""Frontend contract for the per-viewer coin editor in the Points tab."""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "templates" / "index.html"
SCRIPT = ROOT / "static" / "script.js"
STYLE = ROOT / "static" / "style.css"


def test_modal_markup_exists_with_every_wired_element():
    html = INDEX.read_text(encoding="utf-8")

    assert 'id="points-viewer-modal"' in html
    for element_id in (
        "pv-avatar", "pv-nick", "pv-username", "pv-userid",
        "pv-coins", "pv-gifts", "pv-first-seen", "pv-last-gift",
        "pv-adjust-amount", "pv-adjust-note", "pv-history",
    ):
        assert f'id="{element_id}"' in html, element_id


def test_modal_exposes_set_add_and_remove_buttons():
    html = INDEX.read_text(encoding="utf-8")

    for operation in ("add", "remove", "set"):
        assert f"adjustViewerCoins('{operation}')" in html, operation
    assert "closePointsViewerModal()" in html


def test_rows_are_clickable_and_delegated_to_the_modal_opener():
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'class="points-row" data-user-id=' in script
    assert "tr.points-row" in script, "click handler must be delegated on the tbody"
    assert "function openPointsViewerModal(" in script
    assert "function closePointsViewerModal(" in script


def test_adjust_call_posts_the_documented_payload_to_the_blueprint_url():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "'/api/points/viewer/adjust'" in script
    assert "async function adjustViewerCoins(operation)" in script
    for key in ("id: pointsViewerId", "operation,", "amount,", "note:"):
        assert key in script, key
    assert "loadPoints();" in script.split("async function adjustViewerCoins")[1], \
        "table must refresh after a successful adjustment"


def test_history_distinguishes_manual_rows_and_escapes_user_text():
    script = SCRIPT.read_text(encoding="utf-8")
    body = script.split("function renderPointsViewer")[1]

    assert "h.kind === 'manual'" in body
    assert "is-manual" in body
    assert "escHtml(h.gift_name" in body, "gift/note text must be escaped"


def test_modal_styles_are_token_driven_so_light_theme_follows():
    css = STYLE.read_text(encoding="utf-8")
    # Scope to the modal's own section: the Points styles end at the file's own
    # `END VIEWER POINTS TAB` banner. Reading to end-of-file made this test fail
    # whenever an unrelated section (e.g. the Gift Roulette panel) was appended
    # after the modal — those sections legitimately own their own colors.
    section = css.split("/* ── Per-viewer coin editor modal ── */")[1]
    block = section.split("/* ===== END VIEWER POINTS TAB ===== */")[0]

    assert ".pv-history-row" in block
    assert ".pv-stat" in block
    # No hardcoded hex colors — everything must read the global theme tokens.
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", block), "use var(--token), not raw hex"
