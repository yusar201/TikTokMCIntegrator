/**
 * Compose one timeline frame into a complete SVG (JS mirror of
 * gift_card_studio/frame.py).
 *
 * The OBS browser output and the editor preview render frames from here; the
 * PNG/GIF exporter renders them from the Python twin. Both must emit identical
 * markup or an exported GIF stops matching what Khito previewed —
 * tests/test_gift_card_studio_frame_parity.py enforces that byte-for-byte.
 *
 * Pure module: no DOM, no timers, no fetch.
 */

import { stateAt } from './playback.js';
import {
  renderPageBody,
  renderStripBody,
  canvasBackground,
  round,
  num,
} from './renderer.js';

// Pixel wipe reveals in discrete columns rather than a smooth edge, matching the
// stepped aesthetic of the panels themselves.
export const PIXEL_WIPE_STEPS = 16;

function lerp(a, b, t) {
  return a + (b - a) * Number(t);
}

export function svgHeader(width, height) {
  const w = round(width);
  const h = round(height);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" `
    + `viewBox="0 0 ${w} ${h}">`;
}

/**
 * The scrolling strip, translated, plus the trailing copy for a seamless loop.
 *
 * The second copy sits exactly one travel-length behind the first, so as the
 * first walks off screen the second is already filling the gap. Without it the
 * loop shows empty canvas at the seam.
 */
export function scrollFrameBody(page, canvas, scroll, context = {}) {
  const horizontal = scroll.direction === 'left' || scroll.direction === 'right';
  const itemGap = (page.scroll || {}).item_gap;
  const body = renderStripBody(page, canvas, context, horizontal, itemGap);
  if (!body) return '';

  const dx = scroll.offsetX;
  const dy = scroll.offsetY;
  const parts = [`<g transform="translate(${round(dx)} ${round(dy)})">${body}</g>`];

  if (scroll.loop) {
    const travel = scroll.travel;
    let followX = dx;
    let followY = dy;
    if (scroll.direction === 'left') followX = dx + travel;
    else if (scroll.direction === 'right') followX = dx - travel;
    else if (scroll.direction === 'up') followY = dy + travel;
    else followY = dy - travel;
    parts.push(`<g transform="translate(${round(followX)} ${round(followY)})">${body}</g>`);
  }

  return parts.join('');
}

/**
 * Compose two page bodies mid-transition.
 *
 * clipId is caller-supplied so a document showing several frames at once cannot
 * collide on a duplicate SVG id.
 */
export function transitionBody(current, outgoing, transition, progressInput, width, height, clipId = 'wipe') {
  const progress = Math.max(0, Math.min(1, num(progressInput, 0)));

  if (transition === 'fade') {
    return `<g opacity="${round(1 - progress)}">${outgoing}</g>`
      + `<g opacity="${round(progress)}">${current}</g>`;
  }

  if (transition === 'slide') {
    const outDx = lerp(0, -num(width, 0), progress);
    const inDx = lerp(num(width, 0), 0, progress);
    return `<g transform="translate(${round(outDx)} 0)">${outgoing}</g>`
      + `<g transform="translate(${round(inDx)} 0)">${current}</g>`;
  }

  // pixel_wipe — stepped reveal.
  const revealed = Math.max(0, Math.min(PIXEL_WIPE_STEPS, Math.round(progress * PIXEL_WIPE_STEPS)));
  const wipeWidth = num(width, 0) * (revealed / PIXEL_WIPE_STEPS);
  if (wipeWidth <= 0) return outgoing;
  return `${outgoing}<clipPath id="${clipId}">`
    + `<rect x="0" y="0" width="${round(wipeWidth)}" height="${round(height)}" />`
    + '</clipPath>'
    + `<g clip-path="url(#${clipId})">${current}</g>`;
}

/** Inner markup for one frame — no <svg> wrapper, no background. */
export function frameBody(project = {}, timeMs = 0, context = {}, clipId = 'wipe') {
  const canvas = project.canvas || {};
  const state = stateAt(project, timeMs);

  if (state.mode === 'scroll') {
    if (!state.page) return '';
    return scrollFrameBody(state.page, canvas, state.scroll, context);
  }

  if (!state.page) return '';

  const current = renderPageBody(state.page, canvas, context);
  const previousPage = state.previousPage;
  const progress = num(state.transitionProgress, 1);
  const transition = state.transitionType;

  if (!previousPage || transition === 'cut' || progress >= 1) return current;

  const outgoing = renderPageBody(previousPage, canvas, context);
  return transitionBody(
    current, outgoing, transition, progress,
    canvas.width || 0, canvas.height || 0, clipId,
  );
}

/** Complete SVG document for one timeline frame. */
export function frameSvg(project = {}, timeMs = 0, context = {}, clipId = 'wipe') {
  const canvas = project.canvas || {};
  const width = num(canvas.width, 1920);
  const height = num(canvas.height, 1080);
  const background = canvasBackground({
    width, height, background: canvas.background,
  });
  return svgHeader(width, height)
    + background
    + frameBody(project, timeMs, context, clipId)
    + '</svg>';
}
