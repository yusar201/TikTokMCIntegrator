"""Dashboard-wide readable block-font contract."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "static" / "style.css"
FONT_CSS = ROOT / "static" / "app-font.css"
INDEX = ROOT / "templates" / "index.html"
WIZARD = ROOT / "templates" / "wizard.html"


def test_self_hosted_chakra_petch_assets_exist():
    assert (ROOT / "static" / "fonts" / "ChakraPetch-Regular.ttf").is_file()
    assert (ROOT / "static" / "fonts" / "ChakraPetch-Medium.ttf").is_file()
    assert (ROOT / "static" / "fonts" / "ChakraPetch-SemiBold.ttf").is_file()
    assert (ROOT / "static" / "fonts" / "ChakraPetch-Bold.ttf").is_file()
    assert (ROOT / "static" / "fonts" / "OFL.txt").is_file()


def test_dashboard_font_stylesheet_defines_four_real_weights():
    css = FONT_CSS.read_text(encoding="utf-8")

    font_face_blocks = css.split("@font-face")[1:]
    assert len(font_face_blocks) == 4
    assert all("font-family: 'Chakra Petch'" in block for block in font_face_blocks)
    for weight, filename in ((400, "Regular"), (500, "Medium"), (600, "SemiBold"), (700, "Bold")):
        assert f"ChakraPetch-{filename}.ttf" in css
        assert f"font-weight: {weight}" in css


def test_every_dashboard_font_token_uses_chakra_petch():
    css = STYLE.read_text(encoding="utf-8")

    assert "--font-heading: 'Chakra Petch'" in css
    assert "--font-body: 'Chakra Petch'" in css
    assert "--font-mono: 'Chakra Petch'" in css
    assert "Monocraft" not in css
    assert "Pixelify Sans" not in css
    assert "Press Start 2P" not in css


def test_main_dashboard_and_wizard_load_local_font_before_their_styles():
    index = INDEX.read_text(encoding="utf-8")
    wizard = WIZARD.read_text(encoding="utf-8")

    assert index.index("/static/app-font.css") < index.index("/static/style.css")
    assert wizard.index("/static/app-font.css") < wizard.index("<style>")
    assert "Pixelify+Sans" not in index
    assert "Pixelify+Sans" not in wizard
    assert "font-family: 'Chakra Petch'" in wizard


def test_native_form_controls_and_placeholders_inherit_minecraft_font():
    css = FONT_CSS.read_text(encoding="utf-8")

    assert "button," in css
    assert "input," in css
    assert "select," in css
    assert "textarea" in css
    assert "::placeholder" in css
    assert "font-family: 'Chakra Petch'" in css
