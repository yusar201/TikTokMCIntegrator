/**
 * Gift Card Studio — page-assignment row helpers (pure, DOM-free).
 *
 * The "Cards on this page" picker shows each library card as a rich row:
 * gift icon + gift name + the card's visible action text. Action text comes
 * ONLY from the card's text layers (authored from the profile's
 * GiftDescriptions at import) — never from commands, intents, or the gift
 * name. Imported by studio.js; unit-tested directly.
 */
import { escapeHtml } from './editor.js';

export function cardActionText(card) {
  const layers = (card && card.layers) || [];
  const main = layers.find((layer) => layer && layer.type === 'text'
    && (layer.role === 'main' || layer.name === 'Main Text'));
  if (main && String(main.text || '').trim()) return String(main.text).trim();
  const any = layers.find((layer) => layer && layer.type === 'text'
    && String(layer.text || '').trim());
  return any ? String(any.text).trim() : '';
}

export function cardGiftIcon(card) {
  const gift = (card && card.gift_ref) || {};
  if (gift.icon) return gift.icon;
  const badge = ((card && card.layers) || [])
    .find((layer) => layer && layer.type === 'gift_icon' && layer.asset);
  return badge ? badge.asset : '';
}

export function cardDisplayName(card) {
  return (card && (card.name || card.gift_ref?.name)) || (card && card.id) || '';
}

export function rowMatches(card, query) {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return true;
  const hay = `${card?.name || ''} ${card?.gift_ref?.name || ''} ${cardActionText(card)}`.toLowerCase();
  return q.split(/\s+/).every((word) => hay.includes(word));
}

export function assignRowHtml(card, selected) {
  const action = cardActionText(card);
  const icon = cardGiftIcon(card);
  const name = cardDisplayName(card);
  const thumb = icon
    ? `<img src="${escapeHtml(icon)}" alt="" loading="lazy">`
    : `<span class="gcs-assign-fallback" aria-hidden="true"><i class="fa-solid fa-gift"></i></span>`;
  const sub = action
    ? `<small class="gcs-assign-action">${escapeHtml(action)}</small>`
    : `<small class="gcs-assign-noaction">No action text</small>`;
  return `<div class="gcs-assign-row${selected ? ' selected' : ''}"`
    + ` data-assign-card="${escapeHtml(card.id)}" role="checkbox"`
    + ` aria-checked="${selected ? 'true' : 'false'}" tabindex="0"`
    + ` title="${escapeHtml(name)}${action ? ` — ${escapeHtml(action)}` : ''}">`
    + `${thumb}<span class="gcs-assign-copy"><strong>${escapeHtml(name)}</strong>${sub}</span>`
    + `<span class="gcs-assign-check" aria-hidden="true"><i class="fa-solid fa-check"></i></span></div>`;
}
