"""Stats API routes."""

import os
import threading
from flask import Blueprint, jsonify, request
from utils import safe_json_read, save_json, load_json
import paths
from avatar_cache import cache_avatar_image, is_local_avatar_url, local_avatar_path_from_url

stats_bp = Blueprint('stats', __name__)

COIN_GOAL_FILE = paths.data("coin_goal.json")

# Will be set by app.py after BASE_DIR is defined
BASE_DIR = None


# Top Gift and Top Streak poll frequently in OBS.  They need one selected
# entry, not the complete growing stream gift history on every poll.
_GIFT_SUMMARY_CACHE = {
    "signature": None,
    "topgift": [],
    "topstreak": [],
}
_GIFT_SUMMARY_LOCK = threading.Lock()


def _gift_diamond_value(entry):
    if not isinstance(entry, dict):
        return 0
    direct = entry.get("diamond_count")
    if direct not in (None, ""):
        try:
            return int(direct)
        except (TypeError, ValueError):
            pass
    try:
        total = int(entry.get("total_coins") or 0)
        repeats = int(entry.get("repeat_count") or 0)
        return round(total / repeats) if total and repeats else 0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


def _gift_repeat_count(entry):
    try:
        return int(entry.get("repeat_count") or 0) if isinstance(entry, dict) else 0
    except (TypeError, ValueError):
        return 0


def _gift_log_summary(kind):
    """Return the requested top gift/streak entry, cached until file changes."""
    log_file = os.path.join(BASE_DIR, "gift_log.json")
    try:
        stat = os.stat(log_file)
        signature = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return []

    with _GIFT_SUMMARY_LOCK:
        if _GIFT_SUMMARY_CACHE["signature"] != signature:
            entries = safe_json_read(log_file)
            entries = entries if isinstance(entries, list) else []
            valid = [entry for entry in entries if isinstance(entry, dict)]

            def latest_max(score):
                winner = None
                winner_score = None
                for entry in valid:
                    value = score(entry)
                    if winner is None or value >= winner_score:
                        winner = entry
                        winner_score = value
                return [winner] if winner is not None else []

            # Match the overlay's existing >= tie rule: a newer equal-value
            # gift/streak is the current winner rather than a stale earlier one.
            _GIFT_SUMMARY_CACHE["topgift"] = latest_max(_gift_diamond_value)
            _GIFT_SUMMARY_CACHE["topstreak"] = latest_max(_gift_repeat_count)
            _GIFT_SUMMARY_CACHE["signature"] = signature
        if kind == "topshowcase":
            return {
                "topgift": _GIFT_SUMMARY_CACHE["topgift"][0] if _GIFT_SUMMARY_CACHE["topgift"] else None,
                "topstreak": _GIFT_SUMMARY_CACHE["topstreak"][0] if _GIFT_SUMMARY_CACHE["topstreak"] else None,
            }
        return list(_GIFT_SUMMARY_CACHE[kind])


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
    summary = request.args.get("summary", "").strip().lower()
    if summary in {"topgift", "topstreak", "topshowcase"}:
        return jsonify(_gift_log_summary(summary))
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


MAX_CHAT_PAGE_LIMIT = 2000


def _parse_int_arg(name, default=None):
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _chat_page(data, limit, before=None):
    """Return an indexed chat page ending before `before` (exclusive)."""
    if not isinstance(data, list):
        data = []
    total = len(data)
    limit = max(1, min(int(limit), MAX_CHAT_PAGE_LIMIT))
    end = total if before is None else max(0, min(int(before), total))
    start = max(0, end - limit)
    entries = []
    for idx, entry in enumerate(data[start:end], start):
        copied = dict(entry) if isinstance(entry, dict) else {"message": entry}
        copied["_chat_index"] = idx
        entries.append(copied)
    return {
        "entries": entries,
        "total": total,
        "start": start,
        "end": end,
        "has_older": start > 0,
        "next_before": start if start > 0 else None,
    }


@stats_bp.route("/chat", methods=["GET"])
def get_chat_log():
    """Get chat log.

    Backwards compatible: no query string returns the legacy full list used by
    overlays. Dashboard can request paged/tail data with ?limit=N&before=IDX.
    """
    data = safe_json_read(os.path.join(BASE_DIR, "chat_log.json"))
    if data is None:
        data = []
    limit = _parse_int_arg("limit")
    if limit is None:
        return jsonify(data if isinstance(data, list) else [])
    before = _parse_int_arg("before")
    return jsonify(_chat_page(data, limit, before))


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


@stats_bp.route("/topgifter", methods=["GET"])
def get_top_gifters():
    """Get top 3 gifters by total coins for the podium overlay."""
    try:
        ranking_file = os.path.join(BASE_DIR, "..", "data", "gifter_ranking.json")
        if not os.path.exists(ranking_file):
            ranking_file = os.path.join(BASE_DIR, "gifter_ranking.json")
        data = safe_json_read(ranking_file)
        if not isinstance(data, list):
            data = []

        # TikTokLive can intermittently omit profile pictures on gift events.
        # Enrich podium entries from the persistent avatar cache seeded by chat/follow/gift events.
        avatar_cache_file = paths.data("avatar_cache.json")
        avatar_cache = safe_json_read(avatar_cache_file)
        if not isinstance(avatar_cache, dict):
            avatar_cache = {}

        def cache_key(nick="", unique_id=""):
            unique_id = str(unique_id or "").strip().lower()
            if unique_id:
                return f"uid:{unique_id}"
            return f"nick:{str(nick or '').strip().lower()}"

        changed = False
        for entry in data:
            if not isinstance(entry, dict):
                continue

            avatar_url = str(entry.get("avatar_url") or "")
            cached_source_url = ""
            for key in (cache_key(entry.get("nick", ""), entry.get("unique_id", "")), cache_key(entry.get("nick", ""), "")):
                cached = avatar_cache.get(key)
                if isinstance(cached, dict):
                    cached_avatar = str(cached.get("avatar_url") or "")
                    cached_source_url = str(cached.get("source_url") or cached_source_url or "")
                elif isinstance(cached, str):
                    cached_avatar = cached
                else:
                    cached_avatar = ""
                if not avatar_url and cached_avatar:
                    avatar_url = cached_avatar
                    entry["avatar_url"] = avatar_url
                    changed = True
                    break

            # Backfill older ranking/cache entries from expiring TikTok URLs to real
            # local files. If a local URL points at a missing file, try its source_url.
            needs_local = avatar_url and not is_local_avatar_url(avatar_url)
            if is_local_avatar_url(avatar_url):
                local_path = local_avatar_path_from_url(avatar_url)
                needs_local = not (local_path and os.path.exists(local_path))
                if needs_local and cached_source_url:
                    avatar_url = cached_source_url

            if needs_local and avatar_url:
                local_url = cache_avatar_image(avatar_url, entry.get("nick", ""), entry.get("unique_id", ""))
                if local_url:
                    entry["avatar_url"] = local_url
                    changed = True
                    now = int(__import__('time').time())
                    for key in (cache_key(entry.get("nick", ""), entry.get("unique_id", "")), cache_key(entry.get("nick", ""), "")):
                        if key:
                            avatar_cache[key] = {
                                "nick": entry.get("nick", ""),
                                "unique_id": entry.get("unique_id", ""),
                                "avatar_url": local_url,
                                "source_url": avatar_url if not is_local_avatar_url(avatar_url) else cached_source_url,
                                "updated_at": now,
                            }

        if changed:
            try:
                save_json(avatar_cache_file, avatar_cache)
                save_json(ranking_file, data)
            except Exception as e:
                print(f"[STATS] Failed to persist local avatar cache backfill: {e}")

        return jsonify(data[:3])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@stats_bp.route("/topgifter/reset", methods=["POST"])
def reset_top_gifters():
    """Reset gifter ranking to empty list."""
    try:
        ranking_file = os.path.join(BASE_DIR, "..", "data", "gifter_ranking.json")
        if not os.path.exists(os.path.dirname(ranking_file)):
            ranking_file = os.path.join(BASE_DIR, "gifter_ranking.json")
        save_json(ranking_file, [])
        return jsonify({"status": "success", "message": "Gifter ranking cleared"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


COIN_GOAL_DEFAULTS = {"current": 0, "goal": 10000, "label": "Tip Jar", "sublabel": ""}


def _read_coin_goal():
    """Read jar state with defaults filled in + numeric coercion."""
    data = safe_json_read(COIN_GOAL_FILE)
    if not isinstance(data, dict):
        data = {}
    merged = dict(COIN_GOAL_DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in COIN_GOAL_DEFAULTS})
    try:
        merged["current"] = max(0, int(merged["current"]))
    except (ValueError, TypeError):
        merged["current"] = 0
    try:
        merged["goal"] = max(1, int(merged["goal"]))
    except (ValueError, TypeError):
        merged["goal"] = 10000
    merged["label"] = str(merged.get("label", "Tip Jar"))
    merged["sublabel"] = str(merged.get("sublabel", ""))
    return merged


@stats_bp.route("/coingoal", methods=["GET"])
def get_coin_goal():
    """Get the coin goal jar state for the overlay."""
    response = jsonify(_read_coin_goal())
    # OBS/WebView2 can cache repeated GETs to the same URL. Coin-goal state is
    # edited live, so every poll must reach the JSON file instead of a stale
    # browser cache entry.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


GIFT_GOAL_FILE = paths.data("gift_goal.json")
GIFT_GOAL_DEFAULTS = {
    "gift_id": "",
    "gift_name": "",
    "gift_icon": "",
    "gift_asset_url": "",
    "gift_diamond_count": 0,
    "gift_primary_effect_id": "",
    "gift_resource_id": "",
    "gift_has_animation": False,
    "goal": 100,
    "current": 0,
    "header": "Goal Today",
}


def _cached_gift_asset_url(gift_id):
    """Return cached local gift animation URL if this gift was already downloaded."""
    try:
        from assets.gift_assets.manifest import get_entry
        entry = get_entry(int(gift_id))
        if entry and os.path.exists(entry.get("local", "")):
            return entry.get("local_url", "") or ""
    except Exception:
        pass
    return ""


def _read_gift_goal():
    """Read gift goal state with defaults + numeric coercion."""
    data = safe_json_read(GIFT_GOAL_FILE)
    if not isinstance(data, dict):
        data = {}
    merged = dict(GIFT_GOAL_DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in GIFT_GOAL_DEFAULTS})
    try:
        merged["current"] = max(0, int(merged["current"]))
    except (ValueError, TypeError):
        merged["current"] = 0
    try:
        merged["goal"] = max(1, int(merged["goal"]))
    except (ValueError, TypeError):
        merged["goal"] = 100
    merged["gift_id"] = str(merged.get("gift_id", ""))
    merged["gift_name"] = str(merged.get("gift_name", ""))
    merged["gift_icon"] = str(merged.get("gift_icon", ""))
    merged["gift_asset_url"] = str(merged.get("gift_asset_url", ""))
    merged["gift_primary_effect_id"] = str(merged.get("gift_primary_effect_id", ""))
    merged["gift_resource_id"] = str(merged.get("gift_resource_id", ""))
    merged["gift_has_animation"] = bool(merged.get("gift_has_animation", False))
    try:
        merged["gift_diamond_count"] = max(0, int(merged.get("gift_diamond_count", 0)))
    except (ValueError, TypeError):
        merged["gift_diamond_count"] = 0
    # If the selected gift's animation has been cached by the gift downloader,
    # expose it immediately even when gift_goal.json predates this field.
    if not merged["gift_asset_url"] and merged["gift_id"]:
        merged["gift_asset_url"] = _cached_gift_asset_url(merged["gift_id"])
    merged["header"] = str(merged.get("header", "Goal Today"))
    return merged

@stats_bp.route("/giftgoal", methods=["GET"])
def get_gift_goal():
    """Get the gift goal state for the overlay."""
    return jsonify(_read_gift_goal())


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
