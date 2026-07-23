"""Regression checks for bounded-cost packed-alpha gift animation rendering."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "templates" / "overlay.html"


def test_packed_alpha_animation_has_a_fixed_frame_budget():
    html = OVERLAY.read_text(encoding="utf-8")

    assert "const PACKED_ALPHA_FRAME_MS = 50;" in html
    assert "if (now - state.lastDrawAt < PACKED_ALPHA_FRAME_MS)" in html


def test_packed_alpha_crop_stops_scanning_after_learning_the_gift_bounds():
    html = OVERLAY.read_text(encoding="utf-8")

    assert "const PACKED_ALPHA_CROP_SCAN_FRAMES = 10;" in html
    assert "state.cropScanFrames < PACKED_ALPHA_CROP_SCAN_FRAMES" in html


def test_dashboard_preview_never_starts_the_expensive_packed_alpha_compositor():
    html = OVERLAY.read_text(encoding="utf-8")

    assert "if (isPreview) {" in html
    assert "tgSetFallbackIcon(iconUrl);" in html
    assert "ggSetFallbackIcon(iconUrl);" in html
    assert "preview uses static media" in html
