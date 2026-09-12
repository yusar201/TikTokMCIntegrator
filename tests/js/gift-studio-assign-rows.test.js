/**
 * Gift Card Studio — page-assignment rows: action text sourcing, filter, HTML.
 * Run: node --test tests/js/gift-studio-assign-rows.test.js
 */
import assert from 'node:assert/strict';
import { test, describe } from 'node:test';

import {
  cardActionText,
  cardGiftIcon,
  cardDisplayName,
  rowMatches,
  assignRowHtml,
} from '../../static/gift-studio/assign-rows.js';

const textLayer = (text, role = 'main') => ({ id: 't', type: 'text', role, text });
const card = (overrides = {}) => ({
  id: 'c1', name: 'birthday cake',
  gift_ref: { gift_id: '9097', name: 'birthday cake', icon: '/gift-studio-assets/gift-icon-9097.png' },
  action_ref: { gift_key: '9097', commands: ['spawnmob {mc} 1 creeper {user}'], intent: 'mob', confidence: 0.9 },
  layers: [textLayer('Disintegrating')],
  ...overrides,
});

describe('cardActionText', () => {
  test('reads the main text layer (GiftDescriptions content)', () => {
    assert.equal(cardActionText(card()), 'Disintegrating');
  });

  test('prefers the main role when other text layers exist', () => {
    const c = card({ layers: [textLayer('Custom note', 'custom'), textLayer('Disintegrating', 'main')] });
    assert.equal(cardActionText(c), 'Disintegrating');
  });

  test('falls back to any text layer when no main role exists', () => {
    const c = card({ layers: [textLayer('Totem', 'custom')] });
    assert.equal(cardActionText(c), 'Totem');
  });

  test('never derives from commands, intent, or the gift name', () => {
    const c = card({ layers: [] });
    assert.equal(cardActionText(c), '');
    assert.ok(!assignRowHtml(c, false).includes('spawnmob'));
    assert.ok(!assignRowHtml(c, false).includes('mob'));
  });

  test('blank action text renders the no-action hint', () => {
    assert.ok(assignRowHtml(card({ layers: [] }), false).includes('No action text'));
  });
});

describe('cardGiftIcon', () => {
  test('prefers the linked gift icon', () => {
    assert.equal(cardGiftIcon(card()), '/gift-studio-assets/gift-icon-9097.png');
  });

  test('falls back to a gift_icon layer asset', () => {
    const c = card({ gift_ref: {}, layers: [{ id: 'g', type: 'gift_icon', asset: '/x.png' }] });
    assert.equal(cardGiftIcon(c), '/x.png');
  });
});

describe('cardDisplayName', () => {
  test('prefers the card name, then the gift name, then the id', () => {
    assert.equal(cardDisplayName(card()), 'birthday cake');
    assert.equal(cardDisplayName({ id: 'x', gift_ref: { name: 'rose' }, layers: [] }), 'rose');
    assert.equal(cardDisplayName({ id: 'x', layers: [] }), 'x');
  });
});

describe('rowMatches', () => {
  test('empty query matches everything', () => {
    assert.equal(rowMatches(card(), ''), true);
  });

  test('matches gift name and action text case-insensitively', () => {
    assert.equal(rowMatches(card(), 'BIRTHDAY'), true);
    assert.equal(rowMatches(card(), 'disinteg'), true);
  });

  test('every word must match somewhere', () => {
    assert.equal(rowMatches(card(), 'birthday disintegrating'), true);
    assert.equal(rowMatches(card(), 'birthday witch'), false);
  });
});

describe('assignRowHtml', () => {
  test('escapes markup in names and action text', () => {
    const html = assignRowHtml(card({ name: '<b>cake</b>', layers: [textLayer('<img src=x>')] }), false);
    assert.ok(!html.includes('<b>cake</b>'));
    assert.ok(!html.includes('<img src=x>'));
    assert.ok(html.includes('&lt;b&gt;cake&lt;/b&gt;'));
  });

  test('marks selection state for assistive tech', () => {
    assert.ok(assignRowHtml(card(), true).includes('aria-checked="true"'));
    assert.ok(assignRowHtml(card(), true).includes('gcs-assign-row selected'));
    assert.ok(assignRowHtml(card(), false).includes('aria-checked="false"'));
  });

  test('shows a fallback tile when no icon exists', () => {
    const html = assignRowHtml(card({ gift_ref: {}, layers: [textLayer('X')] }), false);
    assert.ok(html.includes('gcs-assign-fallback'));
  });
});
