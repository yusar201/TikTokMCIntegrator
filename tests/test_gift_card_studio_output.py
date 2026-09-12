"""Output-folder persistence and artifact delivery."""

import json
import os

import pytest

from gift_card_studio import output
from gift_card_studio.validation import ValidationError


@pytest.fixture(autouse=True)
def reset_picker():
    output.register_folder_picker(None)
    yield
    output.register_folder_picker(None)


def test_unconfigured_folder_is_reported_without_creating_state(tmp_path):
    info = output.get_output_folder(str(tmp_path / "data"))

    assert info["configured"] is False
    assert info["writable"] is False
    assert info["reason"] == "not set"
    assert not os.path.exists(output.settings_path(str(tmp_path / "data")))


def test_setting_folder_persists_separately_from_bot_config(tmp_path):
    data_dir = str(tmp_path / "data")
    destination = tmp_path / "exports"
    destination.mkdir()

    info = output.set_output_folder(str(destination), data_dir)

    assert info["configured"] is True
    assert info["writable"] is True
    stored = json.loads(open(output.settings_path(data_dir), encoding="utf-8").read())
    assert stored == {"output_folder": os.path.abspath(str(destination))}


def test_missing_folder_is_rejected_before_generation(tmp_path):
    with pytest.raises(ValidationError, match="does not exist"):
        output.set_output_folder(str(tmp_path / "missing"), str(tmp_path / "data"))


def test_picker_cancel_does_not_replace_existing_folder(tmp_path):
    data_dir = str(tmp_path / "data")
    destination = tmp_path / "exports"
    destination.mkdir()
    output.set_output_folder(str(destination), data_dir)
    output.register_folder_picker(lambda: None)

    assert output.pick_folder() is None
    assert output.get_output_folder(data_dir)["path"] == os.path.abspath(str(destination))


def test_picker_returns_an_absolute_path(tmp_path):
    destination = tmp_path / "exports"
    destination.mkdir()
    output.register_folder_picker(lambda: str(destination))

    assert output.pick_folder() == os.path.abspath(str(destination))


def test_pick_without_native_shell_has_clear_error():
    with pytest.raises(ValidationError, match="no native folder picker"):
        output.pick_folder()


def test_delivery_is_atomic_and_does_not_overwrite(tmp_path):
    source = tmp_path / "source.gif"
    source.write_bytes(b"GIF89a-real")
    destination = tmp_path / "exports"
    destination.mkdir()
    (destination / "source.gif").write_bytes(b"old")

    saved = output.deliver(str(source), str(destination))

    assert os.path.basename(saved) == "source-2.gif"
    assert open(saved, "rb").read() == b"GIF89a-real"
    assert (destination / "source.gif").read_bytes() == b"old"
    assert not list(destination.glob("*.part"))


def test_stale_saved_folder_is_detected_on_next_read(tmp_path):
    data_dir = str(tmp_path / "data")
    destination = tmp_path / "exports"
    destination.mkdir()
    output.set_output_folder(str(destination), data_dir)
    destination.rmdir()

    info = output.get_output_folder(data_dir)

    assert info["configured"] is True
    assert info["exists"] is False
    with pytest.raises(ValidationError, match="no longer exists"):
        output.require_output_folder(data_dir)


def test_clear_removes_only_the_folder_setting(tmp_path):
    data_dir = str(tmp_path / "data")
    destination = tmp_path / "exports"
    destination.mkdir()
    output.set_output_folder(str(destination), data_dir)

    output.clear_output_folder(data_dir)

    assert output.get_output_folder(data_dir)["configured"] is False
    assert os.path.isdir(data_dir)
