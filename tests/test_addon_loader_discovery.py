from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import addon_loader


def test_list_addons_ignores_directories_without_manifest(tmp_path, monkeypatch):
    addons = tmp_path / "addons"
    (addons / "__pycache__").mkdir(parents=True)
    (addons / "random-folder").mkdir()
    valid = addons / "valid"
    valid.mkdir()
    (valid / "addon.yml").write_text(
        "id: valid\nname: Valid Add-on\nversion: 1.0.0\n", encoding="utf-8"
    )
    monkeypatch.setattr(addon_loader, "_addons_dir", lambda: str(addons))

    found = addon_loader.list_addons()

    assert [addon["id"] for addon in found] == ["valid"]
