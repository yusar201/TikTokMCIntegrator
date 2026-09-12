import json

from flask import Flask

from routes.sociabuzz import create_sociabuzz_blueprint, load_or_create_webhook_settings


def test_settings_secret_is_generated_once_and_persisted(tmp_path):
    settings_path = tmp_path / "sociabuzz_webhook.json"

    first = load_or_create_webhook_settings(str(settings_path))
    second = load_or_create_webhook_settings(str(settings_path))

    assert first == second
    assert len(first["path_secret"]) >= 32
    assert first["webhook_token"] == ""
    assert json.loads(settings_path.read_text(encoding="utf-8")) == first




def make_client(tmp_path, *, secret="path-secret", token=""):
    app = Flask(__name__)
    app.register_blueprint(
        create_sociabuzz_blueprint(
            secret=secret,
            expected_token=token,
            capture_path=str(tmp_path / "sociabuzz_webhook_capture.json"),
            max_body_bytes=4096,
        )
    )
    return app.test_client(), tmp_path / "sociabuzz_webhook_capture.json"


def test_capture_accepts_json_and_redacts_auth_headers(tmp_path):
    client, capture = make_client(tmp_path)

    response = client.post(
        "/webhook/sociabuzz/path-secret",
        json={
            "supporter": "Khito",
            "email_supporter": "private@example.com",
            "amount": 10000,
        },
        headers={
            "Authorization": "Bearer must-not-be-logged",
            "Sb-Webhook-Token": "hidden",
            "Newrelic": "trace-secret",
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    saved = json.loads(capture.read_text(encoding="utf-8"))
    assert saved["json"] == {
        "supporter": "Khito",
        "email_supporter": "[REDACTED]",
        "amount": 10000,
    }
    assert saved["raw_text"] == "[OMITTED]"
    assert saved["headers"]["Authorization"] == "[REDACTED]"
    assert saved["headers"]["Sb-Webhook-Token"] == "[REDACTED]"
    assert saved["headers"]["Newrelic"] == "[REDACTED]"


def test_wrong_secret_is_indistinguishable_from_missing_route(tmp_path):
    client, capture = make_client(tmp_path)

    response = client.post("/webhook/sociabuzz/wrong", json={"amount": 1})

    assert response.status_code == 404
    assert not capture.exists()


def test_configured_token_is_required(tmp_path):
    client, capture = make_client(tmp_path, token="correct-token")

    missing = client.post("/webhook/sociabuzz/path-secret", json={"amount": 1})
    wrong = client.post(
        "/webhook/sociabuzz/path-secret",
        json={"amount": 1},
        headers={"Sb-Webhook-Token": "wrong"},
    )
    accepted = client.post(
        "/webhook/sociabuzz/path-secret",
        json={"amount": 1},
        headers={"Sb-Webhook-Token": "correct-token"},
    )

    assert missing.status_code == 404
    assert wrong.status_code == 404
    assert accepted.status_code == 200
    assert capture.exists()


def test_oversized_request_is_rejected_without_capture(tmp_path):
    client, capture = make_client(tmp_path)

    response = client.post(
        "/webhook/sociabuzz/path-secret",
        data=b"x" * 4097,
        content_type="application/octet-stream",
    )

    assert response.status_code == 413
    assert not capture.exists()
