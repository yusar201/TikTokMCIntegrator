"""Regression tests for the bounded cross-process Minecraft Sim Console log."""

from pathlib import Path

from sim_console_log import append_line, clear_log, read_tail


def test_read_tail_returns_only_latest_lines_and_revision(tmp_path: Path):
    path = tmp_path / "sim_console.log"
    path.write_text("".join(f"line-{i}\n" for i in range(1_000)), encoding="utf-8")

    snapshot = read_tail(path, max_lines=500)

    assert len(snapshot.lines) == 500
    assert snapshot.lines[0] == "line-500"
    assert snapshot.lines[-1] == "line-999"
    assert snapshot.revision


def test_append_line_keeps_log_bounded_and_preserves_latest_entries(tmp_path: Path):
    path = tmp_path / "sim_console.log"

    for i in range(300):
        append_line(path, f"entry-{i}-" + ("x" * 80), max_bytes=4_096, keep_lines=30)

    snapshot = read_tail(path, max_lines=500)

    assert path.stat().st_size <= 4_096
    assert len(snapshot.lines) < 300
    assert snapshot.lines[-1].startswith("entry-299-")


def test_clear_log_truncates_existing_file(tmp_path: Path):
    path = tmp_path / "sim_console.log"
    path.write_text("old output\n", encoding="utf-8")

    clear_log(path)

    assert path.exists()
    assert path.stat().st_size == 0
    assert read_tail(path).lines == []


def test_frontend_refreshes_when_revision_changes_even_at_500_lines():
    script = (Path(__file__).resolve().parents[1] / "static" / "script.js").read_text(encoding="utf-8")

    assert "lastSimConsoleRevision" in script
    assert "data.revision !== lastSimConsoleRevision" in script
    assert "data.logs.length !== lastSimConsoleCount" not in script
