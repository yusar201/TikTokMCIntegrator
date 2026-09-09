"""Regression coverage for live Coin Goal Jar label changes."""

import app as dashboard
import routes.stats as stats


def test_saved_coin_goal_label_is_returned_without_browser_caching(tmp_path, monkeypatch):
    state_file = str(tmp_path / "coin_goal.json")
    monkeypatch.setattr(dashboard, "COIN_GOAL_FILE", state_file)
    monkeypatch.setattr(stats, "COIN_GOAL_FILE", state_file)
    client = dashboard.app.test_client()

    saved = client.post("/api/coingoal", json={
        "mode": "set",
        "current": 10,
        "goal": 100,
        "label": "Fresh Label",
        "sublabel": "Fresh Sub Label",
    })
    assert saved.status_code == 200
    assert saved.get_json()["data"]["label"] == "Fresh Label"

    response = client.get("/api/stats/coingoal")

    assert response.status_code == 200
    assert response.get_json()["label"] == "Fresh Label"
    assert response.headers["Cache-Control"] == "no-store, no-cache, must-revalidate, max-age=0"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"


def test_coin_goal_overlay_fetches_fresh_state_each_poll():
    html = dashboard.app.test_client().get("/overlay/coingoal").get_data(as_text=True)

    assert "? url + (url.includes('?') ? '&' : '?') + '_=' + Date.now()" in html
    # Roulette shares the no-store fetch path, so the condition now lists both types.
    assert "TYPE === 'coingoal'" in html and "{ cache: 'no-store' }" in html
    assert "labelEl.innerText = cgState.label" in html
