const clone = value => JSON.parse(JSON.stringify(value));

export function pageCapacity(page) {
  const rows = Math.max(1, Number(page?.grid?.rows) || 1);
  const columns = Math.max(1, Number(page?.grid?.columns) || 1);
  return rows * columns;
}

export function collectProjectCards(project) {
  return normalizeCardLibrary(project).card_library;
}

export function materializePageCards(project) {
  const library = project?.card_library || [];
  const byId = new Map(library.map(card => [String(card.id), card]));
  project.pages = (project.pages || []).map(page => ({
    ...page,
    card_ids: [...new Set((page.card_ids || []).map(String))].filter(id => byId.has(id)),
    cards: [...new Set((page.card_ids || []).map(String))].map(id => byId.get(id)).filter(Boolean),
  }));
  return project;
}

export function normalizeCardLibrary(project) {
  const result = { ...(project || {}), pages: (project?.pages || []).map(page => ({ ...page })) };
  const library = [], seen = new Set();
  for (const card of project?.card_library || []) if (card?.id && !seen.has(String(card.id))) { seen.add(String(card.id)); library.push(card); }
  result.pages = result.pages.map(page => {
    const legacy = page.cards || [];
    for (const card of legacy) if (card?.id && !seen.has(String(card.id))) { seen.add(String(card.id)); library.push(card); }
    return { ...page, card_ids: page.card_ids?.length ? [...new Set(page.card_ids.map(String))] : legacy.map(card => String(card.id)) };
  });
  result.card_library = library;
  return materializePageCards(result);
}

export function assignCardToPage(project, pageIndex, cardId) {
  const result = normalizeCardLibrary(project), page = result.pages[pageIndex], id = String(cardId);
  if (page && result.card_library.some(card => String(card.id) === id) && !page.card_ids.includes(id)) page.card_ids.push(id);
  return materializePageCards(result);
}

export function removeCardFromPage(project, pageIndex, cardId) {
  const result = normalizeCardLibrary(project), page = result.pages[pageIndex], id = String(cardId);
  if (page) page.card_ids = page.card_ids.filter(value => value !== id);
  return materializePageCards(result);
}

function freshId(prefix, nonce) {
  return `${prefix}-${nonce}-${Math.random().toString(36).slice(2, 8)}`;
}

function cloneCardWithFreshIds(card, nonce) {
  const copy = clone(card);
  copy.id = freshId('card', nonce);
  copy.layers = (copy.layers || []).map(layer => ({ ...layer, id: freshId('layer', nonce) }));
  return copy;
}

export function duplicatePage(source, pageNumber, nonceFactory = () => Date.now().toString(36)) {
  const nonce = nonceFactory();
  const copy = clone(source || {});
  copy.id = freshId('page', nonce);
  copy.name = `Page ${pageNumber}`;
  copy.card_ids = [...(source?.card_ids || (source?.cards || []).map(card => String(card.id)))];
  copy.cards = [...(source?.cards || [])];
  return copy;
}

export function autoPaginateProject(project, templatePageIndex = 0, nonceFactory = () => Date.now().toString(36)) {
  const pages = project?.pages || [];
  const template = clone(pages[templatePageIndex] || pages[0] || {
    duration_ms: 5000,
    transition: null,
    grid: { rows: 1, columns: 1, gap_x: 20, gap_y: 20, padding: 24, fill_order: 'row', fit: 'contain' },
    scroll: { enabled: false, direction: 'left', speed_px_per_second: 80, loop: true, item_gap: 20, edge_pause_ms: 0 },
  });
  const normalized = normalizeCardLibrary(project);
  const cards = normalized.card_library;
  const capacity = pageCapacity(template);
  const count = Math.max(1, Math.ceil(cards.length / capacity));
  const result = [];
  for (let index = 0; index < count; index += 1) {
    const next = clone(template);
    next.id = freshId('page', nonceFactory());
    next.name = `Page ${index + 1}`;
    next.card_ids = cards.slice(index * capacity, (index + 1) * capacity).map(card => String(card.id));
    next.cards = [];
    result.push(next);
  }
  return materializePageCards({ ...normalized, pages: result });
}
