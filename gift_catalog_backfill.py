"""Recover gifts from local history that no catalog knows about.

``Super GG`` (12988) is in no catalog anywhere — not TikTok's room panel, not
any of EulerStream's 20 regional panels, not Euler's 2783-row catalogue (HTTP
404). Verified 2026-09-02. Yet Khito received it 25 times for 2500 coins.

That makes local history a legitimate catalog source, and the only one that can
recover a gift retroactively:

``gift_log.json``
    Rolling dashboard log. Carries the icon URL that TikTok shipped with the
    event, so it can restore a real image.
``points.db`` → ``gift_ledger``
    Every credited gift ever. No icon, but proves id, name and price. Rows are
    ``repeat_count * unit_price``, so the GCD of a gift's observed totals is the
    best available unit-price estimate — exact as soon as one single-send row
    exists, which is the common case.

Both feed in at the lowest trust rank (``euler``), so a real panel, region sync
or future GiftEvent always wins on price and name.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3

import gift_catalog

# History is the weakest evidence we have. gift_catalog._SOURCE_RANK ranks
# "euler" lowest, so reusing it here means any live source overrides history.
_HISTORY_SOURCE = "euler"


def _merge(path, rows):
    if not rows:
        return {"added": 0, "updated": 0}
    return gift_catalog.merge_into_catalog(path, rows, source=_HISTORY_SOURCE)


def backfill_from_gift_log(catalog_path, gift_log_path):
    """Recover gifts (with icons) from the rolling gift log."""
    try:
        with open(gift_log_path, "r", encoding="utf-8") as handle:
            entries = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {"added": 0, "updated": 0}

    if not isinstance(entries, list):
        return {"added": 0, "updated": 0}

    best = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            gift_id = int(entry.get("gift_id") or 0)
        except (TypeError, ValueError):
            continue
        if gift_id <= 0:
            continue

        icon = str(entry.get("icon") or "")
        # diamond_count is the unit price; total_coins is repeat * price.
        price = entry.get("diamond_count") or 0
        try:
            price = int(price)
        except (TypeError, ValueError):
            price = 0

        row = {
            "id": gift_id,
            "name": entry.get("gift_name") or "",
            "diamond_count": price,
            "icon": icon,
        }
        current = best.get(gift_id)
        # Prefer the entry that actually carries an icon.
        if current is None or (icon and not current.get("icon")):
            best[gift_id] = row

    return _merge(catalog_path, list(best.values()))


def backfill_from_ledger(catalog_path, points_db_path):
    """Recover gift ids/names/prices from the points ledger."""
    if not os.path.exists(points_db_path):
        return {"added": 0, "updated": 0}

    try:
        conn = sqlite3.connect(f"file:{points_db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return {"added": 0, "updated": 0}

    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(gift_ledger)")}
        if not columns:
            return {"added": 0, "updated": 0}

        # kind='manual' rows are operator coin repairs, not gifts. Older
        # databases predate the column entirely.
        where = "WHERE gift_id IS NOT NULL AND gift_id != ''"
        if "kind" in columns:
            where += " AND kind = 'gift'"

        rows = conn.execute(
            f"SELECT gift_id, gift_name, coins FROM gift_ledger {where}"
        ).fetchall()
    except sqlite3.Error:
        return {"added": 0, "updated": 0}
    finally:
        conn.close()

    seen = {}
    for gift_id, gift_name, coins in rows:
        try:
            gid = int(gift_id)
        except (TypeError, ValueError):
            continue
        if gid <= 0:
            continue
        try:
            coins = int(coins or 0)
        except (TypeError, ValueError):
            coins = 0

        record = seen.setdefault(gid, {"name": gift_name or "", "unit": 0})
        if gift_name and not record["name"]:
            record["name"] = gift_name
        if coins > 0:
            # Ledger coins are repeat_count * unit_price. GCD across sightings
            # converges on the unit price and is exact once any 1x send exists.
            record["unit"] = math.gcd(record["unit"], coins)

    return _merge(catalog_path, [
        {"id": gid, "name": rec["name"], "diamond_count": rec["unit"], "icon": ""}
        for gid, rec in seen.items()
    ])


def backfill_all(catalog_path, gift_log_path, points_db_path):
    """Ledger first (ids/prices), then the log so its icons land on top."""
    ledger = backfill_from_ledger(catalog_path, points_db_path)
    log = backfill_from_gift_log(catalog_path, gift_log_path)
    return {
        "added": ledger["added"] + log["added"],
        "updated": ledger["updated"] + log["updated"],
        "ledger": ledger,
        "gift_log": log,
    }
