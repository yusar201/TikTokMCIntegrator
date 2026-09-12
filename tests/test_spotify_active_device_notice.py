"""Spotify connection must distinguish authorization from an active playback device."""

from pathlib import Path

import spotify_handler as sh


ROOT = Path(__file__).resolve().parents[1]


def test_status_reports_authorized_but_inactive_device(monkeypatch):
    monkeypatch.setattr(sh, "get_valid_token", lambda: {"access_token": "ok", "oauth_flow": "pkce"})
    monkeypatch.setattr(sh, "get_current_playback", lambda: {})

    status = sh.get_connection_status()

    assert status["authorized"] is True
    assert status["connected"] is False
    assert status["needs_active_device"] is True
    assert "play something" in status["error"].lower()


def test_status_reports_authorized_and_active_device(monkeypatch):
    monkeypatch.setattr(sh, "get_valid_token", lambda: {"access_token": "ok", "oauth_flow": "pkce"})
    monkeypatch.setattr(sh, "get_current_playback", lambda: {
        "device_name": "Desktop",
        "is_playing": True,
        "item": {"name": "Song"},
    })

    status = sh.get_connection_status()

    assert status["authorized"] is True
    assert status["connected"] is True
    assert status["needs_active_device"] is False
    assert status["device"] == "Desktop"


def test_song_panel_has_persistent_active_device_notice_and_guided_toast():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")

    assert 'id="spotify-active-device-notice"' in html
    assert "Open Spotify and play any song once" in html
    assert "data.needs_active_device" in script
    assert "Spotify connected. Now open Spotify and play any song once" in script
