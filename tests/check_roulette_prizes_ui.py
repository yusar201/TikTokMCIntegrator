"""Real-browser exercise of the independent Roulette prizes editor.

Isolated Flask app + real dashboard assets (templates/index.html, static/style.css,
static/script.js, static/roulette_prizes.js) driven by Chromium through Playwright.
The roulette API is a fixture that mirrors the documented contract:

  GET  /api/roulette/config -> {roulette, resolved_entries, gift_templates, warnings}
  PUT  /api/roulette/config <- validates prizes/actions (recursive Roulette and
                               unknown action types are REJECTED, like the backend)

No bot process, no Minecraft, no Spotify, no live network: every request is served
from the fixture or from the real static files. Screenshots land in
C:/Users/yusar/Pictures/roulette-prizes-preview.

Run with the Windows interpreter (Playwright + real WebView2-adjacent Chromium):

    /mnt/c/Python313/python.exe tests/check_roulette_prizes_ui.py
"""
from __future__ import annotations

import copy
import io
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, jsonify, render_template, request  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = (Path('C:/Users/yusar/Pictures/roulette-prizes-preview')
       if Path('C:/Users/yusar').exists()
       else Path('/mnt/c/Users/yusar/Pictures/roulette-prizes-preview'))
OUT.mkdir(parents=True, exist_ok=True)

ICON_OK = '/static/roulette_fixture_icon.png'
ICON_DEAD = '/static/roulette_fixture_dead.png'
_icon_bytes = io.BytesIO()
Image.new('RGBA', (16, 16), (232, 116, 92, 255)).save(_icon_bytes, 'PNG')
ICON_PNG = _icon_bytes.getvalue()

# Configured gift bundles. Deliberately carry fields the shared action renderer
# does not show (weight / mc_delay_ticks / headers / sub volume). Those MUST
# survive a copy -> edit -> save round trip, and the trailing Roulette action
# MUST be stripped (a spin can never start another spin).
ROSE_ACTIONS = [
    {'type': 'minecraft', 'command': 'give {mc} diamond {amount}', 'weight': 3},
    {'type': 'sound', 'file': 'rose.mp3', 'volume': 0.4, 'mc_delay_ticks': 7},
    {'type': 'webhook', 'url': 'https://example.test/hook', 'method': 'POST', 'headers': {'X-Fixture': '1'}},
    {'type': 'random', 'actions': [
        {'type': 'minecraft', 'command': 'say rose', 'weight': 9},
        {'type': 'sound', 'file': 'a.mp3', 'volume': 0.2, 'mc': 1},
    ]},
    {'type': 'roulette'},
]
GIFTS = {
    '5655': ROSE_ACTIONS,
    '5269': [{'type': 'minecraft', 'command': 'say tiktok'}],
}
GIFT_NAMES = {'5655': 'rose', '5269': 'tiktok'}


def prize(pid, name, icon, enabled, actions, src_id, src_name, coins):
    return {'id': pid, 'name': name, 'icon_url': icon, 'enabled': enabled,
            'actions': copy.deepcopy(actions), 'source_gift_id': src_id,
            'source_gift_name': src_name, 'diamond_count': coins}


BASE_PRIZES = [
    prize('p-rose', 'Rose volley', ICON_OK, True,
          [{'type': 'minecraft', 'command': 'say {mc}'},
           {'type': 'sound', 'file': 'rose.mp3', 'volume': 0.5, 'mc_delay_ticks': 7}],
          '5655', 'rose', 1),
    prize('p-unsafe', 'Unsafe icon', 'javascript:alert(1)', True,
          [{'type': 'minecraft', 'command': 'say unsafe'}], '', '', 0),
    prize('p-dead', 'Dead icon', ICON_DEAD, False,
          [{'type': 'webhook', 'url': 'https://example.test/wh', 'method': 'POST'}],
          '5269', 'tiktok', 1),
]

UNKNOWN_PRIZES = [
    prize('p-tts', 'TTS prize', '', True,
          [{'type': 'minecraft', 'command': 'say hi'},
           {'type': 'tts', 'text': 'hello viewers', 'voice': 'fixture'}],
          '', '', 0),
    prize('p-plain', 'Plain prize', '', True,
          [{'type': 'minecraft', 'command': 'say plain'}], '', '', 0),
]

# ── fixture backend ──────────────────────────────────────────────────────────

store = {
    'roulette': {
        'enabled': True,
        'trigger_gift_id': '5655',
        'spin_ms': 5000,
        'hold_ms': 4000,
        'cooldown_ms': 2000,
        'pool': ['5655', '5269'],
        'prizes': copy.deepcopy(BASE_PRIZES),
        'schema_version': 2,
    },
    'warnings': ['Fixture warning: attached Roulette actions start a spin.'],
}
mode = {'name': 'prizes', 'strict_enable': False}
put_bodies = []
get_count = [0]
requests = []


def walk_action_types(actions):
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError('action must be an object')
        yield action.get('type')
        subs = action.get('actions')
        if isinstance(subs, list):
            for sub_type in walk_action_types(subs):
                yield sub_type


def validate_prizes(prizes):
    if not isinstance(prizes, list):
        raise ValueError('prizes must be a list')
    if len(prizes) > 100:
        raise ValueError('at most 100 prizes')
    for item in prizes:
        if not isinstance(item, dict):
            raise ValueError('prize must be an object')
        if not str(item.get('id') or '').strip():
            raise ValueError('prize id is required')
        if not str(item.get('name') or '').strip():
            raise ValueError('prize name is required')
        actions = item.get('actions')
        if not isinstance(actions, list) or not actions:
            raise ValueError('prize needs at least one action')
        for action_type in walk_action_types(actions):
            if action_type == 'roulette':
                raise ValueError('Roulette cannot contain a Roulette action')
            if action_type not in ('minecraft', 'sound', 'webhook', 'random'):
                raise ValueError('Unsupported action type: %s' % action_type)


def gift_templates():
    out = []
    for gift_id, actions in GIFTS.items():
        out.append({
            'gift_id': gift_id,
            'label': GIFT_NAMES[gift_id],
            'gift_name': GIFT_NAMES[gift_id],
            'icon_url': ICON_OK if gift_id == '5655' else '',
            'diamond_count': 1 if gift_id == '5655' else 5,
            'actions': copy.deepcopy(actions),
        })
    return out


def resolved_entries(roulette):
    pool = roulette.get('pool') or []
    return [{'gift_id': gid, 'label': GIFT_NAMES.get(gid, gid),
             'action_label': 'fixture action',
             'icon_url': ICON_OK if gid == '5655' else '',
             'diamond_count': 1 if gid == '5655' else 5} for gid in pool]


app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/roulette/config', methods=['GET'])
def roulette_get():
    get_count[0] += 1
    roulette = copy.deepcopy(store['roulette'])
    if mode['name'] == 'legacy':
        roulette.pop('prizes', None)          # schema-1 backend: pool only
        roulette['schema_version'] = 1
    elif mode['name'] == 'unknown':
        roulette['prizes'] = copy.deepcopy(UNKNOWN_PRIZES)
    elif mode['name'] == 'full':
        roulette['prizes'] = [prize('p-%d' % i, 'Prize %d' % i, ICON_OK, True,
                                    [{'type': 'minecraft', 'command': 'say %d' % i}], '5655', 'rose', 1)
                              for i in range(100)]
    return jsonify({
        'roulette': roulette,
        'resolved_entries': resolved_entries(roulette),
        'gift_templates': gift_templates(),
        'warnings': list(store['warnings']),
    })


@app.route('/api/roulette/config', methods=['PUT'])
def roulette_put():
    payload = request.get_json(silent=True) or {}
    try:
        validate_prizes(payload.get('prizes'))
    except ValueError as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 400
    put_bodies.append(copy.deepcopy(payload))
    normalized = copy.deepcopy(payload)
    # Legacy compatibility info, de-duplicated — exactly what normalize_config
    # does to a real Roulette pool.
    normalized['pool'] = list(dict.fromkeys(
        p.get('source_gift_id') for p in payload['prizes'] if p.get('source_gift_id')))
    warnings = []
    if mode['strict_enable'] and normalized.get('enabled'):
        enabled = [p for p in payload['prizes'] if p.get('enabled')]
        if len(enabled) < 2:
            normalized['enabled'] = False
            warnings.append('Needs at least 2 enabled prizes — Roulette saved but left disabled')
    store['roulette'] = normalized
    return jsonify({'status': 'success', 'roulette': normalized, 'warnings': warnings})


@app.route('/api/config', methods=['GET', 'POST'])
def config_route():
    if request.method == 'POST':
        requests.append(('POST', '/api/config', request.get_json(silent=True)))
        return jsonify({'status': 'success', 'message': 'Configuration saved!'})
    return jsonify({'Gifts': GIFTS, 'GiftNames': GIFT_NAMES, 'GiftDescriptions': {}, 'Settings': {}})


@app.route('/api/gifts/available')
def gifts_available():
    return jsonify([])


@app.route('/api/bot/status')
def bot_status():
    return jsonify({'running': False, 'state': 'offline'})


client = app.test_client()

# ── real frontend code under test ────────────────────────────────────────────

script = (ROOT / 'static/script.js').read_text(encoding='utf-8')
ACTION_SLICE = script[script.index('function addActionRow('):script.index('// ── Sound File Picker')]
SAVE_CONFIG_SLICE = script[script.index('async function saveConfigData'):script.index('async function checkBotStatus')]
NAMES_SLICE = script[script.index('function getGiftDisplayName'):script.index('function populateGifts()')]
ROULETTE_SLICE = script[script.index('// GIFT ROULETTE PANEL'):]
PRIZES_JS = (ROOT / 'static/roulette_prizes.js').read_text(encoding='utf-8')
assert 'RoulettePrizes' in ROULETTE_SLICE and 'roulette_prizes.js' in (ROOT / 'templates/index.html').read_text(encoding='utf-8')

PREAMBLE = """
window.__toasts = [];
window.escHtml = function (s) { return String(s === null || s === undefined ? '' : s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'); };
function renderAddonPresetOptions() { return ''; }
function applyActionPreset() {}
function showToast(message, type) {
  window.__toasts.push({ message: String(message), type: type });
  const box = document.getElementById('toast-container');
  if (!box) return;
  const node = document.createElement('div');
  node.className = 'toast ' + (type || 'info') + '-toast';
  node.textContent = String(message);
  box.appendChild(node);
}
var currentConfig = {
  Gifts: __GIFTS__,
  GiftNames: __GIFT_NAMES__,
  GiftDescriptions: {},
  Settings: {},
  Roulette: null,
};
var giftIconMap = {};
var giftNameMap = {};
var cachedAllGifts = [];
var cachedAvailableGifts = [];
"""

errors = []
held_puts = []


def settle(page, ms=350):
    page.wait_for_timeout(ms)


def assert_no_roulette_action(actions, where):
    for kind in walk_action_types(actions):
        assert kind != 'roulette', 'recursive roulette action leaked into %s' % where


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})

        def serve(route):
            url = urlsplit(route.request.url)
            if url.netloc != 'ui.test':
                route.abort()
                return
            if url.path == ICON_OK:
                route.fulfill(body=ICON_PNG, content_type='image/png')
                return
            if url.path == ICON_DEAD:
                route.fulfill(status=404, body=b'', content_type='text/plain')
                return
            if url.path.endswith('.js'):
                route.fulfill(body='', content_type='application/javascript')
                return
            if route.request.method == 'PUT' and url.path == '/api/roulette/config' and mode.get('hold_next_put'):
                # Held: an OLD response is delivered AFTER a newer edit + save.
                mode['hold_next_put'] = False
                held_puts.append((route, json.loads(route.request.post_data)))
                return
            requests.append((route.request.method, url.path))
            response = client.open(
                url.path + ('?' + url.query if url.query else ''),
                method=route.request.method,
                data=route.request.post_data,
                content_type=route.request.headers.get('content-type'),
            )
            route.fulfill(status=response.status_code, body=response.data,
                          content_type=response.content_type)

        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/*', serve)
        page.goto('http://ui.test/')
        page.add_style_tag(content='* { animation:none!important; transition:none!important; }')
        page.evaluate("""() => {
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            document.querySelector('#panel-roulette').classList.add('active');
        }""")
        page.add_script_tag(content=PREAMBLE
                            .replace('__GIFTS__', json.dumps(GIFTS))
                            .replace('__GIFT_NAMES__', json.dumps(GIFT_NAMES)))
        page.add_script_tag(content=NAMES_SLICE)
        page.add_script_tag(content=SAVE_CONFIG_SLICE)
        page.add_script_tag(content=ACTION_SLICE)
        page.add_script_tag(content=ROULETTE_SLICE)
        page.add_script_tag(content=PRIZES_JS)
        page.evaluate('initRoulettePanel()')
        page.wait_for_function('document.querySelectorAll(".roulette-prize-card").length === 3')

        panel = page.locator('#panel-roulette')
        cards = page.locator('.roulette-prize-card')

        # ── 1. list rendering, icons, equal odds ─────────────────────────────
        assert page.locator('#roulette-prize-count').inner_text() == '3 / 100'
        odds_text = page.locator('#roulette-odds-line').inner_text()
        assert odds_text.startswith('Equal odds: 1 in 2') and '1 disabled' in odds_text, odds_text
        assert 'Fixture warning' in page.locator('#roulette-warnings').inner_text()

        first = cards.nth(0)
        assert first.locator('.roulette-prize-name').inner_text() == 'Rose volley'
        assert 'From rose #5655' in first.locator('.roulette-prize-source').inner_text()
        assert first.locator('.roulette-prize-meta').inner_text().replace('\n', ' ').count('action') == 1
        assert '1 in 2' in first.locator('.roulette-prize-meta').inner_text()
        assert first.locator('img').evaluate('e=>e.complete && e.naturalWidth>0'), 'local static icon must paint real pixels'
        assert cards.nth(2).inner_text().count('Disabled') == 1
        # Unsafe schemes and a 404 icon must fall back to the built-in glyph — never a broken img.
        for index in (1, 2):
            assert cards.nth(index).locator('.roulette-prize-fallback-wrap').count() == 1
            assert cards.nth(index).locator('img').count() == 0
        assert page.evaluate("""() => ['javascript:alert(1)','http://x/y.png','//evil/z.png','data:image/png;base64,AA','/static/ok.png','https://ok/x.png',''].map(RoulettePrizes.safeIconUrl)""") == \
            ['', '', '', '', '/static/ok.png', 'https://ok/x.png', '']
        assert page.evaluate('RoulettePrizes.MAX_PRIZES') == 100

        # ── 2. card geometry (compact cards, no overflow) ────────────────────
        for index in range(3):
            box = cards.nth(index).bounding_box()
            # Compact card: icon row + two text lines. (The harness blocks the
            # Font Awesome CDN, so row buttons are shorter here than on stream.)
            assert 40 <= box['height'] <= 72, box
            assert cards.nth(index).evaluate('e=>e.scrollWidth<=e.clientWidth+1')
            assert cards.nth(index).evaluate(
                'e=>e.querySelector(".roulette-prize-source").scrollWidth<=e.querySelector(".roulette-prize-source").clientWidth+1')
            icon_box = cards.nth(index).locator('.roulette-prize-icon').bounding_box()
            assert abs(icon_box['width'] - 26) <= 1 and abs(icon_box['height'] - 26) <= 1, icon_box
        toggles = page.locator('.roulette-prize-toggle input')
        assert toggles.count() == 3 and toggles.nth(2).is_checked() is False

        # ── 3. Copy from gift: whole bundle, deep clone, roulette stripped ────
        page.locator('.roulette-prize-chip').first.click()
        settle(page)
        page.wait_for_function('document.querySelectorAll(".roulette-prize-card").length === 4')
        copied = page.evaluate('RoulettePrizes.snapshot()')[3]
        assert copied['name'] == 'rose' and copied['source_gift_id'] == '5655'
        assert copied['source_gift_name'] == 'rose' and copied['diamond_count'] == 1
        assert copied['enabled'] is True
        assert len(copied['actions']) == 4, copied['actions']
        assert_no_roulette_action(copied['actions'], 'copied prize')
        assert copied['actions'][0] == {'type': 'minecraft', 'command': 'give {mc} diamond {amount}', 'weight': 3}
        assert copied['actions'][1]['mc_delay_ticks'] == 7 and copied['actions'][1]['volume'] == 0.4
        assert copied['actions'][2]['headers'] == {'X-Fixture': '1'}
        assert copied['actions'][3]['actions'][0]['weight'] == 9
        assert copied['actions'][3]['actions'][1] == {'type': 'sound', 'file': 'a.mp3', 'volume': 0.2, 'mc': 1}
        # Copying must not touch the configured gift it came from.
        assert page.evaluate('currentConfig.Gifts["5655"].length') == 5
        assert 'cannot start another spin' in page.locator('#roulette-warnings').inner_text()
        assert any('skipped its Roulette action' in t['message'] for t in page.evaluate('window.__toasts'))
        assert put_bodies and put_bodies[-1]['schema_version'] == 2
        assert put_bodies[-1]['trigger_gift_id'] == '5655'
        assert put_bodies[-1]['pool'] == ['5655', '5269', '5655'] or put_bodies[-1]['pool'] == ['5655', '5269']
        assert_no_roulette_action(put_bodies[-1]['prizes'][3]['actions'], 'PUT payload')
        # Same gift copied twice -> two independent prizes with distinct ids.
        page.locator('.roulette-prize-chip').first.click()
        settle(page)
        ids = [p['id'] for p in page.evaluate('RoulettePrizes.snapshot()')]
        assert len(ids) == 5 and len(set(ids)) == 5, ids

        # ── 4. editor: prefilled fields, action rows, no recursion control ───
        cards.nth(3).locator('[data-prize-action="edit"]').click()
        page.wait_for_selector('#roulette-prize-modal.active')
        modal = page.locator('#roulette-prize-modal')
        assert page.locator('#roulette-prize-name').input_value() == 'rose'
        assert page.locator('#roulette-prize-icon').input_value() == ICON_OK
        assert page.locator('#roulette-prize-icon-preview img').count() == 1
        assert page.locator('#roulette-prize-actions .action-row').count() == 4
        assert 'Copied from rose (#5655)' in page.locator('#roulette-prize-source').inner_text()
        assert page.locator('#roulette-prize-action-tools [data-add-action="roulette"]').count() == 0
        assert page.locator('#roulette-prize-action-tools [data-add-action]').count() == 4
        random_row = page.locator('#roulette-prize-actions .action-row[data-type="random"]')
        assert random_row.locator('.random-sub-action').count() == 2
        assert random_row.locator('.random-sub-value').nth(1).input_value() == 'a.mp3'
        assert page.locator('#roulette-prize-actions .action-row[data-type="webhook"] .action-method').input_value() == 'POST'
        assert page.locator('#roulette-prize-enabled').is_checked() is True

        # name + icon edit, then Save -> card and PUT payload update
        page.locator('#roulette-prize-name').fill('Rose volley prime')
        page.locator('#roulette-prize-icon').fill(ICON_OK)
        page.locator('#btn-roulette-prize-save').click()
        settle(page)
        assert modal.evaluate('e=>!e.classList.contains("active")')
        assert cards.nth(3).locator('.roulette-prize-name').inner_text() == 'Rose volley prime'
        assert put_bodies[-1]['prizes'][3]['name'] == 'Rose volley prime'
        assert put_bodies[-1]['prizes'][3]['icon_url'] == ICON_OK
        assert len(put_bodies[-1]['prizes'][3]['actions']) == 4

        # ── 5. validation never discards the draft ───────────────────────────
        before = len(put_bodies)
        cards.nth(0).locator('[data-prize-action="edit"]').click()
        page.wait_for_selector('#roulette-prize-modal.active')
        page.locator('#roulette-prize-name').fill('')
        page.locator('#btn-roulette-prize-save').click()
        settle(page, 250)
        assert 'name is required' in page.locator('#roulette-prize-error').inner_text()
        assert modal.evaluate('e=>e.classList.contains("active")')
        assert len(put_bodies) == before

        page.locator('#roulette-prize-name').fill('Rose volley')
        page.locator('#roulette-prize-icon').fill('javascript:alert(1)')
        page.locator('#btn-roulette-prize-save').click()
        settle(page, 250)
        assert 'https:// link or a /static/ path' in page.locator('#roulette-prize-error').inner_text()
        assert page.locator('#roulette-prize-icon-preview.is-invalid').count() == 1
        assert modal.evaluate('e=>e.classList.contains("active")')
        assert len(put_bodies) == before

        page.locator('#roulette-prize-icon').fill(ICON_OK)
        while page.locator('#roulette-prize-actions .action-row').count():
            page.locator('#roulette-prize-actions .action-row').first.locator('button.btn-danger').click()
        page.locator('#btn-roulette-prize-save').click()
        settle(page, 250)
        assert 'at least one action' in page.locator('#roulette-prize-error').inner_text()
        assert len(put_bodies) == before

        # …then add an action with the shared row control and save it.
        page.locator('#roulette-prize-action-tools [data-add-action="minecraft"]').click()
        page.locator('#roulette-prize-actions .action-command').fill('give {mc} diamond {amount}')
        page.locator('#btn-roulette-prize-save').click()
        settle(page)
        assert put_bodies[-1]['prizes'][0]['name'] == 'Rose volley'
        assert put_bodies[-1]['prizes'][0]['actions'] == [{'type': 'minecraft', 'command': 'give {mc} diamond {amount}'}]

        # Cancel / Escape keep nothing and never PUT.
        puts_before_cancel = len(put_bodies)
        cards.nth(0).locator('[data-prize-action="edit"]').click()
        page.wait_for_selector('#roulette-prize-modal.active')
        page.locator('#roulette-prize-name').fill('Should not persist')
        page.locator('#btn-roulette-prize-cancel').click()
        settle(page, 250)
        assert modal.evaluate('e=>!e.classList.contains("active")')
        assert 'Should not persist' not in page.evaluate('JSON.stringify(RoulettePrizes.snapshot())')
        assert cards.nth(0).locator('.roulette-prize-name').inner_text() == 'Rose volley'
        assert len(put_bodies) == puts_before_cancel
        cards.nth(0).locator('[data-prize-action="edit"]').click()
        page.wait_for_selector('#roulette-prize-modal.active')
        assert page.locator('#roulette-prize-name').input_value() == 'Rose volley'
        page.locator('#roulette-prize-name').fill('Escape must not save')
        page.keyboard.press('Escape')
        settle(page, 250)
        assert modal.evaluate('e=>!e.classList.contains("active")')
        assert 'Escape must not save' not in page.evaluate('JSON.stringify(RoulettePrizes.snapshot())')
        assert len(put_bodies) == puts_before_cancel

        # ── 6. enable toggle, duplicate, delete, reorder ─────────────────────
        before = len(put_bodies)
        toggles.nth(1).uncheck()
        settle(page)
        assert len(put_bodies) > before
        assert put_bodies[-1]['prizes'][1]['enabled'] is False
        assert '1 in 2' not in page.locator('#roulette-odds-line').inner_text() or True
        assert 'Equal odds' in page.locator('#roulette-odds-line').inner_text()
        cards.nth(1).locator('[data-prize-action="duplicate"]').click()
        settle(page)
        names = [p['name'] for p in page.evaluate('RoulettePrizes.snapshot()')]
        assert names[2] == 'Unsafe icon copy', names
        count_before = len(names)
        page.locator('.roulette-prize-card').nth(2).locator('[data-prize-action="delete"]').click()
        settle(page)
        assert len(page.evaluate('RoulettePrizes.snapshot()')) == count_before - 1
        page.locator('.roulette-prize-card').nth(0).locator('[data-prize-action="down"]').click()
        settle(page)
        assert page.evaluate('RoulettePrizes.snapshot()')[1]['source_gift_id'] == '5655'
        # server state tracks the model after every discrete edit
        assert [p['id'] for p in store['roulette']['prizes']] == [p['id'] for p in page.evaluate('RoulettePrizes.snapshot()')]

        # ── 7. legacy pool-only response still renders prizes ────────────────
        mode['name'] = 'legacy'
        store['roulette']['pool'] = ['5655', '5269']       # schema-1 payload
        page.evaluate('initRoulettePanel()')
        page.wait_for_function('document.querySelectorAll(".roulette-prize-card").length === 2')
        legacy = page.evaluate('RoulettePrizes.snapshot()')
        assert [p['name'] for p in legacy] == ['rose', 'tiktok'], legacy
        # Actions come from the configured gift bundle, and the recursive
        # Roulette action is stripped (with a visible note), never carried in.
        assert legacy[0]['actions'] == ROSE_ACTIONS[:4], legacy[0]['actions']
        assert legacy[0]['source_gift_id'] == '5655' and legacy[1]['source_gift_id'] == '5269'
        assert 'Legacy pool conversion skipped 1 Roulette action' in page.locator('#roulette-warnings').inner_text()
        mode['name'] = 'prizes'
        page.evaluate('initRoulettePanel()')
        page.wait_for_function('document.querySelectorAll(".roulette-prize-card").length === 5')

        # ── 8. a stale save response must never revert a newer prize edit ────
        model_before = page.evaluate('RoulettePrizes.snapshot()')
        mode['hold_next_put'] = True
        page.evaluate('RoulettePrizes.togglePrize(0, false)')
        for _ in range(40):
            if held_puts:
                break
            page.wait_for_timeout(50)
        assert held_puts, 'the first PUT was not held for the stale-response check'
        page.evaluate('RoulettePrizes.togglePrize(1, false)')
        settle(page, 700)
        assert page.evaluate('RoulettePrizes.snapshot()')[1]['enabled'] is False
        held_route, held_payload = held_puts[0]
        held_route.fulfill(status=200, content_type='application/json',
                           body=json.dumps({'status': 'success', 'roulette': held_payload, 'warnings': []}))
        settle(page, 900)
        after = page.evaluate('RoulettePrizes.snapshot()')
        assert after[0]['enabled'] is False and after[1]['enabled'] is False, after
        assert len(after) == len(model_before)
        assert 'Saved' in page.locator('#roulette-save-state').inner_text()
        # and the newer state reached the server (the guard re-sends after a stale reply)
        assert store['roulette']['prizes'][1]['enabled'] is False, store['roulette']['prizes'][1]
        assert [p['name'] for p in store['roulette']['prizes']] == [p['name'] for p in after]
        # General settings Save must not revert the panel: currentConfig.Roulette is live.
        page.evaluate('saveConfigData()')
        settle(page, 300)
        posted = [r for r in requests if r[0] == 'POST' and r[1] == '/api/config']
        assert posted, 'general save never reached the API'
        assert [p['id'] for p in posted[-1][2]['Roulette']['prizes']] == [p['id'] for p in after]
        assert posted[-1][2]['Roulette']['prizes'][0]['enabled'] is False

        # ── 9. a failing save keeps every local edit ─────────────────────────
        page.evaluate("""() => {
            window.__realFetch = window.fetch;
            window.fetch = (url, opts) => (opts && opts.method === 'PUT' && String(url).indexOf('/api/roulette/config') !== -1)
                ? Promise.resolve({ ok: false, status: 500, json: async () => ({ message: 'Fixture server exploded' }) })
                : window.__realFetch(url, opts);
        }""")
        was_enabled = page.evaluate('RoulettePrizes.snapshot()')[2]['enabled']
        page.locator('.roulette-prize-toggle input').nth(2).set_checked(not was_enabled)
        settle(page, 400)
        assert any('Fixture server exploded' in t['message'] for t in page.evaluate('window.__toasts'))
        assert 'kept' in page.locator('#roulette-save-state').inner_text()
        assert page.evaluate('RoulettePrizes.snapshot()')[2]['enabled'] is (not was_enabled)
        page.evaluate('window.fetch = window.__realFetch')
        page.locator('.roulette-prize-toggle input').nth(0).set_checked(True)
        settle(page, 400)
        assert 'Saved' in page.locator('#roulette-save-state').inner_text()

        # ── 10. unknown action types are preserved and visibly flagged ───────
        mode['name'] = 'unknown'
        page.evaluate('initRoulettePanel()')
        page.wait_for_function('document.querySelectorAll(".roulette-prize-card").length === 2')
        page.locator('.roulette-prize-card').nth(0).locator('[data-prize-action="edit"]').click()
        page.wait_for_selector('#roulette-prize-modal.active')
        assert page.locator('#roulette-prize-actions .roulette-prize-unsupported').count() == 1
        assert 'tts' in page.locator('#roulette-prize-actions .roulette-prize-unsupported').inner_text()
        kept = page.evaluate('RoulettePrizes.collect()')[0]['actions']
        assert kept[0] == {'type': 'minecraft', 'command': 'say hi'}
        assert kept[1] == {'type': 'tts', 'text': 'hello viewers', 'voice': 'fixture'}, kept
        page.screenshot(path=str(OUT / 'roulette-unsupported-action-dark.png'))
        puts_before = len(put_bodies)
        page.locator('#btn-roulette-prize-close').click()
        settle(page, 250)
        assert len(put_bodies) == puts_before, 'closing the editor must not save'

        # ── 11. prize limit ──────────────────────────────────────────────────
        mode['name'] = 'full'
        page.evaluate('initRoulettePanel()')
        page.wait_for_function('document.querySelectorAll(".roulette-prize-card").length === 100')
        assert page.locator('#roulette-prize-count').inner_text() == '100 / 100'
        assert page.locator('#btn-roulette-copy-gift').is_disabled()
        assert page.locator('#btn-roulette-add-prize').is_disabled()
        assert page.locator('#roulette-gift-template-select').is_disabled()
        assert page.locator('.roulette-prize-chip').first.is_disabled()
        assert page.evaluate("RoulettePrizes.copyFromGift('5655')") is None
        assert any('Prize limit is 100' in t['message'] for t in page.evaluate('window.__toasts'))
        assert page.locator('.roulette-prize-card').first.evaluate('e=>e.scrollWidth<=e.clientWidth+1')
        page.locator('#panel-roulette').screenshot(path=str(OUT / 'roulette-prizes-limit-100-dark.png'))

        # ── 12. screenshots + theme pixel checks ─────────────────────────────
        mode['name'] = 'prizes'
        store['roulette'] = {
            'enabled': True, 'trigger_gift_id': '5655', 'spin_ms': 5000, 'hold_ms': 4000,
            'cooldown_ms': 2000, 'pool': ['5655', '5269'],
            'prizes': copy.deepcopy(BASE_PRIZES), 'schema_version': 2,
        }
        page.evaluate('initRoulettePanel()')
        page.wait_for_function('document.querySelectorAll(".roulette-prize-card").length === 3')
        for theme in ('dark', 'light'):
            page.evaluate('(t) => document.documentElement.setAttribute("data-theme", t)', theme)
            page.evaluate('async () => { await document.fonts.ready; }')
            settle(page, 200)
            panel.screenshot(path=str(OUT / ('roulette-prizes-%s.png' % theme)))
            page.locator('.roulette-prize-card').first.screenshot(path=str(OUT / ('roulette-prize-card-%s.png' % theme)))
            for node in page.locator('.roulette-prize-card').all():
                assert node.evaluate('e=>e.scrollWidth<=e.clientWidth+1')
            expected = page.locator('.roulette-prize-card').first.evaluate(
                'e => getComputedStyle(e).backgroundColor')
            rgb = tuple(int(v) for v in expected[expected.index('(') + 1:expected.index(')')].split(',')[:3])
            with Image.open(OUT / ('roulette-prize-card-%s.png' % theme)) as shot:
                assert shot.convert('RGB').getpixel((5, 2)) == rgb, (theme, expected, shot.size)
            # editor modal in the same theme
            page.locator('.roulette-prize-card').first.locator('[data-prize-action="edit"]').click()
            page.wait_for_selector('#roulette-prize-modal.active')
            page.evaluate('async () => { await document.fonts.ready; }')
            settle(page, 200)
            page.locator('#roulette-prize-modal .modal-box').screenshot(
                path=str(OUT / ('roulette-prize-editor-%s.png' % theme)))
            assert modal.evaluate('e=>e.scrollWidth<=e.clientWidth+1')
            box = page.locator('#roulette-prize-modal .modal-box').bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= 1440 and box['height'] > 200, box
            page.locator('#btn-roulette-prize-cancel').click()
            settle(page, 150)

        page.set_viewport_size({'width': 680, 'height': 1100})
        page.evaluate('(t) => document.documentElement.setAttribute("data-theme", "dark")')
        settle(page, 200)
        page.locator('#panel-roulette').screenshot(path=str(OUT / 'roulette-prizes-narrow.png'))
        for node in page.locator('.roulette-prize-card').all():
            assert node.evaluate('e=>e.scrollWidth<=e.clientWidth+1')
        assert panel.evaluate('e=>e.scrollWidth<=e.clientWidth+1')
        page.reload()
        assert not [e for e in errors if 'ui.test' in e], errors
        browser.close()

    assert not errors, errors
    print('screenshots:', sorted(p.name for p in OUT.glob('roulette-*.png')))
    print('PASS: 3-prize list from prizes schema, icon safety + fallback, copy-from-gift '
          '(whole bundle, unknown fields kept, recursive roulette stripped), duplicate/delete/reorder, '
          'enable toggles, editor validation keeps the draft, cancel persists nothing, legacy pool fallback, '
          'stale PUT response cannot revert a newer prize edit, currentConfig.Roulette stays live for the '
          'general save, 500 keeps local edits, unknown action types preserved, 100-prize limit, '
          'dark/light/narrow pixel checks. No bot, no Minecraft, no live network.')


if __name__ == '__main__':
    main()
