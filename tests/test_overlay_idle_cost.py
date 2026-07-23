"""Regression coverage for overlays that must remain cheap while idle."""

import json
from pathlib import Path

import app as dashboard
import routes.stats as stats


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "templates" / "overlay.html"
DASHBOARD_CSS = ROOT / "static" / "style.css"


def test_top_gift_and_streak_request_compact_summary_payloads():
    html = OVERLAY.read_text(encoding="utf-8")

    assert "TYPE === 'topgift' ? '/api/stats/gifts?summary=topgift'" in html
    assert "TYPE === 'topstreak' ? '/api/stats/gifts?summary=topstreak'" in html
    assert "TYPE === 'topshowcase' ? '/api/stats/gifts?summary=topshowcase'" in html
    assert "TYPE === 'topgift' || TYPE === 'topstreak' || TYPE === 'topshowcase' ? 3000" in html
    assert "TYPE === 'coingoal' ? 2000" in html


def test_static_top_cards_skip_repeated_dom_and_counter_animation_work():
    html = OVERLAY.read_text(encoding="utf-8")

    assert "let tgRenderedKey = '';" in html
    assert "if (renderKey === tgRenderedKey) return;" in html
    assert "let tsRenderedKey = '';" in html
    assert "if (renderKey === tsRenderedKey) return;" in html


def test_coin_jar_frame_scheduler_stops_when_the_jar_is_idle():
    html = OVERLAY.read_text(encoding="utf-8")

    assert "function cgScheduleRender()" in html
    assert "cgRaf = null;" in html
    assert "if (!cgDirty) return;" in html
    assert "if (keepAnimating) cgScheduleRender();" in html
    assert "animation: cg-shimmer 6s ease-in-out infinite;" not in html
    assert "animation: cg-celebrate 1.2s ease infinite;" not in html
    assert "function cgPulseActivity()" in html


def test_dashboard_history_tier_styles_do_not_animate_forever():
    css = DASHBOARD_CSS.read_text(encoding="utf-8")

    assert "DASHBOARD HISTORY PERFORMANCE: EVENT-IDLE" in css
    assert ".ticker-entry.tier-1::after" in css
    assert ".tier-4 .legend-glow" in css
    assert ".ticker-entry[class*=\"tier-\"] .sparkle-particle" in css
    assert "animation: none !important;" in css
    assert ".gift-tier-5" in css
    assert ".streak-card" in css


def test_top_showcase_payload_contains_both_existing_summary_winners(tmp_path, monkeypatch):
    entries = [
        {"gift_id": "1", "sender": "first", "gift_name": "Rose", "diamond_count": 100, "repeat_count": 2},
        {"gift_id": "2", "sender": "longest", "gift_name": "Rose", "diamond_count": 100, "repeat_count": 8},
        {"gift_id": "3", "sender": "largest", "gift_name": "Lion", "diamond_count": 500, "repeat_count": 2},
    ]
    (tmp_path / "gift_log.json").write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setattr(stats, "BASE_DIR", str(tmp_path))
    stats._GIFT_SUMMARY_CACHE.update({"signature": None, "topgift": [], "topstreak": []})

    response = dashboard.app.test_client().get("/api/stats/gifts?summary=topshowcase")

    assert response.status_code == 200
    assert response.get_json() == {"topgift": entries[2], "topstreak": entries[1]}


def test_top_showcase_switches_every_five_seconds_and_preserves_existing_cards():
    html = OVERLAY.read_text(encoding="utf-8")

    assert "id=\"showcase-gift-slot\"" in html
    assert "id=\"showcase-streak-slot\"" in html
    assert "const TOP_SHOWCASE_SWITCH_MS = 5000;" in html
    assert "setInterval(showcaseTick, TOP_SHOWCASE_SWITCH_MS);" in html
    assert "showcaseSwitchTo(next);" in html
    assert "tgRenderGiftMedia(top, diamondVal);" in html


def test_compact_gift_summaries_preserve_top_gift_and_streak_selection(tmp_path, monkeypatch):
    entries = [
        {"gift_id": "1", "sender": "first", "gift_name": "Rose", "diamond_count": 100, "repeat_count": 2},
        {"gift_id": "2", "sender": "latest-tie", "gift_name": "Rose", "diamond_count": 100, "repeat_count": 3},
        {"gift_id": "3", "sender": "largest", "gift_name": "Lion", "diamond_count": 500, "repeat_count": 2},
    ]
    (tmp_path / "gift_log.json").write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setattr(stats, "BASE_DIR", str(tmp_path))
    stats._GIFT_SUMMARY_CACHE.update({"signature": None, "topgift": [], "topstreak": []})
    client = dashboard.app.test_client()

    top_gift = client.get("/api/stats/gifts?summary=topgift")
    top_streak = client.get("/api/stats/gifts?summary=topstreak")

    assert top_gift.status_code == 200
    assert top_gift.get_json() == [entries[2]]
    assert top_streak.status_code == 200
    assert top_streak.get_json() == [entries[1]]
