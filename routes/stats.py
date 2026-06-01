"""Stats API routes."""

import os
from flask import Blueprint, jsonify
from utils import safe_json_read

stats_bp = Blueprint('stats', __name__)

# Will be set by app.py after BASE_DIR is defined
BASE_DIR = None


def init_stats_blueprint(base_dir):
    """Initialize the stats blueprint with the base directory."""
    global BASE_DIR
    BASE_DIR = base_dir


@stats_bp.route("/viewers", methods=["GET"])
def get_viewer_stats():
    """Get viewer statistics."""
    data = safe_json_read(os.path.join(BASE_DIR, "viewer_stats.json"))
    if data is not None:
        return jsonify(data)
    return jsonify({"viewers": 0, "total_viewers": 0})


@stats_bp.route("/gifts", methods=["GET"])
def get_gift_log():
    """Get gift log."""
    data = safe_json_read(os.path.join(BASE_DIR, "gift_log.json"))
    return jsonify(data if data is not None else [])


@stats_bp.route("/gifts/clear", methods=["POST"])
def clear_gift_log():
    """Clear gift log."""
    log_file = os.path.join(BASE_DIR, "gift_log.json")
    if os.path.exists(log_file):
        try:
            os.remove(log_file)
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "success", "message": "No log to clear"})


@stats_bp.route("/chat", methods=["GET"])
def get_chat_log():
    """Get chat log."""
    data = safe_json_read(os.path.join(BASE_DIR, "chat_log.json"))
    return jsonify(data if data is not None else [])


@stats_bp.route("/chat/clear", methods=["POST"])
def clear_chat_log():
    """Clear chat log."""
    log_file = os.path.join(BASE_DIR, "chat_log.json")
    if os.path.exists(log_file):
        try:
            os.remove(log_file)
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "success", "message": "No log to clear"})


@stats_bp.route("/follows", methods=["GET"])
def get_follow_log():
    """Get follow log."""
    data = safe_json_read(os.path.join(BASE_DIR, "follow_log.json"))
    return jsonify(data if data is not None else [])


@stats_bp.route("/follows/clear", methods=["POST"])
def clear_follow_log():
    """Clear follow log."""
    log_file = os.path.join(BASE_DIR, "follow_log.json")
    if os.path.exists(log_file):
        try:
            os.remove(log_file)
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "success", "message": "No log to clear"})


@stats_bp.route("/superfan", methods=["GET"])
def get_superfan_log():
    """Get superfan log."""
    data = safe_json_read(os.path.join(BASE_DIR, "superfan_log.json"))
    return jsonify(data if data is not None else [])


@stats_bp.route("/superfan/clear", methods=["POST"])
def clear_superfan_log():
    """Clear superfan log."""
    log_file = os.path.join(BASE_DIR, "superfan_log.json")
    if os.path.exists(log_file):
        try:
            os.remove(log_file)
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "success", "message": "No log to clear"})


@stats_bp.route("/active-streaks", methods=["GET"])
def get_active_streaks():
    """Get active streaks."""
    data = safe_json_read(os.path.join(BASE_DIR, "active_streaks.json"))
    return jsonify(data if data is not None else {})


@stats_bp.route("/song", methods=["GET"])
def get_song_overlay_data():
    """Get current song data for overlay display."""
    import spotify_handler as sh

    playback = sh.get_current_playback()
    queue = sh.load_queue()

    # Get the actual Spotify track URI if something is playing
    current_spotify_item = playback.get("item") if not isinstance(playback.get("item"), dict) or playback.get("item") else None
    current_spotify_uri = current_spotify_item.get("uri") if current_spotify_item else None

    # Find currently playing entry from queue
    now_playing = None
    for q in queue:
        if q.get("status") == "playing":
            now_playing = q
            break

    # If no local "playing" entry but Spotify is actually playing something,
    # cross-reference the URI against pushed/queued entries
    if not now_playing and current_spotify_uri:
        for q in queue:
            if q.get("spotify_uri") == current_spotify_uri and q.get("status") in ("queued", "pushed"):
                now_playing = q
                break

    # Get all upcoming songs (exclude whatever is now playing via URI match)
    playing_uri = now_playing.get("spotify_uri") if now_playing else None
    upcoming = []
    for q in queue:
        status = q.get("status", "")
        uri = q.get("spotify_uri", "")
        if status in ("queued", "pushed") and uri != playing_uri:
            upcoming.append(q)

    return jsonify({
        "now_playing": now_playing,
        "spotify_playing": playback.get("item"),
        "is_playing": playback.get("is_playing", False),
        "progress_ms": playback.get("progress_ms", 0),
        "upcoming": upcoming,
        "queue_length": len(upcoming),
        "feedback": sh.get_and_clear_feedback(),
    })
