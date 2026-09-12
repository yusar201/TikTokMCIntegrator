import test from 'node:test';
import assert from 'node:assert/strict';
import {
  pageCapacity,
  collectProjectCards,
  autoPaginateProject,
  duplicatePage,
  normalizeCardLibrary,
  assignCardToPage,
  removeCardFromPage,
  materializePageCards,
} from '../../static/gift-studio/page-composer.js';

const card = (id) => ({ id, name: `Card ${id}`, layers: [{ id: `layer-${id}`, type: 'text', text: id }] });
const page = (id, cards, rows = 4, columns = 6) => ({
  id,
  name: id,
  duration_ms: 5000,
  transition: null,
  grid: { rows, columns, gap_x: 20, gap_y: 20, padding: 24, fill_order: 'row', fit: 'contain' },
  scroll: { enabled: false, direction: 'left', speed_px_per_second: 80, loop: true, item_gap: 20, edge_pause_ms: 0 },
  cards,
});

test('pageCapacity uses rows by columns with safe minimums', () => {
  assert.equal(pageCapacity(page('p', [], 4, 6)), 24);
  assert.equal(pageCapacity({ grid: { rows: 0, columns: 0 } }), 1);
});

test('collectProjectCards preserves visual order across existing pages', () => {
  const project = { pages: [page('p1', [card('a'), card('b')]), page('p2', [card('c')])] };
  assert.deepEqual(collectProjectCards(project).map((item) => item.id), ['a', 'b', 'c']);
});

test('autoPaginateProject splits 56 cards into 24, 24, and 8 using current 4x6 layout', () => {
  const cards = Array.from({ length: 56 }, (_, index) => card(String(index + 1)));
  const project = { pages: [page('p1', cards)] };
  const result = autoPaginateProject(project, 0);
  assert.deepEqual(result.pages.map((item) => item.cards.length), [24, 24, 8]);
  assert.equal(result.pages[0].name, 'Page 1');
  assert.equal(result.pages[2].name, 'Page 3');
  assert.deepEqual(result.pages.flatMap((item) => item.cards).map((item) => item.id), cards.map((item) => item.id));
});

test('autoPaginateProject reflows all existing page cards without losing or duplicating cards', () => {
  const project = { pages: [page('p1', [card('a'), card('b')], 1, 2), page('p2', [card('c')], 1, 2)] };
  const result = autoPaginateProject(project, 0);
  assert.deepEqual(result.pages.map((item) => item.cards.length), [2, 1]);
  assert.deepEqual(result.pages.flatMap((item) => item.cards).map((item) => item.id), ['a', 'b', 'c']);
});

test('duplicatePage reuses global card identities on an independent page', () => {
  const source = page('p1', [card('a')], 1, 1);
  const copy = duplicatePage(source, 2, () => 'nonce');
  assert.equal(copy.name, 'Page 2');
  assert.notEqual(copy.id, source.id);
  assert.equal(copy.cards[0].id, source.cards[0].id);
  assert.deepEqual(copy.card_ids, ['a']);
});

test('autoPaginateProject keeps one empty page when project has no cards', () => {
  const result = autoPaginateProject({ pages: [page('p1', [])] }, 0);
  assert.equal(result.pages.length, 1);
  assert.equal(result.pages[0].cards.length, 0);
});

test('legacy page cards migrate into one deduplicated global card library', () => {
  const project = { pages: [page('p1', [card('a'), card('b')]), page('p2', [card('b'), card('c')])] };
  const result = normalizeCardLibrary(project);
  assert.deepEqual(result.card_library.map(item => item.id), ['a', 'b', 'c']);
  assert.deepEqual(result.pages.map(item => item.card_ids), [['a', 'b'], ['b', 'c']]);
});

test('manual assignment freely adds and removes a library card without deleting it', () => {
  let project = normalizeCardLibrary({ card_library: [card('a'), card('b')], pages: [page('p1', [])] });
  project = assignCardToPage(project, 0, 'b');
  assert.deepEqual(project.pages[0].card_ids, ['b']);
  assert.equal(project.pages[0].cards[0].id, 'b');
  project = removeCardFromPage(project, 0, 'b');
  assert.deepEqual(project.pages[0].card_ids, []);
  assert.deepEqual(project.card_library.map(item => item.id), ['a', 'b']);
});

test('editing a global card materializes the edit on every assigned page', () => {
  const project = normalizeCardLibrary({ card_library: [card('a')], pages: [page('p1', []), page('p2', [])] });
  project.pages[0].card_ids = ['a']; project.pages[1].card_ids = ['a'];
  project.card_library[0].name = 'Edited globally';
  const result = materializePageCards(project);
  assert.equal(result.pages[0].cards[0].name, 'Edited globally');
  assert.equal(result.pages[1].cards[0].name, 'Edited globally');
});

test('auto-build assigns global cards and keeps the same editable library identities', () => {
  const cards = Array.from({ length: 56 }, (_, index) => card(String(index + 1)));
  const project = normalizeCardLibrary({ card_library: cards, pages: [page('p1', [], 4, 6)] });
  const result = autoPaginateProject(project, 0);
  assert.deepEqual(result.pages.map(item => item.card_ids.length), [24, 24, 8]);
  assert.deepEqual(result.card_library.map(item => item.id), cards.map(item => item.id));
});
