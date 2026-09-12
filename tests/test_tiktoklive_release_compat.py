"""Compatibility contract for the TikTokLive battle-item-card release."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"
EVENT_REGISTRY = ROOT / "event_registry.py"


def test_python_tiktoklive_release_is_pinned_with_matching_proto_schema():
    requirements = REQUIREMENTS.read_text(encoding="utf-8")

    assert "TikTokLive==7.0.1" in requirements
    assert "TikTokLiveProto==0.2.2" in requirements
    assert "mcrcon==0.7.0" in requirements
    assert "TikTokLive==6.6.5" not in requirements
    assert "TikTokLive==7.0.0b2" not in requirements
    assert "mcrcon==0.3.3" not in requirements


def test_battle_item_card_event_is_available_to_dynamic_actions():
    registry = EVENT_REGISTRY.read_text(encoding="utf-8")

    assert "LinkMicBattleItemCardEvent," in registry
    assert '"LinkMicBattleItemCardEvent": _evt(' in registry
    assert '"Battle Power-Up"' in registry
    assert '["battle_id", "msg_type", "award_reason"]' in registry
