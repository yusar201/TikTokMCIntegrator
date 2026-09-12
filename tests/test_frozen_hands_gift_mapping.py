from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

# release/ is a build output and is not in git, so these assertions only make
# sense on a machine that has actually deployed. Skip instead of failing in a
# fresh clone or a CI checkout.
_RELEASE_DEFAULT_PROFILE = ROOT / "release" / "config" / "profiles" / "default.yml"


def _text(path):
    return path.read_text(encoding="utf-8")


def test_example_maps_friendship_necklace_to_ten_seconds_per_gift():
    config = _text(ROOT / "config.example.yml")

    assert "- rush frozenhands {mc} {amount*10} add {user}" in config
    assert "disableminegift" not in config


@pytest.mark.skipif(
    not _RELEASE_DEFAULT_PROFILE.is_file(),
    reason="release/ is a build output and is not tracked in git",
)
def test_release_default_maps_frozen_hands_help_to_ten_seconds_per_gift():
    path = _RELEASE_DEFAULT_PROFILE
    config = _text(path)

    assert "command: rush frozenhands {mc} {amount*10} remove {user}" in config
