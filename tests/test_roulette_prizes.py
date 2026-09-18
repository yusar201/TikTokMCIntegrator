"""Independent prize contracts; no live actions or storage."""
import copy
import json
import random
import pytest
import gift_roulette as gr


def test_custom_prize_bundle_and_snapshot_without_gifts():
    prizes = [dict(id=str(i), name=f'Prize {i}', enabled=True, icon_url='', actions=[{'type':'minecraft','command':f'say {i}'}]) for i in range(2)]
    cfg = gr.normalize_config(dict(enabled=True, prizes=prizes, pool=[]))
    spin = gr.prepare_spin(cfg, {}, {}, {}, {}, {'user':'Viewer','mc':'Khito'}, rng=random.Random(1))
    assert spin.winner_actions == ({'type':'minecraft','command':'say 0'},)
    prizes[0]['actions'][0]['command'] = 'changed'
    cfg['prizes'][0]['actions'][0]['command'] = 'changed again'
    assert spin.winner_actions[0]['command'] == 'say 0'
    assert spin.winner_context['user'] == 'Viewer'
    assert spin.winner_context['amount'] == '1'
    assert 'command' not in json.dumps(spin.public_state)
    cfg['prizes'][1]['enabled'] = False
    assert len(gr.resolve_entries(cfg, {}, {}, {}, {})) == 1


def test_malformed_duplicate_prizes_raise_domain_error():
    good = dict(id='p', name='P', actions=['say ok'])
    bad = dict(good, actions=[{'type':'roulette'}])
    cfg = gr.normalize_config(dict(enabled=True, prizes=[bad, good, dict(good, id='q')]))
    with pytest.raises(gr.RouletteValidationError):
        gr.prepare_spin(cfg, {}, {}, {}, {}, {}, rng=random.Random(1))


def test_legacy_conversion_is_independent_and_repeatable():
    profile = {'Gifts': {'1':['say original'], '2':['say other']}, 'GiftDescriptions':{'1':'Original'}, 'Roulette':{'enabled':True,'pool':['1','2']}}
    before = copy.deepcopy(profile['Gifts'])
    converted = gr.migrate_prize_config(profile, {})
    profile['Roulette'] = converted
    assert converted['prizes'][0]['name'] == 'Original'
    assert profile['Gifts'] == before
    profile['Gifts']['1'][0] = 'say new gift'
    again = gr.migrate_prize_config(profile, {})
    assert again == converted
    assert again['prizes'][0]['actions'] == [{'type':'minecraft','command':'say original'}]
    assert gr.normalize_config(dict(converted, prizes=[]))['prizes'] == []


def test_prize_validation_rejects_recursive_roulette_and_duplicate_ids():
    base = dict(id='p',name='P',enabled=True,actions=[{'type':'random','actions':[{'type':'roulette'}]}])
    with pytest.raises(ValueError, match='roulette'):
        gr.validate_prizes([base])
    base['actions'] = [{'type':'minecraft','command':'say ok'}]
    with pytest.raises(ValueError, match='Duplicate'):
        gr.validate_prizes([base,copy.deepcopy(base)])
