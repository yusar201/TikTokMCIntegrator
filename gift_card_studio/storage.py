"""On-disk persistence for Gift Card Studio projects and uploaded assets.

Layout (under ``paths.DATA_DIR`` in dev, the release folder when frozen)::

    data/gift_card_studio/
      projects/<project-id>.json
      assets/<asset-name>

Guarantees:

* **Atomic saves.** Write to ``<file>.tmp`` then ``os.replace``, so a crash or a
  concurrent read never observes a half-written project. The dashboard and bot
  are separate processes; a torn design file would be silently lossy.
* **Containment.** Every path is derived from a validated id/name and then
  re-checked with ``os.path.realpath`` against the root. ``../`` and absolute
  paths cannot escape, symlinked or not.
* **Lazy import.** This module imports no rendering or export dependency, so it
  stays cheap to import from a request handler.
"""
from __future__ import annotations

import json
import os
import re

import paths

from . import models
from .validation import (
    ValidationError,
    is_safe_id,
    require_safe_id,
    slugify_id,
)

ROOT_DIRNAME = "gift_card_studio"
PROJECTS_DIRNAME = "projects"
ASSETS_DIRNAME = "assets"

# Uploaded asset filenames: one dot, conservative charset, bounded length.
SAFE_ASSET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
ALLOWED_ASSET_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")

MAX_PROJECT_BYTES = 8 * 1024 * 1024  # a design project is text; 8MB is generous


# ---- Roots ---------------------------------------------------------------

def studio_root(data_dir: str | None = None) -> str:
    return os.path.join(data_dir or paths.DATA_DIR, ROOT_DIRNAME)


def projects_dir(data_dir: str | None = None) -> str:
    return os.path.join(studio_root(data_dir), PROJECTS_DIRNAME)


def assets_dir(data_dir: str | None = None) -> str:
    return os.path.join(studio_root(data_dir), ASSETS_DIRNAME)


def ensure_dirs(data_dir: str | None = None) -> str:
    """Create the studio directories on demand. Returns the studio root.

    Called from request handlers, never at import time — an unopened Studio
    should not create folders in a stream-critical process.
    """
    root = studio_root(data_dir)
    for directory in (root, projects_dir(data_dir), assets_dir(data_dir)):
        os.makedirs(directory, exist_ok=True)
    return root


# ---- Containment ---------------------------------------------------------

def _contained(root: str, candidate: str) -> str:
    """Return ``candidate`` if it really resolves inside ``root``, else raise."""
    root_real = os.path.realpath(root)
    candidate_real = os.path.realpath(candidate)
    if candidate_real != root_real and not candidate_real.startswith(root_real + os.sep):
        raise ValidationError("path escapes the Gift Card Studio directory")
    return candidate


def project_path(project_id: str, data_dir: str | None = None) -> str:
    """Absolute path for a project id, validated and contained."""
    require_safe_id(project_id)
    directory = projects_dir(data_dir)
    return _contained(directory, os.path.join(directory, f"{project_id}.json"))


def is_safe_asset_name(name) -> bool:
    if not isinstance(name, str) or name in (".", ".."):
        return False
    if not SAFE_ASSET_NAME.match(name):
        return False
    if os.path.splitext(name)[1].lower() not in ALLOWED_ASSET_EXTENSIONS:
        return False
    # Reject double extensions like evil.png.exe / evil.html.png shells.
    return name.count(".") == 1


def asset_path(name: str, data_dir: str | None = None) -> str:
    """Absolute path for an uploaded asset, validated and contained."""
    if not is_safe_asset_name(name):
        raise ValidationError(f"unsafe asset name: {name!r}")
    directory = assets_dir(data_dir)
    return _contained(directory, os.path.join(directory, name))


def unique_asset_name(name: str, data_dir: str | None = None) -> str:
    """Sanitize ``name`` and suffix it until it does not collide on disk."""
    base, ext = os.path.splitext(name or "")
    ext = ext.lower()
    if ext not in ALLOWED_ASSET_EXTENSIONS:
        ext = ".png"
    stem = slugify_id(base, "asset")[:60] or "asset"
    candidate = f"{stem}{ext}"
    counter = 2
    while os.path.exists(os.path.join(assets_dir(data_dir), candidate)):
        candidate = f"{stem}-{counter}{ext}"
        counter += 1
        if counter > 9999:
            raise ValidationError("could not allocate an asset filename")
    return candidate


# ---- Atomic IO -----------------------------------------------------------

def _write_atomic(path: str, text: str) -> None:
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


# ---- Projects ------------------------------------------------------------

def list_project_ids(data_dir: str | None = None) -> list[str]:
    directory = projects_dir(data_dir)
    try:
        entries = os.listdir(directory)
    except FileNotFoundError:
        return []
    ids = []
    for entry in entries:
        if not entry.endswith(".json"):
            continue
        candidate = entry[: -len(".json")]
        if is_safe_id(candidate):
            ids.append(candidate)
    return sorted(ids)


def project_exists(project_id: str, data_dir: str | None = None) -> bool:
    if not is_safe_id(project_id):
        return False
    return os.path.exists(project_path(project_id, data_dir))


def load_project(project_id: str, data_dir: str | None = None) -> dict | None:
    """Load and normalize a project. Returns ``None`` when absent.

    A corrupt or oversized file raises :class:`ValidationError` rather than
    silently returning an empty project, so the UI can say "this file is
    damaged" instead of overwriting the user's real design with a blank one.
    """
    path = project_path(project_id, data_dir)
    try:
        size = os.path.getsize(path)
    except FileNotFoundError:
        return None
    if size > MAX_PROJECT_BYTES:
        raise ValidationError(f"project file too large: {size} bytes")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError(f"project file is not valid JSON: {exc}") from exc
    return models.normalize_project(raw, project_id)


def save_project(project: dict, data_dir: str | None = None, project_id: str | None = None) -> dict:
    """Normalize, stamp, and atomically persist a project. Returns the saved dict."""
    normalized = models.normalize_project(project, project_id or (project or {}).get("id"))
    models.touch(normalized)
    ensure_dirs(data_dir)
    path = project_path(normalized["id"], data_dir)
    payload = json.dumps(normalized, ensure_ascii=False, indent=2)
    if len(payload.encode("utf-8")) > MAX_PROJECT_BYTES:
        raise ValidationError("project exceeds the maximum saved size")
    _write_atomic(path, payload)
    return normalized


def delete_project(project_id: str, data_dir: str | None = None) -> bool:
    """Remove a project file. ``False`` when it did not exist."""
    path = project_path(project_id, data_dir)
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False


def create_project(name: str, data_dir: str | None = None, **overrides) -> dict:
    """Create and persist a new project, allocating a non-colliding id."""
    base_id = slugify_id(name, "project")
    candidate = base_id
    counter = 2
    while project_exists(candidate, data_dir):
        suffix = f"-{counter}"
        candidate = base_id[: 64 - len(suffix)] + suffix
        counter += 1
        if counter > 9999:
            raise ValidationError("could not allocate a project id")
    project = models.new_project(name=name, project_id=candidate, **overrides)
    return save_project(project, data_dir)


def list_projects(data_dir: str | None = None) -> list[dict]:
    """Summaries for every readable project; damaged files are flagged, not fatal."""
    summaries = []
    for project_id in list_project_ids(data_dir):
        try:
            project = load_project(project_id, data_dir)
        except ValidationError as exc:
            summaries.append({"id": project_id, "name": project_id, "error": str(exc)})
            continue
        if project is not None:
            summaries.append(models.summarize_project(project))
    return summaries


# ---- Assets --------------------------------------------------------------

def list_assets(data_dir: str | None = None) -> list[dict]:
    directory = assets_dir(data_dir)
    try:
        entries = os.listdir(directory)
    except FileNotFoundError:
        return []
    assets = []
    for entry in sorted(entries):
        if not is_safe_asset_name(entry):
            continue
        full = os.path.join(directory, entry)
        try:
            assets.append({"name": entry, "size": os.path.getsize(full)})
        except OSError:
            continue
    return assets


def save_asset_bytes(name: str, data: bytes, data_dir: str | None = None) -> str:
    """Persist raw asset bytes under a sanitized unique name. Returns the name."""
    ensure_dirs(data_dir)
    final_name = unique_asset_name(name, data_dir)
    path = asset_path(final_name, data_dir)
    tmp = path + ".tmp"
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return final_name


def delete_asset(name: str, data_dir: str | None = None) -> bool:
    path = asset_path(name, data_dir)
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False
