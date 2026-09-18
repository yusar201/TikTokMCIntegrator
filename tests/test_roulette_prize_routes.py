import copy
import json
import pytest
import app as module


@pytest.fixture
def env(tmp_path, monkeypatch):
    import yaml
    cfg = {'Gifts': {'1':['say first'], '2':['say second']}, 'GiftDescriptions':{'1':'First'}, 'Roulette':{'enabled':True,'pool':['1','2']}}
    config = tmp_path/'config.yml'
    profiles = tmp_path/'profiles'
    profiles.mkdir()
    config.write_text(yaml.safe_dump(cfg), encoding='utf-8')
    (profiles/'default.yml').write_text(config.read_text(), encoding='utf-8')
    monkeypatch.setattr(module, 'CONFIG_FILE', str(config))
    monkeypatch.setattr(module, 'PROFILES_DIR', str(profiles))
    monkeypatch.setattr(module, 'get_active_profile', lambda:'default')
    monkeypatch.setattr(module, 'is_any_bot_running', lambda:(False,None))
    monkeypatch.setattr(module, 'safe_json_read', lambda *a,**kw:[])
    return module.app.test_client(), cfg, config


@pytest.mark.parametrize('bad_bundle', [None, [{'type':'roulette'}]])
def test_migrated_disabled_prize_can_roundtrip(env, bad_bundle):
    client, original, path = env
    cfg = module.load_config()
    if bad_bundle is None:
        del cfg['Gifts']['2']
    else:
        cfg['Gifts']['2'] = bad_bundle
    module.save_config(cfg)
    payload = client.get('/api/roulette/config').get_json()['roulette']
    assert payload['prizes'][1]['enabled'] is False
    response = client.put('/api/roulette/config', json=payload)
    assert response.status_code == 200, response.get_json()
    assert module.load_config()['Gifts'] == cfg['Gifts']


def test_migration_disables_insufficient_pool(env):
    client, original, path = env
    cfg = module.load_config()
    del cfg['Gifts']['2']
    module.save_config(cfg)
    body = client.get('/api/roulette/config').get_json()
    assert body['roulette']['enabled'] is False
    assert module.load_config()['Roulette']['enabled'] is False


def test_real_save_migration_gift_independence_and_general_save(env):
    client, original, path = env
    body = client.get('/api/roulette/config').get_json()
    prizes = body['roulette']['prizes']
    assert len(prizes) == 2
    assert module.load_config()['Gifts'] == original['Gifts']
    payload = body['roulette']
    payload['prizes'][0]['actions'][0]['command'] = 'say independent'
    assert client.put('/api/roulette/config',json=payload).status_code == 200
    stale = copy.deepcopy(original)
    stale['Gifts']['1'] = ['say gift changed']
    assert client.post('/api/config',json=stale).status_code == 200
    saved = module.load_config()
    assert saved['Gifts']['1'] == ['say gift changed']
    assert saved['Roulette']['prizes'][0]['actions'][0]['command'] == 'say independent'
    assert client.get('/api/roulette/config').get_json()['roulette'] == saved['Roulette']
    # A rejected save cannot replace the previous persisted pool.
    broken = copy.deepcopy(payload)
    broken['prizes'][0]['actions'] = [{'type':'roulette'}]
    assert client.put('/api/roulette/config',json=broken).status_code == 400
    assert module.load_config()['Roulette'] == saved['Roulette']
    # Deleting all prizes never falls back to old gift IDs.
    payload['prizes'] = []
    response = client.put('/api/roulette/config',json=payload)
    assert response.status_code == 200
    assert response.get_json()['roulette']['enabled'] is False
    assert client.get('/api/roulette/config').get_json()['resolved_entries'] == []
