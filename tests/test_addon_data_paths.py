import os

import pytest

import paths


def test_addon_data_creates_scoped_parent(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))

    result = paths.addon_data("survival_rush", "objective_rush_state.json")

    expected = tmp_path / "addons" / "survival_rush" / "objective_rush_state.json"
    assert result == str(expected)
    assert expected.parent.is_dir()


@pytest.mark.parametrize("addon_id", ["", ".", "..", "../oneblock", "survival/rush", "survival\\rush"])
def test_addon_data_rejects_invalid_addon_id(tmp_path, monkeypatch, addon_id):
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))

    with pytest.raises(ValueError):
        paths.addon_data(addon_id, "state.json")


@pytest.mark.parametrize("name", ["", ".", "..", "../state.json", "dir/state.json", "dir\\state.json"])
def test_addon_data_rejects_invalid_file_name(tmp_path, monkeypatch, name):
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))

    with pytest.raises(ValueError):
        paths.addon_data("survival_rush", name)


def test_addon_data_accepts_safe_identifier_and_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))

    result = paths.addon_data("survival-rush_2", "state.v2.json")

    assert os.path.commonpath([result, str(tmp_path)]) == str(tmp_path)
