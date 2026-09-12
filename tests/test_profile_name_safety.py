import pytest

import app as dashboard


@pytest.mark.parametrize("name", ["../config", "..\\config", "/absolute", "C:\\temp", "", ".", ".."])
def test_profile_name_rejects_path_escape(name):
    with pytest.raises(ValueError):
        dashboard._safe_profile_name(name)


@pytest.mark.parametrize("name", ["default", "stream-1", "One_Block", "profile 2"])
def test_profile_name_accepts_plain_display_names(name):
    assert dashboard._safe_profile_name(name) == name
