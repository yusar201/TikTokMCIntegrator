/**
 * Gift Card Studio — deterministic SVG renderer.
 *
 * One renderer serves the editor preview, the OBS browser output, and the
 * PNG/GIF rasterizers, so what you design is what you export. Everything is
 * emitted as an SVG string from the project model alone — no measurement of the
 * live DOM, no dependence on viewport size or device pixel ratio.
 *
 * Security: every text value and asset URL that reaches the SVG is escaped or
 * allowlisted here. Project JSON is user data, but it can also arrive from a
 * file on disk, so it is treated as untrusted markup input.
 */

import { cellRects, cardTransform, layoutPage, stripLayout } from './grid.js';

const XML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' };

/** Escape text for use in SVG text content or an attribute value. */
export function escapeXml(value) {
  if (value === null || value === undefined) return '';
  return String(value).replace(/[&<>"']/g, (ch) => XML_ESCAPES[ch]);
}

/**
 * Allowlist an asset reference.
 *
 * Permitted: same-origin absolute paths (our own /gift-studio-assets/ and
 * /gift_assets/ files), https URLs (TikTok CDN gift icons), and data:image URLs.
 * Rejected: javascript:, vbscript:, data:text/html, protocol-relative //host,
 * and anything else that could execute or phone out from a rendered overlay.
 */
export function sanitizeAssetUrl(value) {
  if (typeof value !== 'string') return '';
  const url = value.trim();
  if (url === '') return '';
  if (url.startsWith('//')) return '';
  if (/^data:image\/(png|jpeg|jpg|webp|gif);base64,[a-z0-9+/=\s]+$/i.test(url)) return url;
  if (/^https:\/\/[^\s"'<>]+$/i.test(url)) return url;
  if (/^\/[^/\s"'<>]([^\s"'<>]*)?$/.test(url)) return url;
  return '';
}

function num(value, fallback = 0) {
  const parsed = typeof value === 'number' ? value : parseFloat(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/** Round to 3dp so identical geometry produces byte-identical SVG. */
function round(value) {
  return Math.round(num(value) * 1000) / 1000;
}

function opacityAttr(layer) {
  const opacity = num(layer.opacity, 1);
  return opacity >= 1 ? '' : ` opacity="${round(opacity)}"`;
}

function rotationTransform(layer) {
  const rotation = num(layer.rotation, 0);
  if (rotation === 0) return '';
  const cx = round(num(layer.x) + num(layer.width) / 2);
  const cy = round(num(layer.y) + num(layer.height) / 2);
  return ` transform="rotate(${round(rotation)} ${cx} ${cy})"`;
}

function colorOrNone(value) {
  if (typeof value !== 'string' || value === '' || value === 'transparent') return 'none';
  return /^#[0-9a-f]{3,8}$/i.test(value) ? value : 'none';
}

// ---- Layer renderers ------------------------------------------------------

// ---- Shapes ---------------------------------------------------------------

/**
 * Points tracing one stepped corner as a right-angled staircase.
 *
 * (cx, cy) is the notional sharp corner; sx/sy are +1/-1 unit vectors pointing
 * inward along each axis. The run starts on the sy edge and ends on the sx edge
 * and never includes the sharp corner itself: the corner square is removed and
 * the outline detours around it in axis-aligned steps.
 *
 * A single diagonal segment would render as a smooth 45-degree bevel — an
 * octagon, not pixel art.
 */
function cornerStaircase(cx, cy, sx, sy, tiers, unit) {
  const points = [];
  for (let index = 0; index < tiers; index += 1) {
    const tread = cy + sy * (tiers - index) * unit;
    points.push([cx + sx * index * unit, tread]);
    points.push([cx + sx * (index + 1) * unit, tread]);
  }
  points.push([cx + sx * tiers * unit, cy]);
  return points;
}

/** Panel outline with stepped pixel corners on all four sides. */
function steppedPolygon(x, y, w, h, unitInput, tiersInput = 1) {
  let unit = Math.max(0, num(unitInput, 0));
  let tiers = Math.max(1, Math.trunc(num(tiersInput, 1)));

  // Never let the corner treatment eat more than a third of the shorter side,
  // or opposite corners would meet and the panel would collapse.
  const budget = Math.min(w, h) / 3;
  while (tiers > 1 && tiers * unit > budget) tiers -= 1;
  if (tiers * unit > budget && budget > 0) unit = budget / tiers;

  let points;
  if (unit <= 0) {
    points = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]];
  } else {
    points = [
      ...cornerStaircase(x, y, 1, 1, tiers, unit),
      ...cornerStaircase(x + w, y, -1, 1, tiers, unit).reverse(),
      ...cornerStaircase(x + w, y + h, -1, -1, tiers, unit),
      ...cornerStaircase(x, y + h, 1, -1, tiers, unit).reverse(),
    ];
  }

  const deduped = [points[0]];
  for (const point of points.slice(1)) {
    const last = deduped[deduped.length - 1];
    if (point[0] !== last[0] || point[1] !== last[1]) deduped.push(point);
  }
  if (deduped.length > 1) {
    const first = deduped[0];
    const last = deduped[deduped.length - 1];
    if (first[0] === last[0] && first[1] === last[1]) deduped.pop();
  }

  return deduped.map(([px, py]) => `${round(px)},${round(py)}`).join(' ');
}

function renderShape(layer) {
  const kind = layer.kind || 'panel';
  const x = round(layer.x);
  const y = round(layer.y);
  const w = round(layer.width);
  const h = round(layer.height);
  const fill = colorOrNone(layer.fill);
  const stroke = colorOrNone(layer.border_color);
  const strokeWidth = round(num(layer.border_width, 0));
  const common = `fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"`;

  if (kind === 'divider') {
    const midY = round(num(layer.y) + num(layer.height) / 2);
    return `<line x1="${x}" y1="${midY}" x2="${round(num(layer.x) + num(layer.width))}" y2="${midY}" `
      + `stroke="${stroke === 'none' ? fill : stroke}" stroke-width="${strokeWidth || 2}"`
      + `${opacityAttr(layer)}${rotationTransform(layer)} />`;
  }

  if (kind === 'pixel_border') {
    // Stepped corners instead of a smooth radius: matches Khito's overlay look
    // (dark stepped pixel-rounded panels, no glass/glow/gradient).
    const unit = Math.max(1, round(num(layer.pixel_steps, 3)));
    const tiers = Math.max(1, Math.trunc(num(layer.pixel_tiers, 3)));
    const points = steppedPolygon(num(layer.x), num(layer.y), num(layer.width), num(layer.height), unit, tiers);
    return `<polygon points="${points}" ${common} stroke-linejoin="miter"${opacityAttr(layer)}${rotationTransform(layer)} />`;
  }

  const unit = num(layer.pixel_steps, 0);
  if (unit > 0) {
    const tiers = Math.max(1, Math.trunc(num(layer.pixel_tiers, 1)));
    const points = steppedPolygon(num(layer.x), num(layer.y), num(layer.width), num(layer.height), unit, tiers);
    return `<polygon points="${points}" ${common} stroke-linejoin="miter"${opacityAttr(layer)}${rotationTransform(layer)} />`;
  }

  const radius = round(num(layer.corner_radius, 0));
  const rx = radius > 0 ? ` rx="${radius}"` : '';
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}"${rx} ${common}`
    + `${opacityAttr(layer)}${rotationTransform(layer)} />`;
}

function renderImage(layer, context = {}) {
  // gift_icon layers with auto_link follow the card's linked gift unless the
  // user pinned an explicit override asset.
  let source = layer.asset;
  if (layer.type === 'gift_icon' && layer.auto_link !== false && !source) {
    source = (context.giftRef || {}).icon;
  }
  if (layer.type === 'action_icon' && !source && context.resolveActionIcon) {
    source = context.resolveActionIcon(layer.intent);
  }
  const href = sanitizeAssetUrl(source);
  if (!href && layer.type === 'action_icon') return renderActionPlaceholder(layer);
  if (!href) return '';

  const fitMap = { contain: 'xMidYMid meet', cover: 'xMidYMid slice', fill: 'none' };
  const preserve = fitMap[layer.fit] || fitMap.contain;
  const rendering = layer.pixelated === false ? '' : ' image-rendering="pixelated"';

  return `<image x="${round(layer.x)}" y="${round(layer.y)}" width="${round(layer.width)}" `
    + `height="${round(layer.height)}" href="${escapeXml(href)}" preserveAspectRatio="${preserve}"`
    + `${rendering}${opacityAttr(layer)}${rotationTransform(layer)} />`;
}

function renderActionPlaceholder(layer) {
  const x=round(layer.x), y=round(layer.y), w=round(layer.width), h=round(layer.height);
  const unit=Math.max(2,round(Math.min(w,h)*0.045));
  const cx=round(x+w/2), cy=round(y+h/2), icon=Math.max(unit*3,round(Math.min(w,h)*0.22));
  return `<g data-action-placeholder="true"${opacityAttr(layer)}${rotationTransform(layer)}>`
    + `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="#20242d" stroke="#697386" stroke-width="${unit}" stroke-dasharray="${unit*2} ${unit}" />`
    + `<rect x="${cx-icon/2}" y="${cy-unit/2}" width="${icon}" height="${unit}" fill="#aeb8ca" />`
    + `<rect x="${cx-unit/2}" y="${cy-icon/2}" width="${unit}" height="${icon}" fill="#aeb8ca" />`
    + `</g>`;
}

const ANCHORS = { left: 'start', center: 'middle', right: 'end' };

function textLines(layer) {
  const raw = layer.uppercase ? String(layer.text || '').toUpperCase() : String(layer.text || '');
  return raw.split('\n');
}

/** Shrink an oversized responsive_text layer to fit its box (approximate
 *  advance width: SVG has no measurement API available to a pure function). */
function effectiveFontSize(layer) {
  const size = num(layer.font_size, 32);
  if (!layer.responsive_text) return size;
  const lines = textLines(layer);
  const longest = lines.reduce((max, line) => Math.max(max, line.length), 0);
  if (longest === 0) return size;
  const boxWidth = num(layer.width, 0);
  const estimated = longest * size * 0.58 + Math.max(0, lines.length - 1) * 0;
  if (estimated <= boxWidth || boxWidth <= 0) return size;
  return Math.max(1, size * (boxWidth / estimated));
}

function renderText(layer) {
  const lines = textLines(layer);
  if (lines.length === 1 && lines[0] === '') return '';

  const fontSize = effectiveFontSize(layer);
  const lineHeight = fontSize * num(layer.line_height, 1.2);
  const anchor = ANCHORS[layer.align] || 'middle';

  const x = num(layer.x);
  const w = num(layer.width);
  const textX = anchor === 'start' ? x : anchor === 'end' ? x + w : x + w / 2;

  const y = num(layer.y);
  const h = num(layer.height);
  const blockHeight = lineHeight * lines.length;
  let firstBaseline;
  if (layer.vertical_align === 'top') firstBaseline = y + fontSize;
  else if (layer.vertical_align === 'bottom') firstBaseline = y + h - blockHeight + fontSize;
  else firstBaseline = y + (h - blockHeight) / 2 + fontSize;

  const stroke = colorOrNone(layer.stroke_color);
  const strokeWidth = round(num(layer.stroke_width, 0));
  const strokeAttrs = stroke !== 'none' && strokeWidth > 0
    ? ` stroke="${stroke}" stroke-width="${strokeWidth}" paint-order="stroke"` : '';
  const spacing = num(layer.letter_spacing, 0);
  const spacingAttr = spacing === 0 ? '' : ` letter-spacing="${round(spacing)}"`;
  const weight = layer.font_weight === 'bold' ? ' font-weight="bold"' : '';

  const tspans = lines.map((line, index) => {
    const lineY = round(firstBaseline + index * lineHeight);
    return `<tspan x="${round(textX)}" y="${lineY}">${escapeXml(line)}</tspan>`;
  }).join('');

  return `<text font-family="${escapeXml(layer.font_family || 'Minecraft')}" `
    + `font-size="${round(fontSize)}"${weight} fill="${colorOrNone(layer.color)}" `
    + `text-anchor="${anchor}"${spacingAttr}${strokeAttrs}`
    + `${opacityAttr(layer)}${rotationTransform(layer)}>${tspans}</text>`;
}

export function renderLayer(layer, context = {}) {
  if (!layer || layer.visible === false) return '';
  switch (layer.type) {
    case 'shape': return renderShape(layer);
    case 'text': return renderText(layer);
    case 'image':
    case 'gift_icon':
    case 'action_icon': return renderImage(layer, context);
    default: return '';
  }
}

/** Render a card's layers into its own logical coordinate space. */
export function renderCardBody(card, context = {}) {
  if (!card) return '';
  const layers = Array.isArray(card.layers) ? card.layers : [];
  const cardContext = { ...context, giftRef: card.gift_ref || {} };
  return layers
    .slice()
    .sort((a, b) => num(a.z_index, 0) - num(b.z_index, 0))
    .map((layer) => renderLayer(layer, cardContext))
    .join('');
}

/** Standalone card SVG — used by the card editor preview and PNG card export. */
export function renderCardSvg(card, context = {}) {
  const width = round(num(card && card.width, 320));
  const height = round(num(card && card.height, 400));
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" `
    + `viewBox="0 0 ${width} ${height}">${renderCardBody(card, context)}</svg>`;
}

// ---- Page rendering -------------------------------------------------------

export function canvasBackground(canvas) {
  const background = colorOrNone(canvas && canvas.background);
  if (background === 'none') return '';
  return `<rect x="0" y="0" width="${round(canvas.width)}" height="${round(canvas.height)}" `
    + `fill="${background}" />`;
}

/** Shared placement -> markup step for both grid pages and scrolling strips. */
function renderPlacements(placements, cards, context, fitCover) {
  return placements.map((placement) => {
    if (!placement.visible) return '';
    const card = cards[placement.index];
    const t = placement.transform;
    const body = renderCardBody(card, context);
    if (!body) return '';
    const group = `<g transform="translate(${round(t.offsetX)} ${round(t.offsetY)}) `
      + `scale(${round(t.scaleX)} ${round(t.scaleY)})">${body}</g>`;
    if (!fitCover || !t.clipped) return group;
    // cover mode deliberately overflows; clip it to its own cell so it cannot
    // paint over its neighbours.
    const clipId = `clip-${escapeXml(String(placement.index))}`;
    const cell = placement.cell;
    return `<clipPath id="${clipId}"><rect x="${round(cell.x)}" y="${round(cell.y)}" `
      + `width="${round(cell.width)}" height="${round(cell.height)}" /></clipPath>`
      + `<g clip-path="url(#${clipId})">${group}</g>`;
  }).join('');
}

/**
 * Render a page's cards into the grid, each card scaled into its cell.
 * Returns the inner SVG markup (no <svg> wrapper) so callers can compose it
 * into a page, a transition pair, or a scrolling strip.
 */
export function renderPageBody(page, canvas, context = {}) {
  if (!page) return '';
  const cards = Array.isArray(page.cards) ? page.cards : [];
  const fitCover = (page.grid || {}).fit === 'cover';
  return renderPlacements(layoutPage(page, canvas || {}), cards, context, fitCover);
}

/** Render a scrolling strip: every card, laid out past the canvas edge. */
export function renderStripBody(page, canvas, context = {}, horizontal = true, itemGap = null) {
  if (!page) return '';
  const cards = Array.isArray(page.cards) ? page.cards : [];
  const fitCover = (page.grid || {}).fit === 'cover';
  const placements = stripLayout(page, canvas || {}, horizontal, itemGap);
  return renderPlacements(placements, cards, context, fitCover);
}

/** Full page SVG — used by page preview, page PNG export, and GIF frames. */
export function renderPageSvg(page, canvas, context = {}) {
  const width = round(num(canvas && canvas.width, 1920));
  const height = round(num(canvas && canvas.height, 1080));
  const resolved = { width, height, background: (canvas || {}).background };
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" `
    + `viewBox="0 0 ${width} ${height}">${canvasBackground(resolved)}`
    + `${renderPageBody(page, resolved, context)}</svg>`;
}

/** Editor-only grid guides. Never included in an export. */
export function renderGridGuides(page, canvas, stroke = '#4a4a55') {
  const rects = cellRects(
    num(canvas && canvas.width, 0),
    num(canvas && canvas.height, 0),
    (page && page.grid) || {},
  );
  return rects.map((cell) => (
    `<rect x="${round(cell.x)}" y="${round(cell.y)}" width="${round(cell.width)}" `
    + `height="${round(cell.height)}" fill="none" stroke="${colorOrNone(stroke)}" `
    + 'stroke-width="1" stroke-dasharray="4 4" />'
  )).join('');
}

export { cardTransform, cellRects, layoutPage, num, round };
