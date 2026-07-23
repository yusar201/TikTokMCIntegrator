"""Spotify API routes."""

from flask import Blueprint, request, jsonify
import spotify_handler as sh

spotify_bp = Blueprint('spotify', __name__)


@spotify_bp.route("/config", methods=["GET"])
def get_song_config():
    """Get the song configuration."""
    cfg = sh.load_config()
    # Strip secrets for display
    safe = dict(cfg)
    safe["spotify_client_secret"] = "••••" if safe.get("spotify_client_secret") else ""
    return jsonify(safe)


@spotify_bp.route("/config", methods=["POST"])
def update_song_config():
    """Update the song configuration."""
    data = request.json
    cfg = sh.load_config()
    for key in data:
        if key in cfg:
            # Don't overwrite secrets with empty/masked values
            if key == "spotify_client_secret" and not data[key]:
                continue
            if key == "spotify_client_id" and not data[key]:
                continue
            cfg[key] = data[key]
    sh.save_config(cfg)
    return jsonify({"status": "success", "message": "Song config saved!"})


@spotify_bp.route("/auth-url", methods=["GET"])
def get_spotify_auth_url():
    """Get the Spotify authorization URL to start OAuth."""
    cfg = sh.load_config()
    client_id = cfg.get("spotify_client_id", "")
    redirect_uri = cfg.get("spotify_redirect_uri", "http://localhost:5000/api/spotify/callback")
    if not client_id:
        return jsonify({"error": "Spotify Client ID not configured"}), 400
    url = sh.get_auth_url(client_id, redirect_uri)
    return jsonify({"url": url})


@spotify_bp.route("/callback", methods=["GET"])
def spotify_callback():
    """Handle Spotify OAuth callback."""
    code = request.args.get("code")
    error = request.args.get("error")
    print(f"[SPOTIFY] Callback received — code={'present' if code else 'missing'}, error={error}")
    if error:
        return jsonify({"error": f"Spotify authorization denied: {error}"}), 400
    if not code:
        return jsonify({"error": "No authorization code received"}), 400

    cfg = sh.load_config()
    client_id = cfg.get("spotify_client_id", "")
    client_secret = cfg.get("spotify_client_secret", "")
    redirect_uri = cfg.get("spotify_redirect_uri", "http://localhost:5000/api/spotify/callback")

    result = sh.handle_callback(code, client_id, client_secret, redirect_uri)
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

    # Redirect back to dashboard
    return """
    <script>
      window.opener.postMessage({type: 'spotify-connected', status: 'success'}, '*');
      window.close();
    </script>
    <p>Connected! You can close this window.</p>
    """


@spotify_bp.route("/status", methods=["GET"])
def spotify_status():
    """Get the current Spotify connection status and playback info."""
    status = sh.get_connection_status()
    cfg = sh.load_config()
    status["enabled"] = cfg.get("enabled", True)
    status["has_credentials"] = bool(cfg.get("spotify_client_id", ""))
    return jsonify(status)


@spotify_bp.route("/disconnect", methods=["POST"])
def spotify_disconnect():
    """Disconnect from Spotify."""
    sh.clear_token()
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
    sh.push_song_feedback(
        nick, "success", "✓",
        f"@{nick} queued {track['name']} \u2014 {track['artists']}",
        f"Position #{pos} \u2022 Use !pull to remove your request"
    )

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
                    sh.play_track_immediate(track["uri"])
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
                    sh.play_track_immediate(track["uri"])
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
