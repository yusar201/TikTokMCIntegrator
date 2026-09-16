// ==========================================
// STATE
// ==========================================
let currentConfig = {};
let editingGiftKey = null;
let giftIconMap = {};
let giftNameMap = {};
let streakDeltaSelected = [];
let cachedAvailableGifts = [];
let cachedAllGifts = [];
let botRunning = false;
let streamStartTime = null;
let tickerCount = 0;
let songConfig = null;
let spotifyConnected = false;
let installedAddons = [];
let selectedAddonId = null;
let addonActionPresets = [];
const OVERLAY_PREVIEW_TYPES = ['chat', 'gifts', 'follows', 'superfan', 'topshowcase', 'topgift', 'topstreak', 'song', 'coingoal', 'topgifter', 'giftgoal', 'roulette'];

// ==========================================
// NAVIGATION
// ==========================================
let giftStudioModule = null;
let giftStudioLoad = null;
async function activateGiftStudio() {
  if (!giftStudioLoad) {
    giftStudioLoad = import('/static/gift-studio/studio.js?v=12').then(mod => (giftStudioModule = mod));
  }
  await giftStudioLoad;
  return giftStudioModule.activate();
}
function deactivateGiftStudio() {
  if (giftStudioModule) giftStudioModule.deactivate();
}

function switchPanel(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const panel = document.getElementById('panel-' + name);
  const nav = document.querySelector(`[data-panel="${name}"]`);
  if (panel) panel.classList.add('active');
  if (nav) nav.classList.add('active');
  if (name === 'gift-studio') activateGiftStudio().catch(err => showToast(err.message || 'Gift Studio failed to open', 'error'));
  else deactivateGiftStudio();
  // Overlay preview iframes are expensive WebView2 pages. Run them only while
  // this panel is visible and only when the user explicitly enables each one.
  if (name === 'overlays') initOverlayPreviews();
  else suspendOverlayPreviews();
  if (name === 'addons') loadAddons();
  if (name === 'tts') loadTtsConfig();
  if (name === 'points') loadPoints();
  if (name === 'roulette') initRoulettePanel();
}

// ==========================================
// TOAST NOTIFICATIONS
// ==========================================
function showToast(msg, type) {
  const container = document.getElementById('toast-container');
  const iconMap = { gift: 'fa-gift', follow: 'fa-user-plus', success: 'fa-check', info: 'fa-info', error: 'fa-triangle-exclamation', warning: 'fa-triangle-exclamation' };
  const div = document.createElement('div');
  div.className = `toast ${type}-toast`;
  div.innerHTML = `<i class="fa-solid ${iconMap[type] || 'fa-info'}"></i> ${msg}`;
  container.appendChild(div);
  setTimeout(() => { div.style.opacity='0'; div.style.transition='opacity 0.3s';
    setTimeout(() => div.remove(), 300); }, 3500);
}

// ==========================================
// BOT CONTROL
// ==========================================
function updateBotStatusUI(isRunning, meta = {}) {
  const dot = document.getElementById('status-dot');
  const text = document.getElementById('status-text');
  const btn = document.getElementById('btn-toggle');

  botRunning = isRunning;

  // Map the derived connection state to a display label + dot class.
  const state = meta.state || (isRunning ? 'connecting' : 'offline');
  const STATE_META = {
    starting:    { cls: 'connecting', label: 'Starting…' },
    connecting:  { cls: 'connecting', label: 'Connecting…' },
    connected:   { cls: 'online',     label: 'Connected' },
    reconnecting:{ cls: 'connecting', label: 'Reconnecting…' },
    disconnected:{ cls: 'offline',    label: 'Disconnected' },
    failed:      { cls: 'failed',     label: 'Failed' },
    ended:       { cls: 'offline',    label: 'Offline' },
    stopped:     { cls: 'offline',    label: 'Offline' },
    offline:     { cls: 'offline',    label: 'Offline' },
  };
  const m = STATE_META[state] || STATE_META.offline;

  dot.className = 'status-dot ' + m.cls;
  text.textContent = m.label;

  // Attach the error as a tooltip when present (e.g. retries exhausted).
  if (meta.error) {
    text.title = meta.error;
    dot.title = meta.error;
  } else {
    text.title = '';
    dot.title = '';
  }

  // Button reflects process liveness, not connection state: while the bot
  // subprocess is running we must be able to stop it, even if it's still
  // connecting or has failed to reach TikTok.
  if (isRunning) {
    btn.innerHTML = '<i class="fa-solid fa-stop"></i> Stop Bot';
    btn.className = 'btn btn-danger';
    btn.onclick = stopBot;
    // Start/resume timer only when actually connected
    if (state === 'connected') {
      resumeTimerWhenConnected();
    } else if (state === 'connecting' || state === 'starting' || state === 'reconnecting') {
      // Timer does NOT start during these states; ensure it shows "--:--:--"
      if (timerInterval) clearInterval(timerInterval);
      timerInterval = null;
      document.getElementById('stream-timer').textContent = '--:--:--';
    }
    // Append "DEBUG MODE" suffix if LogOnlyMode is ON
    const settings = meta.settings || {};
    if (settings.LogOnlyMode) {
      text.textContent = `${m.label} | DEBUG MODE`;
    }
  } else {
    btn.innerHTML = '<i class="fa-solid fa-play"></i> Start Bot';
    btn.className = 'btn btn-primary';
    btn.onclick = startBot;
    // Pause timer and accumulate any elapsed time so far
    pauseTimer();
    if (_timerState.totalElapsedSec === 0 && streamStartTime) {
      _timerState.totalElapsedSec = Math.floor((Date.now() - streamStartTime) / 1000);
    }
    streamStartTime = null;
    if (!_timerState.lastPauseMs) {
      // Ensure display stays at accumulated time while stopped
      document.getElementById('stream-timer').textContent = formatDuration(_timerState.totalElapsedSec);
    }
  }
}

function toggleBot() {
  if (botRunning) { stopBot(); } else { startBot(); }
}

// Timer
let timerInterval = null;
// Keep this simple: we store `totalElapsedBeforeDisconnect` (seconds) when disconnected,
// and `lastPauseTs` (Date.now() ms). resumeTime will accumulate across reconnects.
let _timerState = { 
  totalElapsedSec: 0, 
  lastPauseMs: null,
  startedNewStream: false  // Track if we've started a fresh stream (for reset logic)
};

function startTimerFromConnectedState() {
  if (timerInterval) clearInterval(timerInterval);
  timerInterval = setInterval(() => {
    if (!_timerState.totalElapsedSec && !_timerState.lastPauseMs && !streamStartTime) return;
    if (_timerState.lastPauseMs) {
      // Paused: show accumulated time only
      document.getElementById('stream-timer').textContent = formatDuration(_timerState.totalElapsedSec);
      return;
    }
    const elapsed = Math.floor((Date.now() - streamStartTime) / 1000) + _timerState.totalElapsedSec;
    document.getElementById('stream-timer').textContent = formatDuration(elapsed);
  }, 1000);
}

function formatDuration(totalSeconds) {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function pauseTimer() {
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
  _timerState.lastPauseMs = Date.now();
}

function resumeTimerWhenConnected() {
  // When connected, compute how much we had accumulated before this connect
  // For simplicity on first connect, we just start counting from 0 and build up via accumulated time.
  // We'll accumulate elapsed time each tick while running, then reset on disconnect.
  _timerState.lastPauseMs = null;
  // If room changed (new stream) or first connect, reset the timer completely
  if (!_timerState.startedNewStream || !streamStartTime) {
    _timerState.totalElapsedSec = 0;
    streamStartTime = Date.now();
    _timerState.startedNewStream = true;
  } else {
    // Reconnect to same stream - keep accumulating from where we left off
    const now = Date.now();
    const accumulated = Math.floor((now - streamStartTime) / 1000);
    _timerState.totalElapsedSec += accumulated;
    streamStartTime = now;
  }
  startTimerFromConnectedState();
}

// ==========================================
// API CALLS
// ==========================================
async function loadConfig() {
  try {
    const res = await fetch(`/api/config?_=${Date.now()}`, { cache: 'no-store' });
    currentConfig = await res.json();
    populateSettings();
    renderEventsGrid();
    populateGifts();
    // Re-render event browser if registry is loaded (for custom events browser)
    if (eventRegistryData) renderEventBrowser();
    // Apply saved theme from config (syncs across machines; localStorage handles instant apply)
    if (currentConfig.Settings && currentConfig.Settings.Theme) {
      applyTheme(currentConfig.Settings.Theme, false);
    }
    // Update TikTok handle in topbar
    if (currentConfig.Settings && currentConfig.Settings.TikTokUsername) {
      document.getElementById('tiktok-handle-display').textContent = currentConfig.Settings.TikTokUsername;
    }
  } catch (e) {
    console.error("Failed to load config:", e);
  }
}

async function saveConfigData(options = {}) {
  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentConfig)
    });
    const data = await res.json();
    showToast(options.successMessage || data.message || 'Configuration saved!', 'success');
  } catch (e) {
    showToast("Error saving config", 'error');
  }
}

async function checkBotStatus() {
  try {
    const res = await fetch('/api/bot/status');
    const data = await res.json();
    updateBotStatusUI(data.running, data);
  } catch (e) {
    updateBotStatusUI(false);
  }
}

async function startBot() {
  try {
    const res = await fetch('/api/bot/start', { method: 'POST' });
    const data = await res.json();
    if(data.status === 'success') {
      // Don't jump to "online" — the bot subprocess is up but TikTok connection
      // is still resolving. Show "connecting" and let checkBotStatus() poll the
      // real state file until ConnectEvent lands.
      updateBotStatusUI(true, { state: 'connecting' });
      showToast('Bot starting…', 'info');
    } else {
      showToast(data.message, data.status === 'warning' ? 'info' : 'error');
      if (data.external) updateBotStatusUI(true, data);
    }
  } catch(e) {
    showToast("Failed to start bot", 'error');
  }
}

async function stopBot() {
  try {
    const res = await fetch('/api/bot/stop', { method: 'POST' });
    const data = await res.json();
    if(data.status === 'success') {
      updateBotStatusUI(false);
      showToast('Bot stopped', 'info');
      // Reset timer state on stop so new streams start from 0
      _timerState.totalElapsedSec = 0;
      streamStartTime = null;
      _timerState.startedNewStream = false;
      document.getElementById('stream-timer').textContent = '--:--:--';
    }
  } catch(e) {
    showToast("Failed to stop bot", 'error');
  }
}

function ensureBotCloseWarningModal() {
  let modal = document.getElementById('bot-close-warning-modal');
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = 'bot-close-warning-modal';
  modal.className = 'bot-close-warning-overlay';
  modal.innerHTML = `
    <div class="bot-close-warning-box">
      <div class="bot-close-warning-corner c1"></div>
      <div class="bot-close-warning-corner c2"></div>
      <div class="bot-close-warning-corner c3"></div>
      <div class="bot-close-warning-corner c4"></div>
      <div class="bot-close-warning-header">
        <div class="bot-close-warning-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>
        <div>
          <h3>Bot Still Connected</h3>
          <p>The TikTok bot is still running in the background.</p>
        </div>
      </div>
      <div class="bot-close-warning-body">
        Closing the app window now can leave the bot connected without the dashboard.
        Choose how you want to exit.
      </div>
      <div class="bot-close-warning-actions">
        <button class="btn btn-ghost" id="bot-close-keep"><i class="fa-solid fa-arrow-left"></i> Keep App Open</button>
        <button class="btn btn-warning" id="bot-close-leave"><i class="fa-solid fa-door-open"></i> Close App Only</button>
        <button class="btn btn-danger" id="bot-close-stop"><i class="fa-solid fa-stop"></i> Stop Bot & Close</button>
      </div>
    </div>`;
  document.body.appendChild(modal);
  modal.querySelector('#bot-close-keep').onclick = () => modal.classList.remove('active');
  modal.querySelector('#bot-close-leave').onclick = async () => {
    modal.classList.remove('active');
    showToast('Closing app; bot stays running', 'info');
    if (window.pywebview?.api?.close_app) await window.pywebview.api.close_app('leave');
  };
  modal.querySelector('#bot-close-stop').onclick = async () => {
    modal.classList.remove('active');
    showToast('Stopping bot and closing app...', 'info');
    if (window.pywebview?.api?.close_app) await window.pywebview.api.close_app('stop');
  };
  return modal;
}

window.showBotCloseWarning = function(source = 'window') {
  const modal = ensureBotCloseWarningModal();
  modal.classList.add('active');
};

// ==========================================
// THEMED CONFIRM DIALOG (replaces native confirm())
// Same Stardew wood-panel shell as the bot close guard.
// Usage: if (!(await appConfirm({ title, message, confirmText, tone, icon }))) return;
// ==========================================
function ensureAppConfirmModal() {
  let modal = document.getElementById('app-confirm-modal');
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = 'app-confirm-modal';
  modal.className = 'bot-close-warning-overlay app-confirm-overlay';
  modal.innerHTML = `
    <div class="bot-close-warning-box app-confirm-box">
      <div class="bot-close-warning-corner c1"></div>
      <div class="bot-close-warning-corner c2"></div>
      <div class="bot-close-warning-corner c3"></div>
      <div class="bot-close-warning-corner c4"></div>
      <div class="bot-close-warning-header">
        <div class="bot-close-warning-icon" id="app-confirm-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>
        <div>
          <h3 id="app-confirm-title">Are you sure?</h3>
          <p id="app-confirm-subtitle" style="display:none;"></p>
        </div>
      </div>
      <div class="bot-close-warning-body" id="app-confirm-body"></div>
      <div class="bot-close-warning-actions">
        <button class="btn btn-ghost" id="app-confirm-cancel"><i class="fa-solid fa-xmark"></i> Cancel</button>
        <button class="btn btn-danger" id="app-confirm-ok"><i class="fa-solid fa-check"></i> Confirm</button>
      </div>
    </div>`;
  document.body.appendChild(modal);
  // Backdrop click and Escape both count as Cancel.
  modal.addEventListener('click', (e) => {
    if (e.target === modal) {
      const c = modal.querySelector('#app-confirm-cancel');
      if (c) c.click();
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal.classList.contains('active')) {
      const c = modal.querySelector('#app-confirm-cancel');
      if (c) c.click();
    }
  });
  return modal;
}

window.appConfirm = function(opts) {
  const o = typeof opts === 'string' ? { message: opts } : (opts || {});
  const modal = ensureAppConfirmModal();
  if (modal._pendingResolve) { modal._pendingResolve(false); modal._pendingResolve = null; }
  modal.querySelector('#app-confirm-title').textContent = o.title || 'Are you sure?';
  const sub = modal.querySelector('#app-confirm-subtitle');
  sub.textContent = o.subtitle || '';
  sub.style.display = o.subtitle ? '' : 'none';
  const body = modal.querySelector('#app-confirm-body');
  body.textContent = o.message || '';
  body.style.display = o.message ? '' : 'none';
  const okBtn = modal.querySelector('#app-confirm-ok');
  okBtn.className = 'btn ' + (o.tone === 'danger' ? 'btn-danger' : 'btn-warning');
  okBtn.innerHTML = `<i class="fa-solid fa-check"></i> ${o.confirmText || 'Confirm'}`;
  const icon = modal.querySelector('#app-confirm-icon');
  icon.className = 'bot-close-warning-icon' + (o.tone === 'danger' ? ' app-confirm-icon-danger' : '');
  icon.innerHTML = `<i class="fa-solid ${o.icon || 'fa-triangle-exclamation'}"></i>`;
  modal.classList.add('active');
  return new Promise(resolve => {
    function settle(value) {
      if (!modal._pendingResolve) return;
      modal._pendingResolve = null;
      modal.classList.remove('active');
      resolve(value);
    }
    modal._pendingResolve = resolve;
    modal.querySelector('#app-confirm-ok').onclick = () => settle(true);
    modal.querySelector('#app-confirm-cancel').onclick = () => settle(false);
  });
};

async function fetchViewerStats() {
  try {
    const res = await fetch('/api/stats/viewers');
    const data = await res.json();
    document.getElementById('metric-viewers').textContent = data.viewers || 0;
    document.getElementById('metric-total').textContent = data.total_viewers || 0;
  } catch (e) {}
}

// ==========================================
// GIFT LOG
// ==========================================
let lastGiftCount = 0;

async function fetchGiftLog() {
  try {
    const res = await fetch('/api/stats/gifts');
    const data = await res.json();
    renderGiftLog(data);
  } catch (e) {}
}

function renderGiftLog(entries) {
  const container = document.getElementById('gift-log-container');
  if (!entries || entries.length === 0) {
    container.innerHTML = '<div class="ticker-empty">No gifts received yet...</div>';
    lastGiftCount = 0;
    document.getElementById('metric-gifts').textContent = '0';
    return;
  }

  // Guard against desync: if log was reset/cleared, resync lastGiftCount
  if (lastGiftCount > entries.length) {
    lastGiftCount = 0;
    container.innerHTML = '';
  }
  const newEntries = entries.slice(lastGiftCount);
  if (newEntries.length === 0) return;

  // Remove empty state
  const empty = container.querySelector('.ticker-empty');
  if (empty) empty.remove();

  // Prepend new gifts at top with animation
  newEntries.reverse().forEach((entry, idx) => {
    const tier = entry.tier || 1;
    const div = document.createElement('div');
    div.className = `gift-log-entry gift-tier-${tier}`;
    div.setAttribute('data-sender', entry.sender || '');
    div.setAttribute('data-gift-name', entry.gift_name || '');
    div.setAttribute('data-gift-id', entry.gift_id || '');
    div.setAttribute('data-coins', entry.total_coins || 0);
    div.setAttribute('data-index', lastGiftCount + idx);
    div.innerHTML = `
      <img src="${entry.icon || ''}" class="gift-icon" alt="${entry.gift_name}" onerror="this.style.display='none'">
      <div class="gift-info">
        <div class="gift-name">${entry.gift_name} <span class="gift-id">#${entry.gift_id}</span></div>
        <div class="gift-meta">${entry.sender} sent ${entry.repeat_count}x = <strong>${entry.total_coins}</strong> coins</div>
      </div>`;
    container.insertBefore(div, container.firstChild);
  });

  // Gift log: no DOM cap — keeps all entries

  lastGiftCount = entries.length;
  document.getElementById('metric-gifts').textContent = entries.length;
  document.getElementById('gift-count').textContent = entries.length;

  // Calculate total coins from all gift entries
  let totalCoins = 0;
  entries.forEach(e => {
    totalCoins += e.total_coins || 0;
  });
  document.getElementById('metric-coins').textContent = totalCoins.toLocaleString();
  document.getElementById('metric-usd').textContent = `≈ $${(totalCoins / 250).toFixed(2)} USD`;

  // Re-apply active search filter
  filterGiftLog();
}

async function clearGiftLog() {
  try {
    await fetch('/api/stats/gifts/clear', { method: 'POST' });
    renderGiftLog([]);
    document.getElementById('metric-gifts').textContent = '0';
    document.getElementById('gift-count').textContent = '0';
    document.getElementById('metric-coins').textContent = '0';
    document.getElementById('metric-usd').textContent = '≈ $0.00 USD';
  } catch(e) {}
}

// ── Gift Log Search/Filter ──
let _giftSortMode = 'none';  // 'none', 'high', 'low'

function toggleGiftSort() {
  const btn = document.getElementById('gift-sort-btn');
  // Cycle: none -> high -> low -> none
  if (_giftSortMode === 'none') {
    _giftSortMode = 'high';
    btn.innerHTML = '<i class="fa-solid fa-arrow-down-wide-short"></i>';
    btn.style.color = 'var(--primary)';
  } else if (_giftSortMode === 'high') {
    _giftSortMode = 'low';
    btn.innerHTML = '<i class="fa-solid fa-arrow-up-wide-short"></i>';
    btn.style.color = 'var(--primary)';
  } else {
    _giftSortMode = 'none';
    btn.innerHTML = '<i class="fa-solid fa-arrow-down-wide-short"></i>';
    btn.style.color = 'var(--text-secondary)';
  }
  sortGiftLog();
}

function sortGiftLog() {
  const container = document.getElementById('gift-log-container');
  if (!container) return;

  const entries = Array.from(container.querySelectorAll('.gift-log-entry'));
  if (entries.length === 0) return;

  if (_giftSortMode === 'none') {
    // Restore chronological order (data attribute stores original order)
    entries.sort((a, b) => {
      const ia = parseInt(a.dataset.index || '0');
      const ib = parseInt(b.dataset.index || '0');
      return ia - ib;
    });
  } else {
    // Sort by coins
    entries.sort((a, b) => {
      const coinsA = parseInt(a.dataset.coins || '0');
      const coinsB = parseInt(b.dataset.coins || '0');
      return _giftSortMode === 'high' ? coinsB - coinsA : coinsA - coinsB;
    });
  }

  // Re-append in sorted order
  entries.forEach(entry => container.appendChild(entry));
}

function filterGiftLog() {
  const input = document.getElementById('gift-search');
  const clearBtn = document.getElementById('gift-search-clear');
  const container = document.getElementById('gift-log-container');
  if (!input || !container) return;

  const query = input.value.trim().toLowerCase();

  // Show/hide clear button
  if (clearBtn) clearBtn.style.display = query ? 'flex' : 'none';

  // Remove any existing no-match message
  const existingNoMatch = container.querySelector('.ticker-no-match');
  if (existingNoMatch) existingNoMatch.remove();

  // Get all gift-log-entry elements
  const entries = container.querySelectorAll('.gift-log-entry');
  if (entries.length === 0) return;

  // If no query, show everything
  if (!query) {
    entries.forEach(entry => { entry.style.display = ''; });
    return;
  }

  // Filter entries
  let hasMatch = false;
  entries.forEach(entry => {
    const sender = (entry.getAttribute('data-sender') || '').toLowerCase();
    const giftName = (entry.getAttribute('data-gift-name') || '').toLowerCase();
    const giftId = (entry.getAttribute('data-gift-id') || '').toLowerCase();
    const match = sender.includes(query) || giftName.includes(query) || giftId.includes(query);
    entry.style.display = match ? '' : 'none';
    if (match) hasMatch = true;
  });

  // Show "no matches" state if nothing matches
  if (!hasMatch) {
    const noMatch = document.createElement('div');
    noMatch.className = 'ticker-empty ticker-no-match';
    noMatch.textContent = 'No matches found';
    container.appendChild(noMatch);
  }
}

function clearGiftSearch() {
  const input = document.getElementById('gift-search');
  const clearBtn = document.getElementById('gift-search-clear');
  if (input) input.value = '';
  if (clearBtn) clearBtn.style.display = 'none';
  filterGiftLog();
  // Focus back on the input for convenience
  if (input) input.focus();
}

// ==========================================
// FOLLOW LOG
// ==========================================
let lastFollowCount = 0;

async function fetchFollowLog() {
  try {
    const res = await fetch('/api/stats/follows');
    const data = await res.json();
    renderFollowLog(data);
  } catch (e) {}
}

function renderFollowLog(entries) {
  const container = document.getElementById('follow-log-container');
  if (!entries || entries.length === 0) {
    container.innerHTML = '<div class="ticker-empty">No new followers yet...</div>';
    lastFollowCount = 0;
    document.getElementById('metric-follows').textContent = '0';
    return;
  }

  // Guard against desync: if log was reset/cleared, resync lastFollowCount
  if (lastFollowCount > entries.length) {
    lastFollowCount = 0;
    container.innerHTML = '';
  }
  const newEntries = entries.slice(lastFollowCount);
  if (newEntries.length === 0) return;

  const empty = container.querySelector('.ticker-empty');
  if (empty) empty.remove();

  // Prepend new entries at top with animation
  newEntries.reverse().forEach(entry => {
    const div = document.createElement('div');
    div.className = 'follow-log-entry';
    div.innerHTML = `
      <div class="follow-avatar">
        ${entry.avatar_url ? `<img src="${entry.avatar_url}" alt="${entry.nick}" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">` : ''}
        <i class="fa-solid fa-user" style="${entry.avatar_url ? 'display:none' : ''}"></i>
      </div>
      <div class="follow-info">
        <div class="follow-nick">${entry.nick}</div>
        <div class="follow-id">@${entry.unique_id || 'unknown'}</div>
      </div>
      <div class="follow-badge">NEW</div>`;
    container.insertBefore(div, container.firstChild);
  });

  // Follow log: no DOM cap — keeps all entries

  lastFollowCount = entries.length;
  document.getElementById('metric-follows').textContent = entries.length;
  document.getElementById('follow-count').textContent = entries.length;
}

async function clearFollowLog() {
  try {
    await fetch('/api/stats/follows/clear', { method: 'POST' });
    renderFollowLog([]);
    document.getElementById('metric-follows').textContent = '0';
    document.getElementById('follow-count').textContent = '0';
  } catch(e) {}
}

// ==========================================
// SUPERFAN LOG
// ==========================================
let lastSuperfanCount = 0;

async function fetchSuperfanLog() {
  try {
    const res = await fetch('/api/stats/superfan');
    const data = await res.json();
    renderSuperfanLog(data);
  } catch (e) {}
}

function getSuperfanMeta(type) {
  switch (type) {
    case 'new_superfan':
      return { icon: 'fa-star', label: 'NEW SUPERFAN', cls: 'new', text: 'became a SuperFan' };
    case 'superfan_box':
    case 'superfan_box_unknown':
      return { icon: 'fa-box-open', label: 'BOX?', cls: 'box', text: 'SuperFan Box event — collecting phase data' };
    case 'superfan_box_sent':
      return { icon: 'fa-gift', label: 'BOX SENT', cls: 'box', text: 'sent a SuperFan Box' };
    case 'superfan_box_claimed':
      return { icon: 'fa-box-open', label: 'BOX CLAIM', cls: 'box', text: 'opened / claimed a SuperFan Box' };
    case 'superfan_join':
      return { icon: 'fa-right-to-bracket', label: 'JOIN', cls: 'join', text: 'joined as existing SuperFan' };
    case 'superfan_join_ignored':
      return { icon: 'fa-shield-halved', label: 'JOIN IGNORED', cls: 'join', text: 'join notice ignored for rewards' };
    case 'superfan_upgrade':
      return { icon: 'fa-arrow-up', label: 'UPGRADE', cls: 'join', text: 'upgraded SuperFan level — no new reward' };
    case 'subscribe':
      return { icon: 'fa-crown', label: 'SUB', cls: 'sub', text: 'subscribed' };
    default:
      return { icon: 'fa-star', label: String(type || 'SUPERFAN').toUpperCase(), cls: 'other', text: type || 'superfan event' };
  }
}

function getSuperfanExtraMeta(entry) {
  const bits = [];
  if (entry.unique_id) bits.push(`@${escHtml(entry.unique_id)}`);
  if (entry.diamond_count) bits.push(`${escHtml(String(entry.diamond_count))} coins`);
  if (entry.people_count) bits.push(`${escHtml(String(entry.people_count))} slots`);
  if (entry.envelope_id) bits.push(`box ${escHtml(String(entry.envelope_id)).slice(-6)}`);
  if (entry.common_display_type) bits.push(escHtml(String(entry.common_display_type)));
  return bits.length ? ` • ${bits.join(' • ')}` : '';
}

function renderSuperfanLog(entries) {
  const container = document.getElementById('superfan-log-container');
  if (!container) return;
  if (!entries || entries.length === 0) {
    container.innerHTML = '<div class="ticker-empty">No superfan events yet...</div>';
    lastSuperfanCount = 0;
    const count = document.getElementById('superfan-count');
    if (count) count.textContent = '0';
    return;
  }

  if (lastSuperfanCount > entries.length) {
    lastSuperfanCount = 0;
    container.innerHTML = '';
  }
  const newEntries = entries.slice(lastSuperfanCount);
  if (newEntries.length === 0) return;

  const empty = container.querySelector('.ticker-empty');
  if (empty) empty.remove();

  newEntries.reverse().forEach(entry => {
    const meta = getSuperfanMeta(entry.event_type);
    const div = document.createElement('div');
    div.className = `superfan-log-entry superfan-${meta.cls}`;
    const avatar = entry.avatar_url
      ? `<img src="${entry.avatar_url}" alt="${escHtml(entry.nick || 'Someone')}" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">`
      : '';
    const tags = (entry.tags || '').split(',').filter(Boolean);
    const tagsHtml = tags.map(t => `<span class="superfan-tag superfan-tag-${escHtml(t)}">${escHtml(t)}</span>`).join('');
    const badgesHtml = (entry.badges || []).slice(0, 4).map(b => {
      if (b.icon && b.level_text) return `<span class="user-badge-combined" title="${escHtml(b.type || '')}"><img src="${b.icon}" alt="${escHtml(b.type || '')}" class="user-badge-icon" onerror="this.style.display='none'"><span class="user-badge-level">${escHtml(b.level_text)}</span></span>`;
      if (b.icon) return `<img src="${b.icon}" alt="${escHtml(b.type || '')}" class="user-badge-icon" onerror="this.style.display='none'">`;
      if (b.level_text) return `<span class="user-badge-combined"><span class="user-badge-level">${escHtml(b.level_text)}</span></span>`;
      return '';
    }).join('');
    div.innerHTML = `
      <div class="superfan-avatar">
        ${avatar}
        <div class="superfan-avatar-fallback" style="${entry.avatar_url ? 'display:none' : ''}">${escHtml((entry.nick || '?').charAt(0).toUpperCase())}</div>
      </div>
      <div class="superfan-icon"><i class="fa-solid ${meta.icon}"></i></div>
      <div class="superfan-info">
        <div class="superfan-name">${escHtml(entry.nick || 'Someone')} ${badgesHtml}</div>
        <div class="superfan-meta">${meta.text}${getSuperfanExtraMeta(entry)}</div>
        <div class="superfan-tags">${tagsHtml}</div>
      </div>
      <div class="superfan-badge">${meta.label}</div>`;
    container.insertBefore(div, container.firstChild);
  });

  lastSuperfanCount = entries.length;
  const count = document.getElementById('superfan-count');
  if (count) count.textContent = entries.length;
}

async function clearSuperfanLog() {
  try {
    await fetch('/api/stats/superfan/clear', { method: 'POST' });
    renderSuperfanLog([]);
    const count = document.getElementById('superfan-count');
    if (count) count.textContent = '0';
  } catch(e) {}
}

// ==========================================
// CHAT LOG
// ==========================================
const CHAT_PAGE_SIZE = 300;
const CHAT_LIVE_DOM_CAP = CHAT_PAGE_SIZE; // keep the full backend live page for continuous history paging
let lastChatCount = 0;
let chatVisibleEntries = [];      // mirrors DOM order
let chatRenderedIndices = new Set();
let chatMaxIndex = -1;            // highest _chat_index currently in DOM
let chatTotalCount = 0;
let chatNextBefore = null;
let chatReviewMode = false;       // frozen: user scrolled back / loaded history
let chatReviewBaseTotal = 0;      // total at the moment review mode was entered
let chatPendingNew = 0;           // new live msgs that arrived during review
let chatIsLoadingOlder = false;
let chatScrollHandlerAttached = false;

async function fetchChatPage(before = null, limit = CHAT_PAGE_SIZE) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (before !== null && before !== undefined) params.set('before', String(before));
  const res = await fetch(`/api/stats/chat?${params.toString()}`);
  return await res.json();
}

async function fetchChatLog() {
  try {
    const page = await fetchChatPage(null, CHAT_PAGE_SIZE);
    renderChatLog(page, { mode: 'live' });
  } catch (e) {}
}

function getChatEntryIndex(entry, fallback) {
  const idx = parseInt(entry?._chat_index);
  return Number.isFinite(idx) ? idx : fallback;
}

function mergeChatEntries(entries) {
  const byIndex = new Map();
  chatVisibleEntries.forEach((entry, i) => byIndex.set(getChatEntryIndex(entry, i), entry));
  entries.forEach((entry, i) => byIndex.set(getChatEntryIndex(entry, i), entry));
  chatVisibleEntries = Array.from(byIndex.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([, entry]) => entry);
}


function getChatTierMeta(tierClass) {
  if (tierClass === 'tier-4') return { key: 'legend', label: 'LEGEND' };
  if (tierClass === 'tier-3') return { key: 'gold', label: 'GOLD' };
  if (tierClass === 'tier-2') return { key: 'amethyst', label: 'AMETHYST' };
  if (tierClass === 'tier-1') return { key: 'iron', label: 'IRON' };
  return null;
}

function createChatEntryElement(entry) {
  const div = document.createElement('div');

  // Determine tier class based on gifter level (effects start at 20+)
  const level = entry.gifter_level || 0;
  let tierClass = '';
  if (level >= 35) tierClass = 'tier-4';
  else if (level >= 30) tierClass = 'tier-3';
  else if (level >= 25) tierClass = 'tier-2';
  else if (level >= 20) tierClass = 'tier-1';

  div.className = `ticker-entry comment ${tierClass}`;
  div.setAttribute('data-nick', entry.nick || '');
  div.setAttribute('data-comment', entry.comment || '');
  div.setAttribute('data-unique-id', entry.unique_id || '');
  div.setAttribute('data-tags', entry.tags || '');
  div.setAttribute('data-gifter-level', entry.gifter_level || 0);
  div.setAttribute('data-member-level', entry.member_level || 0);

  const initial = (entry.nick || '?').charAt(0).toUpperCase();
  const tags = entry.tags || '';
  const tierMeta = getChatTierMeta(tierClass);
  const tierChip = tierMeta ? `<span class="chat-tier-chip chat-tier-chip-${tierMeta.key}">${tierMeta.label}</span>` : '';
  const tagBadge = tags ? `<span class="chat-tag-chip">${escHtml(tags)}</span>` : '';
  const avatarHtml = entry.avatar_url
    ? `<img src="${entry.avatar_url}" alt="${escHtml(entry.nick || '')}" onerror="this.style.display='none'">`
    : escHtml(initial);

  // Render badge icons (TikTok-style: icon + level text with colored background)
  let badgesHtml = '';
  if (entry.badges && entry.badges.length > 0) {
    badgesHtml = entry.badges.map(b => {
      const title = b.level_text ? `${b.type} Lv.${b.level_text}` : b.type;

      // Convert ARGB (#AARRGGBB) to RGBA for CSS
      function argbToRgba(argb) {
        if (!argb || argb.length < 9) return argb;
        const a = parseInt(argb.slice(1, 3), 16) / 255;
        const r = parseInt(argb.slice(3, 5), 16);
        const g = parseInt(argb.slice(5, 7), 16);
        const bl = parseInt(argb.slice(7, 9), 16);
        return `rgba(${r},${g},${bl},${a.toFixed(2)})`;
      }

      const bgStyle = b.bg_color ? `background:${argbToRgba(b.bg_color)};` : '';
      const borderStyle = b.border_color ? `border:1px solid ${argbToRgba(b.border_color)};` : '';

      if (b.icon && b.level_text) {
        // COMBINE style: icon + level number (like TikTok gifter badges)
        return `<span class="user-badge-combined" title="${escHtml(title)}" style="${bgStyle}${borderStyle}">` +
                 `<img src="${b.icon}" alt="${escHtml(b.type)}" class="user-badge-icon" onerror="this.style.display='none'">` +
                 `<span class="user-badge-level">${escHtml(b.level_text)}</span>` +
               `</span>`;
      } else if (b.icon) {
        // IMAGE style: icon only
        return `<img src="${b.icon}" alt="${escHtml(b.type)}" title="${escHtml(title)}" class="user-badge-icon" onerror="this.outerHTML='<span class=\\'user-badge-text\\'>badge</span>'">`;
      } else {
        // TEXT fallback
        return `<span class="user-badge-text" title="${escHtml(title)}">${escHtml(b.type)}${b.level_text ? ' ' + escHtml(b.level_text) : ''}</span>`;
      }
    }).join('');
  }

  // Pixel tier accents are CSS-driven for readability/performance; no random sparkle spam.
  let sparklesHtml = '';

  div.innerHTML = `
    ${sparklesHtml}
    <div class="ticker-avatar">${avatarHtml}</div>
    <div class="ticker-info">
      <div class="ticker-user">${badgesHtml}${tierChip}<span class="tier-nick">${escHtml(entry.nick || 'Unknown')}</span>${tagBadge}</div>
      <div class="ticker-action">${escHtml(entry.comment || '')}</div>
    </div>
    <span class="ticker-time" style="font-size:10px;opacity:0.5;">@${escHtml(entry.unique_id || '?')}</span>
  `;
  return div;
}

function updateChatHistoryControls() {
  const loadBtn = document.getElementById('chat-load-older');
  const fullBtn = document.getElementById('chat-show-full');
  const status = document.getElementById('chat-history-status');
  if (loadBtn) {
    loadBtn.disabled = chatIsLoadingOlder || !chatNextBefore;
    loadBtn.style.display = chatNextBefore ? 'inline-flex' : 'none';
  }
  if (fullBtn) {
    fullBtn.disabled = chatIsLoadingOlder || !chatNextBefore;
    fullBtn.style.display = chatNextBefore ? 'inline-flex' : 'none';
  }
  if (status) {
    // Only meaningful while reviewing loaded history. In live mode the count
    // badge already shows the total and we're just tailing — the "Showing N"
    // is noise (and its N never moves in a capped live window).
    status.textContent = (chatReviewMode && chatTotalCount)
      ? `Showing ${chatVisibleEntries.length.toLocaleString()} / ${chatTotalCount.toLocaleString()}`
      : '';
  }
}
// Full teardown+rebuild from chatVisibleEntries. Used for history loads and
// clears only — NEVER on the live polling path (that uses appendLiveEntries).
function fullRebuildChatLog({ preserveTop = false, stickBottom = false } = {}) {
  const container = document.getElementById('chat-log-container');
  if (!container) return;
  const oldHeight = container.scrollHeight;
  const oldTop = container.scrollTop;
  const wasNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 30;

  chatRenderedIndices = new Set();
  chatMaxIndex = -1;

  if (!chatVisibleEntries.length) {
    container.innerHTML = '<div class="ticker-empty">No chat messages yet...</div>';
  } else {
    container.innerHTML = '';
    chatVisibleEntries.forEach((entry, i) => {
      const idx = getChatEntryIndex(entry, i);
      container.appendChild(createChatEntryElement(entry));
      chatRenderedIndices.add(idx);
      if (idx > chatMaxIndex) chatMaxIndex = idx;
    });
  }

  lastChatCount = chatTotalCount;
  document.getElementById('ticker-count').textContent = chatTotalCount.toLocaleString();
  filterChatLog();

  if (preserveTop) {
    container.scrollTop = oldTop + (container.scrollHeight - oldHeight);
  } else if (stickBottom || wasNearBottom) {
    container.scrollTop = container.scrollHeight;
  }
  updateChatHistoryControls();
}

// Incremental live render: append only genuinely-new entries (idx > chatMaxIndex),
// trim oldest DOM nodes beyond CHAT_LIVE_DOM_CAP. O(new msgs), not O(window).
// Trimmed messages stay on the backend — Load older / Show full re-fetch them.
function appendLiveEntries(entries, nextBefore = null) {
  const container = document.getElementById('chat-log-container');
  if (!container) return;

  const empty = container.querySelector('.ticker-empty');
  if (empty) empty.remove();

  const wasNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 40;
  const firstRender = chatRenderedIndices.size === 0;

  let appended = 0;
  entries.forEach((entry, i) => {
    const idx = getChatEntryIndex(entry, i);
    if (chatRenderedIndices.has(idx)) return;
    if (!firstRender && idx <= chatMaxIndex) return; // only the live tail
    container.appendChild(createChatEntryElement(entry));
    chatRenderedIndices.add(idx);
    chatVisibleEntries.push(entry);
    if (idx > chatMaxIndex) chatMaxIndex = idx;
    appended++;
  });

  // Trim oldest beyond the DOM cap (history is preserved server-side).
  while (container.children.length > CHAT_LIVE_DOM_CAP) {
    const first = container.firstElementChild;
    if (!first || first.classList.contains('ticker-empty')) break;
    first.remove();
    const removed = chatVisibleEntries.shift();
    if (removed) chatRenderedIndices.delete(getChatEntryIndex(removed, -1));
  }

  lastChatCount = chatTotalCount;
  document.getElementById('ticker-count').textContent = chatTotalCount.toLocaleString();

  if (appended) filterChatLog();
  if (wasNearBottom) container.scrollTop = container.scrollHeight;

  // Load-older anchor comes from the backend page, not the DOM. The DOM may be
  // filtered/trimmed, but `next_before` is the authoritative continuous cursor.
  chatNextBefore = (nextBefore !== null && nextBefore !== undefined && nextBefore > 0) ? nextBefore : null;
  updateChatHistoryControls();
}

// ── Review-mode freeze: while scrolled back / loading history, live redraw pauses ──
function enterChatReviewMode() {
  if (chatReviewMode) return;
  chatReviewMode = true;
  chatReviewBaseTotal = chatTotalCount;
  chatPendingNew = 0;
  updateNewMsgBadge();
  updateChatHistoryControls();
}

function exitChatReviewMode() {
  chatReviewMode = false;
  chatReviewBaseTotal = 0;
  chatPendingNew = 0;
  // Drop the loaded history window and repopulate a fresh live tail.
  chatVisibleEntries = [];
  chatRenderedIndices = new Set();
  chatMaxIndex = -1;
  updateNewMsgBadge();
  updateChatHistoryControls();
  fetchChatLog();
}

function updateNewMsgBadge() {
  const badge = document.getElementById('chat-new-msg-badge');
  if (!badge) return;
  if (chatReviewMode && chatPendingNew > 0) {
    badge.textContent = `↓ ${chatPendingNew.toLocaleString()} new`;
    badge.style.display = 'inline-flex';
  } else {
    badge.style.display = 'none';
  }
}

function jumpToLiveChat() {
  exitChatReviewMode();
  const container = document.getElementById('chat-log-container');
  if (container) container.scrollTop = container.scrollHeight;
}

function attachChatScrollHandler() {
  if (chatScrollHandlerAttached) return;
  const container = document.getElementById('chat-log-container');
  if (!container) return;
  container.addEventListener('scroll', () => {
    const nearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 40;
    if (nearBottom && chatReviewMode && !chatIsLoadingOlder) {
      exitChatReviewMode();         // scrolled back to bottom → resume live
    } else if (!nearBottom && !chatReviewMode) {
      enterChatReviewMode();        // scrolled up → freeze
    }
  }, { passive: true });
  chatScrollHandlerAttached = true;
}

function renderChatLog(page, opts = {}) {
  const entries = Array.isArray(page) ? page : (page.entries || []);
  const total = Array.isArray(page) ? entries.length : (page.total || 0);
  const nextBefore = Array.isArray(page) ? null : page.next_before;
  const mode = opts.mode || 'live';

  // Empty / cleared backend.
  if (!entries.length && total === 0) {
    chatVisibleEntries = [];
    chatRenderedIndices = new Set();
    chatMaxIndex = -1;
    chatTotalCount = 0;
    chatNextBefore = null;
    fullRebuildChatLog();
    return;
  }

  chatTotalCount = total;

  if (mode === 'older') {
    // History load → merge into the visible set and do a full rebuild (rare, user-initiated).
    mergeChatEntries(entries);
    chatNextBefore = chatVisibleEntries.length ? getChatEntryIndex(chatVisibleEntries[0], 0) : nextBefore;
    if (nextBefore === null || chatNextBefore <= 0) chatNextBefore = null;
    fullRebuildChatLog({ preserveTop: true });
    return;
  }

  // mode === 'live'
  if (chatReviewMode) {
    // Frozen: don't touch the DOM, just surface a "N new" badge.
    chatPendingNew = Math.max(0, total - chatReviewBaseTotal);
    document.getElementById('ticker-count').textContent = chatTotalCount.toLocaleString();
    updateNewMsgBadge();
    return;
  }
  appendLiveEntries(entries, nextBefore);
}

async function loadOlderChat() {
  if (chatIsLoadingOlder || !chatNextBefore) return;
  enterChatReviewMode();
  chatIsLoadingOlder = true;
  updateChatHistoryControls();
  try {
    const page = await fetchChatPage(chatNextBefore, CHAT_PAGE_SIZE);
    renderChatLog(page, { mode: 'older' });
  } catch (e) {
    showToast('Failed to load older chat', 'error');
  } finally {
    chatIsLoadingOlder = false;
    updateChatHistoryControls();
  }
}

async function showFullChatHistory() {
  if (chatIsLoadingOlder) return;
  if (chatTotalCount > 1500 && !(await window.appConfirm({
    title: 'Load Full Chat History',
    message: `Load all ${chatTotalCount.toLocaleString()} chat messages? This can be slower after long streams.`,
    confirmText: 'Load All'
  }))) return;
  enterChatReviewMode();
  chatIsLoadingOlder = true;
  updateChatHistoryControls();
  try {
    while (chatNextBefore) {
      const page = await fetchChatPage(chatNextBefore, CHAT_PAGE_SIZE);
      renderChatLog(page, { mode: 'older' });
      if (!page.next_before) break;
    }
  } catch (e) {
    showToast('Failed to load full chat history', 'error');
  } finally {
    chatIsLoadingOlder = false;
    updateChatHistoryControls();
  }
}

async function clearChatLog() {
  try {
    await fetch('/api/stats/chat/clear', { method: 'POST' });
    const container = document.getElementById('chat-log-container');
    container.innerHTML = '<div class="ticker-empty">No chat messages yet...</div>';
    lastChatCount = 0;
    chatVisibleEntries = [];
    chatRenderedIndices = new Set();
    chatMaxIndex = -1;
    chatTotalCount = 0;
    chatNextBefore = null;
    chatReviewMode = false;
    chatReviewBaseTotal = 0;
    chatPendingNew = 0;
    document.getElementById('ticker-count').textContent = '0';
    updateNewMsgBadge();
    updateChatHistoryControls();
    showToast('Chat cleared', 'info');
  } catch(e) {}
}

// ── Chat Log Search/Filter ──
function filterChatLog() {
  const input = document.getElementById('chat-search');
  const clearBtn = document.getElementById('chat-search-clear');
  const container = document.getElementById('chat-log-container');
  if (!input || !container) return;

  const query = input.value.trim().toLowerCase();

  // Show/hide clear button
  if (clearBtn) clearBtn.style.display = query ? 'flex' : 'none';

  // Remove any existing no-match message
  const existingNoMatch = container.querySelector('.ticker-no-match');
  if (existingNoMatch) existingNoMatch.remove();

  // Get all ticker-entry.comment elements
  const entries = container.querySelectorAll('.ticker-entry.comment');
  if (entries.length === 0) return;

  // Get active category filters from pills
  const activeCats = getActiveChatCategories();

  // Get min level filters from inputs
  const minGifterInput = document.getElementById('chat-min-gifter-level');
  const minMemberInput = document.getElementById('chat-min-member-level');
  const minGifter = minGifterInput ? (parseInt(minGifterInput.value) || 0) : 0;
  const minMember = minMemberInput ? (parseInt(minMemberInput.value) || 0) : 0;

  // If no query and no filters, show everything
  if (!query && activeCats.length === 0 && minGifter === 0 && minMember === 0) {
    entries.forEach(entry => { entry.style.display = ''; });
    return;
  }

  // Filter entries
  let hasMatch = false;
  entries.forEach(entry => {
    const nick = (entry.getAttribute('data-nick') || '').toLowerCase();
    const comment = (entry.getAttribute('data-comment') || '').toLowerCase();
    const uniqueId = (entry.getAttribute('data-unique-id') || '').toLowerCase();
    const entryTags = (entry.getAttribute('data-tags') || '').split(',').filter(Boolean);

    // Text search match
    let textMatch = true;
    if (query) {
      textMatch = nick.includes(query) || comment.includes(query) || uniqueId.includes(query);
    }

    // Category match
    let catMatch = true;
    if (activeCats.length > 0) {
      catMatch = entryTags.some(t => activeCats.includes(t));
    }

    // Level match
    const entryGifterLevel = parseInt(entry.getAttribute('data-gifter-level') || '0');
    const entryMemberLevel = parseInt(entry.getAttribute('data-member-level') || '0');
    const gifterMatch = minGifter === 0 || entryGifterLevel >= minGifter;
    const memberMatch = minMember === 0 || entryMemberLevel >= minMember;

    const match = textMatch && catMatch && gifterMatch && memberMatch;
    entry.style.display = match ? '' : 'none';
    if (match) hasMatch = true;
  });

  // Show "no matches" state if nothing matches
  if (!hasMatch) {
    const noMatch = document.createElement('div');
    noMatch.className = 'ticker-empty ticker-no-match';
    noMatch.textContent = 'No matches found';
    container.appendChild(noMatch);
  }
}

// ── Chat Category Filter ──
const ALL_CHAT_CATEGORIES = ['vip', 'superfan', 'member', 'friend', 'follower', 'newbie'];
let activeChatCategories = [];

function getActiveChatCategories() {
  return activeChatCategories;
}

function toggleChatCategory(cat) {
  const idx = activeChatCategories.indexOf(cat);
  if (idx >= 0) {
    activeChatCategories.splice(idx, 1);
  } else {
    activeChatCategories.push(cat);
  }
  // Update pill active state
  document.querySelectorAll('.chat-cat-pill').forEach(pill => {
    pill.classList.toggle('active', activeChatCategories.includes(pill.dataset.cat));
  });
  filterChatLog();
}

function clearChatCategories() {
  activeChatCategories = [];
  document.querySelectorAll('.chat-cat-pill').forEach(pill => {
    pill.classList.remove('active');
  });
  filterChatLog();
}

function clearChatSearch() {
  const input = document.getElementById('chat-search');
  const clearBtn = document.getElementById('chat-search-clear');
  if (input) input.value = '';
  if (clearBtn) clearBtn.style.display = 'none';
  filterChatLog();
  // Focus back on the input for convenience
  if (input) input.focus();
}

// ==========================================
// ACTIVE STREAKS
// ==========================================
let _streaksDismissed = false;
let _lastStreakKeys = '';

async function fetchActiveStreaks() {
  try {
    const res = await fetch('/api/stats/active-streaks');
    const data = await res.json();
    renderActiveStreaks(data);
  } catch (e) {}
}

function renderActiveStreaks(streaks) {
  const section = document.getElementById('active-streaks-section');
  const container = document.getElementById('active-streaks-container');
  if (!section || !container) return;

  const keys = Object.keys(streaks);
  if (keys.length === 0) {
    section.style.display = 'none';
    _streaksDismissed = false;
    _lastStreakKeys = '';
    return;
  }

  // Check if streaks changed (new streak appeared)
  const currentKeys = keys.sort().join(',');
  if (currentKeys !== _lastStreakKeys) {
    _streaksDismissed = false;  // New streaks = reset dismissal
    _lastStreakKeys = currentKeys;
  }

  // Don't show if user dismissed
  if (_streaksDismissed) {
    section.style.display = 'none';
    return;
  }

  section.style.display = '';
  // Add close button to header if not already there
  const header = section.querySelector('.streaks-header');
  if (header && !header.querySelector('.streaks-close')) {
    const closeBtn = document.createElement('button');
    closeBtn.className = 'streaks-close';
    closeBtn.innerHTML = '&times;';
    closeBtn.onclick = () => {
      _streaksDismissed = true;
      section.style.display = 'none';
    };
    header.appendChild(closeBtn);
  }
  // Show max 3 most recent streaks
  const visible = keys.slice(-3).reverse();
  container.innerHTML = '';

  visible.forEach(key => {
    const s = streaks[key];
    const div = document.createElement('div');
    div.className = 'streak-card';
    div.innerHTML = `
      <div class="streak-avatar">
        ${s.avatar_url ? `<img src="${s.avatar_url}" alt="${s.user}" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';"><i class="fa-solid fa-user" style="display:none;"></i>` : `<i class="fa-solid fa-user"></i>`}
      </div>
      <div class="streak-info">
        <div class="streak-user">${s.user}</div>
        <div class="streak-gift">
          ${s.gift_icon ? `<img src="${s.gift_icon}" class="streak-gift-icon" alt="${s.gift_name}" onerror="this.style.display='none'">` : ''}
          <span>${s.gift_name}</span>
        </div>
      </div>
      <div class="streak-count">x${s.count}</div>
    `;
    container.appendChild(div);
  });
}

// ==========================================
// LOG POLLING
// ==========================================
let lastLogCount = 0;
async function fetchLogs() {
  try {
    const res = await fetch('/api/bot/logs');
    const data = await res.json();
    const terminal = document.getElementById('terminal-window');
    if (data.logs.length === 0) {
      if (lastLogCount !== 0) {
        terminal.textContent = "Waiting for bot to start...";
        lastLogCount = 0;
      }
    } else {
      // Only update if logs actually changed
      if (data.logs.length !== lastLogCount) {
        // Check if user was already near bottom before update
        const wasNearBottom = terminal.scrollHeight - terminal.scrollTop - terminal.clientHeight < 30;
        terminal.textContent = data.logs.join('\n');
        if (wasNearBottom) {
          terminal.scrollTop = terminal.scrollHeight;
        }
        lastLogCount = data.logs.length;
      }
    }
  } catch (e) {}
}

async function clearConsole() {
  try {
    const res = await fetch('/api/bot/logs/clear', { method: 'POST' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    document.getElementById('terminal-window').textContent = 'Console cleared.';
    lastLogCount = 0;
  } catch (e) {
    showToast('Failed to clear console', 'error');
  }
}

// ==========================================
// SIMULATED MINECRAFT CONSOLE
// ==========================================
let lastSimConsoleCount = 0;
let lastSimConsoleRevision = '';
async function fetchSimConsole() {
  try {
    const res = await fetch('/api/console/logs');
    const data = await res.json();
    const body = document.getElementById('sim-console-body');
    if (!body) return;
    if (!data.logs || data.logs.length === 0) {
      // Don't overwrite the placeholder if empty
      if (lastSimConsoleCount !== 0) {
        body.innerHTML = '<span style="opacity:0.5;">No commands sent yet. Connect a connector (RCON or Forge Mod) and trigger an event, or type a command above and hit Enter.</span>';
        lastSimConsoleCount = 0;
      }
      return;
    }
    // Change-detection + scroll-aware (same fix as fetchLogs)
    if (data.revision !== lastSimConsoleRevision) {
      const wasNearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 30;
      body.textContent = data.logs.join('\n');
      if (wasNearBottom) body.scrollTop = body.scrollHeight;
      lastSimConsoleCount = data.logs.length;
      lastSimConsoleRevision = data.revision || '';
    }
  } catch (e) {}
}

async function sendSimConsoleCommand() {
  const input = document.getElementById('sim-console-input');
  if (!input) return;
  const cmd = (input.value || '').trim();
  if (!cmd) return;
  try {
    const r = await fetch('/api/console/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: cmd })
    });
    if (r.ok) {
      input.value = '';
      // Trigger immediate refresh
      setTimeout(fetchSimConsole, 100);
    } else {
      const err = await r.json().catch(() => ({}));
      alert('Failed to send: ' + (err.error || r.status) + (err.type ? ' (' + err.type + ')' : ''));
    }
  } catch (e) {
    let msg = 'Failed to send: ' + e;
    try {
      const err = await r.json();
      if (err && err.error) msg = 'Failed: ' + err.error + (err.type ? ' (' + err.type + ')' : '');
    } catch (_) {}
    alert(msg);
  }
}

async function clearSimConsole() {
  try {
    await fetch('/api/console/clear', { method: 'POST' });
    const body = document.getElementById('sim-console-body');
    if (body) body.innerHTML = '<span style="opacity:0.5;">Cleared.</span>';
    lastSimConsoleCount = 0;
    lastSimConsoleRevision = '';
  } catch (e) {}
}

// ==========================================
// SETTINGS
// ==========================================
function populateSettings() {
  if(!currentConfig.Settings) currentConfig.Settings = {};
  if(!currentConfig.Rcon) currentConfig.Rcon = {};
  if(!currentConfig.Forge) currentConfig.Forge = {};
  if(!currentConfig.ServerTap) currentConfig.ServerTap = {};
  document.getElementById('tiktok-username').value = currentConfig.Settings.TikTokUsername || "";
  document.getElementById('mc-username').value = currentConfig.Settings.MinecraftUsername || "";
  document.getElementById('euler-api-key').value = currentConfig.Settings.EulerApiKey || "";
  // Gift asset downloader toggle (live-read by bot — takes effect mid-stream, no restart)
  const gadChk = document.getElementById('gift-asset-downloader');
  const gadLbl = document.getElementById('gift-asset-downloader-label');
  if (gadChk) {
    gadChk.checked = !!currentConfig.Settings.GiftAssetDownloader;
    if (gadLbl) gadLbl.textContent = gadChk.checked ? 'Enabled' : 'Disabled';
    if (!gadChk._wired) {
      gadChk.addEventListener('change', () => {
        if (gadLbl) gadLbl.textContent = gadChk.checked ? 'Enabled' : 'Disabled';
      });
      gadChk._wired = true;
    }
  }
  // Debug Mode toggle (live-read by bot — takes effect mid-stream, no restart)
  const dbgChk = document.getElementById('debug-mode');
  const dbgLbl = document.getElementById('debug-mode-label');
  if (dbgChk) {
    dbgChk.checked = !!currentConfig.Settings.DebugMode;
    if (dbgLbl) dbgLbl.textContent = dbgChk.checked ? 'Enabled' : 'Disabled';
    if (!dbgChk._wired) {
      dbgChk.addEventListener('change', () => {
        if (dbgLbl) dbgLbl.textContent = dbgChk.checked ? 'Enabled' : 'Disabled';
      });
      dbgChk._wired = true;
    }
  }
  
  // Log-Only Mode toggle (live-read by bot — takes effect mid-stream, no restart)
  const logonlyChk = document.getElementById('log-only-mode');
  const logonlyLbl = document.getElementById('log-only-mode-label');
  if (logonlyChk) {
    logonlyChk.checked = !!currentConfig.Settings.LogOnlyMode;
    if (logonlyLbl) logonlyLbl.textContent = logonlyChk.checked ? 'Enabled' : 'Disabled';
    if (!logonlyChk._wired) {
      logonlyChk.addEventListener('change', () => {
        if (logonlyLbl) logonlyLbl.textContent = logonlyChk.checked ? 'Enabled' : 'Disabled';
      });
      logonlyChk._wired = true;
    }
  }
  // ConnectorType radio
  const ctype = currentConfig.Settings.ConnectorType || "rcon";
  const rconRadio = document.getElementById('connector-type-rcon');
  const forgeRadio = document.getElementById('connector-type-forge');
  if (rconRadio) rconRadio.checked = (ctype === "rcon");
  if (forgeRadio) forgeRadio.checked = (ctype === "forge");
  // RCON fields
  document.getElementById('rcon-host').value = currentConfig.Rcon.Host || "";
  document.getElementById('rcon-port').value = currentConfig.Rcon.Port || 25575;
  document.getElementById('rcon-password').value = currentConfig.Rcon.Password || "";
  // Forge fields
  document.getElementById('forge-host').value = currentConfig.Forge.Host || "127.0.0.1";
  document.getElementById('forge-port').value = currentConfig.Forge.Port || 5942;
  document.getElementById('forge-password').value = currentConfig.Forge.Password || "";
  // ServerTap fields
  document.getElementById('servertap-host').value = currentConfig.ServerTap.Host || "127.0.0.1";
  document.getElementById('servertap-port').value = currentConfig.ServerTap.Port || 4567;
  document.getElementById('servertap-apikey').value = currentConfig.ServerTap.ApiKey || "";
  // Wire up radio change listeners (idempotent — uses flag)
  if (!window._connectorRadiosWired) {
    document.querySelectorAll('input[name="connector-type"]').forEach(r => {
      r.addEventListener('change', toggleConnectorFields);
    });
    window._connectorRadiosWired = true;
  }
  toggleConnectorFields();
}

function toggleConnectorFields() {
  const isForge = document.getElementById('connector-type-forge') && document.getElementById('connector-type-forge').checked;
  const isServerTap = document.getElementById('connector-type-servertap') && document.getElementById('connector-type-servertap').checked;
  const rconCard = document.getElementById('rcon-settings-card');
  const forgeCard = document.getElementById('forge-settings-card');
  const servertapCard = document.getElementById('servertap-settings-card');
  if (rconCard) rconCard.style.display = (isForge || isServerTap) ? 'none' : '';
  if (forgeCard) forgeCard.style.display = isForge ? '' : 'none';
  if (servertapCard) servertapCard.style.display = isServerTap ? '' : 'none';
}

async function testConnection() {
  const buttons = Array.from(document.querySelectorAll('.connector-test-btn'));
  const clickedBtn = document.activeElement && document.activeElement.classList && document.activeElement.classList.contains('connector-test-btn')
    ? document.activeElement
    : buttons.find(b => b.offsetParent !== null) || buttons[0];
  if (!clickedBtn) return;

  const forgeRadio = document.getElementById('connector-type-forge');
  const servertapRadio = document.getElementById('connector-type-servertap');
  const connectorType = (servertapRadio && servertapRadio.checked) ? 'servertap'
    : (forgeRadio && forgeRadio.checked) ? 'forge'
    : 'rcon';
  const payload = {
    connector_type: connectorType,
    rcon: {
      Host: document.getElementById('rcon-host')?.value || '127.0.0.1',
      Port: parseInt(document.getElementById('rcon-port')?.value || '25575', 10),
      Password: document.getElementById('rcon-password')?.value || ''
    },
    forge: {
      Host: document.getElementById('forge-host')?.value || '127.0.0.1',
      Port: parseInt(document.getElementById('forge-port')?.value || '5942', 10),
      Password: document.getElementById('forge-password')?.value || ''
    },
    servertap: {
      Host: document.getElementById('servertap-host')?.value || '127.0.0.1',
      Port: parseInt(document.getElementById('servertap-port')?.value || '4567', 10),
      ApiKey: document.getElementById('servertap-apikey')?.value || ''
    }
  };

  const origText = clickedBtn.innerHTML;
  buttons.forEach(b => { b.disabled = true; });
  clickedBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Testing...';
  try {
    const resp = await fetch('/api/test-connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await resp.json();
    if (data.status === 'success') {
      showToast(data.message, 'success');
    } else {
      showToast(data.message || 'Connection failed', 'error');
    }
  } catch (e) {
    showToast('Connection test failed: ' + e.message, 'error');
  } finally {
    clickedBtn.innerHTML = origText;
    buttons.forEach(b => { b.disabled = false; });
  }
}

function saveSettings() {
  currentConfig.Settings.TikTokUsername = document.getElementById('tiktok-username').value;
  currentConfig.Settings.MinecraftUsername = document.getElementById('mc-username').value;
  currentConfig.Settings.EulerApiKey = document.getElementById('euler-api-key').value;
  // Gift asset downloader
  const gadChk = document.getElementById('gift-asset-downloader');
  currentConfig.Settings.GiftAssetDownloader = !!(gadChk && gadChk.checked);
  // Debug Mode
  const dbgChk = document.getElementById('debug-mode');
  currentConfig.Settings.DebugMode = !!(dbgChk && dbgChk.checked);
  
  // Log-Only Mode (Test Connection)
  const logonlyChk = document.getElementById('log-only-mode');
  currentConfig.Settings.LogOnlyMode = !!(logonlyChk && logonlyChk.checked);
  
  // ConnectorType
  const forgeRadio = document.getElementById('connector-type-forge');
  const servertapRadio = document.getElementById('connector-type-servertap');
  if (servertapRadio && servertapRadio.checked) {
    currentConfig.Settings.ConnectorType = "servertap";
  } else if (forgeRadio && forgeRadio.checked) {
    currentConfig.Settings.ConnectorType = "forge";
  } else {
    currentConfig.Settings.ConnectorType = "rcon";
  }
  // RCON
  currentConfig.Rcon.Host = document.getElementById('rcon-host').value;
  currentConfig.Rcon.Port = parseInt(document.getElementById('rcon-port').value);
  currentConfig.Rcon.Password = document.getElementById('rcon-password').value;
  // Forge
  currentConfig.Forge.Host = document.getElementById('forge-host').value;
  currentConfig.Forge.Port = parseInt(document.getElementById('forge-port').value);
  currentConfig.Forge.Password = document.getElementById('forge-password').value;
  // ServerTap
  currentConfig.ServerTap = {
    Host: document.getElementById('servertap-host').value,
    Port: parseInt(document.getElementById('servertap-port').value),
    ApiKey: document.getElementById('servertap-apikey').value
  };
  // Update topbar display
  document.getElementById('tiktok-handle-display').textContent = currentConfig.Settings.TikTokUsername || '@loading...';
  saveConfigData();
}

// =========================================
// EVENTS (Redesigned)
// =========================================

function renderEventsGrid() {
  const container = document.getElementById('events-container');
  if (!container) return;
  container.innerHTML = '';

  if (!currentConfig.Events) currentConfig.Events = {};
  const events = currentConfig.Events;

  // Also populate global gift actions in the gifts panel
  populateGlobalGiftActions();

  // Priority order
  const priorityOrder = { high: 0, medium: 1, low: 2 };

  // Build list of event keys with registry info
  const eventEntries = [];
  Object.keys(events).forEach(eventKey => {
    const value = events[eventKey];
    // Get action list
    let actions = [];
    let mode = null, interval = null;
    if (Array.isArray(value)) {
      actions = value;
    } else if (typeof value === 'object' && value !== null) {
      actions = value.actions || [];
      mode = value.mode || null;
      interval = value.interval || null;
    }

    // Look up registry info
    const registry = eventRegistryData ? eventRegistryData.registry : {};
    const reg = registry[eventKey] || {};

    // Compute display name: Like events get special names
    let displayName = reg.name || eventKey;
    if (eventKey === 'Like' || eventKey.startsWith('Like_')) {
      if (mode === 'every_n') {
        displayName = `Like (every ${interval || '?'} likes)`;
      } else if (mode === 'every_like') {
        displayName = 'Like (every like)';
      }
    }

    eventEntries.push({
      key: eventKey,
      name: displayName,
      description: reg.description || '',
      category: reg.category || 'system',
      priority: reg.priority || 'low',
      template_vars: reg.template_vars || [],
      actions: actions,
      mode: mode,
      interval: interval,
      actionCount: actions.length,
    });
  });

  // Sort by priority (high first)
  eventEntries.sort((a, b) => (priorityOrder[a.priority] || 2) - (priorityOrder[b.priority] || 2));

  if (eventEntries.length === 0) {
    container.innerHTML = '<div class="events-grid-empty"><i class="fa-solid fa-bolt"></i>No events configured yet. Click "Add Event" to get started.</div>';
    return;
  }

  // Get category meta for icon/color
  const categories = eventRegistryData ? eventRegistryData.categories : {};

  eventEntries.forEach(evt => {
    const catMeta = categories[evt.category] || {};
    const catIcon = catMeta.icon || '⚙️';
    const catColor = catMeta.color || '#545b70';
    const catLabel = catMeta.label || evt.category;

    const card = document.createElement('div');
    card.className = 'event-card';
    card.dataset.eventKey = evt.key;

    let modeLabel = '';
    if (evt.mode === 'every_n') {
      modeLabel = `<span class="event-card-badge" style="background:#a855f7;">every ${evt.interval || '?'} likes</span>`;
    } else if (evt.mode === 'every_like') {
      modeLabel = `<span class="event-card-badge" style="background:#a855f7;">every like</span>`;
    }

    card.innerHTML = `
      <div class="event-card-top">
        <div class="event-card-icon" style="background:${catColor}22;color:${catColor};">${catIcon}</div>
        <div class="event-card-info">
          <div class="event-card-name">${escHtml(evt.name)}</div>
          <div class="event-card-desc">${escHtml(evt.description)}</div>
        </div>
      </div>
      <div class="event-card-badges">
        <span class="event-card-badge badge-priority-${evt.priority}">${evt.priority}</span>
        <span class="event-card-badge badge-category">${catLabel}</span>
        ${modeLabel}
      </div>
      <div class="event-card-footer">
        <span class="event-card-actions-count">${evt.actionCount} action${evt.actionCount !== 1 ? 's' : ''}</span>
        <div class="event-card-buttons">
          <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation(); openEditEventModal('${evt.key}')"><i class="fa-solid fa-pen"></i> Edit</button>
          <button class="btn btn-danger btn-sm" onclick="event.stopPropagation(); deleteEvent('${evt.key}')"><i class="fa-solid fa-trash"></i></button>
        </div>
      </div>`;

    card.addEventListener('click', () => openEditEventModal(evt.key));
    container.appendChild(card);
  });
}

function populateGlobalGiftActions() {
  // Populate the Global Gift Actions section in the Gifts panel
  const container = document.getElementById('global-actions-gift');
  if (!container) return;
  container.innerHTML = '';
  const globalActions = (currentConfig.Gifts || {}).GlobalActions || [];
  const defaultGiftCmds = [
    {type:'minecraft', command:"chatgift {gift_name} {repeat_count} {user} {total_coin} {mc}"},
    {type:'minecraft', command:"scoreboard players add Coins stats {total_coin}"}
  ];
  const actions = normalizeActions(globalActions.length > 0 ? globalActions : defaultGiftCmds);
  actions.forEach(a => appendActionRowToContainer(container, a.type, a));
}

// ── Add Event Modal ──

let addEventSelectedKey = null;
let addEventTabFilter = 'all';

function openAddEventModal() {
  addEventSelectedKey = null;
  const modal = document.getElementById('add-event-modal');
  modal.classList.add('active');
  document.getElementById('add-event-action-picker').style.display = 'none';
  document.getElementById('btn-save-add-event').disabled = true;
  document.getElementById('add-event-search').value = '';
  renderAddEventTabs();
  renderAddEventList();
}

function closeAddEventModal() {
  document.getElementById('add-event-modal').classList.remove('active');
}

function renderAddEventTabs() {
  const tabsContainer = document.getElementById('add-event-tabs');
  if (!tabsContainer || !eventRegistryData) return;
  tabsContainer.innerHTML = '';

  const categories = eventRegistryData.categories || {};
  const catOrder = ['all', 'social', 'chat', 'gifts', 'room', 'battle', 'subscription', 'interactive', 'moderation', 'display', 'system'];

  catOrder.forEach(catKey => {
    const tab = document.createElement('span');
    tab.className = `event-modal-tab ${addEventTabFilter === catKey ? 'active' : ''}`;
    if (catKey === 'all') {
      tab.textContent = 'All';
    } else {
      const meta = categories[catKey] || {};
      tab.innerHTML = `${meta.icon || ''} ${meta.label || catKey}`;
    }
    tab.onclick = () => {
      addEventTabFilter = catKey;
      renderAddEventTabs();
      renderAddEventList();
    };
    tabsContainer.appendChild(tab);
  });
}

function renderAddEventList() {
  const listContainer = document.getElementById('add-event-list');
  if (!listContainer || !eventRegistryData) return;
  listContainer.innerHTML = '';

  const registry = eventRegistryData.registry || {};
  const categories = eventRegistryData.categories || {};
  const query = (document.getElementById('add-event-search')?.value || '').toLowerCase().trim();
  const existingEvents = Object.keys(currentConfig.Events || {});
  const priorityColors = { high: '#3ba55c', medium: '#f0b232', low: '#545b70' };

  Object.entries(registry).forEach(([key, evt]) => {
    if (evt.infra) return;
    // Filter by tab
    if (addEventTabFilter !== 'all' && evt.category !== addEventTabFilter) return;
    // Filter by search
    if (query) {
      const searchable = `${key} ${evt.name} ${evt.description} ${evt.category}`.toLowerCase();
      if (!searchable.includes(query)) return;
    }

    const isExisting = existingEvents.includes(key);
    // Allow adding Like multiple times (for different intervals)
    const allowMultiple = (key === 'LikeEvent');
    const catMeta = categories[evt.category] || {};
    const catColor = catMeta.color || '#545b70';

    const item = document.createElement('div');
    item.className = `add-event-item ${isExisting ? '' : ''}`;
    item.innerHTML = `
      <div class="ae-icon" style="background:${catColor}22;color:${catColor};">${catMeta.icon || '⚙️'}</div>
      <div class="ae-info">
        <div class="ae-name">${escHtml(evt.name)} <span class="ae-priority" style="background:${priorityColors[evt.priority] || priorityColors.low};">${evt.priority}</span></div>
        <div class="ae-desc">${escHtml(evt.description)}</div>
      </div>
      ${isExisting ? '<span style="font-size:10px;color:var(--success);font-weight:600;">ADDED</span>' : ''}`;

    if (!isExisting || allowMultiple) {
      item.onclick = () => selectAddEvent(key, evt);
    } else {
      item.style.opacity = '0.5';
      item.style.cursor = 'default';
    }
    listContainer.appendChild(item);
  });

  if (listContainer.children.length === 0) {
    listContainer.innerHTML = '<p style="opacity:0.5;padding:16px;text-align:center;">No events found</p>';
  }
}

function selectAddEvent(eventKey, evt) {
  addEventSelectedKey = eventKey;
  const picker = document.getElementById('add-event-action-picker');
  picker.style.display = 'block';

  document.getElementById('add-event-selected-name').textContent = evt.name;
  document.getElementById('add-event-selected-desc').textContent = evt.description;
  document.getElementById('add-event-selected-vars').innerHTML = `Variables: ${varChips(evt.template_vars)}`;

  // Show Like-specific config
  const likeConfig = document.getElementById('add-event-like-config');
  if (eventKey === 'LikeEvent' || eventKey === 'Like' || eventKey.startsWith('Like_')) {
    likeConfig.style.display = 'block';
    const modeSelect = document.getElementById('add-event-like-mode');
    modeSelect.value = 'every_like';
    document.getElementById('add-event-interval-group').style.display = 'none';
    modeSelect.onchange = () => {
      document.getElementById('add-event-interval-group').style.display = modeSelect.value === 'every_n' ? 'block' : 'none';
    };
  } else {
    likeConfig.style.display = 'none';
  }

  // Initialize with one empty action row
  const actionsContainer = document.getElementById('add-event-modal-actions');
  actionsContainer.innerHTML = '';
  appendActionRowToContainer(actionsContainer, 'minecraft');

  document.getElementById('btn-save-add-event').disabled = false;

  // Highlight selected
  document.querySelectorAll('.add-event-item').forEach(el => el.classList.remove('ae-selected'));
  event.target.closest('.add-event-item')?.classList.add('ae-selected');
}

function addAddEventAction(type) {
  const container = document.getElementById('add-event-modal-actions');
  if (container) appendActionRowToContainer(container, type);
}

function saveNewEvent() {
  if (!addEventSelectedKey) return;
  const actions = collectActionsFromContainer(document.getElementById('add-event-modal-actions'));
  if (actions.length === 0) return showToast('Add at least one action!', 'error');

  if (addEventSelectedKey === 'LikeEvent' || addEventSelectedKey === 'Like' || addEventSelectedKey.startsWith('Like_')) {
    const mode = document.getElementById('add-event-like-mode').value;
    const interval = parseInt(document.getElementById('add-event-like-interval').value) || 1000;
    if (mode === 'every_n') {
      const likeKey = `Like_${interval}`;
      if (currentConfig.Events[likeKey]) {
        return showToast(`Event "${likeKey}" already exists! Delete it first or use a different interval.`, 'error');
      }
      currentConfig.Events[likeKey] = { mode, interval, actions };
    } else {
      if (currentConfig.Events['Like']) {
        return showToast('A "Like (every like)" event already exists! Delete it first.', 'error');
      }
      currentConfig.Events.Like = { mode, actions };
    }
  } else {
    currentConfig.Events[addEventSelectedKey] = actions;
  }

  closeAddEventModal();
  renderEventsGrid();
  const addedName = addEventSelectedKey === 'LikeEvent' ? 'Like' : addEventSelectedKey;
  showToast(`Event "${addedName}" added!`, 'success');
}

// ── Edit Event Modal ──

let editingEventKey = null;

function openEditEventModal(eventKey) {
  editingEventKey = eventKey;
  const modal = document.getElementById('edit-event-modal');
  modal.classList.add('active');

  const registry = eventRegistryData ? eventRegistryData.registry : {};
  const reg = registry[eventKey] || {};
  const categories = eventRegistryData ? eventRegistryData.categories : {};
  const catMeta = categories[reg.category || 'system'] || {};

  document.getElementById('edit-event-modal-title').textContent = `Edit: ${reg.name || eventKey}`;
  // Compute display name for Like events
  let editDisplayName = reg.name || eventKey;
  if (eventKey === 'Like' || eventKey.startsWith('Like_')) {
    const val = (currentConfig.Events || {})[eventKey];
    const m = (typeof val === 'object' && val !== null) ? val.mode : null;
    const intv = (typeof val === 'object' && val !== null) ? val.interval : null;
    if (m === 'every_n') editDisplayName = `Like (every ${intv || '?'} likes)`;
    else if (m === 'every_like') editDisplayName = 'Like (every like)';
  }
  document.getElementById('edit-event-name').textContent = editDisplayName;
  document.getElementById('edit-event-desc').textContent = reg.description || '';
  document.getElementById('edit-event-vars').innerHTML = `Variables: ${varChips(reg.template_vars || [])}`;

  const value = (currentConfig.Events || {})[eventKey];
  let actions = [];
  let mode = null, interval = null;

  if (Array.isArray(value)) {
    actions = value;
  } else if (typeof value === 'object' && value !== null) {
    actions = value.actions || [];
    mode = value.mode || null;
    interval = value.interval || null;
  }

  // Like config
  const likeConfig = document.getElementById('edit-event-like-config');
  if (eventKey === 'Like' || eventKey.startsWith('Like_')) {
    likeConfig.style.display = 'block';
    const modeSelect = document.getElementById('edit-event-like-mode');
    modeSelect.value = mode || 'every_like';
    document.getElementById('edit-event-interval-group').style.display = modeSelect.value === 'every_n' ? 'block' : 'none';
    document.getElementById('edit-event-like-interval').value = interval || 1000;
    modeSelect.onchange = () => {
      document.getElementById('edit-event-interval-group').style.display = modeSelect.value === 'every_n' ? 'block' : 'none';
    };
  } else {
    likeConfig.style.display = 'none';
  }

  // Populate actions
  const actionsContainer = document.getElementById('edit-event-modal-actions');
  actionsContainer.innerHTML = '';
  const normalized = normalizeActions(actions);
  normalized.forEach(a => appendActionRowToContainer(actionsContainer, a.type, a));
  if (normalized.length === 0) appendActionRowToContainer(actionsContainer, 'minecraft');

  modal.classList.add('active');
}

function closeEditEventModal() {
  document.getElementById('edit-event-modal').classList.remove('active');
}

function addEditEventAction(type) {
  const container = document.getElementById('edit-event-modal-actions');
  if (container) appendActionRowToContainer(container, type);
}

function saveEditingEvent() {
  if (!editingEventKey) return;
  const actions = collectActionsFromContainer(document.getElementById('edit-event-modal-actions'));

  if (editingEventKey === 'Like' || editingEventKey.startsWith('Like_')) {
    const mode = document.getElementById('edit-event-like-mode').value;
    const interval = parseInt(document.getElementById('edit-event-like-interval').value) || 1000;
    if (mode === 'every_n') {
      // If interval changed, need to rename the key
      const newKey = `Like_${interval}`;
      if (newKey !== editingEventKey && currentConfig.Events[newKey]) {
        return showToast(`Event "${newKey}" already exists! Use a different interval.`, 'error');
      }
      if (newKey !== editingEventKey) {
        delete currentConfig.Events[editingEventKey];
      }
      currentConfig.Events[newKey] = { mode, interval, actions };
      editingEventKey = newKey;
    } else {
      // Switched to every_like — remove old Like_N key if different
      if (editingEventKey !== 'Like') {
        delete currentConfig.Events[editingEventKey];
      }
      currentConfig.Events.Like = { mode, actions };
      editingEventKey = 'Like';
    }
  } else {
    currentConfig.Events[editingEventKey] = actions;
  }

  closeEditEventModal();
  renderEventsGrid();
  showToast(`Event "${editingEventKey}" saved!`, 'success');
}

function deleteEditingEvent() {
  return (async () => {
  if (!editingEventKey) return;
  const registry = eventRegistryData ? eventRegistryData.registry : {};
  const reg = registry[editingEventKey] || {};
  let name = reg.name || editingEventKey;
  if (editingEventKey === 'Like' || editingEventKey.startsWith('Like_')) {
    const val = (currentConfig.Events || {})[editingEventKey];
    const m = (typeof val === 'object' && val !== null) ? val.mode : null;
    const intv = (typeof val === 'object' && val !== null) ? val.interval : null;
    if (m === 'every_n') name = `Like (every ${intv || '?'} likes)`;
    else if (m === 'every_like') name = 'Like (every like)';
  }
  if (!(await window.appConfirm({ title: 'Delete Event', message: `Delete event "${name}"?`, confirmText: 'Delete', tone: 'danger', icon: 'fa-trash' }))) return;
    delete currentConfig.Events[editingEventKey];
    closeEditEventModal();
    renderEventsGrid();
    showToast(`Event "${name}" deleted`, 'info');
}
  );
}

function deleteEvent(eventKey) {
  return (async () => {
  const registry = eventRegistryData ? eventRegistryData.registry : {};
  const reg = registry[eventKey] || {};
  let name = reg.name || eventKey;
  if (eventKey === 'Like' || eventKey.startsWith('Like_')) {
    const val = (currentConfig.Events || {})[eventKey];
    const m = (typeof val === 'object' && val !== null) ? val.mode : null;
    const intv = (typeof val === 'object' && val !== null) ? val.interval : null;
    if (m === 'every_n') name = `Like (every ${intv || '?'} likes)`;
    else if (m === 'every_like') name = 'Like (every like)';
  }
  if (!(await window.appConfirm({ title: 'Delete Event', message: `Delete event "${name}"?`, confirmText: 'Delete', tone: 'danger', icon: 'fa-trash' }))) return;
    delete currentConfig.Events[eventKey];
    renderEventsGrid();
    showToast(`Event "${name}" deleted`, 'info');
}
  );
}

function collectEvents() {
  // Events are already in currentConfig.Events, just need to ensure
  // the global gift actions are collected from the UI
  const globalGiftContainer = document.getElementById('global-actions-gift');
  if (globalGiftContainer) {
    const actions = collectActionsFromContainer(globalGiftContainer);
    if (!currentConfig.Gifts) currentConfig.Gifts = {};
    currentConfig.Gifts.GlobalActions = actions;
  }
  // Like_* events with mode/interval are already stored correctly
  // by saveNewEvent() and saveEditingEvent() — no additional collection needed.
}

function saveEvents() {
  // Collect global gift actions from UI
  collectEvents();
  // Also collect any remaining custom events
  if (typeof collectCustomEvents === 'function') collectCustomEvents();
  saveConfigData();
}

// Helper for event action rows in Gifts panel (global actions)
function addEventActionRow(eventKey, type, prefix = 'event-actions') {
  const container = document.getElementById(`${prefix}-${eventKey}`);
  if (!container) return;
  appendActionRowToContainer(container, type);
}

function collectEventActions(eventKey, prefix = 'event-actions') {
  const container = document.getElementById(`${prefix}-${eventKey}`);
  if (!container) return [];
  return collectActionsFromContainer(container);
}

// =========================================
// GIFTS
// =========================================
function getGiftDisplayName(key) {
  if (currentConfig.GiftNames && currentConfig.GiftNames[key]) return currentConfig.GiftNames[key];
  if (giftNameMap[key]) return giftNameMap[key];
  return key;
}

function populateGifts() {
  const container = document.getElementById('gifts-container');
  container.innerHTML = '';
  if(!currentConfig.Gifts) currentConfig.Gifts = {};
  if(!currentConfig.GiftCategories) currentConfig.GiftCategories = {};
  if(!currentConfig.GiftDescriptions) currentConfig.GiftDescriptions = {};

  streakDeltaSelected = (currentConfig.StreakDeltaGifts || []).map(String);

  const grouped = {};
  Object.keys(currentConfig.Gifts).forEach(giftKey => {
    const cat = currentConfig.GiftCategories[giftKey] || 'Uncategorized';
    if(!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(giftKey);
  });

  const sortedCats = Object.keys(grouped).sort((a, b) => {
    const numA = parseInt(a), numB = parseInt(b);
    if (!isNaN(numA) && !isNaN(numB)) return numA - numB;
    if (!isNaN(numA)) return -1;
    if (!isNaN(numB)) return 1;
    return a.localeCompare(b);
  });

  sortedCats.forEach(cat => {
    const block = document.createElement('div');
    block.className = 'gift-category-block';
    block.innerHTML = `
      <div class="gift-cat-header">${cat} <span class="cat-coins">${grouped[cat].length}</span></div>
      <div class="gift-cat-body"></div>`;
    const body = block.querySelector('.gift-cat-body');

    grouped[cat].forEach(giftKey => {
      const commands = currentConfig.Gifts[giftKey];
      const cmdCount = Array.isArray(commands) ? commands.length : 0;
      const displayName = getGiftDisplayName(giftKey);
      const iconUrl = giftIconMap[giftKey];

      const item = document.createElement('div');
      item.className = 'gift-item';
      item.innerHTML = `
        <div class="gift-item-icon">
          ${iconUrl ? `<img src="${iconUrl}" alt="${displayName}">` : `<i class="fa-solid fa-gift" style="color:var(--text-muted)"></i>`}
        </div>
        <span class="gift-item-name">${displayName}</span>
        <span class="gift-item-cmds">${cmdCount} cmd${cmdCount !== 1 ? 's' : ''}</span>`;
      item.addEventListener('click', () => openGiftModal(giftKey, displayName, commands, cat));
      body.appendChild(item);
    });
    container.appendChild(block);
  });

  if (sortedCats.length === 0) {
    container.innerHTML = '<p class="form-hint" style="text-align:center;padding:40px;">No gifts configured yet. Click "Add Gift" to get started.</p>';
  }
  populateGiftSimulator();
}

function populateGiftSimulator() {
  const select = document.getElementById('gift-sim-select');
  if (!select) return;
  const previous = select.value;
  const gifts = Object.keys(currentConfig.Gifts || {})
    .filter(key => key.toLowerCase() !== 'globalactions')
    .sort((a, b) => getGiftDisplayName(a).localeCompare(getGiftDisplayName(b)));
  select.innerHTML = gifts.map(key => `<option value="${escHtml(key)}">${escHtml(getGiftDisplayName(key))}</option>`).join('');
  if (gifts.includes(previous)) select.value = previous;
  const list = document.getElementById('gift-sim-picker-list');
  if (list) {
    list.innerHTML = gifts.map(key => {
      const name = getGiftDisplayName(key);
      const icon = giftIconMap[key];
      return `<button class="gift-sim-picker-option" type="button" role="option" data-gift-key="${escHtml(key)}" aria-selected="${select.value === key}">${icon ? `<img src="${escHtml(icon)}" alt="">` : '<span class="gift-sim-picker-fallback"><i class="fa-solid fa-gift"></i></span>'}<span class="gift-sim-picker-name">${escHtml(name)}</span><span class="gift-sim-picker-id">#${escHtml(key)}</span></button>`;
    }).join('');
    list.querySelectorAll('.gift-sim-picker-option').forEach(option => {
      option.addEventListener('click', () => selectSimulatorGift(option.dataset.giftKey));
    });
  }
  renderSimulatorGiftSelection();
  const mc = currentConfig.Settings?.MinecraftUsername || 'not configured';
  const mcLabel = document.getElementById('gift-sim-mc');
  if (mcLabel) mcLabel.textContent = `{mc}: ${mc}`;
  const button = document.getElementById('btn-simulate-gift');
  if (button) button.disabled = gifts.length === 0;
}

function renderSimulatorGiftSelection() {
  const select = document.getElementById('gift-sim-select');
  const button = document.getElementById('gift-sim-picker-button');
  if (!select || !button || !select.value) {
    if (button) button.innerHTML = '<span class="gift-sim-picker-placeholder">Choose a gift</span><i class="fa-solid fa-chevron-down"></i>';
    return;
  }
  const key = select.value;
  const name = getGiftDisplayName(key);
  const icon = giftIconMap[key];
  button.innerHTML = `${icon ? `<img src="${escHtml(icon)}" alt="">` : '<span class="gift-sim-picker-fallback"><i class="fa-solid fa-gift"></i></span>'}<span class="gift-sim-picker-name">${escHtml(name)}</span><span class="gift-sim-picker-id">#${escHtml(key)}</span><i class="fa-solid fa-chevron-down"></i>`;
  document.querySelectorAll('#gift-sim-picker-list .gift-sim-picker-option').forEach(option => option.setAttribute('aria-selected', String(option.dataset.giftKey === key)));
}

function selectSimulatorGift(key) {
  const select = document.getElementById('gift-sim-select');
  if (!select || !key) return;
  select.value = key;
  renderSimulatorGiftSelection();
  closeSimulatorGiftPicker();
}

function toggleSimulatorGiftPicker() {
  const list = document.getElementById('gift-sim-picker-list');
  const button = document.getElementById('gift-sim-picker-button');
  if (!list || !button) return;
  const opening = list.hidden;
  list.hidden = !opening;
  button.setAttribute('aria-expanded', String(opening));
}

function closeSimulatorGiftPicker() {
  const list = document.getElementById('gift-sim-picker-list');
  const button = document.getElementById('gift-sim-picker-button');
  if (list) list.hidden = true;
  if (button) button.setAttribute('aria-expanded', 'false');
}

async function simulateGift() {
  const select = document.getElementById('gift-sim-select');
  const user = document.getElementById('gift-sim-user')?.value.trim() || '';
  const amount = Number(document.getElementById('gift-sim-amount')?.value);
  const button = document.getElementById('btn-simulate-gift');
  const status = document.getElementById('gift-sim-status');
  if (!select?.value || !user || !Number.isInteger(amount) || amount < 1 || amount > 10000) {
    if (status) status.textContent = 'Choose a gift, enter a user, and use a whole amount from 1 to 10000.';
    return;
  }
  button.disabled = true;
  if (status) status.textContent = 'Running all configured actions…';
  try {
    const response = await fetch('/api/gifts/simulate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({gift_key: select.value, user, amount}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Simulation failed (${response.status})`);
    if (status) status.textContent = `Ran ${result.actions} action${result.actions === 1 ? '' : 's'} for ${result.gift}.`;
    showToast(`Simulated ${result.gift}: ${result.actions} actions`, 'success');
  } catch (error) {
    if (status) status.textContent = error.message;
    showToast(error.message, 'error');
  } finally {
    button.disabled = !select.options.length;
  }
}

function saveGifts() {
  currentConfig.StreakDeltaGifts = [...streakDeltaSelected];
  // Collect global gift actions from UI
  const globalGiftContainer = document.getElementById('global-actions-gift');
  if (globalGiftContainer) {
    const actions = collectActionsFromContainer(globalGiftContainer);
    if (!currentConfig.Gifts) currentConfig.Gifts = {};
    currentConfig.Gifts.GlobalActions = actions;
  }
  saveConfigData();
}

// ==========================================
// GIFT MODAL
// ==========================================
function openGiftModal(giftKey = null, displayName = null, commands = [], category = null) {
  editingGiftKey = giftKey;
  const modal = document.getElementById('gift-modal');
  const titleName = displayName || giftKey || "";
  document.getElementById('modal-title').textContent = giftKey ? `Edit Gift: ${titleName}` : "Add New Gift";
  document.getElementById('modal-gift-id').value = giftKey || "";
  document.getElementById('modal-gift-name').value = displayName || giftKey || "";
  document.getElementById('modal-gift-category').value = category || "";

  // Load description if editing
  const desc = currentConfig.GiftDescriptions?.[giftKey] || "";
  document.getElementById('modal-gift-description').value = desc;

  // Populate actions list
  const actionsList = document.getElementById('modal-actions-list');
  actionsList.innerHTML = '';
  const actions = normalizeActions(commands);
  actions.forEach(a => addActionRow(a.type, a));
  if (actions.length === 0) addActionRow('minecraft');

  document.getElementById('btn-delete-gift').style.display = giftKey ? 'inline-flex' : 'none';
  modal.classList.add('active');

  // Gift ID input → live icon preview
  document.getElementById('modal-gift-id').oninput = function() {
    const val = this.value.trim();
    if (val) updateGiftIconPreview(val);
    else document.getElementById('gift-icon-group').style.display = 'none';
  };

  // Show icon immediately if editing
  if (giftKey) updateGiftIconPreview(giftKey);
  // Set streak delta checkbox from existing list
  const sdChk = document.getElementById('modal-gift-streak-delta');
  if (sdChk) sdChk.checked = !!(giftKey && streakDeltaSelected.includes(String(giftKey)));
  fetchAvailableGifts();
}

function normalizeActions(commands) {
  // Convert old format (string list) to new format (action dicts)
  if (!commands || !Array.isArray(commands)) return [];
  return commands.map(c => {
    if (typeof c === 'string') return {type: 'minecraft', command: c};
    if (typeof c === 'object' && c.type) return c;
    return {type: 'minecraft', command: String(c)};
  });
}

function renderAddonPresetOptions(selectedCommand = '') {
  if (!addonActionPresets || addonActionPresets.length === 0) return '';
  const groups = {};
  addonActionPresets.forEach(a => {
    const group = a.addon_name || a.addon_id || 'Add-on';
    if (!groups[group]) groups[group] = [];
    groups[group].push(a);
  });
  return Object.entries(groups).map(([group, actions]) => `
    <optgroup label="Addon: ${escHtml(group)}">
      ${actions.map(a => `<option value="${escHtml(a.command || '')}" ${selectedCommand && selectedCommand === a.command ? 'selected' : ''}>${escHtml(a.name || a.id)}</option>`).join('')}
    </optgroup>`).join('');
}

function applyActionPreset(sel) {
  const row = sel.closest('.action-row');
  if (!row || !sel.value) return;
  const input = row.querySelector('.action-command');
  if (input) input.value = sel.value;
  sel.value = '';
}

function refreshActionPresetSelects() {
  document.querySelectorAll('.action-preset-select').forEach(sel => {
    const current = sel.value;
    sel.innerHTML = `<option value="">Addon preset...</option>${renderAddonPresetOptions()}`;
    sel.value = current && Array.from(sel.options).some(o => o.value === current) ? current : '';
  });
}

function addActionRow(type, data = null) {
  const container = document.getElementById('modal-actions-list');
  appendActionRowToContainer(container, type, data);
}

function appendActionRowToContainer(container, type, data = null) {
  const row = document.createElement('div');
  row.className = 'action-row';
  row.dataset.type = type;

  const typeColors = {minecraft: '#4CAF50', sound: '#FF9800', webhook: '#2196F3', random: '#9C27B0', roulette: '#E91E63'};
  const typeIcons = {minecraft: 'fa-terminal', sound: 'fa-volume-high', webhook: 'fa-link', random: 'fa-shuffle', roulette: 'fa-dice'};

  let fieldsHtml = '';
  if (type === 'minecraft') {
    fieldsHtml = `
      <div class="action-minecraft-tools">
        <select class="action-field action-preset-select" onchange="applyActionPreset(this)">
          <option value="">Addon preset...</option>${renderAddonPresetOptions(data?.command || '')}
        </select>
      </div>
      <input type="text" class="action-field action-command" placeholder="give {mc} diamond {amount}" value="${escHtml(data?.command || '')}">`;
  } else if (type === 'sound') {
    fieldsHtml = `
      <div style="display:flex;gap:4px;align-items:center;">
        <input type="text" class="action-field action-file" placeholder="File path (auto-filled after upload)" value="${escHtml(data?.file || '')}" style="flex:1;">
        <button class="btn btn-sm btn-secondary browse-sound-btn" type="button" style="padding:4px 10px;white-space:nowrap;" onclick="pickSoundFile(this)">Browse</button>
        <button class="btn btn-sm btn-ghost preview-sound-btn" type="button" style="padding:4px 8px;" onclick="previewSound(this)" title="Preview sound"><i class="fa-solid fa-play"></i></button>
      </div>
      <input type="text" class="action-field action-url" placeholder="OR URL (e.g. https://...)" value="${escHtml(data?.url || '')}">
      <input type="number" class="action-field action-volume" placeholder="Volume (0-1)" min="0" max="1" step="0.1" value="${data?.volume ?? 0.8}" style="width:80px;">`;
  } else if (type === 'webhook') {
    fieldsHtml = `
      <input type="text" class="action-field action-url" placeholder="https://example.com/hook" value="${escHtml(data?.url || '')}">
      <select class="action-field action-method">
        <option value="POST" ${data?.method === 'POST' ? 'selected' : ''}>POST</option>
        <option value="GET" ${data?.method === 'GET' ? 'selected' : ''}>GET</option>
      </select>`;
  } else if (type === 'random') {
    fieldsHtml = `<p class="form-hint" style="margin:4px 0;">Picks one action randomly when triggered. Add sub-actions below:</p>
      <div class="random-actions-list" style="padding-left:12px;border-left:2px solid ${typeColors.random};">
        ${(data?.actions || [{type:'minecraft',command:''}]).map(sa => `
          <div class="random-sub-action" style="display:flex;gap:4px;align-items:center;margin:4px 0;">
            <select class="random-sub-type" style="width:90px;">
              <option value="minecraft" ${sa.type==='minecraft'?'selected':''}>Minecraft</option>
              <option value="sound" ${sa.type==='sound'?'selected':''}>Sound</option>
            </select>
            <input type="text" class="random-sub-value" placeholder="command or file" value="${escHtml(sa.command || sa.file || '')}" style="flex:1;">
            <button class="btn btn-danger btn-sm" onclick="this.parentElement.remove()" style="padding:2px 6px;">&times;</button>
          </div>
        `).join('')}
      </div>
      <button class="btn btn-ghost btn-sm" onclick="addRandomSubAction(this)" style="margin-top:4px;"><i class="fa-solid fa-plus"></i> Sub-action</button>`;
  } else if (type === 'roulette') {
    fieldsHtml = `<p class="form-hint" style="margin:4px 0;">Starts a Gift Roulette spin when this fires. Pool, timing, and sounds are configured in the Roulette tab. Roulette must be enabled there.</p>`;
  }

  row.innerHTML = `
    <div class="action-row-header" style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
      <span style="color:${typeColors[type]};font-weight:600;font-size:12px;"><i class="fa-solid ${typeIcons[type]}"></i> ${type.toUpperCase()}</span>
      <button class="btn btn-danger btn-sm" onclick="this.closest('.action-row').remove()" style="margin-left:auto;padding:2px 8px;font-size:11px;">Remove</button>
    </div>
    <div class="action-fields">${fieldsHtml}</div>`;
  container.appendChild(row);
}

function addRandomSubAction(btn) {
  const list = btn.previousElementSibling;
  const div = document.createElement('div');
  div.className = 'random-sub-action';
  div.style.cssText = 'display:flex;gap:4px;align-items:center;margin:4px 0;';
  div.innerHTML = `
    <select class="random-sub-type" style="width:90px;">
      <option value="minecraft">Minecraft</option>
      <option value="sound">Sound</option>
    </select>
    <input type="text" class="random-sub-value" placeholder="command or file" style="flex:1;">
    <button class="btn btn-danger btn-sm" onclick="this.parentElement.remove()" style="padding:2px 6px;">&times;</button>`;
  list.appendChild(div);
}

function collectActions() {
  return collectActionsFromContainer(document.getElementById('modal-actions-list'));
}

function collectActionsFromContainer(container) {
  if (!container) return [];
  const rows = container.querySelectorAll('.action-row');
  const actions = [];
  rows.forEach(row => {
    const type = row.dataset.type;
    if (type === 'minecraft') {
      const cmd = row.querySelector('.action-command').value.trim();
      if (cmd) actions.push({type: 'minecraft', command: cmd});
    } else if (type === 'sound') {
      const file = row.querySelector('.action-file')?.value.trim() || '';
      const url = row.querySelector('.action-url')?.value.trim() || '';
      const volume = parseFloat(row.querySelector('.action-volume')?.value) || 0.8;
      if (file || url) actions.push({type: 'sound', ...(file ? {file} : {url}), volume});
    } else if (type === 'webhook') {
      const url = row.querySelector('.action-url').value.trim();
      const method = row.querySelector('.action-method').value;
      if (url) actions.push({type: 'webhook', url, method});
    } else if (type === 'random') {
      const subs = [];
      row.querySelectorAll('.random-sub-action').forEach(sa => {
        const st = sa.querySelector('.random-sub-type').value;
        const sv = sa.querySelector('.random-sub-value').value.trim();
        if (sv) subs.push(st === 'sound' ? {type: 'sound', file: sv} : {type: st, command: sv});
      });
      if (subs.length > 0) actions.push({type: 'random', actions: subs});
    } else if (type === 'roulette') {
      actions.push({type: 'roulette'});
    }
  });
  return actions;
}

// ── Sound File Picker (native Windows file dialog) ─────────────────────────
function pickSoundFile(btn) {
  const input = btn.parentElement.querySelector('.action-file');
  const fileInput = document.createElement('input');
  fileInput.type = 'file';
  fileInput.accept = '.mp3,.wav,.ogg,.flac,.aac,.m4a,.wma,audio/*';
  fileInput.style.display = 'none';

  fileInput.onchange = async () => {
    const file = fileInput.files[0];
    if (!file) return;

    btn.textContent = 'Uploading...';
    btn.disabled = true;

    const formData = new FormData();
    formData.append('file', file);

    try {
      const resp = await fetch('/api/upload-sound', { method: 'POST', body: formData });
      const data = await resp.json();
      if (data.error) {
        alert('Upload failed: ' + data.error);
      } else {
        input.value = data.path;
      }
    } catch (e) {
      alert('Upload error: ' + e.message);
    }

    btn.textContent = 'Browse';
    btn.disabled = false;
    fileInput.remove();
  };

  document.body.appendChild(fileInput);
  fileInput.click();
}

// ── Sound Preview ──
let _previewAudio = null;
let _previewBtn = null;

function previewSound(btn) {
  // If this button is already playing, stop it
  if (_previewAudio && _previewBtn === btn) {
    stopPreview();
    return;
  }

  // Stop any existing preview first
  if (_previewAudio) stopPreview();

  const row = btn.closest('.action-row');
  const filePath = row.querySelector('.action-file')?.value?.trim() || '';
  const fileUrl = row.querySelector('.action-url')?.value?.trim() || '';
  const volume = parseFloat(row.querySelector('.action-volume')?.value) || 0.8;

  let audioSrc = '';
  if (fileUrl && (fileUrl.startsWith('http://') || fileUrl.startsWith('https://'))) {
    audioSrc = fileUrl;
  } else if (filePath) {
    audioSrc = '/api/preview-sound?path=' + encodeURIComponent(filePath);
  } else {
    showToast('No sound file selected!', 'error');
    return;
  }

  _previewAudio = new Audio(audioSrc);
  _previewAudio.volume = Math.min(1, Math.max(0, volume));
  _previewBtn = btn;

  _previewAudio.onended = () => stopPreview();
  _previewAudio.onerror = () => {
    showToast('Failed to load audio file', 'error');
    stopPreview();
  };

  _previewAudio.play().then(() => {
    btn.innerHTML = '<i class="fa-solid fa-stop"></i>';
    btn.style.color = '#f44336';
  }).catch(e => {
    showToast('Playback error: ' + e.message, 'error');
    stopPreview();
  });
}

function stopPreview() {
  if (_previewAudio) {
    _previewAudio.onerror = null;
    _previewAudio.onended = null;
    _previewAudio.pause();
    _previewAudio.currentTime = 0;
    _previewAudio.src = '';
    _previewAudio = null;
  }
  if (_previewBtn) {
    _previewBtn.innerHTML = '<i class="fa-solid fa-play"></i>';
    _previewBtn.style.color = '';
    _previewBtn = null;
  }
}

function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Alias for song section and other callers that use 'esc'
const esc = escHtml;

// ── Hoverable template-variable chips ──────────────────────────────
// One shared explanation map; every "Variables:" hint renders chips from it.
const VAR_EXPLANATIONS = {
  user: 'TikTok username of the sender.',
  mc: 'Your configured Minecraft username.',
  amount: 'Gift count this execution uses — the streak total once the streak ends.',
  repeat_count: 'Running streak total so far.',
  gift_name: 'Display name of the gift.',
  gift_id: 'TikTok numeric ID of the gift.',
  total_coin: 'Coins for this fire: repeat_count x diamond_count.',
  diamond_count: 'Coin price of ONE gift.',
  total_likes: 'Total likes on the stream.',
  comment: 'The chat message text.',
  tag: 'Event tag, when present.',
};
function varChip(v) {
  const tip = VAR_EXPLANATIONS[v] || ('Value of ' + v + '.');
  return `<span class="var-chip" data-var-tip="${escHtml(tip)}">{${escHtml(v)}}</span>`;
}
function varChips(vars) {
  return (vars || []).map(varChip).join(' ');
}
function positionVarTip(el) {
  const tip = document.getElementById('var-tip');
  if (!tip) return;
  const r = el.getBoundingClientRect();
  const w = 260;
  let left = Math.min(Math.max(8, r.left), window.innerWidth - w - 8);
  let top = r.bottom + 6;
  if (top + 80 > window.innerHeight) top = Math.max(8, r.top - 90);
  tip.style.left = left + 'px';
  tip.style.top = top + 'px';
  tip.style.maxWidth = w + 'px';
}
document.addEventListener('mouseover', (e) => {
  const chip = e.target.closest ? e.target.closest('.var-chip') : null;
  let tip = document.getElementById('var-tip');
  if (!chip) { if (tip) tip.remove(); return; }
  if (!tip) {
    tip = document.createElement('div');
    tip.id = 'var-tip';
    document.body.appendChild(tip);
  }
  tip.textContent = chip.getAttribute('data-var-tip') || '';
  positionVarTip(chip);
});
document.addEventListener('mouseout', (e) => {
  const chip = e.target.closest ? e.target.closest('.var-chip') : null;
  if (!chip) return;
  const tip = document.getElementById('var-tip');
  if (tip && !chip.contains(e.relatedTarget)) tip.remove();
});

function closeGiftModal() {
  document.getElementById('gift-modal').classList.remove('active');
  document.getElementById('gift-icon-group').style.display = 'none';
  document.getElementById('modal-gift-description').value = '';
}

async function saveGiftModal() {
  const giftId = document.getElementById('modal-gift-id').value.trim();
  const displayName = document.getElementById('modal-gift-name').value.trim().toLowerCase();
  const newCategory = document.getElementById('modal-gift-category').value.trim();
  if(!giftId) return showToast("Gift ID cannot be empty!", 'error');
  if(!displayName) return showToast("Gift name cannot be empty!", 'error');

  const actions = collectActions();
  if(!currentConfig.GiftCategories) currentConfig.GiftCategories = {};
  if(!currentConfig.GiftNames) currentConfig.GiftNames = {};
  if(!currentConfig.GiftDescriptions) currentConfig.GiftDescriptions = {};
  const newKey = giftId;

  if (editingGiftKey && editingGiftKey !== newKey) {
    delete currentConfig.Gifts[editingGiftKey];
    delete currentConfig.GiftCategories[editingGiftKey];
    delete currentConfig.GiftNames[editingGiftKey];
    delete currentConfig.GiftDescriptions[editingGiftKey];
  }
  if(!currentConfig.Gifts) currentConfig.Gifts = {};
  currentConfig.Gifts[newKey] = actions;
  if (newCategory) currentConfig.GiftCategories[newKey] = newCategory;
  if (displayName) currentConfig.GiftNames[newKey] = displayName;
  // Save description
  const description = document.getElementById('modal-gift-description').value.trim();
  if (description) currentConfig.GiftDescriptions[newKey] = description;
  else delete currentConfig.GiftDescriptions[newKey];

  // Update streak delta from checkbox and commit it before populateGifts(),
  // which rebuilds the modal state from currentConfig.
  const sdChk = document.getElementById('modal-gift-streak-delta');
  if (editingGiftKey && editingGiftKey !== newKey) {
    streakDeltaSelected = streakDeltaSelected.filter(id => id !== String(editingGiftKey));
  }
  if (sdChk && sdChk.checked) {
    if (!streakDeltaSelected.includes(newKey)) streakDeltaSelected.push(newKey);
  } else {
    streakDeltaSelected = streakDeltaSelected.filter(id => id !== newKey);
  }
  currentConfig.StreakDeltaGifts = [...streakDeltaSelected];

  closeGiftModal();
  populateGifts();
  return saveConfigData({ successMessage: 'Gift saved!' });
}

function deleteGiftModal() {
  return (async () => {
  if (editingGiftKey && !(await window.appConfirm({ title: 'Delete Gift', message: `Delete ${getGiftDisplayName(editingGiftKey)}?`, confirmText: 'Delete', tone: 'danger', icon: 'fa-gift' }))) return;
  {
    delete currentConfig.Gifts[editingGiftKey];
    if (currentConfig.GiftCategories) delete currentConfig.GiftCategories[editingGiftKey];
    if (currentConfig.GiftNames) delete currentConfig.GiftNames[editingGiftKey];
    if (currentConfig.GiftDescriptions) delete currentConfig.GiftDescriptions[editingGiftKey];
    closeGiftModal();
    populateGifts();
    showToast('Gift deleted', 'info');
  }
  });
}

// ==========================================
// AVAILABLE GIFTS (catalog)
// ==========================================
async function loadGiftIconMap() {
  try {
    const res = await fetch('/api/gifts/available');
    const gifts = await res.json();
    if (gifts && gifts.length > 0) {
      // This preload exists only for name/icon lookup. Do not seed the modal's
      // precise current-room pool with the full multi-region catalog.
      cachedAllGifts = gifts;
      gifts.forEach(g => {
        const gid = String(g.id);
        if (g.name) giftNameMap[gid] = g.name.toLowerCase();
        if (g.icon) giftIconMap[gid] = g.icon;
      });
      if (Object.keys(currentConfig.Gifts || {}).length > 0) populateGifts();
    }
  } catch(e) {}
}

// Rebuild the catalog from every source: TikTok's room panel, all EulerStream
// regions, Euler's full 2783-row catalog, and this app's own gift history.
// TikTok's panel alone is only ~700 gifts and hides region-locked ones like
// Game Controller, so the sync is the only way to see every gift.
async function refreshGiftCatalog() {
  const btn = document.getElementById('btn-refresh-gift-catalog');
  if (!btn) return;
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Syncing...';
  showToast('Syncing gift catalog from TikTok + all regions...', 'info');
  try {
    const res = await fetch('/api/gifts/refresh', { method: 'POST' });
    const data = await res.json();
    if (!res.ok || data.status !== 'ok') {
      showToast((data.errors && data.errors[0]) || 'Gift catalog sync failed', 'error');
      return;
    }
    cachedAvailableGifts = [];
    cachedAllGifts = [];
    await loadGiftIconMap();
    const gained = data.added > 0 ? `+${data.added} new` : 'no new gifts';
    showToast(`Gift catalog: ${data.after} gifts (${gained})`, 'success');
    if (data.errors && data.errors.length) console.warn('Gift catalog sync notes:', data.errors);
  } catch (e) {
    showToast('Gift catalog sync failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = original;
  }
}

async function fetchAvailableGifts() {
  // Panel scope is exact: only gifts TikTok currently offers in this room.
  // The full catalog remains available only through the explicit scope switch;
  // never silently mix regional duplicate IDs into a current-room search.
  if (cachedAvailableGifts.length > 0) {
    showGiftPickerChips(cachedAvailableGifts);
    return;
  }
  try {
    const [roomRes, allRes] = await Promise.all([
      fetch('/api/gifts/available?scope=panel'),
      fetch('/api/gifts/available')
    ]);
    const roomGifts = await roomRes.json();
    const allGifts = await allRes.json();
    if (allGifts && allGifts.length > 0) {
      allGifts.forEach(g => {
        const gid = String(g.id);
        if (g.name) giftNameMap[gid] = g.name.toLowerCase();
        if (g.icon) giftIconMap[gid] = g.icon;
      });
    }
    if (roomGifts && roomGifts.length > 0) {
      cachedAvailableGifts = roomGifts;
      cachedAllGifts = allGifts;
      showGiftPickerChips(roomGifts);
    } else if (allGifts && allGifts.length > 0) {
      cachedAvailableGifts = allGifts;
      cachedAllGifts = allGifts;
      showGiftPickerChips(allGifts);
    } else {
      document.getElementById('available-gifts-group').style.display = 'none';
    }
  } catch (e) {}
}

function showGiftPickerChips(roomGifts) {
  const group = document.getElementById('available-gifts-group');
  group.style.display = 'block';
  renderGiftChips(roomGifts);
  const searchInput = document.getElementById('gift-search-input');
  const scopeSelect = document.getElementById('gift-picker-scope');
  const scopeNote = document.getElementById('gift-picker-scope-note');
  searchInput.value = '';
  if (scopeSelect) scopeSelect.value = 'panel';
  const refresh = () => {
    const q = searchInput.value.toLowerCase().trim();
    const allMode = scopeSelect?.value === 'all';
    let pool = allMode ? cachedAllGifts : cachedAvailableGifts;
    if (q) pool = pool.filter(g => g.name.includes(q) || String(g.id).includes(q));
    if (scopeNote) scopeNote.textContent = allMode
      ? 'Showing the full catalog. IDs may be regional or unavailable in your room.'
      : 'Showing only gifts TikTok currently offers in your room.';
    searchInput.placeholder = allMode
      ? 'Search all known gifts by name or ID...'
      : 'Search gifts available in your current TikTok room...';
    renderGiftChips(pool);
  };
  searchInput.oninput = refresh;
  if (scopeSelect) scopeSelect.onchange = refresh;
}

function renderGiftChips(gifts) {
  const list = document.getElementById('available-gifts-list');
  list.innerHTML = '';
  gifts.forEach(gift => {
    const chip = document.createElement('div');
    chip.className = 'gift-chip';
    chip.onclick = () => selectAvailableGift(String(gift.id), gift.name, gift.diamond_count);
    chip.innerHTML = `${gift.icon ? `<img src="${gift.icon}" alt="${gift.name}">` : '<i class="fa-solid fa-gift" style="color:var(--accent)"></i>'} <span class="chip-name">${gift.name}</span> <span class="chip-id">#${gift.id}</span> <span class="chip-coins">${gift.diamond_count}</span>`;
    list.appendChild(chip);
  });
  if (gifts.length === 0) list.innerHTML = '<p class="gift-picker-empty">No matching gift in your selected scope.</p>';
}

function selectAvailableGift(id, name, coins) {
  document.getElementById('modal-gift-id').value = id;
  document.getElementById('modal-gift-name').value = name;
  document.getElementById('modal-gift-category').value = `${coins} Coins`;
  document.getElementById('modal-gift-description').value = '';
  updateGiftIconPreview(id);
}

// ── Gift Icon Preview ──────────────────────
function updateGiftIconPreview(id) {
  const group = document.getElementById('gift-icon-group');
  const img = document.getElementById('gift-icon-preview');
  const btn = document.getElementById('btn-download-icon');
  const hint = document.getElementById('gift-icon-hint');
  const iconUrl = giftIconMap[id];
  if (iconUrl) {
    img.src = iconUrl;
    group.style.display = 'block';
    btn.style.display = 'inline-flex';
    hint.textContent = 'Click Download PNG to save as PNG';
    btn.dataset.iconUrl = iconUrl;
    btn.dataset.giftId = id;
  } else {
    group.style.display = 'none';
  }
}

// ── Download Gift Icon as PNG ──────────────
async function downloadGiftIconAsPng() {
  const btn = document.getElementById('btn-download-icon');
  const url = btn.dataset.iconUrl;
  const giftId = btn.dataset.giftId || 'gift';
  if (!url) return;

  try {
    const res = await fetch(url);
    const blob = await res.blob();
    const img = new Image();
    const blobUrl = URL.createObjectURL(blob);
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0);
      canvas.toBlob(pngBlob => {
        const link = document.createElement('a');
        link.href = URL.createObjectURL(pngBlob);
        link.download = `gift_${giftId}.png`;
        link.click();
        URL.revokeObjectURL(link.href);
      }, 'image/png');
      URL.revokeObjectURL(blobUrl);
    };
    img.src = blobUrl;
  } catch (e) {
    alert('Failed to download icon. Check console for details.');
    console.error('Download icon error:', e);
  }
}

// ==========================================
// PROFILES
// ==========================================
let currentProfile = "default";

async function loadProfiles() {
  try {
    const res = await fetch(`/api/profiles?_=${Date.now()}`, { cache: 'no-store' });
    const data = await res.json();
    currentProfile = data.active;
    const select = document.getElementById('active-profile-select');
    select.innerHTML = '';
    data.profiles.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p;
      opt.textContent = p;
      if(p === currentProfile) opt.selected = true;
      select.appendChild(opt);
    });
  } catch(e) {}
}

async function openProfileModal() {
  document.getElementById('profile-modal').classList.add('active');
  try {
    const res = await fetch(`/api/profiles?_=${Date.now()}`, { cache: 'no-store' });
    const data = await res.json();
    const container = document.getElementById('profile-list-container');
    container.innerHTML = '';
    data.profiles.forEach(p => {
      const isActive = p === data.active;
      const div = document.createElement('div');
      div.className = 'profile-list-item';
      div.innerHTML = `
        <span style="font-size:1.1rem;">${p} ${isActive ? '<span style="color:var(--accent);margin-left:8px;font-size:0.85rem;font-weight:700;">ACTIVE</span>' : ''}</span>
        <div style="display:flex;gap:8px;">
          <button class="btn btn-ghost btn-sm" onclick="exportProfile('${p}')"><i class="fa-solid fa-download"></i></button>
          <button class="btn btn-primary btn-sm" onclick="switchProfile('${p}')" ${isActive ? 'disabled' : ''}><i class="fa-solid fa-play"></i></button>
          <button class="btn btn-danger btn-sm" onclick="deleteProfile('${p}')" ${isActive ? 'disabled' : ''}><i class="fa-solid fa-trash"></i></button>
        </div>`;
      container.appendChild(div);
    });
  } catch(e) {}
}

function closeProfileModal() {
  document.getElementById('profile-modal').classList.remove('active');
}

async function createProfile(duplicate) {
  const name = document.getElementById('new-profile-name').value.trim();
  if(!name) return showToast("Enter a profile name!", 'error');
  try {
    const res = await fetch('/api/profiles/create', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({profile: name, duplicate: duplicate})
    });
    const data = await res.json();
    if(data.status === 'success') {
      document.getElementById('new-profile-name').value = '';
      await loadProfiles();
      await loadConfig();
      openProfileModal();
      showToast('Profile created!', 'success');
    } else { showToast(data.message, 'error'); }
  } catch(e) { showToast("Failed to create profile", 'error'); }
}

async function deleteProfile(name) {
  if (!(await window.appConfirm({ title: 'Delete Profile', message: `Delete profile: ${name}?`, subtitle: 'The bot keeps running with the current profile.', confirmText: 'Delete', tone: 'danger', icon: 'fa-user-slash' }))) return;
  {
    try {
      const res = await fetch(`/api/profiles/${name}?_=${Date.now()}`, { method: 'DELETE', cache: 'no-store' });
      const data = await res.json();
      if(data.status === 'success') { await loadProfiles(); openProfileModal(); showToast('Profile deleted', 'info'); }
      else { showToast(data.message, 'error'); }
    } catch(e) { showToast("Failed to delete profile", 'error'); }
  }
}

function exportProfile(name) {
  window.location.href = `/api/profiles/${name}/export`;
}

async function importProfile(event) {
  const file = event.target.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await fetch('/api/profiles/import', { method: 'POST', body: formData });
    const data = await res.json();
    if(data.status === 'success') { await loadProfiles(); openProfileModal(); showToast(data.message, 'success'); }
    else { showToast(data.message, 'error'); }
  } catch(e) { showToast("Failed to import profile", 'error'); }
  event.target.value = '';
}

async function switchProfile(name) {
  try {
    await fetch('/api/profiles/switch', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({profile: name})
    });
    await loadConfig();
    await loadProfiles();
    document.dispatchEvent(new CustomEvent('gcs:profile-changed', {detail: {profile: name}}));
    closeProfileModal();
    showToast(`Switched to ${name}`, 'success');
  } catch(e) { showToast("Failed to switch profile", 'error'); }
}

// =========================================
// EVENT BROWSER (Dynamic Event Registry)
// =========================================
let eventRegistryData = null;

async function loadEventRegistry() {
  try {
    const res = await fetch('/api/event-registry');
    const data = await res.json();
    eventRegistryData = data;
    window.eventRegistry = data;
    renderEventBrowser();
  } catch (e) {
    console.error("Failed to load event registry:", e);
  }
}

function renderEventBrowser() {
  const container = document.getElementById('event-browser-categories');
  const searchInput = document.getElementById('event-browser-search');
  if (!container || !eventRegistryData) return;

  const grouped = eventRegistryData.grouped;
  const events = (currentConfig.Events || {});
  const query = (searchInput?.value || '').toLowerCase().trim();

  container.innerHTML = '';

  const catOrder = ['gifts', 'social', 'chat', 'room', 'battle', 'subscription', 'interactive', 'moderation', 'display', 'system'];
  let totalShown = 0;

  catOrder.forEach(catKey => {
    const catData = grouped[catKey];
    if (!catData) return;
    const meta = catData.meta;
    const events = catData.events;

    // Filter events by search query
    const filtered = {};
    Object.entries(events).forEach(([key, evt]) => {
      if (evt.infra) return; // Skip infrastructure events from the browser
      if (query) {
        const searchable = `${key} ${evt.name} ${evt.description} ${evt.category}`.toLowerCase();
        if (!searchable.includes(query)) return;
      }
      filtered[key] = evt;
    });

    if (Object.keys(filtered).length === 0) return;
    totalShown += Object.keys(filtered).length;

    // Build category section
    const section = document.createElement('div');
    section.className = 'eb-category';

    const enabledCount = Object.keys(filtered).filter(k => {
      const val = events[k];
      if (Array.isArray(val)) return val.length > 0;
      if (typeof val === 'object' && val !== null) return (val.actions || []).length > 0;
      return false;
    }).length;

    section.innerHTML = `
      <div class="eb-cat-header" onclick="this.parentElement.classList.toggle('collapsed')">
        <div style="display:flex;align-items:center;gap:10px;">
          <span class="eb-cat-icon">${meta.icon}</span>
          <span class="eb-cat-label">${meta.label}</span>
          <span class="eb-cat-count">${Object.keys(filtered).length}</span>
          ${enabledCount > 0 ? `<span class="eb-cat-active">${enabledCount} active</span>` : ''}
        </div>
        <i class="fa-solid fa-chevron-down eb-cat-chevron"></i>
      </div>
      <div class="eb-cat-body"></div>
    `;

    const body = section.querySelector('.eb-cat-body');

    Object.entries(filtered).forEach(([eventKey, evt]) => {
      const val = events[eventKey];
      let isEnabled = false;
      if (Array.isArray(val)) isEnabled = val.length > 0;
      else if (typeof val === 'object' && val !== null) isEnabled = (val.actions || []).length > 0;
      const card = document.createElement('div');
      card.className = `eb-event-card ${isEnabled ? 'eb-enabled' : ''}`;
      card.dataset.eventKey = eventKey;

      const priorityColors = { high: '#3ba55c', medium: '#f0b232', low: '#545b70' };
      const priorityColor = priorityColors[evt.priority] || priorityColors.low;

      card.innerHTML = `
        <div class="eb-event-row">
          <div class="eb-event-info">
            <div class="eb-event-name">
              ${evt.name}
              <span class="eb-priority-badge" style="background:${priorityColor};">${evt.priority}</span>
            </div>
            <div class="eb-event-desc">${evt.description}</div>
            <div class="eb-event-vars">
              ${evt.template_vars.map(v => `<code>{${v}}</code>`).join(' ')}
            </div>
          </div>
          <label class="eb-toggle">
            <input type="checkbox" ${isEnabled ? 'checked' : ''} onchange="toggleEvent('${eventKey}', this.checked)">
            <span class="eb-toggle-slider"></span>
          </label>
        </div>
        <div class="eb-event-actions" style="display:${isEnabled ? 'block' : 'none'};">
          <div class="form-hint" style="margin-bottom:8px;">Actions to run when this event fires:</div>
          <div id="custom-event-actions-${eventKey}" class="event-actions-container"></div>
          <div style="margin-top:6px; display:flex; gap:4px; flex-wrap:wrap;">
            <button class="btn btn-ghost btn-sm" onclick="addCustomEventAction('${eventKey}','minecraft')"><i class="fa-solid fa-terminal"></i> Minecraft</button>
            <button class="btn btn-ghost btn-sm" onclick="addCustomEventAction('${eventKey}','sound')"><i class="fa-solid fa-volume-high"></i> Sound</button>
            <button class="btn btn-ghost btn-sm" onclick="addCustomEventAction('${eventKey}','webhook')"><i class="fa-solid fa-link"></i> Webhook</button>
            <button class="btn btn-ghost btn-sm" onclick="addCustomEventAction('${eventKey}','random')"><i class="fa-solid fa-shuffle"></i> Random</button>
            <button class="btn btn-ghost btn-sm" onclick="addCustomEventAction('${eventKey}','roulette')"><i class="fa-solid fa-dice"></i> Roulette</button>
          </div>
        </div>
      `;

      body.appendChild(card);

      // Populate existing actions if enabled
      if (isEnabled) {
        const actionsContainer = card.querySelector(`#custom-event-actions-${eventKey}`);
        const rawActions = Array.isArray(val) ? val : (val?.actions || []);
        const normalized = normalizeActions(rawActions);
        normalized.forEach(a => appendActionRowToContainer(actionsContainer, a.type, a));
      }
    });

    container.appendChild(section);
  });

  // Update count badge
  const countBadge = document.getElementById('event-browser-count');
  if (countBadge) countBadge.textContent = `${totalShown} events`;
}

function toggleEvent(eventKey, enabled) {
  const card = document.querySelector(`.eb-event-card[data-event-key="${eventKey}"]`);
  if (!card) return;

  const actionsPanel = card.querySelector('.eb-event-actions');
  if (actionsPanel) {
    actionsPanel.style.display = enabled ? 'block' : 'none';
  }

  if (enabled) {
    card.classList.add('eb-enabled');
    // Initialize with an empty action row if no actions exist
    const container = document.getElementById(`custom-event-actions-${eventKey}`);
    if (container && container.children.length === 0) {
      appendActionRowToContainer(container, 'minecraft');
    }
  } else {
    card.classList.remove('eb-enabled');
  }

  // Auto-save the change to config
  saveCustomEvent(eventKey);
}

function addCustomEventAction(eventKey, type) {
  const container = document.getElementById(`custom-event-actions-${eventKey}`);
  if (container) appendActionRowToContainer(container, type);
}

function saveCustomEvent(eventKey) {
  // Collect all custom events from the browser and update config
  collectCustomEvents();
  saveConfigData();
}

function collectCustomEvents() {
  if (!currentConfig.Events) currentConfig.Events = {};

  // Iterate all event cards in the browser
  document.querySelectorAll('.eb-event-card').forEach(card => {
    const key = card.dataset.eventKey;
    const checkbox = card.querySelector('input[type="checkbox"]');
    if (!checkbox || !key) return;

    if (checkbox.checked) {
      const actionsContainer = card.querySelector('.event-actions-container');
      const actions = collectActionsFromContainer(actionsContainer);
      if (actions.length > 0) {
        currentConfig.Events[key] = actions;
      } else {
        // Don't remove if it has a complex structure (Like)
        const existing = currentConfig.Events[key];
        if (!existing || (Array.isArray(existing) && existing.length === 0)) {
          delete currentConfig.Events[key];
        }
      }
    } else {
      delete currentConfig.Events[key];
    }
  });
}

// ==========================================
// THEME (Stardew dark/light)
// ==========================================
function applyTheme(theme, persist) {
  theme = (theme === 'light') ? 'light' : 'dark';
  // dark is the default :root, so only set the attr for light
  if (theme === 'light') document.documentElement.setAttribute('data-theme', 'light');
  else document.documentElement.removeAttribute('data-theme');
  // reflect on the toggle buttons
  const lb = document.getElementById('theme-btn-light');
  const db = document.getElementById('theme-btn-dark');
  if (lb && db) {
    lb.classList.toggle('on', theme === 'light');
    db.classList.toggle('on', theme === 'dark');
  }
  // instant-apply cache for next load (no flash)
  try { localStorage.setItem('tmc-theme', theme); } catch (e) {}
  if (persist) {
    if (!currentConfig.Settings) currentConfig.Settings = {};
    currentConfig.Settings.Theme = theme;
    fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(currentConfig)
    }).catch(() => {});
  }
}

function setupThemeToggle() {
  document.querySelectorAll('#theme-toggle button').forEach(btn => {
    btn.addEventListener('click', () => applyTheme(btn.dataset.themeSet, true));
  });
}

// ==========================================
// INITIALIZATION
// ==========================================
// Static "Variables:" hints (gift modal + global gift actions) render once.
const GIFT_VAR_LIST = ['user', 'mc', 'amount', 'repeat_count', 'gift_name', 'gift_id', 'total_coin', 'diamond_count'];
function renderStaticVarHints() {
  const giftModalVars = document.getElementById('gift-modal-vars');
  if (giftModalVars) giftModalVars.innerHTML = 'Each action runs in order. Variables:<br>' + varChips(GIFT_VAR_LIST);
  const globalVars = document.getElementById('global-gift-vars');
  if (globalVars) globalVars.innerHTML = 'These actions run on EVERY gift received. Variables:<br>' + varChips(GIFT_VAR_LIST);
}
document.addEventListener('DOMContentLoaded', () => {
  setupThemeToggle();
  renderStaticVarHints();
  loadProfiles();
  loadConfig();
  checkBotStatus();
  loadGiftIconMap();
  loadEventRegistry();
  loadAddons();
  loadSongConfig();
  fetchSongHistory();
  setupTopGifterToggles();

  // Low-overhead polling: skip hidden dashboard work and never overlap requests.
  // This preserves each endpoint's cadence while preventing a slow response from
  // creating concurrent fetches and extra CPU/network pressure.
  attachChatScrollHandler();
  const scheduleLightPoll = (fn, intervalMs) => {
    let inFlight = false;
    return setInterval(async () => {
      if (document.hidden || inFlight) return;
      inFlight = true;
      try { await fn(); } finally { inFlight = false; }
    }, intervalMs);
  };

  scheduleLightPoll(checkBotStatus, 3000);
  scheduleLightPoll(fetchLogs, 1500);
  scheduleLightPoll(fetchViewerStats, 3000);
  scheduleLightPoll(fetchGiftLog, 2500);
  scheduleLightPoll(fetchFollowLog, 3000);
  scheduleLightPoll(fetchSuperfanLog, 2500);
  scheduleLightPoll(fetchChatLog, 2500);
  scheduleLightPoll(fetchSimConsole, 2000);
  // Active streaks do not need sub-second hidden-dashboard polling.
  scheduleLightPoll(fetchActiveStreaks, 1000);
  scheduleLightPoll(fetchSongQueue, 3000);
  scheduleLightPoll(fetchSongHistory, 5000);
  scheduleLightPoll(fetchSpotifyStatus, 10000);

  // Save buttons
  document.getElementById('btn-save-settings').addEventListener('click', saveSettings);
  document.getElementById('btn-save-events').addEventListener('click', saveEvents);
  document.getElementById('btn-save-gifts').addEventListener('click', saveGifts);
  document.getElementById('btn-simulate-gift').addEventListener('click', simulateGift);
  document.getElementById('gift-sim-picker-button').addEventListener('click', toggleSimulatorGiftPicker);
  document.addEventListener('click', event => {
    if (!event.target.closest('#gift-sim-picker')) closeSimulatorGiftPicker();
  });
  document.getElementById('btn-add-gift').addEventListener('click', () => openGiftModal());
  const btnSyncCatalog = document.getElementById('btn-refresh-gift-catalog');
  if (btnSyncCatalog) btnSyncCatalog.addEventListener('click', refreshGiftCatalog);
  document.getElementById('btn-add-event').addEventListener('click', openAddEventModal);
  document.getElementById('btn-manage-profiles').addEventListener('click', openProfileModal);

  // Song tab
  document.getElementById('btn-save-song-config').addEventListener('click', saveSongConfig);
  document.getElementById('btn-spotify-connect').addEventListener('click', connectSpotify);
  document.getElementById('btn-spotify-disconnect').addEventListener('click', disconnectSpotify);

  // Profile select change
  document.getElementById('active-profile-select').addEventListener('change', async (e) => {
    await switchProfile(e.target.value);
  });

  // Watch panel visibility changes — re-render events/gifts when their tab is shown
  // (WebView2 doesn't paint innerHTML changes made to hidden panels)
  const _panelObserver = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.attributeName === 'class' && m.target.classList.contains('active')) {
        if (m.target.id === 'panel-events') renderEventsGrid();
        if (m.target.id === 'panel-gifts') populateGifts();
        if (m.target.id === 'panel-addons') loadAddons();
        if (m.target.id === 'panel-console') { fetchLogs(); fetchSimConsole(); }
      }
    }
  });
  document.querySelectorAll('.panel').forEach(p => {
    _panelObserver.observe(p, { attributes: true, attributeFilter: ['class'] });
  });

  // Streak Delta search
  const streakSearch = document.getElementById('streak-delta-search');
  if (streakSearch) {
    streakSearch.addEventListener('input', (e) => renderStreakDeltaDropdown(e.target.value));
    streakSearch.addEventListener('focus', (e) => renderStreakDeltaDropdown(e.target.value));
    document.addEventListener('click', (e) => {
      const picker = streakSearch.parentElement;
      if (picker && !picker.contains(e.target)) {
        document.getElementById('streak-delta-dropdown').style.display = 'none';
      }
    });
  }

  // Event Browser search
  const ebSearch = document.getElementById('event-browser-search');
  if (ebSearch) {
    ebSearch.addEventListener('input', () => renderEventBrowser());
  }

  // Add Event Modal search
  const aeSearch = document.getElementById('add-event-search');
  if (aeSearch) {
    aeSearch.addEventListener('input', () => renderAddEventList());
  }

  // Modal close buttons
  document.querySelectorAll('.modal-close').forEach(btn => {
    btn.addEventListener('click', function() {
      this.closest('.modal-overlay').classList.remove('active');
    });
  });
});

// ==========================================
// ADD-ONS
// ==========================================
async function loadAddons(opts = {}) {
  const grid = document.getElementById('addons-grid');
  try {
    const res = await fetch(`/api/addons?_=${Date.now()}`, { cache: 'no-store' });
    const data = await res.json();
    installedAddons = Array.isArray(data.addons) ? data.addons : [];
    addonActionPresets = installedAddons.filter(a => a.enabled).flatMap(a => a.actions || []);
    if (!selectedAddonId && installedAddons.length) selectedAddonId = installedAddons[0].id;
    if (selectedAddonId && !installedAddons.some(a => a.id === selectedAddonId)) {
      selectedAddonId = installedAddons.length ? installedAddons[0].id : null;
    }
    renderAddonsGrid();
    renderAddonDetail();
    refreshActionPresetSelects();
    if (opts.force) showToast('Add-ons rescanned', 'success');
  } catch (e) {
    if (grid) grid.innerHTML = '<div class="addon-empty">Failed to load add-ons.</div>';
    showToast('Failed to load add-ons', 'error');
  }
}

function addonById(id) {
  return installedAddons.find(a => a.id === id) || null;
}

function renderAddonsGrid() {
  const grid = document.getElementById('addons-grid');
  const count = document.getElementById('addons-count');
  if (!grid) return;
  if (count) count.textContent = installedAddons.length;
  if (!installedAddons.length) {
    grid.innerHTML = '<div class="addon-empty">No add-ons installed yet. Click Install Add-on to import a .zip pack.</div>';
    return;
  }
  grid.innerHTML = installedAddons.map(addon => {
    const enabled = !!addon.enabled;
    const selected = addon.id === selectedAddonId;
    const overlayCount = (addon.overlays || []).length;
    const actionCount = (addon.actions || []).length;
    return `
      <button type="button" class="addon-card ${selected ? 'selected' : ''} ${enabled ? '' : 'disabled'}" onclick="selectAddon('${escHtml(addon.id)}')">
        <div class="addon-card-top">
          <div class="addon-card-icon"><i class="fa-solid ${escHtml(addon.icon || 'fa-puzzle-piece')}"></i></div>
          <div class="addon-card-main">
            <div class="addon-card-name">${escHtml(addon.name || addon.id)}</div>
            <div class="addon-card-meta">v${escHtml(addon.version || '0.0.0')} · ${escHtml(addon.game || 'Minecraft')}</div>
          </div>
          <span class="addon-status ${enabled ? 'ok' : 'muted'}">${enabled ? 'Enabled' : 'Disabled'}</span>
        </div>
        <div class="addon-card-desc">${escHtml(addon.description || 'No description')}</div>
        <div class="addon-card-stats">
          <span><i class="fa-solid fa-tv"></i> ${overlayCount} overlays</span>
          <span><i class="fa-solid fa-terminal"></i> ${actionCount} actions</span>
        </div>
      </button>`;
  }).join('');
}

function selectAddon(id) {
  selectedAddonId = id;
  renderAddonsGrid();
  renderAddonDetail();
}

function renderAddonDetail() {
  const box = document.getElementById('addon-detail-card');
  if (!box) return;
  const addon = addonById(selectedAddonId);
  if (!addon) {
    box.innerHTML = '<div class="addon-empty tall"><i class="fa-solid fa-puzzle-piece"></i><span>Select an add-on to view setup, actions, overlays, and health.</span></div>';
    return;
  }
  const helperUrl = (addon.config && addon.config.helper_url) || (addon.connection && addon.connection.default_base_url) || '';
  const reqs = Array.isArray(addon.requirements) ? addon.requirements : [];
  const overlays = Array.isArray(addon.overlays) ? addon.overlays : [];
  const actions = Array.isArray(addon.actions) ? addon.actions : [];
  const modPath = addon.install && addon.install.helper_mod_jar ? `${addon.path}/${addon.install.helper_mod_jar}` : '';
  box.innerHTML = `
    <div class="addon-detail-header">
      <div class="addon-detail-title">
        <div class="addon-detail-icon"><i class="fa-solid ${escHtml(addon.icon || 'fa-puzzle-piece')}"></i></div>
        <div>
          <h3>${escHtml(addon.name || addon.id)}</h3>
          <p>${escHtml(addon.description || '')}</p>
        </div>
      </div>
      <label class="addon-enable-toggle">
        <input type="checkbox" ${addon.enabled ? 'checked' : ''} onchange="toggleAddonEnabled('${escHtml(addon.id)}', this.checked)">
        <span>${addon.enabled ? 'Enabled' : 'Disabled'}</span>
      </label>
    </div>

    <div class="addon-detail-section">
      <div class="addon-section-heading"><i class="fa-solid fa-list-check"></i> Setup Checklist</div>
      <div class="addon-check-list">
        <div class="addon-check ok"><i class="fa-solid fa-check"></i> Add-on installed</div>
        <div class="addon-check ${addon.enabled ? 'ok' : 'warn'}"><i class="fa-solid ${addon.enabled ? 'fa-check' : 'fa-pause'}"></i> ${addon.enabled ? 'Enabled in app' : 'Disabled in app'}</div>
        ${reqs.map(r => `<div class="addon-check info"><i class="fa-solid fa-circle-info"></i> ${escHtml(r.label || r.id || r)}</div>`).join('')}
      </div>
      ${modPath ? `<div class="addon-copy-row"><input class="addon-copy-input" value="${escHtml(modPath)}" readonly><button class="btn btn-ghost btn-sm" onclick="copyAddonText('${encodeURIComponent(modPath)}')"><i class="fa-solid fa-copy"></i> Copy helper path</button></div>` : ''}
    </div>

    <div class="addon-detail-section">
      <div class="addon-section-heading"><i class="fa-solid fa-heart-pulse"></i> Connection / Health</div>
      <div class="addon-health-row">
        <input type="text" class="form-input" id="addon-helper-url" value="${escHtml(helperUrl)}" placeholder="http://127.0.0.1:5943">
        <button class="btn btn-primary btn-sm" onclick="saveAddonHelperUrl('${escHtml(addon.id)}')"><i class="fa-solid fa-save"></i> Save</button>
        <button class="btn btn-ghost btn-sm" onclick="testAddonHealth('${escHtml(addon.id)}')"><i class="fa-solid fa-signal"></i> Test</button>
      </div>
      <div id="addon-health-result" class="addon-health-result muted">Click Test to ping the helper.</div>
    </div>

    ${addon.id === 'survival_rush' ? `
    <div class="addon-detail-section objective-rush-section">
      <div class="addon-section-heading"><i class="fa-solid fa-flag-checkered"></i> Objective Rush</div>
      <div id="objective-rush-control" class="objective-rush-control"><div class="addon-empty small">Loading game state...</div></div>
    </div>` : ''}

    <div class="addon-detail-section">
      <div class="addon-section-heading"><i class="fa-solid fa-tv"></i> Overlays</div>
      <div class="addon-overlay-list">
        ${overlays.length ? overlays.map(o => {
          const full = window.location.origin + o.url;
          return `<div class="addon-overlay-item">
            <div><strong>${escHtml(o.name)}</strong><span>${escHtml(o.description || o.recommended_size || '')}</span></div>
            <div class="addon-copy-row compact"><input class="addon-copy-input" value="${escHtml(full)}" readonly><button class="btn btn-primary btn-sm" onclick="copyAddonText('${encodeURIComponent(full)}')"><i class="fa-solid fa-copy"></i></button></div>
          </div>`;
        }).join('') : '<div class="addon-empty small">No overlays in this add-on.</div>'}
      </div>
    </div>

    <div class="addon-detail-section">
      <div class="addon-section-heading"><i class="fa-solid fa-terminal"></i> Action Presets</div>
      <div class="addon-action-list">
        ${actions.length ? actions.map(a => `<div class="addon-action-item">
          <div class="addon-action-info"><strong>${escHtml(a.name)}</strong><code>${escHtml(a.command || '')}</code><span>${escHtml(a.description || '')}</span></div>
          <div class="addon-action-buttons">
            <button class="btn btn-ghost btn-sm" onclick="copyAddonText('${encodeURIComponent(a.command || '')}')"><i class="fa-solid fa-copy"></i></button>
            ${a.id === 'survival_rush_gift_dragon' ? '<span class="addon-gift-only"><i class="fa-solid fa-gift"></i> Gift only</span>' : `<button class="btn btn-primary btn-sm" onclick="testAddonCommand('${encodeURIComponent(a.command || '')}')"><i class="fa-solid fa-play"></i> Test</button>`}
          </div>
        </div>`).join('') : '<div class="addon-empty small">No action presets in this add-on.</div>'}
      </div>
      <p class="form-hint">These presets also appear in Minecraft action rows under the “Addon preset...” dropdown.</p>
    </div>

    <div class="addon-detail-section">
      <div class="addon-section-heading"><i class="fa-solid fa-folder-open"></i> Debug Info</div>
      <div class="addon-debug-grid">
        <div><span>ID</span><code>${escHtml(addon.id)}</code></div>
        <div><span>Folder</span><code>${escHtml(addon.path || '')}</code></div>
        <div><span>Manifest</span><code>${escHtml(addon.manifest_path || '')}</code></div>
      </div>
      <button class="btn btn-danger btn-sm" onclick="removeAddon('${escHtml(addon.id)}')"><i class="fa-solid fa-trash"></i> Remove Add-on</button>
    </div>
  `;
  if (addon.id === 'survival_rush') loadObjectiveRushState();
}

let objectiveRushPollTimer = null;

async function loadObjectiveRushState() {
  if (selectedAddonId !== 'survival_rush' || !document.getElementById('objective-rush-control')) return;
  try {
    const res = await fetch(`/api/addons/survival-rush/objective-rush/state?_=${Date.now()}`, {cache:'no-store'});
    const data = await res.json();
    renderObjectiveRush(data);
  } catch (e) {
    renderObjectiveRush({state:{status:'idle'}, helper:{connected:false,error:e.message}});
  }
  clearTimeout(objectiveRushPollTimer);
  if (selectedAddonId === 'survival_rush' && document.getElementById('panel-addons')?.classList.contains('active')) {
    objectiveRushPollTimer = setTimeout(loadObjectiveRushState, 1000);
  }
}

function objectiveTargetAmount(active) {
  const target = active?.definition?.target || {};
  return Math.max(1, Number(target.amount || 1));
}

function renderObjectiveRush(data) {
  const box = document.getElementById('objective-rush-control');
  if (!box) return;
  const state = data.state || {status:'idle',wins:0,strikes:0,win_target:20};
  const helper = data.helper || {};
  const objectives = state.active_objectives || (state.active ? [state.active] : []);
  const status = String(state.status || 'idle');
  const running = status === 'active';
  const paused = status === 'paused';
  const isError = status === 'error' || status === 'aborted';
  const worldMismatch = !!state.world_mismatch;
  const world = state.world_context || {};
  const tier = escHtml(state.progression_tier || 'START');
  const countdown = Number(state.completion_countdown_remaining || 0);
  const dragonActive = !!(state.dragon_active || (state.active_objectives || []).some(o => o.definition && (o.definition.id === 'dragon_slayer' || o.definition.family === 'dragon')));
  const objectiveRows = objectives.slice(0, 3).map((active, index) => {
    const target = objectiveTargetAmount(active);
    const progress = Math.min(Number(active?.progress || 0), target);
    const pct = target ? Math.min(100, Math.round(progress / target * 100)) : 0;
    const name = escHtml(active?.definition?.name || active?.definition?.id || '');
    const desc = escHtml(active?.definition?.description || '');
    const isDragonRow = !!(active?.definition?.id === 'dragon_slayer' || active?.definition?.family === 'dragon');
    return `<div class="or-objective ${active?.resolved ? 'complete' : ''} ${isDragonRow ? 'dragon-row' : ''}"><span>OBJECTIVE ${index + 1}${active?.resolved ? ' \u2713' : ''}</span><h4>${name}</h4><p>${desc}</p><div class="or-progress"><div style="width:${pct}%"></div></div><b>${progress} / ${target}</b></div>`;
  }).join('');
  const worldLine = [
    world.day ? `Day ${escHtml(String(world.day))}` : '',
    world.difficulty ? escHtml(world.difficulty) : '',
    world.dimension ? escHtml(world.dimension) : '',
    world.biome ? escHtml(world.biome) : '',
  ].filter(Boolean).join(' \u00b7 ');
  const diagLines = Array.isArray(state.director_diagnostics) ? state.director_diagnostics : [];
  const diagHtml = diagLines.length ? `<div class="or-diagnostics"><div class="or-diag-label">Director Diagnostics</div>${diagLines.map(d => `<div class="or-diag-line">${escHtml(typeof d === 'string' ? d : (d.message || JSON.stringify(d)))}</div>`).join('')}</div>` : '';
  const statusLabel = isError ? 'ERROR' : paused ? 'PAUSED' : running ? 'ACTIVE' : (status === 'won' ? 'WON' : 'IDLE');
  box.innerHTML = `
    <div class="or-head"><span class="or-status ${running ? 'active' : paused ? 'paused' : isError ? 'error' : ''}">${escHtml(statusLabel)} \u00d7${Number(state.objective_count || 1)}</span><span class="or-helper ${helper.connected ? 'ok' : 'off'}"><i class="fa-solid fa-circle"></i> ${helper.connected ? 'Helper online' : 'Helper offline'}</span></div>
    <div class="or-tier-world"><span class="or-tier">${tier}</span>${worldLine ? `<span class="or-world">${worldLine}</span>` : ''}</div>
    <div class="or-score"><strong>${Number(state.wins || 0)}<small>/${Number(state.win_target || 10)} WINS</small></strong><strong>${Number(state.strikes || 0)}<small>/3 STRIKES</small></strong></div>
    <div class="or-actions">${[1,2,3].map(n => `<button class="btn btn-ghost btn-sm ${Number(state.objective_count || 1) === n ? 'active' : ''}" onclick="objectiveRushAction('objective-count',{count:${n}})">${n} Objective${n > 1 ? 's' : ''}</button>`).join('')}</div>
    ${running && countdown > 0 ? `<div class="or-countdown"><i class="fa-solid fa-stopwatch"></i> ${countdown}s remaining</div>` : ''}
    ${worldMismatch ? `<div class="or-warn"><i class="fa-solid fa-triangle-exclamation"></i> World mismatch detected \u2014 progress paused until resolved</div>` : ''}
    ${(running || paused || isError) && objectives.length ? objectiveRows : `<div class="or-idle">${status === 'won' ? 'RUN COMPLETE!' : paused ? 'Run paused. Resume when ready.' : isError ? 'Run encountered an error.' : 'Start a 20-Win Objective Rush run.'}</div>`}
    ${running ? `<small>Count changes apply next set.</small>` : ''}
    ${dragonActive ? `<div class="or-dragon"><i class="fa-solid fa-dragon"></i> Dragon Slayer is active \u2014 gift objective</div>` : ''}
    ${helper.error && !helper.connected ? `<div class="or-error">${escHtml(helper.error)}</div>` : ''}
    ${diagHtml}
    <div class="or-actions">
      ${running ? `<button class="btn btn-danger btn-sm" onclick="objectiveRushAction('fail',{reason:'manual'})">Fail Set</button><button class="btn btn-ghost btn-sm" onclick="objectiveRushAction('reroll',{penalize:false})">Reroll Set</button><button class="btn btn-ghost btn-sm" onclick="objectiveRushAction('surrender',{})">Surrender</button><button class="btn btn-danger btn-sm" onclick="objectiveRushAction('abort',{})">Abort</button>` : `<button class="btn btn-primary" ${helper.connected ? '' : 'disabled'} onclick="objectiveRushAction('start',{win_target:20})"><i class="fa-solid fa-play"></i> Start 20-Win Run</button>`}
    </div>`;
}

async function objectiveRushAction(action, payload) {
  try {
    const res = await fetch(`/api/addons/survival-rush/objective-rush/${action}`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload || {})});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Objective Rush action failed');
    renderObjectiveRush(data);
    showToast(`Objective Rush: ${action}`, 'success');
  } catch (e) { showToast(e.message || 'Objective Rush action failed', 'error'); }
}

async function toggleAddonEnabled(id, enabled) {
  try {
    const res = await fetch(`/api/addons/${encodeURIComponent(id)}/enable`, {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({enabled})
    });
    const data = await res.json();
    if (data.status !== 'success') throw new Error(data.message || 'Toggle failed');
    showToast(enabled ? 'Add-on enabled' : 'Add-on disabled', enabled ? 'success' : 'info');
    await loadAddons();
  } catch (e) { showToast(e.message || 'Failed to update add-on', 'error'); }
}

async function saveAddonHelperUrl(id) {
  const value = document.getElementById('addon-helper-url')?.value?.trim() || '';
  try {
    const res = await fetch(`/api/addons/${encodeURIComponent(id)}/config`, {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({config:{helper_url:value}})
    });
    const data = await res.json();
    if (data.status !== 'success') throw new Error(data.message || 'Save failed');
    showToast('Add-on config saved', 'success');
    await loadAddons();
  } catch (e) { showToast(e.message || 'Failed to save add-on config', 'error'); }
}

async function testAddonHealth(id) {
  const out = document.getElementById('addon-health-result');
  if (out) { out.className = 'addon-health-result muted'; out.textContent = 'Testing...'; }
  try {
    const res = await fetch(`/api/addons/${encodeURIComponent(id)}/health?_=${Date.now()}`, { cache:'no-store' });
    const data = await res.json();
    if (out) {
      out.className = `addon-health-result ${data.connected ? 'ok' : 'error'}`;
      out.textContent = data.connected
        ? `Connected · ${data.latency_ms || 0}ms · ${data.helper_url || ''}`
        : (data.error || data.response?.error || 'Helper offline');
    }
  } catch (e) {
    if (out) { out.className = 'addon-health-result error'; out.textContent = 'Health check failed: ' + e.message; }
  }
}

async function installAddonFromInput(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  try {
    const res = await fetch('/api/addons/install', { method: 'POST', body: form });
    const data = await res.json();
    if (data.status !== 'success') throw new Error(data.message || 'Install failed');
    selectedAddonId = data.addon && data.addon.id;
    showToast(data.message || 'Add-on installed', 'success');
    await loadAddons();
  } catch (e) {
    showToast(e.message || 'Failed to install add-on', 'error');
  } finally {
    event.target.value = '';
  }
}

async function removeAddon(id) {
  const addon = addonById(id);
  if (!addon || !(await window.appConfirm({ title: 'Remove Add-on', message: `Remove add-on "${addon.name || id}"?`, confirmText: 'Remove', tone: 'danger', icon: 'fa-puzzle-piece' }))) return;
  try {
    const res = await fetch(`/api/addons/${encodeURIComponent(id)}/remove`, { method: 'POST' });
    const data = await res.json();
    if (data.status !== 'success') throw new Error(data.message || 'Remove failed');
    selectedAddonId = null;
    showToast('Add-on removed', 'info');
    await loadAddons();
  } catch (e) { showToast(e.message || 'Failed to remove add-on', 'error'); }
}

async function testAddonCommand(encodedCommand) {
  const command = decodeURIComponent(encodedCommand || '').trim();
  if (!command) return;
  try {
    const r = await fetch('/api/console/send', {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({command})
    });
    const data = await r.json().catch(() => ({}));
    if (r.ok && data.ok !== false) showToast('Command sent to Minecraft connector', 'success');
    else showToast(data.error || 'Command failed', 'error');
    setTimeout(fetchSimConsole, 100);
  } catch (e) { showToast('Command test failed: ' + e.message, 'error'); }
}

function copyAddonText(encodedText) {
  const text = decodeURIComponent(encodedText || '');
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(() => showCopyToast('Copied!')).catch(() => copyAddonTextFallback(text));
  } else {
    copyAddonTextFallback(text);
  }
}

function copyAddonTextFallback(text) {
  const input = document.createElement('input');
  input.value = text;
  input.style.position = 'fixed';
  input.style.opacity = '0';
  document.body.appendChild(input);
  input.select();
  document.execCommand('copy');
  input.remove();
  showCopyToast('Copied!');
}

// ==========================================
// OVERLAY MANAGEMENT
// ==========================================

function copyOverlayUrl(type) {
  const input = document.getElementById('overlay-url-' + type);
  if (!input) return;
  if (navigator.clipboard) {
    navigator.clipboard.writeText(input.value).then(() => {
      showCopyToast('Overlay URL copied!');
    }).catch(() => { fallbackCopy(input); });
  } else {
    fallbackCopy(input);
  }
}

function fallbackCopy(input) {
  input.select();
  document.execCommand('copy');
  showCopyToast('Overlay URL copied!');
}

function showCopyToast(msg) {
  const existing = document.querySelector('.copy-toast');
  if (existing) existing.remove();
  const toast = document.createElement('div');
  toast.className = 'copy-toast';
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => { toast.style.opacity='0'; toast.style.transition='opacity 0.3s'; setTimeout(()=>toast.remove(),300); }, 2000);
}

function toggleFilterPill(btn) {
  const group = btn.closest('.filter-pills');
  const pills = group ? Array.from(group.querySelectorAll('.filter-pill')) : [btn];
  const activeCount = pills.filter(p => p.classList.contains('active')).length;
  const allActive = activeCount === pills.length;

  if (allActive) {
    // First click from "show all" starts a chosen subset with only this category.
    pills.forEach(p => p.classList.toggle('active', p === btn));
  } else {
    // Subset mode is true multi-select: add/remove categories like Follower + Newbie.
    btn.classList.toggle('active');
    const nextActiveCount = pills.filter(p => p.classList.contains('active')).length;
    if (nextActiveCount === 0) {
      // Empty subset would show nothing; treat it as reset/show all.
      pills.forEach(p => p.classList.add('active'));
    }
  }
  updateOverlayUrl('chat');
}

function updateOverlayUrl(type) {
  const base = window.location.origin;
  let url = base + '/overlay/' + type;
  const params = new URLSearchParams();

  if (type === 'chat') {
    const pills = document.querySelectorAll('#chat-filter-categories .filter-pill.active');
    const cats = Array.from(pills).map(p => p.dataset.val);
    const allPills = document.querySelectorAll('#chat-filter-categories .filter-pill');
    if (cats.length > 0 && cats.length < allPills.length) {
      params.set('categories', cats.join(','));
    }
    const minGifter = document.getElementById('chat-min-gifter');
    const minMember = document.getElementById('chat-min-member');
    if (minGifter && parseInt(minGifter.value) > 0) params.set('min_gifter_level', minGifter.value);
    if (minMember && parseInt(minMember.value) > 0) params.set('min_member_level', minMember.value);
  } else if (type === 'gifts') {
    const search = document.getElementById('gift-search-filter');
    const sort = document.getElementById('gift-sort');
    const minCoins = document.getElementById('gift-min-coins');
    if (search && search.value.trim()) params.set('search', search.value.trim());
    if (sort && sort.value !== 'none') params.set('sort', sort.value);
    if (minCoins && parseInt(minCoins.value) > 0) params.set('min_coins', minCoins.value);
  } else if (type === 'song') {
    const skinSel = document.getElementById('song-skin-select');
    if (skinSel && skinSel.value && skinSel.value !== 'default') params.set('skin', skinSel.value);
  } else if (type === 'roulette') {
    // No URL params yet; the overlay URL is static. Kept as a branch so future
    // options (e.g. accent color) slot in without touching the generic path.
  }

  const qs = params.toString();
  const fullUrl = qs ? url + '?' + qs : url;

  const urlInput = document.getElementById('overlay-url-' + type);
  if (urlInput) urlInput.value = fullUrl;

  const iframe = document.getElementById('preview-' + type);
  if (iframe) {
    const panelActive = document.getElementById('panel-overlays')?.classList.contains('active') === true;
    const isRunning = OverlayPreviewManager.syncFrame(type, iframe, fullUrl, panelActive, window.localStorage);
    iframe.closest('.overlay-preview-frame')?.classList.toggle('preview-disabled', !isRunning);
  }
}

function ensureOverlayPreviewControl(type) {
  const iframe = document.getElementById('preview-' + type);
  const body = iframe?.closest('.overlay-section-body');
  const frame = iframe?.closest('.overlay-preview-frame');
  if (!iframe || !body || !frame || document.getElementById('preview-toggle-' + type)) return;

  iframe.setAttribute('loading', 'lazy');
  iframe.setAttribute('title', type + ' overlay preview');

  const toolbar = document.createElement('div');
  toolbar.className = 'overlay-preview-toolbar';
  toolbar.innerHTML = `
    <div class="overlay-preview-note"><i class="fa-solid fa-gauge-high"></i> Dashboard preview uses extra CPU/RAM</div>
    <label class="overlay-preview-toggle">
      <input type="checkbox" id="preview-toggle-${type}">
      <span class="overlay-preview-toggle-slider"></span>
      <span>Live preview</span>
    </label>`;
  body.insertBefore(toolbar, frame);

  const toggle = toolbar.querySelector('input');
  toggle.checked = OverlayPreviewManager.isEnabled(type, window.localStorage);
  toggle.addEventListener('change', () => toggleOverlayPreview(type, toggle.checked));
}

function toggleOverlayPreview(type, enabled) {
  OverlayPreviewManager.setEnabled(type, enabled, window.localStorage);
  updateOverlayUrl(type);
}

function suspendOverlayPreviews() {
  OVERLAY_PREVIEW_TYPES.forEach(type => {
    const iframe = document.getElementById('preview-' + type);
    if (iframe && iframe.src !== 'about:blank') iframe.src = 'about:blank';
  });
}

function initOverlayPreviews() {
  OVERLAY_PREVIEW_TYPES.forEach(type => {
    ensureOverlayPreviewControl(type);
    updateOverlayUrl(type);
  });
}

// ===== COIN GOAL JAR CUSTOMIZE MODAL =====
function openCoinGoalModal() {
  fetch('/api/stats/coingoal')
    .then(r => r.json())
    .then(d => {
      document.getElementById('cg-modal-label').value = d.label || 'Tip Jar';
      document.getElementById('cg-modal-sublabel').value = d.sublabel || '';
      document.getElementById('cg-modal-goal').value = d.goal != null ? d.goal : 10000;
      document.getElementById('cg-modal-current').value = d.current != null ? d.current : 0;
      document.getElementById('cg-modal-adjust').value = '';
    })
    .catch(() => {})
    .finally(() => {
      const m = document.getElementById('coingoal-modal');
      if (m) m.classList.add('active');
    });
}

function closeCoinGoalModal() {
  const m = document.getElementById('coingoal-modal');
  if (m) m.classList.remove('active');
}

function _postCoinGoal(payload, okMsg) {
  return fetch('/api/coingoal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
    .then(r => r.json())
    .then(res => {
      if (res.status === 'success') {
        showCopyToast(okMsg || 'Coin jar updated!');
        // Refresh the live preview iframe
        const iframe = document.getElementById('preview-coingoal');
        if (iframe) iframe.src = iframe.src;
        // Sync modal fields to returned state
        if (res.data) {
          document.getElementById('cg-modal-current').value = res.data.current;
          document.getElementById('cg-modal-goal').value = res.data.goal;
        }
      } else {
        showCopyToast(res.message || 'Update failed', true);
      }
      return res;
    })
    .catch(() => showCopyToast('Update failed', true));
}

// mode: 'save' = save all fields (label/sublabel/goal/current absolute)
//       'set'  = set current to exact value only
function saveCoinGoal(mode) {
  const label = document.getElementById('cg-modal-label').value;
  const sublabel = document.getElementById('cg-modal-sublabel').value;
  const goal = parseInt(document.getElementById('cg-modal-goal').value) || 10000;
  const current = parseInt(document.getElementById('cg-modal-current').value) || 0;
  if (mode === 'set') {
    _postCoinGoal({ mode: 'set', current: current }, 'Current coins set!');
  } else {
    _postCoinGoal({ mode: 'set', label: label, sublabel: sublabel, goal: goal, current: current }, 'Coin jar saved!');
  }
}

function adjustCoinGoal() {
  const adj = parseInt(document.getElementById('cg-modal-adjust').value);
  if (isNaN(adj) || adj === 0) { showCopyToast('Enter a +/- amount', true); return; }
  _postCoinGoal({ mode: 'adjust', current: adj }, (adj > 0 ? '+' : '') + adj + ' coins applied!')
    .then(() => { document.getElementById('cg-modal-adjust').value = ''; });
}

async function resetCoinGoal() {
  if (!(await window.appConfirm({
    title: 'Reset Coin Jar',
    message: 'Reset current coins to 0?',
    subtitle: 'Goal & label stay.',
    confirmText: 'Reset to 0',
    tone: 'danger',
    icon: 'fa-coins'
  }))) return;
  _postCoinGoal({ reset: true }, 'Jar reset to 0!');
}

// ===== TOP GIFT LAYOUT CUSTOMIZE MODAL =====
let topGiftLayoutChoice = 'left';

function openTopGiftLayoutModal() {
  fetch('/api/stats/topgift/layout', { cache: 'no-store' })
    .then(r => r.json())
    .then(d => {
      topGiftLayoutChoice = (d && d.layout) || 'left';
      highlightTopGiftLayoutChoice();
    })
    .catch(() => {})
    .finally(() => {
      const m = document.getElementById('topgift-layout-modal');
      if (m) m.classList.add('active');
    });
}

function closeTopGiftLayoutModal() {
  const m = document.getElementById('topgift-layout-modal');
  if (m) m.classList.remove('active');
}

function selectLayout(choice) {
  topGiftLayoutChoice = choice;
  highlightTopGiftLayoutChoice();
}

function highlightTopGiftLayoutChoice() {
  const choices = document.querySelectorAll('#topgift-layout-modal label[data-choice]');
  choices.forEach(el => {
    if (el.dataset.choice === topGiftLayoutChoice) {
      el.style.borderColor = '#5865f2';
      el.style.background = 'rgba(88,101,242,0.12)';
    } else {
      el.style.borderColor = 'var(--border-default)';
      el.style.background = 'transparent';
    }
  });
}

function saveTopGiftLayout() {
  fetch('/api/topgift/layout', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ layout: topGiftLayoutChoice })
  })
    .then(r => r.json())
    .then(res => {
      if (res.status === 'success') {
        showCopyToast('Top card layout updated! Gift, Streak & Showcase refresh automatically.');
        // Refresh all three live previews so Khito sees the switch immediately
        ['preview-topgift', 'preview-topstreak', 'preview-topshowcase'].forEach(id => {
          const iframe = document.getElementById(id);
          if (iframe && iframe.src) iframe.src = iframe.src;
        });
        closeTopGiftLayoutModal();
      } else {
        showCopyToast(res.message || 'Update failed', true);
      }
    })
    .catch(() => showCopyToast('Update failed', true));
}

// ===== GIFT GOAL CUSTOMIZE MODAL =====
let giftGoalAvailableGifts = [];
let giftGoalSelectedGift = null;

function ggEscapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[ch]));
}

function normalizeGiftGoalGift(g) {
  const coins = parseInt(g.diamond_count || g.coins || g.gift_diamond_count || 0) || 0;
  return {
    id: String(g.id || g.gift_id || ''),
    name: String(g.name || g.gift_name || 'Unknown'),
    icon: String(g.icon || g.gift_icon || ''),
    coins,
    primary_effect_id: String(g.primary_effect_id || g.gift_primary_effect_id || ''),
    resource_id: String(g.resource_id || g.gift_resource_id || ''),
    has_animation: Boolean(g.has_animation || g.gift_has_animation || (coins >= 100 && (g.primary_effect_id || g.resource_id))),
  };
}

function setGiftGoalSelectedGift(gift) {
  giftGoalSelectedGift = gift && gift.id ? gift : null;
  document.getElementById('gg-modal-gift-id').value = giftGoalSelectedGift ? giftGoalSelectedGift.id : '';
  document.getElementById('gg-modal-gift-name').value = giftGoalSelectedGift ? giftGoalSelectedGift.name : '';
  document.getElementById('gg-modal-gift-icon').value = giftGoalSelectedGift ? giftGoalSelectedGift.icon : '';

  const box = document.getElementById('gg-selected-gift');
  if (!box) return;
  if (!giftGoalSelectedGift) {
    box.innerHTML = `
      <div class="gg-selected-gift-icon"><i class="fa-solid fa-gift"></i></div>
      <div class="gg-selected-gift-info">
        <div class="gg-selected-gift-name">No gift selected</div>
        <div class="gg-selected-gift-meta">Pick one from the list below</div>
      </div>`;
    return;
  }
  box.innerHTML = `
    <div class="gg-selected-gift-icon">
      ${giftGoalSelectedGift.icon ? `<img src="${giftGoalSelectedGift.icon}" alt="${giftGoalSelectedGift.name}" onerror="this.style.display='none';this.nextElementSibling.style.display='flex';">` : ''}
      <i class="fa-solid fa-gift" style="${giftGoalSelectedGift.icon ? 'display:none' : 'display:flex'}"></i>
    </div>
    <div class="gg-selected-gift-info">
      <div class="gg-selected-gift-name">${ggEscapeHtml(giftGoalSelectedGift.name)}</div>
      <div class="gg-selected-gift-meta">ID ${ggEscapeHtml(giftGoalSelectedGift.id)} · ${giftGoalSelectedGift.coins.toLocaleString()} coins</div>
    </div>`;
}

function renderGiftGoalGiftPicker() {
  const list = document.getElementById('gg-gift-list');
  if (!list) return;
  const search = (document.getElementById('gg-gift-search')?.value || '').trim().toLowerCase();
  const sort = document.getElementById('gg-gift-sort')?.value || 'az';
  let gifts = giftGoalAvailableGifts.slice();

  if (search) {
    gifts = gifts.filter(g =>
      g.name.toLowerCase().includes(search) ||
      g.id.toLowerCase().includes(search) ||
      String(g.coins).includes(search)
    );
  }

  gifts.sort((a, b) => {
    if (sort === 'za') return b.name.localeCompare(a.name) || a.coins - b.coins;
    if (sort === 'coins_low') return a.coins - b.coins || a.name.localeCompare(b.name);
    if (sort === 'coins_high') return b.coins - a.coins || a.name.localeCompare(b.name);
    return a.name.localeCompare(b.name) || a.coins - b.coins;
  });

  if (!gifts.length) {
    list.innerHTML = `<div class="gg-gift-empty">${giftGoalAvailableGifts.length ? 'No matching gifts' : 'No gifts loaded yet'}</div>`;
    return;
  }

  list.innerHTML = gifts.slice(0, 160).map(g => {
    const selected = giftGoalSelectedGift && String(giftGoalSelectedGift.id) === String(g.id);
    return `
      <button type="button" class="gg-gift-card ${selected ? 'selected' : ''}" onclick="selectGiftGoalGift('${encodeURIComponent(g.id)}')">
        <span class="gg-gift-card-icon">
          ${g.icon ? `<img src="${g.icon}" alt="${ggEscapeHtml(g.name)}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex';">` : ''}
          <i class="fa-solid fa-gift" style="${g.icon ? 'display:none' : 'display:flex'}"></i>
        </span>
        <span class="gg-gift-card-main">
          <span class="gg-gift-card-name">${ggEscapeHtml(g.name)}</span>
          <span class="gg-gift-card-meta">ID ${ggEscapeHtml(g.id)} · ${g.coins.toLocaleString()} coins</span>
        </span>
      </button>`;
  }).join('') + (gifts.length > 160 ? `<div class="gg-gift-empty">Showing first 160 results — search to narrow</div>` : '');
}

function selectGiftGoalGift(encodedId) {
  const id = decodeURIComponent(encodedId);
  const gift = giftGoalAvailableGifts.find(g => String(g.id) === String(id));
  if (!gift) return;
  setGiftGoalSelectedGift(gift);
  renderGiftGoalGiftPicker();
}

function openGiftGoalModal() {
  fetch('/api/stats/giftgoal')
    .then(r => r.json())
    .then(d => {
      document.getElementById('gg-modal-header').value = d.header || 'Goal Today';
      document.getElementById('gg-modal-goal').value = d.goal != null ? d.goal : 100;
      document.getElementById('gg-modal-current').value = d.current != null ? d.current : 0;
      document.getElementById('gg-gift-search').value = '';
      document.getElementById('gg-gift-sort').value = 'az';
      loadGiftGoalGifts(d.gift_id || '', d);
    })
    .catch(() => {})
    .finally(() => {
      const m = document.getElementById('giftgoal-modal');
      if (m) m.classList.add('active');
    });
}

function loadGiftGoalGifts(selectedId, currentState = {}) {
  const list = document.getElementById('gg-gift-list');
  if (list) list.innerHTML = '<div class="gg-gift-empty">Loading gifts...</div>';
  fetch('/api/gifts/available')
    .then(r => r.json())
    .then(gifts => {
      giftGoalAvailableGifts = Array.isArray(gifts) ? gifts.map(normalizeGiftGoalGift).filter(g => g.id) : [];
      const selected = giftGoalAvailableGifts.find(g => String(g.id) === String(selectedId));
      if (selected) {
        setGiftGoalSelectedGift(selected);
      } else if (selectedId) {
        setGiftGoalSelectedGift({
          id: String(selectedId),
          name: currentState.gift_name || 'Selected gift',
          icon: currentState.gift_icon || '',
          coins: parseInt(currentState.gift_diamond_count || 0) || 0,
          primary_effect_id: String(currentState.gift_primary_effect_id || ''),
          resource_id: String(currentState.gift_resource_id || ''),
          has_animation: Boolean(currentState.gift_has_animation),
        });
      } else {
        setGiftGoalSelectedGift(null);
      }
      renderGiftGoalGiftPicker();
    })
    .catch(() => {
      giftGoalAvailableGifts = [];
      setGiftGoalSelectedGift(null);
      if (list) list.innerHTML = '<div class="gg-gift-empty">Failed to load gifts</div>';
    });
}

function closeGiftGoalModal() {
  const m = document.getElementById('giftgoal-modal');
  if (m) m.classList.remove('active');
}

function saveGiftGoal() {
  const giftId = document.getElementById('gg-modal-gift-id').value;
  const giftName = document.getElementById('gg-modal-gift-name').value;
  const giftIcon = document.getElementById('gg-modal-gift-icon').value;
  const header = document.getElementById('gg-modal-header').value;
  const goal = parseInt(document.getElementById('gg-modal-goal').value) || 100;
  const current = parseInt(document.getElementById('gg-modal-current').value) || 0;

  if (!giftId) {
    showCopyToast('Pick a gift first', true);
    return;
  }

  const selected = giftGoalSelectedGift || {};
  fetch('/api/giftgoal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      gift_id: giftId,
      gift_name: giftName,
      gift_icon: giftIcon,
      gift_diamond_count: selected.coins || 0,
      gift_primary_effect_id: selected.primary_effect_id || '',
      gift_resource_id: selected.resource_id || '',
      gift_has_animation: Boolean(selected.has_animation),
      goal,
      current,
      header
    })
  })
    .then(r => r.json())
    .then(res => {
      if (res.status === 'success') {
        showCopyToast('Gift goal saved!');
        const iframe = document.getElementById('preview-giftgoal');
        if (iframe) iframe.src = iframe.src;
      } else {
        showCopyToast(res.message || 'Save failed', true);
      }
    })
    .catch(() => showCopyToast('Save failed', true));
}

async function resetGiftGoal() {
  if (!(await window.appConfirm({ title: 'Reset Gift Goal', message: 'Reset current count to 0?', confirmText: 'Reset to 0', tone: 'danger', icon: 'fa-gift' }))) return;
  fetch('/api/giftgoal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reset: true })
  })
    .then(r => r.json())
    .then(res => {
      if (res.status === 'success') {
        showCopyToast('Gift goal reset!');
        document.getElementById('gg-modal-current').value = 0;
        const iframe = document.getElementById('preview-giftgoal');
        if (iframe) iframe.src = iframe.src;
      }
    })
    .catch(() => showCopyToast('Reset failed', true));
}

function resetTopGiftOverlay() {
  const iframe = document.getElementById('preview-topgift');
  if (iframe && iframe.contentWindow) {
    // Call the reset function inside the iframe
    try {
      iframe.contentWindow.resetTopGift();
      showCopyToast('Top Gift reset!');
    } catch(e) {
      // Fallback: reload the iframe
      iframe.src = iframe.src;
      showCopyToast('Top Gift reset!');
    }
  }
}

function resetTopStreakOverlay() {
  const iframe = document.getElementById('preview-topstreak');
  if (iframe && iframe.contentWindow) {
    try {
      iframe.contentWindow.resetTopStreak();
      showCopyToast('Top Streak reset!');
    } catch(e) {
      iframe.src = iframe.src;
      showCopyToast('Top Streak reset!');
    }
  }
}

async function resetTopGifter() {
  if (!(await window.appConfirm({ title: 'Reset Rankings', message: 'Reset gifter AND liker rankings for this stream?', confirmText: 'Reset', tone: 'danger', icon: 'fa-trophy' }))) return;
  fetch('/api/stats/topgifter/reset', { method: 'POST' })
    .then(r => r.json())
    .then(res => {
      showCopyToast(res.status === 'success' ? 'Gifter & liker rankings reset!' : res.message || 'Reset failed');
      const iframe = document.getElementById('preview-topgifter');
      if (iframe) iframe.src = iframe.src;
    })
    .catch(() => showCopyToast('Reset failed', true));
}

// Amount-visibility toggles for the Top Gifter & Liker leaderboard overlay.
// Settings persist to data/overlay_settings.json and the overlay reads them
// live from the /api/stats/topgifter poll — no bot restart, no OBS-side UI.
function setupTopGifterToggles() {
  const coinChk = document.getElementById('topgifter-show-coins');
  const likeChk = document.getElementById('topgifter-show-likes');
  if (!coinChk && !likeChk) return;

  // Load current state.
  fetch('/api/stats/overlay/settings', { cache: 'no-store' })
    .then(r => r.json())
    .then(s => {
      if (coinChk) coinChk.checked = !!s.show_gift_amounts;
      if (likeChk) likeChk.checked = !!s.show_like_amounts;
    })
    .catch(() => {});

  function persist(field, value) {
    fetch('/api/stats/overlay/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: value })
    }).catch(() => showCopyToast('Failed to save toggle', true));
    // Refresh the live preview so the change is visible immediately.
    const iframe = document.getElementById('preview-topgifter');
    if (iframe) iframe.src = iframe.src;
  }

  if (coinChk) {
    coinChk.addEventListener('change', () => persist('show_gift_amounts', coinChk.checked));
  }
  if (likeChk) {
    likeChk.addEventListener('change', () => persist('show_like_amounts', likeChk.checked));
  }
}

// Click-to-select overlay URL input
document.addEventListener('click', function(e) {
  if (e.target.classList.contains('overlay-url-input')) {
    e.target.select();
  }
});

// =========================================
// SONG TAB - SPOTIFY INTEGRATION
// =========================================

async function fetchSpotifyStatus() {
  try {
    const res = await fetch('/api/spotify/status');
    const data = await res.json();
    const dot = document.getElementById('spotify-status-dot');
    const text = document.getElementById('spotify-status-text');
    const deviceName = document.getElementById('spotify-device-name');
    const connectBtn = document.getElementById('btn-spotify-connect');
    const disconnectBtn = document.getElementById('btn-spotify-disconnect');
    const activeDeviceNotice = document.getElementById('spotify-active-device-notice');


    spotifyConnected = data.connected;
    if (data.connected) {
      dot.className = 'status-dot online';
      text.textContent = 'Connected';
      deviceName.textContent = data.device ? `Device: ${data.device}` : '';
      connectBtn.style.display = 'none';
      disconnectBtn.style.display = '';
      activeDeviceNotice.style.display = 'none';

    } else if (data.authorized && data.needs_active_device) {
      dot.className = 'status-dot';
      text.textContent = 'Spotify Connected - Device Inactive';
      deviceName.textContent = 'Open Spotify and play any song once';
      connectBtn.style.display = 'none';
      disconnectBtn.style.display = '';
      activeDeviceNotice.style.display = '';
    } else {
      dot.className = 'status-dot';
      text.textContent = data.error || (data.auth_ready === false ? 'Unavailable' : 'Not Connected');
      deviceName.textContent = data.error ? `⚠ ${data.error}` : '';
      connectBtn.style.display = '';
      disconnectBtn.style.display = 'none';
      activeDeviceNotice.style.display = 'none';

    }
  } catch(e) {
    console.warn('Spotify status poll failed', e);
  }
}

async function connectSpotify() {
  try {
    const res = await fetch('/api/spotify/auth-url');
    const data = await res.json();
    if (data.error) {
      showToast(data.error, 'error');
      return;
    }
    // Open popup for OAuth
    const popup = window.open(data.url, 'spotify-auth', 'width=600,height=700');
    // Listen for the postMessage callback
    window.addEventListener('message', function handler(event) {
      if (event.data && event.data.type === 'spotify-connected') {
        showToast('Spotify connected. Now open Spotify and play any song once so the bot can use song commands.', 'info');
        fetchSpotifyStatus();
        window.removeEventListener('message', handler);
      } else if (event.data && event.data.type === 'spotify-error') {
        showToast('Spotify connection failed: ' + event.data.error, 'error');
        fetchSpotifyStatus();
        window.removeEventListener('message', handler);
      }
    });
  } catch(e) {
    showToast('Failed to connect: ' + e.message, 'error');
  }
}

async function disconnectSpotify() {
  try {
    const res = await fetch('/api/spotify/disconnect', { method: 'POST' });
    const data = await res.json();
    if (data.status === 'success') {
      showToast(data.message, 'info');
      fetchSpotifyStatus();
    }
  } catch(e) {
    showToast('Failed to disconnect', 'error');
  }
}

async function loadSongConfig() {
  try {
    const res = await fetch('/api/spotify/config');
    const data = await res.json();
    songConfig = data;

    document.getElementById('song-play-cmd').value = data.play_command || '!play';
    document.getElementById('song-skip-cmd').value = data.skip_command || '!skip';
    document.getElementById('song-revoke-cmd').value = data.revoke_command || '!revoke';
    document.getElementById('song-enabled').checked = data.enabled !== false;
    document.getElementById('song-allow-explicit').checked = data.allow_explicit !== false;
    // Minecraft chat mirror (off by default)
    const mcFb = data.mc_feedback || {};
    document.getElementById('song-mc-feedback').checked = mcFb.enabled === true;
    document.getElementById('song-max-total').value = data.max_queue_total || 10;
    document.getElementById('song-max-user').value = data.max_queue_per_user || 2;

    // Play permissions
    const playPerm = data.play_permission || {};
    document.getElementById('play-perm-everyone').checked = playPerm.everyone !== false;
    document.getElementById('play-perm-followers').checked = playPerm.followers === true;
    document.getElementById('play-perm-friends').checked = playPerm.friends === true;
    document.getElementById('play-perm-superfans').checked = playPerm.superfans === true;
    document.getElementById('play-perm-members').checked = playPerm.members === true;
    document.getElementById('play-perm-mods').checked = playPerm.mods === true;
    document.getElementById('play-perm-vip').checked = playPerm.vip === true;
    document.getElementById('play-perm-whitelist').value = (playPerm.whitelist || []).join('\n');

    // Skip permissions
    const skipPerm = data.skip_permission || {};
    document.getElementById('skip-perm-everyone').checked = skipPerm.everyone === true;
    document.getElementById('skip-perm-followers').checked = skipPerm.followers === true;
    document.getElementById('skip-perm-friends').checked = skipPerm.friends === true;
    document.getElementById('skip-perm-superfans').checked = skipPerm.superfans === true;
    document.getElementById('skip-perm-members').checked = skipPerm.members === true;
    document.getElementById('skip-perm-mods').checked = skipPerm.mods !== false;
    document.getElementById('skip-perm-vip').checked = skipPerm.vip !== false;
    document.getElementById('skip-perm-whitelist').value = (skipPerm.whitelist || []).join('\n');
  } catch(e) {
    console.warn('Failed to load song config:', e);
  }
}

async function saveSongConfig() {
  try {
    const playWhitelist = document.getElementById('play-perm-whitelist').value
      .split('\n').map(s => s.trim()).filter(Boolean);
    const skipWhitelist = document.getElementById('skip-perm-whitelist').value
      .split('\n').map(s => s.trim()).filter(Boolean);

    const data = {
      play_command: document.getElementById('song-play-cmd').value,
      skip_command: document.getElementById('song-skip-cmd').value,
      revoke_command: document.getElementById('song-revoke-cmd').value,
      enabled: document.getElementById('song-enabled').checked,
      allow_explicit: document.getElementById('song-allow-explicit').checked,
      max_queue_total: parseInt(document.getElementById('song-max-total').value) || 10,
      max_queue_per_user: parseInt(document.getElementById('song-max-user').value) || 2,
      play_permission: {
        everyone: document.getElementById('play-perm-everyone').checked,
        followers: document.getElementById('play-perm-followers').checked,
        friends: document.getElementById('play-perm-friends').checked,
        superfans: document.getElementById('play-perm-superfans').checked,
        members: document.getElementById('play-perm-members').checked,
        mods: document.getElementById('play-perm-mods').checked,
        vip: document.getElementById('play-perm-vip').checked,
        whitelist: playWhitelist
      },
      skip_permission: {
        everyone: document.getElementById('skip-perm-everyone').checked,
        followers: document.getElementById('skip-perm-followers').checked,
        friends: document.getElementById('skip-perm-friends').checked,
        superfans: document.getElementById('skip-perm-superfans').checked,
        members: document.getElementById('skip-perm-members').checked,
        mods: document.getElementById('skip-perm-mods').checked,
        vip: document.getElementById('skip-perm-vip').checked,
        whitelist: skipWhitelist
      },
      // Preserve existing mc_feedback sub-toggles (notify_success/errors/denied),
      // only flipping the master switch — the backend replaces whole keys.
      mc_feedback: Object.assign({}, songConfig && songConfig.mc_feedback, {
        enabled: document.getElementById('song-mc-feedback').checked
      })
    };

    const res = await fetch('/api/spotify/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    const result = await res.json();
    showToast(result.message, 'success');
    fetchSpotifyStatus();
  } catch(e) {
    showToast('Error saving config', 'error');
  }
}

async function fetchSongQueue() {
  try {
    const res = await fetch('/api/spotify/queue');
    const queue = await res.json();
    renderSongQueue(queue);
  } catch(e) {}
}

function renderSongQueue(queue) {
  const container = document.getElementById('song-queue-container');
  if (!container) return;
  if (!queue || queue.length === 0) {
    container.innerHTML = '<div class="song-empty"><i class="fa-solid fa-music"></i><span>Queue is empty. Requested songs will appear here.</span></div>';
    return;
  }

  if (document.getElementById('preview-song')) updateOverlayUrl('song');

  container.innerHTML = '';
  queue.forEach((entry, i) => {
    const statusLabels = {
      playing: '<span class="song-status-text"><i class="fa-solid fa-play"></i> Playing</span>',
      queued: '<span class="song-status-text"><i class="fa-solid fa-clock"></i> Queued</span>',
      pushed: '<span class="song-status-text"><i class="fa-solid fa-arrow-up"></i> Pushed</span>',
      played: '<span class="song-status-text" style="color:var(--text-muted);"><i class="fa-solid fa-check"></i> Played</span>',
      skipped: '<span class="song-status-text" style="color:var(--text-muted);"><i class="fa-solid fa-forward"></i> Skipped</span>'
    };

    const row = document.createElement('div');
    row.className = 'song-row';

    const albumImg = entry.album_image
      ? `<img src="${entry.album_image}" alt="" class="song-row-cover">`
      : `<div class="song-row-cover"><i class="fa-solid fa-music"></i></div>`;
    const explicitBadge = entry.explicit ? '<span class="song-explicit">E</span>' : '';

    row.innerHTML = `
      ${albumImg}
      <div style="flex:1;min-width:0;">
        <div class="song-row-title">${esc(entry.track_name)}${explicitBadge}</div>
        <div class="song-row-sub">${esc(entry.artist)} · requested by ${esc(entry.requested_by)}</div>
      </div>
      <div>${statusLabels[entry.status] || ''}</div>
      ${entry.status === 'queued' || entry.status === 'pushed' ? `<button class="btn btn-ghost btn-sm" onclick="removeQueueItem(${i})" title="Remove"><i class="fa-solid fa-xmark"></i></button>` : ''}
    `;
    container.appendChild(row);
  });
}

async function removeQueueItem(index) {
  try {
    const res = await fetch(`/api/spotify/queue/${index + 1}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.status === 'success' || data.success) {
      showToast('Removed from queue', 'info');
      fetchSongQueue();
    }
  } catch(e) {
    showToast('Failed to remove', 'error');
  }
}

async function clearSongQueue() {
  if (!(await window.appConfirm({ title: 'Clear Song Queue', message: 'Clear the entire song queue?', confirmText: 'Clear Queue', tone: 'danger', icon: 'fa-music' }))) return;
  try {
    await fetch('/api/spotify/queue/clear', { method: 'POST' });
    showToast('Queue cleared', 'info');
    fetchSongQueue();
  } catch(e) {
    showToast('Failed to clear queue', 'error');
  }
}

let songHistoryCache = [];
let songHistoryFiltersWired = false;

function renderSongHistory() {
  const container = document.getElementById('song-history-container');
  const count = document.getElementById('song-history-count');
  if (!container) return;

  const options = {
    viewer: document.getElementById('song-history-viewer')?.value || '',
    date: document.getElementById('song-history-date')?.value || '',
    sort: document.getElementById('song-history-sort')?.value || 'newest'
  };
  const filtered = SongHistoryFilters.filterAndSortSongHistory(songHistoryCache, options);
  if (count) count.textContent = `${filtered.length} of ${songHistoryCache.length} songs`;
  if (!filtered.length) {
    container.innerHTML = `<div class="song-empty small"><span>${songHistoryCache.length ? 'No matching songs.' : 'No history yet.'}</span></div>`;
    return;
  }

  const fragment = document.createDocumentFragment();
  filtered.forEach(entry => {
    const playedAt = Number(entry.completed_at || entry.requested_at || 0);
    const playedLabel = playedAt ? new Date(playedAt * 1000).toLocaleString([], {
      year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    }) : 'Date unavailable';
    const div = document.createElement('div');
    div.className = 'song-row';
    div.innerHTML = `
      <div class="song-row-cover" style="width:32px;height:32px;"><i class="fa-solid fa-check"></i></div>
      <div style="flex:1;min-width:0;">
        <div class="song-row-title">${esc(entry.track_name)}</div>
        <div class="song-row-sub">${esc(entry.artist)} · by ${esc(entry.requested_by)}</div>
        <time class="song-history-time">${esc(playedLabel)}</time>
      </div>
    `;
    fragment.appendChild(div);
  });
  container.replaceChildren(fragment);
}

function wireSongHistoryFilters() {
  if (songHistoryFiltersWired) return;
  ['song-history-viewer', 'song-history-date', 'song-history-sort'].forEach(id => {
    const control = document.getElementById(id);
    if (control) control.addEventListener(id === 'song-history-viewer' ? 'input' : 'change', renderSongHistory);
  });
  songHistoryFiltersWired = true;
}

async function fetchSongHistory() {
  try {
    const res = await fetch('/api/spotify/history');
    const history = await res.json();
    songHistoryCache = Array.isArray(history) ? history : [];
    wireSongHistoryFilters();
    renderSongHistory();
  } catch(e) {}
}

async function clearSongHistory() {
  try {
    await fetch('/api/spotify/history/clear', { method: 'POST' });
    showToast('History cleared', 'info');
    fetchSongHistory();
  } catch(e) {
    showToast('Failed to clear history', 'error');
  }
}

async function testSongSearch() {
  const query = document.getElementById('song-test-search').value.trim();
  if (!query) return;
  const container = document.getElementById('song-test-results');
  container.innerHTML = '<div class="song-empty small"><span>Searching...</span></div>';
  try {
    const res = await fetch('/api/spotify/search?q=' + encodeURIComponent(query));
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.error) {
      const msg = typeof payload.error === 'string'
        ? payload.error
        : (payload.error?.message || payload.message || `Spotify search failed (${res.status})`);
      container.innerHTML = `<div class="song-empty small" style="color:var(--danger);"><span>${esc(msg)}</span></div>`;
      showToast(msg, 'error');
      return;
    }
    const results = Array.isArray(payload) ? payload : [];
    if (results.length === 0) {
      container.innerHTML = '<div class="song-empty small"><span>No results found.</span></div>';
      return;
    }
    container.innerHTML = '';
    results.forEach(track => {
      const div = document.createElement('div');
      div.className = 'song-row';
      div.style.cursor = 'pointer';
      div.onclick = () => testQueueTrack(track);

      const albumImg = track.album_image
        ? `<img src="${track.album_image}" alt="" class="song-row-cover">`
        : `<div class="song-row-cover"><i class="fa-solid fa-music"></i></div>`;
      const explicit = track.explicit ? '<span class="song-explicit">E</span>' : '';

      div.innerHTML = `
        ${albumImg}
        <div style="flex:1;min-width:0;">
          <div class="song-row-title">${esc(track.name)}${explicit}</div>
          <div class="song-row-sub">${esc(track.artists)}</div>
        </div>
      `;
      const btn = document.createElement('button');
      btn.className = 'btn btn-primary btn-sm';
      btn.innerHTML = '<i class="fa-solid fa-plus"></i> Queue';
      btn.onclick = (event) => { event.stopPropagation(); testQueueTrack(track); };
      div.appendChild(btn);
      container.appendChild(div);
    });
  } catch(e) {
    container.innerHTML = `<div class="song-empty small" style="color:var(--danger);"><span>${esc(e.message || 'Search failed')}</span></div>`;
    showToast(e.message || 'Search failed', 'error');
  }
}

async function testQueueTrack(track) {
  try {
    const res = await fetch('/api/spotify/queue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(track)
    });
    const data = await res.json();
    if (data.error) {
      showToast(data.error, 'error');
    } else {
      showToast(`Queued: ${track.name}`, 'success');
      fetchSongQueue();
    }
  } catch(e) {
    showToast('Failed to queue', 'error');
  }
}

// ==========================================
// TTS CONFIG
// ==========================================
let _ttsVoices = [];

async function loadTtsConfig() {
  try {
    const res = await fetch('/api/tts/config');
    const cfg = await res.json();
    document.getElementById('tts-enabled').checked = cfg.enabled !== false;
    document.getElementById('tts-command').value = cfg.command || '.';
    document.getElementById('tts-max-length').value = cfg.max_length || 200;
    document.getElementById('tts-global-cd').value = cfg.global_cooldown || 2;
    document.getElementById('tts-user-cd').value = cfg.per_user_cooldown || 10;
    document.getElementById('tts-member-min').value = cfg.member_min_level || 0;

    // Voice
    const voiceSelect = document.getElementById('tts-voice');
    if (_ttsVoices.length === 0) await loadTtsVoices();
    voiceSelect.innerHTML = _ttsVoices.map(v =>
      `<option value="${v.ShortName}" ${v.ShortName === cfg.voice ? 'selected' : ''}>${v.FriendlyName} (${v.Locale})</option>`
    ).join('');

    // Speed
    const speed = cfg.speed || '+0%';
    const speedVal = parseInt(speed) || 0;
    document.getElementById('tts-speed').value = speedVal;
    document.getElementById('tts-speed-val').textContent = speed;

    // Pitch
    const pitch = cfg.pitch || '+0Hz';
    const pitchVal = parseInt(pitch) || 0;
    document.getElementById('tts-pitch').value = pitchVal;
    document.getElementById('tts-pitch-val').textContent = pitch;

    // Permissions
    const p = cfg.permission || {};
    document.getElementById('tts-perm-everyone').checked = p.everyone !== false;
    document.getElementById('tts-perm-followers').checked = !!p.followers;
    document.getElementById('tts-perm-friends').checked = !!p.friends;
    document.getElementById('tts-perm-superfans').checked = !!p.superfans;
    document.getElementById('tts-perm-members').checked = !!p.members;
    document.getElementById('tts-perm-vip').checked = !!p.vip;
    document.getElementById('tts-perm-mods').checked = !!p.mods;
    document.getElementById('tts-whitelist').value = (p.whitelist || []).join('\n');
  } catch(e) {
    console.error('Failed to load TTS config:', e);
  }
}

async function loadTtsVoices() {
  try {
    const res = await fetch('/api/tts/voices');
    _ttsVoices = await res.json();
  } catch(e) {
    _ttsVoices = [{ ShortName: 'en-US-AriaNeural', FriendlyName: 'Aria (US)', Locale: 'en-US' }];
  }
}

async function saveTtsConfig(options = {}) {
  const cfg = {
    enabled: document.getElementById('tts-enabled').checked,
    command: document.getElementById('tts-command').value || '.',
    voice: document.getElementById('tts-voice').value || 'en-US-AriaNeural',
    speed: (document.getElementById('tts-speed').value > 0 ? '+' : '') + document.getElementById('tts-speed').value + '%',
    pitch: (document.getElementById('tts-pitch').value > 0 ? '+' : '') + document.getElementById('tts-pitch').value + 'Hz',
    max_length: parseInt(document.getElementById('tts-max-length').value) || 200,
    global_cooldown: parseFloat(document.getElementById('tts-global-cd').value) || 2,
    per_user_cooldown: parseInt(document.getElementById('tts-user-cd').value) || 10,
    member_min_level: parseInt(document.getElementById('tts-member-min').value) || 0,
    permission: {
      everyone: document.getElementById('tts-perm-everyone').checked,
      followers: document.getElementById('tts-perm-followers').checked,
      friends: document.getElementById('tts-perm-friends').checked,
      superfans: document.getElementById('tts-perm-superfans').checked,
      members: document.getElementById('tts-perm-members').checked,
      vip: document.getElementById('tts-perm-vip').checked,
      mods: document.getElementById('tts-perm-mods').checked,
      whitelist: (document.getElementById('tts-whitelist').value || '').split('\n').map(s => s.trim().replace(/^@+/, '').toLowerCase()).filter(Boolean)
    }
  };
  try {
    const res = await fetch('/api/tts/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg)
    });
    const result = await res.json().catch(() => ({}));
    if (!res.ok || result.status === 'error') throw new Error(result.message || 'Save failed');
    document.getElementById('tts-whitelist').value = (cfg.permission.whitelist || []).join('\n');
    if (options.showToast) showToast('TTS config saved', 'success');
  } catch(e) {
    console.error('Failed to save TTS config:', e);
    showToast('Failed to save TTS config', 'error');
  }
}

async function testTts() {
  const raw = document.getElementById('tts-test-input').value.trim();
  if (!raw) return;

  // Parse effect tag (e.g. "*whisper* hello" → effect="whisper", text="hello")
  const effectMatch = raw.match(/^[\s]*[*[{(](whisper|yell|shout|scream|quiet|loud|whisp)[*}\])]\s*/i);
  const aliases = { whisper:'whisper', whisp:'whisper', quiet:'whisper', yell:'yell', shout:'yell', scream:'yell', loud:'yell' };
  let effect = 'normal';
  let text = raw;
  if (effectMatch) {
    const tag = effectMatch[1].toLowerCase();
    if (aliases[tag] && raw.slice(effectMatch[0].length).trim()) {
      effect = aliases[tag];
      text = raw.slice(effectMatch[0].length).trim();
    }
  }

  try {
    await fetch('/api/tts/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, nick: 'Dashboard Test', _test: true, effect })
    });
    showToast(effect !== 'normal' ? `TTS [${effect}] sent!` : 'TTS sent!', 'success');
  } catch(e) {
    showToast('TTS failed', 'error');
  }
}

// ── TTS History ──────────────────────────────────────────────────
async function fetchTtsHistory() {
  try {
    const r = await fetch('/api/tts/history');
    const data = await r.json();
    renderTtsHistory(data);
  } catch(e) {
    console.error('Failed to fetch TTS history:', e);
  }
}

function renderTtsHistory(entries) {
  const el = document.getElementById('tts-history-list');
  if (!el) return;
  if (!entries || !entries.length) {
    el.innerHTML = '<div class="tts-history-empty">No TTS history yet</div>';
    return;
  }
  // Show newest first
  const sorted = [...entries].reverse().slice(0, 100);
  el.innerHTML = sorted.map(e => {
    const initial = (e.nick || e.user || '?')[0].toUpperCase();
    const ts = e.timestamp ? new Date(e.timestamp * 1000) : new Date();
    const timeStr = ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const dateStr = ts.toLocaleDateString([], { month: 'short', day: 'numeric' });
    const text = (e.text || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const nick = (e.nick || e.user || 'unknown').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const effect = e.effect || 'normal';
    const effectBadge = effect !== 'normal' ? ` <span style="font-size:10px;padding:1px 5px;border-radius:3px;background:${effect==='whisper'?'rgba(100,150,255,.15)':'rgba(255,100,100,.15)'};color:${effect==='whisper'?'#6496ff':'#ff6464'};">${effect}</span>` : '';
    return `<div class="tts-history-item">
      <div class="tts-history-avatar">${initial}</div>
      <div class="tts-history-content">
        <div class="tts-history-meta">
          <span class="tts-history-user">${nick}${effectBadge}</span>
          <span class="tts-history-time">${dateStr} ${timeStr}</span>
        </div>
        <div class="tts-history-text">${text}</div>
      </div>
    </div>`;
  }).join('');
}

async function clearTtsHistory() {
  if (!(await window.appConfirm({ title: 'Clear TTS History', message: 'Clear all TTS history?', confirmText: 'Clear History', tone: 'danger', icon: 'fa-comment-dots' }))) return;
  try {
    await fetch('/api/tts/history/clear', { method: 'POST' });
    showToast('History cleared', 'success');
    fetchTtsHistory();
  } catch(e) {
    showToast('Failed to clear history', 'error');
  }
}

// Auto-fetch TTS history on load
document.addEventListener('DOMContentLoaded', () => {
  // Only fetch if TTS panel exists (we're on dashboard)
  if (document.getElementById('panel-tts')) {
    fetchTtsHistory();
    // Refresh history every 10 seconds
    setInterval(fetchTtsHistory, 10000);
  }
});


// ==========================================
// SIMULATE COMMANDS (Debug)
// ==========================================
function _simStatus(msg, type) {
  const el = document.getElementById('sim-status');
  if (!el) return;
  const colors = { success: '#1DB954', error: '#ef4444', info: '#64748b' };
  el.style.color = colors[type] || colors.info;
  el.textContent = msg;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.textContent = ''; }, 4000);
}

async function simPlay() {
  const nick = (document.getElementById('sim-nick')?.value || 'testuser').trim();
  const query = (document.getElementById('sim-query')?.value || '').trim();
  if (!query) { _simStatus('Enter a song query', 'error'); return; }
  _simStatus('Simulating !play...', 'info');
  try {
    const res = await fetch('/api/spotify/simulate/play', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nick, query })
    });
    const data = await res.json();
    if (data.feedback_pushed) {
      _simStatus(`✓ Feedback pushed for @${nick} — check overlay!`, 'success');
      fetchSongQueue();
    } else {
      _simStatus(data.error || 'Failed', 'error');
    }
  } catch(e) {
    _simStatus('Error: ' + e.message, 'error');
  }
}

async function simSkip() {
  const nick = (document.getElementById('sim-nick')?.value || 'testuser').trim();
  _simStatus('Simulating !skip...', 'info');
  try {
    const res = await fetch('/api/spotify/simulate/skip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nick })
    });
    const data = await res.json();
    if (data.feedback_pushed) {
      _simStatus(`✓ Skip feedback pushed for @${nick} — check overlay!`, 'success');
    } else {
      _simStatus(data.error || 'Failed', 'error');
    }
  } catch(e) {
    _simStatus('Error: ' + e.message, 'error');
  }
}

async function simPull() {
  const nick = (document.getElementById('sim-nick')?.value || 'testuser').trim();
  _simStatus('Simulating !pull...', 'info');
  try {
    const res = await fetch('/api/spotify/simulate/pull', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nick })
    });
    const data = await res.json();
    if (data.feedback_pushed) {
      _simStatus(`✓ Pull feedback pushed for @${nick} — check overlay!`, 'success');
      fetchSongQueue();
    } else {
      _simStatus(data.error || 'No pending request', 'error');
    }
  } catch(e) {
    _simStatus('Error: ' + e.message, 'error');
  }
}

// ==========================================
// VIEWER POINTS TAB (SQLite-backed long-term DB)
// ==========================================
let pointsOffset = 0;
const POINTS_PAGE_SIZE = 50;
let pointsTimer = null;

function _pointsTimeAgo(ts) {
  if (!ts) return '—';
  const diff = Math.max(0, Date.now() / 1000 - ts);
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  if (diff < 86400 * 30) return Math.floor(diff / 86400) + 'd ago';
  const d = new Date(ts * 1000);
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

async function loadPoints() {
  const q = (document.getElementById('points-search')?.value || '').trim();
  const sort = document.getElementById('points-sort')?.value || 'coins';
  const period = document.getElementById('points-period')?.value || 'all';
  const start = document.getElementById('points-start-date')?.value || '';
  const end = document.getElementById('points-end-date')?.value || '';
  const bounds = getPointsPeriodBounds(period, start, end);
  if (bounds.error) {
    showToast(bounds.error, 'error');
    return;
  }
  try {
    const params = new URLSearchParams({ limit: POINTS_PAGE_SIZE, offset: pointsOffset, sort, q });
    if (bounds.since !== null) params.set('since', bounds.since);
    if (bounds.until !== null) params.set('until', bounds.until);
    const res = await fetch('/api/points/viewers?' + params, { cache: 'no-store' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to load points');
    document.getElementById('points-period-label').textContent = bounds.label;
    renderPoints(data);
  } catch (e) {
    console.error('points load failed', e);
    showToast(e.message || 'Failed to load points', 'error');
  }
}

function renderPoints(data) {
  const tbody = document.getElementById('points-tbody');
  const empty = document.getElementById('points-empty');
  const viewers = data.viewers || [];

  document.getElementById('points-total-viewers').textContent = (data.total_viewers ?? data.total ?? 0).toLocaleString();
  document.getElementById('points-total-coins').textContent = (data.total_coins ?? 0).toLocaleString();
  document.getElementById('points-total-gifts').textContent = (data.total_gifts ?? 0).toLocaleString();

  if (!viewers.length) {
    tbody.innerHTML = '';
    empty.style.display = '';
  } else {
    empty.style.display = 'none';
    tbody.innerHTML = viewers.map((v, i) => {
      const rank = pointsOffset + i + 1;
      const nick = v.nickname || v.username || 'Anonymous';
      const uname = v.username ? '@' + v.username : '';
      const avatar = v.avatar_url
        ? `<img class="points-avatar" src="${escHtml(v.avatar_url)}" loading="lazy" onerror="this.outerHTML='<span class=points-avatar-fallback>${escHtml((nick[0] || '?').toUpperCase())}</span>'">`
        : `<span class="points-avatar-fallback">${escHtml((nick[0] || '?').toUpperCase())}</span>`;
      return `<tr class="points-row" data-user-id="${escHtml(v.user_id)}" tabindex="0" role="button" title="Click to view / adjust coins">
        <td class="col-avatar">${rank}</td>
        <td><div class="points-viewer-cell">${avatar}<div style="min-width:0;"><div class="points-nick" title="${escHtml(nick)}">${escHtml(nick)}</div></div></div></td>
        <td class="points-username" title="${escHtml(uname)}">${escHtml(uname)}</td>
        <td class="col-num coins-cell">${(v.total_coins || 0).toLocaleString()}</td>
        <td class="col-num">${(v.gift_count || 0).toLocaleString()}</td>
        <td class="col-activity">${_pointsTimeAgo(v.last_gift_ts)}</td>
      </tr>`;
    }).join('');
  }

  const total = data.total || 0;
  const pages = Math.max(1, Math.ceil(total / POINTS_PAGE_SIZE));
  const page = Math.floor(pointsOffset / POINTS_PAGE_SIZE) + 1;
  document.getElementById('points-page-info').textContent = total ? `Page ${page} / ${pages}` : '—';
  document.getElementById('points-prev').disabled = pointsOffset <= 0;
  document.getElementById('points-next').disabled = pointsOffset + POINTS_PAGE_SIZE >= total;
}

function _bindPointsControls() {
  const search = document.getElementById('points-search');
  const sort = document.getElementById('points-sort');
  const period = document.getElementById('points-period');
  const customRange = document.getElementById('points-custom-range');
  const start = document.getElementById('points-start-date');
  const end = document.getElementById('points-end-date');
  if (!search || search.dataset.bound) return;
  search.dataset.bound = '1';
  let debounce = null;
  search.addEventListener('input', () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => { pointsOffset = 0; loadPoints(); }, 250);
  });
  sort.addEventListener('change', () => { pointsOffset = 0; loadPoints(); });
  period.addEventListener('change', () => {
    const custom = period.value === 'custom';
    customRange.hidden = !custom;
    if (custom) {
      const today = new Date();
      const localToday = new Date(today.getTime() - today.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
      if (!end.value) end.value = localToday;
      if (!start.value) {
        const weekAgo = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 6);
        start.value = new Date(weekAgo.getTime() - weekAgo.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
      }
      return;
    }
    pointsOffset = 0;
    loadPoints();
  });
  document.getElementById('points-apply-period').addEventListener('click', () => {
    pointsOffset = 0;
    loadPoints();
  });
  document.getElementById('points-prev').addEventListener('click', () => {
    pointsOffset = Math.max(0, pointsOffset - POINTS_PAGE_SIZE);
    loadPoints();
  });
  document.getElementById('points-next').addEventListener('click', () => {
    pointsOffset += POINTS_PAGE_SIZE;
    loadPoints();
  });

  // Row click / keyboard opens the per-viewer coin editor. Delegated so it
  // survives every table re-render from polling.
  const tbody = document.getElementById('points-tbody');
  if (tbody) {
    tbody.addEventListener('click', (e) => {
      const row = e.target.closest('tr.points-row');
      if (row && row.dataset.userId) openPointsViewerModal(row.dataset.userId);
    });
    tbody.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const row = e.target.closest('tr.points-row');
      if (!row || !row.dataset.userId) return;
      e.preventDefault();
      openPointsViewerModal(row.dataset.userId);
    });
  }

  const amount = document.getElementById('pv-adjust-amount');
  if (amount) {
    amount.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); adjustViewerCoins('add'); }
    });
  }
}

// ===== PER-VIEWER COIN EDITOR MODAL =====
// Manual recovery path: gifts can be lost when the app crashes or the TikTok
// connection drops, so the operator can set/add/remove a viewer's coins.
let pointsViewerId = null;

function _pvDate(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function _pvDateTime(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
  });
}

async function openPointsViewerModal(userId) {
  pointsViewerId = String(userId);
  const modal = document.getElementById('points-viewer-modal');
  document.getElementById('pv-adjust-amount').value = '';
  document.getElementById('pv-adjust-note').value = '';
  document.getElementById('pv-history').innerHTML = '<div class="pv-history-empty">Loading…</div>';
  if (modal) modal.classList.add('active');
  try {
    const res = await fetch('/api/points/viewer?id=' + encodeURIComponent(pointsViewerId), { cache: 'no-store' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to load viewer');
    renderPointsViewer(data);
  } catch (e) {
    document.getElementById('pv-history').innerHTML =
      `<div class="pv-history-empty">${escHtml(e.message || 'Failed to load viewer')}</div>`;
    showToast(e.message || 'Failed to load viewer', 'error');
  }
}

function closePointsViewerModal() {
  const modal = document.getElementById('points-viewer-modal');
  if (modal) modal.classList.remove('active');
  pointsViewerId = null;
}

function renderPointsViewer(data) {
  const v = data.viewer || {};
  const nick = v.nickname || v.username || 'Anonymous';
  const initial = escHtml((nick[0] || '?').toUpperCase());
  document.getElementById('pv-avatar').innerHTML = v.avatar_url
    ? `<img class="points-avatar" src="${escHtml(v.avatar_url)}" loading="lazy" onerror="this.outerHTML='<span class=points-avatar-fallback>${initial}</span>'">`
    : `<span class="points-avatar-fallback">${initial}</span>`;
  document.getElementById('pv-nick').textContent = nick;
  document.getElementById('pv-username').textContent = v.username ? '@' + v.username : '';
  document.getElementById('pv-userid').textContent = v.user_id ? 'ID ' + v.user_id : '';
  document.getElementById('pv-coins').textContent = (v.total_coins || 0).toLocaleString();
  document.getElementById('pv-gifts').textContent = (v.gift_count || 0).toLocaleString();
  document.getElementById('pv-first-seen').textContent = _pvDate(v.first_seen);
  document.getElementById('pv-last-gift').textContent = _pointsTimeAgo(v.last_gift_ts);

  const history = data.history || [];
  const box = document.getElementById('pv-history');
  if (!history.length) {
    box.innerHTML = '<div class="pv-history-empty">No gift history recorded.</div>';
    return;
  }
  box.innerHTML = history.map(h => {
    const manual = h.kind === 'manual';
    const coins = Number(h.coins || 0);
    const sign = coins > 0 ? '+' : '';
    return `<div class="pv-history-row${manual ? ' is-manual' : ''}">
      <span class="pv-history-icon"><i class="fa-solid ${manual ? 'fa-pen' : 'fa-gift'}"></i></span>
      <span class="pv-history-name" title="${escHtml(h.gift_name || '')}">${escHtml(h.gift_name || (manual ? 'Manual adjustment' : 'Gift'))}</span>
      <span class="pv-history-coins${coins < 0 ? ' is-negative' : ''}">${sign}${coins.toLocaleString()}</span>
      <span class="pv-history-time">${_pvDateTime(h.ts)}</span>
    </div>`;
  }).join('');
}

async function adjustViewerCoins(operation) {
  if (!pointsViewerId) return;
  const amountEl = document.getElementById('pv-adjust-amount');
  const raw = (amountEl.value || '').trim();
  if (raw === '') { showToast('Enter a coin amount', 'error'); return; }
  const amount = Number(raw);
  if (!Number.isFinite(amount) || amount < 0 || !Number.isInteger(amount)) {
    showToast('Coins must be a whole number of 0 or more', 'error');
    return;
  }
  try {
    const res = await fetch('/api/points/viewer/adjust', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: pointsViewerId,
        operation,
        amount,
        note: (document.getElementById('pv-adjust-note').value || '').trim()
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Adjustment failed');
    renderPointsViewer(data);
    amountEl.value = '';
    document.getElementById('pv-adjust-note').value = '';
    const delta = Number(data.applied_delta || 0);
    showToast(
      delta === 0
        ? 'Already at that total — nothing changed'
        : `${delta > 0 ? 'Added' : 'Removed'} ${Math.abs(delta).toLocaleString()} coins — now ${(data.total_coins || 0).toLocaleString()}`,
      'success'
    );
    loadPoints();
  } catch (e) {
    showToast(e.message || 'Adjustment failed', 'error');
  }
}

// Refresh "last activity" + totals while the panel is visible.
setInterval(() => {
  const panel = document.getElementById('panel-points');
  if (panel && panel.classList.contains('active')) loadPoints();
}, 15000);

document.addEventListener('DOMContentLoaded', _bindPointsControls);

// ==========================================
// GIFT ROULETTE PANEL
// ==========================================
let rouletteConfig = null;
let roulettePool = [];          // array of gift_id strings, ordered
let rouletteConfiguredGifts = []; // resolved entries from /api/roulette/config

function rouletteDisplayName(giftId) {
  const entry = rouletteConfiguredGifts.find(e => e.gift_id === giftId);
  if (entry) return entry.label;
  return getGiftDisplayName(giftId);
}

function rouletteIcon(giftId) {
  const entry = rouletteConfiguredGifts.find(e => e.gift_id === giftId);
  return (entry && entry.icon_url) || giftIconMap[giftId] || '';
}

function renderRoulettePool() {
  const list = document.getElementById('roulette-pool-list');
  if (!list) return;
  list.innerHTML = '';
  roulettePool.forEach((giftId, idx) => {
    const row = document.createElement('div');
    row.className = 'roulette-pool-row';
    const icon = rouletteIcon(giftId);
    const img = document.createElement('img');
    if (icon) { img.src = icon; img.alt = ''; } else { img.style.visibility = 'hidden'; }
    const name = document.createElement('span');
    name.className = 'roulette-pool-name';
    name.textContent = rouletteDisplayName(giftId);
    const id = document.createElement('span');
    id.className = 'roulette-pool-id';
    id.textContent = '#' + giftId;
    const up = document.createElement('button');
    up.className = 'btn btn-ghost btn-sm'; up.innerHTML = '<i class="fa-solid fa-arrow-up"></i>';
    up.disabled = idx === 0;
    up.onclick = () => { [roulettePool[idx-1], roulettePool[idx]] = [roulettePool[idx], roulettePool[idx-1]]; renderRoulettePool(); saveRouletteConfig(); };
    const down = document.createElement('button');
    down.className = 'btn btn-ghost btn-sm'; down.innerHTML = '<i class="fa-solid fa-arrow-down"></i>';
    down.disabled = idx === roulettePool.length - 1;
    down.onclick = () => { [roulettePool[idx+1], roulettePool[idx]] = [roulettePool[idx], roulettePool[idx+1]]; renderRoulettePool(); saveRouletteConfig(); };
    const rm = document.createElement('button');
    rm.className = 'btn btn-danger btn-sm'; rm.innerHTML = '&times;';
    rm.onclick = () => { roulettePool.splice(idx, 1); renderRoulettePool(); fillRouletteAddSelect(); saveRouletteConfig(); };
    row.appendChild(img); row.appendChild(name); row.appendChild(id);
    const btns = document.createElement('span');
    btns.className = 'roulette-pool-btns';
    btns.appendChild(up); btns.appendChild(down); btns.appendChild(rm);
    row.appendChild(btns);
    list.appendChild(row);
  });
  const count = document.getElementById('roulette-pool-count');
  if (count) count.textContent = roulettePool.length + ' events';
}

function fillRouletteAddSelect() {
  const sel = document.getElementById('roulette-add-select');
  if (!sel) return;
  const current = sel.value;
  sel.innerHTML = '<option value="">Add configured gift…</option>';
  // All configured gifts (currentConfig.Gifts) except GlobalActions/empties.
  const gifts = (currentConfig && currentConfig.Gifts) || {};
  Object.keys(gifts).forEach(gid => {
    if (gid === 'GlobalActions') return;
    const actions = gifts[gid];
    if (!Array.isArray(actions) || actions.length === 0) return;
    if (roulettePool.includes(gid)) return;
    const opt = document.createElement('option');
    opt.value = gid;
    opt.textContent = `${rouletteDisplayName(gid)} (#${gid})`;
    sel.appendChild(opt);
  });
  sel.value = current;
  if (!sel.value) sel.value = '';
}

async function initRoulettePanel() {
  try {
    const res = await fetch('/api/roulette/config', { cache: 'no-store' });
    const body = await res.json();
    rouletteConfig = body.roulette || null;
    rouletteConfiguredGifts = body.resolved_entries || [];
    if (rouletteConfig) {
      roulettePool = [...(rouletteConfig.pool || [])];
      const en = document.getElementById('roulette-enabled');
      if (en) en.checked = !!rouletteConfig.enabled;
      const spin = document.getElementById('roulette-spin-ms');
      const hold = document.getElementById('roulette-hold-ms');
      const cd = document.getElementById('roulette-cooldown-ms');
      if (spin) spin.value = Math.round((rouletteConfig.spin_ms || 5000) / 1000);
      if (hold) hold.value = Math.round((rouletteConfig.hold_ms || 4000) / 1000);
      if (cd) cd.value = Math.round((rouletteConfig.cooldown_ms || 2000) / 1000);
    }
    renderRoulettePool();
    fillRouletteAddSelect();
    renderRouletteWarnings(body.warnings || []);
    bindRouletteAutosave();
  } catch (e) {
    showToast('Failed to load Roulette config', 'error');
  }
}

// One-time bindings: enable + timing inputs persist themselves. Guarded by a
// flag because initRoulettePanel re-runs (programmatic .value sets don't fire
// these listeners, so no save loops).
let rouletteAutosaveBound = false;
function bindRouletteAutosave() {
  if (rouletteAutosaveBound) return;
  rouletteAutosaveBound = true;
  const en = document.getElementById('roulette-enabled');
  // Toggle feels instant: skip the debounce.
  if (en) en.addEventListener('change', () => saveRouletteConfig(true));
  ['roulette-spin-ms', 'roulette-hold-ms', 'roulette-cooldown-ms'].forEach(id => {
    const input = document.getElementById(id);
    // Typing debounces 600ms; stepper arrows commit immediately.
    if (input) {
      input.addEventListener('input', () => saveRouletteConfig());
      input.addEventListener('change', () => saveRouletteConfig(true));
    }
  });
}

function renderRouletteWarnings(warnings) {
  const box = document.getElementById('roulette-warnings');
  if (!box) return;
  box.innerHTML = '';
  (warnings || []).forEach(w => {
    const div = document.createElement('div');
    div.className = 'roulette-warning';
    div.textContent = w;
    box.appendChild(div);
  });
}

// ── Roulette autosave ──
// Every control persists itself (debounced) — there is no Save button.
// Each save PUTs the full Roulette block assembled from current UI state,
// shows a quiet "Saved ✓" / warning in the status line, and applies live
// via the server hot-reload signal. Failures restore the last-known-good
// checkbox state and surface an error toast; nothing is ever discarded.
let rouletteSaveTimer = null;
let rouletteSaving = false;

function rouletteCollectPayload() {
  const en = document.getElementById('roulette-enabled');
  const spin = document.getElementById('roulette-spin-ms');
  const hold = document.getElementById('roulette-hold-ms');
  const cd = document.getElementById('roulette-cooldown-ms');
  return {
    enabled: !!(en && en.checked),
    spin_ms: Math.round(parseFloat(spin ? spin.value : '5') * 1000),
    hold_ms: Math.round(parseFloat(hold ? hold.value : '4') * 1000),
    cooldown_ms: Math.round(parseFloat(cd ? cd.value : '2') * 1000),
    pool: [...roulettePool],
  };
}

function rouletteSaveState(text, kind) {
  const status = document.getElementById('roulette-save-state');
  if (!status) return;
  status.textContent = text;
  status.dataset.state = kind || '';
}

async function saveRouletteConfig(immediate) {
  // immediate=true skips the debounce (enable toggle feels instant).
  if (rouletteSaveTimer) { clearTimeout(rouletteSaveTimer); rouletteSaveTimer = null; }
  if (!immediate) {
    rouletteSaveState('Editing…', 'editing');
    rouletteSaveTimer = setTimeout(() => saveRouletteConfig(true), 600);
    return;
  }
  if (rouletteSaving) {  // coalesce bursts; the latest state always wins
    rouletteSaveTimer = setTimeout(() => saveRouletteConfig(true), 600);
    return;
  }
  rouletteSaving = true;
  rouletteSaveState('Saving…', 'saving');
  try {
    const res = await fetch('/api/roulette/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(rouletteCollectPayload()),
    });
    const body = await res.json();
    if (!res.ok) { showToast(body.message || 'Save failed', 'error'); rouletteSaveState('Save failed — retrying on next change', 'error'); return; }
    if (body.roulette) {
      rouletteConfig = body.roulette;
      roulettePool = [...(body.roulette.pool || [])];
      renderRoulettePool();
    }
    renderRouletteWarnings(body.warnings || []);
    if (body.warnings && body.warnings.length) {
      showToast('Saved, but roulette left disabled: ' + body.warnings[0], 'warning');
      const en = document.getElementById('roulette-enabled');
      if (en) en.checked = false;
      rouletteSaveState('Saved ✓ (disabled — ' + body.warnings[0] + ')', 'warn');
    } else {
      rouletteSaveState(
        'Saved ✓ ' + (body.roulette && body.roulette.enabled ? '(live)' : '(disabled)'), 'ok'
      );
    }
  } catch (e) {
    showToast('Save failed', 'error');
    rouletteSaveState('Save failed — retrying on next change', 'error');
  } finally {
    rouletteSaving = false;
  }
}

async function testRouletteSpin() {
  const status = document.getElementById('roulette-status');
  try {
    const res = await fetch('/api/roulette/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user: 'TestViewer' }),
    });
    const body = await res.json();
    const now = Date.now() / 1000;
    const spinMs = Number(body.spin_ms) || 5000;
    const holdMs = Number(body.hold_ms) || 4000;

    if (status) {
      if (!res.ok) {
        status.textContent = body.message || 'Test spin failed';
      } else if (body.queued) {
        status.textContent = `Test spin queued (#${body.queue_depth}) — winner will be "${body.winner}" after the current spin.`;
      } else {
        status.textContent = `Test spin accepted — winner will be "${body.winner}" (lands in ~${Math.max(0, Math.round((body.lands_at || now) - now))}s). Watch /overlay/roulette.`;
      }
    }
    if (!res.ok) showToast(body.message || 'Test spin failed', 'error');
    else {
      // Mirror the spin audio in the dashboard: the overlay iframe's context
      // stays suspended (no gesture inside the frame), but the Test Spin click
      // unlocked THIS context.
      // A QUEUED spin must NOT play on top of the spin still on screen: space
      // its roll after the current spin's roll + reveal window. The server
      // starts the next spin right after the previous hide_at, so that is the
      // right moment to start this one's audio too.
      if (body.queued) {
        const startAt = Math.max(now, rouletteMirrorFreeAt);
        rouletteMirrorFreeAt = startAt + (spinMs + holdMs) / 1000;
        scheduleRouletteTestSpinAudio((startAt - now) * 1000, spinMs);
        showToast(`Test spin queued (#${body.queue_depth})`, 'success');
      } else {
        const landsAt = Number(body.lands_at) || (now + spinMs / 1000);
        rouletteMirrorFreeAt = Number(body.hide_at) || (landsAt + holdMs / 1000);
        scheduleRouletteTestSpinAudio(0, Math.max(0, (landsAt - now) * 1000));
        showToast('Test spin started: ' + body.winner, 'success');
      }
    }
  } catch (e) {
    showToast('Test spin failed', 'error');
  }
}

// ── Slot synth (shared by preview + test-spin mirror; same recipe as overlay) ──
function rouletteTickAt(ctx, t) {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = 'square';
  osc.frequency.setValueAtTime(1900 + Math.random() * 500, t);
  gain.gain.setValueAtTime(0.06, t);
  gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.045);
  osc.connect(gain).connect(ctx.destination);
  osc.start(t); osc.stop(t + 0.05);
}

function rouletteChimeAt(ctx, t0) {
  [[523.25, 0.0, 0.14], [783.99, 0.09, 0.16], [1046.5, 0.18, 0.22]].forEach(([freq, dt, dur]) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'triangle';
    osc.frequency.setValueAtTime(freq, t0 + dt);
    gain.gain.setValueAtTime(0.0001, t0 + dt);
    gain.gain.exponentialRampToValueAtTime(0.12, t0 + dt + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + dt + dur);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t0 + dt); osc.stop(t0 + dt + dur + 0.05);
  });
}

// Schedules decelerating ticks spanning totalMs, then the land chime.
// Fixed absolute rhythm (not a fixed tick count): opens at ~70ms rat-a-tat
// and grows ~12% per tick, so EVERY spin starts punchy like the 2s one and
// only the tail stretches. Longer spins get MORE ticks, never lazier ones.
// Returns the end offset (seconds) so callers can close the context.
function rouletteRollSynth(ctx, tStart, totalMs) {
  const end = tStart + totalMs / 1000;
  let t = tStart;
  let gap = 0.07;
  let ticks = 0;
  for (;;) {
    rouletteTickAt(ctx, t);
    ticks++;
    t += gap;
    gap *= 1.12;
    if (t >= end || ticks > 200) break;
  }
  const tLand = end + 0.12;
  rouletteChimeAt(ctx, tLand);
  return (tLand - tStart) + 0.8;
}

// ── Slot sound preview (same synth as the overlay) ──
function playRouletteSoundPreview() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) { showToast('Web Audio not available', 'error'); return; }
  const ctx = new AC();
  const play = () => {
    // Fixed ~1.5s demo roll with the same tension curve as a real spin.
    const endOffset = rouletteRollSynth(ctx, ctx.currentTime, 1500);
    setTimeout(() => ctx.close(), endOffset * 1000);
  };
  // Click on the button IS a user gesture — resume then play.
  if (ctx.state === 'suspended') ctx.resume().then(play); else play();
}

// ── Test-spin audio mirror ──
// The overlay iframe never receives a click, so its AudioContext stays
// suspended in a browser tab (OBS allows autoplay — stream audio is fine).
// Mirror the spin audio here in the dashboard: the click on Test Spin IS the
// gesture that unlocked THIS context.
// ONE shared context: browsers cap how many AudioContexts a page may hold, and
// a fresh context per click leaked one per Test Spin.
let rouletteMirrorCtx = null;
let rouletteMirrorFreeAt = 0;   // epoch seconds when the mirrored audio frees up

function rouletteMirrorContext() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return null;
  if (!rouletteMirrorCtx) rouletteMirrorCtx = new AC();
  if (rouletteMirrorCtx.state === 'suspended') rouletteMirrorCtx.resume();
  return rouletteMirrorCtx;
}

// Schedule a spin's roll + land chime.
//   startDelayMs — how long until this roll begins (0 = immediately)
//   rollMs       — how long the roll lasts before the land chime
// A queued spin is scheduled into the future instead of played on click, so it
// never overlaps the spin still on screen.
function scheduleRouletteTestSpinAudio(startDelayMs, rollMs) {
  const ctx = rouletteMirrorContext();
  if (!ctx) return;
  const play = () => {
    rouletteRollSynth(ctx, ctx.currentTime + Math.max(0, startDelayMs) / 1000, rollMs);
  };
  if (ctx.state === 'suspended') ctx.resume().then(play); else play();
}

// Bind roulette controls once DOM is ready.
document.addEventListener('DOMContentLoaded', () => {
  const test = document.getElementById('btn-roulette-test');
  const add = document.getElementById('btn-roulette-add');
  const sound = document.getElementById('btn-roulette-sound');
  if (sound) sound.onclick = playRouletteSoundPreview;
  if (test) test.onclick = testRouletteSpin;
  if (add) add.onclick = () => {
    const sel = document.getElementById('roulette-add-select');
    if (sel && sel.value && !roulettePool.includes(sel.value)) {
      roulettePool.push(sel.value);
      renderRoulettePool();
      fillRouletteAddSelect();
      saveRouletteConfig();
    }
  };
});
