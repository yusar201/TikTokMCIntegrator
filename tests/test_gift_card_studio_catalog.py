"""Gift Card Studio — catalog adapter: join, draft, and refresh-diff.

Fixtures mirror the real shapes found in Khito's config (2026-08-28):
numeric-id keys, legacy name keys, and the GlobalActions pseudo-key.
"""

import json
import os

import pytest

from gift_card_studio import catalog, models


@pytest.fixture
def sources(tmp_path):
    """A data_dir + assets_dir pair populated with realistic source files."""
    data_dir = tmp_path / "data"
    assets_dir = tmp_path / "assets"
    (assets_dir / "gift_assets").mkdir(parents=True)
    data_dir.mkdir()

    (data_dir / "available_gifts.json").write_text(json.dumps([
        {"id": 5487, "name": "finger heart", "diamond_count": 5,
         "icon": "https://cdn.tiktok/fingerheart.webp", "has_animation": False},
        {"id": 5599, "name": "gold necklace", "diamond_count": 200,
         "icon": "https://cdn.tiktok/gold.webp", "has_animation": True},
        {"id": 5655, "name": "rose", "diamond_count": 1,
         "icon": "https://cdn.tiktok/rose.webp", "has_animation": False},
        {"id": 7777, "name": "bff necklace", "diamond_count": 10,
         "icon": "https://cdn.tiktok/bff.webp", "has_animation": False},
    ]), encoding="utf-8")

    (assets_dir / "gift_assets" / "manifest.json").write_text(json.dumps({
        "5655": {"local_url": "/gift_assets/5655.png", "type": "png"},
    }), encoding="utf-8")

    return str(data_dir), str(assets_dir)


@pytest.fixture
def config():
    return {
        "Gifts": {
            "5487": [
                "spawnmob {mc} {amount*5} vex {user}",
                "titlecustom '{user}' {mc} {amount*5} Vex",
            ],
            "5599": [
                "spawnmob {mc} {amount} warden {user}",
                "titlecustom '{user}' {mc} Warden",
            ],
            "5655": [
                "tntspawn {mc} {amount} {user_q}",
                "titlecustom '{user}' {mc} {amount} TNT",
            ],
            # Legacy name-keyed row, as seen in the real config.
            "bff necklace": ["helpwin {mc} {user}"],
            # Pseudo-key: not a gift.
            "GlobalActions": ["score add 1"],
        },
        "GiftNames": {"5487": "finger heart", "5599": "gold necklace", "5655": "rose"},
        "GiftCategories": {
            "5487": "5 Coins", "5599": "200 Coins", "5655": "1 Coin",
            "bff necklace": "10 Coins",
        },
        "GiftDescriptions": {},
    }


class TestSourceLoading:

    def test_missing_sources_yield_empty_containers_not_errors(self, tmp_path):
        missing = str(tmp_path / "nope")

        assert catalog.load_available_gifts(missing) == []
        assert catalog.load_icon_manifest(missing) == {}

    def test_corrupt_sources_degrade_gracefully(self, tmp_path):
        (tmp_path / "available_gifts.json").write_text("{{{", encoding="utf-8")
        (tmp_path / "gift_assets").mkdir()
        (tmp_path / "gift_assets" / "manifest.json").write_text("nope", encoding="utf-8")

        assert catalog.load_available_gifts(str(tmp_path)) == []
        assert catalog.load_icon_manifest(str(tmp_path)) == {}

    def test_index_resolves_a_gift_by_both_id_and_name(self, sources):
        data_dir, _ = sources

        index = catalog.index_available_gifts(catalog.load_available_gifts(data_dir))

        assert index["5487"]["name"] == "finger heart"
        assert index["finger heart"]["id"] == 5487


class TestGiftKeys:

    def test_global_actions_is_not_a_gift(self):
        assert catalog.is_gift_key("GlobalActions") is False
        assert catalog.is_gift_key("globalactions") is False

    def test_normal_keys_are_gifts(self):
        assert catalog.is_gift_key("5487") is True
        assert catalog.is_gift_key("bff necklace") is True


class TestBuildCatalog:

    def test_global_actions_never_becomes_an_entry(self, config, sources):
        entries = catalog.build_catalog(config, *sources)

        assert all(entry["key"] != "GlobalActions" for entry in entries)
        assert len(entries) == 4

    def test_entries_are_sorted_by_coin_value(self, config, sources):
        entries = catalog.build_catalog(config, *sources)

        assert [e["diamond_count"] for e in entries] == sorted(e["diamond_count"] for e in entries)

    def test_numeric_key_joins_catalog_metadata(self, config, sources):
        entries = {e["key"]: e for e in catalog.build_catalog(config, *sources)}

        vex = entries["5487"]
        assert vex["gift_id"] == "5487"
        assert vex["name"] == "finger heart"
        assert vex["diamond_count"] == 5
        assert vex["in_tiktok_catalog"] is True

    def test_legacy_name_key_still_resolves_its_catalog_entry(self, config, sources):
        entries = {e["key"]: e for e in catalog.build_catalog(config, *sources)}

        bff = entries["bff necklace"]
        assert bff["gift_id"] == "7777"
        assert bff["diamond_count"] == 10
        assert bff["in_tiktok_catalog"] is True

    def test_locally_cached_icon_wins_over_the_remote_cdn_url(self, config, sources):
        entries = {e["key"]: e for e in catalog.build_catalog(config, *sources)}

        rose = entries["5655"]
        assert rose["icon"] == "/gift_assets/5655.png"
        assert rose["icon_local"] == "/gift_assets/5655.png"
        assert rose["icon_remote"] == "https://cdn.tiktok/rose.webp"
        assert rose["icon_missing"] is False

    def test_remote_url_is_used_when_nothing_is_cached(self, config, sources):
        entries = {e["key"]: e for e in catalog.build_catalog(config, *sources)}

        assert entries["5487"]["icon"] == "https://cdn.tiktok/fingerheart.webp"
        assert entries["5487"]["icon_local"] == ""

    def test_cached_live_overlay_mp4_never_replaces_the_static_gift_icon(
        self, config, sources
    ):
        """resvg cannot draw mp4; preferring it made the gift badge blank."""
        data_dir, assets_dir = sources
        manifest = os.path.join(assets_dir, "gift_assets", "manifest.json")
        with open(manifest, "w", encoding="utf-8") as handle:
            json.dump({
                "5655": {
                    "local_url": "/gift_assets/gift_5655.mp4?v=1",
                    "type": "mp4",
                }
            }, handle)

        rose = {e["key"]: e for e in catalog.build_catalog(config, data_dir, assets_dir)}["5655"]

        assert rose["icon"] == "https://cdn.tiktok/rose.webp"
        assert rose["icon_local"] == ""
        assert rose["icon_local_unusable"] == "/gift_assets/gift_5655.mp4?v=1"

    def test_static_gif_cache_is_still_accepted(self, config, sources):
        data_dir, assets_dir = sources
        manifest = os.path.join(assets_dir, "gift_assets", "manifest.json")
        with open(manifest, "w", encoding="utf-8") as handle:
            json.dump({"5655": {"local_url": "/gift_assets/gift_5655.gif"}}, handle)

        rose = {e["key"]: e for e in catalog.build_catalog(config, data_dir, assets_dir)}["5655"]

        assert rose["icon"] == "/gift_assets/gift_5655.gif"
        assert rose["icon_local_unusable"] == ""

    def test_a_gift_absent_from_the_tiktok_catalog_is_flagged_not_dropped(self, sources):
        config = {"Gifts": {"9999": ["spawnmob {mc} 1 pig {user}"]}, "GiftNames": {}}

        entries = catalog.build_catalog(config, *sources)

        assert len(entries) == 1
        assert entries[0]["in_tiktok_catalog"] is False
        assert entries[0]["icon_missing"] is True

    def test_typed_action_objects_feed_action_text_and_icon_detection(self, config, sources):
        config["Gifts"]["5487"] = [
            {"command": "give {mc} minecraft:golden_apple {amount}", "type": "minecraft"},
            {"command": "titlecustom '{user}' {mc} {amount} Golden Apple", "type": "minecraft"},
            {"type": "sound", "path": "ding.mp3"},
        ]

        entry = {e["key"]: e for e in catalog.build_catalog(config, *sources)}["5487"]
        card = catalog.draft_card(entry)

        assert entry["commands"] == [
            "give {mc} minecraft:golden_apple {amount}",
            "titlecustom '{user}' {mc} {amount} Golden Apple",
        ]
        assert entry["label"] == "Golden Apple"
        assert entry["intent"] == "item"
        assert next(layer for layer in card["layers"] if layer.get("role") == "main")["text"] == ""

    def test_classification_and_draft_text_are_attached(self, config, sources):
        entries = {e["key"]: e for e in catalog.build_catalog(config, *sources)}

        vex = entries["5487"]
        assert vex["intent"] == "mob"
        assert vex["label"] == "Vex"
        assert vex["suggested_text"] == {"main": "", "secondary": ""}
        assert vex["high_confidence"] is True
        assert vex["suggested_action_icon"] == "mob"

    def test_visible_action_text_comes_only_from_gift_description(self, config, sources):
        config["GiftDescriptions"]["5487"] = "Spawn Vex"
        entry = {e["key"]: e for e in catalog.build_catalog(config, *sources)}["5487"]
        card = catalog.draft_card(entry)
        main = next(layer for layer in card["layers"] if layer.get("role") == "main")
        assert entry["suggested_text"]["main"] == "Spawn Vex"
        assert main["text"] == "Spawn Vex"

    def test_missing_description_does_not_fall_back_to_command_or_gift_name(self, config, sources):
        entry = {e["key"]: e for e in catalog.build_catalog(config, *sources)}["5487"]
        card = catalog.draft_card(entry)
        main = next(layer for layer in card["layers"] if layer.get("role") == "main")
        assert entry["label"] == "Vex"
        assert entry["suggested_text"]["main"] == ""
        assert main["text"] == ""

    def test_tntspawn_gift_is_classified_explosive(self, config, sources):
        entries = {e["key"]: e for e in catalog.build_catalog(config, *sources)}

        assert entries["5655"]["intent"] == "explosive"

    def test_build_catalog_does_not_mutate_the_config(self, config, sources):
        before = json.dumps(config, sort_keys=True)

        catalog.build_catalog(config, *sources)

        assert json.dumps(config, sort_keys=True) == before

    def test_empty_config_yields_an_empty_catalog(self, sources):
        assert catalog.build_catalog({}, *sources) == []
        assert catalog.build_catalog({"Gifts": {}}, *sources) == []


class TestCatalogStats:

    def test_stats_summarize_the_review_workload(self, config, sources):
        entries = catalog.build_catalog(config, *sources)

        stats = catalog.catalog_stats(entries)

        assert stats["total"] == 4
        assert stats["high_confidence"] + stats["needs_review"] == 4
        assert "mob" in stats["intents"]

    def test_stats_on_an_empty_catalog_are_zeroed(self):
        stats = catalog.catalog_stats([])

        assert stats["total"] == 0
        assert stats["needs_review"] == 0


class TestDraftCard:

    def _entry(self, config, sources, key):
        return {e["key"]: e for e in catalog.build_catalog(config, *sources)}[key]

    def test_draft_card_is_a_valid_normalized_card(self, config, sources):
        card = catalog.draft_card(self._entry(config, sources, "5487"))

        assert card == models.normalize_card(card)
        assert card["width"] == 320
        assert card["height"] == 320

    def test_draft_card_links_the_gift_and_its_actions(self, config, sources):
        card = catalog.draft_card(self._entry(config, sources, "5487"))

        assert card["gift_ref"]["gift_id"] == "5487"
        assert card["gift_ref"]["name"] == "finger heart"
        assert card["action_ref"]["gift_key"] == "5487"
        assert card["action_ref"]["intent"] == "mob"
        assert card["action_ref"]["commands"][0].startswith("spawnmob")

    def test_draft_card_does_not_use_command_label_as_main_text(self, config, sources):
        card = catalog.draft_card(self._entry(config, sources, "5487"))

        main = next(l for l in card["layers"] if l.get("role") == "main")
        assert main["text"] == ""

    def test_draft_card_starts_uncustomized(self, config, sources):
        assert catalog.draft_card(self._entry(config, sources, "5487"))["customized"] is False

    def test_action_icon_remains_as_manual_placeholder_on_new_cards(self, config, sources):
        entry = self._entry(config, sources, "5487")
        card = catalog.draft_card(entry)
        action = next(l for l in card["layers"] if l["type"] == "action_icon")
        assert action["asset"] == ""
        assert action["placeholder"] is True
        assert any(l["type"] == "gift_icon" for l in card["layers"])
        assert any(l["type"] == "text" for l in card["layers"])

    def test_automatic_action_asset_is_not_applied_to_manual_icon(self, config, sources):
        entry = self._entry(config, sources, "5487")
        entry["action_asset_url"] = "/gift-studio-assets/mc-minecraft-item-golden-apple-a1.png"
        entry["action_match"] = {"status": "matched", "confidence": "exact"}

        card = catalog.draft_card(entry)
        action = next(layer for layer in card["layers"] if layer["type"] == "action_icon")

        assert action["asset"] == ""
        assert action["placeholder"] is True

    def test_unknown_intent_gets_replaceable_action_icon_placeholder(self, sources):
        config = {"Gifts": {"1": ["frobnicate {mc}"]}, "GiftNames": {"1": "mystery"}}
        entry = catalog.build_catalog(config, *sources)[0]

        card = catalog.draft_card(entry)

        assert entry["intent"] == "custom"
        layer = next(l for l in card["layers"] if l["type"] == "action_icon")
        assert layer["asset"] == ""
        assert layer["placeholder"] is True

    def test_secondary_text_is_skipped_when_it_would_be_empty(self, sources):
        config = {"Gifts": {"1": ["titlecustom '{user}' {mc} Boom"]}, "GiftCategories": {}}
        entry = catalog.build_catalog(config, *sources)[0]

        card = catalog.draft_card(entry)

        assert not any(l.get("role") == "secondary" for l in card["layers"])

    def test_layers_stay_inside_the_card_box(self, config, sources):
        card = catalog.draft_card(self._entry(config, sources, "5599"))

        for layer in card["layers"]:
            assert layer["x"] >= 0
            assert layer["y"] >= 0
            assert layer["x"] + layer["width"] <= card["width"] + 1e-9

    def test_custom_card_size_scales_the_layout(self, config, sources):
        card = catalog.draft_card(self._entry(config, sources, "5487"), card_width=640, card_height=800)

        assert card["width"] == 640
        panel = next(l for l in card["layers"] if l["type"] == "shape")
        assert panel["width"] == 640
        assert panel["height"] == 800

    def test_draft_cards_preserves_catalog_order(self, config, sources):
        entries = catalog.build_catalog(config, *sources)

        cards = catalog.draft_cards(entries)

        assert [c["action_ref"]["gift_key"] for c in cards] == [e["key"] for e in entries]

    def test_draft_cards_on_an_empty_catalog_returns_empty(self):
        assert catalog.draft_cards([]) == []
        assert catalog.draft_cards(None) == []


class TestDiffCatalog:

    def _project_with(self, entries, keys=None):
        project = models.new_project("Diff Test")
        chosen = entries if keys is None else [e for e in entries if e["key"] in keys]
        project["pages"][0]["cards"] = catalog.draft_cards(chosen)
        return models.normalize_project(project)

    def test_an_empty_project_reports_every_gift_as_new(self, config, sources):
        entries = catalog.build_catalog(config, *sources)

        diff = catalog.diff_catalog(models.new_project("Empty"), entries)

        assert diff["counts"]["new"] == 4
        assert diff["counts"]["unchanged"] == 0

    def test_a_freshly_drafted_project_reports_everything_unchanged(self, config, sources):
        entries = catalog.build_catalog(config, *sources)
        project = self._project_with(entries)

        diff = catalog.diff_catalog(project, entries)

        assert diff["counts"] == {"new": 0, "changed": 0, "unchanged": 4, "missing": 0}

    def test_a_gift_added_to_the_config_shows_up_as_new(self, config, sources):
        entries = catalog.build_catalog(config, *sources)
        project = self._project_with(entries, keys={"5487", "5599"})

        diff = catalog.diff_catalog(project, entries)

        assert diff["counts"]["new"] == 2
        assert {item["key"] for item in diff["new"]} == {"5655", "bff necklace"}

    def test_changed_commands_are_detected(self, config, sources):
        entries = catalog.build_catalog(config, *sources)
        project = self._project_with(entries)
        config["Gifts"]["5487"] = [
            "spawnmob {mc} {amount*10} vex {user}",
            "titlecustom '{user}' {mc} {amount*10} Vex",
        ]

        diff = catalog.diff_catalog(project, catalog.build_catalog(config, *sources))

        assert diff["counts"]["changed"] == 1
        changed = diff["changed"][0]
        assert changed["key"] == "5487"
        assert changed["commands_changed"] is True

    def test_a_changed_intent_is_detected_even_when_commands_match_count(self, config, sources):
        entries = catalog.build_catalog(config, *sources)
        project = self._project_with(entries)
        # mob -> item
        config["Gifts"]["5487"] = [
            "give {mc} diamond 5",
            "titlecustom '{user}' {mc} {amount*5} Vex",
        ]

        diff = catalog.diff_catalog(project, catalog.build_catalog(config, *sources))

        changed = next(i for i in diff["changed"] if i["key"] == "5487")
        assert changed["intent_changed"] is True

    def test_a_gift_removed_from_the_config_is_reported_missing(self, config, sources):
        entries = catalog.build_catalog(config, *sources)
        project = self._project_with(entries)
        del config["Gifts"]["5599"]

        diff = catalog.diff_catalog(project, catalog.build_catalog(config, *sources))

        assert diff["counts"]["missing"] == 1
        assert diff["missing"][0]["key"] == "5599"

    def test_customized_cards_are_flagged_protected(self, config, sources):
        entries = catalog.build_catalog(config, *sources)
        project = self._project_with(entries)
        project["pages"][0]["cards"][0]["customized"] = True
        target_key = project["pages"][0]["cards"][0]["action_ref"]["gift_key"]
        config["Gifts"][target_key] = ["give {mc} dirt 1"]

        diff = catalog.diff_catalog(project, catalog.build_catalog(config, *sources))

        changed = next(i for i in diff["changed"] if i["key"] == target_key)
        assert changed["protected"] is True


class TestApplyCatalogImport:

    def test_import_into_an_empty_project_adds_every_card(self, config, sources):
        entries = catalog.build_catalog(config, *sources)

        report = catalog.apply_catalog_import(models.new_project("Fresh"), entries)

        assert len(report["added"]) == 4
        assert len(report["project"]["pages"][0]["cards"]) == 4

    def test_reimporting_is_a_no_op(self, config, sources):
        entries = catalog.build_catalog(config, *sources)
        first = catalog.apply_catalog_import(models.new_project("Twice"), entries)

        second = catalog.apply_catalog_import(first["project"], entries)

        assert second["added"] == []
        assert second["refreshed"] == []
        assert len(second["project"]["pages"][0]["cards"]) == 4

    def test_a_customized_card_is_never_overwritten(self, config, sources):
        """Acceptance criterion 10: manual customizations survive refresh."""
        entries = catalog.build_catalog(config, *sources)
        report = catalog.apply_catalog_import(models.new_project("Protected"), entries)
        project = report["project"]

        card = next(
            c for c in project["pages"][0]["cards"]
            if c["action_ref"]["gift_key"] == "5487"
        )
        card["customized"] = True
        main = next(l for l in card["layers"] if l.get("role") == "main")
        main["text"] = "MY OWN LABEL"
        config["Gifts"]["5487"] = ["give {mc} dirt 1"]

        refreshed = catalog.apply_catalog_import(
            project, catalog.build_catalog(config, *sources)
        )

        assert "5487" in refreshed["skipped_customized"]
        survivor = next(
            c for c in refreshed["project"]["pages"][0]["cards"]
            if c["action_ref"]["gift_key"] == "5487"
        )
        kept = next(l for l in survivor["layers"] if l.get("role") == "main")
        assert kept["text"] == "MY OWN LABEL"
        assert survivor["customized"] is True

    def test_an_untouched_changed_card_is_refreshed_in_place(self, config, sources):
        entries = catalog.build_catalog(config, *sources)
        report = catalog.apply_catalog_import(models.new_project("Refresh"), entries)
        project = report["project"]
        original_id = next(
            c["id"] for c in project["pages"][0]["cards"]
            if c["action_ref"]["gift_key"] == "5487"
        )
        config["Gifts"]["5487"] = [
            "give {mc} diamond 5",
            "titlecustom '{user}' {mc} Diamonds",
        ]
        config["GiftDescriptions"]["5487"] = "Diamonds"

        refreshed = catalog.apply_catalog_import(
            project, catalog.build_catalog(config, *sources)
        )

        assert refreshed["refreshed"] == ["5487"]
        card = next(
            c for c in refreshed["project"]["pages"][0]["cards"]
            if c["action_ref"]["gift_key"] == "5487"
        )
        assert card["id"] == original_id  # identity preserved
        assert card["action_ref"]["intent"] == "item"
        main = next(l for l in card["layers"] if l.get("role") == "main")
        assert main["text"] == "Diamonds"

    def test_importing_a_subset_only_adds_the_selected_keys(self, config, sources):
        entries = catalog.build_catalog(config, *sources)

        report = catalog.apply_catalog_import(
            models.new_project("Subset"), entries, keys=["5487", "5655"]
        )

        assert sorted(report["added"]) == ["5487", "5655"]
        assert len(report["project"]["pages"][0]["cards"]) == 2

    def test_refresh_can_be_disabled(self, config, sources):
        entries = catalog.build_catalog(config, *sources)
        project = catalog.apply_catalog_import(models.new_project("NoRefresh"), entries)["project"]
        config["Gifts"]["5487"] = ["give {mc} dirt 1"]

        report = catalog.apply_catalog_import(
            project, catalog.build_catalog(config, *sources), refresh_changed=False
        )

        assert report["refreshed"] == []

    def test_new_cards_append_to_the_last_page_and_never_repaginate(self, config, sources):
        """Plan rule: overflow is explicit; import must not move existing cards."""
        entries = catalog.build_catalog(config, *sources)
        project = models.new_project("Paged")
        project["pages"].append(models.default_page(1))
        project = models.normalize_project(project)

        report = catalog.apply_catalog_import(project, entries)

        assert len(report["project"]["pages"]) == 2
        assert report["project"]["pages"][0]["cards"] == []
        assert len(report["project"]["pages"][1]["cards"]) == 4

    def test_the_result_is_always_a_valid_normalized_project(self, config, sources):
        entries = catalog.build_catalog(config, *sources)

        report = catalog.apply_catalog_import(models.new_project("Valid"), entries)

        assert report["project"] == models.normalize_project(report["project"])

    def test_import_reports_diff_counts_for_the_ui(self, config, sources):
        entries = catalog.build_catalog(config, *sources)

        report = catalog.apply_catalog_import(models.new_project("Counts"), entries)

        assert report["diff_counts"]["new"] == 4
        assert set(report["diff_counts"]) == {"new", "changed", "unchanged", "missing"}
