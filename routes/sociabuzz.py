"""Minimal, capture-only SociaBuzz webhook receiver.

No gameplay actions are executed here. The first verified SociaBuzz test request is
captured so its real payload contract can be implemented without guessing.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import tempfile
from datetime import datetime, timezone

from flask import Blueprint, abort, jsonify, request

_SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "newrelic",
    "sb-webhook-token",
    "x-api-key",
    "x-auth-token",
    "x-webhook-token",
}


def _safe_headers(headers):
    result = {}
    for name, value in headers.items():
        result[name] = "[REDACTED]" if name.lower() in _SENSITIVE_HEADERS else value[:1000]
    return result


def _safe_json(value):
    if not isinstance(value, dict):
        return value
    sanitized = dict(value)
    if "email_supporter" in sanitized:
        sanitized["email_supporter"] = "[REDACTED]"
    return sanitized


def _atomic_write_json(path, payload):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".sociabuzz-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_or_create_webhook_settings(path):
    try:
        with open(path, "r", encoding="utf-8") as stream:
            loaded = json.load(stream)
        secret = str(loaded.get("path_secret") or "")
        if len(secret) >= 32:
            return {
                "path_secret": secret,
                "webhook_token": str(loaded.get("webhook_token") or ""),
            }
    except (OSError, ValueError, TypeError):
        pass

    settings = {"path_secret": secrets.token_urlsafe(32), "webhook_token": ""}
    _atomic_write_json(path, settings)
    return settings


def create_sociabuzz_blueprint(*, secret, expected_token="", capture_path, max_body_bytes=65536):
    blueprint = Blueprint("sociabuzz_webhook", __name__)
    path_secret = str(secret or "")
    webhook_token = str(expected_token or "")

    @blueprint.post("/webhook/sociabuzz/<provided_secret>")
    def capture_sociabuzz_webhook(provided_secret):
        if not path_secret or not hmac.compare_digest(provided_secret, path_secret):
            abort(404)

        if webhook_token:
            provided_token = request.headers.get("Sb-Webhook-Token", "")
            if not hmac.compare_digest(provided_token, webhook_token):
                abort(404)

        if request.content_length is not None and request.content_length > max_body_bytes:
            abort(413)

        raw = request.get_data(cache=True, as_text=False)
        if len(raw) > max_body_bytes:
            abort(413)

        parsed_json = request.get_json(silent=True)
        capture = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "method": request.method,
            "content_type": request.content_type,
            "headers": _safe_headers(request.headers),
            "query": request.args.to_dict(flat=False),
            "form": request.form.to_dict(flat=False),
            "json": _safe_json(parsed_json),
            "raw_text": "[OMITTED]",
        }
        _atomic_write_json(capture_path, capture)
        return jsonify({"ok": True})

    return blueprint
