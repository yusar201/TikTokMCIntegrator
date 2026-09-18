"""Real Roulette UI functions -> real Flask routes -> isolated YAML files."""
import json
from urllib.parse import urlsplit
import pytest
from playwright.sync_api import sync_playwright
import app as module
from test_roulette_prize_routes import env
import check_roulette_prizes_ui as ui


def test_browser_copy_edit_reload_preserves_gifts(env):
    client, original, path = env
    errors = []
    responses = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width':1440, 'height':1100})
            def serve(route):
                req = route.request
                url = urlsplit(req.url)
                if url.netloc != 'ui.test':
                    route.abort()
                    return
                if url.path.endswith('.js'):
                    route.fulfill(body='', content_type='application/javascript')
                    return
                response = client.open(url.path + ('?' + url.query if url.query else ''),
                    method=req.method, data=req.post_data,
                    content_type=req.headers.get('content-type'))
                if req.method == 'PUT':
                    responses.append(response.status_code)
                route.fulfill(status=response.status_code, body=response.data,
                              content_type=response.content_type)
            page.route('**/*', serve)
            page.on('pageerror', lambda err: errors.append(str(err)))
            page.goto('http://ui.test/')
            page.add_style_tag(content='* {animation:none!important;transition:none!important;}')
            page.evaluate("document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active')); document.querySelector('#panel-roulette').classList.add('active')")
            page.add_script_tag(content=ui.PREAMBLE.replace('__GIFTS__', json.dumps(original['Gifts'])).replace('__GIFT_NAMES__', '{}'))
            for source in (ui.NAMES_SLICE, ui.SAVE_CONFIG_SLICE, ui.ACTION_SLICE, ui.ROULETTE_SLICE, ui.PRIZES_JS):
                page.add_script_tag(content=source)
            page.evaluate('initRoulettePanel()')
            page.wait_for_function('RoulettePrizes.snapshot().length === 2')
            page.locator('.roulette-prize-chip').first.click()
            page.wait_for_function("!rouletteSaving && RoulettePrizes.snapshot().length === 3")
            page.locator('.roulette-prize-card').nth(2).locator('[data-prize-action="edit"]').click()
            page.locator('#roulette-prize-name').fill('Independent browser prize')
            page.locator('#roulette-prize-actions .action-command').fill('say independent browser')
            page.locator('#btn-roulette-prize-save').click()
            page.wait_for_function("!rouletteSaving && document.querySelector('#roulette-save-state').dataset.state === 'ok'")
            saved = module.load_config()
            assert saved['Gifts'] == original['Gifts']
            assert saved['Roulette']['prizes'][2]['actions'][0]['command'] == 'say independent browser'
            page.evaluate('initRoulettePanel()')
            page.wait_for_function("RoulettePrizes.snapshot()[2].name === 'Independent browser prize'")
            assert page.locator('.roulette-prize-card').nth(2).locator('.roulette-prize-name').inner_text() == 'Independent browser prize'
            assert len(responses) >= 2 and all(s == 200 for s in responses), responses
            assert not errors, errors
        finally:
            browser.close()
