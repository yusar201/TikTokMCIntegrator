"""Regression tests for actionable TikTok connection failures."""

import asyncio
import json
from pathlib import Path

from reconnect_diagnostics import (
    format_connection_failure,
    install_http_response_capture,
    last_http_response,
)


def _raise_json_failure():
    json.loads("")


def test_connection_failure_always_contains_full_traceback_and_exact_call_site():
    try:
        _raise_json_failure()
    except Exception as exc:
        output = format_connection_failure(exc, attempt=3, max_attempts=20)

    assert "TikTok connection failure (3/20)" in output
    assert "Traceback (most recent call last):" in output
    assert "_raise_json_failure" in output
    assert 'json.loads("")' in output
    assert "JSONDecodeError: Expecting value: line 1 column 1 (char 0)" in output


def test_json_decode_failure_explains_what_is_known_without_claiming_an_endpoint():
    try:
        _raise_json_failure()
    except Exception as exc:
        output = format_connection_failure(exc, attempt=1, max_attempts=20)

    assert "empty or non-JSON response/payload" in output
    assert "exact failing TikTokLive call is shown in the traceback" in output


def test_chained_root_cause_is_not_hidden():
    try:
        try:
            raise ValueError("upstream body was HTML")
        except ValueError as cause:
            raise RuntimeError("connect failed") from cause
    except Exception as exc:
        output = format_connection_failure(exc, attempt=1, max_attempts=20)

    assert "ValueError: upstream body was HTML" in output
    assert "RuntimeError: connect failed" in output
    assert "direct cause" in output


def test_json_failure_includes_exact_sanitized_http_response_context():
    class Request:
        url = "https://webcast.tiktok.com/room/check?sessionid=SECRET&room_id=123"

    class Response:
        status_code = 200
        headers = {"content-type": "text/html", "content-length": "18"}
        request = Request()
        content = b"<html>blocked</html>"

        def json(self):
            json.loads(self.content)

    try:
        Response().json()
    except Exception as exc:
        output = format_connection_failure(exc, attempt=1, max_attempts=20)

    assert "Failing HTTP response:" in output
    assert "endpoint=https://webcast.tiktok.com/room/check" in output
    assert "status=200" in output
    assert "content_type=text/html" in output
    assert "bytes=20" in output
    assert "body_preview=<html>blocked</html>" in output
    assert "SECRET" not in output
    assert "room_id=123" not in output


def test_http_response_capture_records_safe_context_without_breaking_existing_hooks():
    calls = []

    async def existing_hook(response):
        calls.append(response.status_code)

    class Client:
        event_hooks = {"request": [], "response": [existing_hook]}

    class Request:
        url = "https://example.test/gift/list/?sessionid=SECRET"

    class Response:
        status_code = 503
        headers = {"content-type": "text/plain"}
        request = Request()
        content = b"upstream unavailable"

    client = Client()
    install_http_response_capture(client)
    assert len(client.event_hooks["response"]) == 2

    asyncio.run(client.event_hooks["response"][-1](Response()))

    assert calls == []
    assert last_http_response() == {
        "endpoint": "https://example.test/gift/list/",
        "status": 503,
        "content_type": "text/plain",
        "bytes": 20,
        "body_preview": "upstream unavailable",
    }


def test_json_failure_uses_last_captured_response_when_library_drops_response_object():
    class Client:
        event_hooks = {"request": [], "response": []}

    class Request:
        url = "https://example.test/room/api/?token=SECRET"

    class Response:
        status_code = 200
        headers = {"content-type": "text/html"}
        request = Request()
        content = b"<html>captcha</html>"

    client = Client()
    install_http_response_capture(client)
    asyncio.run(client.event_hooks["response"][-1](Response()))

    try:
        _raise_json_failure()
    except Exception as exc:
        output = format_connection_failure(exc, attempt=1, max_attempts=20)

    assert "endpoint=https://example.test/room/api/" in output
    assert "body_preview=<html>captcha</html>" in output
    assert "SECRET" not in output


def test_bot_installs_response_capture_on_tiktok_http_client():
    source = (Path(__file__).parents[1] / "minecraft_main.py").read_text(encoding="utf-8")

    assert "install_http_response_capture(client.web.httpx_client)" in source
