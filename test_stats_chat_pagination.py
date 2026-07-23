import json

from routes.stats import init_stats_blueprint, stats_bp
from flask import Flask


def _client(tmp_path, entries):
    (tmp_path / "chat_log.json").write_text(json.dumps(entries), encoding="utf-8")
    init_stats_blueprint(str(tmp_path))
    app = Flask(__name__)
    app.register_blueprint(stats_bp, url_prefix="/api/stats")
    return app.test_client()


def _entries(count):
    return [
        {"nick": f"user{i}", "unique_id": f"u{i}", "comment": f"msg {i}", "timestamp": i}
        for i in range(count)
    ]


def test_chat_without_limit_preserves_legacy_list_response(tmp_path):
    client = _client(tmp_path, _entries(5))

    res = client.get("/api/stats/chat")

    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, list)
    assert [e["comment"] for e in data] == [f"msg {i}" for i in range(5)]


def test_chat_limit_returns_latest_page_with_indexes_and_total(tmp_path):
    client = _client(tmp_path, _entries(10))

    res = client.get("/api/stats/chat?limit=3")

    assert res.status_code == 200
    data = res.get_json()
    assert data["total"] == 10
    assert data["start"] == 7
    assert data["end"] == 10
    assert data["has_older"] is True
    assert data["next_before"] == 7
    assert [e["_chat_index"] for e in data["entries"]] == [7, 8, 9]
    assert [e["comment"] for e in data["entries"]] == ["msg 7", "msg 8", "msg 9"]


def test_chat_before_loads_older_page_before_index(tmp_path):
    client = _client(tmp_path, _entries(10))

    res = client.get("/api/stats/chat?limit=3&before=7")

    assert res.status_code == 200
    data = res.get_json()
    assert data["total"] == 10
    assert data["start"] == 4
    assert data["end"] == 7
    assert data["has_older"] is True
    assert data["next_before"] == 4
    assert [e["_chat_index"] for e in data["entries"]] == [4, 5, 6]


def test_chat_limit_is_clamped_for_dashboard_safety(tmp_path):
    client = _client(tmp_path, _entries(5000))

    res = client.get("/api/stats/chat?limit=99999")

    assert res.status_code == 200
    data = res.get_json()
    assert len(data["entries"]) == 2000
    assert data["start"] == 3000
    assert data["end"] == 5000
