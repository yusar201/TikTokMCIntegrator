/**
 * Gift Card Studio — grid geometry (JS mirror of gift_card_studio/grid.py).
 *
 * These two implementations MUST agree: the browser preview, the OBS output,
 * and the PNG/GIF exporters all lay pages out with this same contract, and a
 * divergence shows up as "the export doesn't match what I designed".
 *
 *     cell_width  = (W - 2P - (C - 1)Gx) / C
 *     cell_height = (H - 2P - (R - 1)Gy) / R
 *
 * Pure module: no DOM, no globals, no side effects.
 */

export const FIT_MODES = ['contain', 'cover', 'stretch'];
export const FILL_ORDERS = ['row', 'column'];
export const MAX_CELLS_PER_PAGE = 100;

const DEFAULT_FIT = 'contain';
const DEFAULT_FILL_ORDER = 'row';

function num(value, fallback = 0) {
  const parsed = typeof value === 'number' ? value : parseFloat(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function positiveInt(value, fallback = 1) {
  const parsed = Math.round(num(value, fallback));
  return parsed >= 1 ? parsed : fallback;
}

export function cellCount(rows, columns) {
  return Math.max(0, Math.round(num(rows, 0))) * Math.max(0, Math.round(num(columns, 0)));
}

export function exceedsCellBudget(rows, columns, budget = MAX_CELLS_PER_PAGE) {
  return cellCount(rows, columns) > budget;
}

export function cellSize(canvasWidth, canvasHeight, grid = {}) {
  const rows = positiveInt(grid.rows, 1);
  const columns = positiveInt(grid.columns, 1);
  const padding = num(grid.padding, 0);
  const gapX = num(grid.gap_x, 0);
  const gapY = num(grid.gap_y, 0);

  const usableW = num(canvasWidth, 0) - 2 * padding - (columns - 1) * gapX;
  const usableH = num(canvasHeight, 0) - 2 * padding - (rows - 1) * gapY;

  return {
    width: Math.max(0, usableW / columns),
    height: Math.max(0, usableH / rows),
  };
}

export function cellIndex(row, column, rows, columns, fillOrder = DEFAULT_FILL_ORDER) {
  const order = FILL_ORDERS.includes(fillOrder) ? fillOrder : DEFAULT_FILL_ORDER;
  if (order === 'column') return Math.round(column) * positiveInt(rows) + Math.round(row);
  return Math.round(row) * positiveInt(columns) + Math.round(column);
}

export function cellPosition(index, rows, columns, fillOrder = DEFAULT_FILL_ORDER) {
  const order = FILL_ORDERS.includes(fillOrder) ? fillOrder : DEFAULT_FILL_ORDER;
  const r = positiveInt(rows);
  const c = positiveInt(columns);
  const i = Math.max(0, Math.round(num(index, 0)));
  if (order === 'column') return { row: i % r, column: Math.floor(i / r) };
  return { row: Math.floor(i / c), column: i % c };
}

export function cellRect(index, canvasWidth, canvasHeight, grid = {}) {
  const rows = positiveInt(grid.rows, 1);
  const columns = positiveInt(grid.columns, 1);
  const padding = num(grid.padding, 0);
  const gapX = num(grid.gap_x, 0);
  const gapY = num(grid.gap_y, 0);
  const { width, height } = cellSize(canvasWidth, canvasHeight, grid);
  const { row, column } = cellPosition(index, rows, columns, grid.fill_order);

  return {
    row,
    column,
    x: padding + column * (width + gapX),
    y: padding + row * (height + gapY),
    width,
    height,
  };
}

export function cellRects(canvasWidth, canvasHeight, grid = {}) {
  const total = positiveInt(grid.rows, 1) * positiveInt(grid.columns, 1);
  const rects = [];
  for (let i = 0; i < total; i += 1) rects.push(cellRect(i, canvasWidth, canvasHeight, grid));
  return rects;
}

export function fitScale(cardWidth, cardHeight, cellWidth, cellHeight, fit = DEFAULT_FIT) {
  const mode = FIT_MODES.includes(fit) ? fit : DEFAULT_FIT;
  const cw = num(cardWidth, 0);
  const ch = num(cardHeight, 0);
  if (cw <= 0 || ch <= 0) return { scaleX: 0, scaleY: 0 };

  const sx = num(cellWidth, 0) / cw;
  const sy = num(cellHeight, 0) / ch;
  if (mode === 'stretch') return { scaleX: Math.max(0, sx), scaleY: Math.max(0, sy) };
  const scale = Math.max(0, mode === 'contain' ? Math.min(sx, sy) : Math.max(sx, sy));
  return { scaleX: scale, scaleY: scale };
}

export function cardTransform(cardWidth, cardHeight, cell, fit = DEFAULT_FIT) {
  const { scaleX, scaleY } = fitScale(cardWidth, cardHeight, cell.width, cell.height, fit);
  const scaledWidth = num(cardWidth, 0) * scaleX;
  const scaledHeight = num(cardHeight, 0) * scaleY;
  return {
    scaleX,
    scaleY,
    scaledWidth,
    scaledHeight,
    offsetX: cell.x + (cell.width - scaledWidth) / 2,
    offsetY: cell.y + (cell.height - scaledHeight) / 2,
    clipped: scaledWidth > cell.width + 1e-9 || scaledHeight > cell.height + 1e-9,
  };
}

/**
 * Resolve every card on a page to an absolute placement.
 * Overflow cards are returned with visible:false — flagged, never dropped and
 * never silently moved to another page.
 */
export function layoutPage(page = {}, canvas = {}) {
  const grid = page.grid || {};
  const cards = Array.isArray(page.cards) ? page.cards : [];
  const fit = grid.fit || DEFAULT_FIT;
  const rects = cellRects(canvas.width, canvas.height, grid);

  return cards.map((card, index) => {
    if (index >= rects.length) {
      return { cardId: card && card.id, index, visible: false, overflow: true, cell: null, transform: null };
    }
    const cell = rects[index];
    return {
      cardId: card && card.id,
      index,
      visible: true,
      overflow: false,
      cell,
      transform: cardTransform(num(card && card.width, 0), num(card && card.height, 0), cell, fit),
    };
  });
}

export function overflowCount(page = {}) {
  const grid = page.grid || {};
  const cards = Array.isArray(page.cards) ? page.cards : [];
  return Math.max(0, cards.length - cellCount(grid.rows, grid.columns));
}

/** Bounding size of laid-out content; falls back to the canvas so a scrolling
 *  empty page can never produce a zero-length (infinite-speed) loop. */
export function contentExtent(page = {}, canvas = {}) {
  const placements = layoutPage(page, canvas).filter((p) => p.visible);
  if (placements.length === 0) {
    return { width: num(canvas.width, 0), height: num(canvas.height, 0) };
  }
  const padding = num((page.grid || {}).padding, 0);
  return {
    width: Math.max(...placements.map((p) => p.cell.x + p.cell.width)) + padding,
    height: Math.max(...placements.map((p) => p.cell.y + p.cell.height)) + padding,
  };
}

// ---- Scroll strip layout --------------------------------------------------
//
// In scroll mode rows/columns describe the *visible window* (1x5 shows five
// cards at a time) while every card lays out in one continuous strip extending
// past the canvas. A plain grid layout is always canvas-sized, so scrolling it
// would reveal nothing new and overflow cards would stay invisible forever.

export function stripTrackCount(cardCount, rows, columns, horizontal) {
  const count = Math.max(0, Math.round(num(cardCount, 0)));
  if (count === 0) return 0;
  const across = Math.max(1, Math.round(num(horizontal ? rows : columns, 1)));
  return Math.ceil(count / across);
}

export function stripLayout(page = {}, canvas = {}, horizontal = true, itemGap = null) {
  const g = page.grid || {};
  const cards = Array.isArray(page.cards) ? page.cards : [];
  const rows = positiveInt(g.rows, 1);
  const columns = positiveInt(g.columns, 1);
  const padding = num(g.padding, 0);
  const gapX = num(g.gap_x, 0);
  const gapY = num(g.gap_y, 0);
  const fit = g.fit || DEFAULT_FIT;

  const { width: cellW, height: cellH } = cellSize(canvas.width, canvas.height, g);

  let advanceGap = horizontal ? gapX : gapY;
  if (itemGap !== null && itemGap !== undefined) advanceGap = num(itemGap, 0);
  const crossGap = horizontal ? gapY : gapX;

  const across = horizontal ? rows : columns;

  return cards.map((card, index) => {
    const track = Math.floor(index / Math.max(1, across));
    const slot = index % Math.max(1, across);

    const x = horizontal
      ? padding + track * (cellW + advanceGap)
      : padding + slot * (cellW + crossGap);
    const y = horizontal
      ? padding + slot * (cellH + crossGap)
      : padding + track * (cellH + advanceGap);

    const cell = {
      row: horizontal ? slot : track,
      column: horizontal ? track : slot,
      x, y, width: cellW, height: cellH,
    };
    return {
      cardId: card && card.id,
      index,
      visible: true,
      overflow: false,
      cell,
      transform: cardTransform(num(card && card.width, 0), num(card && card.height, 0), cell, fit),
    };
  });
}

export function stripExtent(page = {}, canvas = {}, horizontal = true, itemGap = null) {
  const cards = Array.isArray(page.cards) ? page.cards : [];
  if (cards.length === 0) return 0;

  const g = page.grid || {};
  const rows = positiveInt(g.rows, 1);
  const columns = positiveInt(g.columns, 1);
  const padding = num(g.padding, 0);
  let gap = num(horizontal ? g.gap_x : g.gap_y, 0);
  if (itemGap !== null && itemGap !== undefined) gap = num(itemGap, 0);

  const { width: cellW, height: cellH } = cellSize(canvas.width, canvas.height, g);
  const size = horizontal ? cellW : cellH;
  const tracks = stripTrackCount(cards.length, rows, columns, horizontal);

  return Math.max(0, tracks * size + Math.max(0, tracks - 1) * gap + 2 * padding);
}
