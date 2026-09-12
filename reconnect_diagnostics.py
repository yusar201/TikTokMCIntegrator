"""Operator-facing diagnostics for TikTok connection failures."""

from __future__ import annotations

import json
import re
import threading
import time
import traceback
from urllib.parse import urlsplit, urlunsplit


_MAX_BODY_PREVIEW = 240
_CAPTURE_MAX_AGE_SECONDS = 10.0
_LAST_RESPONSE: dict[str, object] | None = None
_LAST_RESPONSE_AT = 0.0
_LAST_RESPONSE_LOCK = threading.Lock()
_SECRET_PATTERNS = (
    re.compile(r"(?i)(sessionid|sessionid_ss|sid_tt|token|api[_-]?key|authorization)([=:]\s*)([^\s&;,]+)"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+"),
)


def _safe_endpoint(url: object) -> str:
    """Return scheme/host/path only; never expose signed query parameters."""
    try:
        parts = urlsplit(str(url))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except Exception:
        return "unknown"


def _redact_preview(value: str) -> str:
    preview = " ".join(value.replace("\x00", "").split())[:_MAX_BODY_PREVIEW]
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.lower().startswith("(?i)(bearer"):
            preview = pattern.sub(r"\1[REDACTED]", preview)
        else:
            preview = pattern.sub(r"\1\2[REDACTED]", preview)
    return preview or "<empty>"


def _safe_response(response: object) -> dict[str, object]:
    content = bytes(getattr(response, "content", b"") or b"")
    headers = getattr(response, "headers", {}) or {}
    request = getattr(response, "request", None)
    return {
        "endpoint": _safe_endpoint(getattr(request, "url", "unknown")),
        "status": getattr(response, "status_code", "unknown"),
        "content_type": str(headers.get("content-type", "unknown")).split(";", 1)[0],
        "bytes": len(content),
        "body_preview": _redact_preview(content.decode("utf-8", errors="replace")),
    }


def _response_lines(context: dict[str, object]) -> list[str]:
    return [
        "Failing HTTP response:",
        f"  endpoint={context['endpoint']}",
        f"  status={context['status']}",
        f"  content_type={context['content_type']}",
        f"  bytes={context['bytes']}",
        f"  body_preview={context['body_preview']}",
    ]


def last_http_response() -> dict[str, object] | None:
    """Return the most recently captured response context, if still relevant."""
    with _LAST_RESPONSE_LOCK:
        if _LAST_RESPONSE is None:
            return None
        if time.monotonic() - _LAST_RESPONSE_AT > _CAPTURE_MAX_AGE_SECONDS:
            return None
        return dict(_LAST_RESPONSE)


def install_http_response_capture(http_client: object) -> None:
    """Attach a lightweight async HTTPX response hook once per client."""
    hooks = getattr(http_client, "event_hooks", None)
    if not isinstance(hooks, dict):
        return
    response_hooks = hooks.setdefault("response", [])
    if any(getattr(hook, "_tiktok_diagnostics_capture", False) for hook in response_hooks):
        return

    async def _capture(response: object) -> None:
        global _LAST_RESPONSE, _LAST_RESPONSE_AT
        try:
            context = _safe_response(response)
        except Exception:
            return
        with _LAST_RESPONSE_LOCK:
            _LAST_RESPONSE = context
            _LAST_RESPONSE_AT = time.monotonic()

    _capture._tiktok_diagnostics_capture = True  # type: ignore[attr-defined]
    response_hooks.append(_capture)


def _response_context(exc: BaseException) -> list[str]:
    """Extract safe HTTP fields from traceback frames or the response hook."""
    tb = exc.__traceback__
    while tb is not None:
        for value in tb.tb_frame.f_locals.values():
            if not hasattr(value, "status_code") or not hasattr(value, "content"):
                continue
            try:
                return _response_lines(_safe_response(value))
            except Exception:
                continue
        tb = tb.tb_next

    captured = last_http_response()
    return _response_lines(captured) if captured is not None else []


def format_connection_failure(
    exc: BaseException,
    *,
    attempt: int,
    max_attempts: int,
) -> str:
    """Return an actionable failure report with the complete exception chain.

    Traceback locals are intentionally excluded so credentials cannot leak into
    the dashboard console. Source filenames, line numbers, calls, exception
    causes, and exception messages are preserved.
    """
    lines = [
        f"TikTok connection failure ({attempt}/{max_attempts})",
        f"Exception: {type(exc).__name__}: {exc}",
    ]

    if isinstance(exc, json.JSONDecodeError):
        lines.append(
            "Diagnostic: TikTokLive received an empty or non-JSON response/payload; "
            "the exact failing TikTokLive call is shown in the traceback below."
        )

    lines.extend(_response_context(exc))
    lines.append("Full traceback:")
    lines.extend(
        part.rstrip("\n")
        for part in traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    return "\n".join(lines)
