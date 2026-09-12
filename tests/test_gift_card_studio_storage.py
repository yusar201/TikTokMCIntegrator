"""Gift Card Studio — storage: atomic saves, containment, asset safety.

Every test points at a tmp_path data dir; nothing touches the real data/ tree.
"""

import json
import os

import pytest

from gift_card_studio import models, storage
from gift_card_studio.validation import ValidationError


@pytest.fixture
def data_dir(tmp_path):
    directory = tmp_path / "data"
    directory.mkdir()
    storage.ensure_dirs(str(directory))
    return str(directory)


class TestDirectoryLifecycle:

    def test_importing_the_module_creates_nothing(self, tmp_path):
        """Zero-idle contract: no directory work happens at import time."""
        untouched = tmp_path / "never"

        assert not (untouched / "gift_card_studio").exists()

    def test_ensure_dirs_is_idempotent(self, tmp_path):
        target = str(tmp_path / "d")

        first = storage.ensure_dirs(target)
        second = storage.ensure_dirs(target)

        assert first == second
        assert os.path.isdir(storage.projects_dir(target))
        assert os.path.isdir(storage.assets_dir(target))

    def test_listing_a_missing_directory_returns_empty_not_an_error(self, tmp_path):
        missing = str(tmp_path / "nope")

        assert storage.list_project_ids(missing) == []
        assert storage.list_assets(missing) == []


class TestProjectRoundTrip:

    def test_save_then_load_preserves_the_design(self, data_dir):
        project = models.new_project("Survival Rush Gifts")
        project["pages"][0]["grid"].update({"rows": 1, "columns": 5})
        project["pages"][0]["cards"] = [
            models.normalize_card({
                "name": f"card {i}",
                "gift_ref": {"gift_id": str(5000 + i), "name": "rose"},
                "layers": [{"type": "gift_icon"}, {"type": "text", "text": f"{i} coins"}],
            })
            for i in range(5)
        ]

        saved = storage.save_project(project, data_dir)
        loaded = storage.load_project(saved["id"], data_dir)

        assert loaded is not None
        assert loaded["id"] == "survival-rush-gifts"
        assert loaded["pages"][0]["grid"]["columns"] == 5
        assert len(loaded["pages"][0]["cards"]) == 5
        assert [layer["type"] for layer in loaded["pages"][0]["cards"][0]["layers"]] == [
            "gift_icon",
            "text",
        ]

    def test_saved_file_is_valid_indented_json_on_disk(self, data_dir):
        saved = storage.save_project(models.new_project("Readable"), data_dir)

        raw = json.loads(open(storage.project_path(saved["id"], data_dir), encoding="utf-8").read())

        assert raw["schema_version"] == models.SCHEMA_VERSION
        assert raw["id"] == "readable"

    def test_save_leaves_no_temp_file_behind(self, data_dir):
        storage.save_project(models.new_project("Clean"), data_dir)

        leftovers = [n for n in os.listdir(storage.projects_dir(data_dir)) if n.endswith(".tmp")]

        assert leftovers == []

    def test_save_normalizes_before_writing(self, data_dir):
        storage.save_project({"id": "coerced", "canvas": {"width": "800"}}, data_dir)

        loaded = storage.load_project("coerced", data_dir)

        assert loaded is not None
        assert loaded["canvas"]["width"] == 800

    def test_save_stamps_updated_at(self, data_dir):
        project = models.new_project("Stamped")
        project["updated_at"] = "1999-01-01T00:00:00Z"

        saved = storage.save_project(project, data_dir)

        assert saved["updated_at"] != "1999-01-01T00:00:00Z"

    def test_loading_a_missing_project_returns_none(self, data_dir):
        assert storage.load_project("absent", data_dir) is None

    def test_overwriting_replaces_rather_than_appends(self, data_dir):
        storage.save_project(models.new_project("Twice"), data_dir)
        project = storage.load_project("twice", data_dir)
        assert project is not None
        project["name"] = "Renamed"
        storage.save_project(project, data_dir)

        reloaded = storage.load_project("twice", data_dir)

        assert reloaded is not None
        assert reloaded["name"] == "Renamed"
        assert storage.list_project_ids(data_dir) == ["twice"]


class TestCreateListDelete:

    def test_create_allocates_a_non_colliding_id(self, data_dir):
        first = storage.create_project("My Cards", data_dir)
        second = storage.create_project("My Cards", data_dir)

        assert first["id"] == "my-cards"
        assert second["id"] == "my-cards-2"

    def test_list_projects_returns_summaries_without_page_bodies(self, data_dir):
        storage.create_project("Alpha", data_dir)
        storage.create_project("Beta", data_dir)

        summaries = storage.list_projects(data_dir)

        assert {s["id"] for s in summaries} == {"alpha", "beta"}
        assert all("pages" not in s for s in summaries)
        assert all("page_count" in s for s in summaries)

    def test_delete_removes_the_file_and_reports_absence(self, data_dir):
        storage.create_project("Doomed", data_dir)

        assert storage.delete_project("doomed", data_dir) is True
        assert storage.delete_project("doomed", data_dir) is False
        assert storage.project_exists("doomed", data_dir) is False

    def test_non_json_files_in_the_projects_dir_are_ignored(self, data_dir):
        open(os.path.join(storage.projects_dir(data_dir), "notes.txt"), "w").close()
        storage.create_project("Real", data_dir)

        assert storage.list_project_ids(data_dir) == ["real"]


class TestPathContainment:

    @pytest.mark.parametrize("evil", [
        "../escape",
        "../../etc/passwd",
        "..",
        ".",
        "/absolute",
        "sub/dir",
        "back\\slash",
        "with space",
        "UPPER",
        "",
        "-leading-dash",
        "x" * 65,
    ])
    def test_unsafe_project_ids_are_refused(self, data_dir, evil):
        with pytest.raises(ValidationError):
            storage.project_path(evil, data_dir)

    def test_project_exists_is_false_for_unsafe_ids_instead_of_raising(self, data_dir):
        assert storage.project_exists("../../etc/passwd", data_dir) is False

    def test_every_resolved_project_path_stays_inside_the_projects_dir(self, data_dir):
        path = storage.project_path("legit-id", data_dir)
        root = os.path.realpath(storage.projects_dir(data_dir))

        assert os.path.realpath(path).startswith(root + os.sep)

    def test_delete_cannot_be_pointed_outside_the_studio_dir(self, data_dir, tmp_path):
        victim = tmp_path / "important.json"
        victim.write_text("{}", encoding="utf-8")

        with pytest.raises(ValidationError):
            storage.delete_project("../../important", data_dir)

        assert victim.exists()


class TestCorruptFiles:

    def test_corrupt_json_raises_instead_of_returning_a_blank_project(self, data_dir):
        path = storage.project_path("broken", data_dir)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json at all")

        with pytest.raises(ValidationError):
            storage.load_project("broken", data_dir)

    def test_list_projects_flags_a_damaged_file_without_failing_the_whole_list(self, data_dir):
        storage.create_project("Good", data_dir)
        with open(storage.project_path("bad", data_dir), "w", encoding="utf-8") as handle:
            handle.write("[[[")

        summaries = {s["id"]: s for s in storage.list_projects(data_dir)}

        assert "error" in summaries["bad"]
        assert "error" not in summaries["good"]

    def test_oversized_project_file_is_rejected_on_load(self, data_dir, monkeypatch):
        storage.create_project("Fat", data_dir)
        # Shrink the cap only after the file exists, so this exercises the
        # load-side guard rather than the save-side one.
        monkeypatch.setattr(storage, "MAX_PROJECT_BYTES", 32)

        with pytest.raises(ValidationError):
            storage.load_project("fat", data_dir)

    def test_oversized_project_is_rejected_on_save(self, data_dir, monkeypatch):
        monkeypatch.setattr(storage, "MAX_PROJECT_BYTES", 32)

        with pytest.raises(ValidationError):
            storage.save_project(models.new_project("Fat"), data_dir)


class TestAssetSafety:

    @pytest.mark.parametrize("name", ["icon.png", "gift-5487.webp", "a_b.jpg", "x.jpeg", "loop.gif"])
    def test_allowed_asset_names(self, name):
        assert storage.is_safe_asset_name(name) is True

    @pytest.mark.parametrize("name", [
        "../evil.png",
        "sub/dir.png",
        "evil.png.exe",
        "shell.html.png",
        "script.svg",
        "payload.php",
        "no-extension",
        ".hidden.png",
        "",
        "x" * 200 + ".png",
    ])
    def test_rejected_asset_names(self, name):
        assert storage.is_safe_asset_name(name) is False

    def test_asset_path_refuses_unsafe_names(self, data_dir):
        with pytest.raises(ValidationError):
            storage.asset_path("../../evil.png", data_dir)

    def test_svg_is_not_an_allowed_asset_extension(self):
        """SVG can carry script/external refs; the plan excludes it as an upload."""
        assert ".svg" not in storage.ALLOWED_ASSET_EXTENSIONS

    def test_save_asset_sanitizes_the_name_and_writes_the_bytes(self, data_dir):
        name = storage.save_asset_bytes("My Gift Icon!.PNG", b"\x89PNG-data", data_dir)

        assert name == "my-gift-icon.png"
        with open(storage.asset_path(name, data_dir), "rb") as handle:
            assert handle.read() == b"\x89PNG-data"

    def test_colliding_asset_names_get_a_numeric_suffix(self, data_dir):
        first = storage.save_asset_bytes("icon.png", b"a", data_dir)
        second = storage.save_asset_bytes("icon.png", b"b", data_dir)

        assert first == "icon.png"
        assert second == "icon-2.png"

    def test_unknown_extension_is_coerced_to_png_rather_than_trusted(self, data_dir):
        name = storage.save_asset_bytes("thing.php", b"x", data_dir)

        assert name.endswith(".png")

    def test_list_assets_reports_names_and_sizes(self, data_dir):
        storage.save_asset_bytes("one.png", b"1234", data_dir)

        assets = storage.list_assets(data_dir)

        assert assets == [{"name": "one.png", "size": 4}]

    def test_delete_asset_reports_absence(self, data_dir):
        storage.save_asset_bytes("gone.png", b"1", data_dir)

        assert storage.delete_asset("gone.png", data_dir) is True
        assert storage.delete_asset("gone.png", data_dir) is False
