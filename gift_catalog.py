"""Union-merged TikTok gift catalog.

TikTok's ``/gift/list/`` only returns the **room panel** for the connected
stream and self-reports ``is_full_gift_data: False``. Verified against Khito's
live room on 2026-09-02: 701 gifts returned, 2783 exist. Region-locked gifts
(``Game Controller`` 6581/7569) and creator/event-exclusive gifts
(``Super GG`` 12988, ``KhitoFam`` 938882) never appear in it, so the dashboard
rendered them with no icon and no coin value even though the gift was received
and credited correctly.

This module owns ``data/available_gifts.json`` and merges three sources into it
as a **union that never drops a known gift**:

``panel``
    The room panel fetched on connect. Authoritative for price, real TikTok CDN
    icons, but incomplete.
``region``
    EulerStream regional gift blobs, unioned across regions. Adds region-locked
    gifts (1767 unique verified). Real TikTok CDN icons.
``event``
    Learned from live ``GiftEvent``s. The ONLY source that can ever know a
    creator-exclusive gift, because TikTok ships the gift struct with the event
    even when it is absent from every catalog.

The old code overwrote the file wholesale on every connect, which is why
learned entries kept vanishing. Every write here goes through
:func:`merge_into_catalog`.

The on-disk shape stays a **flat JSON list** because three existing consumers
read it directly: ``gift_card_studio/catalog.py``, ``static/script.js``
(``/api/gifts/available``), and ``minecraft_main.get_gift_icon``.
"""
from __future__ import annotations

import json
import os
import tempfile

# EulerStream's own image CDN rejects server-side fetches with
# 403 {"error":"Origin not allowed"} (verified 2026-09-02, with and without an
# api key, Origin and Referer headers). Storing one of those URLs would render a
# broken <img> in the dashboard, which is worse than an empty icon since the UI
# already hides empty icons. TikTok's own CDN serves fine.
_BLOCKED_ICON_HOSTS = ("assets.cdn.eulerstream.com",)

# Price/name trust order. A stale EulerStream snapshot must never downgrade a
# value that the live room panel or a real GiftEvent reported.
_SOURCE_RANK = {"euler": 0, "region": 1, "panel": 2, "event": 3}

_COIN_ANIMATION_FLOOR = 100


def _first_url(image) -> str:
    """First usable URL from a TikTok ImageModel-shaped dict.

    Also accepts a bare string, because the catalog's own persisted shape stores
    ``icon`` as a flat URL — a legacy cache round-tripping through here would
    otherwise lose every icon it had (Khito's live cache: 701 entries).
    """
    if isinstance(image, str):
        return image if image.startswith("http") else ""
    if not isinstance(image, dict):
        return ""
    for key in ("url_list", "urls", "urlList"):
        urls = image.get(key)
        if isinstance(urls, (list, tuple)) and urls:
            first = str(urls[0] or "")
            if first:
                return first
    for key in ("url", "uri"):
        value = image.get(key)
        if value and str(value).startswith("http"):
            return str(value)
    return ""


def _clean_icon(url) -> str:
    """Drop icon URLs we know cannot be fetched or rendered."""
    url = str(url or "")
    if not url.startswith("http"):
        return ""
    if any(host in url for host in _BLOCKED_ICON_HOSTS):
        return ""
    return url


def _as_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_entry(raw, source: str = "panel"):
    """Coerce any of the three source shapes into one catalog entry.

    Returns ``None`` when the row has no usable gift id, so callers can filter
    junk without a second validation pass.
    """
    if not isinstance(raw, dict):
        return None

    gift_id = _as_int(raw.get("id", raw.get("giftId")), 0)
    if gift_id <= 0:
        return None

    name = str(raw.get("name", raw.get("giftName", "")) or "").strip().lower()
    coins = _as_int(raw.get("diamond_count", raw.get("diamondCount")), 0)

    icon = _clean_icon(_first_url(raw.get("icon")) or _first_url(raw.get("image")))
    if not icon:
        # EulerStream's catalog route exposes a flat imageUri instead of an
        # ImageModel. Kept only when it points at TikTok's CDN.
        icon = _clean_icon(raw.get("imageUri", raw.get("image_uri", "")))

    primary_effect_id = str(raw.get("primary_effect_id", raw.get("primaryEffectId", "")) or "")
    resource_id = str(raw.get("resource_id", raw.get("resourceId", "")) or "")
    if primary_effect_id in ("0", "None"):
        primary_effect_id = ""
    if resource_id in ("0", "None"):
        resource_id = ""

    # Room-scope visibility. A learned GiftEvent is authoritative on both:
    # TikTok shipped that gift struct *into this room*, so the gift is both
    # deliverable here (``in_panel``) and actually received (``seen``) — the
    # only proof a creator-exclusive gift like Super GG really exists.
    in_panel = bool(raw.get("in_panel", source == "panel" or source == "event"))
    seen = bool(raw.get("seen", source == "event"))

    return {
        "id": gift_id,
        "name": name,
        "diamond_count": coins,
        "icon": icon,
        "primary_effect_id": primary_effect_id,
        "resource_id": resource_id,
        "has_animation": bool(coins >= _COIN_ANIMATION_FLOOR and (primary_effect_id or resource_id)),
        "source": source,
        "in_panel": in_panel,
        "seen": seen,
    }


def _better(existing: dict, incoming: dict) -> dict:
    """Field-wise merge of two entries for the same gift id.

    Never regresses: a present icon/name/price is not replaced by an empty or
    lower-trust one. Scope flags only ever turn ON: a gift seen once stays
    ``seen`` forever, and a gift that lost its panel slot keeps its
    ``in_panel`` flag until an explicit panel fetch re-evaluates it.
    """
    merged = dict(existing)
    old_rank = _SOURCE_RANK.get(existing.get("source", ""), 0)
    new_rank = _SOURCE_RANK.get(incoming.get("source", ""), 0)

    if incoming.get("icon") and not existing.get("icon"):
        merged["icon"] = incoming["icon"]
    elif incoming.get("icon") and new_rank >= old_rank:
        merged["icon"] = incoming["icon"]

    if incoming.get("name") and (not existing.get("name") or new_rank >= old_rank):
        merged["name"] = incoming["name"]

    incoming_coins = incoming.get("diamond_count") or 0
    if incoming_coins and (not existing.get("diamond_count") or new_rank >= old_rank):
        merged["diamond_count"] = incoming_coins

    for key in ("primary_effect_id", "resource_id"):
        if incoming.get(key) and not existing.get(key):
            merged[key] = incoming[key]

    if incoming.get("in_panel"):
        merged["in_panel"] = True
    if incoming.get("seen"):
        merged["seen"] = True

    if new_rank >= old_rank:
        merged["source"] = incoming.get("source", existing.get("source", ""))

    coins = merged.get("diamond_count") or 0
    merged["has_animation"] = bool(
        coins >= _COIN_ANIMATION_FLOOR
        and (merged.get("primary_effect_id") or merged.get("resource_id"))
    )
    return merged


def merge_entries(base, incoming):
    """Union ``incoming`` into ``base``. Returns ``(entries, stats)``.

    ``stats`` is ``{"added": n, "updated": n}`` so callers can log a one-line
    delta instead of dumping the catalog.
    """
    index = {}
    for entry in base or []:
        normalized = entry if "source" in entry else normalize_entry(entry, source="panel")
        if normalized:
            index[normalized["id"]] = normalized

    added = 0
    updated = 0
    for entry in incoming or []:
        if not entry:
            continue
        gift_id = entry["id"]
        current = index.get(gift_id)
        if current is None:
            index[gift_id] = entry
            added += 1
            continue
        merged = _better(current, entry)
        if merged != current:
            index[gift_id] = merged
            updated += 1

    entries = sorted(index.values(), key=lambda e: (e.get("diamond_count") or 0, e["id"]))
    return entries, {"added": added, "updated": updated}


def load_catalog(path):
    """Read the catalog. A missing or corrupt file is an empty catalog."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict) and entry.get("id")]


def save_catalog(path, entries):
    """Atomically replace the catalog file.

    Atomic because the bot writes it while Flask serves ``/api/gifts/available``
    from the same file; a partial write would surface as a corrupt catalog in
    the dashboard mid-stream.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=directory, prefix=".gifts-", suffix=".tmp", delete=False
    )
    try:
        with handle:
            json.dump(entries, handle, indent=2, ensure_ascii=False)
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def mark_panel_gifts(path, gift_ids):
    """Stamp ``in_panel=True`` on exactly ``gift_ids`` and clear it elsewhere.

    Called on each fresh panel fetch so ``in_panel`` reflects what TikTok can
    deliver to the room *right now*: a gift that dropped out of the panel (rotated
    out, region changed) loses its flag, while ``seen`` is untouched — receiving
    a gift is forever, panel membership is not. Returns the number of entries
    whose flag actually flipped.
    """
    wanted = {str(g) for g in (gift_ids or []) if str(g).strip()}
    entries = load_catalog(path)
    changed = 0
    for entry in entries:
        should = str(entry.get("id")) in wanted
        if bool(entry.get("in_panel")) != should:
            entry["in_panel"] = should
            changed += 1
    if changed:
        save_catalog(path, entries)
    return changed


def merge_into_catalog(path, raw_entries, source="panel"):
    """Normalize ``raw_entries``, union them into the catalog on disk, save.

    Writes only when something actually changed, so a reconnect that learns
    nothing costs one read.
    """
    normalized = [normalize_entry(entry, source=source) for entry in (raw_entries or [])]
    normalized = [entry for entry in normalized if entry]

    entries, stats = merge_entries(load_catalog(path), normalized)
    if stats["added"] or stats["updated"]:
        save_catalog(path, entries)
    return stats


def learn_gift(path, gift_id, name, diamond_count, icon_url=""):
    """Teach the catalog one gift seen in a live ``GiftEvent``.

    Returns ``True`` when the catalog changed. Never raises: this runs inside
    the ``GiftEvent`` handler, where an exception would break a live stream.
    """
    try:
        if _as_int(gift_id, 0) <= 0:
            return False
        stats = merge_into_catalog(
            path,
            [{
                "id": gift_id,
                "name": name,
                "diamond_count": diamond_count,
                "icon": {"url_list": [icon_url]} if icon_url else None,
            }],
            source="event",
        )
        return bool(stats["added"] or stats["updated"])
    except Exception:
        return False


def icon_for(path, gift_id):
    """Icon URL for ``gift_id``, or ``""``.

    Reads the file per call so a gift learned mid-stream is visible without a
    bot restart, matching the project rule that live settings and caches must
    never require a restart.
    """
    wanted = str(gift_id)
    for entry in load_catalog(path):
        if str(entry.get("id")) == wanted:
            return entry.get("icon", "") or ""
    return ""
