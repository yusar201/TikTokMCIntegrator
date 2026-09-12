"""Gift Card Studio — PNG export against real pixels.

These tests rasterize for real (no mocked renderer) and inspect the resulting
images: dimensions, alpha, and that ink actually landed. A PNG exporter that
writes a valid-but-blank file is the failure mode worth catching, and only
pixel assertions catch it.

Skips when the rasterizer is unavailable, so a Python-only environment without
resvg-py still runs the rest of the suite.
"""

import os

import pytest

from gift_card_studio import catalog, exporter, models
from gift_card_studio.rasterizer import rasterizer_available

pytestmark = pytest.mark.skipif(
    not rasterizer_available(), reason="resvg-py rasterizer not installed"
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def image_module():
    from PIL import Image
    return Image


def catalog_entry(name="Vex", intent_command="spawnmob {mc} 5 vex {user}", category="5 Coins"):
    config = {
        "Gifts": {"5487": [intent_command, f"titlecustom '{{user}}' {{mc}} {name}"]},
        "GiftNames": {"5487": "finger heart"},
        "GiftCategories": {"5487": category},
    }
    # data/assets dirs that do not exist -> no catalog metadata, no cached icon.
    return catalog.build_catalog(config, "/nonexistent", "/nonexistent")[0]


@pytest.fixture
def project():
    """A 5-card 1x5 project on a small canvas, so tests stay fast."""
    entry = catalog_entry()
    entries = []
    for index in range(5):
        clone = dict(entry)
        clone["key"] = f"card{index}"
        clone["name"] = f"Gift {index}"
        clone["suggested_text"] = {"main": f"CARD {index}", "secondary": "5 Coins"}
        entries.append(clone)

    payload = models.new_project("Pixel Test")
    payload["canvas"].update({"width": 640, "height": 360, "background": "transparent"})
    payload["pages"][0]["grid"].update({"rows": 1, "columns": 5, "gap_x": 8, "padding": 8})
    payload = models.normalize_project(payload)
    return catalog.apply_catalog_import(payload, entries)["project"]


def _load(image_module, path):
    with image_module.open(path) as handle:
        handle.load()
        return handle.convert("RGBA")


class TestDimensionResolution:

    def test_scale_multiplies_both_axes(self):
        assert exporter._scaled_dimensions(640, 360, 2.0) == (1280, 720)
        assert exporter._scaled_dimensions(640, 360, 0.5) == (320, 180)

    def test_explicit_width_preserves_aspect_ratio(self):
        assert exporter._scaled_dimensions(640, 360, target_width=1280) == (1280, 720)

    def test_explicit_height_preserves_aspect_ratio(self):
        assert exporter._scaled_dimensions(640, 360, target_height=180) == (320, 180)

    def test_both_targets_are_honoured_verbatim(self):
        assert exporter._scaled_dimensions(640, 360, target_width=100, target_height=100) == (100, 100)

    def test_an_absurd_scale_is_refused_before_allocating(self):
        with pytest.raises(exporter.ExportError):
            exporter._scaled_dimensions(1920, 1080, 100.0)


class TestEstimate:

    def test_png_page_estimate_reports_one_file(self, project):
        estimate = exporter.estimate_export(project, "page")

        assert estimate["file_count"] == 1
        assert (estimate["width"], estimate["height"]) == (640, 360)

    def test_pages_estimate_counts_every_page(self, project):
        project["pages"].append(models.default_page(1))
        project = models.normalize_project(project)

        assert exporter.estimate_export(project, "pages")["file_count"] == 2

    def test_gif_estimate_reports_frames_and_duration(self, project):
        project["playback"]["default_page_duration_ms"] = 2000
        project = models.normalize_project(project)

        estimate = exporter.estimate_export(project, "gif", fps=15)

        assert estimate["frame_count"] == 30
        assert estimate["duration_ms"] == 2000
        assert estimate["exceeds_frame_limit"] is False

    def test_gif_estimate_flags_an_over_long_export(self, project):
        estimate = exporter.estimate_export(project, "gif", fps=30, duration_ms=120_000)

        assert estimate["exceeds_frame_limit"] is True

    def test_scale_is_reflected_in_the_estimate(self, project):
        estimate = exporter.estimate_export(project, "page", scale=2.0)

        assert (estimate["width"], estimate["height"]) == (1280, 720)


class TestCardPng:

    def test_a_card_exports_at_its_logical_size_with_visible_ink(self, project, tmp_path, image_module):
        report = exporter.export_png(project, str(tmp_path), mode="card", base_dir=ROOT)

        assert report["file_count"] == 1
        image = _load(image_module, report["files"][0])
        assert image.size == (320, 320)
        assert image.getbbox() is not None, "exported card is blank"

    def test_card_scale_multiplies_the_output(self, project, tmp_path, image_module):
        report = exporter.export_png(project, str(tmp_path), mode="card", scale=2.0, base_dir=ROOT)

        assert _load(image_module, report["files"][0]).size == (640, 640)

    def test_exporting_a_specific_card_by_id(self, project, tmp_path, image_module):
        target = project["pages"][0]["cards"][3]

        report = exporter.export_png(
            project, str(tmp_path), mode="card", card_id=target["id"], base_dir=ROOT
        )

        assert len(report["files"]) == 1
        assert _load(image_module, report["files"][0]).getbbox() is not None

    def test_an_unknown_card_id_is_an_error_not_a_blank_file(self, project, tmp_path):
        with pytest.raises(exporter.ExportError):
            exporter.export_png(project, str(tmp_path), mode="card", card_id="nope", base_dir=ROOT)

        assert os.listdir(tmp_path) == []

    def test_all_cards_mode_writes_one_file_each(self, project, tmp_path):
        report = exporter.export_png(project, str(tmp_path), mode="cards", base_dir=ROOT)

        assert report["file_count"] == 5
        assert len(os.listdir(tmp_path)) == 5


class TestPagePng:

    def test_a_page_exports_at_canvas_size(self, project, tmp_path, image_module):
        report = exporter.export_png(project, str(tmp_path), mode="page", base_dir=ROOT)

        image = _load(image_module, report["files"][0])
        assert image.size == (640, 360)

    def test_a_transparent_canvas_stays_transparent(self, project, tmp_path, image_module):
        """These are OBS overlay assets: the background must not become black."""
        report = exporter.export_png(project, str(tmp_path), mode="page", base_dir=ROOT)

        image = _load(image_module, report["files"][0])
        assert image.getpixel((0, 0))[3] == 0
        assert image.getpixel((image.width - 1, image.height - 1))[3] == 0

    def test_the_five_cells_all_contain_ink(self, project, tmp_path, image_module):
        """Acceptance criterion 5, verified in pixels rather than in geometry."""
        report = exporter.export_png(project, str(tmp_path), mode="page", base_dir=ROOT)
        image = _load(image_module, report["files"][0])

        # 640 wide, padding 8, gap 8 -> cells ~124.8 wide. Sample each centre.
        for index in range(5):
            centre_x = int(8 + index * (124.8 + 8) + 124.8 / 2)
            column = [image.getpixel((centre_x, y))[3] for y in range(image.height)]
            assert any(alpha > 0 for alpha in column), f"cell {index} is empty"

    def test_a_solid_background_is_actually_painted(self, project, tmp_path, image_module):
        project["canvas"]["background"] = "#101014"
        project = models.normalize_project(project)

        report = exporter.export_png(project, str(tmp_path), mode="page", base_dir=ROOT)

        image = _load(image_module, report["files"][0])
        assert image.getpixel((0, 0)) == (16, 16, 20, 255)

    def test_page_scale_multiplies_the_output(self, project, tmp_path, image_module):
        report = exporter.export_png(project, str(tmp_path), mode="page", scale=2.0, base_dir=ROOT)

        assert _load(image_module, report["files"][0]).size == (1280, 720)

    def test_an_out_of_range_page_index_is_an_error(self, project, tmp_path):
        with pytest.raises(exporter.ExportError):
            exporter.export_png(project, str(tmp_path), mode="page", page_index=9, base_dir=ROOT)

    def test_all_pages_mode_writes_numbered_files(self, project, tmp_path):
        project["pages"].append(models.default_page(1))
        project = models.normalize_project(project)

        report = exporter.export_png(project, str(tmp_path), mode="pages", base_dir=ROOT)

        assert report["file_count"] == 2
        names = sorted(os.path.basename(p) for p in report["files"])
        assert names[0].endswith("-001.png")
        assert names[1].endswith("-002.png")


class TestSheetPng:

    def test_a_sheet_holds_every_card_and_grows_vertically(self, project, tmp_path, image_module):
        # 5 cards in a 5-column grid = 1 row; add a second page to force 2 rows.
        project["pages"].append(models.default_page(1))
        project = models.normalize_project(project)
        entry = catalog_entry()
        entry["key"] = "extra"
        project = catalog.apply_catalog_import(project, [entry])["project"]

        report = exporter.export_png(project, str(tmp_path), mode="sheet", base_dir=ROOT)

        image = _load(image_module, report["files"][0])
        assert image.width == 640
        assert image.height > 360, "sheet did not grow to fit the second row"
        assert image.getbbox() is not None

    def test_a_sheet_of_an_empty_project_is_refused(self, tmp_path):
        empty = models.new_project("Empty")

        with pytest.raises(exporter.ExportError):
            exporter.export_png(empty, str(tmp_path), mode="sheet", base_dir=ROOT)


class TestCancellationAndCleanup:

    def test_cancelling_mid_export_removes_every_partial_file(self, project, tmp_path):
        calls = {"n": 0}

        def is_cancelled():
            calls["n"] += 1
            return calls["n"] > 3

        with pytest.raises(exporter.ExportCancelled):
            exporter.export_png(
                project, str(tmp_path), mode="cards", base_dir=ROOT, is_cancelled=is_cancelled
            )

        assert os.listdir(tmp_path) == [], "cancelled export left files behind"

    def test_a_failure_mid_export_also_cleans_up(self, project, tmp_path, monkeypatch):
        original = exporter.render_card_png
        state = {"n": 0}

        def flaky(*args, **kwargs):
            state["n"] += 1
            if state["n"] > 2:
                raise RuntimeError("rasterizer exploded")
            return original(*args, **kwargs)

        monkeypatch.setattr(exporter, "render_card_png", flaky)

        with pytest.raises(RuntimeError):
            exporter.export_png(project, str(tmp_path), mode="cards", base_dir=ROOT)

        assert os.listdir(tmp_path) == []

    def test_a_successful_export_leaves_exactly_its_files(self, project, tmp_path):
        report = exporter.export_png(project, str(tmp_path), mode="page", base_dir=ROOT)

        assert sorted(os.listdir(tmp_path)) == [os.path.basename(report["files"][0])]


class TestFilenameSafety:

    def test_card_names_are_sanitized_into_filenames(self):
        assert exporter._safe_filename("../../etc/passwd") == "etcpasswd.png"
        assert exporter._safe_filename("My Gift!") == "MyGift.png"
        assert exporter._safe_filename("") == "export.png"
        assert exporter._safe_filename(None) == "export.png"

    def test_indexed_filenames_are_zero_padded(self):
        assert exporter._safe_filename("page", 7) == "page-007.png"

    def test_a_hostile_card_name_cannot_escape_the_output_dir(self, project, tmp_path):
        project["pages"][0]["cards"][0]["name"] = "../../escaped"
        project = models.normalize_project(project)

        report = exporter.export_png(
            project, str(tmp_path), mode="card",
            card_id=project["pages"][0]["cards"][0]["id"], base_dir=ROOT,
        )

        written = os.path.abspath(report["files"][0])
        assert written.startswith(os.path.abspath(str(tmp_path)) + os.sep)
