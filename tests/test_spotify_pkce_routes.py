"""Spotify PKCE Flask route contract."""

from urllib.parse import parse_qs, urlparse

from flask import Flask

import routes.spotify as spotify_routes
import spotify_handler as sh


def _client():
    app = Flask(__name__)
    app.register_blueprint(spotify_routes.spotify_bp, url_prefix="/api/spotify")
    return app.test_client()


def test_auth_url_route_returns_one_click_pkce_url(monkeypatch):
    monkeypatch.setattr(sh, "get_spotify_client_id", lambda: "public-client-id")
    sh.clear_pending_oauth()
    response = _client().get("/api/spotify/auth-url")

    assert response.status_code == 200
    query = parse_qs(urlparse(response.get_json()["url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [sh.SPOTIFY_REDIRECT_URI]


def test_callback_requires_matching_oauth_state(monkeypatch):
    called = False

    def fake_callback(code, state):
        nonlocal called
        called = True
        assert code == "code"
        assert state == "state"
        return {"status": "success"}

    monkeypatch.setattr(sh, "handle_pkce_callback", fake_callback)
    response = _client().get("/api/spotify/callback?code=code&state=state")

    assert response.status_code == 200
    assert called is True
    assert "spotify-connected" in response.get_data(as_text=True)


def test_config_route_never_returns_legacy_credentials(monkeypatch):
    monkeypatch.setattr(sh, "load_config", lambda: {
        "enabled": True,
        "spotify_client_id": "legacy",
        "spotify_client_secret": "legacy-secret",
        "spotify_redirect_uri": "legacy-uri",
    })
    response = _client().get("/api/spotify/config")
    body = response.get_json()

    # Route relies on load_config's migration scrub in production; defense-in-depth
    # means old credential keys must never be sent to the browser regardless.
    assert "spotify_client_id" not in body
    assert "spotify_client_secret" not in body
    assert "spotify_redirect_uri" not in body
