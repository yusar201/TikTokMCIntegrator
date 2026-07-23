"""Regression tests for the dashboard bot-console Clear action."""

import app as dashboard


def test_clear_bot_logs_endpoint_removes_server_side_history():
    with dashboard._bot_logs_lock:
        dashboard.bot_logs[:] = ["first line", "second line"]

    client = dashboard.app.test_client()
    response = client.post("/api/bot/logs/clear")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    assert client.get("/api/bot/logs").get_json() == {"logs": []}
