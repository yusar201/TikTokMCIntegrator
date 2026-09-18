"""Persistent operator bans, distinct from legacy revoke cleanup."""
import pytest
from flask import Flask
import spotify_handler as sh
from routes.spotify import spotify_bp

URI = 'spotify:track:7aw1kLNrWLe6j6bHTcXyZy'
OTHER = 'spotify:track:4uLU6hMCjMI75M1A2tKUQC'
TRACK = dict(uri=URI, name='Blocked song', artists='Artist', album='Album', album_image='', duration_ms=180000, explicit=False)

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    for attr, name in [('BLOCKLIST_FILE','blocklist.sqlite3'), ('CONFIG_FILE','config.json'), ('QUEUE_FILE','queue.json'), ('HISTORY_FILE','history.json'), ('BLOCKED_URIS_FILE','revoked.json')]:
        monkeypatch.setattr(sh, attr, str(tmp_path / name), raising=False)
    monkeypatch.setattr(sh, 'get_current_playback', lambda: {'is_playing': False, 'item': None})
    monkeypatch.setattr(sh, '_log_worker', lambda *a: None)
    def forbidden(*a, **kw):
        pytest.fail('Blocked operation must not contact Spotify')
    monkeypatch.setattr(sh, '_spotify_put', forbidden)
    monkeypatch.setattr(sh, '_spotify_post', forbidden)
    app = Flask(__name__)
    app.register_blueprint(spotify_bp, url_prefix='/api/spotify')
    return app.test_client()

def test_block_rejects_queue_and_every_explicit_start(isolated):
    response = isolated.post('/api/spotify/blocklist', json=TRACK)
    assert response.status_code == 200
    for result in [sh.add_to_queue(TRACK, 'viewer'), sh.play_track_immediate(URI), sh.queue_track(URI)]:
        assert result['code'] == 'song_blocked'
        assert 'blocked' in result['error'].lower()
    assert sh.load_queue() == []
    assert isolated.get('/api/spotify/blocklist').json[0]['uri'] == URI


def test_block_purges_pending_without_interrupting_other_song(isolated):
    sh.add_to_queue(TRACK, 'viewer')
    sh.add_to_queue(dict(TRACK, uri=OTHER), 'other')
    assert isolated.post('/api/spotify/blocklist', json=TRACK).status_code == 200
    assert [q['spotify_uri'] for q in sh.load_queue()] == [OTHER]


def test_worker_advance_skips_preexisting_blocked_queue_entries(isolated, monkeypatch):
    isolated.post('/api/spotify/blocklist', json=TRACK)
    sh.save_queue([dict(spotify_uri=URI, status='queued'), dict(spotify_uri=OTHER, status='queued')])
    calls = []
    monkeypatch.setattr(sh, '_spotify_put', lambda endpoint, data=None: calls.append((endpoint, data)) or {'success': True})
    assert sh.play_next_from_queue() is True
    assert [data['uris'] for endpoint, data in calls if endpoint == '/me/player/play'] == [[OTHER]]
    assert all(q.get('spotify_uri') != URI for q in sh.load_queue())


def test_current_blocked_song_pauses_and_moves_to_allowed_request(isolated, monkeypatch):
    sh.save_queue([dict(spotify_uri=URI, status='playing'), dict(spotify_uri=OTHER, status='queued')])
    monkeypatch.setattr(sh, 'get_current_playback', lambda: {'is_playing': True, 'item': {'uri': URI}})
    calls = []
    monkeypatch.setattr(sh, '_spotify_put', lambda endpoint, data=None: calls.append((endpoint, data)) or {'success': True})
    result = isolated.post('/api/spotify/blocklist', json=TRACK)
    assert result.status_code == 200
    assert calls[0][0] == '/me/player/pause'
    assert [data['uris'] for endpoint, data in calls if endpoint == '/me/player/play'] == [[OTHER]]
    assert sh.song_block_error(URI)['code'] == 'song_blocked'


def test_blocked_default_rejected_but_other_settings_remain_editable(isolated):
    sh.save_config(dict(sh.get_default_config(), loop_song_uri=URI))
    isolated.post('/api/spotify/blocklist', json=TRACK)
    # The dashboard posts every field. An unchanged blocked default must not
    # prevent saving unrelated settings; the playback guard still refuses it.
    assert isolated.post('/api/spotify/config', json={'loop_song_uri': URI, 'max_queue_total': 15}).status_code == 200
    assert sh.load_config()['max_queue_total'] == 15
    assert sh.load_config()['loop_song_uri'] == URI
    assert sh.play_track_immediate(URI)['code'] == 'song_blocked'
    assert isolated.post('/api/spotify/config', json={'loop_song_uri': OTHER}).status_code == 200
    assert isolated.post('/api/spotify/config', json={'loop_song_uri': URI}).status_code == 400


def test_unblock_persists_does_not_requeue_and_legacy_revokes_stay_separate(isolated):
    sh.add_blocked_uri(OTHER)
    isolated.post('/api/spotify/blocklist', json=TRACK)
    sh.remove_blocked_uri(OTHER)
    assert sh.song_block_error(URI)
    assert isolated.delete('/api/spotify/blocklist/' + URI.split(':')[-1]).status_code == 200
    assert isolated.get('/api/spotify/blocklist').json == []
    assert sh.load_queue() == []
    assert sh.add_to_queue(TRACK, 'viewer')['success']


def test_simulated_request_reports_blocked_without_starting_or_queueing(isolated, monkeypatch):
    isolated.post('/api/spotify/blocklist', json=TRACK)
    monkeypatch.setattr(sh, 'search_track', lambda *a, **kw: [TRACK])
    feedback = []
    monkeypatch.setattr(sh, 'push_song_feedback', lambda *a: feedback.append(a))
    result = isolated.post('/api/spotify/simulate/play', json={'query': 'song', 'nick': 'viewer'})
    assert result.status_code == 400
    assert result.json['code'] == 'song_blocked'
    assert 'blocked' in feedback[0][3]
    assert sh.load_queue() == []
    assert isolated.post('/api/spotify/queue', json=TRACK).json['code'] == 'song_blocked'
    assert isolated.get('/api/spotify/search?q=song').json[0]['blocked'] is True


@pytest.mark.parametrize('value', [None, [], {}, dict(TRACK, uri='spotify:album:7aw1kLNrWLe6j6bHTcXyZy'), dict(TRACK, name=''), dict(TRACK, album_image='javascript:alert(1)')])
def test_invalid_block_never_changes_policy(isolated, value):
    response = isolated.post('/api/spotify/blocklist', json=value)
    assert response.status_code == 400
    assert isolated.get('/api/spotify/blocklist').json == []


def test_stop_failure_keeps_ban_and_reports_warning(isolated, monkeypatch):
    monkeypatch.setattr(sh, 'get_current_playback', lambda: {'is_playing': True, 'item': {'uri': URI}})
    monkeypatch.setattr(sh, '_spotify_put', lambda *a, **kw: {'error': 'Spotify offline'})
    response = isolated.post('/api/spotify/blocklist', json=TRACK)
    assert response.status_code == 200
    assert response.json['warning']
    assert sh.song_block_error(URI)


def test_worker_detects_external_blocked_playback_and_never_starts_blocked_loop(isolated, monkeypatch):
    isolated.post('/api/spotify/blocklist', json=TRACK)
    sh.save_config(dict(sh.get_default_config(), loop_song_uri=URI))
    calls = []
    monkeypatch.setattr(sh, '_spotify_put', lambda endpoint, data=None: calls.append(endpoint) or {'success': True})
    monkeypatch.setattr(sh, 'get_valid_token', lambda: {'access_token': 'test'})
    monkeypatch.setattr(sh, 'get_current_playback', lambda: {'is_playing': True, 'item': {'uri': URI}})
    monkeypatch.setattr(sh, '_song_queue_running', True)
    def one_tick(_):
        sh._song_queue_running = False
    monkeypatch.setattr(sh.time, 'sleep', one_tick)
    sh.process_song_queue()
    assert calls == ['/me/player/pause']
    assert sh.song_block_error(URI)


def test_mid_song_pause_is_not_resumed_by_block_enforcement(isolated, monkeypatch):
    isolated.post('/api/spotify/blocklist', json=TRACK)
    assert sh.enforce_song_blocklist({'is_playing': False, 'item': {'uri': URI}}) == (False, None)


def test_corrupt_policy_refuses_new_playback(isolated):
    from pathlib import Path
    Path(sh.BLOCKLIST_FILE).write_text('broken database')
    assert sh.play_track_immediate(OTHER)['code'] == 'blocklist_unavailable'
    assert sh.add_to_queue(dict(TRACK, uri=OTHER), 'viewer')['code'] == 'blocklist_unavailable'


def test_block_between_repeat_and_start_is_still_refused(isolated, monkeypatch):
    calls = []
    def put(endpoint, data=None):
        calls.append(endpoint)
        if endpoint.startswith('/me/player/repeat'):
            isolated.post('/api/spotify/blocklist', json=TRACK)
        return {'success': True}
    monkeypatch.setattr(sh, '_spotify_put', put)
    assert sh.play_track_immediate(URI)['code'] == 'song_blocked'
    assert '/me/player/play' not in calls


def test_simulate_late_block_does_not_claim_success_or_mark_playing(isolated, monkeypatch):
    monkeypatch.setattr(sh, 'search_track', lambda *a, **kw: [TRACK])
    monkeypatch.setattr(sh, 'get_valid_token', lambda: {'access_token': 'fixture'})
    feedback = []
    monkeypatch.setattr(sh, 'push_song_feedback', lambda *a: feedback.append(a))
    def blocked_start(uri):
        sh.block_song(TRACK)
        return sh.song_block_error(uri)
    monkeypatch.setattr(sh, 'play_track_immediate', blocked_start)
    result = isolated.post('/api/spotify/simulate/play', json={'query': 'song'})
    assert result.status_code == 400
    assert result.json['code'] == 'song_blocked'
    assert not any(f[1] == 'success' for f in feedback)
    assert not any(q['status'] == 'playing' for q in sh.load_queue())
