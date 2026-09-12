"""Gift Card Studio layer-editor UX requested after live review."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
EDITOR = (ROOT / "static" / "gift-studio" / "editor.js").read_text(encoding="utf-8")
STUDIO = (ROOT / "static" / "gift-studio" / "studio.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "gift-studio" / "studio.css").read_text(encoding="utf-8")


def test_each_layer_row_has_its_own_visibility_checkbox():
    assert 'data-layer-visible=' in EDITOR
    assert 'class="gcs-layer-visible"' in EDITOR
    assert 'data-layer-type=' in EDITOR
    assert '> Visible</label>' not in EDITOR


def test_layer_visibility_click_does_not_change_selected_layer_accidentally():
    assert "stopPropagation()" in EDITOR
    assert "layer.visible=checkbox.checked" in EDITOR


def test_editor_has_add_text_layer_action():
    assert 'id="gcs-add-text-layer"' in INDEX
    assert "$('gcs-add-text-layer').onclick=addTextLayer" in STUDIO
    assert "function addTextLayer()" in STUDIO


def test_editor_has_add_gift_icon_layer_action():
    assert 'id="gcs-add-gift-icon-layer"' in INDEX
    assert "$('gcs-add-gift-icon-layer').onclick=addGiftIconLayer" in STUDIO
    assert "function addGiftIconLayer()" in STUDIO


def test_new_gift_icon_layer_is_bounding_box_editable_and_auto_linked():
    for token in ["type:'gift_icon'", "auto_link:true", "fit:'contain'", "asset:''",
                  "state.layerIndex=card.layers.length-1"]:
        assert token in STUDIO
    # Badge default must derive from the card's own size, not a fixed pixel value
    assert "Math.min(width,height)" in STUDIO


def test_new_text_layer_has_independent_geometry_and_text_properties():
    for token in ["type:'text'", "font_size:24", "x:24", "y:24", "width:272", "height:52"]:
        assert token in STUDIO
    assert "state.layerIndex=card.layers.length-1" in STUDIO


def test_action_and_gift_image_layers_have_browse_and_replace_controls():
    assert 'id="gcs-layer-asset-file"' in INDEX
    assert "layer.type==='image'||layer.type==='action_icon'||layer.type==='gift_icon'" in EDITOR
    assert 'data-action="browse-asset"' in EDITOR
    assert 'data-action="clear-asset"' in EDITOR
    assert "uploadLayerAsset" in STUDIO


def test_missing_gift_badge_can_be_replaced_without_changing_action_artwork():
    assert "layer.type==='gift_icon'" in EDITOR
    assert "layer.asset=`/gift-studio-assets/${encodeURIComponent(body.asset.name)}`" in STUDIO
    assert "layer.asset=''" in EDITOR


def test_asset_upload_uses_existing_multipart_endpoint_and_updates_selected_layer():
    assert "new FormData()" in STUDIO
    assert "form.append('file'" in STUDIO
    assert "fetch(API+'/assets'" in STUDIO
    assert "layer.asset=`/gift-studio-assets/${encodeURIComponent(body.asset.name)}`" in STUDIO


def test_image_layer_keeps_full_geometry_controls():
    assert "['x','y','width','height','rotation','opacity']" in EDITOR


def test_layer_row_and_inline_checkbox_have_dedicated_layout_styles():
    assert '.gcs-layer-row' in CSS
    assert '.gcs-layer-visible' in CSS
    assert '.gcs-layer-actions' in CSS
