/**
 * Gift Card Studio — deterministic playback timeline (JS mirror of
 * gift_card_studio/playback.py).
 *
 * stateAt(project, ms) is a pure function of (project, time). The editor
 * preview drives it from requestAnimationFrame; the OBS output drives it from
 * the same clock; the exporter walks it at fixed frame times. Because it is
 * pure, all three agree exactly — and the module holds no timer of its own, so
 * nothing here can keep running after the Studio panel closes.
 *
 * Kept in lockstep with the Python module by
 * tests/test_gift_card_studio_playback_parity.py.
 */

import { contentExtent, stripExtent } from './grid.js';

export const MIN_MEANINGFUL_TRANSITION_MS = 1;

const DEFAULT_PAGE_DURATION_MS = 5000;

function num(value, fallback = 0) {
  const parsed = typeof value === 'number' ? value : parseFloat(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

// ---- Duration / transition resolution (mirrors models.py) -----------------

export function pageDurationMs(page = {}, playback = {}) {
  const explicit = page.duration_ms;
  if (explicit === null || explicit === undefined) {
    return Math.round(num(playback.default_page_duration_ms, DEFAULT_PAGE_DURATION_MS));
  }
  return Math.round(num(explicit, DEFAULT_PAGE_DURATION_MS));
}

export function pageTransition(page = {}, playback = {}) {
  const transition = page.transition || playback.default_transition;
  if (transition && typeof transition === 'object') return transition;
  return { type: 'cut', duration_ms: 0 };
}

/** Transition duration clamped to half the shorter adjacent page. */
export function effectiveTransitionMs(page, previousPage, playback) {
  const transition = pageTransition(page, playback);
  if (transition.type === 'cut') return 0;
  const requested = Math.round(num(transition.duration_ms, 0));
  let limit = pageDurationMs(page, playback);
  if (previousPage) limit = Math.min(limit, pageDurationMs(previousPage, playback));
  return Math.max(0, Math.min(requested, Math.floor(limit / 2)));
}

// ---- Page windows ---------------------------------------------------------

export function pageWindows(project = {}) {
  const playback = project.playback || {};
  const pages = Array.isArray(project.pages) ? project.pages : [];
  const windows = [];
  let cursor = 0;

  pages.forEach((page, index) => {
    const duration = pageDurationMs(page, playback);
    const previous = index > 0 ? pages[index - 1] : (pages.length > 1 ? pages[pages.length - 1] : null);
    const transition = pageTransition(page, playback);
    let transitionMs = effectiveTransitionMs(page, previous, playback);
    if (transitionMs < MIN_MEANINGFUL_TRANSITION_MS) transitionMs = 0;
    windows.push({
      index,
      pageId: page.id,
      startMs: cursor,
      endMs: cursor + duration,
      durationMs: duration,
      transitionType: transitionMs === 0 ? 'cut' : (transition.type || 'cut'),
      transitionMs,
    });
    cursor += duration;
  });

  return windows;
}

export function projectDurationMs(project = {}) {
  const playback = project.playback || {};
  const pages = Array.isArray(project.pages) ? project.pages : [];
  return pages.reduce((total, page) => total + pageDurationMs(page, playback), 0);
}

export function loopDurationMs(project = {}) {
  if ((project.playback || {}).mode === 'scroll') return scrollLoopDurationMs(project);
  return projectDurationMs(project);
}

function normalizeTime(timeMs, totalMs, loop) {
  if (totalMs <= 0) return 0;
  const t = num(timeMs, 0);
  if (t < 0) return 0;
  if (t < totalMs) return t;
  if (loop) return t % totalMs;
  return totalMs - 1e-9;
}

export function pagesStateAt(project = {}, timeMs = 0) {
  const playback = project.playback || {};
  const pages = Array.isArray(project.pages) ? project.pages : [];
  const windows = pageWindows(project);
  const total = windows.length ? windows[windows.length - 1].endMs : 0;

  if (!pages.length || total <= 0) {
    return {
      mode: 'pages', timeMs: 0, loopMs: 0,
      pageIndex: 0, page: null, previousIndex: null, previousPage: null,
      transitionType: 'cut', transitionProgress: 1, scroll: null,
    };
  }

  const loop = playback.loop !== false;
  const local = normalizeTime(timeMs, total, loop);

  let window = windows[windows.length - 1];
  for (const candidate of windows) {
    if (local < candidate.endMs) { window = candidate; break; }
  }

  const index = window.index;
  const elapsed = local - window.startMs;
  const transitionMs = window.transitionMs;

  const hasPrevious = index > 0 || (pages.length > 1 && loop);
  let previousIndex = index > 0 ? index - 1 : (hasPrevious ? pages.length - 1 : null);

  let progress = 1;
  let transitionType = 'cut';
  if (transitionMs > 0 && elapsed < transitionMs && previousIndex !== null) {
    progress = elapsed / transitionMs;
    transitionType = window.transitionType;
  } else {
    previousIndex = null;
  }

  return {
    mode: 'pages',
    timeMs: local,
    loopMs: total,
    pageIndex: index,
    page: pages[index],
    previousIndex,
    previousPage: previousIndex !== null ? pages[previousIndex] : null,
    transitionType,
    transitionProgress: progress,
    scroll: null,
  };
}

// ---- Scroll ---------------------------------------------------------------

function scrollPage(project = {}) {
  const pages = Array.isArray(project.pages) ? project.pages : [];
  return pages.length ? pages[0] : null;
}

export function scrollConfig(project = {}) {
  const scroll = (scrollPage(project) || {}).scroll || {};
  return {
    enabled: scroll.enabled === true,
    direction: ['left', 'right', 'up', 'down'].includes(scroll.direction) ? scroll.direction : 'left',
    speed_px_per_second: Math.min(2000, Math.max(1, num(scroll.speed_px_per_second, 60))),
    loop: scroll.loop !== false,
    item_gap: Math.max(0, num(scroll.item_gap, 20)),
    edge_pause_ms: Math.max(0, num(scroll.edge_pause_ms, 0)),
  };
}

export function scrollTravelPx(project = {}) {
  const page = scrollPage(project);
  if (!page) return 0;
  const canvas = project.canvas || {};
  const scroll = scrollConfig(project);
  const horizontal = scroll.direction === 'left' || scroll.direction === 'right';
  const extent = stripExtent(page, canvas, horizontal, scroll.item_gap);
  if (extent <= 0) return 0;
  if (scroll.loop) return extent;
  const visible = num(horizontal ? canvas.width : canvas.height, 0);
  return Math.max(0, extent - visible);
}

export function scrollLoopDurationMs(project = {}) {
  const scroll = scrollConfig(project);
  const travel = scrollTravelPx(project);
  const speed = Math.max(1e-9, scroll.speed_px_per_second);
  const movingMs = (travel / speed) * 1000;
  const pauses = scroll.loop ? scroll.edge_pause_ms : scroll.edge_pause_ms * 2;
  return Math.round(movingMs + pauses);
}

export function scrollStateAt(project = {}, timeMs = 0) {
  const scroll = scrollConfig(project);
  const page = scrollPage(project);
  const travel = scrollTravelPx(project);
  const speed = Math.max(1e-9, scroll.speed_px_per_second);
  const pauseMs = scroll.edge_pause_ms;
  const movingMs = (travel / speed) * 1000;
  const total = scrollLoopDurationMs(project);

  let progress = 0;
  let local = 0;
  if (total > 0 && travel > 0) {
    local = normalizeTime(timeMs, total, true);
    if (local < pauseMs) progress = 0;
    else if (scroll.loop) progress = Math.min(1, (local - pauseMs) / Math.max(1e-9, movingMs));
    else if (local < pauseMs + movingMs) progress = (local - pauseMs) / Math.max(1e-9, movingMs);
    else progress = 1;
  }

  const distance = travel * progress;
  let offsetX = 0;
  let offsetY = 0;
  if (scroll.direction === 'left') offsetX = -distance;
  else if (scroll.direction === 'right') offsetX = distance;
  else if (scroll.direction === 'up') offsetY = -distance;
  else offsetY = distance;

  return {
    mode: 'scroll',
    timeMs: local,
    loopMs: total,
    pageIndex: 0,
    page,
    previousIndex: null,
    previousPage: null,
    transitionType: 'cut',
    transitionProgress: 1,
    scroll: {
      direction: scroll.direction,
      offsetX,
      offsetY,
      distance,
      travel,
      progress,
      loop: scroll.loop,
      speedPxPerSecond: scroll.speed_px_per_second,
    },
  };
}

// ---- Entry points ---------------------------------------------------------

export function stateAt(project = {}, timeMs = 0) {
  if ((project.playback || {}).mode === 'scroll') return scrollStateAt(project, timeMs);
  return pagesStateAt(project, timeMs);
}

export function frameTimes(project = {}, fps = 15, durationMs = null) {
  const rate = Math.max(1, Math.round(num(fps, 15)));
  const total = Math.round(durationMs === null || durationMs === undefined
    ? loopDurationMs(project) : num(durationMs, 0));
  if (total <= 0) return [0];
  const count = Math.max(1, Math.round((total * rate) / 1000));
  return Array.from({ length: count }, (_, i) => Math.round((i * 1000) / rate));
}

export function frameCount(project = {}, fps = 15, durationMs = null) {
  return frameTimes(project, fps, durationMs).length;
}

export { contentExtent };
