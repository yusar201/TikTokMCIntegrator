"""Regression contract: modal Save must durably persist gift edits."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "static" / "script.js"


def test_gift_modal_save_persists_complete_config_after_updating_gift_state():
    script = SCRIPT.read_text(encoding="utf-8")
    save_modal = script[
        script.index("function saveGiftModal()") : script.index("function deleteGiftModal()")
    ]

    persistence = "return saveConfigData({ successMessage: 'Gift saved!' })"
    state_commit = "currentConfig.StreakDeltaGifts = [...streakDeltaSelected];"

    assert persistence in save_modal
    assert save_modal.index(state_commit) < save_modal.index(persistence)
    assert save_modal.index("populateGifts();") < save_modal.index(persistence)
    assert "showToast('Gift saved!', 'success');" not in save_modal


def test_config_save_supports_a_caller_specific_success_message():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "async function saveConfigData(options = {})" in script
    assert "options.successMessage || data.message || 'Configuration saved!'" in script
