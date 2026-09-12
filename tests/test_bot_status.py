"""Tests for the bot connection-state bridge (bot_status module)."""

import json
import os
import time

import bot_status


class _FakePaths:
    """Minimal paths stand-in exposing only data()."""

    def __init__(self, tmp_path):
        self._tmp = str(tmp_path)

    def data(self, name):
        return os.path.join(self._tmp, name)


def test_write_then_read_roundtrip(tmp_path):
    paths = _FakePaths(tmp_path)
    bot_status.write_status(paths, "connected", room_id="123", username="khito")
    data = bot_status.read_status(paths)
    assert data["state"] == "connected"
    assert data["room_id"] == "123"
    assert data["username"] == "khito"
    assert isinstance(data["ts"], float)


def test_read_missing_file_returns_empty_dict(tmp_path):
    paths = _FakePaths(tmp_path)
    assert bot_status.read_status(paths) == {}


def test_read_corrupt_file_returns_empty_dict(tmp_path):
    paths = _FakePaths(tmp_path)
    with open(paths.data(bot_status.STATUS_FILENAME), "w", encoding="utf-8") as f:
        f.write("{not valid json")
    assert bot_status.read_status(paths) == {}


def test_write_status_persists_error_and_attempt(tmp_path):
    paths = _FakePaths(tmp_path)
    bot_status.write_status(paths, "failed", attempt=3, max_attempts=20, error="boom")
    data = bot_status.read_status(paths)
    assert data["state"] == "failed"
    assert data["attempt"] == 3
    assert data["max_attempts"] == 20
    assert data["error"] == "boom"
