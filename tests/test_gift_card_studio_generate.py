"""Generate settings validation and one-artifact-per-generate behaviour.

The Studio's product is a downloadable file, so these tests care about two
things: that a bad setting is rejected with a message the user can act on
*before* any rasterization starts, and that a generate yields exactly one
artifact to hand to OBS.
"""

import os
import zipfile

import pytest

from gift_card_studio import catalog, exporter, generate, models

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _entry(key="a", label="Warden"):
    config = {
        "Gifts": {"5487": ["spawnmob {mc} 1 warden {user}", f"titlecustom '{{user}}' {{mc}} {label}"]},
        "GiftNames": {"5487": "gold necklace"},
        "GiftCategories": {"5487": "200 Coins"},
    }
    entry = catalog.build_catalog(config, "/nonexistent", "/nonexistent")[0]
    entry["key"] = key
    entry["name"] = label
    return entry


@pytest.fixture
def project():
    payload = models.new_project("Generate Test")
    payload["canvas"].update({"width": 480, "height": 200, "background": "transparent"})
    payload["pages"][0]["grid"].update({"rows": 1, "columns": 3, "gap_x": 8, "padding": 8})
    payload["playback"].update({
        "mode": "pages", "default_page_duration_ms": 600,
        "default_transition": {"type": "fade", "duration_ms": 200},
    })
    base = models.normalize_project(payload)
    return catalog.apply_catalog_import(
        base, [_entry(f"c{i}", f"C{i}") for i in range(3)]
    )["project"]


@pytest.fixture
def two_page_project(project):
    project["pages"].append(models.default_page(1))
    project = models.normalize_project(project)
    project["pages"][1]["grid"].update({"rows": 1, "columns": 3, "gap_x": 8, "padding": 8})
    return catalog.apply_catalog_import(
        models.normalize_project(project), [_entry(f"d{i}", f"D{i}") for i in range(3)]
    )["project"]


class _Context:
    """Stand-in for the job context, recording progress calls."""

    def __init__(self, output_dir):
        self.output_dir = str(output_dir)
        self.calls = []
        self._cancel = False

    def progress(self, done, total):
        self.calls.append((done, total))

    def cancelled(self):
        return self._cancel

    def check_cancelled(self):
        if self._cancel:
            from gift_card_studio.jobs import JobCancelled
            raise JobCancelled("cancelled")


class TestSettingsValidation:

    def test_defaults_produce_a_single_page_png(self):
        settings = generate.normalize_settings(None)

        assert settings["format"] == "png"
        assert settings["mode"] == "page"
        assert settings["scale"] == 1.0
        assert settings["background"] is None

    def test_an_unknown_format_is_rejected_by_name(self):
        with pytest.raises(generate.SettingsError, match="format must be one of"):
            generate.normalize_settings({"format": "webp"})

    def test_an_unknown_png_mode_is_rejected(self):
        with pytest.raises(generate.SettingsError, match="mode must be one of"):
            generate.normalize_settings({"format": "png", "mode": "everything"})

    def test_an_unsupported_fps_names_the_valid_options(self):
        with pytest.raises(generate.SettingsError) as excinfo:
            generate.normalize_settings({"format": "gif", "fps": 12})

        for valid in exporter.VALID_FPS:
            assert str(valid) in str(excinfo.value)

    def test_zero_and_negative_scale_are_rejected(self):
        for bad in (0, -1, -0.5):
            with pytest.raises(generate.SettingsError, match="scale"):
                generate.normalize_settings({"scale": bad})

    def test_an_absurd_scale_is_rejected(self):
        with pytest.raises(generate.SettingsError, match="scale"):
            generate.normalize_settings({"scale": 100})

    def test_a_non_numeric_scale_says_so(self):
        with pytest.raises(generate.SettingsError, match="scale must be a number"):
            generate.normalize_settings({"scale": "big"})

    def test_transparent_background_normalizes_to_none(self):
        for value in ("", "transparent", None):
            assert generate.normalize_settings({"background": value})["background"] is None

    def test_omitted_gif_duration_means_one_loop(self):
        settings = generate.normalize_settings({"format": "gif"})

        assert settings["duration_ms"] is None

    def test_a_negative_gif_duration_is_rejected(self):
        with pytest.raises(generate.SettingsError, match="duration_ms must be positive"):
            generate.normalize_settings({"format": "gif", "duration_ms": -5})

    def test_an_over_long_gif_is_rejected_before_rendering(self):
        with pytest.raises(generate.SettingsError, match="cannot exceed"):
            generate.normalize_settings({"format": "gif", "duration_ms": 120_000})

    def test_gif_loop_defaults_to_forever(self):
        assert generate.normalize_settings({"format": "gif"})["loop"] == 0

    def test_png_settings_do_not_carry_gif_keys(self):
        settings = generate.normalize_settings({"format": "png"})

        assert "fps" not in settings
        assert "duration_ms" not in settings


class TestEstimate:

    def test_a_single_page_png_is_one_file(self, project):
        settings = generate.normalize_settings({"format": "png", "mode": "page"})

        info = generate.estimate(project, settings)

        assert info["file_count"] == 1
        assert info["zipped"] is False

    def test_cards_mode_counts_every_card(self, two_page_project):
        settings = generate.normalize_settings({"format": "png", "mode": "cards"})

        info = generate.estimate(two_page_project, settings)

        assert info["file_count"] == 6
        assert info["zipped"] is True

    def test_pages_mode_counts_every_page(self, two_page_project):
        settings = generate.normalize_settings({"format": "png", "mode": "pages"})

        info = generate.estimate(two_page_project, settings)

        assert info["file_count"] == 2
        assert info["zipped"] is True

    def test_scale_multiplies_the_reported_output_size(self, project):
        settings = generate.normalize_settings({"scale": 2.0})

        info = generate.estimate(project, settings)

        assert info["output_width"] == 960
        assert info["output_height"] == 400

    def test_a_gif_estimate_reports_real_frame_count(self, two_page_project):
        settings = generate.normalize_settings({"format": "gif", "fps": 15})

        info = generate.estimate(two_page_project, settings)

        # 2 pages x 600ms = 1200ms at 15fps = 18 frames.
        assert info["frame_count"] == 18
        assert info["duration_ms"] == 1200

    def test_estimate_touches_no_disk(self, project, tmp_path):
        settings = generate.normalize_settings({"format": "gif"})

        generate.estimate(project, settings)

        assert list(tmp_path.iterdir()) == []


class TestFeasibility:

    def test_an_oversized_canvas_is_rejected_with_its_dimensions(self, project):
        project["canvas"].update({"width": 8000, "height": 8000})
        settings = generate.normalize_settings({"scale": 2.0})

        with pytest.raises(generate.SettingsError, match="megapixel"):
            generate.check_feasible(models.normalize_project(project), settings)

    def test_too_many_gif_frames_suggests_the_fix(self, project):
        project["playback"]["default_page_duration_ms"] = 30_000
        settings = generate.normalize_settings({"format": "gif", "fps": 30, "duration_ms": 60_000})

        with pytest.raises(generate.SettingsError) as excinfo:
            generate.check_feasible(models.normalize_project(project), settings)

        assert "frame" in str(excinfo.value)

    def test_a_gif_canvas_over_the_frame_budget_is_rejected(self, project):
        project["canvas"].update({"width": 3000, "height": 3000})
        settings = generate.normalize_settings({"format": "gif"})

        with pytest.raises(generate.SettingsError, match="GIF frames are capped"):
            generate.check_feasible(models.normalize_project(project), settings)

    def test_card_mode_on_an_empty_project_is_rejected(self):
        empty = models.normalize_project(models.new_project("Empty"))
        settings = generate.normalize_settings({"format": "png", "mode": "cards"})

        with pytest.raises(generate.SettingsError, match="no cards"):
            generate.check_feasible(empty, settings)

    def test_a_page_index_past_the_end_names_the_real_count(self, project):
        settings = generate.normalize_settings(
            {"format": "png", "mode": "page", "page_index": 5}
        )

        with pytest.raises(generate.SettingsError, match="does not exist"):
            generate.check_feasible(project, settings)


class TestGenerateProducesOneArtifact:

    def test_a_single_page_png_is_handed_over_unzipped(self, project, tmp_path):
        """Wrapping a lone PNG in a zip would just make the user unpack it."""
        settings = generate.normalize_settings({"format": "png", "mode": "page"})
        context = _Context(tmp_path)

        artifact, report = generate.generate(project, settings, context, base_dir=ROOT)

        assert artifact.endswith(".png")
        assert report["zipped"] is False
        assert os.path.getsize(artifact) > 0

    def test_multi_file_png_modes_collapse_into_one_zip(self, two_page_project, tmp_path):
        settings = generate.normalize_settings({"format": "png", "mode": "pages"})
        context = _Context(tmp_path)

        artifact, report = generate.generate(
            two_page_project, settings, context, base_dir=ROOT
        )

        assert artifact.endswith(".zip")
        assert report["zipped"] is True
        assert report["archived_file_count"] == 2

    def test_the_zip_really_contains_valid_pngs(self, two_page_project, tmp_path):
        settings = generate.normalize_settings({"format": "png", "mode": "pages"})
        context = _Context(tmp_path)

        artifact, _ = generate.generate(two_page_project, settings, context, base_dir=ROOT)

        with zipfile.ZipFile(artifact) as archive:
            names = archive.namelist()
            assert len(names) == 2
            for name in names:
                assert name.endswith(".png")
                # PNG magic number — proves real image bytes, not empty files.
                assert archive.read(name)[:8] == b"\x89PNG\r\n\x1a\n"

    def test_the_loose_pngs_are_removed_after_zipping(self, two_page_project, tmp_path):
        settings = generate.normalize_settings({"format": "png", "mode": "pages"})
        context = _Context(tmp_path)

        generate.generate(two_page_project, settings, context, base_dir=ROOT)

        leftovers = [p for p in os.listdir(tmp_path) if p.endswith(".png")]
        assert leftovers == []

    def test_a_gif_generate_produces_one_animated_file(self, two_page_project, tmp_path):
        settings = generate.normalize_settings({"format": "gif", "fps": 10})
        context = _Context(tmp_path)

        artifact, report = generate.generate(
            two_page_project, settings, context, base_dir=ROOT
        )

        assert artifact.endswith(".gif")
        assert report["encoded_frame_count"] >= 2
        from PIL import Image
        with Image.open(artifact) as image:
            assert image.n_frames >= 2

    def test_the_report_carries_the_estimate_for_the_ui(self, project, tmp_path):
        settings = generate.normalize_settings({"format": "png"})
        context = _Context(tmp_path)

        _, report = generate.generate(project, settings, context, base_dir=ROOT)

        assert report["estimate"]["output_width"] == 480

    def test_progress_is_reported_and_ends_at_the_total(self, two_page_project, tmp_path):
        settings = generate.normalize_settings({"format": "gif", "fps": 10})
        context = _Context(tmp_path)

        generate.generate(two_page_project, settings, context, base_dir=ROOT)

        assert context.calls, "no progress was reported"
        done, total = context.calls[-1]
        assert done == total > 0

    def test_the_filename_is_derived_from_the_project(self, project, tmp_path):
        project["id"] = "my-gift-board"
        settings = generate.normalize_settings({"format": "png"})
        context = _Context(tmp_path)

        artifact, _ = generate.generate(project, settings, context, base_dir=ROOT)

        assert "my-gift-board" in os.path.basename(artifact)

    def test_a_hostile_project_id_cannot_escape_the_output_dir(self, project, tmp_path):
        project["id"] = "../../etc/passwd"
        settings = generate.normalize_settings({"format": "png"})
        context = _Context(tmp_path)

        artifact, _ = generate.generate(project, settings, context, base_dir=ROOT)

        assert os.path.dirname(os.path.abspath(artifact)) == os.path.abspath(str(tmp_path))
