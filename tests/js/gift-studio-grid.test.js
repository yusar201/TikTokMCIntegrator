/**
 * Gift Card Studio — grid geometry (JS side).
 * Run: node --test tests/js/
 */
import assert from 'node:assert/strict';
import { test, describe } from 'node:test';

import * as grid from '../../static/gift-studio/grid.js';

const makeGrid = (overrides = {}) => ({
  rows: 1, columns: 1, gap_x: 0, gap_y: 0, padding: 0,
  fill_order: 'row', fit: 'contain', ...overrides,
});

describe('cellSize', () => {
  test('a single cell with no padding fills the canvas', () => {
    assert.deepEqual(grid.cellSize(1920, 1080, makeGrid()), { width: 1920, height: 1080 });
  });

  test('1x5 matches the documented formula', () => {
    const { width, height } = grid.cellSize(1920, 1080, makeGrid({ rows: 1, columns: 5, gap_x: 20, padding: 24 }));
    assert.equal(width, 358.4);
    assert.equal(height, 1032);
  });

  test('an over-padded grid collapses to zero instead of inverting', () => {
    assert.deepEqual(grid.cellSize(1920, 1080, makeGrid({ padding: 2000 })), { width: 0, height: 0 });
  });

  test('gaps only apply between cells', () => {
    assert.equal(grid.cellSize(1000, 100, makeGrid({ columns: 1, gap_x: 50 })).width, 1000);
    assert.equal(grid.cellSize(1000, 100, makeGrid({ columns: 2, gap_x: 50 })).width, 475);
  });

  test('string numbers from a form are coerced', () => {
    const { width } = grid.cellSize('1920', '1080', makeGrid({ columns: '5', gap_x: '20', padding: '24' }));
    assert.equal(width, 358.4);
  });
});

describe('cell budget', () => {
  test('counts rows x columns', () => {
    assert.equal(grid.cellCount(3, 4), 12);
  });

  test('100 cells allowed, 120 is not', () => {
    assert.equal(grid.exceedsCellBudget(10, 10), false);
    assert.equal(grid.exceedsCellBudget(20, 6), true);
  });
});

describe('fill order', () => {
  test('row order walks left-to-right then down', () => {
    const positions = [0, 1, 2, 3, 4, 5].map((i) => grid.cellPosition(i, 2, 3, 'row'));
    assert.deepEqual(positions.map((p) => [p.row, p.column]),
      [[0, 0], [0, 1], [0, 2], [1, 0], [1, 1], [1, 2]]);
  });

  test('column order walks top-to-bottom then right', () => {
    const positions = [0, 1, 2, 3, 4, 5].map((i) => grid.cellPosition(i, 2, 3, 'column'));
    assert.deepEqual(positions.map((p) => [p.row, p.column]),
      [[0, 0], [1, 0], [0, 1], [1, 1], [0, 2], [1, 2]]);
  });

  test('index and position are inverses', () => {
    for (const order of ['row', 'column']) {
      for (let i = 0; i < 12; i += 1) {
        const { row, column } = grid.cellPosition(i, 3, 4, order);
        assert.equal(grid.cellIndex(row, column, 3, 4, order), i);
      }
    }
  });

  test('unknown fill order falls back to row', () => {
    assert.deepEqual(grid.cellPosition(1, 2, 3, 'spiral'), grid.cellPosition(1, 2, 3, 'row'));
  });
});

describe('cellRects', () => {
  test('1x5 rects are evenly spaced and stay inside the canvas', () => {
    const rects = grid.cellRects(1920, 1080, makeGrid({ rows: 1, columns: 5, gap_x: 20, padding: 24 }));
    assert.equal(rects.length, 5);
    assert.equal(rects[0].x, 24);
    assert.equal(rects[1].x, 24 + 358.4 + 20);
    assert.ok(Math.abs((rects[4].x + rects[4].width) - (1920 - 24)) < 1e-9);
  });

  test('rects carry their row and column', () => {
    const rects = grid.cellRects(600, 400, makeGrid({ rows: 2, columns: 2 }));
    assert.deepEqual(rects.map((r) => [r.row, r.column]), [[0, 0], [0, 1], [1, 0], [1, 1]]);
  });
});

describe('fitScale', () => {
  test('contain uses the smaller axis', () => {
    const { scaleX, scaleY } = grid.fitScale(320, 400, 358.4, 1032, 'contain');
    assert.equal(scaleX, scaleY);
    assert.equal(scaleX, 358.4 / 320);
  });

  test('cover uses the larger axis', () => {
    const { scaleX } = grid.fitScale(320, 400, 358.4, 1032, 'cover');
    assert.equal(scaleX, 1032 / 400);
  });

  test('stretch scales axes independently', () => {
    assert.deepEqual(grid.fitScale(320, 400, 640, 400, 'stretch'), { scaleX: 2, scaleY: 1 });
  });

  test('unknown fit falls back to contain', () => {
    assert.deepEqual(grid.fitScale(100, 100, 50, 200, 'warp'), grid.fitScale(100, 100, 50, 200, 'contain'));
  });

  test('a degenerate card size yields zero scale, not NaN', () => {
    assert.deepEqual(grid.fitScale(0, 400, 100, 100), { scaleX: 0, scaleY: 0 });
  });
});

describe('cardTransform', () => {
  const cell = { x: 100, y: 200, width: 400, height: 400 };

  test('contain centres the scaled card in its cell', () => {
    const t = grid.cardTransform(320, 400, cell, 'contain');
    assert.equal(t.scaleX, 1);
    assert.equal(t.offsetX, 100 + (400 - 320) / 2);
    assert.equal(t.offsetY, 200);
    assert.equal(t.clipped, false);
  });

  test('cover reports clipping on the overflowing axis', () => {
    const t = grid.cardTransform(320, 400, { x: 0, y: 0, width: 400, height: 400 }, 'cover');
    assert.equal(t.scaleX, 1.25);
    assert.equal(t.clipped, true);
  });

  test('a 1x5 page scales five default cards to fit uniformly', () => {
    const rects = grid.cellRects(1920, 1080, makeGrid({ rows: 1, columns: 5, gap_x: 20, padding: 24 }));
    const transforms = rects.map((c) => grid.cardTransform(320, 400, c, 'contain'));
    assert.equal(transforms.length, 5);
    for (const t of transforms) {
      assert.ok(t.scaledWidth <= 358.4 + 1e-9);
      assert.equal(t.clipped, false);
    }
    assert.equal(new Set(transforms.map((t) => t.scaleX.toFixed(9))).size, 1);
  });
});

describe('layoutPage', () => {
  const page = (count, overrides = {}) => ({
    grid: makeGrid(overrides),
    cards: Array.from({ length: count }, (_, i) => ({ id: `card-${i}`, width: 320, height: 400 })),
  });

  test('cards within the cell count all get placements', () => {
    const placements = grid.layoutPage(page(5, { rows: 1, columns: 5 }), { width: 1920, height: 1080 });
    assert.equal(placements.length, 5);
    assert.ok(placements.every((p) => p.visible && p.transform));
  });

  test('overflow cards are flagged, not dropped or moved', () => {
    const placements = grid.layoutPage(page(7, { rows: 1, columns: 5 }), { width: 1920, height: 1080 });
    assert.equal(placements.length, 7);
    assert.deepEqual(placements.map((p) => p.visible), [true, true, true, true, true, false, false]);
    assert.ok(placements.slice(5).every((p) => p.overflow && p.transform === null));
  });

  test('overflowCount reports cards without a cell', () => {
    assert.equal(grid.overflowCount(page(7, { rows: 1, columns: 5 })), 2);
    assert.equal(grid.overflowCount(page(3, { rows: 1, columns: 5 })), 0);
  });

  test('placements preserve card ids and order', () => {
    const placements = grid.layoutPage(page(3, { rows: 1, columns: 3 }), { width: 900, height: 300 });
    assert.deepEqual(placements.map((p) => p.cardId), ['card-0', 'card-1', 'card-2']);
  });

  test('an empty page has no placements', () => {
    assert.deepEqual(grid.layoutPage(page(0), { width: 800, height: 600 }), []);
  });
});

describe('contentExtent', () => {
  test('an empty page falls back to the canvas so scroll cannot divide by zero', () => {
    const extent = grid.contentExtent({ grid: makeGrid(), cards: [] }, { width: 800, height: 600 });
    assert.deepEqual(extent, { width: 800, height: 600 });
  });

  test('extent covers the laid-out cells plus padding', () => {
    const page = {
      grid: makeGrid({ rows: 1, columns: 3, gap_x: 10, padding: 20 }),
      cards: [0, 1, 2].map((i) => ({ id: String(i), width: 100, height: 100 })),
    };
    assert.deepEqual(grid.contentExtent(page, { width: 620, height: 200 }), { width: 620, height: 200 });
  });
});
