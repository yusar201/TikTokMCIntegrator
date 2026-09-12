"""Gift Card Studio — HTTP API contract and security.

Each test builds an isolated Flask app over a tmp data dir, so nothing here
touches the real data/ tree or the dashboard app object.
"""

import io
import json
from pathlib import Path

import pytest
from flask import Flask
from PIL import Image

from gift_card_studio import assets, storage
from routes.gift_card_studio import (
    create_gift_studio_assets_blueprint,
    create_gift_studio_blueprint,
)


CONFIG = {
    "Gifts": {
        "5487": [
            "spawnmob {mc} {amount*5} vex {user}",
            "titlecustom '{user}' {mc} {amount*5} Vex",
        ],
        "5655": [
            "tntspawn {mc} {amount} {user_q}",
            "titlecustom '{user}' {mc} {amount} TNT",
        ],
        "GlobalActions": ["score add 1"],
    },
    "GiftNames": {"5487": "finger heart", "5655": "rose"},
    "GiftCategories": {"5487": "5 Coins", "5655": "1 Coin"},
}


@pytest.fixture
def env(tmp_path):
    data_dir = tmp_path / "data"
    assets_dir = tmp_path / "assets"
    data_dir.mkdir()
    (assets_dir / "gift_assets").mkdir(parents=True)
    (data_dir / "available_gifts.json").write_text(json.dumps([
        {"id": 5487, "name": "finger heart", "diamond_count": 5, "icon": "https://cdn/fh.webp"},
        {"id": 5655, "name": "rose", "diamond_count": 1, "icon": "https://cdn/rose.webp"},
    ]), encoding="utf-8")

    config = json.loads(json.dumps(CONFIG))
    app = Flask(__name__)
    app.register_blueprint(
        create_gift_studio_blueprint(str(data_dir), str(assets_dir), lambda: config),
        url_prefix="/api/gift-studio",
    )
    app.register_blueprint(create_gift_studio_assets_blueprint(str(data_dir)))
    return app.test_client(), str(data_dir), config


def png_bytes(size=(8, 8), color=(255, 0, 0, 255)):
    buffer = io.BytesIO()
    Image.new("RGBA", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class TestRemovedAutomaticActionArtwork:
    def test_minecraft_asset_endpoints_are_gone(self, env):
        client, _, _ = env
        for path in (
            "/api/gift-studio/minecraft-assets/status",
            "/api/gift-studio/minecraft-assets/detect",
            "/api/gift-studio/minecraft-assets/source",
            "/api/gift-studio/minecraft-assets/browse",
            "/api/gift-studio/minecraft-assets/rescan",
            "/api/gift-studio/minecraft-assets/resolve",
        ):
            assert client.get(path).status_code == 404


class TestProjectCrud:

    def test_listing_is_empty_before_anything_is_created(self, env):
        client, _, _ = env

        response = client.get("/api/gift-studio/projects")

        assert response.status_code == 200
        assert response.get_json() == {"projects": []}

    def test_create_returns_201_and_a_normalized_project(self, env):
        client, _, _ = env

        response = client.post("/api/gift-studio/projects", json={"name": "My Cards"})

        assert response.status_code == 201
        project = response.get_json()["project"]
        assert project["id"] == "my-cards"
        assert project["name"] == "My Cards"
        assert len(project["pages"]) == 1

    def test_create_without_a_name_still_works(self, env):
        client, _, _ = env

        response = client.post("/api/gift-studio/projects", json={})

        assert response.status_code == 201
        assert response.get_json()["project"]["id"] == "untitled-project"

    def test_get_returns_the_saved_project(self, env):
        client, _, _ = env
        client.post("/api/gift-studio/projects", json={"name": "Fetch Me"})

        response = client.get("/api/gift-studio/projects/fetch-me")

        assert response.status_code == 200
        assert response.get_json()["project"]["name"] == "Fetch Me"

    def test_get_missing_project_is_404(self, env):
        client, _, _ = env

        assert client.get("/api/gift-studio/projects/nope").status_code == 404

    def test_put_saves_and_normalizes(self, env):
        client, _, _ = env
        client.post("/api/gift-studio/projects", json={"name": "Editable"})

        response = client.put("/api/gift-studio/projects/editable", json={
            "name": "Edited",
            "canvas": {"width": "1080", "height": 1920},
            "pages": [{"grid": {"rows": 1, "columns": 5}}],
        })

        assert response.status_code == 200
        project = response.get_json()["project"]
        assert project["name"] == "Edited"
        assert project["canvas"]["width"] == 1080
        assert project["pages"][0]["grid"]["columns"] == 5

    def test_put_accepts_a_project_wrapped_payload(self, env):
        client, _, _ = env
        client.post("/api/gift-studio/projects", json={"name": "Wrapped"})

        response = client.put(
            "/api/gift-studio/projects/wrapped",
            json={"project": {"name": "Unwrapped Fine"}},
        )

        assert response.status_code == 200
        assert response.get_json()["project"]["name"] == "Unwrapped Fine"

    def test_put_url_id_wins_over_a_body_id(self, env):
        """A client must not be able to relocate a project by lying in the body."""
        client, data_dir, _ = env
        client.post("/api/gift-studio/projects", json={"name": "Anchored"})

        response = client.put(
            "/api/gift-studio/projects/anchored",
            json={"id": "somewhere-else", "name": "Anchored"},
        )

        assert response.status_code == 200
        assert response.get_json()["project"]["id"] == "anchored"
        assert storage.list_project_ids(data_dir) == ["anchored"]

    def test_put_rejects_a_non_object_body(self, env):
        client, _, _ = env
        client.post("/api/gift-studio/projects", json={"name": "Strict"})

        response = client.put("/api/gift-studio/projects/strict", json=[1, 2, 3])

        assert response.status_code == 400

    def test_delete_removes_then_404s(self, env):
        client, _, _ = env
        client.post("/api/gift-studio/projects", json={"name": "Temp"})

        assert client.delete("/api/gift-studio/projects/temp").status_code == 200
        assert client.delete("/api/gift-studio/projects/temp").status_code == 404

    def test_round_trip_survives_a_save_and_reload(self, env):
        client, _, _ = env
        client.post("/api/gift-studio/projects", json={"name": "Durable"})
        client.put("/api/gift-studio/projects/durable", json={
            "name": "Durable",
            "pages": [{"cards": [{"name": "one", "layers": [{"type": "text", "text": "hi"}]}]}],
        })

        project = client.get("/api/gift-studio/projects/durable").get_json()["project"]

        assert project["pages"][0]["cards"][0]["layers"][0]["text"] == "hi"


class TestPathTraversalDefense:

    @pytest.mark.parametrize("evil", ["..", "%2e%2e", "UPPER", "with%20space"])
    def test_unsafe_ids_never_reach_the_filesystem(self, env, evil):
        client, _, _ = env

        for method in (client.get, client.delete):
            response = method(f"/api/gift-studio/projects/{evil}")
            assert response.status_code in (400, 404), (evil, response.status_code)

    def test_traversal_attempt_does_not_write_outside_the_projects_dir(self, env, tmp_path):
        client, data_dir, _ = env

        client.put("/api/gift-studio/projects/..%2f..%2fescaped", json={"name": "x"})

        assert not (tmp_path / "escaped.json").exists()
        assert storage.list_project_ids(data_dir) == []


class TestCatalogEndpoints:

    def test_catalog_returns_entries_and_stats(self, env):
        client, _, _ = env

        response = client.get("/api/gift-studio/catalog")

        assert response.status_code == 200
        body = response.get_json()
        assert len(body["entries"]) == 2
        assert body["stats"]["total"] == 2

    def test_global_actions_is_excluded_from_the_catalog(self, env):
        client, _, _ = env

        entries = client.get("/api/gift-studio/catalog").get_json()["entries"]

        assert all(e["key"] != "GlobalActions" for e in entries)

    def test_catalog_reflects_live_config_changes_without_a_restart(self, env):
        """Project invariant: settings must apply live, not at startup."""
        client, _, config = env
        assert len(client.get("/api/gift-studio/catalog").get_json()["entries"]) == 2

        config["Gifts"]["9001"] = ["give {mc} diamond 1"]

        assert len(client.get("/api/gift-studio/catalog").get_json()["entries"]) == 3

    def test_preview_on_a_fresh_project_reports_everything_new(self, env):
        client, _, _ = env
        client.post("/api/gift-studio/projects", json={"name": "Preview Target"})

        response = client.post(
            "/api/gift-studio/catalog/preview", json={"project_id": "preview-target"}
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["counts"]["new"] == 2
        assert sorted(body["new"]) == ["5487", "5655"]

    def test_preview_writes_nothing(self, env):
        client, _, _ = env
        client.post("/api/gift-studio/projects", json={"name": "Untouched"})

        client.post("/api/gift-studio/catalog/preview", json={"project_id": "untouched"})

        project = client.get("/api/gift-studio/projects/untouched").get_json()["project"]
        assert project["pages"][0]["cards"] == []

    def test_preview_without_a_project_id_uses_an_empty_baseline(self, env):
        client, _, _ = env

        response = client.post("/api/gift-studio/catalog/preview", json={})

        assert response.status_code == 200
        assert response.get_json()["counts"]["new"] == 2

    def test_preview_for_a_missing_project_is_404(self, env):
        client, _, _ = env

        response = client.post(
            "/api/gift-studio/catalog/preview", json={"project_id": "ghost"}
        )

        assert response.status_code == 404

    def test_import_adds_cards_and_persists_them(self, env):
        client, _, _ = env
        client.post("/api/gift-studio/projects", json={"name": "Import Target"})

        response = client.post(
            "/api/gift-studio/catalog/import", json={"project_id": "import-target"}
        )

        assert response.status_code == 200
        body = response.get_json()
        assert sorted(body["added"]) == ["5487", "5655"]

        reloaded = client.get("/api/gift-studio/projects/import-target").get_json()["project"]
        assert len(reloaded["pages"][0]["cards"]) == 2

    def test_import_caches_static_icons_before_drafting_cards(self, env, monkeypatch):
        client, _, _ = env
        client.post("/api/gift-studio/projects", json={"name": "Icon Cache"})
        calls = []

        def fake_cache(entries, data_dir, timeout=assets.ICON_DOWNLOAD_TIMEOUT):
            calls.extend(entry["key"] for entry in entries)
            for entry in entries:
                entry["icon"] = f"/gift-studio-assets/gift-icon-{entry['gift_id']}.png"
                entry["icon_local"] = entry["icon"]
                entry["icon_missing"] = False
            return {"cached": calls[:], "failed": [], "cached_count": len(calls), "failed_count": 0}

        monkeypatch.setattr(assets, "cache_catalog_icons", fake_cache)

        response = client.post(
            "/api/gift-studio/catalog/import", json={"project_id": "icon-cache"}
        )

        assert response.status_code == 200
        assert sorted(calls) == ["5487", "5655"]
        cards = response.get_json()["project"]["pages"][0]["cards"]
        assert all(
            card["gift_ref"]["icon"].startswith("/gift-studio-assets/gift-icon-")
            for card in cards
        )
        assert response.get_json()["icon_cache"]["cached_count"] == 2

    def test_subset_import_only_caches_selected_icons(self, env, monkeypatch):
        client, _, _ = env
        client.post("/api/gift-studio/projects", json={"name": "One Icon"})
        cached = []

        def fake_cache(entries, data_dir, timeout=assets.ICON_DOWNLOAD_TIMEOUT):
            cached.extend(entry["key"] for entry in entries)
            return {"cached": cached[:], "failed": [], "cached_count": len(cached), "failed_count": 0}

        monkeypatch.setattr(assets, "cache_catalog_icons", fake_cache)

        client.post("/api/gift-studio/catalog/import", json={
            "project_id": "one-icon", "keys": ["5487"],
        })

        assert cached == ["5487"]

    def test_import_requires_a_project_id(self, env):
        client, _, _ = env

        assert client.post("/api/gift-studio/catalog/import", json={}).status_code == 400

    def test_import_of_a_subset_only_adds_the_selected_keys(self, env):
        client, _, _ = env
        client.post("/api/gift-studio/projects", json={"name": "Subset"})

        response = client.post("/api/gift-studio/catalog/import", json={
            "project_id": "subset", "keys": ["5487"],
        })

        assert response.get_json()["added"] == ["5487"]

    def test_import_rejects_a_non_list_keys_value(self, env):
        client, _, _ = env
        client.post("/api/gift-studio/projects", json={"name": "Bad Keys"})

        response = client.post("/api/gift-studio/catalog/import", json={
            "project_id": "bad-keys", "keys": "5487",
        })

        assert response.status_code == 400

    def test_import_can_omit_action_icons(self, env):
        client, _, _ = env
        client.post("/api/gift-studio/projects", json={"name": "No Icons"})

        client.post("/api/gift-studio/catalog/import", json={
            "project_id": "no-icons", "include_action_icon": False,
        })

        project = client.get("/api/gift-studio/projects/no-icons").get_json()["project"]
        layers = [l for card in project["pages"][0]["cards"] for l in card["layers"]]
        assert not any(l["type"] == "action_icon" for l in layers)
        assert any(l["type"] == "gift_icon" for l in layers)

    def test_reimport_is_idempotent(self, env):
        client, _, _ = env
        client.post("/api/gift-studio/projects", json={"name": "Twice"})
        client.post("/api/gift-studio/catalog/import", json={"project_id": "twice"})

        second = client.post("/api/gift-studio/catalog/import", json={"project_id": "twice"})

        assert second.get_json()["added"] == []
        project = client.get("/api/gift-studio/projects/twice").get_json()["project"]
        assert len(project["pages"][0]["cards"]) == 2

    def test_import_preserves_a_customized_card(self, env):
        client, _, config = env
        client.post("/api/gift-studio/projects", json={"name": "Protected"})
        client.post("/api/gift-studio/catalog/import", json={"project_id": "protected"})

        project = client.get("/api/gift-studio/projects/protected").get_json()["project"]
        card = next(
            c for c in project["pages"][0]["cards"]
            if c["action_ref"]["gift_key"] == "5487"
        )
        card["customized"] = True
        next(l for l in card["layers"] if l.get("role") == "main")["text"] = "MINE"
        client.put("/api/gift-studio/projects/protected", json=project)
        config["Gifts"]["5487"] = ["give {mc} dirt 1"]

        response = client.post(
            "/api/gift-studio/catalog/import", json={"project_id": "protected"}
        )

        assert "5487" in response.get_json()["skipped_customized"]
        after = client.get("/api/gift-studio/projects/protected").get_json()["project"]
        survivor = next(
            c for c in after["pages"][0]["cards"]
            if c["action_ref"]["gift_key"] == "5487"
        )
        assert next(l for l in survivor["layers"] if l.get("role") == "main")["text"] == "MINE"


class TestAssetUpload:

    def test_a_real_png_is_accepted_and_listed(self, env):
        client, _, _ = env

        response = client.post(
            "/api/gift-studio/assets",
            data={"file": (io.BytesIO(png_bytes()), "My Icon.png")},
            content_type="multipart/form-data",
        )

        assert response.status_code == 201
        name = response.get_json()["asset"]["name"]
        assert name == "my-icon.png"
        assert client.get("/api/gift-studio/assets").get_json()["assets"][0]["name"] == name

    def test_a_renamed_non_image_is_rejected_by_decoding_not_by_extension(self, env):
        """A .png filename over text bytes must not pass."""
        client, _, _ = env

        response = client.post(
            "/api/gift-studio/assets",
            data={"file": (io.BytesIO(b"<?php system($_GET[0]); ?>"), "shell.png")},
            content_type="multipart/form-data",
        )

        assert response.status_code == 400
        assert "image" in response.get_json()["message"].lower()

    def test_svg_is_rejected(self, env):
        client, _, _ = env
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

        response = client.post(
            "/api/gift-studio/assets",
            data={"file": (io.BytesIO(svg), "vector.svg")},
            content_type="multipart/form-data",
        )

        assert response.status_code == 400

    def test_the_stored_extension_follows_the_decoded_format(self, env):
        """A real PNG uploaded as .jpg is stored as .png."""
        client, _, _ = env

        response = client.post(
            "/api/gift-studio/assets",
            data={"file": (io.BytesIO(png_bytes()), "mislabeled.jpg")},
            content_type="multipart/form-data",
        )

        assert response.get_json()["asset"]["name"].endswith(".png")

    def test_missing_file_and_empty_file_are_rejected(self, env):
        client, _, _ = env

        assert client.post(
            "/api/gift-studio/assets", data={}, content_type="multipart/form-data"
        ).status_code == 400
        assert client.post(
            "/api/gift-studio/assets",
            data={"file": (io.BytesIO(b""), "empty.png")},
            content_type="multipart/form-data",
        ).status_code == 400

    def test_oversized_upload_is_rejected_with_413(self, env, monkeypatch):
        import routes.gift_card_studio as routes_module
        monkeypatch.setattr(routes_module, "MAX_ASSET_BYTES", 64)
        client, _, _ = env

        response = client.post(
            "/api/gift-studio/assets",
            data={"file": (io.BytesIO(png_bytes(size=(256, 256))), "big.png")},
            content_type="multipart/form-data",
        )

        assert response.status_code == 413

    def test_delete_asset_then_404(self, env):
        client, _, _ = env
        name = client.post(
            "/api/gift-studio/assets",
            data={"file": (io.BytesIO(png_bytes()), "gone.png")},
            content_type="multipart/form-data",
        ).get_json()["asset"]["name"]

        assert client.delete(f"/api/gift-studio/assets/{name}").status_code == 200
        assert client.delete(f"/api/gift-studio/assets/{name}").status_code == 404


class TestAssetServing:

    def test_an_uploaded_asset_is_served_back(self, env):
        client, _, _ = env
        payload = png_bytes()
        name = client.post(
            "/api/gift-studio/assets",
            data={"file": (io.BytesIO(payload), "served.png")},
            content_type="multipart/form-data",
        ).get_json()["asset"]["name"]

        response = client.get(f"/gift-studio-assets/{name}")

        assert response.status_code == 200
        assert response.data == payload

    def test_missing_asset_is_404(self, env):
        client, _, _ = env

        assert client.get("/gift-studio-assets/absent.png").status_code == 404

    def test_serving_refuses_non_image_names(self, env, tmp_path):
        client, data_dir, _ = env
        # Plant a file the route must refuse to serve even though it exists.
        storage.ensure_dirs(data_dir)
        with open(f"{storage.assets_dir(data_dir)}/secrets.json", "w") as handle:
            handle.write("{}")

        assert client.get("/gift-studio-assets/secrets.json").status_code == 404

    def test_serving_refuses_traversal(self, env):
        client, _, _ = env

        for path in ("..%2f..%2fapp.py", "....//app.py"):
            assert client.get(f"/gift-studio-assets/{path}").status_code in (400, 404)
