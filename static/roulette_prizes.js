/* ==========================================================================
   Gift Roulette — INDEPENDENT PRIZES (dashboard frontend)
   --------------------------------------------------------------------------
   A roulette prize is its OWN object: name, icon, whole action bundle, its
   own enabled switch, and (optionally) the gift it was copied from. Prizes no
   longer point at `Gifts[<id>]`, so editing a gift later cannot change a prize
   that was copied from it, and the same gift can be copied as many times as
   the operator wants (each copy gets a fresh UUID).

   Backend contract (schema_version 2):
     GET  /api/roulette/config ->
       {roulette: {enabled, trigger_gift_id, spin_ms, hold_ms, cooldown_ms,
                   pool: [legacy gift ids], prizes: [{id, name, icon_url,
                   enabled, actions, source_gift_id, source_gift_name,
                   diamond_count}], schema_version: 2},
        resolved_entries: [...], gift_templates: [{gift_id, label, icon_url,
                   diamond_count, actions, gift_name}], warnings: [...]}
     PUT  /api/roulette/config <- the same roulette block (prizes authoritative)

   This file owns ONLY the prize model + prize list + prize editor. The panel
   shell, timing knobs, slot sounds, Test Spin and the save round-trip stay in
   static/script.js, which calls into this namespace.

   Guarantees implemented here:
   - actions are rendered/collected with the EXISTING action-row helpers from
     script.js, so there is one action language in the app;
   - copying a gift deep-clones its whole bundle; `roulette` actions are
     stripped (a spin must never recurse) and reported, never silently dropped;
   - unknown action types and unknown action fields are PRESERVED and visibly
     flagged, so a save can never quietly lose part of a bundle;
   - icons are restricted to https:// or same-origin /static/ paths, with a
     built-in fallback glyph when the URL is unsafe or the image fails;
   - a local revision counter lets script.js refuse a stale save response.
   ========================================================================== */
(function (global) {
  'use strict';

  var MAX_PRIZES = 100;
  var PRIZE_ACTION_TYPES = ['minecraft', 'sound', 'webhook', 'random'];
  var MAX_NAME_LEN = 60;
  var MAX_ICON_LEN = 500;

  // Static, self-contained fallback glyph: no CDN font, so it paints offline.
  var FALLBACK_ICON_SVG =
    '<svg class="roulette-prize-fallback" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">' +
    '<path fill="currentColor" d="M12 2 3 7v10l9 5 9-5V7l-9-5Zm0 2.3 6.5 3.6L12 11.5 5.5 7.9 12 4.3ZM5 9.6l6.3 3.5v6.6L5 16.2V9.6Zm8 10.1v-6.6l6.3-3.5v6.6l-6.3 3.5Z"/>' +
    '</svg>';

  var state = {
    prizes: [],
    templates: [],
    warnings: [],
    revision: 0,
    editingIndex: -1,
    draftUnsupported: [],
    controlsBound: false,
  };

  // script.js assigns this; every discrete prize edit fires it (immediate save).
  var api = { onChange: null };
  Object.defineProperty(api, 'revision', { get: function () { return state.revision; } });

  // ── small helpers ─────────────────────────────────────────────────────────

  function deepClone(value) {
    try { return JSON.parse(JSON.stringify(value)); } catch (e) { return null; }
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  // script.js declares these with top-level `let`, which is NOT on window, so
  // read them as bare identifiers behind a typeof guard (never throws).
  function dashToast(message, type) {
    try { if (typeof showToast === 'function') showToast(message, type); } catch (e) { /* no dashboard shell */ }
  }

  function dashConfig() {
    try { return (typeof currentConfig !== 'undefined' && currentConfig) || null; }
    catch (e) { return global.currentConfig || null; }
  }

  function giftDisplayName(giftId) {
    try { if (typeof getGiftDisplayName === 'function') return getGiftDisplayName(giftId); } catch (e) { /* ignore */ }
    var cfg = dashConfig();
    var names = (cfg && cfg.GiftNames) || {};
    return names[giftId] || String(giftId);
  }

  function giftIconUrl(giftId) {
    try { if (typeof giftIconMap !== 'undefined' && giftIconMap[giftId]) return String(giftIconMap[giftId]); }
    catch (e) { /* ignore */ }
    var map = global.giftIconMap || {};
    return map[giftId] ? String(map[giftId]) : '';
  }

  function uuid() {
    try {
      if (global.crypto && typeof global.crypto.randomUUID === 'function') return global.crypto.randomUUID();
    } catch (e) { /* fall through */ }
    var rnd = function () { return Math.floor(Math.random() * 0x100000000).toString(16).padStart(8, '0'); };
    return rnd() + '-' + rnd() + '-' + rnd() + '-' + rnd();
  }

  // Only same-origin /static/ paths and https:// URLs are accepted. Everything
  // else (javascript:, data:, http:, protocol-relative //host, css words) is
  // rejected so a prize icon can never become an injection or a plain-http
  // mixed-content hole. Rejected/blank icons render the local fallback glyph.
  function safeIconUrl(raw) {
    var url = String(raw === undefined || raw === null ? '' : raw).trim();
    if (!url || url.length > MAX_ICON_LEN) return '';
    if (/^https:\/\/[^\s"'<>\\]+$/i.test(url)) return url;
    if (/^\/static\/[^\s"'<>\\]*$/i.test(url)) return url;
    return '';
  }

  function actionCount(actions) {
    return Array.isArray(actions) ? actions.length : 0;
  }

  function enabledPrizes() {
    return state.prizes.filter(function (p) { return p.enabled; });
  }

  // ── icon rendering ────────────────────────────────────────────────────────

  function buildFallbackIcon() {
    var wrap = el('span', 'roulette-prize-fallback-wrap');
    wrap.innerHTML = FALLBACK_ICON_SVG;
    return wrap;
  }

  function buildIcon(iconUrl, giftId) {
    var wrap = el('span', 'roulette-prize-icon');
    var safe = safeIconUrl(iconUrl);
    if (!safe && giftId) safe = safeIconUrl(giftIconUrl(giftId));
    if (!safe) { wrap.appendChild(buildFallbackIcon()); return wrap; }
    var img = document.createElement('img');
    img.alt = '';
    img.loading = 'lazy';
    img.addEventListener('error', function () {
      img.remove();
      if (!wrap.querySelector('.roulette-prize-fallback-wrap')) wrap.appendChild(buildFallbackIcon());
    });
    img.src = safe;
    wrap.appendChild(img);
    return wrap;
  }

  // ── gift templates ("Copy from gift") ─────────────────────────────────────

  function buildTemplatesFromConfig() {
    var gifts = (dashConfig() && dashConfig().Gifts) || {};
    var out = [];
    Object.keys(gifts).forEach(function (gid) {
      if (gid === 'GlobalActions') return;
      var actions = gifts[gid];
      if (!Array.isArray(actions) || actions.length === 0) return;
      var name = giftDisplayName(gid);
      out.push({
        gift_id: String(gid),
        label: name,
        gift_name: name,
        icon_url: giftIconUrl(gid),
        diamond_count: 0,
        actions: deepClone(actions) || [],
      });
    });
    return out;
  }

  function normalizeTemplate(raw) {
    if (!raw || typeof raw !== 'object') return null;
    var giftId = String(raw.gift_id === undefined || raw.gift_id === null ? '' : raw.gift_id);
    if (!giftId) return null;
    var name = String(raw.label || raw.gift_name || giftId);
    return {
      gift_id: giftId,
      label: name,
      gift_name: String(raw.gift_name || name),
      icon_url: String(raw.icon_url || ''),
      diamond_count: parseInt(raw.diamond_count, 10) || 0,
      actions: Array.isArray(raw.actions) ? deepClone(raw.actions) : [],
    };
  }

  function stripRouletteActions(actions) {
    var kept = [];
    var skipped = 0;
    (Array.isArray(actions) ? actions : []).forEach(function (action) {
      if (!action || typeof action !== 'object') return;
      var type = String(action.type || '');
      if (type === 'roulette') { skipped += 1; return; }
      if (type === 'random' && Array.isArray(action.actions)) {
        var copy = deepClone(action) || {};
        var subs = [];
        copy.actions.forEach(function (sub) {
          if (sub && typeof sub === 'object' && String(sub.type) === 'roulette') { skipped += 1; return; }
          subs.push(sub);
        });
        copy.actions = subs;
        kept.push(copy);
        return;
      }
      kept.push(deepClone(action));
    });
    return { actions: kept, skipped: skipped };
  }

  function templateGiftName(tpl) {
    return String((tpl && (tpl.gift_name || tpl.label)) || '');
  }

  function newPrize(name, iconUrl, actions, source) {
    return {
      id: uuid(),
      name: String(name || ''),
      icon_url: String(iconUrl || ''),
      enabled: true,
      actions: Array.isArray(actions) ? actions : [],
      source_gift_id: String((source && source.gift_id) || ''),
      source_gift_name: String((source && source.name) || ''),
      diamond_count: parseInt((source && source.diamond_count) || 0, 10) || 0,
    };
  }

  function normalizePrize(raw, index) {
    if (!raw || typeof raw !== 'object') return null;
    var id = String(raw.id || '').trim() || uuid();
    var sourceId = String(raw.source_gift_id || '');
    var sourceName = String(raw.source_gift_name || '');
    var name = String(raw.name || '').trim();
    if (!name) name = sourceName || ('Prize ' + (index + 1));
    return {
      id: id,
      name: name,
      icon_url: String(raw.icon_url || ''),
      enabled: raw.enabled !== false,
      actions: Array.isArray(raw.actions) ? (deepClone(raw.actions) || []) : [],
      source_gift_id: sourceId,
      source_gift_name: sourceName,
      diamond_count: parseInt(raw.diamond_count, 10) || 0,
    };
  }

  // ── model input from the server ───────────────────────────────────────────

  // Legacy compatibility ONLY: a schema-1 response carries `pool` of gift ids
  // and no `prizes`. The updated GET converts pool -> prizes server side; this
  // fallback keeps the dashboard usable against an older backend. `prizes` is
  // authoritative whenever it is present.
  function prizesFromLegacyPool(pool, entries) {
    var byId = {};
    (Array.isArray(entries) ? entries : []).forEach(function (entry) {
      if (entry && entry.gift_id !== undefined) byId[String(entry.gift_id)] = entry;
    });
    var gifts = (dashConfig() && dashConfig().Gifts) || {};
    var out = [];
    var missing = [];
    var skipped = 0;
    (Array.isArray(pool) ? pool : []).forEach(function (giftId) {
      var gid = String(giftId);
      if (!gid || gid === 'GlobalActions') return;
      var entry = byId[gid] || {};
      var raw = Array.isArray(entry.actions) ? entry.actions : gifts[gid];
      var stripped = stripRouletteActions(raw);
      if (!stripped.actions.length) { missing.push(gid); return; }
      skipped += stripped.skipped;
      var label = String(entry.label || giftDisplayName(gid));
      out.push(newPrize(label, String(entry.icon_url || giftIconUrl(gid)), stripped.actions, {
        gift_id: gid,
        name: label,
        diamond_count: parseInt(entry.diamond_count, 10) || 0,
      }));
    });
    if (missing.length) {
      pushWarning('Pool ' + (missing.length > 1 ? 'entries ' : 'entry ') + missing.join(', ') +
        ' could not be converted to a prize (no configured actions)');
    }
    if (skipped) {
      pushWarning('Legacy pool conversion skipped ' + skipped + ' Roulette action' +
        (skipped === 1 ? '' : 's') + ' — a spin cannot start another spin.');
    }
    return out;
  }

  function prizesFromRoulette(roulette, entries) {
    if (roulette && Array.isArray(roulette.prizes)) {
      return roulette.prizes.slice(0, MAX_PRIZES)
        .map(function (raw, i) { return normalizePrize(raw, i); })
        .filter(Boolean);
    }
    return prizesFromLegacyPool(roulette && roulette.pool, entries);
  }

  function load(response) {
    var body = response || {};
    var roulette = body.roulette || {};
    // A fresh panel load starts a new session: drop notes from the previous
    // one (conversion/pool notes from THIS load are pushed just below).
    state.warnings = [];
    state.templates = (Array.isArray(body.gift_templates) ? body.gift_templates : [])
      .map(normalizeTemplate).filter(Boolean);
    if (!state.templates.length) state.templates = buildTemplatesFromConfig();
    state.prizes = prizesFromRoulette(roulette, body.resolved_entries);
    state.editingIndex = -1;
    state.draftUnsupported = [];
    renderTemplatePicker();
    render();
  }

  // Server echo after a successful save: only applied when the caller verified
  // that no newer local edit happened while the request was in flight.
  function applyServer(roulette) {
    if (!roulette) return;
    state.prizes = prizesFromRoulette(roulette, []);
    if (state.editingIndex >= state.prizes.length) closeEditor(true);
    render();
  }

  function snapshot() { return deepClone(state.prizes) || []; }

  function collect() { return snapshot(); }

  // Legacy `pool` compatibility info: the source gift ids of the prizes, in
  // order, de-duplicated. Prizes are authoritative for the backend.
  function legacyPool(prizes) {
    var list = Array.isArray(prizes) ? prizes : state.prizes;
    var seen = {};
    var out = [];
    list.forEach(function (prize) {
      var gid = String((prize && prize.source_gift_id) || '');
      if (!gid || seen[gid]) return;
      seen[gid] = true;
      out.push(gid);
    });
    return out;
  }

  // ── warnings ──────────────────────────────────────────────────────────────

  function pushWarning(text) {
    if (!text) return;
    if (state.warnings.indexOf(text) === -1) state.warnings.push(text);
    renderWarnings([]);
  }

  function clearWarnings() { state.warnings = []; }

  // Single renderer for the panel's warning box: server warnings first, then
  // the local (client-side) notes so a copy that skipped something stays visible.
  function renderWarnings(serverWarnings) {
    var box = document.getElementById('roulette-warnings');
    if (!box) return;
    box.innerHTML = '';
    var all = (Array.isArray(serverWarnings) ? serverWarnings : []).concat(state.warnings);
    all.forEach(function (text) {
      box.appendChild(el('div', 'roulette-warning', text));
    });
  }

  // ── list rendering ────────────────────────────────────────────────────────

  function prizeSubtitle(prize) {
    if (prize.source_gift_id) {
      return 'From ' + (prize.source_gift_name || giftDisplayName(prize.source_gift_id)) +
        ' #' + prize.source_gift_id +
        (prize.diamond_count ? ' · ' + prize.diamond_count + (prize.diamond_count === 1 ? ' coin' : ' coins') : '');
    }
    return 'Custom prize';
  }

  function cardButton(label, iconClass, className) {
    var btn = el('button', 'btn btn-ghost btn-sm ' + (className || ''));
    btn.type = 'button';
    btn.title = label;
    btn.setAttribute('aria-label', label);
    btn.innerHTML = '<i class="fa-solid ' + iconClass + '"></i>';
    return btn;
  }

  function renderPrizeCard(prize, index, oddsCount) {
    var card = el('div', 'roulette-prize-card' + (prize.enabled ? '' : ' is-disabled'));
    card.dataset.prizeId = prize.id;
    card.dataset.prizeIndex = String(index);
    card.appendChild(buildIcon(prize.icon_url, prize.source_gift_id));

    var main = el('div', 'roulette-prize-main');
    var title = el('div', 'roulette-prize-title');
    title.appendChild(el('span', 'roulette-prize-name', prize.name));
    title.appendChild(el('span', 'roulette-prize-source', prizeSubtitle(prize)));
    main.appendChild(title);

    var meta = el('div', 'roulette-prize-meta');
    var actions = actionCount(prize.actions);
    meta.appendChild(el('span', 'roulette-prize-actions', actions + (actions === 1 ? ' action' : ' actions')));
    if (prize.enabled && oddsCount > 0) meta.appendChild(el('span', 'roulette-prize-odds', '1 in ' + oddsCount));
    if (!prize.enabled) meta.appendChild(el('span', 'roulette-prize-off', 'Disabled'));
    main.appendChild(meta);
    card.appendChild(main);

    var controls = el('div', 'roulette-prize-controls');

    var toggleLabel = el('label', 'roulette-prize-toggle');
    toggleLabel.title = prize.enabled ? 'Enabled — click to disable' : 'Disabled — click to enable';
    var toggle = document.createElement('input');
    toggle.type = 'checkbox';
    toggle.checked = !!prize.enabled;
    toggle.dataset.prizeAction = 'toggle';
    toggle.setAttribute('aria-label', 'Enable prize ' + prize.name);
    toggle.addEventListener('change', function () { togglePrize(index, toggle.checked); });
    toggleLabel.appendChild(toggle);
    controls.appendChild(toggleLabel);

    var up = cardButton('Move up', 'fa-arrow-up');
    up.dataset.prizeAction = 'up';
    up.disabled = index === 0;
    up.addEventListener('click', function () { movePrize(index, -1); });
    var down = cardButton('Move down', 'fa-arrow-down');
    down.dataset.prizeAction = 'down';
    down.disabled = index === state.prizes.length - 1;
    down.addEventListener('click', function () { movePrize(index, 1); });
    var edit = cardButton('Edit prize', 'fa-pen');
    edit.dataset.prizeAction = 'edit';
    edit.addEventListener('click', function () { openEditor(index); });
    var dup = cardButton('Duplicate prize', 'fa-clone');
    dup.dataset.prizeAction = 'duplicate';
    dup.addEventListener('click', function () { duplicatePrize(index); });
    var del = cardButton('Delete prize', 'fa-trash', 'btn-danger');
    del.dataset.prizeAction = 'delete';
    del.addEventListener('click', function () { deletePrize(index); });
    [up, down, edit, dup, del].forEach(function (btn) { controls.appendChild(btn); });
    card.appendChild(controls);
    return card;
  }

  function render() {
    var list = document.getElementById('roulette-prize-list');
    var count = document.getElementById('roulette-prize-count');
    var odds = document.getElementById('roulette-odds-line');
    var total = state.prizes.length;

    if (count) {
      count.textContent = total + ' / ' + MAX_PRIZES;
      count.dataset.full = total >= MAX_PRIZES ? '1' : '0';
    }
    if (odds) {
      var n = enabledPrizes().length;
      var text;
      if (n === 0) text = 'No enabled prizes — enable at least one before spinning.';
      else if (n === 1) text = 'Equal odds: only 1 enabled prize — a spin needs at least 2, so Roulette will refuse to run until you enable another.';
      else text = 'Equal odds: 1 in ' + n + ' per enabled prize (' + n + ' enabled).';
      if (total && n > 0 && n < total) text += ' ' + (total - n) + ' disabled.';
      odds.textContent = text;
      odds.dataset.enabled = String(n);
    }

    if (list) {
      list.innerHTML = '';
      if (!total) {
        var empty = el('div', 'roulette-prize-empty');
        empty.appendChild(el('strong', null, 'No prizes yet'));
        empty.appendChild(el('span', null, 'Copy a configured gift or add your own prize — every enabled prize has equal odds.'));
        list.appendChild(empty);
      } else {
        var oddsCount = enabledPrizes().length;
        state.prizes.forEach(function (prize, index) {
          list.appendChild(renderPrizeCard(prize, index, oddsCount));
        });
      }
    }
    renderTemplatePicker();
    updateToolbarLimits();
  }

  function renderTemplatePicker() {
    var sel = document.getElementById('roulette-gift-template-select');
    if (sel) {
      var current = sel.value;
      sel.innerHTML = '';
      var first = el('option', null, state.templates.length ? 'Copy from gift…' : 'No configured gifts with actions');
      first.value = '';
      sel.appendChild(first);
      state.templates.forEach(function (tpl) {
        var opt = el('option', null, tpl.label + ' (#' + tpl.gift_id + ')');
        opt.value = tpl.gift_id;
        sel.appendChild(opt);
      });
      sel.value = Array.prototype.some.call(sel.options, function (o) { return o.value === current; }) ? current : '';
    }
    var quick = document.getElementById('roulette-prize-quick');
    if (quick) {
      quick.innerHTML = '';
      if (!state.templates.length) {
        quick.appendChild(el('span', 'roulette-prize-quick-hint', 'No configured gifts yet — add gifts in the Gifts tab to copy one here.'));
      }
      state.templates.forEach(function (tpl) {
        var chip = el('button', 'roulette-prize-chip');
        chip.type = 'button';
        chip.dataset.giftId = tpl.gift_id;
        chip.title = 'Copy "' + tpl.label + '" (' + tpl.actions.length + ' actions) as a prize';
        chip.appendChild(buildIcon(tpl.icon_url, tpl.gift_id));
        chip.appendChild(el('span', 'roulette-prize-chip-label', tpl.label));
        chip.addEventListener('click', function () { copyFromGift(tpl.gift_id); });
        quick.appendChild(chip);
      });
    }
  }

  function updateToolbarLimits() {
    var full = state.prizes.length >= MAX_PRIZES;
    ['btn-roulette-copy-gift', 'btn-roulette-add-prize'].forEach(function (id) {
      var btn = document.getElementById(id);
      if (btn) { btn.disabled = full; btn.title = full ? 'Limit of ' + MAX_PRIZES + ' prizes reached' : ''; }
    });
    var sel = document.getElementById('roulette-gift-template-select');
    if (sel) sel.disabled = full;
    var quick = document.getElementById('roulette-prize-quick');
    if (quick) quick.querySelectorAll('.roulette-prize-chip').forEach(function (chip) { chip.disabled = full; });
  }

  // ── model mutations (each one bumps the revision) ─────────────────────────

  function bump() {
    state.revision += 1;
    render();
    if (typeof api.onChange === 'function') {
      try { api.onChange(); } catch (e) { /* save path reports its own errors */ }
    }
  }

  function canAdd() {
    if (state.prizes.length >= MAX_PRIZES) {
      dashToast('Prize limit is ' + MAX_PRIZES + ' — remove one first', 'warning');
      return false;
    }
    return true;
  }

  function copyFromGift(giftId) {
    if (!canAdd()) return null;
    var gid = String(giftId);
    var tpl = state.templates.filter(function (t) { return t.gift_id === gid; })[0];
    if (!tpl) {
      dashToast('Gift #' + gid + ' is not a configured gift with actions', 'error');
      return null;
    }
    var stripped = stripRouletteActions(tpl.actions);
    var prize = newPrize(tpl.label, tpl.icon_url, stripped.actions, {
      gift_id: tpl.gift_id,
      name: tpl.gift_name || tpl.label,
      diamond_count: tpl.diamond_count,
    });
    state.prizes.push(prize);
    clearWarnings();
    if (stripped.skipped) {
      pushWarning('Copied "' + tpl.label + '" without ' + stripped.skipped +
        ' Roulette action' + (stripped.skipped === 1 ? '' : 's') + ' — a spin cannot start another spin.');
      dashToast('Copied "' + tpl.label + '" and skipped its Roulette action (no recursion)', 'warning');
    } else {
      dashToast('Copied "' + tpl.label + '" as a prize (whole action bundle)', 'success');
    }
    bump();
    return prize.id;
  }

  function addCustomPrize() {
    if (!canAdd()) return null;
    var prize = newPrize('New prize', '', [], null);
    state.prizes.push(prize);
    var index = state.prizes.length - 1;
    bump();
    openEditor(index);
    return prize.id;
  }

  function duplicatePrize(index) {
    var prize = state.prizes[index];
    if (!prize || !canAdd()) return;
    var copy = deepClone(prize) || {};
    copy.id = uuid();
    copy.name = prize.name + ' copy';
    state.prizes.splice(index + 1, 0, normalizePrize(copy, index + 1));
    bump();
  }

  function deletePrize(index) {
    var prize = state.prizes[index];
    if (!prize) return;
    if (state.editingIndex === index) closeEditor(true);
    state.prizes.splice(index, 1);
    if (state.editingIndex > index) state.editingIndex -= 1;
    bump();
  }

  function togglePrize(index, enabled) {
    var prize = state.prizes[index];
    if (!prize) return;
    prize.enabled = !!enabled;
    bump();
  }

  function movePrize(index, delta) {
    var target = index + delta;
    if (target < 0 || target >= state.prizes.length) return;
    var tmp = state.prizes[index];
    state.prizes[index] = state.prizes[target];
    state.prizes[target] = tmp;
    bump();
  }

  // ── action rows inside the prize editor ───────────────────────────────────

  // Renders via the SHARED action-row helper (script.js) so the prize editor
  // speaks exactly the same action language as the gift/event editors.
  // Returns the unsupported entries as [{index, action}] so they can be spliced
  // back into the collected bundle: never lost, and visibly flagged.
  function renderActionsInto(container, actions) {
    container.innerHTML = '';
    var unsupported = [];
    var list = Array.isArray(actions) ? actions : [];
    list.forEach(function (action, index) {
      if (!action || typeof action !== 'object') return;
      var type = String(action.type || '');
      if (PRIZE_ACTION_TYPES.indexOf(type) === -1) {
        unsupported.push({ index: index, action: deepClone(action) });
        return;
      }
      if (typeof appendActionRowToContainer !== 'function') {
        unsupported.push({ index: index, action: deepClone(action) });
        return;
      }
      appendActionRowToContainer(container, type, action);
      var row = container.lastElementChild;
      if (!row) return;
      // Keep the raw object so collection can merge back fields the shared
      // renderer does not show (never silently drop an unknown action field).
      row.__rouletteRaw = action;
      if (type === 'random') decorateRandomRow(row, action);
    });
    unsupported.forEach(function (item) {
      var notice = el('div', 'roulette-prize-unsupported');
      notice.appendChild(el('span', null, 'Unsupported action kept as-is: type "' + String(item.action && item.action.type) + '"'));
      container.appendChild(notice);
    });
    return unsupported;
  }

  function decorateRandomRow(row, action) {
    var raws = Array.isArray(action.actions) ? action.actions : [];
    row.querySelectorAll('.random-sub-action').forEach(function (node, i) {
      node.dataset.rawIndex = String(i);
      var raw = raws[i];
      var rawType = raw && typeof raw.type === 'string' ? raw.type : '';
      var select = node.querySelector('.random-sub-type');
      if (!select || !rawType) return;
      if (['minecraft', 'sound'].indexOf(rawType) !== -1) return;
      var opt = document.createElement('option');
      opt.value = rawType;
      opt.textContent = rawType + ' (unsupported)';
      select.appendChild(opt);
      select.value = rawType;
    });
  }

  // Merge the shared collector's output (known fields, as typed) back over the
  // raw action so unknown fields survive a round-trip.
  function mergeRawAction(raw, base, clone) {
    if (!raw || typeof raw !== 'object') return base;
    var out = deepClone(raw) || {};
    Object.assign(out, base);
    if (base.type === 'random' && Array.isArray(base.actions)) {
      var rawSubs = Array.isArray(raw.actions) ? raw.actions : [];
      var nodes = clone ? Array.prototype.slice.call(clone.querySelectorAll('.random-sub-action')) : [];
      out.actions = base.actions.map(function (sub, i) {
        var node = nodes[i];
        var idx = node && node.dataset.rawIndex !== undefined ? parseInt(node.dataset.rawIndex, 10) : i;
        var rawSub = Number.isInteger(idx) && idx >= 0 && idx < rawSubs.length ? rawSubs[idx] : null;
        if (!rawSub || typeof rawSub !== 'object' || String(rawSub.type || '') !== String(sub.type || '')) return sub;
        return Object.assign(deepClone(rawSub) || {}, sub);
      });
    }
    return out;
  }

  function collectActionsWithRaw(container, preserved) {
    var out = [];
    if (container && typeof collectActionsFromContainer === 'function') {
      Array.prototype.slice.call(container.querySelectorAll('.action-row')).forEach(function (row) {
        var wrapper = document.createElement('div');
        var clone = row.cloneNode(true);
        clone.__rouletteRaw = row.__rouletteRaw;
        wrapper.appendChild(clone);
        var base = collectActionsFromContainer(wrapper);
        if (!base.length) return;  // blank row: same behaviour as the gift editor
        out.push(mergeRawAction(row.__rouletteRaw, base[0], clone));
      });
    }
    (Array.isArray(preserved) ? preserved : []).forEach(function (item) {
      if (!item || !item.action) return;
      out.splice(Math.min(item.index, out.length), 0, deepClone(item.action));
    });
    return out;
  }

  function collectEditorActions() {
    return collectActionsWithRaw(document.getElementById('roulette-prize-actions'), state.draftUnsupported);
  }

  // ── prize editor ──────────────────────────────────────────────────────────

  function editorEl(id) { return document.getElementById(id); }

  function setEditorError(text) {
    var box = editorEl('roulette-prize-error');
    if (!box) return;
    box.textContent = text || '';
    box.dataset.state = text ? 'error' : '';
  }

  function renderIconPreview() {
    var wrap = editorEl('roulette-prize-icon-preview');
    if (!wrap) return;
    var value = editorEl('roulette-prize-icon') ? editorEl('roulette-prize-icon').value : '';
    var safe = safeIconUrl(value);
    wrap.innerHTML = '';
    wrap.classList.toggle('is-invalid', !!String(value || '').trim() && !safe);
    if (safe) {
      var img = document.createElement('img');
      img.alt = '';
      img.addEventListener('error', function () {
        wrap.innerHTML = '';
        wrap.classList.add('is-invalid');
        wrap.appendChild(buildFallbackIcon());
      });
      img.src = safe;
      wrap.appendChild(img);
    } else {
      wrap.appendChild(buildFallbackIcon());
    }
    var hint = editorEl('roulette-prize-icon-hint');
    if (hint) {
      hint.textContent = safe
        ? 'Icon loaded from ' + (safe.indexOf('/static/') === 0 ? 'this app (local)' : 'an https link')
        : (String(value || '').trim()
            ? 'Blocked: use an https:// link or a /static/ path'
            : 'Optional — leave empty for the built-in placeholder');
    }
  }

  function openEditor(index) {
    var prize = state.prizes[index];
    if (!prize) return;
    state.editingIndex = index;
    var draft = deepClone(prize) || {};
    var nameInput = editorEl('roulette-prize-name');
    var iconInput = editorEl('roulette-prize-icon');
    var enabledInput = editorEl('roulette-prize-enabled');
    if (nameInput) nameInput.value = draft.name || '';
    if (iconInput) iconInput.value = draft.icon_url || '';
    if (enabledInput) enabledInput.checked = draft.enabled !== false;
    var title = editorEl('roulette-prize-modal-title');
    if (title) title.textContent = 'Edit prize — ' + (draft.name || 'unnamed');
    var source = editorEl('roulette-prize-source');
    if (source) {
      source.textContent = draft.source_gift_id
        ? 'Copied from ' + (draft.source_gift_name || draft.source_gift_id) + ' (#' + draft.source_gift_id +
          ') — this prize is independent of that gift now.'
        : 'Custom prize — not linked to any gift.';
    }
    setEditorError('');
    var container = editorEl('roulette-prize-actions');
    state.draftUnsupported = container ? renderActionsInto(container, draft.actions || []) : [];
    renderIconPreview();
    var modal = editorEl('roulette-prize-modal');
    if (modal) {
      modal.classList.add('active');
      modal.setAttribute('aria-hidden', 'false');
    }
  }

  function closeEditor(keepModel) {
    state.editingIndex = -1;
    state.draftUnsupported = [];
    setEditorError('');
    var modal = editorEl('roulette-prize-modal');
    if (modal) {
      modal.classList.remove('active');
      modal.setAttribute('aria-hidden', 'true');
    }
    if (!keepModel) return;
  }

  function savePrize() {
    if (state.editingIndex < 0 || !state.prizes[state.editingIndex]) { closeEditor(true); return false; }
    var nameInput = editorEl('roulette-prize-name');
    var iconInput = editorEl('roulette-prize-icon');
    var enabledInput = editorEl('roulette-prize-enabled');
    var name = String(nameInput ? nameInput.value : '').trim();
    var iconRaw = String(iconInput ? iconInput.value : '').trim();

    // Validation NEVER discards the draft: the modal stays open with everything
    // the operator typed, and only the first problem is reported.
    if (!name) { setEditorError('Prize name is required.'); return false; }
    if (name.length > MAX_NAME_LEN) { setEditorError('Prize name must be ' + MAX_NAME_LEN + ' characters or fewer.'); return false; }
    if (iconRaw && !safeIconUrl(iconRaw)) {
      setEditorError('Icon must be an https:// link or a /static/ path from this app.');
      return false;
    }
    var actions = collectEditorActions();
    var realActions = actions.filter(function (a) { return a && typeof a === 'object' && a.type && a.type !== 'roulette'; });
    if (!realActions.length) {
      setEditorError('Add at least one action — a prize with no action would do nothing.');
      return false;
    }

    var prize = state.prizes[state.editingIndex];
    prize.name = name;
    prize.icon_url = iconRaw;
    prize.enabled = enabledInput ? !!enabledInput.checked : prize.enabled;
    prize.actions = actions;
    closeEditor(true);
    bump();
    return true;
  }

  // ── control binding ───────────────────────────────────────────────────────

  function bindControls() {
    if (state.controlsBound) return;
    state.controlsBound = true;

    var copyBtn = document.getElementById('btn-roulette-copy-gift');
    if (copyBtn) copyBtn.addEventListener('click', function () {
      var sel = document.getElementById('roulette-gift-template-select');
      if (!sel || !sel.value) { dashToast('Choose a configured gift to copy', 'info'); return; }
      copyFromGift(sel.value);
    });
    var addBtn = document.getElementById('btn-roulette-add-prize');
    if (addBtn) addBtn.addEventListener('click', function () { addCustomPrize(); });

    var tools = document.getElementById('roulette-prize-action-tools');
    if (tools) tools.querySelectorAll('[data-add-action]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var container = editorEl('roulette-prize-actions');
        if (!container) return;
        if (typeof appendActionRowToContainer !== 'function') return;
        var type = btn.dataset.addAction;
        if (type === 'roulette') return;  // no recursion, ever
        appendActionRowToContainer(container, type, null);
        var row = container.lastElementChild;
        if (row) row.__rouletteRaw = null;
      });
    });

    var nameInput = editorEl('roulette-prize-name');
    if (nameInput) nameInput.addEventListener('input', setEditorError.bind(null, ''));
    var iconInput = editorEl('roulette-prize-icon');
    if (iconInput) {
      iconInput.addEventListener('input', renderIconPreview);
      iconInput.addEventListener('change', renderIconPreview);
    }

    var save = editorEl('btn-roulette-prize-save');
    if (save) save.addEventListener('click', savePrize);
    ['btn-roulette-prize-cancel', 'btn-roulette-prize-close'].forEach(function (id) {
      var btn = editorEl(id);
      if (btn) btn.addEventListener('click', function () { closeEditor(true); });
    });
    var modal = editorEl('roulette-prize-modal');
    if (modal) {
      modal.addEventListener('mousedown', function (event) {
        if (event.target === modal) closeEditor(true);  // Cancel — nothing persisted
      });
    }
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && editorEl('roulette-prize-modal') && editorEl('roulette-prize-modal').classList.contains('active')) {
        closeEditor(true);
      }
    });

    renderTemplatePicker();
    updateToolbarLimits();
  }

  api.MAX_PRIZES = MAX_PRIZES;
  api.safeIconUrl = safeIconUrl;
  api.load = load;
  api.applyServer = applyServer;
  api.collect = collect;
  api.snapshot = snapshot;
  api.legacyPool = legacyPool;
  api.render = render;
  api.renderWarnings = renderWarnings;
  api.pushWarning = pushWarning;
  api.bindControls = bindControls;
  api.copyFromGift = copyFromGift;
  api.addCustomPrize = addCustomPrize;
  api.duplicatePrize = duplicatePrize;
  api.deletePrize = deletePrize;
  api.togglePrize = togglePrize;
  api.movePrize = movePrize;
  api.openEditor = openEditor;
  api.closeEditor = closeEditor;
  api.savePrize = savePrize;
  api.isEditing = function () { return state.editingIndex >= 0; };
  api.templates = function () { return deepClone(state.templates) || []; };

  global.RoulettePrizes = api;
})(typeof window !== 'undefined' ? window : this);
