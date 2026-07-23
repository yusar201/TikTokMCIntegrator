"""Manifest store for downloaded gift animation assets.

Persists a JSON map of gift_id -> local file info so we don't re-download
the same animation twice. Lives at <BASE_DIR>/gift_assets/manifest.json.
BASE_DIR resolves to the release/ folder when frozen, matching the rest of the app.
"""
import os
import sys
import json
import time

# Centralized path layout — assets live under <BASE_DIR>/assets/gift_assets/.
import paths

BASE_DIR = paths.BASE_DIR
ASSETS_DIR = paths.assets("gift_assets")
MANIFEST_FILE = os.path.join(ASSETS_DIR, "manifest.json")


def load_manifest() -> dict:
    """Return the full manifest as a dict, or {} if missing/corrupt."""
    if not os.path.exists(MANIFEST_FILE):
        return {}
    try:
        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_manifest(manifest: dict) -> None:
    """Write the manifest atomically-ish (write+replace)."""
    os.makedirs(ASSETS_DIR, exist_ok=True)
    tmp = MANIFEST_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    os.replace(tmp, MANIFEST_FILE)


def get_entry(gift_id: int) -> dict | None:
    """Return the manifest entry for a gift, or None."""
    return load_manifest().get(str(gift_id))


def set_entry(gift_id: int, local_path: str, local_url: str, source_url: str, ext: str) -> dict:
    """Add or update an entry and persist. Returns the new entry."""
    m = load_manifest()
    entry = {
        "local": local_path,
        "local_url": local_url,
        "source": source_url,
        "type": ext,
        "ts": int(time.time()),
    }
    m[str(gift_id)] = entry
    save_manifest(m)
    return entry
