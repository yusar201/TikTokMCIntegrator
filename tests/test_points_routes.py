"""Points API period-filter contract tests."""

from flask import Flask

import routes.points as points_routes


def _client():
    app = Flask(__name__)
    app.register_blueprint(points_routes.points_bp, url_prefix="/api/points")
    return app.test_client()


def test_viewers_route_forwards_period_bounds(monkeypatch):
    captured = {}

    def fake_list_viewers(**kwargs):
        captured.update(kwargs)
        return {"viewers": [], "total": 0}

    monkeypatch.setattr(points_routes.points_store, "list_viewers", fake_list_viewers)

    response = _client().get(
        "/api/points/viewers?limit=25&offset=5&sort=recent&q=ali&since=100.5&until=200.5"
    )

    assert response.status_code == 200
    assert captured == {
        "limit": 25,
        "offset": 5,
        "sort": "recent",
        "q": "ali",
        "since": 100.5,
        "until": 200.5,
    }


def test_viewers_route_rejects_reversed_period():
    response = _client().get("/api/points/viewers?since=200&until=100")

    assert response.status_code == 400
    assert response.get_json()["error"] == "until must be greater than since"
