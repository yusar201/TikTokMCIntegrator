"""Default song editing: isolated config, never contacts Spotify."""
import json
import pytest
from flask import Flask
import spotify_handler as sh
from routes.spotify import spotify_bp

TRACK = '7aw1kLNrWLe6j6bHTcXyZy'
URI = 'spotify:track:' + TRACK

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(sh, 'CONFIG_FILE', str(tmp_path / 'song_config.json'))
    app = Flask(__name__)
    app.register_blueprint(spotify_bp, url_prefix='/api/spotify')
    return app.test_client()

@pytest.mark.parametrize('value', [URI, 'https://open.spotify.com/track/' + TRACK + '?si=example', '  ' + URI + '  ', 'https://open.spotify.com/intl-id/track/' + TRACK])
def test_save_normalizes_track_and_survives_reload(client, value):
    response = client.post('/api/spotify/config', json={'loop_song_uri': value})
    assert response.status_code == 200
    assert client.get('/api/spotify/config').json['loop_song_uri'] == URI
    assert json.loads(open(sh.CONFIG_FILE, encoding='utf-8').read())['loop_song_uri'] == URI

@pytest.mark.parametrize('value', ['https://example.com/track/' + TRACK, 'spotify:playlist:' + TRACK, 'https://open.spotify.com/album/' + TRACK, 'bad', None, 123, {}, 'spotify:track:short'])
def test_invalid_track_rejects_entire_update(client, value):
    sh.save_config(dict(sh.get_default_config(), loop_song_uri=URI))
    before = open(sh.CONFIG_FILE, encoding='utf-8').read()
    response = client.post('/api/spotify/config', json={'loop_song_uri': value, 'enabled': False})
    assert response.status_code == 400
    assert 'error' in response.json
    assert open(sh.CONFIG_FILE, encoding='utf-8').read() == before

def test_clear_and_partial_update_preserve_other_settings(client):
    sh.save_config(dict(sh.get_default_config(), loop_song_uri=URI))
    assert client.post('/api/spotify/config', json={'max_queue_total': 17}).status_code == 200
    assert sh.load_config()['loop_song_uri'] == URI
    assert client.post('/api/spotify/config', json={'loop_song_uri': '  '}).status_code == 200
    assert sh.load_config()['loop_song_uri'] == ''
    assert sh.load_config()['max_queue_total'] == 17

def test_default_config_contains_empty_loop(client):
    assert client.get('/api/spotify/config').json['loop_song_uri'] == ''

def test_save_never_changes_playback_or_queue(client, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Config save must not control playback or queue')
    for name in ('play_track_immediate', 'play_next_from_queue', 'save_queue', 'get_current_playback'):
        monkeypatch.setattr(sh, name, forbidden)
    assert client.post('/api/spotify/config', json={'loop_song_uri': URI}).status_code == 200

@pytest.mark.parametrize('value', [[], None, 'bad'])
def test_non_object_rejected(client, value):
    assert client.post('/api/spotify/config', data=json.dumps(value), content_type='application/json').status_code == 400
