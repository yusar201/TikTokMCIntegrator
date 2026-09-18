"""Isolated real UI + Flask API exercise; fixtures never touch live playback."""
import sys, tempfile, json
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import Flask, render_template
import spotify_handler as sh
from routes.spotify import spotify_bp
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = Path('C:/Users/yusar/Pictures/song-default-preview')
OUT.mkdir(parents=True, exist_ok=True)
# Captured by read_default_song_live.py using a real read-only Spotify lookup.
TRACK = json.loads((OUT / 'live-track.json').read_text(encoding='utf-8'))
URI = TRACK['uri']
OTHER = dict(TRACK, uri='spotify:track:4uLU6hMCjMI75M1A2tKUQC', name='Fixture alternate song')
with tempfile.TemporaryDirectory() as tmp:
    sh.CONFIG_FILE = str(Path(tmp) / 'song_config.json')
    sh.QUEUE_FILE = str(Path(tmp) / 'song_queue.json')
    sh.BLOCKLIST_FILE = str(Path(tmp) / 'blocklist.sqlite3')
    sh.save_config(dict(sh.get_default_config(), loop_song_uri=URI))
    def forbidden(*a, **kw):
        raise AssertionError('No live network or player calls in UI harness')
    for name in ('_spotify_get', 'play_track_immediate', 'play_next_from_queue', 'get_current_playback'):
        setattr(sh, name, forbidden)
    sh.get_default_track = lambda: dict(uri=URI, track=TRACK)
    sh.search_track = lambda query: {'error': 'Fixture Spotify disconnected'} if query == 'error' else [] if query == 'empty' else [TRACK, OTHER]
    app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    app.register_blueprint(spotify_bp, url_prefix='/api/spotify')
    @app.route('/')
    def index():
        return render_template('index.html')
    client = app.test_client()
    script = (ROOT / 'static/script.js').read_text(encoding='utf-8')
    funcs = script[script.index('let songBlocklist ='):script.index('async function fetchSongQueue()')]
    funcs += script[script.index('async function testSongSearch()'):script.index('// TTS CONFIG')]
    requests = []
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        def serve(route):
            url = urlsplit(route.request.url)
            if route.request.url == TRACK['album_image']:
                route.fulfill(body=(OUT / 'live-cover.jpg').read_bytes(), content_type='image/jpeg'); return
            if url.netloc != 'ui.test':
                route.abort(); return
            if url.path.endswith('.js'):
                route.fulfill(body='', content_type='application/javascript'); return
            requests.append((route.request.method, url.path))
            response = client.open(url.path + ('?' + url.query if url.query else ''), method=route.request.method, data=route.request.post_data, content_type=route.request.headers.get('content-type'))
            route.fulfill(status=response.status_code, body=response.data, content_type=response.content_type)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/*', serve)
        page.goto('http://ui.test/')
        page.add_style_tag(content='* { animation:none!important; transition:none!important; }')
        page.evaluate("""() => {
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            document.querySelector('#panel-song').classList.add('active');
        }""")
        page.evaluate("window.songConfig={}; window.showToast=(m,t)=>window.lastToast={message:m,type:t}; window.fetchSpotifyStatus=()=>{}; window.fetchSongQueue=()=>{}; window.esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('\"','&quot;');")
        page.add_script_tag(content=funcs)
        page.locator('#btn-save-song-config').evaluate('(el) => el.onclick = saveSongConfig')
        page.evaluate('loadSongConfig()')
        card = page.locator('#song-default-card')
        page.wait_for_function('document.querySelector("#song-default-card").textContent.includes("boba date")')
        assert card.locator('img').evaluate('e=>e.complete && e.naturalWidth>0')
        assert URI not in card.inner_text()
        page.locator('#song-default-card button.btn-secondary').click()
        assert page.locator('#song-test-search').evaluate('e=>e===document.activeElement')
        page.locator('#song-test-search').fill('boba date')
        page.locator('#song-test-search').press('Enter')
        page.wait_for_selector('.song-search-result')
        assert page.locator('.song-search-result').count() == 2
        # No implicit queue-on-row-click; choosing a default is not playback.
        page.locator('.song-search-result .song-row-title').first.click()
        page.get_by_role('button', name='Use as default').nth(1).click()
        assert 'Fixture alternate song' in card.inner_text()
        assert 'Unsaved' in page.locator('#song-default-status').inner_text()
        assert sh.load_config()['loop_song_uri'] == URI
        assert not any(method == 'POST' and path == '/api/spotify/queue' for method, path in requests)
        page.locator('#btn-save-song-config').click()
        page.wait_for_function('window.lastToast?.type === "success"')
        assert sh.load_config()['loop_song_uri'] == OTHER['uri']
        assert sh.load_config()['loop_song_track']['name'] == OTHER['name']
        page.evaluate('loadSongConfig()')
        assert 'Fixture alternate song' in card.inner_text()
        # Select the actual saved song again for real-data previews.
        page.get_by_role('button', name='Use as default').first.click()
        page.evaluate('saveSongConfig()')
        assert sh.load_config()['loop_song_uri'] == URI
        page.evaluate('loadSongConfig()')
        for theme, expected in [('dark', 'rgb(38, 43, 56)'), ('light', 'rgb(246, 231, 196)')]:
            page.evaluate('(t)=>document.documentElement.setAttribute("data-theme",t)', theme)
            page.evaluate('async()=>{await document.fonts.ready}')
            # The actual song cards, using the production styles and layout.
            field = page.locator('.song-default-field')
            field.screenshot(path=str(OUT / f'song-default-{theme}.png'))
            page.locator('section', has=page.locator('#song-test-search')).screenshot(path=str(OUT / f'song-search-{theme}.png'))
            assert card.evaluate('e=>getComputedStyle(e.closest("section")).backgroundColor') == expected
            from PIL import Image
            rgb = (38, 43, 56) if theme == 'dark' else (246, 231, 196)
            with Image.open(OUT / f'song-default-{theme}.png') as shot:
                assert shot.convert('RGB').getpixel((shot.width - 2, 2)) == rgb
            print(theme, 'computed surface and screenshot pixel:', rgb)
            for selector in ('.song-default-field', '.song-search-result'):
                for node in page.locator(selector).all():
                    assert node.evaluate('e=>e.scrollWidth<=e.clientWidth+1'), selector
        # Queue remains a separate explicit action using the real API and temp queue.
        page.get_by_role('button', name='Queue', exact=True).first.click()
        page.wait_for_function('window.lastToast?.message?.startsWith("Queued:")')
        assert len(sh.load_queue()) == 1
        assert sh.load_config()['loop_song_uri'] == URI
        page.locator('#song-default-card').get_by_role('button', name='Clear').click()
        assert 'No default song' in card.inner_text()
        page.evaluate('saveSongConfig()')
        assert sh.load_config()['loop_song_uri'] == ''
        assert sh.load_config()['loop_song_track'] is None
        page.locator('.song-default-field').screenshot(path=str(OUT / 'song-default-empty.png'))
        for query, message in [('empty', 'No results found.'), ('error', 'Fixture Spotify disconnected')]:
            page.locator('#song-test-search').fill(query)
            page.evaluate('testSongSearch()')
            assert message in page.locator('#song-test-results').inner_text()
        # Out-of-order metadata lookup must not override a new selection or clear.
        page.evaluate("""async (track) => {
            const original = window.fetch;
            let resolve;
            window.fetch = () => new Promise(r => resolve=r);
            const pending = loadDefaultSong({loop_song_uri: track.uri});
            selectDefaultSong(null);
            resolve({ok:true,json:async()=>({uri:track.uri,track})});
            await pending;
            window.fetch=original;
        }""", TRACK)
        assert 'No default song' in card.inner_text()
        # Rendering treats song metadata as text, not markup; broken cover has fallback.
        page.evaluate('selectDefaultSong', dict(TRACK, name='<img src=x onerror=alert(1)>', album_image='https://invalid.test/cover'))
        page.wait_for_selector('#song-default-card .song-art-placeholder')
        assert '<img src=x' in card.inner_text()
        page.set_viewport_size({'width': 680, 'height': 1100})
        page.evaluate('selectDefaultSong', TRACK)
        page.locator('#song-test-search').fill('boba date')
        page.evaluate('testSongSearch()')
        page.locator('.song-default-field').screenshot(path=str(OUT / 'song-default-narrow.png'))
        for selector in ('.song-default-field', '.song-search-result'):
            for node in page.locator(selector).all():
                assert node.evaluate('e=>e.scrollWidth<=e.clientWidth+1'), selector
        assert not errors, errors
        browser.close()
print('PASS: saved legacy metadata, real artwork, search Enter, draft/persist/reload, distinct Queue, clear, empty/error, stale response guard, escaped text, broken artwork, dark/light/narrow. No live player calls; browser closed; no server ports opened.')
