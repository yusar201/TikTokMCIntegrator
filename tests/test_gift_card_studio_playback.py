"""Gift Card Studio — deterministic playback timeline.

Covers page windows, transition boundaries and clamping, scroll distance/speed
maths, loop seams, and export frame timing.
"""

import pytest

from gift_card_studio import models, playback


def project_with_pages(count=3, duration=1000, transition=None, loop=True):
    payload = {
        "name": "Playback",
        "playback": {
            "mode": "pages",
            "loop": loop,
            "default_page_duration_ms": duration,
            "default_transition": transition or {"type": "cut", "duration_ms": 0},
        },
        "pages": [
            {
                "name": f"Page {i + 1}",
                "grid": {"rows": 1, "columns": 1},
                "cards": [{"name": f"card {i}", "width": 320, "height": 400}],
            }
            for i in range(count)
        ],
    }
    return models.normalize_project(payload)


def scrolling_project(direction="left", speed=100.0, loop=True, edge_pause=0,
                      columns=3, cards=6, canvas=(900, 300), item_gap=0):
    """A scroll-mode project.

    ``columns`` is the *visible* window (a 1x3 grid shows three cards at a
    time); ``cards`` is how many exist in total. Scrolling only has anything to
    reveal when cards > visible cells, which is the real-world case.
    """
    payload = {
        "name": "Scroller",
        "canvas": {"width": canvas[0], "height": canvas[1]},
        "playback": {"mode": "scroll", "loop": True},
        "pages": [{
            "grid": {"rows": 1, "columns": columns, "gap_x": 0, "gap_y": 0, "padding": 0},
            "scroll": {
                "enabled": True,
                "direction": direction,
                "speed_px_per_second": speed,
                "loop": loop,
                "edge_pause_ms": edge_pause,
                "item_gap": item_gap,
            },
            "cards": [
                {"name": f"c{i}", "width": 300, "height": 300} for i in range(cards)
            ],
        }],
    }
    return models.normalize_project(payload)


class TestPageWindows:

    def test_windows_are_contiguous_and_cover_the_whole_loop(self):
        project = project_with_pages(3, duration=1000)

        windows = playback.page_windows(project)

        assert [w["start_ms"] for w in windows] == [0, 1000, 2000]
        assert [w["end_ms"] for w in windows] == [1000, 2000, 3000]
        assert playback.loop_duration_ms(project) == 3000

    def test_per_page_duration_overrides_the_default(self):
        project = models.normalize_project({
            "playback": {"default_page_duration_ms": 1000},
            "pages": [{"duration_ms": 250}, {"duration_ms": None}, {"duration_ms": 4000}],
        })

        windows = playback.page_windows(project)

        assert [w["duration_ms"] for w in windows] == [250, 1000, 4000]
        assert windows[-1]["end_ms"] == 5250

    def test_transition_is_clamped_to_half_the_shorter_neighbour(self):
        project = models.normalize_project({
            "playback": {"default_page_duration_ms": 5000},
            "pages": [
                {"duration_ms": 400},
                {"duration_ms": 5000, "transition": {"type": "fade", "duration_ms": 4000}},
            ],
        })

        windows = playback.page_windows(project)

        assert windows[1]["transition_ms"] == 200

    def test_a_cut_has_no_transition_window(self):
        project = project_with_pages(2, transition={"type": "cut", "duration_ms": 500})

        assert all(w["transition_ms"] == 0 for w in playback.page_windows(project))
        assert all(w["transition_type"] == "cut" for w in playback.page_windows(project))

    def test_sub_millisecond_transitions_collapse_to_a_cut(self):
        project = models.normalize_project({
            "playback": {"default_page_duration_ms": 1000},
            "pages": [{}, {"transition": {"type": "fade", "duration_ms": 0}}],
        })

        assert playback.page_windows(project)[1]["transition_type"] == "cut"


class TestPagesStateAt:

    def test_time_zero_shows_the_first_page(self):
        state = playback.pages_state_at(project_with_pages(3), 0)

        assert state["page_index"] == 0
        assert state["transition_type"] == "cut"

    def test_boundaries_select_the_expected_page(self):
        project = project_with_pages(3, duration=1000)

        assert playback.state_at(project, 999)["page_index"] == 0
        assert playback.state_at(project, 1000)["page_index"] == 1
        assert playback.state_at(project, 1999)["page_index"] == 1
        assert playback.state_at(project, 2000)["page_index"] == 2
        assert playback.state_at(project, 2999)["page_index"] == 2

    def test_time_wraps_when_looping(self):
        project = project_with_pages(3, duration=1000, loop=True)

        assert playback.state_at(project, 3000)["page_index"] == 0
        assert playback.state_at(project, 4500)["page_index"] == 1
        assert playback.state_at(project, 10_000)["page_index"] == 1

    def test_a_non_looping_project_holds_the_final_page(self):
        project = project_with_pages(3, duration=1000, loop=False)

        assert playback.state_at(project, 99_999)["page_index"] == 2

    def test_negative_time_clamps_to_the_start(self):
        assert playback.state_at(project_with_pages(3), -500)["page_index"] == 0

    def test_transition_progress_runs_zero_to_one_across_its_window(self):
        project = project_with_pages(
            2, duration=1000, transition={"type": "fade", "duration_ms": 400}
        )

        start = playback.state_at(project, 1000)
        middle = playback.state_at(project, 1200)
        end = playback.state_at(project, 1400)

        assert start["transition_progress"] == pytest.approx(0.0)
        assert middle["transition_progress"] == pytest.approx(0.5)
        assert start["previous_index"] == 0
        assert start["page_index"] == 1
        assert middle["transition_type"] == "fade"
        # At the far edge the transition is finished: single page, no pair.
        assert end["transition_progress"] == 1.0
        assert end["previous_index"] is None

    def test_outside_a_transition_only_one_page_is_active(self):
        project = project_with_pages(
            2, duration=1000, transition={"type": "fade", "duration_ms": 400}
        )

        state = playback.state_at(project, 1700)

        assert state["previous_page"] is None
        assert state["transition_type"] == "cut"

    def test_a_looping_project_transitions_into_page_one_from_the_last_page(self):
        project = project_with_pages(
            3, duration=1000, transition={"type": "slide", "duration_ms": 200}, loop=True
        )

        state = playback.state_at(project, 0)

        assert state["page_index"] == 0
        assert state["previous_index"] == 2

    def test_a_non_looping_project_does_not_transition_into_its_first_page(self):
        project = project_with_pages(
            3, duration=1000, transition={"type": "slide", "duration_ms": 200}, loop=False
        )

        state = playback.state_at(project, 0)

        assert state["previous_index"] is None
        assert state["transition_type"] == "cut"

    def test_an_empty_project_yields_a_safe_state(self):
        project = models.normalize_project({"pages": []})
        project["pages"] = []

        state = playback.pages_state_at(project, 500)

        assert state["page"] is None
        assert state["loop_ms"] == 0


class TestScrollGeometry:
    """Geometry uses a 900x300 canvas, 1x3 visible grid, so cells are 300x300."""

    def test_the_strip_extends_past_the_canvas_so_scrolling_reveals_cards(self):
        # 6 cards x 300px = 1800px of strip on a 900px canvas.
        project = scrolling_project(columns=3, cards=6, canvas=(900, 300))

        assert playback.scroll_travel_px(project) == 1800.0

    def test_travel_for_a_seamless_loop_is_the_whole_strip(self):
        project = scrolling_project(loop=True, columns=3, cards=4, canvas=(900, 300))

        assert playback.scroll_travel_px(project) == 1200.0

    def test_travel_for_a_non_looping_reveal_excludes_the_visible_window(self):
        project = scrolling_project(loop=False, columns=3, cards=6, canvas=(900, 300))

        # strip 1800 wide, canvas 900 -> only 900px needs to move
        assert playback.scroll_travel_px(project) == 900.0

    def test_a_non_looping_scroll_that_already_fits_does_not_move(self):
        project = scrolling_project(loop=False, columns=3, cards=3, canvas=(900, 300))

        assert playback.scroll_travel_px(project) == 0.0

    def test_item_gap_lengthens_the_strip(self):
        tight = scrolling_project(columns=3, cards=6, item_gap=0)
        spaced = scrolling_project(columns=3, cards=6, item_gap=20)

        # 6 tracks -> 5 gaps of 20px
        assert playback.scroll_travel_px(spaced) - playback.scroll_travel_px(tight) == 100.0

    def test_vertical_scroll_measures_the_vertical_strip(self):
        project = scrolling_project(direction="up", loop=True, columns=1, cards=4, canvas=(300, 300))

        # 1x1 visible grid on a 300-tall canvas -> 4 rows of 300
        assert playback.scroll_travel_px(project) == 1200.0

    def test_loop_duration_follows_distance_over_speed(self):
        project = scrolling_project(speed=100.0, loop=True, columns=3, cards=6, canvas=(900, 300))

        # 1800px at 100px/s = 18s
        assert playback.scroll_loop_duration_ms(project) == 18_000

    def test_doubling_the_speed_halves_the_duration(self):
        slow = scrolling_project(speed=100.0)
        fast = scrolling_project(speed=200.0)

        assert playback.scroll_loop_duration_ms(fast) * 2 == playback.scroll_loop_duration_ms(slow)

    def test_edge_pause_extends_the_cycle(self):
        no_pause = scrolling_project(speed=100.0, loop=True, edge_pause=0)
        paused = scrolling_project(speed=100.0, loop=True, edge_pause=1000)

        assert playback.scroll_loop_duration_ms(paused) - playback.scroll_loop_duration_ms(no_pause) == 1000

    def test_a_non_looping_scroll_pauses_at_both_edges(self):
        paused = scrolling_project(speed=100.0, loop=False, edge_pause=500, cards=6, canvas=(900, 300))
        no_pause = scrolling_project(speed=100.0, loop=False, edge_pause=0, cards=6, canvas=(900, 300))

        assert playback.scroll_loop_duration_ms(paused) - playback.scroll_loop_duration_ms(no_pause) == 1000


class TestStripLayout:

    def test_every_card_gets_a_placement_even_beyond_the_visible_cells(self):
        """Scroll mode must not hide overflow the way a static page does."""
        project = scrolling_project(columns=3, cards=6, canvas=(900, 300))
        page = project["pages"][0]

        from gift_card_studio import grid as gridmod
        placements = gridmod.strip_layout(page, project["canvas"], horizontal=True, item_gap=0)

        assert len(placements) == 6
        assert all(p["visible"] for p in placements)

    def test_strip_positions_advance_along_the_scroll_axis(self):
        project = scrolling_project(columns=3, cards=4, canvas=(900, 300))
        from gift_card_studio import grid as gridmod

        placements = gridmod.strip_layout(project["pages"][0], project["canvas"], True, 0)

        assert [p["cell"]["x"] for p in placements] == [0.0, 300.0, 600.0, 900.0]
        assert all(p["cell"]["y"] == 0.0 for p in placements)

    def test_a_two_row_strip_fills_each_column_before_advancing(self):
        project = scrolling_project(columns=3, cards=4, canvas=(900, 600))
        project["pages"][0]["grid"]["rows"] = 2
        from gift_card_studio import grid as gridmod

        placements = gridmod.strip_layout(project["pages"][0], project["canvas"], True, 0)
        columns = [p["cell"]["column"] for p in placements]

        assert columns == [0, 0, 1, 1]


class TestScrollStateAt:

    def test_distance_equals_elapsed_seconds_times_speed(self):
        """Acceptance criterion 7: exact px/s, not a vague speed setting."""
        project = scrolling_project(speed=100.0, loop=True, columns=3, canvas=(900, 300))

        for seconds in (0, 1, 2.5, 4, 8):
            state = playback.state_at(project, seconds * 1000)
            assert state["scroll"]["distance"] == pytest.approx(seconds * 100.0, abs=1e-6)

    def test_left_moves_content_negative_and_right_positive(self):
        left = playback.state_at(scrolling_project(direction="left", speed=100.0), 1000)
        right = playback.state_at(scrolling_project(direction="right", speed=100.0), 1000)

        assert left["scroll"]["offset_x"] == pytest.approx(-100.0)
        assert right["scroll"]["offset_x"] == pytest.approx(100.0)
        assert left["scroll"]["offset_y"] == 0.0

    def test_up_moves_content_negative_and_down_positive(self):
        up = playback.state_at(scrolling_project(direction="up", speed=100.0, columns=1, canvas=(300, 300)), 1000)
        down = playback.state_at(scrolling_project(direction="down", speed=100.0, columns=1, canvas=(300, 300)), 1000)

        assert up["scroll"]["offset_y"] == pytest.approx(-100.0)
        assert down["scroll"]["offset_y"] == pytest.approx(100.0)
        assert up["scroll"]["offset_x"] == 0.0

    def test_the_loop_seam_returns_to_the_start(self):
        project = scrolling_project(speed=100.0, loop=True, columns=3, canvas=(900, 300))
        cycle = playback.scroll_loop_duration_ms(project)

        start = playback.state_at(project, 0)["scroll"]
        wrapped = playback.state_at(project, cycle)["scroll"]

        assert wrapped["distance"] == pytest.approx(start["distance"])
        assert wrapped["offset_x"] == pytest.approx(start["offset_x"])

    def test_progress_saturates_at_one_and_never_exceeds_travel(self):
        project = scrolling_project(speed=100.0, loop=True, columns=3, canvas=(900, 300))

        for time_ms in range(0, 20_000, 137):
            scroll = playback.state_at(project, time_ms)["scroll"]
            assert 0.0 <= scroll["progress"] <= 1.0
            assert abs(scroll["distance"]) <= scroll["travel"] + 1e-9

    def test_an_edge_pause_holds_position_before_moving(self):
        project = scrolling_project(speed=100.0, loop=True, edge_pause=1000)

        assert playback.state_at(project, 0)["scroll"]["distance"] == 0.0
        assert playback.state_at(project, 500)["scroll"]["distance"] == 0.0
        assert playback.state_at(project, 1500)["scroll"]["distance"] == pytest.approx(50.0)

    def test_a_scroll_project_with_no_content_cannot_divide_by_zero(self):
        project = models.normalize_project({
            "canvas": {"width": 800, "height": 600},
            "playback": {"mode": "scroll"},
            "pages": [{"scroll": {"enabled": True}, "cards": []}],
        })

        state = playback.state_at(project, 1234)

        assert state["scroll"]["distance"] == 0.0
        assert state["loop_ms"] >= 0

    def test_scroll_mode_reports_no_page_transition(self):
        state = playback.state_at(scrolling_project(), 500)

        assert state["mode"] == "scroll"
        assert state["previous_page"] is None
        assert state["transition_type"] == "cut"


class TestFrameTiming:

    def test_a_five_second_loop_at_fifteen_fps_is_seventy_five_frames(self):
        project = project_with_pages(1, duration=5000)

        assert playback.frame_count(project, 15) == 75

    def test_frame_times_are_evenly_spaced_without_float_drift(self):
        project = project_with_pages(1, duration=1000)

        times = playback.frame_times(project, 30)

        assert times[0] == 0
        assert times[1] == 33
        assert len(times) == 30
        assert all(isinstance(t, int) for t in times)
        assert times == sorted(times)
        assert len(set(times)) == len(times)

    def test_frame_times_stay_inside_one_loop(self):
        project = project_with_pages(3, duration=1000)

        times = playback.frame_times(project, 15)

        assert max(times) < playback.loop_duration_ms(project)

    def test_an_explicit_duration_overrides_the_loop_length(self):
        project = project_with_pages(3, duration=1000)

        assert playback.frame_count(project, 10, duration_ms=2000) == 20

    def test_frame_times_for_a_scroll_project_cover_one_cycle(self):
        project = scrolling_project(speed=100.0, loop=True, columns=3, cards=6, canvas=(900, 300))

        times = playback.frame_times(project, 15)

        assert len(times) == 270  # 1800px at 100px/s = 18s, at 15fps
        assert max(times) < playback.scroll_loop_duration_ms(project)

    def test_a_zero_length_project_still_yields_one_frame(self):
        project = models.normalize_project({"pages": []})
        project["pages"] = []

        assert playback.frame_times(project, 15) == [0]

    def test_fps_is_floored_at_one(self):
        project = project_with_pages(1, duration=1000)

        assert playback.frame_count(project, 0) == 1


class TestDeterminism:

    def test_the_same_time_always_yields_the_same_state(self):
        project = project_with_pages(
            3, duration=1000, transition={"type": "pixel_wipe", "duration_ms": 300}
        )

        for time_ms in (0, 150, 999, 1000, 1150, 2999, 3000, 7777):
            first = playback.state_at(project, time_ms)
            second = playback.state_at(project, time_ms)
            assert first == second

    def test_state_does_not_mutate_the_project(self):
        import json
        project = project_with_pages(3, duration=1000)
        before = json.dumps(project, sort_keys=True)

        for time_ms in range(0, 4000, 250):
            playback.state_at(project, time_ms)

        assert json.dumps(project, sort_keys=True) == before
