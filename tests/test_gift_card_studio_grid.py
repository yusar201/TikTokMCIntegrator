"""Gift Card Studio — pure grid geometry.

Locks the plan's resize contract:
    cell_width  = (W - 2P - (C - 1)Gx) / C
    cell_height = (H - 2P - (R - 1)Gy) / R
plus contain/cover/stretch fit, fill order, and overflow behavior.
"""

from gift_card_studio import grid


def make_grid(**overrides):
    base = {
        "rows": 1,
        "columns": 1,
        "gap_x": 0,
        "gap_y": 0,
        "padding": 0,
        "fill_order": "row",
        "fit": "contain",
    }
    base.update(overrides)
    return base


class TestCellSize:

    def test_single_cell_with_no_padding_fills_the_canvas(self):
        assert grid.cell_size(1920, 1080, make_grid()) == (1920.0, 1080.0)

    def test_one_by_five_matches_the_documented_formula(self):
        g = make_grid(rows=1, columns=5, gap_x=20, padding=24)

        width, height = grid.cell_size(1920, 1080, g)

        # (1920 - 48 - 4*20) / 5 = 358.4
        assert width == 358.4
        assert height == 1032.0

    def test_two_by_three_matches_the_documented_formula(self):
        g = make_grid(rows=2, columns=3, gap_x=20, gap_y=20, padding=24)

        width, height = grid.cell_size(1920, 1080, g)

        assert width == (1920 - 48 - 40) / 3
        assert height == (1080 - 48 - 20) / 2

    def test_over_padded_grid_collapses_to_zero_instead_of_inverting(self):
        g = make_grid(rows=1, columns=1, padding=2000)

        assert grid.cell_size(1920, 1080, g) == (0.0, 0.0)

    def test_gaps_only_apply_between_cells_not_at_the_edges(self):
        one = grid.cell_size(1000, 100, make_grid(columns=1, gap_x=50))[0]
        two = grid.cell_size(1000, 100, make_grid(columns=2, gap_x=50))[0]

        assert one == 1000.0
        assert two == 475.0


class TestCellBudget:

    def test_cell_count_multiplies_rows_by_columns(self):
        assert grid.cell_count(3, 4) == 12

    def test_one_hundred_cells_is_allowed_and_one_hundred_one_is_not(self):
        assert grid.exceeds_cell_budget(10, 10) is False
        assert grid.exceeds_cell_budget(20, 6) is True


class TestFillOrder:

    def test_row_order_walks_left_to_right_then_down(self):
        positions = [grid.cell_position(i, 2, 3, "row") for i in range(6)]

        assert positions == [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)]

    def test_column_order_walks_top_to_bottom_then_right(self):
        positions = [grid.cell_position(i, 2, 3, "column") for i in range(6)]

        assert positions == [(0, 0), (1, 0), (0, 1), (1, 1), (0, 2), (1, 2)]

    def test_index_and_position_are_inverses_for_both_orders(self):
        for order in ("row", "column"):
            for i in range(12):
                row, column = grid.cell_position(i, 3, 4, order)
                assert grid.cell_index(row, column, 3, 4, order) == i

    def test_unknown_fill_order_falls_back_to_row(self):
        assert grid.cell_position(1, 2, 3, "spiral") == grid.cell_position(1, 2, 3, "row")


class TestCellRects:

    def test_one_by_five_rects_are_evenly_spaced_and_inside_the_canvas(self):
        g = make_grid(rows=1, columns=5, gap_x=20, padding=24)

        rects = grid.cell_rects(1920, 1080, g)

        assert len(rects) == 5
        assert rects[0]["x"] == 24
        assert rects[1]["x"] == 24 + 358.4 + 20
        last = rects[-1]
        assert abs((last["x"] + last["width"]) - (1920 - 24)) < 1e-9

    def test_rects_carry_their_row_and_column(self):
        rects = grid.cell_rects(600, 400, make_grid(rows=2, columns=2))

        assert [(r["row"], r["column"]) for r in rects] == [(0, 0), (0, 1), (1, 0), (1, 1)]


class TestFitScale:

    def test_contain_uses_the_smaller_axis_so_nothing_is_clipped(self):
        # card 320x400 into a 358.4x1032 cell -> height is not the constraint
        scale_x, scale_y = grid.fit_scale(320, 400, 358.4, 1032, "contain")

        assert scale_x == scale_y
        assert scale_x == 358.4 / 320

    def test_cover_uses_the_larger_axis_and_overflows(self):
        scale_x, scale_y = grid.fit_scale(320, 400, 358.4, 1032, "cover")

        assert scale_x == scale_y
        assert scale_x == 1032 / 400

    def test_stretch_scales_axes_independently(self):
        scale_x, scale_y = grid.fit_scale(320, 400, 640, 400, "stretch")

        assert (scale_x, scale_y) == (2.0, 1.0)

    def test_unknown_fit_falls_back_to_contain(self):
        assert grid.fit_scale(100, 100, 50, 200, "warp") == grid.fit_scale(100, 100, 50, 200, "contain")

    def test_degenerate_card_size_yields_zero_scale_not_a_crash(self):
        assert grid.fit_scale(0, 400, 100, 100) == (0.0, 0.0)


class TestCardTransform:

    def test_contain_centres_the_scaled_card_in_its_cell(self):
        cell = {"x": 100, "y": 200, "width": 400, "height": 400}

        transform = grid.card_transform(320, 400, cell, "contain")

        assert transform["scale_x"] == 1.0
        assert transform["scaled_width"] == 320
        assert transform["offset_x"] == 100 + (400 - 320) / 2
        assert transform["offset_y"] == 200
        assert transform["clipped"] is False

    def test_cover_reports_clipping_on_the_overflowing_axis(self):
        cell = {"x": 0, "y": 0, "width": 400, "height": 400}

        # 320x400 card, cover scale = max(400/320, 400/400) = 1.25 -> 400x500
        transform = grid.card_transform(320, 400, cell, "cover")
        assert transform["scale_x"] == 1.25
        assert transform["scaled_height"] == 500
        assert transform["clipped"] is True

        # Matching aspect ratio covers exactly, so nothing spills.
        square = grid.card_transform(200, 200, cell, "cover")
        assert square["clipped"] is False

    def test_contain_never_reports_clipping(self):
        cell = {"x": 0, "y": 0, "width": 400, "height": 400}

        for size in ((320, 400), (800, 100), (50, 900)):
            assert grid.card_transform(*size, cell, "contain")["clipped"] is False

    def test_a_1x5_page_scales_a_default_card_down_to_fit(self):
        """Acceptance criterion 5: five correctly scaled cards on one page."""
        g = make_grid(rows=1, columns=5, gap_x=20, padding=24)
        rects = grid.cell_rects(1920, 1080, g)

        transforms = [grid.card_transform(320, 400, cell, "contain") for cell in rects]

        assert len(transforms) == 5
        for transform in transforms:
            assert transform["scaled_width"] <= 358.4 + 1e-9
            assert transform["scaled_height"] <= 1032 + 1e-9
            assert transform["clipped"] is False
        # uniform: every card gets the identical scale in a uniform grid
        assert len({round(t["scale_x"], 9) for t in transforms}) == 1


class TestLayoutPage:

    def _page(self, card_count, **grid_overrides):
        return {
            "grid": make_grid(**grid_overrides),
            "cards": [
                {"id": f"card-{i}", "width": 320, "height": 400} for i in range(card_count)
            ],
        }

    def test_every_card_within_the_cell_count_gets_a_placement(self):
        placements = grid.layout_page(
            self._page(5, rows=1, columns=5, gap_x=20, padding=24),
            {"width": 1920, "height": 1080},
        )

        assert len(placements) == 5
        assert all(p["visible"] for p in placements)
        assert all(p["transform"] is not None for p in placements)

    def test_overflow_cards_are_flagged_not_dropped_or_moved(self):
        placements = grid.layout_page(
            self._page(7, rows=1, columns=5),
            {"width": 1920, "height": 1080},
        )

        assert len(placements) == 7
        assert [p["visible"] for p in placements] == [True] * 5 + [False] * 2
        assert all(p["overflow"] for p in placements[5:])
        assert all(p["transform"] is None for p in placements[5:])

    def test_overflow_count_reports_cards_without_a_cell(self):
        assert grid.overflow_count(self._page(7, rows=1, columns=5)) == 2
        assert grid.overflow_count(self._page(3, rows=1, columns=5)) == 0

    def test_empty_page_has_no_placements(self):
        assert grid.layout_page(self._page(0), {"width": 800, "height": 600}) == []

    def test_placements_preserve_card_ids_and_order(self):
        placements = grid.layout_page(
            self._page(3, rows=1, columns=3),
            {"width": 900, "height": 300},
        )

        assert [p["card_id"] for p in placements] == ["card-0", "card-1", "card-2"]
        assert [p["index"] for p in placements] == [0, 1, 2]


class TestContentExtent:

    def test_extent_covers_the_laid_out_cells_plus_padding(self):
        page = {
            "grid": make_grid(rows=1, columns=3, gap_x=10, padding=20),
            "cards": [{"id": str(i), "width": 100, "height": 100} for i in range(3)],
        }

        width, height = grid.content_extent(page, {"width": 620, "height": 200})

        assert width == 620.0
        assert height == 200.0

    def test_empty_page_falls_back_to_the_canvas_so_scroll_cannot_divide_by_zero(self):
        page = {"grid": make_grid(), "cards": []}

        assert grid.content_extent(page, {"width": 800, "height": 600}) == (800.0, 600.0)
