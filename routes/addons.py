"""Add-on API + overlay routes."""
from __future__ import annotations

import os
from flask import Blueprint, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import NotFound

import addon_loader

addons_api_bp = Blueprint("addons_api", __name__)
addons_page_bp = Blueprint("addons_page", __name__)


def init_addons_blueprint(addons_dir: str | None = None) -> None:
    # Kept for symmetry with stats init and future dependency injection.
    if addons_dir:
        os.makedirs(addons_dir, exist_ok=True)


@addons_api_bp.route("", methods=["GET"])
def list_addons():
    addons = addon_loader.list_addons(include_disabled=True)
    return jsonify({"addons": addons})


@addons_api_bp.route("/actions", methods=["GET"])
def list_addon_actions():
    actions = []
    for addon in addon_loader.list_addons(include_disabled=False):
        actions.extend(addon.get("actions", []))
    return jsonify({"actions": actions})


@addons_api_bp.route("/install", methods=["POST"])
def install_addon():
    file = request.files.get("file")
    if not file:
        return jsonify({"status": "error", "message": "No .zip file uploaded"}), 400
    try:
        addon = addon_loader.install_zip(file)
        return jsonify({"status": "success", "message": f"Installed {addon['name']}", "addon": addon})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@addons_api_bp.route("/<addon_id>", methods=["GET"])
def get_addon(addon_id):
    addon = addon_loader.load_addon(addon_id)
    if not addon:
        return jsonify({"status": "error", "message": "Add-on not found"}), 404
    return jsonify(addon)


@addons_api_bp.route("/<addon_id>/enable", methods=["POST"])
def set_addon_enabled(addon_id):
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", True))
    try:
        addon = addon_loader.set_enabled(addon_id, enabled)
        return jsonify({"status": "success", "addon": addon})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@addons_api_bp.route("/<addon_id>/config", methods=["POST"])
def update_addon_config(addon_id):
    data = request.get_json(silent=True) or {}
    try:
        addon = addon_loader.update_config(addon_id, data.get("config", data))
        return jsonify({"status": "success", "addon": addon})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@addons_api_bp.route("/<addon_id>/remove", methods=["POST"])
def remove_addon(addon_id):
    try:
        addon_loader.remove_addon(addon_id)
        return jsonify({"status": "success", "message": "Add-on removed"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@addons_api_bp.route("/<addon_id>/health", methods=["GET"])
def addon_health(addon_id):
    return jsonify(addon_loader.health(addon_id))


@addons_api_bp.route("/<addon_id>/proxy/<endpoint_id>", methods=["GET"])
def addon_proxy(addon_id, endpoint_id):
    data, status = addon_loader.request_endpoint(addon_id, endpoint_id)
    resp = jsonify(data)
    resp.status_code = status
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@addons_page_bp.route("/overlay/addon/<addon_id>/<overlay_id>")
def addon_overlay(addon_id, overlay_id):
    try:
        return send_file(addon_loader.resolve_overlay_file(addon_id, overlay_id), mimetype="text/html")
    except FileNotFoundError as e:
        return str(e), 404
    except Exception as e:
        return str(e), 400


@addons_page_bp.route("/addon-assets/<addon_id>/<path:filename>")
def addon_static(addon_id, filename):
    try:
        return send_from_directory(addon_loader.resolve_static_dir(addon_id), filename)
    except (FileNotFoundError, NotFound):
        return "Not found", 404
    except Exception as e:
        return str(e), 400
