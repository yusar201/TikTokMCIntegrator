"""Spotify desktop OAuth must use one-click PKCE without a client secret."""

import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

import spotify_handler as sh


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload) if text is None else text
        self.headers = {}

    def json(self):
        return self._payload


@pytest.fixture()
def oauth_files(monkeypatch, tmp_path):
    monkeypatch.setattr(sh, "TOKEN_FILE", str(tmp_path / "token.json"))
    monkeypatch.setattr(sh, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(sh, "get_spotify_client_id", lambda: "public-client-id")
    sh.clear_pending_oauth()
    yield tmp_path
    sh.clear_pending_oauth()


def test_begin_pkce_authorization_has_challenge_state_and_fixed_redirect(oauth_files):
    result = sh.begin_pkce_authorization()
    query = parse_qs(urlparse(result["url"]).query)

    assert query["client_id"] == ["public-client-id"]
    assert query["redirect_uri"] == [sh.SPOTIFY_REDIRECT_URI]
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) >= 43
    assert len(query["state"][0]) >= 32
    assert "code_verifier" not in query
    assert "client_secret" not in query


def test_pkce_callback_rejects_unknown_state_without_contacting_spotify(oauth_files, monkeypatch):
    called = False

    def unexpected_post(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("Spotify token endpoint must not be called")

    monkeypatch.setattr("requests.post", unexpected_post)
    result = sh.handle_pkce_callback("code", "unknown-state")

    assert "invalid or expired" in result["error"].lower()
    assert called is False


def test_pkce_callback_exchanges_verifier_without_client_secret(oauth_files, monkeypatch):
    auth = sh.begin_pkce_authorization()
    state = parse_qs(urlparse(auth["url"]).query)["state"][0]
    captured = {}

    def fake_post(url, data, timeout):
        captured.update({"url": url, "data": dict(data), "timeout": timeout})
        return FakeResponse(payload={
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
        })

    monkeypatch.setattr("requests.post", fake_post)
    result = sh.handle_pkce_callback("authorization-code", state)

    assert result["status"] == "success"
    assert captured["data"]["client_id"] == "public-client-id"
    assert captured["data"]["redirect_uri"] == sh.SPOTIFY_REDIRECT_URI
    assert captured["data"]["grant_type"] == "authorization_code"
    assert len(captured["data"]["code_verifier"]) >= 43
    assert "client_secret" not in captured["data"]
    stored = json.loads(Path(sh.TOKEN_FILE).read_text(encoding="utf-8"))
    assert stored["oauth_flow"] == "pkce"


def test_legacy_confidential_token_is_discarded_for_clean_pkce_reconnect(oauth_files):
    Path(sh.TOKEN_FILE).write_text(json.dumps({
        "access_token": "legacy-access",
        "refresh_token": "legacy-refresh",
        "expires_at": int(time.time()) + 3600,
    }), encoding="utf-8")

    assert sh.get_valid_token() is None
    assert not Path(sh.TOKEN_FILE).exists()


def test_pkce_refresh_uses_client_id_and_never_client_secret(oauth_files, monkeypatch):
    Path(sh.TOKEN_FILE).write_text(json.dumps({
        "access_token": "expired",
        "refresh_token": "refresh",
        "expires_at": int(time.time()) - 10,
        "oauth_flow": "pkce",
    }), encoding="utf-8")
    captured = {}

    def fake_post(url, data, timeout):
        captured.update(dict(data))
        return FakeResponse(payload={"access_token": "new", "expires_in": 3600})

    monkeypatch.setattr("requests.post", fake_post)
    sh._token_refresh_until = 0
    token = sh.get_valid_token()

    assert token["access_token"] == "new"
    assert captured["client_id"] == "public-client-id"
    assert captured["grant_type"] == "refresh_token"
    assert "client_secret" not in captured
    assert token["refresh_token"] == "refresh"
    assert token["oauth_flow"] == "pkce"


def test_load_config_scrubs_legacy_credentials_from_disk(oauth_files):
    legacy = sh.get_default_config() | {
        "spotify_client_id": "old-id",
        "spotify_client_secret": "old-secret",
        "spotify_redirect_uri": "old-uri",
    }
    Path(sh.CONFIG_FILE).write_text(json.dumps(legacy), encoding="utf-8")

    loaded = sh.load_config()
    stored = json.loads(Path(sh.CONFIG_FILE).read_text(encoding="utf-8"))

    for obsolete in ("spotify_client_id", "spotify_client_secret", "spotify_redirect_uri"):
        assert obsolete not in loaded
        assert obsolete not in stored


def test_song_config_no_longer_exposes_spotify_developer_credentials():
    defaults = sh.get_default_config()
    assert "spotify_client_id" not in defaults
    assert "spotify_client_secret" not in defaults
    assert "spotify_redirect_uri" not in defaults

    html = (Path(__file__).parents[1] / "templates" / "index.html").read_text(encoding="utf-8")
    script = (Path(__file__).parents[1] / "static" / "script.js").read_text(encoding="utf-8")
    for obsolete in ("song-client-id", "song-client-secret", "song-redirect-uri", "spotify-credential-warning"):
        assert obsolete not in html
        assert obsolete not in script
