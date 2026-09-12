"""Production frontend contract for the lazy Gift Card Studio panel."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "templates" / "index.html"
SCRIPT = ROOT / "static" / "script.js"
STUDIO = ROOT / "static" / "gift-studio" / "studio.js"
STYLE = ROOT / "static" / "gift-studio" / "studio.css"


def source(path):
    return path.read_text(encoding="utf-8")


def test_sidebar_and_panel_exist_without_eager_module_script():
    html = source(INDEX)
    assert 'data-panel="gift-studio"' in html
    assert 'id="panel-gift-studio"' in html
    assert '/static/gift-studio/studio.js' not in html
    assert '<script type="module"' not in html or 'gift-studio' not in html.split('<script type="module"', 1)[-1]


def test_dashboard_dynamically_imports_studio_only_when_panel_opens():
    js = source(SCRIPT)
    assert "name === 'gift-studio'" in js
    assert "import('/static/gift-studio/studio.js" in js
    assert "activateGiftStudio" in js


def test_profile_switch_notifies_gift_studio_to_reload_catalog():
    script = source(SCRIPT)
    studio = source(STUDIO)
    assert "gcs:profile-changed" in script
    assert "gcs:profile-changed" in studio
    assert "await loadCatalog()" in studio


def test_project_toolbar_exposes_delete_control():
    html = source(INDEX)
    studio = source(STUDIO)
    assert 'id="gcs-delete-project"' in html
    assert "deleteCurrentProject" in studio


def test_action_artwork_workflow_is_removed_from_card_editor():
    html = source(INDEX)
    studio = source(STUDIO)
    assert 'id="gcs-minecraft-assets"' not in html
    assert "openActionArtwork" not in studio
    assert "minecraft-assets" not in studio


def test_studio_lifecycle_has_explicit_activate_and_dispose_exports():
    js = source(STUDIO)
    assert "export async function activate" in js
    assert "export function deactivate" in js
    assert "cancelAnimationFrame" in js
    assert "clearTimeout" in js or "clearInterval" in js
    assert "URL.revokeObjectURL" in js


def test_generate_flow_uses_folder_estimate_job_progress_and_cancel_routes():
    js = source(STUDIO)
    for route in (
        "/output-folder/browse",
        "/generate/estimate",
        "/generate",
        "/generate/jobs/",
    ):
        assert route in js
    assert "saved_path" in js


def test_editor_exposes_required_catalog_layout_layer_page_and_format_controls():
    html = source(INDEX)
    required_ids = (
        "gcs-catalog-search", "gcs-catalog-list", "gcs-import-selected",
        "gcs-project-select", "gcs-save-project", "gcs-card-list",
        "gcs-layer-list", "gcs-grid-rows", "gcs-grid-columns",
        "gcs-page-list", "gcs-preview", "gcs-output-folder",
        "gcs-format", "gcs-generate", "gcs-progress",
    )
    for element_id in required_ids:
        assert f'id="{element_id}"' in html


def test_studio_styles_do_not_use_forbidden_effects():
    css = source(STYLE).lower()
    assert "linear-gradient" not in css
    assert "radial-gradient" not in css
    assert "backdrop-filter" not in css
    assert "filter: blur" not in css
    assert "clip-path" not in css
    assert "text-shadow: 0 0" not in css


def test_panel_load_does_not_start_studio_work_before_activation():
    js = source(STUDIO)
    prefix = js.split("export async function activate", 1)[0]
    assert "fetch(" not in prefix
    assert "setinterval(" not in prefix.lower()
    assert "requestanimationframe(" not in prefix.lower()
    assert "new worker(" not in prefix.lower()


def test_manual_action_icon_remains_without_minecraft_setup():
    html = source(INDEX)
    js = source(STUDIO)
    assert 'id="gcs-minecraft-assets"' not in html
    assert "minecraft-assets" not in js
    assert "'action_icon'" in js  # manual upload support remains
