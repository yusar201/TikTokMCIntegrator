"""Fetch the EulerStream regional gift catalogs and union them into the cache.

Why regions: TikTok's ``/gift/list/`` returns only the room panel for the
connected stream (701 gifts on Khito's room, ``is_full_gift_data: False``).
EulerStream mirrors TikTok's panel **per region**, and gifts are region-gated —
``Game Controller`` (6581 / 7569, 100 coins) is absent from Indonesia but
present in the US blob. Unioning the regions below yielded 1767 unique gifts
when verified on 2026-09-02.

Two API facts that cost real debugging time:

* Plain ``urllib`` is rejected by Cloudflare with ``403 error code: 1010``. A
  browser ``User-Agent`` is required — see :func:`build_headers`.
* ``/webcast/gifts`` does not return gifts. It returns a short-lived signed R2
  URL; the gift blob lives behind that URL and is fetched **without** the api
  key (it is presigned).
"""
from __future__ import annotations

import gift_catalog

EULER_HOST = "https://tiktok.eulerstream.com"
GIFTS_ROUTE = EULER_HOST + "/webcast/gifts"
CATALOG_ROUTE = EULER_HOST + "/webcast/gifts/catalog"

# The catalog route silently clamps pageSize to 100 (verified: asking for 200,
# 500 and 1000 all returned 100 rows and totalPages=28 for 2783 gifts).
CATALOG_PAGE_SIZE = 100

# Hard stop so a pagination bug on either side can never spin forever.
_MAX_CATALOG_PAGES = 60

# Verified productive regions (2026-09-02). RU and IN are excluded because the
# API answers HTTP 422 for them; including them only buys failed requests.
DEFAULT_REGIONS = (
    "ID", "US", "GB", "JP", "PH", "MY", "SG", "VN", "TH",
    "BR", "DE", "FR", "SA", "TR", "KR", "TW", "MX", "IT", "ES", "EG",
)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_TIMEOUT_SECONDS = 45


def build_headers(api_key: str) -> dict:
    """Headers that actually get past Cloudflare on the Euler host."""
    return {
        "x-api-key": api_key,
        "User-Agent": _BROWSER_UA,
        "Accept": "application/json",
    }


def _gifts_from_blob(payload) -> list:
    """Pull the gift array out of the R2 blob, wrapped or bare."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("gifts"), list):
        return data["gifts"]
    if isinstance(payload.get("gifts"), list):
        return payload["gifts"]
    return []


def _fetch_region(client, region: str, headers: dict) -> list:
    """Gift rows for one region, or ``[]`` when the region is unavailable."""
    response = client.get(
        GIFTS_ROUTE,
        params={"region": region, "webcast_language": "en", "redirect": "false"},
        headers=headers,
    )
    if response.status_code != 200:
        return []

    signed_url = (response.json() or {}).get("url")
    if not signed_url:
        return []

    blob = client.get(signed_url, headers={"User-Agent": _BROWSER_UA})
    if blob.status_code != 200:
        return []

    return _gifts_from_blob(blob.json())


def sync_regions(path, api_key, regions=None, client=None):
    """Union every region's gift panel into the catalog at ``path``.

    Returns ``{"added", "updated", "regions_ok", "regions_failed",
    "failed_regions", "error"}``. Never raises: this is called from the bot's
    connect path and from a dashboard route, and a catalog refresh failing must
    never take either of them down.
    """
    stats = {
        "added": 0,
        "updated": 0,
        "regions_ok": 0,
        "regions_failed": 0,
        "failed_regions": [],
        "error": "",
    }

    if not api_key:
        stats["error"] = "No EulerStream api key configured (Settings.EulerApiKey)."
        return stats

    regions = list(regions or DEFAULT_REGIONS)
    headers = build_headers(api_key)

    owns_client = client is None
    if owns_client:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            stats["error"] = f"httpx unavailable: {exc}"
            return stats
        client = httpx.Client(timeout=_TIMEOUT_SECONDS, follow_redirects=True)

    collected = []
    try:
        for region in regions:
            try:
                rows = _fetch_region(client, region, headers)
            except Exception:
                rows = []
            if rows:
                collected.extend(rows)
                stats["regions_ok"] += 1
            else:
                stats["regions_failed"] += 1
                stats["failed_regions"].append(region)
    finally:
        if owns_client:
            try:
                client.close()
            except Exception:
                pass

    if collected:
        merged = gift_catalog.merge_into_catalog(path, collected, source="region")
        stats["added"] = merged["added"]
        stats["updated"] = merged["updated"]
    elif not stats["error"]:
        stats["error"] = "No region returned a gift catalog."

    return stats


def sync_euler_catalog(path, api_key, client=None):
    """Union EulerStream's full gift catalog (2783 rows) into ``path``.

    This covers gifts TikTok has retired from every live panel. Khito received
    ``Spirit of 45`` (9047), ``Live Up`` (1189923), ``Fighting`` (15957) and
    ``Spark ring`` (1189924) — none appear in any of the 20 regional panels, but
    all four are in this catalog with correct names and prices.

    Icons are deliberately dropped: the rows point at
    ``assets.cdn.eulerstream.com``, which answers 403 ``Origin not allowed`` (and
    404 for a reused signed URL) to any server-side fetch. ``gift_catalog``
    filters that host out, so these entries land with a name and price and pick
    up a real icon later from a panel refresh or a live GiftEvent.

    The route does not count against hourly/daily rate limits.
    """
    stats = {"added": 0, "updated": 0, "pages": 0, "fetched": 0, "error": ""}

    if not api_key:
        stats["error"] = "No EulerStream api key configured (Settings.EulerApiKey)."
        return stats

    headers = build_headers(api_key)
    owns_client = client is None
    if owns_client:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            stats["error"] = f"httpx unavailable: {exc}"
            return stats
        client = httpx.Client(timeout=_TIMEOUT_SECONDS, follow_redirects=True)

    collected = []
    try:
        page = 1
        total_pages = 1
        while page <= min(total_pages, _MAX_CATALOG_PAGES):
            try:
                response = client.get(
                    CATALOG_ROUTE,
                    params={"pageSize": CATALOG_PAGE_SIZE, "pageNumber": page},
                    headers=headers,
                )
            except Exception as exc:
                stats["error"] = f"page {page}: {exc}"
                break

            if response.status_code != 200:
                stats["error"] = f"page {page}: HTTP {response.status_code}"
                break

            payload = response.json() or {}
            rows = payload.get("gifts") or []
            if not rows:
                break

            collected.extend(rows)
            stats["pages"] = page
            total_pages = int(payload.get("totalPages") or page)
            page += 1
    finally:
        if owns_client:
            try:
                client.close()
            except Exception:
                pass

    stats["fetched"] = len(collected)
    if collected:
        merged = gift_catalog.merge_into_catalog(path, collected, source="euler")
        stats["added"] = merged["added"]
        stats["updated"] = merged["updated"]
    elif not stats["error"]:
        stats["error"] = "Euler catalog returned no gifts."

    return stats
