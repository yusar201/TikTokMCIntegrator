"""Gift Card Studio project model: normalize, default, bound, migrate.

Every project that enters the system — from a client PUT, from disk, from the
catalog drafter — goes through :func:`normalize_project`. That function is
total: it never raises on bad *values* (it clamps or defaults them) and only
raises :class:`~gift_card_studio.validation.ValidationError` on things that
cannot be repaired safely, i.e. an unsafe project id or a non-object payload.

That split matters. Design data arriving from a WebView2 editor is messy
(strings for numbers, nulls for objects, stale keys from an older build); the
model layer's job is to always hand the renderer/exporter something coherent.
Refusing the save would just lose the user's work mid-stream.

Pure module: stdlib only, no I/O.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .validation import (
    DEFAULT_CANVAS_HEIGHT,
    DEFAULT_CANVAS_WIDTH,
    DEFAULT_CARD_HEIGHT,
    DEFAULT_CARD_WIDTH,
    DEFAULT_FILL_ORDER,
    DEFAULT_FIT,
    DEFAULT_FONT_FAMILY,
    DEFAULT_FONT_SIZE,
    DEFAULT_PAGE_DURATION_MS,
    DEFAULT_PLAYBACK_MODE,
    DEFAULT_SCROLL_DIRECTION,
    DEFAULT_SCROLL_SPEED,
    DEFAULT_TEXT_ROLE,
    DEFAULT_TRANSITION_MS,
    DEFAULT_TRANSITION_TYPE,
    FILL_ORDERS,
    FIT_MODES,
    IMAGE_FITS,
    LAYER_TYPES,
    MAX_CANVAS,
    MAX_CARD_SIZE,
    MAX_COLUMNS,
    MAX_EDGE_PAUSE_MS,
    MAX_FONT_SIZE,
    MAX_GAP,
    MAX_LAYERS_PER_CARD,
    MAX_NAME_LENGTH,
    MAX_PADDING,
    MAX_PAGE_DURATION_MS,
    MAX_PAGES,
    MAX_ROWS,
    MAX_SCROLL_SPEED,
    MAX_TEMPLATES,
    MAX_TRANSITION_MS,
    MIN_CANVAS,
    MIN_CARD_SIZE,
    MIN_COLUMNS,
    MIN_FONT_SIZE,
    MIN_PAGE_DURATION_MS,
    MIN_ROWS,
    MIN_SCROLL_SPEED,
    MIN_TRANSITION_MS,
    PLAYBACK_MODES,
    SHAPE_KINDS,
    TEXT_ALIGNS,
    TEXT_ROLES,
    TRANSITION_TYPES,
    TRANSPARENT,
    VERTICAL_ALIGNS,
    ValidationError,
    coerce_bool,
    coerce_choice,
    coerce_color,
    coerce_float,
    coerce_int,
    coerce_text,
    is_safe_id,
    require_safe_id,
    slugify_id,
)

SCHEMA_VERSION = 1

# Keys we accept on a card's gift/action reference. Anything else is dropped so
# a stale client build can't smuggle unbounded blobs into the saved project.
GIFT_REF_KEYS = ("gift_id", "name", "icon", "icon_asset", "diamond_count", "category")
ACTION_REF_KEYS = ("gift_key", "commands", "intent", "confidence")


def utc_now_iso() -> str:
    """Timezone-aware UTC timestamp, second precision, ``Z`` suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    """Short unique id for a page/card/layer/template."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _ensure_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _ensure_list(value) -> list:
    return value if isinstance(value, list) else []


def _local_id(value, prefix: str) -> str:
    """Normalize an internal (non-filename) id: bounded text or a fresh one."""
    text = coerce_text(value, "", 64).strip()
    cleaned = "".join(ch for ch in text if ch.isalnum() or ch in "-_")
    return cleaned or new_id(prefix)


# ---- Canvas --------------------------------------------------------------

def normalize_canvas(raw) -> dict:
    raw = _ensure_dict(raw)
    return {
        "width": coerce_int(raw.get("width"), DEFAULT_CANVAS_WIDTH, MIN_CANVAS, MAX_CANVAS),
        "height": coerce_int(raw.get("height"), DEFAULT_CANVAS_HEIGHT, MIN_CANVAS, MAX_CANVAS),
        "background": coerce_color(raw.get("background"), TRANSPARENT),
        "safe_padding": coerce_int(raw.get("safe_padding"), 32, 0, MAX_PADDING),
    }


# ---- Playback ------------------------------------------------------------

def normalize_transition(raw, allow_none=False):
    """Normalize a transition. ``None`` means 'inherit the project default'."""
    if raw is None and allow_none:
        return None
    raw = _ensure_dict(raw)
    return {
        "type": coerce_choice(raw.get("type"), TRANSITION_TYPES, DEFAULT_TRANSITION_TYPE),
        "duration_ms": coerce_int(
            raw.get("duration_ms"), DEFAULT_TRANSITION_MS, MIN_TRANSITION_MS, MAX_TRANSITION_MS
        ),
    }


def normalize_playback(raw) -> dict:
    raw = _ensure_dict(raw)
    return {
        "mode": coerce_choice(raw.get("mode"), PLAYBACK_MODES, DEFAULT_PLAYBACK_MODE),
        "loop": coerce_bool(raw.get("loop"), True),
        "default_page_duration_ms": coerce_int(
            raw.get("default_page_duration_ms"),
            DEFAULT_PAGE_DURATION_MS,
            MIN_PAGE_DURATION_MS,
            MAX_PAGE_DURATION_MS,
        ),
        "default_transition": normalize_transition(raw.get("default_transition")),
        # Editor-only preview affordance; never consulted by the exporters.
        "reduce_motion_preview": coerce_bool(raw.get("reduce_motion_preview"), False),
    }


# ---- Grid / scroll -------------------------------------------------------

def normalize_grid(raw) -> dict:
    raw = _ensure_dict(raw)
    return {
        "rows": coerce_int(raw.get("rows"), 1, MIN_ROWS, MAX_ROWS),
        "columns": coerce_int(raw.get("columns"), 1, MIN_COLUMNS, MAX_COLUMNS),
        "gap_x": coerce_int(raw.get("gap_x"), 20, 0, MAX_GAP),
        "gap_y": coerce_int(raw.get("gap_y"), 20, 0, MAX_GAP),
        "padding": coerce_int(raw.get("padding"), 24, 0, MAX_PADDING),
        "fill_order": coerce_choice(raw.get("fill_order"), FILL_ORDERS, DEFAULT_FILL_ORDER),
        "fit": coerce_choice(raw.get("fit"), FIT_MODES, DEFAULT_FIT),
    }


def normalize_scroll(raw) -> dict:
    raw = _ensure_dict(raw)
    return {
        "enabled": coerce_bool(raw.get("enabled"), False),
        "direction": coerce_choice(raw.get("direction"), (
            "left", "right", "up", "down"), DEFAULT_SCROLL_DIRECTION),
        "speed_px_per_second": coerce_float(
            raw.get("speed_px_per_second"), DEFAULT_SCROLL_SPEED, MIN_SCROLL_SPEED, MAX_SCROLL_SPEED
        ),
        "loop": coerce_bool(raw.get("loop"), True),
        "item_gap": coerce_int(raw.get("item_gap"), 20, 0, MAX_GAP),
        "edge_pause_ms": coerce_int(raw.get("edge_pause_ms"), 0, 0, MAX_EDGE_PAUSE_MS),
    }


# ---- Layers --------------------------------------------------------------

def _normalize_layer_box(raw, layer) -> None:
    layer["x"] = coerce_float(raw.get("x"), 0.0, -MAX_CARD_SIZE, MAX_CARD_SIZE)
    layer["y"] = coerce_float(raw.get("y"), 0.0, -MAX_CARD_SIZE, MAX_CARD_SIZE)
    layer["width"] = coerce_float(raw.get("width"), 100.0, 0.0, MAX_CARD_SIZE)
    layer["height"] = coerce_float(raw.get("height"), 100.0, 0.0, MAX_CARD_SIZE)
    layer["rotation"] = coerce_float(raw.get("rotation"), 0.0, -360.0, 360.0)
    layer["opacity"] = coerce_float(raw.get("opacity"), 1.0, 0.0, 1.0)


def normalize_layer(raw, index=0) -> dict:
    raw = _ensure_dict(raw)
    layer_type = coerce_choice(raw.get("type"), LAYER_TYPES, "text")

    layer = {
        "id": _local_id(raw.get("id"), "layer"),
        "type": layer_type,
        "name": coerce_text(raw.get("name"), layer_type.replace("_", " ").title(), MAX_NAME_LENGTH),
        "visible": coerce_bool(raw.get("visible"), True),
        "locked": coerce_bool(raw.get("locked"), False),
        "z_index": coerce_int(raw.get("z_index"), index, 0, MAX_LAYERS_PER_CARD * 10),
    }
    _normalize_layer_box(raw, layer)

    if layer_type == "text":
        layer.update({
            "role": coerce_choice(raw.get("role"), TEXT_ROLES, DEFAULT_TEXT_ROLE),
            "text": coerce_text(raw.get("text"), ""),
            "font_family": coerce_text(raw.get("font_family"), DEFAULT_FONT_FAMILY, 80),
            "font_size": coerce_int(raw.get("font_size"), DEFAULT_FONT_SIZE, MIN_FONT_SIZE, MAX_FONT_SIZE),
            "font_weight": coerce_choice(raw.get("font_weight"), ("normal", "bold"), "normal"),
            "color": coerce_color(raw.get("color"), "#ffffff"),
            "align": coerce_choice(raw.get("align"), TEXT_ALIGNS, "center"),
            "vertical_align": coerce_choice(raw.get("vertical_align"), VERTICAL_ALIGNS, "middle"),
            "line_height": coerce_float(raw.get("line_height"), 1.2, 0.5, 4.0),
            "letter_spacing": coerce_float(raw.get("letter_spacing"), 0.0, -20.0, 20.0),
            "stroke_color": coerce_color(raw.get("stroke_color"), TRANSPARENT),
            "stroke_width": coerce_float(raw.get("stroke_width"), 0.0, 0.0, 32.0),
            "shadow": coerce_bool(raw.get("shadow"), False),
            "uppercase": coerce_bool(raw.get("uppercase"), False),
            # When enabled the renderer may shrink text to fit its box.
            "responsive_text": coerce_bool(raw.get("responsive_text"), False),
        })
    elif layer_type in ("image", "gift_icon", "action_icon"):
        layer.update({
            # Relative asset name resolved by the API layer; never a raw URL to
            # an arbitrary host at render time.
            "asset": coerce_text(raw.get("asset"), "", 200),
            "fit": coerce_choice(raw.get("fit"), IMAGE_FITS, "contain"),
            "pixelated": coerce_bool(raw.get("pixelated"), True),
        })
        if layer_type == "gift_icon":
            # Follow the card's linked gift unless the user pinned an override.
            layer["auto_link"] = coerce_bool(raw.get("auto_link"), True)
        if layer_type == "action_icon":
            layer["intent"] = coerce_text(raw.get("intent"), "", 64)
            layer["placeholder"] = coerce_bool(raw.get("placeholder"), True)
    else:  # shape
        layer.update({
            "kind": coerce_choice(raw.get("kind"), SHAPE_KINDS, "panel"),
            "fill": coerce_color(raw.get("fill"), "#1b1b1f"),
            "border_color": coerce_color(raw.get("border_color"), "#3a3a42"),
            "border_width": coerce_float(raw.get("border_width"), 2.0, 0.0, 64.0),
            "corner_radius": coerce_float(raw.get("corner_radius"), 0.0, 0.0, 256.0),
            # Stepped pixel corners instead of smooth radii (Khito's overlay
            # look). ``pixel_steps`` is the size of one step in canvas units;
            # ``pixel_tiers`` is how many steps make up the staircase. One tier
            # is a single notch; three reads as a proper Minecraft panel corner.
            "pixel_steps": coerce_int(raw.get("pixel_steps"), 0, 0, 16),
            "pixel_tiers": coerce_int(raw.get("pixel_tiers"), 1, 1, 8),
        })

    return layer


def normalize_layers(raw) -> list:
    layers = [normalize_layer(item, i) for i, item in enumerate(_ensure_list(raw))]
    layers = layers[:MAX_LAYERS_PER_CARD]
    layers.sort(key=lambda item: item["z_index"])
    for i, layer in enumerate(layers):
        layer["z_index"] = i
    return layers


# ---- Refs / cards --------------------------------------------------------

def _normalize_ref(raw, keys) -> dict:
    raw = _ensure_dict(raw)
    ref = {}
    for key in keys:
        if key not in raw:
            continue
        value = raw[key]
        if key == "commands":
            ref[key] = [coerce_text(c, "", 400) for c in _ensure_list(value)][:40]
        elif key == "diamond_count":
            ref[key] = coerce_int(value, 0, 0, 10_000_000)
        elif key == "confidence":
            ref[key] = coerce_float(value, 0.0, 0.0, 1.0)
        else:
            ref[key] = coerce_text(value, "", 300)
    return ref


def normalize_card(raw) -> dict:
    raw = _ensure_dict(raw)
    width = coerce_int(raw.get("width"), DEFAULT_CARD_WIDTH, MIN_CARD_SIZE, MAX_CARD_SIZE)
    height = coerce_int(raw.get("height"), DEFAULT_CARD_HEIGHT, MIN_CARD_SIZE, MAX_CARD_SIZE)
    layers = normalize_layers(raw.get("layers"))
    for layer in layers:
        if (layer["type"] == "action_icon"
                and layer.get("asset", "").startswith("/gift-studio-assets/action-")):
            layer["asset"] = ""
            layer["placeholder"] = True
    gift_ref = _normalize_ref(raw.get("gift_ref"), GIFT_REF_KEYS)
    return {
        "id": _local_id(raw.get("id"), "card"),
        "name": coerce_text(raw.get("name"), "", MAX_NAME_LENGTH),
        "width": width,
        "height": height,
        "gift_ref": gift_ref,
        "action_ref": _normalize_ref(raw.get("action_ref"), ACTION_REF_KEYS),
        "template_id": coerce_text(raw.get("template_id"), "", 64),
        # True once the user touched this card: the catalog importer must never
        # overwrite it (plan: "manual customizations survive catalog refresh").
        "customized": coerce_bool(raw.get("customized"), False),
        "layers": layers,
    }


# ---- Pages ---------------------------------------------------------------

def normalize_page(raw, index=0) -> dict:
    raw = _ensure_dict(raw)
    duration = raw.get("duration_ms")
    cards = [normalize_card(card) for card in _ensure_list(raw.get("cards"))]
    card_ids = []
    for value in _ensure_list(raw.get("card_ids")):
        card_id = _local_id(value, "card")
        if card_id not in card_ids:
            card_ids.append(card_id)
    if not card_ids:
        card_ids = [card["id"] for card in cards]
    return {
        "id": _local_id(raw.get("id"), "page"),
        "name": coerce_text(raw.get("name"), f"Page {index + 1}", MAX_NAME_LENGTH),
        # None = inherit playback.default_page_duration_ms
        "duration_ms": (
            None if duration is None
            else coerce_int(duration, DEFAULT_PAGE_DURATION_MS, MIN_PAGE_DURATION_MS, MAX_PAGE_DURATION_MS)
        ),
        "transition": normalize_transition(raw.get("transition"), allow_none=True),
        "grid": normalize_grid(raw.get("grid")),
        "scroll": normalize_scroll(raw.get("scroll")),
        "card_ids": card_ids[:MAX_PAGES * 100],
        "cards": cards[:MAX_PAGES * 100],
    }


def default_page(index=0) -> dict:
    return normalize_page({"name": f"Page {index + 1}"}, index)


# ---- Templates -----------------------------------------------------------

def normalize_template(raw) -> dict:
    raw = _ensure_dict(raw)
    return {
        "id": _local_id(raw.get("id"), "tpl"),
        "name": coerce_text(raw.get("name"), "Template", MAX_NAME_LENGTH),
        "card_width": coerce_int(raw.get("card_width"), DEFAULT_CARD_WIDTH, MIN_CARD_SIZE, MAX_CARD_SIZE),
        "card_height": coerce_int(raw.get("card_height"), DEFAULT_CARD_HEIGHT, MIN_CARD_SIZE, MAX_CARD_SIZE),
        "layers": normalize_layers(raw.get("layers")),
    }


# ---- Project -------------------------------------------------------------

def normalize_project(raw, project_id=None) -> dict:
    """Coerce ``raw`` into a complete, bounded, schema-current project.

    ``project_id`` overrides/supplies the id (used by the storage layer, which
    owns the filename). Raises :class:`ValidationError` only for a non-object
    payload or an id that is unsafe to put on disk.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValidationError("project payload must be an object")

    raw = migrate_project(raw)

    candidate = project_id if project_id is not None else raw.get("id")
    if candidate is None or candidate == "":
        candidate = slugify_id(raw.get("name"), "project")
    elif not is_safe_id(candidate):
        # An id we generated ourselves can be slugified; one a client asserted
        # must be rejected loudly so we never write outside the project dir.
        if project_id is not None:
            raise ValidationError(f"unsafe project id: {candidate!r}")
        candidate = slugify_id(candidate, "project")
    identifier = require_safe_id(candidate)

    pages = [normalize_page(page, i) for i, page in enumerate(_ensure_list(raw.get("pages")))]
    pages = pages[:MAX_PAGES]
    if not pages:
        pages = [default_page(0)]

    library = []
    by_id = {}
    for raw_card in _ensure_list(raw.get("card_library")):
        card = normalize_card(raw_card)
        if card["id"] not in by_id:
            by_id[card["id"]] = card
            library.append(card)
    for page in pages:
        for card in page.get("cards") or []:
            existing = by_id.get(card["id"])
            if existing is None:
                by_id[card["id"]] = card
                library.append(card)
            elif card.get("customized") and not existing.get("customized"):
                # Legacy clients edited full page cards before the global library
                # existed. Their customized copy is authoritative during migration.
                by_id[card["id"]] = card
                library[library.index(existing)] = card
        page["card_ids"] = [card_id for card_id in page.get("card_ids") or [] if card_id in by_id]
        page["cards"] = [by_id[card_id] for card_id in page["card_ids"]]

    templates = [normalize_template(t) for t in _ensure_list(raw.get("templates"))][:MAX_TEMPLATES]

    return {
        "schema_version": SCHEMA_VERSION,
        "id": identifier,
        "name": coerce_text(raw.get("name"), identifier, MAX_NAME_LENGTH) or identifier,
        "canvas": normalize_canvas(raw.get("canvas")),
        "playback": normalize_playback(raw.get("playback")),
        "card_library": library,
        "pages": pages,
        "templates": templates,
        "updated_at": coerce_text(raw.get("updated_at"), utc_now_iso(), 40) or utc_now_iso(),
    }


def new_project(name="Untitled Project", project_id=None, **overrides) -> dict:
    """Create a fresh single-page project."""
    payload = {"name": name, "pages": [default_page(0)]}
    payload.update(overrides)
    return normalize_project(payload, project_id or slugify_id(name, "project"))


def touch(project: dict) -> dict:
    """Stamp ``updated_at``. Mutates and returns the same dict."""
    project["updated_at"] = utc_now_iso()
    return project


# ---- Migration -----------------------------------------------------------

def migrate_project(raw: dict) -> dict:
    """Bring an older on-disk payload up to :data:`SCHEMA_VERSION`.

    v1 is the first schema, so there is nothing to rewrite yet; this is the
    documented seam so a future v2 has one obvious place to live and old files
    are never silently reinterpreted under new key meanings.
    """
    version = coerce_int(raw.get("schema_version"), SCHEMA_VERSION, 0, 1000)
    if version >= SCHEMA_VERSION:
        return raw
    migrated = dict(raw)
    # while version < SCHEMA_VERSION: apply _migrate_v{n}_to_v{n+1}
    migrated["schema_version"] = SCHEMA_VERSION
    return migrated


# ---- Derived helpers ----------------------------------------------------

def page_duration_ms(page: dict, playback: dict) -> int:
    """Effective duration for a page, resolving the inherit-default case."""
    explicit = page.get("duration_ms")
    if explicit is None:
        return int(playback.get("default_page_duration_ms", DEFAULT_PAGE_DURATION_MS))
    return int(explicit)


def page_transition(page: dict, playback: dict) -> dict:
    """Effective transition for a page, resolving the inherit-default case."""
    transition = page.get("transition") or playback.get("default_transition")
    if isinstance(transition, dict):
        return transition
    return normalize_transition(None) or {}


def effective_transition_ms(page: dict, previous_page: dict | None, playback: dict) -> int:
    """Transition duration clamped to half the shorter adjacent page duration.

    Plan rule: a transition may never eat more than half of either neighbour,
    otherwise a 400ms wipe on a 300ms page would never resolve.
    """
    transition = page_transition(page, playback)
    requested = int(transition.get("duration_ms", 0))
    if transition.get("type") == "cut":
        return 0
    limit = page_duration_ms(page, playback)
    if previous_page is not None:
        limit = min(limit, page_duration_ms(previous_page, playback))
    return max(0, min(requested, limit // 2))


def project_duration_ms(project: dict) -> int:
    """Total loop length: page durations only (transitions overlap pages)."""
    playback = project.get("playback") or {}
    return sum(page_duration_ms(page, playback) for page in project.get("pages") or [])


def summarize_project(project: dict) -> dict:
    """Compact listing payload — no page/card/layer bodies."""
    pages = project.get("pages") or []
    return {
        "id": project.get("id"),
        "name": project.get("name"),
        "schema_version": project.get("schema_version", SCHEMA_VERSION),
        "updated_at": project.get("updated_at"),
        "page_count": len(pages),
        "card_count": sum(len(page.get("cards") or []) for page in pages),
        "canvas": project.get("canvas"),
        "playback_mode": (project.get("playback") or {}).get("mode", DEFAULT_PLAYBACK_MODE),
    }
