"""User-flow regressions for canonical library exports."""
from gift_card_studio import models, generate, exporter


def test_all_cards_includes_unassigned_library_once(tmp_path, monkeypatch):
    project = models.new_project('Library')
    a = models.normalize_card({'id': 'card-a', 'name': 'A'})
    b = models.normalize_card({'id': 'card-b', 'name': 'B'})
    project['card_library'] = [a, b]
    project['pages'][0]['card_ids'] = [a['id']]
    project['pages'].append({**project['pages'][0], 'id': 'page-b'})
    settings = generate.normalize_settings({'format': 'png', 'mode': 'cards'})
    seen = []
    monkeypatch.setattr(exporter, 'render_card_png', lambda card, *args: seen.append(card['id']) or b'png')
    exporter.export_png(project, str(tmp_path), mode='cards')
    assert seen == ['card-a', 'card-b']
    assert generate.estimate(project, settings)['file_count'] == 2


def test_single_unassigned_card_export(tmp_path, monkeypatch):
    project = models.new_project('Library')
    project['card_library'] = [models.normalize_card({'id': 'unassigned'})]
    seen = []
    monkeypatch.setattr(exporter, 'render_card_png', lambda card, *args: seen.append(card['id']) or b'png')
    exporter.export_png(project, str(tmp_path), mode='card', card_id='unassigned')
    assert seen == ['unassigned']
