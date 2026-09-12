"""Real-pixel guard for the approved action-hero/gift-badge hierarchy."""

import io

from PIL import Image, ImageDraw

from gift_card_studio import catalog, exporter, storage


def _distinct_colours(image, box):
    pixels = [pixel for pixel in image.crop(box).getdata() if pixel[3] > 8]
    return len({pixel[:3] for pixel in pixels})


def test_exported_card_contains_real_pixels_in_the_gift_badge(tmp_path):
    data_dir = str(tmp_path / "data")
    storage.ensure_dirs(data_dir)

    icon = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    for y in range(64):
        draw.line((0, y, 63, y), fill=((y * 7) % 255, (y * 13) % 255, 220, 255))
    icon_path = storage.asset_path("gift-icon-5655.png", data_dir)
    icon.save(icon_path, format="PNG")

    entry = {
        "key": "5655", "gift_id": "5655", "name": "rose",
        "diamond_count": 1, "category": "1 Coin",
        "commands": ["summon luckytntmod:village_defense ~ ~ ~"],
        "intent": "explosive", "label": "TNT",
        "suggested_text": {"main": "TNT", "secondary": ""},
        "suggested_action_icon": "explosive", "confidence": 1.0,
        "high_confidence": True,
        "icon": "/gift-studio-assets/gift-icon-5655.png",
        "icon_local": "/gift-studio-assets/gift-icon-5655.png",
        "icon_remote": "", "icon_missing": False,
        "in_tiktok_catalog": True,
    }
    card = catalog.draft_card(entry, include_action_icon=True)

    png = exporter.render_card_png(
        card, scale=2, base_dir=str(tmp_path), data_dir=data_dir
    )
    rendered = Image.open(io.BytesIO(png)).convert("RGBA")

    # Gift badge authored at x=22..118, y=148..244 on a 320-square card.
    assert _distinct_colours(rendered, (44, 296, 236, 488)) > 100
