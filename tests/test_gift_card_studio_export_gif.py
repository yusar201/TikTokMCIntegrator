"""Gift Card Studio — GIF export against real encoded files.

Verifies frame timing, loop metadata, transparency, cleanup, and the guard
rails. The important property is that the *encoded* GIF's total duration equals
the project's loop length: GIF stores delays in centiseconds, so naive rounding
silently plays the animation ~11% fast at 15fps.
"""

import os

import pytest

from gift_card_studio import catalog, exporter, models, playback
from gift_card_studio.rasterizer import rasterizer_available

pytestmark = pytest.mark.skipif(
    not rasterizer_available(), reason="resvg-py rasterizer not installed"
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _entry(key, label):
    config = {
        "Gifts": {"5487": ["spawnmob {mc} 5 vex {user}", f"titlecustom '{{user}}' {{mc}} {label}"]},
        "GiftNames": {"5487": "finger heart"},
        "GiftCategories": {"5487": "5 Coins"},
    }
    entry = catalog.build_catalog(config, "/nonexistent", "/nonexistent")[0]
    entry["key"] = key
    entry["name"] = label
    entry["suggested_text"] = {"main": label, "secondary": "5 Coins"}
    return entry


@pytest.fixture
def paged_project():
    """Two pages, 1s each, fading — small canvas so tests stay fast."""
    payload = models.new_project("Gif Pages")
    payload["canvas"].update({"width": 240, "height": 135, "background": "transparent"})
    payload["pages"][0]["grid"].update({"rows": 1, "columns": 2, "gap_x": 4, "padding": 4})
    payload["playback"].update({
        "mode": "pages",
        "default_page_duration_ms": 1000,
        "default_transition": {"type": "fade", "duration_ms": 300},
    })
    payload = models.normalize_project(payload)
    payload = catalog.apply_catalog_import(payload, [_entry("a", "AAA"), _entry("b", "BBB")])["project"]
    payload["pages"].append(models.default_page(1))
    payload = models.normalize_project(payload)
    payload["pages"][1]["grid"].update({"rows": 1, "columns": 2, "gap_x": 4, "padding": 4})
    payload = catalog.apply_catalog_import(
        models.normalize_project(payload), [_entry("c", "CCC"), _entry("d", "DDD")]
    )["project"]
    return payload


@pytest.fixture
def scroll_project():
    payload = models.new_project("Gif Scroll")
    payload["canvas"].update({"width": 240, "height": 80, "background": "transparent"})
    payload["playback"]["mode"] = "scroll"
    payload["pages"][0]["grid"].update({"rows": 1, "columns": 3, "gap_x": 0, "padding": 0})
    payload["pages"][0]["scroll"].update({
        "enabled": True, "direction": "left", "speed_px_per_second": 240.0,
        "loop": True, "item_gap": 0, "edge_pause_ms": 0,
    })
    payload = models.normalize_project(payload)
    entries = [_entry(f"s{i}", f"S{i}") for i in range(6)]
    return catalog.apply_catalog_import(payload, entries)["project"]


def _durations(path):
    from PIL import Image, ImageSequence

    with Image.open(path) as image:
        return [frame.info.get("duration", 0) for frame in ImageSequence.Iterator(image)]


def _open_gif(path):
    from PIL import Image
    return Image.open(path)


class TestFrameDurationAllocation:
    """gif_frame_durations is pure; test it without rasterizing."""

    @pytest.mark.parametrize("fps,total", [(15, 2000), (15, 5000), (30, 1000), (20, 3000), (10, 1000)])
    def test_durations_sum_to_the_exact_loop_length(self, fps, total):
        project = models.normalize_project({
            "playback": {"default_page_duration_ms": total}, "pages": [{}],
        })
        times = playback.frame_times(project, fps)

        durations = exporter.gif_frame_durations(times, total)

        assert sum(durations) == total, f"{fps}fps drifted"
        assert len(durations) == len(times)

    def test_every_delay_is_a_whole_centisecond(self):
        project = models.normalize_project({
            "playback": {"default_page_duration_ms": 2000}, "pages": [{}],
        })
        times = playback.frame_times(project, 15)

        durations = exporter.gif_frame_durations(times, 2000)

        assert all(delay % 10 == 0 for delay in durations)

    def test_fifteen_fps_alternates_between_60_and_70_rather_than_always_60(self):
        """Always-60ms would make a 15fps export play 11% fast."""
        project = models.normalize_project({
            "playback": {"default_page_duration_ms": 2000}, "pages": [{}],
        })
        times = playback.frame_times(project, 15)

        durations = set(exporter.gif_frame_durations(times, 2000))

        assert durations == {60, 70}

    def test_no_delay_is_ever_zero(self):
        project = models.normalize_project({
            "playback": {"default_page_duration_ms": 100}, "pages": [{}],
        })
        times = playback.frame_times(project, 30)

        assert all(delay >= 10 for delay in exporter.gif_frame_durations(times, 100))

    def test_an_empty_frame_list_yields_no_durations(self):
        assert exporter.gif_frame_durations([], 1000) == []


class TestPagedGif:

    def test_the_encoded_gif_lasts_exactly_the_project_loop(self, paged_project, tmp_path):
        """The whole point of the duration accumulator."""
        out = str(tmp_path / "pages.gif")

        report = exporter.export_gif(paged_project, out, fps=15, base_dir=ROOT)

        assert report["duration_ms"] == playback.loop_duration_ms(paged_project) == 2000
        assert sum(_durations(out)) == 2000

    def test_the_report_distinguishes_timeline_frames_from_encoded_frames(self, paged_project, tmp_path):
        out = str(tmp_path / "pages.gif")

        report = exporter.export_gif(paged_project, out, fps=15, base_dir=ROOT)

        # 2000ms at 15fps = 30 timeline frames; identical held frames merge.
        assert report["frame_count"] == 30
        assert 0 < report["encoded_frame_count"] <= 30
        assert report["encoded_frame_count"] == len(_durations(out))

    def test_the_gif_dimensions_follow_the_canvas(self, paged_project, tmp_path):
        out = str(tmp_path / "pages.gif")

        exporter.export_gif(paged_project, out, fps=15, base_dir=ROOT)

        with _open_gif(out) as image:
            assert image.size == (240, 135)

    def test_scale_multiplies_the_gif_dimensions(self, paged_project, tmp_path):
        out = str(tmp_path / "pages2x.gif")

        exporter.export_gif(paged_project, out, fps=15, scale=2.0, base_dir=ROOT)

        with _open_gif(out) as image:
            assert image.size == (480, 270)

    def test_infinite_loop_is_the_default(self, paged_project, tmp_path):
        out = str(tmp_path / "loop.gif")

        exporter.export_gif(paged_project, out, fps=15, base_dir=ROOT)

        with _open_gif(out) as image:
            assert image.info.get("loop") == 0

    def test_a_finite_loop_count_is_written(self, paged_project, tmp_path):
        out = str(tmp_path / "loop3.gif")

        exporter.export_gif(paged_project, out, fps=15, loop=3, base_dir=ROOT)

        with _open_gif(out) as image:
            assert image.info.get("loop") == 3

    def test_transparency_is_declared_and_the_corner_is_clear(self, paged_project, tmp_path):
        out = str(tmp_path / "alpha.gif")

        exporter.export_gif(paged_project, out, fps=15, base_dir=ROOT)

        with _open_gif(out) as image:
            assert image.info.get("transparency") == exporter.GIF_TRANSPARENT_INDEX
            assert image.convert("RGBA").getpixel((0, 0))[3] == 0

    def test_the_animation_actually_changes_between_pages(self, paged_project, tmp_path):
        """Two settled pages must not look the same.

        Deliberately samples mid-page rather than first-vs-last: with a seamless
        looping cross-fade, frame 0 is the *start* of the fade into page 0 and so
        legitimately shows page 1 at full opacity — identical to the final frame.
        Comparing the ends would assert a false requirement.
        """
        out = str(tmp_path / "moving.gif")

        exporter.export_gif(paged_project, out, fps=15, base_dir=ROOT)

        # 1000ms pages at 15fps: frame 7 is ~470ms (page 0 settled), frame 22 is
        # ~1470ms (page 1 settled) on the raw timeline.
        frames = [
            image.convert("RGB").tobytes()
            for image in exporter.render_gif_frames(paged_project, fps=15, base_dir=ROOT)
        ]

        assert frames[7] != frames[22], "both pages render identically"
        assert len(set(frames)) > 1, "the timeline is not advancing at all"

    def test_an_explicit_duration_overrides_the_loop_length(self, paged_project, tmp_path):
        out = str(tmp_path / "short.gif")

        report = exporter.export_gif(
            paged_project, out, fps=15, duration_ms=1000, base_dir=ROOT
        )

        assert report["frame_count"] == 15
        assert sum(_durations(out)) == 1000

    @pytest.mark.parametrize("fps", [10, 15, 20, 30])
    def test_every_supported_fps_encodes_a_correct_duration(self, paged_project, tmp_path, fps):
        out = str(tmp_path / f"fps{fps}.gif")

        exporter.export_gif(paged_project, out, fps=fps, base_dir=ROOT)

        assert sum(_durations(out)) == 2000

    def test_an_unsupported_fps_is_refused(self, paged_project, tmp_path):
        with pytest.raises(exporter.ExportError):
            exporter.export_gif(paged_project, str(tmp_path / "x.gif"), fps=7, base_dir=ROOT)


class TestScrollGif:

    def test_a_scroll_capture_encodes_its_full_cycle(self, scroll_project, tmp_path):
        out = str(tmp_path / "scroll.gif")
        expected = playback.scroll_loop_duration_ms(scroll_project)

        report = exporter.export_gif(scroll_project, out, fps=15, base_dir=ROOT)

        assert expected > 0
        assert report["duration_ms"] == expected
        assert sum(_durations(out)) == expected

    def test_scrolling_frames_differ_from_each_other(self, scroll_project, tmp_path):
        out = str(tmp_path / "scroll.gif")

        exporter.export_gif(scroll_project, out, fps=15, base_dir=ROOT)

        with _open_gif(out) as image:
            assert image.n_frames > 1
            image.seek(0)
            first = image.convert("RGB").tobytes()
            image.seek(1)
            second = image.convert("RGB").tobytes()
        assert first != second, "scroll is not moving between frames"

    def test_a_scroll_gif_keeps_its_transparent_background(self, scroll_project, tmp_path):
        out = str(tmp_path / "scroll.gif")

        exporter.export_gif(scroll_project, out, fps=15, base_dir=ROOT)

        with _open_gif(out) as image:
            assert image.info.get("transparency") == exporter.GIF_TRANSPARENT_INDEX


class TestGuardRails:

    def test_too_many_frames_is_refused_before_rendering(self, paged_project, tmp_path):
        with pytest.raises(exporter.ExportError, match="frames"):
            exporter.export_gif(
                paged_project, str(tmp_path / "huge.gif"),
                fps=30, duration_ms=120_000, base_dir=ROOT,
            )

        assert not os.path.exists(tmp_path / "huge.gif")

    def test_an_oversized_frame_is_refused(self, paged_project, tmp_path):
        with pytest.raises(exporter.ExportError):
            exporter.export_gif(
                paged_project, str(tmp_path / "big.gif"), fps=15, scale=40.0, base_dir=ROOT
            )

    def test_the_frame_generator_reports_progress(self, paged_project):
        seen = []

        for _ in exporter.render_gif_frames(
            paged_project, fps=10, base_dir=ROOT,
            on_progress=lambda done, total: seen.append((done, total)),
        ):
            pass

        assert seen[0] == (1, 20)
        assert seen[-1] == (20, 20)


class TestGifCancellationAndCleanup:

    def test_cancelling_leaves_no_output_file(self, paged_project, tmp_path):
        out = str(tmp_path / "cancelled.gif")
        calls = {"n": 0}

        def is_cancelled():
            calls["n"] += 1
            return calls["n"] > 5

        with pytest.raises(exporter.ExportCancelled):
            exporter.export_gif(paged_project, out, fps=15, base_dir=ROOT, is_cancelled=is_cancelled)

        assert not os.path.exists(out)
        assert os.listdir(tmp_path) == []

    def test_a_render_failure_leaves_no_partial_gif(self, paged_project, tmp_path, monkeypatch):
        out = str(tmp_path / "broken.gif")

        def explode(*args, **kwargs):
            raise RuntimeError("rasterizer exploded")
            yield  # pragma: no cover - generator marker

        monkeypatch.setattr(exporter, "render_gif_frames", explode)

        with pytest.raises(RuntimeError):
            exporter.export_gif(paged_project, out, fps=15, base_dir=ROOT)

        assert not os.path.exists(out)

    def test_a_successful_export_writes_exactly_one_file(self, paged_project, tmp_path):
        report = exporter.export_gif(
            paged_project, str(tmp_path / "only.gif"), fps=15, base_dir=ROOT
        )

        assert os.listdir(tmp_path) == ["only.gif"]
        assert report["bytes"] == os.path.getsize(report["path"]) > 0
