"""Regression checks for bounded-cost packed-alpha gift animation rendering."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "templates" / "overlay.html"


def test_packed_alpha_animation_has_a_fixed_frame_budget():
    html = OVERLAY.read_text(encoding="utf-8")

    assert "const PACKED_ALPHA_FRAME_MS = 50;" in html
    assert "if (now - state.lastDrawAt < PACKED_ALPHA_FRAME_MS)" in html


def test_packed_alpha_crop_learns_bounds_across_the_first_full_animation_loop():
    html = OVERLAY.read_text(encoding="utf-8")

    assert "const PACKED_ALPHA_CROP_SAMPLE_MS = 50;" in html
    assert "cropLearning: true" in html
    assert "video.currentTime + 0.05 < state.lastVideoTime" in html
    assert "state.cropLearning = false;" in html
    assert "state.cropLearning && sampleBucket !== state.lastCropSampleBucket" in html
    assert "PACKED_ALPHA_CROP_SCAN_FRAMES" not in html
    assert "cropScanFrames" not in html


def test_packed_alpha_animation_fits_the_complete_learned_bounds_inside_the_canvas():
    html = OVERLAY.read_text(encoding="utf-8")

    assert "const scale = Math.min(outW / cropW, outH / cropH);" in html
    assert "const dy = Math.round(outH - drawH);" in html
    assert "const scale = Math.max(outW / cropW, outH / cropH);" not in html


def test_dashboard_preview_never_starts_the_expensive_packed_alpha_compositor():
    html = OVERLAY.read_text(encoding="utf-8")

    assert "if (isPreview) {" in html
    assert "tgSetFallbackIcon(iconUrl);" in html
    assert "ggSetFallbackIcon(iconUrl);" in html
    assert "preview uses static media" in html
