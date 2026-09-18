"""Read-only Spotify metadata smoke check; no player calls or config writes."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import spotify_handler as sh
ROOT = Path(__file__).resolve().parents[1]
sh.CONFIG_FILE = str(ROOT / 'release/data/song_config.json')
sh.TOKEN_FILE = str(ROOT / 'release/data/song_spotify_token.json')
for name in ('play_track_immediate', 'play_next_from_queue', 'get_current_playback', 'save_queue'):
    setattr(sh, name, lambda *a, **kw: (_ for _ in ()).throw(AssertionError('No player calls allowed')))
result = sh.get_default_track()
print(json.dumps(result, ensure_ascii=True))
if result.get('track'):
    out = Path('C:/Users/yusar/Pictures/song-default-preview')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'live-track.json').write_text(json.dumps(result['track']), encoding='utf-8')
    import requests
    image = requests.get(result['track']['album_image'], timeout=20)
    image.raise_for_status()
    (out / 'live-cover.jpg').write_bytes(image.content)
    print('Saved real metadata and cover for browser verification.')
