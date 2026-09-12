"""Gift Card Studio — project model, bounds, migration, and derived helpers.

Covers the plan's model contract:
  * normalize_project is total for messy values, strict for unsafe ids
  * every documented bound is enforced
  * optional layers stay optional
  * inherit-vs-explicit page duration/transition resolution
  * transition clamped to half the shorter adjacent page
"""

import pytest

from gift_card_studio import models
from gift_card_studio.validation import (
    MAX_CANVAS,
    MAX_COLUMNS,
    MAX_LAYERS_PER_CARD,
    MAX_PAGES,
    MAX_ROWS,
    ValidationError,
)


# ---------------------------------------------------------------------------
# Defaults and shape
# ---------------------------------------------------------------------------

class TestProjectDefaults:

    def test_empty_payload_yields_a_complete_single_page_project(self):
        project = models.normalize_project({})

        assert project["schema_version"] == models.SCHEMA_VERSION
        assert project["canvas"] == {
            "width": 1920,
            "height": 1080,
            "background": "transparent",
            "safe_padding": 32,
        }
        assert project["playback"]["mode"] == "pages"
        assert project["playback"]["default_page_duration_ms"] == 5000
        assert len(project["pages"]) == 1
        assert project["pages"][0]["cards"] == []
        assert project["card_library"] == []
        assert project["templates"] == []
        assert project["updated_at"].endswith("Z")

    def test_new_project_uses_a_slugified_id_and_keeps_the_display_name(self):
        project = models.new_project("Survival Rush Gifts!")

        assert project["id"] == "survival-rush-gifts"
        assert project["name"] == "Survival Rush Gifts!"

    def test_old_missing_action_asset_url_migrates_to_placeholder(self):
        card = models.normalize_card({
            "gift_ref": {"gift_id": "1", "name": "Rose"},
            "layers": [{"type": "action_icon", "asset": "/gift-studio-assets/action-mob.png"}],
        })

        action = next(layer for layer in card["layers"] if layer["type"] == "action_icon")
        assert action["asset"] == ""
        assert action["placeholder"] is True

    def test_normalize_is_idempotent(self):
        once = models.normalize_project({"name": "Cards", "pages": [{"grid": {"rows": 1, "columns": 5}}]})
        twice = models.normalize_project(once)

        # updated_at is preserved on re-normalize (only touch() advances it)
        assert once == twice

    def test_legacy_page_cards_migrate_to_global_library_and_page_ids(self):
        project = models.normalize_project({"pages": [
            {"cards": [{"id": "card-a", "name": "A"}]},
            {"cards": [{"id": "card-a", "name": "A"}, {"id": "card-b", "name": "B"}]},
        ]})
        assert [card["id"] for card in project["card_library"]] == ["card-a", "card-b"]
        assert project["pages"][0]["card_ids"] == ["card-a"]
        assert project["pages"][1]["card_ids"] == ["card-a", "card-b"]

    def test_global_library_is_materialized_into_page_cards_for_export_compatibility(self):
        project = models.normalize_project({
            "card_library": [{"id": "card-a", "name": "Globally edited"}],
            "pages": [{"card_ids": ["card-a"]}],
        })
        assert project["pages"][0]["cards"][0]["name"] == "Globally edited"

    def test_non_object_payload_is_rejected(self):
        with pytest.raises(ValidationError):
            models.normalize_project([1, 2, 3])

    def test_asserted_unsafe_id_is_rejected_not_silently_rewritten(self):
        with pytest.raises(ValidationError):
            models.normalize_project({"name": "x"}, project_id="../../etc/passwd")

    def test_unsafe_embedded_id_is_slugified_when_not_asserted_by_caller(self):
        project = models.normalize_project({"id": "../Weird Name", "name": "n"})

        assert project["id"] == "weird-name"


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------

class TestBounds:

    def test_canvas_dimensions_are_clamped(self):
        project = models.normalize_project({"canvas": {"width": 99999, "height": 0}})

        assert project["canvas"]["width"] == MAX_CANVAS
        assert project["canvas"]["height"] == 16

    def test_grid_rows_and_columns_are_clamped(self):
        project = models.normalize_project({"pages": [{"grid": {"rows": 999, "columns": 0}}]})
        grid = project["pages"][0]["grid"]

        assert grid["rows"] == MAX_ROWS
        assert grid["columns"] == 1
        assert grid["columns"] <= MAX_COLUMNS

    def test_one_by_five_grid_survives_normalization_exactly(self):
        project = models.normalize_project({
            "pages": [{"grid": {"rows": 1, "columns": 5, "gap_x": 20, "gap_y": 20, "padding": 24}}]
        })
        grid = project["pages"][0]["grid"]

        assert (grid["rows"], grid["columns"]) == (1, 5)
        assert grid["fit"] == "contain"
        assert grid["fill_order"] == "row"

    def test_string_numbers_from_a_form_are_coerced(self):
        project = models.normalize_project({
            "canvas": {"width": "1080", "height": "1920"},
            "pages": [{"grid": {"rows": "2", "columns": "3"}}],
        })

        assert project["canvas"]["width"] == 1080
        assert project["canvas"]["height"] == 1920
        assert project["pages"][0]["grid"]["rows"] == 2

    def test_garbage_values_fall_back_to_defaults_instead_of_raising(self):
        project = models.normalize_project({
            "canvas": {"width": "not-a-number", "height": None, "background": "javascript:alert(1)"},
            "playback": {"mode": "3d-explosion", "loop": "yes"},
        })

        assert project["canvas"]["width"] == 1920
        assert project["canvas"]["background"] == "transparent"
        assert project["playback"]["mode"] == "pages"
        assert project["playback"]["loop"] is True

    def test_page_and_layer_counts_are_capped(self):
        project = models.normalize_project({
            "pages": [{"name": f"p{i}"} for i in range(MAX_PAGES + 25)],
        })
        assert len(project["pages"]) == MAX_PAGES

        card = models.normalize_card({
            "layers": [{"type": "text", "text": str(i)} for i in range(MAX_LAYERS_PER_CARD + 10)]
        })
        assert len(card["layers"]) == MAX_LAYERS_PER_CARD

    def test_scroll_speed_is_stored_as_pixels_per_second_and_clamped(self):
        page = models.normalize_page({"scroll": {"enabled": True, "speed_px_per_second": 99999}})

        assert page["scroll"]["speed_px_per_second"] == 2000.0
        assert page["scroll"]["direction"] == "left"

    def test_hex_colors_accepted_and_normalized_lowercase(self):
        layer = models.normalize_layer({"type": "text", "color": "#FFAA00", "stroke_color": "#0008"})

        assert layer["color"] == "#ffaa00"
        assert layer["stroke_color"] == "#0008"


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------

class TestLayers:

    def test_every_layer_type_is_individually_constructible(self):
        for layer_type in ("gift_icon", "action_icon", "image", "text", "shape"):
            layer = models.normalize_layer({"type": layer_type})
            assert layer["type"] == layer_type
            assert layer["visible"] is True

    def test_gift_icon_auto_links_by_default_and_can_be_pinned(self):
        assert models.normalize_layer({"type": "gift_icon"})["auto_link"] is True
        assert models.normalize_layer({"type": "gift_icon", "auto_link": False})["auto_link"] is False

    def test_a_card_may_use_only_a_gift_icon_and_text(self):
        """Plan requirement: action icons are optional."""
        card = models.normalize_card({
            "layers": [{"type": "gift_icon"}, {"type": "text", "text": "5 Coins"}]
        })

        assert [layer["type"] for layer in card["layers"]] == ["gift_icon", "text"]
        assert not any(layer["type"] == "action_icon" for layer in card["layers"])

    def test_z_index_is_compacted_in_sorted_order(self):
        card = models.normalize_card({
            "layers": [
                {"type": "text", "text": "top", "z_index": 90},
                {"type": "shape", "z_index": 5},
                {"type": "gift_icon", "z_index": 40},
            ]
        })

        assert [layer["z_index"] for layer in card["layers"]] == [0, 1, 2]
        assert [layer["type"] for layer in card["layers"]] == ["shape", "gift_icon", "text"]

    def test_text_control_characters_are_stripped_but_newlines_kept(self):
        layer = models.normalize_layer({"type": "text", "text": "a\x00b\x1bc\nd"})

        assert layer["text"] == "abc\nd"

    def test_unknown_layer_type_degrades_to_text_rather_than_vanishing(self):
        assert models.normalize_layer({"type": "hologram"})["type"] == "text"

    def test_layer_ids_are_generated_when_missing_and_are_unique(self):
        card = models.normalize_card({"layers": [{"type": "text"}, {"type": "text"}]})
        ids = [layer["id"] for layer in card["layers"]]

        assert all(ids)
        assert len(set(ids)) == 2


# ---------------------------------------------------------------------------
# Cards / refs
# ---------------------------------------------------------------------------

class TestCards:

    def test_card_keeps_its_own_logical_size_independent_of_the_canvas(self):
        card = models.normalize_card({"width": 300, "height": 420})

        assert (card["width"], card["height"]) == (300, 420)

    def test_refs_drop_unknown_keys(self):
        card = models.normalize_card({
            "gift_ref": {"gift_id": "5487", "name": "finger heart", "evil": "<script>"},
            "action_ref": {"commands": ["spawnmob {mc} 5 vex {user}"], "nope": 1},
        })

        assert card["gift_ref"] == {"gift_id": "5487", "name": "finger heart"}
        assert "evil" not in card["gift_ref"]
        assert card["action_ref"] == {"commands": ["spawnmob {mc} 5 vex {user}"]}

    def test_customized_flag_defaults_false_and_round_trips(self):
        assert models.normalize_card({})["customized"] is False
        assert models.normalize_card({"customized": True})["customized"] is True


# ---------------------------------------------------------------------------
# Playback resolution
# ---------------------------------------------------------------------------

class TestPlaybackResolution:

    def test_page_duration_none_inherits_the_project_default(self):
        project = models.normalize_project({
            "playback": {"default_page_duration_ms": 4000},
            "pages": [{"duration_ms": None}, {"duration_ms": 9000}],
        })
        playback = project["playback"]

        assert models.page_duration_ms(project["pages"][0], playback) == 4000
        assert models.page_duration_ms(project["pages"][1], playback) == 9000

    def test_page_transition_none_inherits_the_project_default(self):
        project = models.normalize_project({
            "playback": {"default_transition": {"type": "fade", "duration_ms": 250}},
            "pages": [{"transition": None}, {"transition": {"type": "slide", "duration_ms": 300}}],
        })
        playback = project["playback"]

        assert models.page_transition(project["pages"][0], playback)["type"] == "fade"
        assert models.page_transition(project["pages"][1], playback)["type"] == "slide"

    def test_transition_is_clamped_to_half_the_shorter_adjacent_page(self):
        project = models.normalize_project({
            "playback": {"default_page_duration_ms": 5000},
            "pages": [
                {"duration_ms": 400},
                {"duration_ms": 5000, "transition": {"type": "pixel_wipe", "duration_ms": 4000}},
            ],
        })
        playback = project["playback"]

        # previous page is only 400ms, so the wipe may use at most 200ms
        assert models.effective_transition_ms(
            project["pages"][1], project["pages"][0], playback
        ) == 200

    def test_cut_transition_is_always_zero_length(self):
        project = models.normalize_project({
            "pages": [{"transition": {"type": "cut", "duration_ms": 900}}]
        })

        assert models.effective_transition_ms(
            project["pages"][0], None, project["playback"]
        ) == 0

    def test_project_duration_is_the_sum_of_page_durations(self):
        project = models.normalize_project({
            "playback": {"default_page_duration_ms": 3000},
            "pages": [{"duration_ms": None}, {"duration_ms": 1500}, {"duration_ms": None}],
        })

        assert models.project_duration_ms(project) == 7500


# ---------------------------------------------------------------------------
# Migration + summary
# ---------------------------------------------------------------------------

class TestMigrationAndSummary:

    def test_missing_schema_version_is_stamped_current(self):
        project = models.normalize_project({"name": "legacy"})

        assert project["schema_version"] == models.SCHEMA_VERSION

    def test_migration_seam_leaves_current_version_untouched(self):
        raw = {"schema_version": models.SCHEMA_VERSION, "name": "x"}

        assert models.migrate_project(raw) is raw

    def test_future_schema_version_is_not_downgraded_silently(self):
        raw = {"schema_version": models.SCHEMA_VERSION + 5, "name": "x"}

        assert models.migrate_project(raw)["schema_version"] == models.SCHEMA_VERSION + 5

    def test_summary_has_counts_and_no_card_bodies(self):
        project = models.normalize_project({
            "name": "Cards",
            "pages": [
                {"cards": [{"name": "a"}, {"name": "b"}]},
                {"cards": [{"name": "c"}]},
            ],
        })
        summary = models.summarize_project(project)

        assert summary["page_count"] == 2
        assert summary["card_count"] == 3
        assert "pages" not in summary

    def test_touch_advances_updated_at_format(self):
        project = models.normalize_project({})
        models.touch(project)

        assert project["updated_at"].endswith("Z")
        assert "T" in project["updated_at"]
