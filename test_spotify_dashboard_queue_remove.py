import json

from flask import Flask

import spotify_handler as sh
from routes.spotify import spotify_bp


def _client(tmp_path, entries):
    queue_file = tmp_path / "song_queue.json"
    queue_file.write_text(json.dumps(entries), encoding="utf-8")
    original_queue_file = sh.QUEUE_FILE
    original_blocked_file = sh.BLOCKED_URIS_FILE
    sh.QUEUE_FILE = str(queue_file)
    sh.BLOCKED_URIS_FILE = str(tmp_path / "song_blocked_uris.json")

    app = Flask(__name__)
    app.register_blueprint(spotify_bp, url_prefix="/api/spotify")

    client = app.test_client()
    client._queue_file = queue_file
    client._restore_spotify_paths = lambda: _restore(original_queue_file, original_blocked_file)
    return client


def _restore(queue_file, blocked_file):
    sh.QUEUE_FILE = queue_file
    sh.BLOCKED_URIS_FILE = blocked_file


def test_dashboard_can_remove_any_queued_song(tmp_path):
    client = _client(tmp_path, [
        {"track_name": "God's Plan", "artist": "Drake", "spotify_uri": "spotify:track:1", "requested_by": "educationwithinu", "status": "queued"},
        {"track_name": "Next Song", "artist": "Artist", "spotify_uri": "spotify:track:2", "requested_by": "other", "status": "queued"},
    ])
    try:
        res = client.delete("/api/spotify/queue/1")

        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["removed"]["track_name"] == "God's Plan"
        remaining = json.loads(client._queue_file.read_text(encoding="utf-8"))
        assert [q["track_name"] for q in remaining] == ["Next Song"]
    finally:
        client._restore_spotify_paths()


def test_dashboard_still_cannot_remove_currently_playing_song(tmp_path):
    client = _client(tmp_path, [
        {"track_name": "Currently Playing", "artist": "Artist", "spotify_uri": "spotify:track:1", "requested_by": "viewer", "status": "playing"},
    ])
    try:
        res = client.delete("/api/spotify/queue/1")

        assert res.status_code == 400
        data = res.get_json()
        assert "currently playing" in data["error"].lower()
        remaining = json.loads(client._queue_file.read_text(encoding="utf-8"))
        assert remaining[0]["track_name"] == "Currently Playing"
    finally:
        client._restore_spotify_paths()
