"""Resolve overlay asset references to something a rasterizer can actually read.

The browser resolves ``/gift_assets/5655.png`` against the Flask app and fetches
``https://…tiktokcdn.com/…`` over the network. A rasterizer does neither: resvg
has no HTTP client and no notion of the app's URL space, so both reference kinds
render as *nothing at all* — a silently blank gift icon in every exported card.

This module closes that gap by rewriting an export-bound SVG so every ``href``
points at inline bytes:

* ``/gift_assets/<f>``        -> ``assets/gift_assets/<f>`` on disk
* ``/gift-studio-assets/<f>`` -> ``data/gift_card_studio/assets/<f>`` on disk
* ``https://…``               -> the locally cached copy if one exists, else the
  reference is dropped rather than left dangling
* ``data:image/…``            -> passed through untouched

Anything unresolvable is removed, so an export never contains a reference that
would resolve differently (or leak a request) on another machine.
"""
from __future__ import annotations

import base64
import mimetypes
import os
import re

# href="..." on an <image> element. Attribute values are XML-escaped by the
# renderer, and none of the accepted URL forms can contain a quote, so a
# non-greedy match to the closing quote is exact here.
_HREF = re.compile(r'href="([^"]*)"')

GIFT_ASSETS_PREFIX = "/gift_assets/"
STUDIO_ASSETS_PREFIX = "/gift-studio-assets/"

# Only formats the rasterizer can decode. SVG is deliberately excluded: an
# inlined SVG could carry its own scripts or external references.
INLINE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _safe_leaf(url_path: str) -> str:
    """Last path segment, with any query string and traversal stripped."""
    leaf = url_path.split("?", 1)[0].split("#", 1)[0]
    leaf = leaf.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if leaf in ("", ".", ".."):
        return ""
    return leaf


def _read_inline(path: str) -> str:
    """Read a local image file into a ``data:`` URI, or "" if unusable."""
    extension = os.path.splitext(path)[1].lower()
    mime = INLINE_MIME.get(extension)
    if mime is None:
        guessed, _ = mimetypes.guess_type(path)
        if guessed not in INLINE_MIME.values():
            return ""
        mime = guessed
    try:
        with open(path, "rb") as handle:
            payload = handle.read()
    except OSError:
        return ""
    if not payload:
        return ""
    return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"


def _contained_join(root: str, leaf: str) -> str:
    """Join and verify the result really sits under ``root``."""
    candidate = os.path.realpath(os.path.join(root, leaf))
    root_real = os.path.realpath(root)
    if candidate != root_real and not candidate.startswith(root_real + os.sep):
        return ""
    return candidate


def resolve_asset_href(href: str, base_dir: str, data_dir: str,
                       icon_manifest=None) -> str:
    """Return an inlinable ``data:`` URI for ``href``, or "" if unresolvable."""
    if not isinstance(href, str) or not href.strip():
        return ""
    href = href.strip()

    if href.startswith("data:image/"):
        return href

    if href.startswith(GIFT_ASSETS_PREFIX):
        leaf = _safe_leaf(href[len(GIFT_ASSETS_PREFIX):])
        if not leaf:
            return ""
        path = _contained_join(os.path.join(base_dir, "assets", "gift_assets"), leaf)
        return _read_inline(path) if path else ""

    if href.startswith(STUDIO_ASSETS_PREFIX):
        leaf = _safe_leaf(href[len(STUDIO_ASSETS_PREFIX):])
        if not leaf:
            return ""
        path = _contained_join(
            os.path.join(data_dir, "gift_card_studio", "assets"), leaf
        )
        return _read_inline(path) if path else ""

    if href.startswith("https://"):
        # Never fetch during an export: a stream-time network stall is worse
        # than a missing icon, and exports must be reproducible offline. Use the
        # cached copy the app already downloaded, if there is one.
        for entry in (icon_manifest or {}).values():
            if not isinstance(entry, dict):
                continue
            if entry.get("source") != href:
                continue
            local = entry.get("local")
            if local and os.path.exists(local):
                return _read_inline(local)
            local_url = entry.get("local_url") or ""
            if local_url.startswith(GIFT_ASSETS_PREFIX):
                return resolve_asset_href(local_url, base_dir, data_dir)
        return ""

    return ""


def inline_svg_assets(svg: str, base_dir: str, data_dir: str,
                      icon_manifest=None) -> tuple[str, dict]:
    """Rewrite every ``href`` in ``svg`` to inline bytes.

    Returns ``(svg, report)`` where report counts what resolved and what was
    dropped, so an export can tell the user "3 gift icons had no cached image"
    instead of quietly shipping empty boxes.
    """
    stats = {"total": 0, "inlined": 0, "dropped": 0, "missing": []}

    def replace(match):
        original = match.group(1)
        stats["total"] += 1
        resolved = resolve_asset_href(original, base_dir, data_dir, icon_manifest)
        if resolved:
            stats["inlined"] += 1
            return f'href="{resolved}"'
        stats["dropped"] += 1
        if original not in stats["missing"]:
            stats["missing"].append(original)
        # Point at nothing rather than at an unfetchable URL.
        return 'href=""'

    return _HREF.sub(replace, svg), stats


# ---- Icon caching --------------------------------------------------------
#
# Separate from the app's existing gift-asset downloader, which caches gift
# *animations* (mp4/webp video) for the live overlays. A card needs a static
# still image the rasterizer can decode, so the Studio caches those itself into
# its own asset directory. This also insulates saved projects from TikTok CDN
# URLs expiring — the plan's stated mitigation.

ICON_DOWNLOAD_TIMEOUT = 8
MAX_ICON_BYTES = 4 * 1024 * 1024


def cache_gift_icon(gift_id, icon_url, data_dir: str, timeout=ICON_DOWNLOAD_TIMEOUT):
    """Download a gift's static icon and store it as a Studio PNG asset.

    Returns the ``/gift-studio-assets/<name>`` URL, or ``None`` on any failure.
    Network access happens **only** here, on an explicit user action — never
    during an export or a render.
    """
    import urllib.error
    import urllib.request

    from . import storage

    if not gift_id or not icon_url or not str(icon_url).startswith("https://"):
        return None

    name = f"gift-icon-{gift_id}.png"
    existing = os.path.join(storage.assets_dir(data_dir), name)
    if os.path.exists(existing):
        return STUDIO_ASSETS_PREFIX + name

    try:
        request = urllib.request.Request(
            icon_url, headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_ICON_BYTES + 1)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
        return None

    if not payload or len(payload) > MAX_ICON_BYTES:
        return None

    # TikTok serves these as .webp behind a .png name; normalize to real PNG so
    # the extension matches the bytes and the rasterizer can always decode it.
    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            converted = image.convert("RGBA")
        buffer = io.BytesIO()
        converted.save(buffer, format="PNG")
        png_bytes = buffer.getvalue()
    except Exception:
        return None

    storage.ensure_dirs(data_dir)
    try:
        path = storage.asset_path(name, data_dir)
    except Exception:
        return None
    temporary = path + ".tmp"
    try:
        with open(temporary, "wb") as handle:
            handle.write(png_bytes)
        os.replace(temporary, path)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        return None

    return STUDIO_ASSETS_PREFIX + name


def cache_catalog_icons(entries, data_dir: str, timeout=ICON_DOWNLOAD_TIMEOUT) -> dict:
    """Cache the icon for each catalog entry, rewriting ``icon`` in place.

    Returns a report of what was cached and what failed, so the UI can flag
    "2 gifts have no usable icon" before the user builds cards around them.
    """
    cached, failed = [], []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        current = entry.get("icon") or ""
        if current.startswith(STUDIO_ASSETS_PREFIX):
            cached.append(entry.get("key"))
            continue
        source = entry.get("icon_remote") or (current if current.startswith("https://") else "")
        if not source:
            failed.append(entry.get("key"))
            continue
        url = cache_gift_icon(entry.get("gift_id"), source, data_dir, timeout)
        if url:
            entry["icon"] = url
            entry["icon_local"] = url
            entry["icon_missing"] = False
            cached.append(entry.get("key"))
        else:
            failed.append(entry.get("key"))

    return {"cached": cached, "failed": failed,
            "cached_count": len(cached), "failed_count": len(failed)}
