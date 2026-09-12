"""File-based add-on loader for TikTokMCIntegrator.

Add-ons live outside the PyInstaller bundle at BASE_DIR/addons/<addon_id>/ so
users can install/remove/update packs without rebuilding the app.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

import paths
import addon_runtime_registry
from utils import load_json, save_json

ADDON_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
STATE_FILE = paths.data("addons_state.json")

_DEFAULT_STATE = {
    "enabled": True,
    "config": {},
    "installed_at": None,
}


def _addons_dir() -> str:
    os.makedirs(paths.ADDONS_DIR, exist_ok=True)
    return paths.ADDONS_DIR


def _state() -> Dict[str, Dict[str, Any]]:
    data = load_json(STATE_FILE, {})
    return data if isinstance(data, dict) else {}


def _save_state(data: Dict[str, Dict[str, Any]]) -> None:
    save_json(STATE_FILE, data)


def _safe_id(value: str) -> str:
    value = (value or "").strip().lower().replace(" ", "-")
    value = re.sub(r"[^a-z0-9_-]+", "", value)
    if not ADDON_ID_RE.match(value):
        raise ValueError("Invalid add-on id. Use lowercase letters, numbers, dash or underscore.")
    return value


def _read_yaml_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if not text.strip():
        return {}
    if path.endswith(".json"):
        data = json.loads(text)
    else:
        data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def _normalize_overlay(addon_id: str, overlay: Dict[str, Any]) -> Dict[str, Any]:
    oid = _safe_id(str(overlay.get("id") or "overlay"))
    file_name = str(overlay.get("file") or f"overlays/{oid}.html").replace("\\", "/")
    return {
        "id": oid,
        "name": str(overlay.get("name") or oid.title()),
        "description": str(overlay.get("description") or ""),
        "file": file_name,
        "recommended_size": str(overlay.get("recommended_size") or overlay.get("size") or ""),
        "url": f"/overlay/addon/{addon_id}/{oid}",
    }


def _normalize_action(action: Dict[str, Any], addon_id: str, addon_name: str) -> Dict[str, Any]:
    aid = _safe_id(str(action.get("id") or action.get("name") or "action"))
    command = str(action.get("command") or action.get("minecraft_command") or "").strip()
    return {
        "id": aid,
        "addon_id": addon_id,
        "addon_name": addon_name,
        "name": str(action.get("name") or aid.replace("_", " ").replace("-", " ").title()),
        "description": str(action.get("description") or ""),
        "type": str(action.get("type") or "minecraft"),
        "command": command,
        "category": str(action.get("category") or "General"),
    }


def _manifest_paths(addon_dir: str) -> Tuple[str, str]:
    return os.path.join(addon_dir, "addon.yml"), os.path.join(addon_dir, "addon.json")


def get_addon_dir(addon_id: str) -> str:
    addon_id = _safe_id(addon_id)
    addon_dir = os.path.realpath(os.path.join(_addons_dir(), addon_id))
    root = os.path.realpath(_addons_dir())
    if not addon_dir.startswith(root + os.sep):
        raise ValueError("Invalid add-on path")
    return addon_dir


def load_addon(addon_id: str) -> Optional[Dict[str, Any]]:
    addon_id = _safe_id(addon_id)
    addon_dir = get_addon_dir(addon_id)
    yml, jsn = _manifest_paths(addon_dir)
    manifest_path = yml if os.path.exists(yml) else jsn
    if not os.path.exists(manifest_path):
        return None

    manifest = _read_yaml_json(manifest_path)
    manifest["id"] = _safe_id(str(manifest.get("id") or addon_id))
    addon_id = manifest["id"]
    name = str(manifest.get("name") or addon_id.title())

    state = _state().get(addon_id, {})
    config_defaults = manifest.get("config_defaults") or {}
    state_config = state.get("config") if isinstance(state.get("config"), dict) else {}
    config = dict(config_defaults if isinstance(config_defaults, dict) else {})
    config.update(state_config)

    connection = manifest.get("connection") if isinstance(manifest.get("connection"), dict) else {}
    overlays_raw = manifest.get("overlays") if isinstance(manifest.get("overlays"), list) else []
    actions_file = str(manifest.get("actions_file") or "actions.yml")
    actions_path = os.path.join(addon_dir, actions_file)
    actions_data = _read_yaml_json(actions_path)
    raw_actions = actions_data.get("actions") if isinstance(actions_data.get("actions"), list) else []

    return {
        "id": addon_id,
        "name": name,
        "version": str(manifest.get("version") or "0.0.0"),
        "author": str(manifest.get("author") or ""),
        "description": str(manifest.get("description") or ""),
        "icon": str(manifest.get("icon") or "fa-puzzle-piece"),
        "game": str(manifest.get("game") or "Minecraft"),
        "enabled": bool(state.get("enabled", manifest.get("enabled", True))),
        "status": "enabled" if bool(state.get("enabled", manifest.get("enabled", True))) else "disabled",
        "path": addon_dir,
        "manifest_path": manifest_path,
        "config": config,
        "connection": connection,
        "requirements": manifest.get("requirements") or [],
        "overlays": [_normalize_overlay(addon_id, o) for o in overlays_raw if isinstance(o, dict)],
        "actions": [_normalize_action(a, addon_id, name) for a in raw_actions if isinstance(a, dict)],
        "install": manifest.get("install") or {},
    }


def list_addons(include_disabled: bool = True) -> List[Dict[str, Any]]:
    root = _addons_dir()
    addons: List[Dict[str, Any]] = []
    for child in sorted(Path(root).iterdir() if os.path.exists(root) else [], key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        # A directory is an add-on only when it declares a manifest. Ignore
        # Python caches, tooling folders, and other runtime artifacts entirely.
        if not ((child / "addon.yml").is_file() or (child / "addon.json").is_file()):
            continue
        try:
            addon = load_addon(child.name)
            if not addon:
                continue
            if include_disabled or addon.get("enabled"):
                addons.append(addon)
        except Exception as e:
            addons.append({
                "id": child.name,
                "name": child.name,
                "version": "?",
                "enabled": False,
                "status": "error",
                "error": str(e),
                "path": str(child),
                "overlays": [],
                "actions": [],
                "requirements": [],
                "config": {},
            })
    return addons


def set_enabled(addon_id: str, enabled: bool) -> Dict[str, Any]:
    addon_id = _safe_id(addon_id)
    if not load_addon(addon_id):
        raise FileNotFoundError("Add-on not found")
    st = _state()
    entry = dict(_DEFAULT_STATE)
    entry.update(st.get(addon_id, {}))
    entry["enabled"] = bool(enabled)
    entry.setdefault("installed_at", time.time())
    st[addon_id] = entry
    _save_state(st)
    addon = load_addon(addon_id)
    assert addon is not None
    addon_runtime_registry.set_enabled(addon_id, bool(enabled))
    return addon


def update_config(addon_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    addon_id = _safe_id(addon_id)
    addon = load_addon(addon_id)
    if not addon:
        raise FileNotFoundError("Add-on not found")
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    st = _state()
    entry = dict(_DEFAULT_STATE)
    entry.update(st.get(addon_id, {}))
    merged = dict(entry.get("config") or {})
    merged.update(config)
    entry["config"] = merged
    entry.setdefault("installed_at", time.time())
    st[addon_id] = entry
    _save_state(st)
    addon = load_addon(addon_id)
    assert addon is not None
    addon_runtime_registry.set_config(addon_id, addon.get("config") or {})
    return addon


def _safe_extract_zip(zip_path: str, target_dir: str) -> None:
    target_real = os.path.realpath(target_dir)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            name = member.filename.replace("\\", "/")
            if not name or name.startswith("/") or "../" in name or name == ".." or name.startswith("../"):
                raise ValueError(f"Unsafe zip path: {member.filename}")
            dest = os.path.realpath(os.path.join(target_dir, name))
            if not (dest == target_real or dest.startswith(target_real + os.sep)):
                raise ValueError(f"Unsafe zip path: {member.filename}")
        zf.extractall(target_dir)


def _find_manifest_root(extract_dir: str) -> str:
    direct = [os.path.join(extract_dir, "addon.yml"), os.path.join(extract_dir, "addon.json")]
    if any(os.path.exists(p) for p in direct):
        return extract_dir
    children = [p for p in Path(extract_dir).iterdir() if p.is_dir()]
    for child in children:
        if (child / "addon.yml").exists() or (child / "addon.json").exists():
            return str(child)
    raise ValueError("No addon.yml or addon.json found in zip")


def install_zip(file: FileStorage) -> Dict[str, Any]:
    filename = secure_filename(file.filename or "addon.zip")
    if not filename.lower().endswith(".zip"):
        raise ValueError("Upload a .zip add-on package")

    with tempfile.TemporaryDirectory(prefix="tmc-addon-") as tmp:
        zip_path = os.path.join(tmp, filename)
        file.save(zip_path)
        extract_dir = os.path.join(tmp, "extract")
        os.makedirs(extract_dir, exist_ok=True)
        _safe_extract_zip(zip_path, extract_dir)
        root = _find_manifest_root(extract_dir)
        manifest = _read_yaml_json(os.path.join(root, "addon.yml") if os.path.exists(os.path.join(root, "addon.yml")) else os.path.join(root, "addon.json"))
        addon_id = _safe_id(str(manifest.get("id") or Path(root).name))
        dest = get_addon_dir(addon_id)
        if os.path.exists(dest):
            backup = dest + ".bak"
            if os.path.exists(backup):
                shutil.rmtree(backup)
            shutil.move(dest, backup)
        shutil.copytree(root, dest)

    st = _state()
    entry = dict(_DEFAULT_STATE)
    entry.update(st.get(addon_id, {}))
    entry["enabled"] = True
    entry["installed_at"] = time.time()
    st[addon_id] = entry
    _save_state(st)
    addon = load_addon(addon_id)
    if not addon:
        raise RuntimeError("Add-on installed but failed to load")
    return addon


def remove_addon(addon_id: str) -> None:
    addon_id = _safe_id(addon_id)
    addon_dir = get_addon_dir(addon_id)
    if os.path.exists(addon_dir):
        shutil.rmtree(addon_dir)
    st = _state()
    st.pop(addon_id, None)
    _save_state(st)


def _endpoint_url(addon: Dict[str, Any], endpoint_id: str) -> str:
    connection = addon.get("connection") or {}
    config = addon.get("config") or {}
    base = str(config.get("helper_url") or connection.get("default_base_url") or "").rstrip("/")
    if not base:
        raise ValueError("No helper URL configured")

    endpoint_id = endpoint_id.strip().lower()
    if endpoint_id in ("health", "ping"):
        path = str(connection.get("health_path") or "/ping")
    elif endpoint_id in ("status", "data", "oneblock"):
        path = str(connection.get("status_path") or "/status")
    else:
        endpoints = connection.get("endpoints") if isinstance(connection.get("endpoints"), dict) else {}
        path = str(endpoints.get(endpoint_id) or "")
        if not path:
            raise ValueError(f"Unknown endpoint: {endpoint_id}")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def request_endpoint(addon_id: str, endpoint_id: str = "status", timeout: float = 3.0) -> Tuple[Dict[str, Any], int]:
    addon = load_addon(addon_id)
    if not addon:
        return {"ok": False, "error": "Add-on not found"}, 404
    if not addon.get("enabled"):
        return {"ok": False, "error": "Add-on disabled"}, 409
    url = _endpoint_url(addon, endpoint_id)
    try:
        r = requests.get(url, timeout=timeout)
        ctype = r.headers.get("content-type", "")
        if "json" in ctype.lower():
            data = r.json()
        else:
            data = {"text": r.text[:1000]}
        if isinstance(data, dict):
            data.setdefault("_source_url", url)
        return data, r.status_code
    except requests.exceptions.ConnectionError:
        return {"ok": False, "connected": False, "error": f"Helper unreachable at {url}"}, 503
    except requests.exceptions.Timeout:
        return {"ok": False, "connected": False, "error": f"Helper timed out at {url}"}, 504
    except Exception as e:
        return {"ok": False, "connected": False, "error": str(e)}, 500


def health(addon_id: str) -> Dict[str, Any]:
    addon = load_addon(addon_id)
    if not addon:
        return {"ok": False, "connected": False, "error": "Add-on not found"}
    started = time.time()
    data, status = request_endpoint(addon_id, "health", timeout=2.0)
    latency_ms = int((time.time() - started) * 1000)
    return {
        "ok": status < 400,
        "connected": status < 400,
        "status_code": status,
        "latency_ms": latency_ms,
        "helper_url": (addon.get("config") or {}).get("helper_url") or (addon.get("connection") or {}).get("default_base_url") or "",
        "response": data,
    }


def resolve_overlay_file(addon_id: str, overlay_id: str) -> str:
    addon = load_addon(addon_id)
    if not addon:
        raise FileNotFoundError("Add-on not found")
    overlay_id = _safe_id(overlay_id)
    match = next((o for o in addon.get("overlays", []) if o.get("id") == overlay_id), None)
    if not match:
        raise FileNotFoundError("Overlay not found")
    addon_dir = get_addon_dir(addon["id"])
    file_path = os.path.realpath(os.path.join(addon_dir, match.get("file", "")))
    root = os.path.realpath(addon_dir)
    if not file_path.startswith(root + os.sep):
        raise ValueError("Invalid overlay path")
    if not os.path.exists(file_path):
        raise FileNotFoundError("Overlay file missing")
    return file_path


def resolve_static_dir(addon_id: str) -> str:
    addon_dir = get_addon_dir(addon_id)
    static_dir = os.path.realpath(os.path.join(addon_dir, "static"))
    root = os.path.realpath(addon_dir)
    if not static_dir.startswith(root + os.sep):
        raise ValueError("Invalid static path")
    os.makedirs(static_dir, exist_ok=True)
    return static_dir
