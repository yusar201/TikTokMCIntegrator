"""Real released EXE/browser smoke, isolated storage and fixture search only."""
import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = Path('C:/Users/yusar/Pictures/song-default-preview')
TRACK = dict(uri='spotify:track:7aw1kLNrWLe6j6bHTcXyZy', name='Block-list test fixture', artists='Test artist', album='Test album', album_image='', duration_ms=180000, explicit=False)
with socket.socket() as s:
    assert s.connect_ex(('127.0.0.1', 5000)) != 0, 'Port 5000 occupied; refuse to launch'
folder = Path(tempfile.mkdtemp(prefix='tiktokmc-blocklist-'))
links = []
process = None
try:
    shutil.copy2(ROOT / 'release/TikTokMCIntegrator.exe', folder)
    for name in ('_internal', 'templates', 'static', 'addons'):
        link = folder / name
        subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(ROOT / 'release' / name)], check=True, capture_output=True)
        links.append(link)
    (folder / 'config/profiles').mkdir(parents=True)
    (folder / 'config/profiles/default.yml').write_text('configured: true\nSettings:\n  TikTokUsername: ""\n  MinecraftUsername: ""\n', encoding='utf-8')
    (folder / 'config/active_profile.txt').write_text('default', encoding='utf-8')
    (folder / 'data').mkdir()
    (folder / 'data/song_config.json').write_text('{"enabled":false}', encoding='utf-8')
    process = subprocess.Popen([str(folder / 'TikTokMCIntegrator.exe')], cwd=folder)
    for attempt in range(120):
        if process.poll() is not None:
            raise AssertionError('Isolated EXE exited before ready')
        try:
            with urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=1) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.5)
    else:
        raise AssertionError('Released EXE never became healthy')
    assert not (folder / 'data/song_spotify_token.json').exists()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width':1440, 'height':1100})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        # Only search is a fixture; HTML, JS, block/unblock and queue use the EXE.
        page.route('**/api/spotify/search?*', lambda route: route.fulfill(json=[TRACK]))
        page.goto('http://127.0.0.1:5000/')
        page.wait_for_function('typeof loadSongConfig === "function"')
        page.evaluate("document.querySelectorAll('.panel').forEach(e=>e.classList.remove('active')); document.querySelector('#panel-song').classList.add('active')")
        page.evaluate('loadSongConfig()')
        page.locator('#song-test-search').fill('test fixture')
        page.locator('#song-test-search').press('Enter')
        page.get_by_role('button', name='Block song', exact=True).click()
        page.wait_for_function('document.querySelector("#song-blocklist-count").textContent.includes("1")')
        print('BUTTON STATE:', page.evaluate("Array.from(document.querySelectorAll('.song-search-result button')).map(b=>({text:b.textContent,label:b.getAttribute('aria-label'),disabled:b.disabled,visible:!!b.getClientRects().length}))"))
        print('PANEL STATE:', page.locator('#panel-song').get_attribute('class'))
        print('SEARCH STATE:', ascii(page.locator('#song-test-results').inner_text()))
        import sqlite3
        db = sqlite3.connect(folder / 'data/song_blocklist.sqlite3')
        try:
            assert db.execute('SELECT uri FROM blocked_songs').fetchall() == [(TRACK['uri'],)]
        finally:
            db.close()
        page.screenshot(path=str(OUT / 'release-block-diagnostic.png'))
        # Font Awesome contributes to the accessible name in the full app.
        # Match the visible Queue text, then assert its actual disabled property.
        queue_button = page.locator('.song-search-result button').filter(has_text='Queue')
        assert queue_button.count() == 1
        assert queue_button.is_disabled()
        response = page.request.post('http://127.0.0.1:5000/api/spotify/queue', data=TRACK)
        assert response.status == 400, response.text()
        assert response.json()['code'] == 'song_blocked'
        page.reload()
        page.wait_for_function('typeof loadSongConfig === "function"')
        page.evaluate("document.querySelectorAll('.panel').forEach(e=>e.classList.remove('active')); document.querySelector('#panel-song').classList.add('active')")
        page.evaluate('loadSongConfig()')
        page.wait_for_function('document.querySelector("#song-blocklist-count").textContent.includes("1")')
        assert TRACK['name'] in page.locator('#song-blocklist-panel').inner_text()
        for theme in ('dark', 'light'):
            page.evaluate('(t)=>document.documentElement.setAttribute("data-theme",t)', theme)
            page.add_style_tag(content='* { transition:none!important; animation:none!important; }')
            page.locator('#song-blocklist-panel').screenshot(path=str(OUT / f'song-blocklist-release-{theme}.png'))
        page.locator('#song-blocklist-panel').get_by_role('button', name='Unblock', exact=True).click()
        page.wait_for_function('document.querySelector("#song-blocklist-count").textContent.includes("0")')
        assert page.request.get('http://127.0.0.1:5000/api/spotify/blocklist').json() == []
        # Queue, then block: existing queued copy must be removed by the actual EXE.
        assert page.request.post('http://127.0.0.1:5000/api/spotify/queue', data=TRACK).status == 200
        assert page.request.post('http://127.0.0.1:5000/api/spotify/blocklist', data=TRACK).status == 200
        queued = page.request.get('http://127.0.0.1:5000/api/spotify/queue').json()
        assert not any(q.get('spotify_uri') == TRACK['uri'] for q in queued), queued
        print('PASS: real released EXE /health, production JS block button, reload persistence, queue refusal, unblock, purge queued copy. Search fixture only; no Spotify token.')
        print('Browser page errors:', errors)
        assert not errors
        browser.close()
finally:
    if process is not None and process.poll() is None:
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
        process.wait(timeout=15)
    for link in reversed(links):
        if link.exists():
            link.rmdir()  # Remove junction itself, never traverse shared artifacts.
    shutil.rmtree(folder)
    with socket.socket() as s:
        assert s.connect_ex(('127.0.0.1',5000)) != 0, 'Test listener leaked'
    print('Cleanup: owned EXE tree stopped, disposable storage removed, port 5000 released.')
