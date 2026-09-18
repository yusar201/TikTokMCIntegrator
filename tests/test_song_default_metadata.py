"""Default picker display-only metadata; no live Spotify access."""
import pytest
from flask import Flask
import spotify_handler as sh
from routes.spotify import spotify_bp

URI = 'spotify:track:7aw1kLNrWLe6j6bHTcXyZy'
OTHER = 'spotify:track:4uLU6hMCjMI75M1A2tKUQC'
TRACK = dict(uri=URI, name='A song', artists='An artist', album='Album', album_image='https://i.scdn.co/image/test', duration_ms=123000, explicit=False)

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(sh, 'CONFIG_FILE', str(tmp_path / 'song_config.json'))
    for name in ('play_track_immediate', 'play_next_from_queue', 'save_queue', 'get_current_playback'):
        monkeypatch.setattr(sh, name, lambda *a, **kw: pytest.fail('Display/settings must not touch player or queue'))
    monkeypatch.setattr(sh, '_spotify_get', lambda *a, **kw: pytest.fail('Unexpected network call'))
    app = Flask(__name__)
    app.register_blueprint(spotify_bp, url_prefix='/api/spotify')
    return app.test_client()

def test_picked_metadata_survives_reload_without_network(client):
    assert client.post('/api/spotify/config', json={'loop_song_uri': URI, 'loop_song_track': TRACK}).status_code == 200
    assert sh.load_config()['loop_song_track'] == TRACK
    assert client.get('/api/spotify/default-track').json == {'uri': URI, 'track': TRACK}
    assert client.post('/api/spotify/config', json={'max_queue_total': 17}).status_code == 200
    assert sh.load_config()['loop_song_track'] == TRACK

@pytest.mark.parametrize('value', [[], 'bad', {**TRACK, 'uri': OTHER}, {**TRACK, 'name': None}, {**TRACK, 'duration_ms': 'bad'}, {**TRACK, 'album_image': 'javascript:alert(1)'}])
def test_bad_metadata_rejects_entire_update(client, value):
    sh.save_config(dict(sh.get_default_config(), loop_song_uri=URI))
    before = sh.load_config()
    r = client.post('/api/spotify/config', json={'loop_song_uri': URI, 'loop_song_track': value, 'enabled': False})
    assert r.status_code == 400
    assert sh.load_config() == before

def test_change_uri_and_clear_drop_old_metadata(client):
    client.post('/api/spotify/config', json={'loop_song_uri': URI, 'loop_song_track': TRACK})
    client.post('/api/spotify/config', json={'loop_song_uri': OTHER})
    assert sh.load_config()['loop_song_track'] is None
    client.post('/api/spotify/config', json={'loop_song_uri': ''})
    assert client.get('/api/spotify/default-track').json == {'uri': '', 'track': None}

def test_legacy_uri_resolves_and_caches_without_config_write(client, monkeypatch):
    sh.save_config(dict(sh.get_default_config(), loop_song_uri=URI))
    before = open(sh.CONFIG_FILE, encoding='utf-8').read()
    monkeypatch.setattr(sh, '_default_track_cache', {})
    calls = []
    def lookup(endpoint):
        calls.append(endpoint)
        return dict(uri=URI, name='A song', artists=[{'name': 'An artist'}], album={'name': 'Album', 'images': [{'url': TRACK['album_image']}]}, duration_ms=123000, explicit=False)
    monkeypatch.setattr(sh, '_spotify_get', lookup)
    for _ in range(2):
        r = client.get('/api/spotify/default-track')
        assert r.status_code == 200
        assert r.json['track'] == TRACK
    assert calls == ['/tracks/' + URI.rsplit(':', 1)[1]]
    assert open(sh.CONFIG_FILE, encoding='utf-8').read() == before

def test_lookup_failure_preserves_uri_and_throttles_retries(client, monkeypatch):
    sh.save_config(dict(sh.get_default_config(), loop_song_uri=URI))
    monkeypatch.setattr(sh, '_default_track_cache', {})
    calls = []
    def fail(endpoint):
        calls.append(endpoint)
        return {'error': 'Connect Spotify to load song details.'}
    monkeypatch.setattr(sh, '_spotify_get', fail)
    for _ in range(2):
        r = client.get('/api/spotify/default-track')
        assert r.json == {'uri': URI, 'track': None, 'error': 'Connect Spotify to load song details.'}
    assert len(calls) == 1
    assert sh.load_config()['loop_song_uri'] == URI
