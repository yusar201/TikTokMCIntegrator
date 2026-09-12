"""Gift Card Studio catalog/page UX corrections from hands-on review."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
STUDIO = (ROOT / "static" / "gift-studio" / "studio.js").read_text(encoding="utf-8")
EDITOR = (ROOT / "static" / "gift-studio" / "editor.js").read_text(encoding="utf-8")
STYLE = (ROOT / "static" / "gift-studio" / "studio.css").read_text(encoding="utf-8")


def test_catalog_has_check_all_visible_control():
    assert 'id="gcs-check-all"' in INDEX
    assert "$('gcs-check-all').onclick=toggleAllVisible" in STUDIO
    assert "function visibleCatalogRows()" in STUDIO
    assert "function toggleAllVisible()" in STUDIO


def test_check_all_operates_on_current_filtered_results():
    assert "const rows=visibleCatalogRows()" in STUDIO
    assert "rows.every(entry=>state.selected.has(String(entry.key)))" in STUDIO
    assert "state.selected.add(String(entry.key))" in STUDIO
    assert "state.selected.delete(String(entry.key))" in STUDIO


def test_check_all_label_reflects_visible_selection_state():
    assert "allVisibleSelected" in STUDIO
    assert "Clear visible" in STUDIO
    assert "Check all" in STUDIO


def test_pages_have_remove_selected_page_control():
    assert 'id="gcs-remove-page"' in INDEX
    assert "$('gcs-remove-page').onclick=removePage" in STUDIO
    assert "function removePage()" in STUDIO


def test_removing_page_keeps_indices_valid_and_marks_project_changed():
    assert "state.project.pages.splice(state.pageIndex,1)" in STUDIO
    assert "state.pageIndex=Math.min(state.pageIndex,state.project.pages.length-1)" in STUDIO
    assert "state.cardIndex=0;state.layerIndex=0;changed(true)" in STUDIO


def test_last_page_cannot_be_removed():
    assert "state.project.pages.length<=1" in STUDIO
    assert "remove.disabled=(state.project?.pages?.length||0)<=1" in EDITOR


def test_useless_1x5_preset_is_completely_removed():
    assert 'gcs-preset-1x5' not in INDEX
    assert 'gcs-preset-1x5' not in STUDIO
    assert 'Apply 1 × 5' not in INDEX


def test_layout_is_the_complete_multi_page_composer_workspace():
    for element_id in (
        "gcs-auto-pages", "gcs-duplicate-page", "gcs-add-empty-page",
        "gcs-page-card-summary", "gcs-all-page-previews",
        "gcs-layout-estimate", "gcs-layout-generate", "gcs-layout-output",
    ):
        assert f'id="{element_id}"' in INDEX
    assert "Auto-build pages" in INDEX
    assert "All Pages Preview" in INDEX
    assert "Export Overlay" in INDEX


def test_auto_page_builder_and_duplicate_page_are_bound():
    assert "$('gcs-auto-pages').onclick=autoBuildPages" in STUDIO
    assert "$('gcs-duplicate-page').onclick=duplicateCurrentPage" in STUDIO
    assert "$('gcs-add-empty-page').onclick=addEmptyPage" in STUDIO
    assert "autoPaginateProject" in STUDIO
    assert "duplicatePage" in STUDIO


def test_layout_preview_renders_every_page_and_shares_export_flow():
    assert "function renderAllPagePreviews()" in STUDIO
    assert "state.project.pages.map" in STUDIO
    assert "renderPageSvg" in STUDIO
    assert "$('gcs-layout-estimate').onclick=estimate" in STUDIO
    assert "$('gcs-layout-generate').onclick=generate" in STUDIO
    assert "function syncGenerateControls" in STUDIO


def test_layout_composer_has_responsive_preview_and_export_styling():
    assert ".gcs-composer" in STYLE
    assert ".gcs-page-preview-grid" in STYLE
    assert ".gcs-composer-export" in STYLE
    assert ".gcs-page-summary" in STYLE


def test_card_editor_is_global_and_layout_has_manual_assignment_workspace():
    assert "Global Card Library" in INDEX
    assert 'id="gcs-page-card-library"' in INDEX
    assert 'id="gcs-page-assigned-cards"' in INDEX
    assert 'id="gcs-assign-card"' in INDEX
    assert 'id="gcs-unassign-card"' in INDEX
    assert "normalizeCardLibrary" in STUDIO
    assert "renderPageAssignments" in STUDIO
    assert "assignCardToPage" in STUDIO
    assert "removeCardFromPage" in STUDIO


def test_assignment_lists_are_rich_rows_not_bare_selects():
    # Bare <select> rows showed only the gift name, so Khito could not tell
    # which gift maps to which action. Both lists are now rich div rows.
    assert '<select id="gcs-page-card-library"' not in INDEX
    assert '<select id="gcs-page-assigned-cards"' not in INDEX
    assert '<div id="gcs-page-card-library"' in INDEX
    assert '<div id="gcs-page-assigned-cards"' in INDEX
    assert 'id="gcs-page-card-search"' in INDEX
    assert "cardActionText" in STUDIO or "assign-rows.js" in STUDIO
    assert "assignRowHtml" in STUDIO or "assign-rows.js" in STUDIO
    assert "gcs-assign-action" in STYLE


def test_assignment_rows_show_no_forbidden_artwork_or_gradients():
    assert "linear-gradient" not in STYLE
    assert "radial-gradient" not in STYLE
    assert "backdrop-filter" not in STYLE
    assert "box-shadow: 0 0" not in STYLE


def test_editor_reads_global_library_not_selected_page_cards():
    assert "state.project?.card_library" in EDITOR
    assert "currentPage(state)?.cards?.[state.cardIndex]" not in EDITOR
