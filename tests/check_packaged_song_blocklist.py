"""Exercise the deployed EXE's real Python modules with isolated storage.

This is packaged API verification, not a native-window or live Spotify test.
"""
import hashlib
import sys
import tempfile
import types
from pathlib import Path

from flask import Flask
from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
archive = CArchiveReader(str(ROOT / 'release/TikTokMCIntegrator.exe'))
pyz = archive.open_embedded_archive('PYZ.pyz')
assert hashlib.sha256((ROOT / 'release/TikTokMCIntegrator.exe').read_bytes()).digest() == hashlib.sha256((ROOT / 'dist/TikTokMCIntegrator/TikTokMCIntegrator.exe').read_bytes()).digest()

def packaged_module(name):
    mod = types.ModuleType(name)
    mod.__file__ = str(ROOT / (name.replace('.', '/') + '.py'))
    mod.__package__ = name.rpartition('.')[0]
    sys.modules[name] = mod
    exec(pyz.extract(name), mod.__dict__)
    return mod

sh = packaged_module('spotify_handler')
route_module = packaged_module('routes.spotify')
track = dict(uri='spotify:track:7aw1kLNrWLe6j6bHTcXyZy', name='Packaged API test fixture', artists='Fixture', album='', album_image='', duration_ms=1000, explicit=False)
with tempfile.TemporaryDirectory() as directory:
    for attr, name in [('BLOCKLIST_FILE', 'b.sqlite3'), ('CONFIG_FILE', 'config.json'), ('QUEUE_FILE', 'queue.json'), ('HISTORY_FILE', 'history.json')]:
        setattr(sh, attr, str(Path(directory) / name))
    sh.get_current_playback = lambda: {'is_playing': False, 'item': None}
    def forbidden(*args, **kwargs):
        raise AssertionError('No live Spotify writes in packaged smoke test')
    sh._spotify_put = forbidden
    sh._spotify_post = forbidden
    app = Flask(__name__)
    app.register_blueprint(route_module.spotify_bp, url_prefix='/api/spotify')
    c = app.test_client()
    assert c.get('/api/spotify/blocklist').json == []
    assert c.post('/api/spotify/blocklist', json=track).status_code == 200
    assert c.get('/api/spotify/blocklist').json[0]['uri'] == track['uri']
    assert c.post('/api/spotify/queue', json=track).json['code'] == 'song_blocked'
    assert sh.play_track_immediate(track['uri'])['code'] == 'song_blocked'
    assert c.delete('/api/spotify/blocklist/' + track['uri'].split(':')[-1]).status_code == 200
    assert c.get('/api/spotify/blocklist').json == []
    assert sh.load_queue() == []
print('PASS: deployed EXE matches dist; packaged GET/block/refuse queue/refuse playback/unblock. Temporary storage removed, no server or player calls.')
