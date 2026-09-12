import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import addon_runtime_registry as registry
import addon_loader


class FakeRuntime:
    def __init__(self):
        self.enabled = None
        self.transitions = []
        self.configs = []

    def set_runtime_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.transitions.append(self.enabled)

    def set_runtime_config(self, config):
        self.configs.append(dict(config))


@pytest.fixture(autouse=True)
def clean_registry():
    registry.clear()
    yield
    registry.clear()


def test_register_applies_initial_state_once():
    runtime = FakeRuntime()
    assert registry.register("survival_rush", runtime, enabled=True) is runtime
    assert runtime.transitions == [True]
    assert registry.get("survival_rush") is runtime
    assert registry.is_enabled("survival_rush") is True


def test_register_same_runtime_is_idempotent():
    runtime = FakeRuntime()
    registry.register("survival_rush", runtime, enabled=True)
    registry.register("survival_rush", runtime, enabled=True)
    assert runtime.transitions == [True]


def test_register_replacement_stops_old_runtime():
    old = FakeRuntime()
    new = FakeRuntime()
    registry.register("survival_rush", old, enabled=True)
    registry.register("survival_rush", new, enabled=True)
    assert old.transitions == [True, False]
    assert new.transitions == [True]


def test_live_disable_and_enable_are_synchronous():
    runtime = FakeRuntime()
    registry.register("survival_rush", runtime, enabled=True)
    assert registry.set_enabled("survival_rush", False) is True
    assert runtime.enabled is False
    assert registry.is_enabled("survival_rush") is False
    assert registry.set_enabled("survival_rush", True) is True
    assert runtime.enabled is True
    assert runtime.transitions == [True, False, True]


def test_unrelated_addon_does_not_touch_survival_runtime():
    runtime = FakeRuntime()
    registry.register("survival_rush", runtime, enabled=True)
    assert registry.set_enabled("another_addon", False) is False
    assert runtime.transitions == [True]


def test_unregister_stops_runtime():
    runtime = FakeRuntime()
    registry.register("survival_rush", runtime, enabled=True)
    assert registry.unregister("survival_rush") is runtime
    assert runtime.transitions == [True, False]
    assert registry.get("survival_rush") is None


def test_addon_loader_toggle_applies_runtime_live(tmp_path, monkeypatch):
    addon_dir = tmp_path / "addons" / "survival_rush"
    addon_dir.mkdir(parents=True)
    (addon_dir / "addon.yml").write_text(
        "id: survival_rush\nname: Survival Rush\nenabled: true\n",
        encoding="utf-8",
    )
    state_file = tmp_path / "addons_state.json"
    monkeypatch.setattr(addon_loader.paths, "ADDONS_DIR", str(tmp_path / "addons"))
    monkeypatch.setattr(addon_loader, "STATE_FILE", str(state_file))

    runtime = FakeRuntime()
    registry.register("survival_rush", runtime, enabled=True)
    addon_loader.set_enabled("survival_rush", False)
    assert runtime.enabled is False
    assert addon_loader.load_addon("survival_rush")["enabled"] is False

    addon_loader.set_enabled("survival_rush", True)
    assert runtime.enabled is True
    assert addon_loader.load_addon("survival_rush")["enabled"] is True


def test_addon_loader_config_applies_runtime_live(tmp_path, monkeypatch):
    addon_dir = tmp_path / "addons" / "survival_rush"
    addon_dir.mkdir(parents=True)
    (addon_dir / "addon.yml").write_text(
        "id: survival_rush\nname: Survival Rush\nconfig_defaults:\n  helper_url: http://127.0.0.1:5943\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(addon_loader.paths, "ADDONS_DIR", str(tmp_path / "addons"))
    monkeypatch.setattr(addon_loader, "STATE_FILE", str(tmp_path / "addons_state.json"))

    runtime = FakeRuntime()
    registry.register("survival_rush", runtime, enabled=True)
    addon_loader.update_config("survival_rush", {
        "helper_url": "http://127.0.0.1:15943",
        "helper_secret": "disposable-secret",
    })

    assert runtime.configs[-1] == {
        "helper_url": "http://127.0.0.1:15943",
        "helper_secret": "disposable-secret",
    }
