"""Bounded file-backed log shared by dashboard and bot processes."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path


DEFAULT_MAX_BYTES = 1_000_000
DEFAULT_KEEP_LINES = 500
_READ_CHUNK = 64 * 1024


@dataclass(frozen=True)
class LogSnapshot:
    lines: list[str]
    revision: str


def _tail_bytes(path: Path, max_bytes: int) -> bytes:
    size = path.stat().st_size
    with path.open("rb") as stream:
        stream.seek(max(0, size - max_bytes))
        data = stream.read()
    if size > max_bytes:
        split = data.find(b"\n")
        data = data[split + 1 :] if split >= 0 else b""
    return data


def read_tail(path: str | os.PathLike[str], max_lines: int = DEFAULT_KEEP_LINES) -> LogSnapshot:
    log_path = Path(path)
    if not log_path.exists() or log_path.stat().st_size == 0:
        return LogSnapshot([], "empty")

    data = _tail_bytes(log_path, max(_READ_CHUNK, max_lines * 512))
    raw_lines = data.decode("utf-8", errors="replace").splitlines()[-max_lines:]
    revision_data = "\n".join(raw_lines).encode("utf-8")
    revision = hashlib.blake2s(revision_data, digest_size=8).hexdigest()
    return LogSnapshot(raw_lines, revision)


def _trim(log_path: Path, keep_lines: int) -> None:
    snapshot = read_tail(log_path, max_lines=keep_lines)
    body = "".join(line + "\n" for line in snapshot.lines)
    temp = log_path.with_suffix(log_path.suffix + ".tmp")
    temp.write_text(body, encoding="utf-8")
    os.replace(temp, log_path)


def append_line(
    path: str | os.PathLike[str],
    line: str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    keep_lines: int = DEFAULT_KEEP_LINES,
) -> None:
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    clean = str(line).replace("\r", " ").replace("\n", " ")
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(clean + "\n")
    if log_path.stat().st_size > max_bytes:
        _trim(log_path, keep_lines)


def clear_log(path: str | os.PathLike[str]) -> None:
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")
