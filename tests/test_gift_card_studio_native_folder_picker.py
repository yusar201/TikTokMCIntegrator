"""Desktop-shell integration for Gift Card Studio's native folder picker."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"


def _source():
    return MAIN.read_text(encoding="utf-8")


def test_shell_registers_a_real_pywebview_folder_dialog():
    source = _source()

    assert "FOLDER_DIALOG" in source
    assert ".create_file_dialog(" in source
    assert "register_folder_picker" in source


def test_picker_is_registered_only_after_the_window_exists():
    source = _source()
    create = source.index("_window = webview.create_window(")
    register = source.index("_register_gift_studio_folder_picker(webview)", create)

    assert register > create


def test_picker_normalizes_pywebviews_tuple_result_to_one_directory():
    source = _source()

    assert "return chosen[0]" in source
    assert "if not chosen" in source


def test_failed_native_window_clears_the_picker_before_browser_fallback():
    source = _source()

    assert "register_folder_picker(None)" in source


def test_folder_picker_registration_starts_no_thread_or_timer():
    source = _source()
    helper_start = source.index("def _register_gift_studio_folder_picker")
    helper_end = source.index("\ndef ", helper_start + 5)
    helper = source[helper_start:helper_end]

    assert "threading.Thread" not in helper
    assert "threading.Timer" not in helper
    assert "while " not in helper
