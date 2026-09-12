"""Read the configured gift catalog and draft cards from it.

Reads three existing sources, **without mutating any of them**:

* ``config.yml`` -> ``Gifts`` (id/name -> command list), ``GiftNames``,
  ``GiftCategories``, ``GiftDescriptions``
* ``data/available_gifts.json`` -> TikTok catalog metadata (icon, diamond_count)
* ``assets/gift_assets/manifest.json`` -> locally cached icon files

Two real-config shapes the join has to survive (verified against Khito's live
config, 2026-08-28):

1. ``Gifts`` keys are usually numeric TikTok ids (``"5487"``) but some are legacy
   gift *names* (``"bff necklace"``, ``"cow"``). Both must resolve.
2. ``GlobalActions`` is a pseudo-key holding actions that apply to every gift —
   it is not a gift and must never become a card.

Import cost stays low: no Pillow, no network, no Flask.
"""
from __future__ import annotations

import json
import os

from . import classifier, models

# Keys inside config["Gifts"] that are not gifts.
PSEUDO_GIFT_KEYS = {"GlobalActions", "globalactions"}

AVAILABLE_GIFTS_FILENAME = "available_gifts.json"
ICON_MANIFEST_RELPATH = os.path.join("gift_assets", "manifest.json")

# Draft-diff verdicts surfaced by the bulk-review screen.
STATUS_NEW = "new"
STATUS_CHANGED = "changed"
STATUS_UNCHANGED = "unchanged"
STATUS_MISSING = "missing"


def normalize_key(value) -> str:
    """Canonical lookup key for a gift: lowercased, trimmed string."""
    if value is None:
        return ""
    return str(value).strip().lower()


def is_gift_key(key) -> bool:
    """False for pseudo-keys like ``GlobalActions``."""
    return normalize_key(key) not in {normalize_key(k) for k in PSEUDO_GIFT_KEYS}


# ---- Source loading ------------------------------------------------------

def load_available_gifts(data_dir: str) -> list[dict]:
    """Cached TikTok gift catalog. Missing/corrupt file yields an empty list.

    Never triggers a network refresh: the plan requires catalog import to be a
    local, explicit, offline-safe operation.
    """
    path = os.path.join(data_dir, AVAILABLE_GIFTS_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        return []
    return [entry for entry in raw if isinstance(entry, dict)] if isinstance(raw, list) else []


def load_icon_manifest(assets_dir: str) -> dict:
    """Locally cached gift icon manifest keyed by gift id string."""
    path = os.path.join(assets_dir, ICON_MANIFEST_RELPATH)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def index_available_gifts(available: list[dict]) -> dict:
    """Index catalog entries by both id and lowercased name.

    One entry appears under two keys so a legacy name-keyed config row and a
    modern id-keyed row both resolve to the same metadata.
    """
    index: dict[str, dict] = {}
    for entry in available or []:
        gift_id = entry.get("id")
        if gift_id is not None:
            index.setdefault(normalize_key(gift_id), entry)
        name = entry.get("name")
        if name:
            index.setdefault(normalize_key(name), entry)
    return index


# ---- Join ----------------------------------------------------------------

def _commands_for(raw) -> list[str]:
    """Normalize legacy strings and redesigned typed Minecraft actions."""
    values = [raw] if isinstance(raw, (str, dict)) else raw if isinstance(raw, list) else []
    commands = []
    for value in values:
        if isinstance(value, str) and value.strip():
            commands.append(value)
        elif isinstance(value, dict):
            command = value.get("command")
            action_type = str(value.get("type") or "minecraft").lower()
            if action_type == "minecraft" and isinstance(command, str) and command.strip():
                commands.append(command)
    return commands


# Still-image extensions a rasterizer can actually decode. The app's existing
# gift-asset cache stores *animations* (mp4/webm) for the live overlays, and
# those are useless as a card icon — resvg draws nothing and the badge comes out
# empty. Anything not on this list is treated as "no local still image".
RASTERIZABLE_ICON_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def is_rasterizable_icon(url) -> bool:
    """True if ``url`` names a still image an exporter can decode."""
    if not isinstance(url, str) or not url.strip():
        return False
    path = url.split("?", 1)[0].split("#", 1)[0].lower()
    return path.endswith(RASTERIZABLE_ICON_EXTENSIONS)


def _icon_for(gift_id, catalog_entry, manifest) -> dict:
    """Resolve the best icon reference available for a gift.

    Prefers a locally cached **still image** (survives TikTok CDN URLs expiring)
    and falls back to the remote URL.

    The local-first preference must be extension-aware: ``manifest.json`` is the
    live overlays' animation cache, so ``local_url`` is frequently
    ``/gift_assets/gift_5655.mp4``. Preferring that unconditionally pointed every
    exported gift badge at a video the rasterizer silently ignored — the icon was
    "present" in the SVG and blank in the PNG.
    """
    entry = manifest.get(str(gift_id)) if gift_id is not None else None
    raw_local = (entry or {}).get("local_url") or ""
    local_url = raw_local if is_rasterizable_icon(raw_local) else ""
    remote = (catalog_entry or {}).get("icon") or ""
    return {
        "icon": local_url or remote,
        "icon_local": local_url,
        "icon_remote": remote,
        # Recorded so the UI can explain *why* a gift needs caching rather than
        # just reporting it as missing.
        "icon_local_unusable": raw_local if (raw_local and not local_url) else "",
        "icon_missing": not (local_url or remote),
    }


def build_catalog(config: dict, data_dir: str, assets_dir: str) -> list[dict]:
    """Join configured gifts to catalog metadata + classification.

    Returns one entry per configured gift, ordered by coin value then name so
    the review screen reads like Khito's own gift ladder. Read-only.
    """
    config = config or {}
    gifts = config.get("Gifts") or {}
    names = config.get("GiftNames") or {}
    categories = config.get("GiftCategories") or {}
    descriptions = config.get("GiftDescriptions") or {}

    index = index_available_gifts(load_available_gifts(data_dir))
    manifest = load_icon_manifest(assets_dir)

    entries = []
    for key, raw_commands in gifts.items():
        if not is_gift_key(key):
            continue

        commands = _commands_for(raw_commands)
        configured_name = names.get(key) or ""
        lookup = index.get(normalize_key(key)) or index.get(normalize_key(configured_name)) or {}

        gift_id = lookup.get("id", key if str(key).isdigit() else None)
        display_name = configured_name or lookup.get("name") or str(key)
        category = categories.get(key) or ""
        classification = classifier.classify_actions(commands)
        description = str(descriptions.get(key) or "").strip()
        # Visible card text is editorial content owned by GiftDescriptions.
        # Commands still classify the action and resolve artwork, but never
        # author or override what viewers read.
        text = {"main": description, "secondary": ""}

        entry = {
            "key": str(key),
            "gift_id": str(gift_id) if gift_id is not None else "",
            "name": display_name,
            "category": category,
            "description": description,
            "diamond_count": lookup.get("diamond_count", 0) or 0,
            "has_animation": bool(lookup.get("has_animation")),
            "commands": commands,
            "intent": classification["intent"],
            "confidence": classification["confidence"],
            "label": classification["label"],
            "suggested_action_icon": classifier.suggest_action_icon(classification["intent"]),
            "suggested_text": text,
            "high_confidence": classifier.is_high_confidence(classification),
            "in_tiktok_catalog": bool(lookup),
        }
        entry.update(_icon_for(gift_id, lookup, manifest))
        entries.append(entry)

    entries.sort(key=lambda item: (item["diamond_count"], item["name"].lower()))
    return entries


def catalog_stats(entries: list[dict]) -> dict:
    """Counts the review screen shows before the user imports anything."""
    entries = entries or []
    return {
        "total": len(entries),
        "high_confidence": sum(1 for e in entries if e["high_confidence"]),
        "needs_review": sum(1 for e in entries if not e["high_confidence"]),
        "missing_icon": sum(1 for e in entries if e["icon_missing"]),
        "not_in_catalog": sum(1 for e in entries if not e["in_tiktok_catalog"]),
        "intents": _count_by(entries, "intent"),
    }


def _count_by(entries, field) -> dict:
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.get(field, "")] = counts.get(entry.get(field, ""), 0) + 1
    return dict(sorted(counts.items()))


# ---- Draft card generation ----------------------------------------------

# Square by default: the cards read as icon tiles in a row, and a square cell
# wastes no vertical space in a banner-shaped canvas.
DEFAULT_DRAFT_CARD_WIDTH = 320
DEFAULT_DRAFT_CARD_HEIGHT = 320

# Gift badge size as a share of the card's short side, when an action icon is
# present and takes the centre. Big enough to recognize the gift, small enough
# to stay secondary.
BADGE_SHARE = 0.30

# Vertical overlap between the badge and the hero icon, as a share of the badge
# height. The badge sits at the bottom-left and is drawn on top, so this is how
# far its upper part covers the hero's lower-left corner. A slight overlap ties
# the two into one unit; full coverage would look like a mistake.
BADGE_OVERLAP_SHARE = 0.35


def draft_card(entry: dict, card_width=DEFAULT_DRAFT_CARD_WIDTH,
               card_height=DEFAULT_DRAFT_CARD_HEIGHT,
               include_action_icon=True, include_secondary_text=False) -> dict:
    """Build a normalized card from one catalog entry.

    Icon hierarchy depends on whether the card has an action icon:

    * **With an action icon** — the *action* is the hero: it fills the centre,
      because what the gift does on stream is the information a viewer needs.
      The gift icon drops to a corner badge at the bottom-left, deliberately
      overlapping the action icon a little so the two read as one unit rather
      than as two separate pictures.
    * **Without one** — the gift icon is the hero and fills the centre itself.

    The badge draws above the hero (higher ``z_index``) so the overlap resolves
    gift-over-action; the reverse would clip the badge.

    Coin category is omitted by default (``include_secondary_text=True`` restores
    it) since the icons already carry the identity.
    """
    text = entry.get("suggested_text") or {}
    secondary = (text.get("secondary") or "") if include_secondary_text else ""
    has_action = bool(include_action_icon)

    # Proportional to the card so any size/aspect stays balanced.
    short_side = min(card_width, card_height)
    pad = round(short_side * 0.055)
    border = max(2, round(short_side * 0.0125))
    inset = pad + border
    label_height = round(card_height * 0.17)
    secondary_height = round(card_height * 0.11) if secondary else 0

    # Bottom of the icon band — everything below this belongs to the text.
    band_bottom = card_height - inset - label_height - secondary_height
    hero_top = inset
    badge = max(8, round(short_side * BADGE_SHARE)) if has_action else 0

    if has_action:
        # The badge hangs below the hero, overlapping it by a set fraction of
        # the badge height, and the pair together fills the band. Solving for
        # the hero keeps that proportion true at any card size.
        overlap = badge * BADGE_OVERLAP_SHARE
        hero_bottom = band_bottom - badge + overlap
        badge_top = hero_bottom - overlap
    else:
        hero_bottom = band_bottom
        badge_top = 0.0

    hero_size = max(8, min(card_width - 2 * inset, hero_bottom - hero_top))
    hero_x = (card_width - hero_size) / 2
    text_top = band_bottom

    layers = [
        {
            "type": "shape",
            "name": "Panel",
            "kind": "pixel_border",
            "x": 0, "y": 0, "width": card_width, "height": card_height,
            "fill": "#16161a",
            "border_color": "#3a3a42",
            "border_width": border,
            # Three-tier staircase: reads as a Minecraft panel corner rather
            # than a chamfer. Step size scales with the card.
            "pixel_steps": max(2, round(short_side * 0.02)),
            "pixel_tiers": 3,
            "z_index": 0,
        },
    ]

    hero_layer = {
        "name": "Action Icon" if has_action else "Gift Icon",
        "x": hero_x,
        "y": hero_top,
        "width": hero_size,
        "height": hero_size,
        "fit": "contain",
        "z_index": 10,
    }
    if has_action:
        hero_layer.update({
            "type": "action_icon",
            "intent": entry.get("intent") or "",
            "asset": "",
            "placeholder": True,
        })
    else:
        hero_layer.update({
            "type": "gift_icon",
            "auto_link": True,
            "asset": entry.get("icon") or "",
        })
    layers.append(hero_layer)

    if has_action:
        layers.append({
            "type": "gift_icon",
            "name": "Gift Icon",
            "auto_link": True,
            "asset": entry.get("icon") or "",
            "x": inset,
            "y": badge_top,
            "width": badge,
            "height": badge,
            "fit": "contain",
            "z_index": 20,
        })

    layers.append({
        "type": "text",
        "name": "Main Text",
        "role": "main",
        "text": text.get("main") or "",
        "x": inset,
        "y": text_top,
        "width": card_width - 2 * inset,
        "height": label_height,
        "font_size": round(label_height * 0.72),
        "align": "center",
        "color": "#ffffff",
        "responsive_text": True,
        "z_index": 30,
    })

    if secondary:
        layers.append({
            "type": "text",
            "name": "Secondary Text",
            "role": "secondary",
            "text": secondary,
            "x": inset,
            "y": text_top + label_height,
            "width": card_width - 2 * inset,
            "height": secondary_height,
            "font_size": round(secondary_height * 0.7),
            "align": "center",
            "color": "#ffd479",
            "responsive_text": True,
            "z_index": 40,
        })

    return models.normalize_card({
        "name": entry.get("name") or entry.get("key") or "Card",
        "width": card_width,
        "height": card_height,
        "gift_ref": {
            "gift_id": entry.get("gift_id") or "",
            "name": entry.get("name") or "",
            "icon": entry.get("icon") or "",
            "diamond_count": entry.get("diamond_count") or 0,
            "category": entry.get("category") or "",
        },
        "action_ref": {
            "gift_key": entry.get("key") or "",
            "commands": entry.get("commands") or [],
            "intent": entry.get("intent") or "",
            "confidence": entry.get("confidence") or 0.0,
        },
        "customized": False,
        "layers": layers,
    })


def draft_cards(entries, **kwargs) -> list[dict]:
    """Draft a card per catalog entry, preserving catalog order."""
    return [draft_card(entry, **kwargs) for entry in entries or []]


# ---- Refresh diff --------------------------------------------------------

def _card_gift_key(card: dict) -> str:
    """Stable identity for matching an existing card to a catalog entry."""
    action_ref = card.get("action_ref") or {}
    gift_ref = card.get("gift_ref") or {}
    return normalize_key(action_ref.get("gift_key") or gift_ref.get("gift_id") or "")


def existing_cards_by_key(project: dict) -> dict:
    """Map gift key -> (page index, card) for every card already in a project."""
    found: dict[str, tuple[int, dict]] = {}
    for card in project.get("card_library") or []:
        key = _card_gift_key(card)
        if key:
            found.setdefault(key, (-1, card))
    for page_index, page in enumerate(project.get("pages") or []):
        for card in page.get("cards") or []:
            key = _card_gift_key(card)
            if key:
                found.setdefault(key, (page_index, card))
    return found


def diff_catalog(project: dict, entries: list[dict]) -> dict:
    """Compare a saved project against a freshly built catalog.

    Verdicts:
      * ``new``       — catalog gift with no card yet
      * ``changed``   — the gift's commands/label moved since the card was drafted
      * ``unchanged`` — card still matches the catalog
      * ``missing``   — card whose gift is no longer configured

    A ``changed`` entry on a card the user customized is reported with
    ``protected: True``: the importer must surface it but never overwrite it.
    """
    existing = existing_cards_by_key(project or {})
    seen: set[str] = set()
    buckets: dict[str, list[dict]] = {
        STATUS_NEW: [], STATUS_CHANGED: [], STATUS_UNCHANGED: [], STATUS_MISSING: []
    }

    for entry in entries or []:
        key = normalize_key(entry.get("key"))
        seen.add(key)
        match = existing.get(key)
        if match is None:
            buckets[STATUS_NEW].append({"key": entry.get("key"), "entry": entry})
            continue

        _, card = match
        action_ref = card.get("action_ref") or {}
        commands_changed = list(action_ref.get("commands") or []) != list(entry.get("commands") or [])
        intent_changed = (action_ref.get("intent") or "") != (entry.get("intent") or "")
        main_layer = next((layer for layer in card.get("layers") or [] if layer.get("role") == "main"), {})
        description_changed = (main_layer.get("text") or "") != (entry.get("description") or "")
        status = STATUS_CHANGED if (commands_changed or intent_changed or description_changed) else STATUS_UNCHANGED
        buckets[status].append({
            "key": entry.get("key"),
            "entry": entry,
            "card_id": card.get("id"),
            "protected": bool(card.get("customized")),
            "commands_changed": commands_changed,
            "intent_changed": intent_changed,
            "description_changed": description_changed,
        })

    for key, (page_index, card) in existing.items():
        if key not in seen:
            buckets[STATUS_MISSING].append({
                "key": key,
                "card_id": card.get("id"),
                "page_index": page_index,
                "name": card.get("name") or "",
                "protected": bool(card.get("customized")),
            })

    return {
        "new": buckets[STATUS_NEW],
        "changed": buckets[STATUS_CHANGED],
        "unchanged": buckets[STATUS_UNCHANGED],
        "missing": buckets[STATUS_MISSING],
        "counts": {status: len(items) for status, items in buckets.items()},
    }


def apply_catalog_import(project: dict, entries: list[dict], keys=None,
                         refresh_changed=True, assign_to_page=True, **draft_kwargs) -> dict:
    """Add/refresh cards from the catalog. Returns ``(project, report)`` data.

    Rules, straight from the plan:
      * customized cards are never overwritten
      * new cards enter the global library; page assignment is always explicit
      * a subset can be imported via ``keys``
    """
    project = models.normalize_project(project)
    selected = None if keys is None else {normalize_key(k) for k in keys}
    diff = diff_catalog(project, entries)
    existing = existing_cards_by_key(project)

    added, refreshed, skipped = [], [], []

    for item in diff["new"]:
        key = normalize_key(item["key"])
        if selected is not None and key not in selected:
            continue
        card = draft_card(item["entry"], **draft_kwargs)
        project.setdefault("card_library", []).append(card)
        if assign_to_page:
            project["pages"][-1].setdefault("card_ids", []).append(card["id"])
        added.append(item["key"])

    if refresh_changed:
        for item in diff["changed"]:
            key = normalize_key(item["key"])
            if selected is not None and key not in selected:
                continue
            if item["protected"]:
                skipped.append(item["key"])
                continue
            match = existing.get(key)
            if match is None:
                continue
            _, card = match
            fresh = draft_card(item["entry"], **draft_kwargs)
            # Keep the card's identity and position; replace generated content.
            fresh["id"] = card.get("id") or fresh["id"]
            for i, existing_card in enumerate(project.get("card_library") or []):
                if existing_card is card or existing_card.get("id") == fresh["id"]:
                    project["card_library"][i] = fresh
                    break
            refreshed.append(item["key"])

    models.touch(project)
    return {
        "project": models.normalize_project(project),
        "added": added,
        "refreshed": refreshed,
        "skipped_customized": skipped,
        "diff_counts": diff["counts"],
    }
