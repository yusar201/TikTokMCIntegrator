from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(path):
    return path.read_text(encoding="utf-8")


def test_example_maps_friendship_necklace_to_ten_seconds_per_gift():
    config = _text(ROOT / "config.example.yml")

    assert "- rush frozenhands {mc} {amount*10} add {user}" in config
    assert "disableminegift" not in config


def test_release_default_maps_frozen_hands_help_to_ten_seconds_per_gift():
    path = ROOT / "release" / "config" / "profiles" / "default.yml"
    config = _text(path)

    assert "command: rush frozenhands {mc} {amount*10} remove {user}" in config
