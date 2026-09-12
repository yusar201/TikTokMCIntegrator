"""Gift Card Studio — classifier: turn configured commands into draft content.

Fixtures are lifted verbatim from Khito's real config.yml Gifts block so the
classifier is tested against the commands it will actually see.
"""

import pytest

from gift_card_studio import classifier as clf


class TestCommandVerb:

    def test_verb_is_lowercased_and_slash_stripped(self):
        assert clf.command_verb("/SpawnMob {mc} 5 vex {user}") == "spawnmob"

    def test_blank_and_non_string_yield_empty(self):
        for value in ("", "   ", None, 42, []):
            assert clf.command_verb(value) == ""


class TestStripPlaceholders:

    def test_placeholders_are_removed_and_whitespace_collapsed(self):
        assert clf.strip_placeholders("{mc} {amount*5} Silverfish") == "Silverfish"

    def test_arithmetic_placeholders_do_not_leak_digits(self):
        assert clf.strip_placeholders("{amount*15} Charge Creeper") == "Charge Creeper"

    def test_placeholder_only_text_becomes_empty(self):
        assert clf.strip_placeholders("{user} {mc}") == ""


class TestTitleLabel:

    @pytest.mark.parametrize("command,expected", [
        ("titlecustom '{user}' {mc} {amount*5} Silverfish", "Silverfish"),
        ("titlecustom '{user}' {mc} Netherite Monstrosity", "Netherite Monstrosity"),
        ("titlecustom '{user}' {mc} {amount} Baby Husk", "Baby Husk"),
        ("titlecustom '{user}' {mc} Lava Pool", "Lava Pool"),
        ("titlecustom '{user}' {mc} {amount} TNT", "TNT"),
        ("titlecustom '{user}' {mc} Golem Army", "Golem Army"),
    ])
    def test_real_config_labels_are_extracted(self, command, expected):
        assert clf.title_label(command) == expected

    def test_quoted_username_is_not_mistaken_for_the_label(self):
        assert "user" not in clf.title_label("titlecustom '{user}' {mc} Warden").lower()

    def test_non_title_commands_have_no_label(self):
        assert clf.title_label("spawnmob {mc} {amount} wither {user}") == ""


class TestClassifyCommand:

    @pytest.mark.parametrize("command,intent", [
        ("spawnmob {mc} {amount} baby husk {user}", clf.INTENT_MOB),
        ("spawnsilverfish {mc} {amount*5} {user}", clf.INTENT_MOB),
        ("randommob {mc} {amount} {user}", clf.INTENT_MOB),
        ("tntspawn {mc} {amount} {user_q}", clf.INTENT_EXPLOSIVE),
        ("tntrain {mc} 10", clf.INTENT_EXPLOSIVE),
        ("lightningstrike {mc} {amount*5}", clf.INTENT_EXPLOSIVE),
        ("give {mc} diamond 1", clf.INTENT_ITEM),
        ("diamondpick {mc} {user}", clf.INTENT_ITEM),
        ("clearinven {mc}", clf.INTENT_ITEM),
        ("randompotions {mc} {user}", clf.INTENT_EFFECT),
        ("cobwebtrap {mc} {user}", clf.INTENT_WORLD),
        ("revealore {mc}", clf.INTENT_WORLD),
        ("rtp {mc} {user}", clf.INTENT_TELEPORT),
        ("setspawn {mc}", clf.INTENT_TELEPORT),
        ("score add 1", clf.INTENT_SCORE),
        ("helpwin {mc} {user}", clf.INTENT_SCORE),
        ("titlecustom '{user}' {mc} Warden", clf.INTENT_TITLE),
    ])
    def test_known_verbs_map_to_their_intent(self, command, intent):
        assert clf.classify_command(command)[0] == intent

    def test_execute_run_summon_is_recognized_as_a_mob(self):
        command = "execute at {mc} run summon cataclysm:ignis ~ ~ ~ {CustomName:'\"{user}\"'}"

        intent, confidence = clf.classify_command(command)

        assert intent == clf.INTENT_MOB
        assert confidence == clf.CONFIDENCE_NESTED

    def test_execute_run_fill_is_recognized_as_a_world_action(self):
        command = "execute at {mc} run fill ~10 ~3 ~10 ~-10 ~ ~-10 lava replace"

        assert clf.classify_command(command)[0] == clf.INTENT_WORLD

    def test_modded_tnt_summon_is_explosive_not_mob(self):
        """luckytntmod:nuclear_tnt is a bomb even though the verb is summon."""
        command = "execute at {mc} run summon luckytntmod:nuclear_tnt ~ ~ ~ {Fuse:20}"

        assert clf.classify_command(command)[0] == clf.INTENT_EXPLOSIVE

    def test_village_defense_summon_stays_a_mob(self):
        command = "execute at {mc} run summon luckytntmod:village_defense ~ ~ ~ {Fuse:0}"

        assert clf.classify_command(command)[0] == clf.INTENT_MOB

    def test_explosive_detection_reads_the_entity_path_not_the_mod_namespace(self):
        """`luckytntmod:` ships non-explosive entities; only the path decides."""
        assert clf._explosive_tokens_in("summon luckytntmod:nuclear_tnt") is True
        assert clf._explosive_tokens_in("summon luckytntmod:village_defense") is False
        assert clf._explosive_tokens_in("summon cataclysm:ignis") is False

    def test_vanilla_unnamespaced_tnt_is_still_explosive(self):
        assert clf._explosive_tokens_in("summon tnt ~ ~ ~") is True

    def test_unknown_verb_is_custom_with_low_confidence(self):
        intent, confidence = clf.classify_command("frobnicate {mc} 3")

        assert intent == clf.INTENT_CUSTOM
        assert confidence == clf.CONFIDENCE_UNKNOWN


class TestClassifyActions:
    """Whole-gift classification against real config entries."""

    def test_title_is_labelling_and_the_other_command_is_the_real_effect(self):
        result = clf.classify_actions([
            "spawnsilverfish {mc} {amount*5} {user}",
            "titlecustom '{user}' {mc} {amount*5} Silverfish",
        ])

        assert result["intent"] == clf.INTENT_MOB
        assert result["label"] == "Silverfish"
        assert result["effect_commands"] == ["spawnsilverfish {mc} {amount*5} {user}"]
        assert result["title_commands"] == ["titlecustom '{user}' {mc} {amount*5} Silverfish"]

    def test_a_reused_on_stream_label_raises_confidence_to_high(self):
        result = clf.classify_actions([
            "spawnmob {mc} {amount} wither {user}",
            "titlecustom '{user}' {mc} Wither",
        ])

        assert result["confidence"] == clf.CONFIDENCE_TITLE_LABEL
        assert clf.is_high_confidence(result) is True

    def test_no_label_stays_below_the_bulk_approve_threshold(self):
        result = clf.classify_actions(["rtp {mc} {user}"])

        assert result["intent"] == clf.INTENT_TELEPORT
        assert result["label"] == ""
        assert clf.is_high_confidence(result) is False

    def test_multi_command_world_action_picks_the_confident_intent(self):
        result = clf.classify_actions([
            "execute at {mc} run fill ~10 ~3 ~10 ~-10 ~ ~-10 air replace water",
            "execute at {mc} run fill ~10 ~3 ~10 ~-10 ~ ~-10 lava replace",
            "titlecustom '{user}' {mc} Lava Pool",
        ])

        assert result["intent"] == clf.INTENT_WORLD
        assert result["label"] == "Lava Pool"

    def test_a_title_only_gift_is_classified_as_a_title(self):
        result = clf.classify_actions(["titlecustom '{user}' {mc} Shoutout"])

        assert result["intent"] == clf.INTENT_TITLE
        assert result["label"] == "Shoutout"

    def test_empty_command_list_is_custom_and_never_raises(self):
        for value in ([], None, [""], ["   "]):
            result = clf.classify_actions(value)
            assert result["intent"] == clf.INTENT_CUSTOM
            assert result["label"] == ""

    def test_confidence_is_always_a_bounded_float(self):
        for commands in ([], ["spawnmob {mc} 1 pig {user}"], ["nonsense"]):
            confidence = clf.classify_actions(commands)["confidence"]
            assert 0.0 <= confidence <= 1.0


class TestSuggestions:

    def test_every_intent_has_an_icon_mapping(self):
        for intent in clf.INTENTS:
            assert intent in clf.INTENT_ICONS

    def test_custom_intent_suggests_no_action_icon(self):
        """Action icons are optional; an unknown intent must not invent one."""
        assert clf.suggest_action_icon(clf.INTENT_CUSTOM) == ""

    def test_unknown_intent_name_suggests_no_icon(self):
        assert clf.suggest_action_icon("nonsense") == ""

    def test_draft_text_prefers_the_on_stream_label_over_the_gift_name(self):
        classification = clf.classify_actions([
            "spawnmob {mc} {amount*5} vex {user}",
            "titlecustom '{user}' {mc} {amount*5} Vex",
        ])

        text = clf.draft_text("finger heart", classification, "5 Coins")

        assert text["main"] == "Vex"
        assert text["secondary"] == "5 Coins"

    def test_draft_text_falls_back_to_a_titlecased_gift_name(self):
        classification = clf.classify_actions(["rtp {mc} {user}"])

        text = clf.draft_text("paper crane", classification, "100 Coins")

        assert text["main"] == "Paper Crane"
        assert text["secondary"] == "100 Coins"

    def test_draft_text_never_repeats_the_category_as_secondary(self):
        classification = clf.classify_actions(["titlecustom '{user}' {mc} 100 Coins"])

        text = clf.draft_text("gift", classification, "100 Coins")

        assert text["secondary"] == ""

    def test_draft_text_handles_a_nameless_gift(self):
        text = clf.draft_text("", clf.classify_actions([]), "")

        assert text["main"] == "Gift"
