"""API contract for manual viewer coin adjustments from the Points tab."""

import pytest
from flask import Flask

import routes.points as points_routes


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(points_routes.points_bp, url_prefix="/api/points")
    return app.test_client()


def test_adjust_route_forwards_operation_amount_and_note(client, monkeypatch):
    captured = {}

    def fake_adjust(user_id, operation, amount, note=""):
        captured.update(user_id=user_id, operation=operation, amount=amount, note=note)
        return {"user_id": user_id, "total_coins": 500, "applied_delta": 400}

    monkeypatch.setattr(points_routes.points_store, "adjust_coins", fake_adjust)

    response = client.post("/api/points/viewer/adjust", json={
        "id": "123",
        "operation": "add",
        "amount": 400,
        "note": "missed gift",
    })

    assert response.status_code == 200
    assert captured == {
        "user_id": "123",
        "operation": "add",
        "amount": 400,
        "note": "missed gift",
    }
    assert response.get_json()["total_coins"] == 500


def test_adjust_route_returns_refreshed_viewer_detail(client, monkeypatch):
    monkeypatch.setattr(points_routes.points_store, "adjust_coins",
                        lambda *a, **k: {"total_coins": 500, "applied_delta": 400})
    monkeypatch.setattr(points_routes.points_store, "viewer_detail",
                        lambda user_id, history_limit=100: {
                            "viewer": {"user_id": user_id, "total_coins": 500},
                            "history": [{"ts": 1.0, "coins": 400, "kind": "manual"}],
                        })

    payload = client.post("/api/points/viewer/adjust", json={
        "id": "123", "operation": "add", "amount": 400,
    }).get_json()

    assert payload["viewer"]["total_coins"] == 500
    assert payload["history"][0]["kind"] == "manual"


def test_adjust_route_rejects_missing_id(client):
    response = client.post("/api/points/viewer/adjust",
                           json={"operation": "add", "amount": 10})

    assert response.status_code == 400
    assert response.get_json()["error"] == "missing id"


def test_adjust_route_maps_validation_error_to_400(client, monkeypatch):
    def boom(*a, **k):
        raise ValueError("operation must be set, add, or remove")

    monkeypatch.setattr(points_routes.points_store, "adjust_coins", boom)

    response = client.post("/api/points/viewer/adjust",
                           json={"id": "1", "operation": "nope", "amount": 10})

    assert response.status_code == 400
    assert response.get_json()["error"] == "operation must be set, add, or remove"


def test_adjust_route_maps_unknown_viewer_to_404(client, monkeypatch):
    def missing(*a, **k):
        raise LookupError("viewer 9 not found")

    monkeypatch.setattr(points_routes.points_store, "adjust_coins", missing)

    response = client.post("/api/points/viewer/adjust",
                           json={"id": "9", "operation": "add", "amount": 10})

    assert response.status_code == 404
    assert response.get_json()["error"] == "viewer 9 not found"


def test_adjust_route_requires_a_json_body(client):
    response = client.post("/api/points/viewer/adjust")

    assert response.status_code == 400
    assert "error" in response.get_json()
