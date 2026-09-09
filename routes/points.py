"""Points API routes — long-term viewer coin database."""

from flask import Blueprint, jsonify, request

import points_store

points_bp = Blueprint('points', __name__)


def _int_arg(name, default):
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _float_arg(name):
    raw = request.args.get(name)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


@points_bp.route("/viewers", methods=["GET"])
def get_points_viewers():
    """Paged viewer totals, optionally aggregated inside a timestamp period."""
    since = _float_arg("since")
    until = _float_arg("until")
    if since is not None and until is not None and until <= since:
        return jsonify({"error": "until must be greater than since"}), 400
    return jsonify(points_store.list_viewers(
        limit=_int_arg("limit", 50),
        offset=_int_arg("offset", 0),
        sort=request.args.get("sort", "coins"),
        q=request.args.get("q", ""),
        since=since,
        until=until,
    ))


@points_bp.route("/viewer", methods=["GET"])
def get_points_viewer_detail():
    """Single viewer aggregate + recent gift history."""
    user_id = request.args.get("id", "").strip()
    if not user_id:
        return jsonify({"error": "missing id"}), 400
    return jsonify(points_store.viewer_detail(
        user_id,
        history_limit=_int_arg("limit", 100),
    ))


@points_bp.route("/viewer/adjust", methods=["POST"])
def adjust_points_viewer_coins():
    """Manually set/add/remove a viewer's coins.

    Recovery path for gifts that never reached the database (app crash,
    dropped TikTok connection). Returns the adjustment result merged with the
    refreshed viewer detail so the modal can re-render without a second fetch.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    user_id = str(data.get("id") or "").strip()
    if not user_id:
        return jsonify({"error": "missing id"}), 400

    try:
        result = points_store.adjust_coins(
            user_id,
            str(data.get("operation") or "").strip().lower(),
            data.get("amount"),
            note=str(data.get("note") or "").strip(),
        )
    except LookupError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # DB/IO failure — surface instead of silently passing
        return jsonify({"error": f"adjustment failed: {e}"}), 500

    detail = points_store.viewer_detail(user_id, history_limit=100)
    return jsonify({**result, **detail})
