"""Download a TikTok gift animation asset to local cache and update manifest.

URLs come from GiftEvent asset resources. TikTok commonly serves gift effects as
ZIP bundles (often named .zip or .x-zip-compressed) containing output.mp4 plus
config.json. The overlay cannot play the ZIP directly, so this downloader extracts
the playable payload and stores that as /gift_assets/gift_<id>.<ext>.
"""
import io
import os
import time
import zipfile
import urllib.request
import urllib.error

from .manifest import ASSETS_DIR, get_entry, set_entry


def _ext_from_name(name: str) -> str:
    """Pick an extension from a URL/path/member name."""
    u = (name or "").split("?", 1)[0].lower()
    if ".webm" in u:
        return "webm"
    if ".json" in u or "lottie" in u:
        return "json"
    if ".gif" in u:
        return "gif"
    if ".mp4" in u or ".mov" in u:
        return "mp4"
    if ".zip" in u or "x-zip-compressed" in u:
        return "zip"
    return ""


def _sniff_ext(url: str, data: bytes | None = None) -> str:
    """Pick a sensible file extension from URL + magic bytes."""
    if data:
        head = data[:32]
        if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06") or head.startswith(b"PK\x07\x08"):
            return "zip"
        if b"ftyp" in head:
            return "mp4"
        if head.startswith(b"\x1aE\xdf\xa3"):
            return "webm"
        stripped = data[:128].lstrip()
        if stripped.startswith(b"{") or stripped.startswith(b"["):
            return "json"
        if head.startswith(b"GIF8"):
            return "gif"
    return _ext_from_name(url) or "mp4"


def _extract_zip_payload(data: bytes) -> tuple[bytes, str, str] | None:
    """Extract the best browser-playable asset from a TikTok ZIP bundle."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            members = [i for i in zf.infolist() if not i.is_dir() and i.file_size > 0]
            if not members:
                return None

            def score(info: zipfile.ZipInfo) -> tuple[int, int]:
                name = info.filename.lower()
                ext = _ext_from_name(name)
                ext_score = {"mp4": 50, "webm": 45, "gif": 35, "json": 10}.get(ext, 0)
                name_score = 20 if os.path.basename(name) in ("output.mp4", "output.webm", "output.gif") else 0
                return (ext_score + name_score, info.file_size)

            best = max(members, key=score)
            if score(best)[0] <= 0:
                return None
            payload = zf.read(best)
            ext = _sniff_ext(best.filename, payload)
            if ext == "zip":
                return None
            return payload, ext, best.filename
    except (zipfile.BadZipFile, RuntimeError, OSError):
        return None


def _normalize_payload(source_url: str, data: bytes) -> tuple[bytes, str] | None:
    """Return (browser-playable bytes, ext), extracting TikTok ZIP bundles."""
    ext = _sniff_ext(source_url, data)
    if ext == "zip":
        extracted = _extract_zip_payload(data)
        if not extracted:
            print(f"[!] Gift asset ZIP had no playable payload: {source_url}")
            return None
        payload, payload_ext, member = extracted
        print(f"[GIFT-ASSET] Extracted {member} from TikTok ZIP bundle")
        return payload, payload_ext
    return data, ext


def _cache_busted_url(fname: str) -> str:
    return f"/gift_assets/{fname}?v={int(time.time())}"


def _repair_cached_zip(gift_id: int, cached: dict) -> str | None:
    """If an older build cached a ZIP as .mp4, extract it in-place and update manifest."""
    local = cached.get("local", "")
    if not local or not os.path.exists(local):
        return None
    try:
        with open(local, "rb") as f:
            data = f.read()
    except OSError:
        return None

    if _sniff_ext(local, data) != "zip":
        return cached.get("local_url")

    normalized = _normalize_payload(cached.get("source", ""), data)
    if not normalized:
        return None
    payload, ext = normalized
    fname = f"gift_{gift_id}.{ext}"
    fpath = os.path.join(ASSETS_DIR, fname)
    try:
        with open(fpath, "wb") as f:
            f.write(payload)
    except OSError as e:
        print(f"[!] Gift asset cache repair failed for gift_id={gift_id}: {e}")
        return None
    local_url = _cache_busted_url(fname)
    set_entry(gift_id, fpath, local_url, cached.get("source", ""), ext)
    print(f"[GIFT-ASSET] Repaired cached ZIP asset for gift_id={gift_id}: {local_url}")
    return local_url


def download_gift_asset(gift_id: int, url: str, timeout: int = 8) -> str | None:
    """Download animation, cache locally, return the local URL path.

    Returns None on failure. Idempotent — re-uses cached entry if present,
    repairing older bad ZIP-as-MP4 cache files when encountered.
    """
    if not url or not gift_id:
        return None

    # Cache hit — return existing local URL, but repair old ZIP-as-MP4 cache first.
    cached = get_entry(gift_id)
    if cached and os.path.exists(cached.get("local", "")):
        return _repair_cached_zip(gift_id, cached) or cached.get("local_url")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        # Sanity: don't write tiny error pages (404 HTML etc.)
        if len(data) < 256:
            print(f"[!] Gift asset too small ({len(data)} bytes), skipping: {url}")
            return None
        normalized = _normalize_payload(url, data)
        if not normalized:
            return None
        data, ext = normalized
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
        print(f"[!] Gift asset download failed for gift_id={gift_id}: {e}")
        return None

    os.makedirs(ASSETS_DIR, exist_ok=True)
    fname = f"gift_{gift_id}.{ext}"
    fpath = os.path.join(ASSETS_DIR, fname)
    try:
        with open(fpath, "wb") as f:
            f.write(data)
    except OSError as e:
        print(f"[!] Gift asset write failed for gift_id={gift_id}: {e}")
        return None

    local_url = _cache_busted_url(fname)
    set_entry(gift_id, fpath, local_url, url, ext)
    return local_url
