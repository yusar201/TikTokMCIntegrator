"""Regression checks for downloads initiated inside the pywebview dashboard."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"
SCRIPT = ROOT / "static" / "script.js"


def test_native_shell_enables_webview_downloads_before_window_creation():
    """pywebview blocks anchor/blob downloads unless ALLOW_DOWNLOADS is enabled."""
    source = MAIN.read_text(encoding="utf-8")

    enable = "webview.settings['ALLOW_DOWNLOADS'] = True"
    assert enable in source
    assert source.index(enable) < source.index("webview.create_window(")


def test_gift_icon_png_uses_browser_download_pipeline():
    """The gift editor converts the icon to PNG and starts an anchor download."""
    source = SCRIPT.read_text(encoding="utf-8")

    assert "async function downloadGiftIconAsPng()" in source
    assert "canvas.toBlob" in source
    assert "link.download = `gift_${giftId}.png`" in source
    assert "link.click()" in source
