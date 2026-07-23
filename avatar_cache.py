"""Local persistent cache for TikTok profile/avatar images.

TikTok avatar URLs are signed and expire/rotate. This module downloads the
image while the signed URL is still valid and stores a same-origin URL for OBS
overlays to use later.
"""
from __future__ import annotations

import hashlib
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

import paths

AVATAR_ASSETS_DIR = os.path.join(paths.ASSETS_DIR, "avatar_cache")
MAX_AVATAR_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT = 8

_CONTENT_TYPE_EXT = {
    "image/webp": ".webp",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
}


def is_local_avatar_url(url: str) -> bool:
    """Return True when `url` already points at our Flask-served avatar cache."""
    return str(url or "").startswith("/avatar_cache/")


def _safe_key(nick: str = "", unique_id: str = "", source_url: str = "") -> str:
    raw = (unique_id or nick or "").strip().lower()
    safe = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in raw).strip("_")
    if not safe:
        safe = "avatar"
    digest_src = (source_url or raw or str(time.time())).encode("utf-8", "ignore")
    digest = hashlib.sha1(digest_src).hexdigest()[:10]
    return f"{safe[:48]}_{digest}"


def _ext_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url or "").path.lower()
    for ext in (".webp", ".jpg", ".jpeg", ".png", ".gif"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    # TikTok URLs often include "~tplv-...webp" before query but not as clean path suffix.
    if ".webp" in path:
        return ".webp"
    if ".png" in path:
        return ".png"
    if ".jpg" in path or ".jpeg" in path:
        return ".jpg"
    return ".webp"


def _ext_from_response(content_type: str, fallback: str) -> str:
    content_type = (content_type or "").split(";", 1)[0].strip().lower()
    return _CONTENT_TYPE_EXT.get(content_type, fallback or ".webp")


def _looks_like_image(data: bytes) -> bool:
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return True
    if data.startswith(b"\xff\xd8\xff"):
        return True
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if data.startswith((b"GIF87a", b"GIF89a")):
        return True
    return False


def local_avatar_path_from_url(local_url: str) -> Optional[str]:
    """Convert /avatar_cache/name.webp to an absolute file path, safely."""
    if not is_local_avatar_url(local_url):
        return None
    name = os.path.basename(urllib.parse.urlparse(local_url).path)
    if not name or name in (".", ".."):
        return None
    path = os.path.abspath(os.path.join(AVATAR_ASSETS_DIR, name))
    root = os.path.abspath(AVATAR_ASSETS_DIR)
    if os.path.commonpath([root, path]) != root:
        return None
    return path


def cache_avatar_image(source_url: str, nick: str = "", unique_id: str = "") -> str:
    """Download a TikTok avatar URL and return a stable same-origin local URL.

    Returns an empty string when download/validation fails. Callers should keep
    using the source URL/fallback in that case.
    """
    source_url = str(source_url or "").strip()
    if not source_url or is_local_avatar_url(source_url) or source_url.startswith("data:"):
        return source_url if is_local_avatar_url(source_url) else ""

    try:
        os.makedirs(AVATAR_ASSETS_DIR, exist_ok=True)
        fallback_ext = _ext_from_url(source_url)
        stem = _safe_key(nick, unique_id, source_url)

        # If this exact URL was already cached, reuse it without network.
        for ext in (fallback_ext, ".webp", ".jpg", ".png", ".gif"):
            candidate = os.path.join(AVATAR_ASSETS_DIR, stem + ext)
            if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
                return f"/avatar_cache/{os.path.basename(candidate)}"

        req = urllib.request.Request(
            source_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
                "Referer": "https://www.tiktok.com/",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            content_type = resp.headers.get("Content-Type", "")
            ext = _ext_from_response(content_type, fallback_ext)
            data = resp.read(MAX_AVATAR_BYTES + 1)

        if len(data) > MAX_AVATAR_BYTES:
            raise ValueError("avatar image too large")
        if not _looks_like_image(data):
            raise ValueError(f"avatar response is not a supported image ({content_type})")

        final_path = os.path.join(AVATAR_ASSETS_DIR, stem + ext)
        tmp_path = final_path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(data)
        os.replace(tmp_path, final_path)
        return f"/avatar_cache/{os.path.basename(final_path)}"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as e:
        print(f"[AVATAR-CACHE] Failed to cache avatar for {nick or unique_id or 'unknown'}: {e}")
        return ""
    except Exception as e:
        print(f"[AVATAR-CACHE] Unexpected avatar cache error for {nick or unique_id or 'unknown'}: {e}")
        return ""
