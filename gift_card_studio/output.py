"""Where generated overlays get saved.

Khito's flow is: pick a folder once, then every Generate writes the finished
PNG/GIF straight there so it can be added to OBS as an image source. That means
the destination is *persistent app state*, not a per-request parameter, and the
picker has to be the real OS folder dialog — typing a Windows path into a text
box is exactly the friction this replaces.

Two halves live here:

* **Persistence** — the chosen folder is stored in its own small JSON file under
  the Studio's data dir. Deliberately not in ``config/config.yml``: that file is
  the bot's live configuration and the Studio must never mutate it.
* **Validation** — a stored path can go stale (external drive unplugged, folder
  renamed). Every read re-checks it is a real, writable directory, so the UI can
  say "that folder is gone" instead of failing at the end of a 30-second render.

The native dialog itself is injected by the desktop shell (``main.py`` owns the
pywebview window). This module only knows *that* a picker may exist, so the
package keeps importing cleanly in a plain browser or under pytest.
"""
from __future__ import annotations

import json
import os
import tempfile

from .validation import ValidationError

SETTINGS_FILENAME = "output_settings.json"

# Set by the desktop shell at startup: a zero-arg callable returning a chosen
# directory path, or None if the user cancelled. Left None everywhere else, and
# the API reports that the picker is unavailable rather than pretending.
_folder_picker = None


def register_folder_picker(picker) -> None:
    """Install the native folder dialog. Called once by the desktop shell."""
    global _folder_picker
    _folder_picker = picker


def has_folder_picker() -> bool:
    return callable(_folder_picker)


def pick_folder():
    """Open the native folder dialog. Returns a path, or None if cancelled.

    Raises ``ValidationError`` when no picker is installed, so a browser-only
    session gets a clear "type a path instead" answer rather than a silent no-op.
    """
    if not callable(_folder_picker):
        raise ValidationError("no native folder picker is available in this context")
    chosen = _folder_picker()
    if not chosen:
        return None
    return os.path.abspath(str(chosen))


# ---- Persistence ---------------------------------------------------------

def settings_path(data_dir=None) -> str:
    from . import storage

    return os.path.join(storage.studio_root(data_dir), SETTINGS_FILENAME)


def _load_raw(data_dir=None) -> dict:
    try:
        with open(settings_path(data_dir), "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_raw(payload: dict, data_dir=None) -> None:
    from . import storage

    storage.ensure_dirs(data_dir)
    path = settings_path(data_dir)
    # Atomic: a half-written settings file would lose the folder on next launch.
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=os.path.dirname(path), delete=False, suffix=".tmp"
    )
    try:
        with handle:
            json.dump(payload, handle, indent=2)
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def describe_folder(path) -> dict:
    """Report whether ``path`` is usable as an output folder, and why not."""
    if not path:
        return {"path": "", "exists": False, "writable": False, "reason": "not set"}

    absolute = os.path.abspath(str(path))
    if not os.path.exists(absolute):
        return {
            "path": absolute, "exists": False, "writable": False,
            "reason": "folder no longer exists",
        }
    if not os.path.isdir(absolute):
        return {
            "path": absolute, "exists": True, "writable": False,
            "reason": "that path is a file, not a folder",
        }
    # Probe by actually creating a file: os.access lies on Windows, where ACLs
    # and read-only network shares are not reflected in the mode bits.
    try:
        probe = tempfile.NamedTemporaryFile(dir=absolute, prefix=".gcs-write-", delete=True)
        probe.close()
    except (OSError, PermissionError) as exc:
        return {
            "path": absolute, "exists": True, "writable": False,
            "reason": f"folder is not writable ({exc.__class__.__name__})",
        }
    return {"path": absolute, "exists": True, "writable": True, "reason": ""}


def get_output_folder(data_dir=None) -> dict:
    """Current destination plus its live status."""
    stored = _load_raw(data_dir).get("output_folder") or ""
    info = describe_folder(stored)
    info["configured"] = bool(stored)
    info["picker_available"] = has_folder_picker()
    return info


def set_output_folder(path, data_dir=None) -> dict:
    """Store ``path`` as the destination after verifying it is usable."""
    if not path or not str(path).strip():
        raise ValidationError("a folder path is required")

    info = describe_folder(path)
    if not info["exists"]:
        raise ValidationError(f"{info['path']}: folder does not exist")
    if not info["writable"]:
        raise ValidationError(f"{info['path']}: {info['reason']}")

    payload = _load_raw(data_dir)
    payload["output_folder"] = info["path"]
    _save_raw(payload, data_dir)

    info["configured"] = True
    info["picker_available"] = has_folder_picker()
    return info


def clear_output_folder(data_dir=None) -> None:
    payload = _load_raw(data_dir)
    payload.pop("output_folder", None)
    _save_raw(payload, data_dir)


def require_output_folder(data_dir=None) -> str:
    """The destination directory, or raise with a message the UI can show."""
    info = get_output_folder(data_dir)
    if not info["configured"]:
        raise ValidationError("choose an output folder before generating")
    if not info["exists"]:
        raise ValidationError(f"{info['path']} no longer exists — choose it again")
    if not info["writable"]:
        raise ValidationError(f"{info['path']}: {info['reason']}")
    return info["path"]


# ---- Delivery ------------------------------------------------------------

def unique_destination(directory: str, filename: str) -> str:
    """A path in ``directory`` that does not overwrite an existing file.

    Regenerating with tweaked settings is the normal loop, so silently clobbering
    the previous export would destroy a file Khito may already have wired into
    OBS. Collisions get ``-2``, ``-3``, … instead.
    """
    stem, extension = os.path.splitext(os.path.basename(filename))
    candidate = os.path.join(directory, stem + extension)
    counter = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{stem}-{counter}{extension}")
        counter += 1
        if counter > 9999:  # pathological; do not spin forever
            raise ValidationError("too many existing files with that name")
    return candidate


def deliver(source_path: str, directory: str, filename=None) -> str:
    """Copy a finished artifact into the user's folder. Returns the new path.

    Copy, not move: the job registry owns the original and cleans it up on its
    own schedule, and the download endpoint still needs to work afterwards.
    """
    import shutil

    if not os.path.isfile(source_path):
        raise ValidationError("the generated file is no longer available")

    destination = unique_destination(directory, filename or os.path.basename(source_path))
    # Copy to a temp name in the *destination* directory first, then rename, so a
    # partially-copied GIF is never visible to OBS or a file watcher.
    staging = destination + ".part"
    try:
        shutil.copyfile(source_path, staging)
        os.replace(staging, destination)
    except BaseException:
        try:
            os.unlink(staging)
        except OSError:
            pass
        raise
    return destination
