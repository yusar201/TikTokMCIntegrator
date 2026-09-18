"""Spotify API routes."""

from flask import Blueprint, request, jsonify
import spotify_handler as sh
import re

spotify_bp = Blueprint('spotify', __name__)


@spotify_bp.route("/config", methods=["GET"])
def get_song_config():
    """Get song-request settings; OAuth application identity is not user config."""
    safe = dict(sh.load_config())
    for obsolete in ("spotify_client_id", "spotify_client_secret", "spotify_redirect_uri"):
        safe.pop(obsolete, None)
    return jsonify(safe)


@spotify_bp.route("/config", methods=["POST"])
def update_song_config():
    """Update the song configuration."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Song config must be a JSON object."}), 400
    if "loop_song_uri" in data:
        value = data["loop_song_uri"]
        if not isinstance(value, str):
            return jsonify({"error": "Default song must be a Spotify track link or URI."}), 400
        value = value.strip()
        if value:
            match = re.fullmatch(r"spotify:track:([A-Za-z0-9]{22})", value)
            if not match:
                match = re.fullmatch(
                    r"https://open\.spotify\.com/(?:intl-[a-zA-Z-]+/)?track/([A-Za-z0-9]{22})/?(?:[?#][^\s]*)?",
                    value,
                )
            if not match:
                return jsonify({"error": "Use a Spotify track link or URI, not an album or playlist. Leave blank to disable."}), 400
            value = "spotify:track:" + match.group(1)
        data["loop_song_uri"] = value
    cfg = sh.load_config()
    uri = data.get("loop_song_uri", cfg.get("loop_song_uri", ""))
    # Full-form saves include the unchanged default. Keep it editable even when
    # blocked, but reject selecting a new blocked default. Playback stays guarded.
    if uri and uri != cfg.get("loop_song_uri", ""):
        denied = sh.song_block_error(uri)
        if denied:
            return jsonify(denied), 400
    if data.get("loop_song_track") is not None:
        try:
            data["loop_song_track"] = sh.clean_default_track(data["loop_song_track"], uri)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    if not uri or uri != cfg.get("loop_song_uri", ""):
        data.setdefault("loop_song_track", None)
    for key in data:
        if key in cfg:
            cfg[key] = data[key]
    sh.save_config(cfg)
    return jsonify({"status": "success", "message": "Song config saved!"})


@spotify_bp.route("/default-track", methods=["GET"])
def default_song_details():
    """Display metadata without affecting the queue or playback."""
    return jsonify(sh.get_default_track())


@spotify_bp.route("/blocklist", methods=["GET", "POST"])
def song_blocklist():
    try:
        if request.method == "GET":
            return jsonify(sh.load_song_blocklist())
        return jsonify(sh.block_song(request.get_json(silent=True)))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except (sh.sqlite3.Error, OSError):
        return jsonify({"error": "Song block list could not be read or saved."}), 503


@spotify_bp.route("/blocklist/<track_id>", methods=["DELETE"])
def unblock_song(track_id):
    try:
        return jsonify(sh.unblock_song(track_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except (sh.sqlite3.Error, OSError):
        return jsonify({"error": "Song block list could not be updated."}), 503


@spotify_bp.route("/auth-url", methods=["GET"])
def get_spotify_auth_url():
    """Start one-click desktop OAuth using the bundled public app identity."""
    result = sh.begin_pkce_authorization()
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result)


@spotify_bp.route("/callback", methods=["GET"])
def spotify_callback():
    """Handle Spotify OAuth callback."""
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    print(f"[SPOTIFY] Callback received — code={'present' if code else 'missing'}, error={error}")
    if error:
        return jsonify({"error": f"Spotify authorization denied: {error}"}), 400
    if not code:
        return jsonify({"error": "No authorization code received"}), 400

    result = sh.handle_pkce_callback(code, state)
    if "error" in result:
        return f"""
        <!DOCTYPE html>
        <html>
        <body>
        <p>Spotify connection failed: {result['error']}</p>
        <script>
          window.opener.postMessage({{type: 'spotify-error', error: '{result['error']}'}}, '*');
          setTimeout(() => window.close(), 3000);
        </script>
        </body>
        </html>
        """, 400

    # Tell the dashboard about the required device-activation step.
    return """
    <script>
      window.opener.postMessage({type: 'spotify-connected', status: 'success'}, '*');
      window.close();
    </script>
    <p>Spotify connected. Open Spotify and play any song once so the bot can use song commands. You can close this window.</p>
    """


@spotify_bp.route("/status", methods=["GET"])
def spotify_status():
    """Get the current Spotify connection status and playback info."""
    status = sh.get_connection_status()
    cfg = sh.load_config()
    status["enabled"] = cfg.get("enabled", True)
    status["auth_ready"] = bool(sh.get_spotify_client_id())
    return jsonify(status)


@spotify_bp.route("/disconnect", methods=["POST"])
def spotify_disconnect():
    """Disconnect from Spotify and discard any unfinished login attempt."""
    sh.clear_token()
    sh.clear_pending_oauth()
    return jsonify({"status": "success", "message": "Disconnected from Spotify"})


@spotify_bp.route("/devices", methods=["GET"])
def spotify_devices():
    """Get available Spotify devices."""
    devices = sh.get_active_devices()
    if "error" in devices:
        return jsonify(devices), 400
    return jsonify(devices)


@spotify_bp.route("/transfer", methods=["POST"])
def spotify_transfer():
    """Transfer playback to a specific device."""
    device_id = request.json.get("device_id", "")
    if not device_id:
        return jsonify({"error": "Device ID required"}), 400
    result = sh.transfer_playback(device_id)
    if "error" in result:
        return jsonify(result), 400
    return jsonify({"status": "success", "message": "Playback transferred"})


@spotify_bp.route("/search", methods=["GET"])
def spotify_search():
    """Search for tracks on Spotify."""
    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "Query required"}), 400
    results = sh.search_track(query)
    if "error" in results:
        return jsonify(results), 400
    results = [dict(track, blocked=bool(sh.song_block_error(track.get("uri", "")))) for track in results]
    return jsonify(results)


@spotify_bp.route("/player", methods=["GET"])
def spotify_player():
    """Get current playback state."""
    return jsonify(sh.get_current_playback())


@spotify_bp.route("/skip", methods=["POST"])
def spotify_skip():
    """Skip current track."""
    result = sh.skip_track()
    if "error" in result:
        return jsonify(result), 400
    return jsonify({"status": "success", "message": "Skipped!"})


@spotify_bp.route("/queue", methods=["GET"])
def get_song_queue():
    """Get the local song queue."""
    queue = sh.load_queue()
    return jsonify(queue)


@spotify_bp.route("/queue", methods=["POST"])
def add_to_song_queue():
    """Add a track to the local queue (for testing)."""
    track = request.json
    requested_by = request.json.get("requested_by", "dashboard")
    result = sh.add_to_queue(track, requested_by)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@spotify_bp.route("/queue/<int:position>", methods=["DELETE"])
def remove_from_song_queue(position):
    """Remove a queued/pushed track from the local queue via dashboard admin control."""
    result = sh.remove_from_queue(position - 1, "dashboard", allow_any=True)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@spotify_bp.route("/queue/clear", methods=["POST"])
def clear_song_queue():
    """Clear the entire song queue."""
    result = sh.clear_queue()
    return jsonify(result)


@spotify_bp.route("/history", methods=["GET"])
def get_song_history():
    """Get song history."""
    history = sh.load_history()
    return jsonify(history)


@spotify_bp.route("/history/clear", methods=["POST"])
def clear_song_history():
    """Clear song history."""
    result = sh.clear_history()
    return jsonify(result)


@spotify_bp.route("/token", methods=["GET"])
def get_spotify_token_status():
    """Check if a valid Spotify token exists."""
    token = sh.load_token()
    return jsonify({
        "has_token": token is not None,
        "has_refresh": bool(token and token.get("refresh_token")) if token else False,
    })


# ── Simulate Commands (for overlay debug) ──────────────────────────────

@spotify_bp.route("/simulate/play", methods=["POST"])
def simulate_play():
    """Simulate a !play command. Searches Spotify, queues first result, pushes feedback."""
    data = request.json or {}
    nick = data.get("nick", "testuser")
    query = data.get("query", "")
    if not query:
        sh.push_song_feedback(nick, "error", "✗", f"@{nick} — no search query provided")
        return jsonify({"error": "Query required"}), 400

    # Search
    results = sh.search_track(query, limit=5)
    if isinstance(results, dict) and "error" in results:
        sh.push_song_feedback(nick, "error", "✗", f"@{nick} — search failed: {results['error']}")
        return jsonify(results), 400
    if not results:
        sh.push_song_feedback(nick, "error", "✗", f'@{nick} — no results for "{query}"')
        return jsonify({"error": "No results", "feedback_pushed": True})

    track = results[0]

    # Queue
    result = sh.add_to_queue(track, nick)
    if "error" in result:
        if "duplicate" in result.get("error", "").lower() or "already" in result.get("error", "").lower():
            sh.push_song_feedback(nick, "denied", "⊘", f"@{nick} — {result['error']}")
        else:
            sh.push_song_feedback(nick, "error", "✗", f"@{nick} — {result['error']}")
        return jsonify(result), 400

    pos = result.get("position", 0) + 1

    # Try direct push if nothing playing
    try:
        token = sh.get_valid_token()
        if token:
            # Check LOCAL queue first — it's the source of truth and doesn't
            # lag like Spotify's playback cache does. (See minecraft_main.py
            # !play handler for the same fix.)
            local_queue = sh.load_queue()
            has_local_playing = any(
                q.get("status") == "playing" for q in local_queue
            )

            if has_local_playing:
                # User song already playing in our local queue. Just queue
                # this one locally — DON'T touch Spotify's queue.
                pass
            else:
                playback = sh.get_current_playback()
                spotify_playing = playback.get("is_playing", False)
                spotify_item = playback.get("item")

                if not spotify_playing and not spotify_item:
                    # Nothing playing anywhere → play immediately via
                    # play_track_immediate (local-only architecture).
                    start_result = sh.play_track_immediate(track["uri"])
                    if start_result.get("code") in ("song_blocked", "blocklist_unavailable"):
                        sh.push_song_feedback(nick, "error", "✗", f"@{nick} — {start_result['error']}")
                        return jsonify(start_result), 400
                    queue = sh.load_queue()
                    new_pos = None
                    for i, q in enumerate(queue):
                        if q.get("spotify_uri") == track.get("uri") and q.get("status") in ("queued", "pushed"):
                            new_pos = i
                            break
                    if new_pos is not None:
                        sh.mark_as_playing(new_pos)
                else:
                    # Loop song / non-user song is playing on Spotify, no
                    # user song in our local queue → replace context.
                    start_result = sh.play_track_immediate(track["uri"])
                    if start_result.get("code") in ("song_blocked", "blocklist_unavailable"):
                        sh.push_song_feedback(nick, "error", "✗", f"@{nick} — {start_result['error']}")
                        return jsonify(start_result), 400
                    queue = sh.load_queue()
                    new_pos = None
                    for i, q in enumerate(queue):
                        if q.get("spotify_uri") == track.get("uri") and q.get("status") in ("queued", "pushed"):
                            new_pos = i
                            break
                    if new_pos is not None:
                        sh.mark_as_playing(new_pos)
    except Exception as e:
        print(f"[SIMULATE] Direct push error (non-fatal): {e}")

    sh.push_song_feedback(
        nick, "success", "✓",
        f"@{nick} queued {track['name']} \u2014 {track['artists']}",
        f"Position #{pos} \u2022 Use !pull to remove your request"
    )

    return jsonify({"success": True, "track": track, "position": pos, "feedback_pushed": True})


@spotify_bp.route("/simulate/skip", methods=["POST"])
def simulate_skip():
    """Simulate a !skip command. Skips current track, pushes feedback."""
    data = request.json or {}
    nick = data.get("nick", "testuser")

    result = sh.skip_track()
    if isinstance(result, dict) and "error" in result:
        sh.push_song_feedback(nick, "error", "✗", f"@{nick} — skip failed: {result['error']}")
        return jsonify(result), 400

    # Play next from local queue immediately
    played = sh.play_next_from_queue()
    sh.push_song_feedback(nick, "success", "⏭",
        f"@{nick} skipped to next track" if played else f"@{nick} skipped the track")
    return jsonify({"success": True, "feedback_pushed": True})


@spotify_bp.route("/simulate/pull", methods=["POST"])
def simulate_pull():
    """Simulate a !pull command. Removes user's latest queued song, pushes feedback."""
    data = request.json or {}
    nick = data.get("nick", "testuser")

    queue = sh.load_queue()
    removed = False
    removed_track = ""
    # Iterate in REVERSE to find the latest request
    for i in range(len(queue) - 1, -1, -1):
        q = queue[i]
        if q.get("requested_by", "").lower() == nick.lower() and q.get("status") in ("queued", "pushed"):
            removed_track = f"{q.get('track_name', 'Unknown')} \u2014 {q.get('artist', 'Unknown')}"
            sh.remove_from_queue(i, nick)
            removed = True
            break

    if removed:
        sh.push_song_feedback(
            nick, "success", "↩",
            f"@{nick} pulled {removed_track}",
            "Request removed from queue"
        )
        return jsonify({"success": True, "removed": removed_track, "feedback_pushed": True})
    else:
        sh.push_song_feedback(
            nick, "denied", "⊘",
            f"@{nick} — no pending request to pull"
        )
        return jsonify({"success": False, "message": "No pending request", "feedback_pushed": True})
