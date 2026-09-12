"""Bounds, enums, and coercion helpers for Gift Card Studio project data.

Pure module: no I/O, no imports outside the stdlib. Every bound lives here so
the model normalizer, the API layer, and the tests agree on one source of truth.
"""
from __future__ import annotations

import re
import unicodedata

# ---- Identity ------------------------------------------------------------
# Project ids become filenames, so they are deliberately narrow.
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_ID_LENGTH = 64
MAX_NAME_LENGTH = 120

# ---- Canvas --------------------------------------------------------------
MIN_CANVAS = 16
MAX_CANVAS = 7680
DEFAULT_CANVAS_WIDTH = 1920
DEFAULT_CANVAS_HEIGHT = 1080

# ---- Grid ----------------------------------------------------------------
MIN_ROWS = 1
MAX_ROWS = 20
MIN_COLUMNS = 1
MAX_COLUMNS = 20
MAX_CELLS_PER_PAGE = 100
MAX_GAP = 512
MAX_PADDING = 512

FIT_MODES = ("contain", "cover", "stretch")
DEFAULT_FIT = "contain"
FILL_ORDERS = ("row", "column")
DEFAULT_FILL_ORDER = "row"

# ---- Playback ------------------------------------------------------------
PLAYBACK_MODES = ("pages", "scroll")
DEFAULT_PLAYBACK_MODE = "pages"
MIN_PAGE_DURATION_MS = 100
MAX_PAGE_DURATION_MS = 600_000
DEFAULT_PAGE_DURATION_MS = 5_000

TRANSITION_TYPES = ("cut", "fade", "slide", "pixel_wipe")
DEFAULT_TRANSITION_TYPE = "pixel_wipe"
MIN_TRANSITION_MS = 0
MAX_TRANSITION_MS = 5_000
DEFAULT_TRANSITION_MS = 400

SCROLL_DIRECTIONS = ("left", "right", "up", "down")
DEFAULT_SCROLL_DIRECTION = "left"
MIN_SCROLL_SPEED = 1.0
MAX_SCROLL_SPEED = 2000.0
DEFAULT_SCROLL_SPEED = 60.0
MAX_EDGE_PAUSE_MS = 60_000

# ---- Structure limits ----------------------------------------------------
MAX_PAGES = 50
MAX_CARDS_PER_PAGE = MAX_CELLS_PER_PAGE
MAX_LAYERS_PER_CARD = 40
MAX_TEMPLATES = 100

# ---- Layers --------------------------------------------------------------
LAYER_TYPES = ("gift_icon", "action_icon", "image", "text", "shape")
TEXT_ROLES = ("main", "secondary", "amount", "duration", "custom")
DEFAULT_TEXT_ROLE = "custom"
TEXT_ALIGNS = ("left", "center", "right")
VERTICAL_ALIGNS = ("top", "middle", "bottom")
IMAGE_FITS = ("contain", "cover", "fill")
SHAPE_KINDS = ("panel", "pixel_border", "divider")
MAX_TEXT_LENGTH = 400
MIN_FONT_SIZE = 1
MAX_FONT_SIZE = 512
DEFAULT_FONT_SIZE = 32
DEFAULT_FONT_FAMILY = "Minecraft"

# ---- Card --------------------------------------------------------------
DEFAULT_CARD_WIDTH = 320
DEFAULT_CARD_HEIGHT = 400
MIN_CARD_SIZE = 8
MAX_CARD_SIZE = 4096

# ---- Colors ------------------------------------------------------------
HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
TRANSPARENT = "transparent"


class ValidationError(ValueError):
    """Raised when project data cannot be coerced into the schema."""


# ---- Coercion helpers ---------------------------------------------------

def clamp(value, low, high):
    """Clamp a numeric value into ``[low, high]``."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def coerce_int(value, default, low, high):
    """Best-effort int coercion, clamped. Falsy/invalid input yields default."""
    try:
        if isinstance(value, bool):
            raise TypeError
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return int(clamp(number, low, high))


def coerce_float(value, default, low, high):
    """Best-effort float coercion, clamped. Invalid input yields default."""
    try:
        if isinstance(value, bool):
            raise TypeError
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        return default
    return float(clamp(number, low, high))


def coerce_bool(value, default=False):
    """Coerce common JSON truthy/falsey spellings to bool."""
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off", ""):
            return False
        return bool(default)
    try:
        return bool(value)
    except Exception:
        return bool(default)


def coerce_choice(value, choices, default):
    """Return ``value`` when it is one of ``choices``, else ``default``."""
    if isinstance(value, str) and value in choices:
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in choices:
            return lowered
    return default


def coerce_text(value, default="", max_length=MAX_TEXT_LENGTH):
    """Coerce to a bounded single-value string, stripping control characters."""
    if value is None:
        return default
    if not isinstance(value, str):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        else:
            return default
    cleaned = "".join(
        ch for ch in value if ch in ("\n", "\t") or unicodedata.category(ch)[0] != "C"
    )
    return cleaned[:max_length]


def coerce_color(value, default=TRANSPARENT):
    """Accept ``transparent`` or a #RGB/#RGBA/#RRGGBB/#RRGGBBAA hex string."""
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.lower() == TRANSPARENT:
            return TRANSPARENT
        if HEX_COLOR.match(candidate):
            return candidate.lower()
    return default


def slugify_id(value, fallback="project"):
    """Turn arbitrary text into a filesystem-safe project id.

    Rejects nothing: this is the *generator*. Use :func:`is_safe_id` to
    validate ids that arrive from a client.
    """
    text = value if isinstance(value, str) else ""
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)[:MAX_ID_LENGTH]
    if not slug or not slug[0].isalnum():
        slug = (fallback + ("-" + slug if slug else ""))[:MAX_ID_LENGTH].strip("-")
    return slug or fallback


def is_safe_id(value) -> bool:
    """True when ``value`` is a project id we are willing to touch on disk."""
    if not isinstance(value, str):
        return False
    if value in (".", ".."):
        return False
    return bool(SAFE_ID.match(value))


def require_safe_id(value) -> str:
    """Return ``value`` if it is a safe id, else raise :class:`ValidationError`."""
    if not is_safe_id(value):
        raise ValidationError(f"unsafe project id: {value!r}")
    return value
