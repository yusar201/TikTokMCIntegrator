// ==========================================
// STATE
// ==========================================
let currentConfig = {};
let editingGiftKey = null;
let giftIconMap = {};
let giftNameMap = {};
let streakDeltaSelected = [];
let cachedAvailableGifts = [];
let botRunning = false;
let streamStartTime = null;
let tickerCount = 0;
let songConfig = null;
let spotifyConnected = false;

// ==========================================
// NAVIGATION
// ==========================================
function switchPanel(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const panel = document.getElementById('panel-' + name);
  const nav = document.querySelector(`[data-panel="${name}"]`);
  if (panel) panel.classList.add('active');
  if (nav) nav.classList.add('active');
  // Initialize overlay previews when switching to overlays tab
  if (name === 'overlays') initOverlayPreviews();
  if (name === 'tts') loadTtsConfig();
}

// ==========================================
// TOAST NOTIFICATIONS
// ==========================================
function showToast(msg, type) {
  const container = document.getElementById('toast-container');
  const iconMap = { gift: 'fa-gift', follow: 'fa-user-plus', success: 'fa-check', info: 'fa-info', error: 'fa-triangle-exclamation' };
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
function updateBotStatusUI(isRunning) {
  const dot = document.getElementById('status-dot');
  const text = document.getElementById('status-text');
  const btn = document.getElementById('btn-toggle');

  botRunning = isRunning;
  if (isRunning) {
    dot.className = 'status-dot online';
    text.textContent = 'Streaming';
    btn.innerHTML = '<i class="fa-solid fa-stop"></i> Stop Bot';
    btn.className = 'btn btn-danger';
    btn.onclick = stopBot;
    if (!streamStartTime) { streamStartTime = Date.now(); startTimer(); }
  } else {
    dot.className = 'status-dot';
    text.textContent = 'Offline';
    btn.innerHTML = '<i class="fa-solid fa-play"></i> Start Bot';
    btn.className = 'btn btn-primary';
    btn.onclick = startBot;
    streamStartTime = null;
    document.getElementById('stream-timer').textContent = '--:--:--';
  }
}

function toggleBot() {
  if (botRunning) { stopBot(); } else { startBot(); }
}

// Timer
let timerInterval = null;
function startTimer() {
  if (timerInterval) clearInterval(timerInterval);
  timerInterval = setInterval(() => {
    if (!streamStartTime) return;
    const elapsed = Math.floor((Date.now() - streamStartTime) / 1000);
    const h = Math.floor(elapsed / 3600);
    const m = Math.floor((elapsed % 3600) / 60);
    const s = elapsed % 60;
    document.getElementById('stream-timer').textContent =
      `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  }, 1000);
}

// ==========================================
// API CALLS
// ==========================================
async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    currentConfig = await res.json();
    populateSettings();
    renderEventsGrid();
    populateGifts();
    // Re-render event browser if registry is loaded (for custom events browser)
    if (eventRegistryData) renderEventBrowser();
    // Update TikTok handle in topbar
    if (currentConfig.Settings && currentConfig.Settings.TikTokUsername) {
      document.getElementById('tiktok-handle-display').textContent = currentConfig.Settings.TikTokUsername;
    }
  } catch (e) {
    console.error("Failed to load config:", e);
  }
}

async function saveConfigData() {
  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentConfig)
    });
    const data = await res.json();
    showToast(data.message, 'success');
  } catch (e) {
    showToast("Error saving config", 'error');
  }
}

async function checkBotStatus() {
  try {
    const res = await fetch('/api/bot/status');
    const data = await res.json();
    updateBotStatusUI(data.running);
  } catch (e) {
    updateBotStatusUI(false);
  }
}

async function startBot() {
  try {
    const res = await fetch('/api/bot/start', { method: 'POST' });
    const data = await res.json();
    if(data.status === 'success') {
      updateBotStatusUI(true);
      showToast('Bot started!', 'success');
    } else {
      showToast(data.message, 'error');
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
    }
  } catch(e) {
    showToast("Failed to stop bot", 'error');
  }
}

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
// CHAT LOG
// ==========================================
let lastChatCount = 0;

async function fetchChatLog() {
  try {
    const res = await fetch('/api/stats/chat');
    const data = await res.json();
    renderChatLog(data);
  } catch (e) {}
}

function renderChatLog(entries) {
  const container = document.getElementById('chat-log-container');
  if (!container) return;

  if (!entries || entries.length === 0) {
    if (container.querySelector('.ticker-empty')) return;
    container.innerHTML = '<div class="ticker-empty">No chat messages yet...</div>';
    lastChatCount = 0;
    document.getElementById('ticker-count').textContent = '0';
    return;
  }

  // Guard against desync: if log was reset/cleared, resync lastChatCount
  if (lastChatCount > entries.length) {
    lastChatCount = 0;
    container.innerHTML = '';
  }
  const newEntries = entries.slice(lastChatCount);
  if (newEntries.length === 0) return;

  // Remove empty state if present
  const empty = container.querySelector('.ticker-empty');
  if (empty) empty.remove();

  // Append new entries at bottom (newest scrolls down)
  newEntries.forEach(entry => {
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
    const tagBadge = tags ? `<span style="font-size:9px;background:var(--accent);color:#fff;padding:1px 6px;border-radius:8px;margin-left:4px;font-weight:600;">${tags}</span>` : '';
    const avatarHtml = entry.avatar_url
      ? `<img src="${entry.avatar_url}" alt="${entry.nick}" onerror="this.style.display='none'">`
      : initial;

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
          return `<span class="user-badge-combined" title="${title}" style="${bgStyle}${borderStyle}">` +
                   `<img src="${b.icon}" alt="${b.type}" class="user-badge-icon" onerror="this.style.display='none'">` +
                   `<span class="user-badge-level">${b.level_text}</span>` +
                 `</span>`;
        } else if (b.icon) {
          // IMAGE style: icon only
          return `<img src="${b.icon}" alt="${b.type}" title="${title}" class="user-badge-icon" onerror="this.outerHTML='<span class=\\'user-badge-text\\' title=\\'${title}\\'>${b.type}</span>'">`;
        } else {
          // TEXT fallback
          return `<span class="user-badge-text" title="${title}">${b.type}${b.level_text ? ' ' + b.level_text : ''}</span>`;
        }
      }).join('');
    }

    // Add sparkle particles for tier 3 and tier 4
    let sparklesHtml = '';
    if (tierClass === 'tier-3') {
      sparklesHtml = Array.from({length: 3}, (_, i) => {
        const tx = -12 + Math.random() * 24;
        const ty = -15 - Math.random() * 15;
        const colors = ['#fbbf24', '#f97316', '#fcd34d'];
        return `<span class="sparkle-particle" style="left:${15 + i * 30}%;bottom:${15 + i * 10}%;background:${colors[i]};--tx:${tx}px;--ty:${ty}px;animation-delay:${i * 0.6}s;"></span>`;
      }).join('');
    } else if (tierClass === 'tier-4') {
      sparklesHtml = `<span class="legend-glow"></span>` + 
        Array.from({length: 5}, (_, i) => {
          const tx = -30 + Math.random() * 60;
          const ty = -20 - Math.random() * 30;
          const colors = ['#ff0080', '#ffdd00', '#00ff7f', '#00bfff', '#ff69b4'];
          return `<span class="sparkle-particle" style="left:${10 + i * 18}%;bottom:0;background:${colors[i]};--tx:${tx}px;--ty:${ty}px;animation-delay:${i * 0.8}s;"></span>`;
        }).join('');
    }

    div.innerHTML = `
      ${sparklesHtml}
      <div class="ticker-avatar">${avatarHtml}</div>
      <div class="ticker-info">
        <div class="ticker-user">${badgesHtml}<span class="tier-nick">${entry.nick || 'Unknown'}</span> ${tagBadge}</div>
        <div class="ticker-action">${entry.comment || ''}</div>
      </div>
      <span class="ticker-time" style="font-size:10px;opacity:0.5;">@${entry.unique_id || '?'}</span>
    `;
    container.appendChild(div);
  });

  // Chat log: no DOM cap — keeps all entries

  // Scroll to bottom so newest is visible
  container.scrollTop = container.scrollHeight;

  lastChatCount = entries.length;
  document.getElementById('ticker-count').textContent = entries.length;

  // Re-apply active search filter
  filterChatLog();
}

async function clearChatLog() {
  try {
    await fetch('/api/stats/chat/clear', { method: 'POST' });
    const container = document.getElementById('chat-log-container');
    container.innerHTML = '<div class="ticker-empty">No chat messages yet...</div>';
    lastChatCount = 0;
    document.getElementById('ticker-count').textContent = '0';
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
      // Always update — backend is now unlimited so length only grows
      terminal.textContent = data.logs.join('\n');
      terminal.scrollTop = terminal.scrollHeight;
      lastLogCount = data.logs.length;
    }
  } catch (e) {}
}

function clearConsole() {
  document.getElementById('terminal-window').textContent = '';
  lastLogCount = 0;
}

// ==========================================
// SETTINGS
// ==========================================
function populateSettings() {
  if(!currentConfig.Settings) currentConfig.Settings = {};
  if(!currentConfig.Rcon) currentConfig.Rcon = {};
  document.getElementById('tiktok-username').value = currentConfig.Settings.TikTokUsername || "";
  document.getElementById('mc-username').value = currentConfig.Settings.MinecraftUsername || "";
  document.getElementById('euler-api-key').value = currentConfig.Settings.EulerApiKey || "";
  document.getElementById('rcon-host').value = currentConfig.Rcon.Host || "";
  document.getElementById('rcon-port').value = currentConfig.Rcon.Port || 25575;
  document.getElementById('rcon-password').value = currentConfig.Rcon.Password || "";
}

function saveSettings() {
  currentConfig.Settings.TikTokUsername = document.getElementById('tiktok-username').value;
  currentConfig.Settings.MinecraftUsername = document.getElementById('mc-username').value;
  currentConfig.Settings.EulerApiKey = document.getElementById('euler-api-key').value;
  currentConfig.Rcon.Host = document.getElementById('rcon-host').value;
  currentConfig.Rcon.Port = parseInt(document.getElementById('rcon-port').value);
  currentConfig.Rcon.Password = document.getElementById('rcon-password').value;
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
  document.getElementById('add-event-selected-vars').innerHTML = `Variables: ${evt.template_vars.map(v => `<code>{${v}}</code>`).join(' ')}`;

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
  document.getElementById('edit-event-vars').innerHTML = `Variables: ${(reg.template_vars || []).map(v => `<code>{${v}}</code>`).join(' ')}`;

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
  if (confirm(`Delete event "${name}"?`)) {
    delete currentConfig.Events[editingEventKey];
    closeEditEventModal();
    renderEventsGrid();
    showToast(`Event "${name}" deleted`, 'info');
  }
}

function deleteEvent(eventKey) {
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
  if (confirm(`Delete event "${name}"?`)) {
    delete currentConfig.Events[eventKey];
    renderEventsGrid();
    showToast(`Event "${name}" deleted`, 'info');
  }
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
  renderStreakDeltaSelected();

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
// STREAK DELTA
// ==========================================
function renderStreakDeltaSelected() {
  const container = document.getElementById('streak-delta-selected');
  if (!container) return;
  container.innerHTML = '';
  if (streakDeltaSelected.length === 0) {
    container.innerHTML = '<span class="streak-delta-empty">No streak delta gifts selected. Search and pick below.</span>';
    return;
  }
  streakDeltaSelected.forEach(giftId => {
    const displayName = getGiftDisplayName(giftId);
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.innerHTML = `${displayName} <span style="font-size:10px;opacity:0.7;margin-left:4px;">#${giftId}</span> <button class="chip-remove" onclick="removeStreakDeltaGift('${giftId}')">&times;</button>`;
    container.appendChild(chip);
  });
}

function renderStreakDeltaDropdown(query) {
  const dropdown = document.getElementById('streak-delta-dropdown');
  if (!dropdown) return;
  if (cachedAvailableGifts.length === 0) { dropdown.style.display = 'none'; return; }
  const q = (query || '').toLowerCase().trim();
  const filtered = cachedAvailableGifts.filter(g => {
    if (streakDeltaSelected.includes(String(g.id))) return false;
    if (!q) return true;
    return g.name.includes(q) || String(g.id).includes(q);
  });
  dropdown.innerHTML = '';
  if (filtered.length === 0) {
    dropdown.innerHTML = '<p style="opacity:0.5;padding:8px;">No gifts found</p>';
  } else {
    filtered.forEach(gift => {
      const chip = document.createElement('div');
      chip.className = 'gift-chip';
      chip.style.cursor = 'pointer';
      chip.onclick = () => addStreakDeltaGift(String(gift.id));
      chip.innerHTML = `${gift.icon ? `<img src="${gift.icon}" alt="${gift.name}">` : '<i class="fa-solid fa-gift" style="color:var(--accent)"></i>'} <span class="chip-name">${gift.name}</span> <span class="chip-id">#${gift.id}</span> <span class="chip-coins">${gift.diamond_count}</span>`;
      dropdown.appendChild(chip);
    });
  }
  dropdown.style.display = 'block';
}

function addStreakDeltaGift(giftId) {
  if (!streakDeltaSelected.includes(giftId)) {
    streakDeltaSelected.push(giftId);
    renderStreakDeltaSelected();
  }
  const searchInput = document.getElementById('streak-delta-search');
  if (searchInput) searchInput.value = '';
  renderStreakDeltaDropdown('');
}

function removeStreakDeltaGift(giftId) {
  streakDeltaSelected = streakDeltaSelected.filter(id => id !== giftId);
  renderStreakDeltaSelected();
  const searchInput = document.getElementById('streak-delta-search');
  if (searchInput) renderStreakDeltaDropdown(searchInput.value.toLowerCase().trim());
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

function addActionRow(type, data = null) {
  const container = document.getElementById('modal-actions-list');
  appendActionRowToContainer(container, type, data);
}

function appendActionRowToContainer(container, type, data = null) {
  const row = document.createElement('div');
  row.className = 'action-row';
  row.dataset.type = type;

  const typeColors = {minecraft: '#4CAF50', sound: '#FF9800', webhook: '#2196F3', random: '#9C27B0'};
  const typeIcons = {minecraft: 'fa-terminal', sound: 'fa-volume-high', webhook: 'fa-link', random: 'fa-shuffle'};

  let fieldsHtml = '';
  if (type === 'minecraft') {
    fieldsHtml = `<input type="text" class="action-field action-command" placeholder="give {mc} diamond {amount}" value="${escHtml(data?.command || '')}">`;
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

function closeGiftModal() {
  document.getElementById('gift-modal').classList.remove('active');
  document.getElementById('gift-icon-group').style.display = 'none';
  document.getElementById('modal-gift-description').value = '';
}

function saveGiftModal() {
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

  closeGiftModal();
  populateGifts();
  showToast('Gift saved!', 'success');
}

function deleteGiftModal() {
  if(editingGiftKey && confirm(`Delete ${getGiftDisplayName(editingGiftKey)}?`)) {
    delete currentConfig.Gifts[editingGiftKey];
    if (currentConfig.GiftCategories) delete currentConfig.GiftCategories[editingGiftKey];
    if (currentConfig.GiftNames) delete currentConfig.GiftNames[editingGiftKey];
    if (currentConfig.GiftDescriptions) delete currentConfig.GiftDescriptions[editingGiftKey];
    closeGiftModal();
    populateGifts();
    showToast('Gift deleted', 'info');
  }
}

// ==========================================
// AVAILABLE GIFTS (catalog)
// ==========================================
async function loadGiftIconMap() {
  try {
    const res = await fetch('/api/gifts/available');
    const gifts = await res.json();
    if (gifts && gifts.length > 0) {
      cachedAvailableGifts = gifts;
      gifts.forEach(g => {
        const gid = String(g.id);
        if (g.name) giftNameMap[gid] = g.name.toLowerCase();
        if (g.icon) giftIconMap[gid] = g.icon;
      });
      if (Object.keys(currentConfig.Gifts || {}).length > 0) populateGifts();
    }
  } catch(e) {}
}

async function fetchAvailableGifts() {
  if (cachedAvailableGifts.length > 0) {
    const group = document.getElementById('available-gifts-group');
    group.style.display = 'block';
    renderGiftChips(cachedAvailableGifts);
    const searchInput = document.getElementById('gift-search-input');
    searchInput.value = '';
    searchInput.oninput = () => {
      const q = searchInput.value.toLowerCase().trim();
      const filtered = q ? cachedAvailableGifts.filter(g => g.name.includes(q) || String(g.id).includes(q)) : cachedAvailableGifts;
      renderGiftChips(filtered);
    };
    return;
  }
  try {
    const res = await fetch('/api/gifts/available');
    const gifts = await res.json();
    const group = document.getElementById('available-gifts-group');
    if (gifts && gifts.length > 0) {
      cachedAvailableGifts = gifts;
      gifts.forEach(g => {
        const gid = String(g.id);
        if (g.name) giftNameMap[gid] = g.name.toLowerCase();
        if (g.icon) giftIconMap[gid] = g.icon;
      });
      group.style.display = 'block';
      renderGiftChips(gifts);
      const searchInput = document.getElementById('gift-search-input');
      searchInput.value = '';
      searchInput.oninput = () => {
        const q = searchInput.value.toLowerCase().trim();
        const filtered = q ? cachedAvailableGifts.filter(g => g.name.includes(q) || String(g.id).includes(q)) : cachedAvailableGifts;
        renderGiftChips(filtered);
      };
    } else { group.style.display = 'none'; }
  } catch (e) {}
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
  if (gifts.length === 0) list.innerHTML = '<p style="opacity:0.5;padding:8px;">No gifts found</p>';
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
    const res = await fetch('/api/profiles');
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
    const res = await fetch('/api/profiles');
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
  if(confirm(`Delete profile: ${name}?`)) {
    try {
      const res = await fetch(`/api/profiles/${name}`, {method: 'DELETE'});
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

// =========================================
// INITIALIZATION
// =========================================
document.addEventListener('DOMContentLoaded', () => {
  loadProfiles();
  loadConfig();
  checkBotStatus();
  loadGiftIconMap();
  loadEventRegistry();
  loadSongConfig();
  fetchSongHistory();

  // Polling
  setInterval(checkBotStatus, 3000);
  setInterval(fetchLogs, 1500);
  setInterval(fetchViewerStats, 3000);
  setInterval(fetchGiftLog, 2500);
  setInterval(fetchFollowLog, 3000);
  setInterval(fetchChatLog, 2500);
  setInterval(fetchActiveStreaks, 300);
  setInterval(fetchSongQueue, 3000);
  setInterval(fetchSongHistory, 5000);
  setInterval(fetchSpotifyStatus, 10000);

  // Save buttons
  document.getElementById('btn-save-settings').addEventListener('click', saveSettings);
  document.getElementById('btn-save-events').addEventListener('click', saveEvents);
  document.getElementById('btn-save-gifts').addEventListener('click', saveGifts);
  document.getElementById('btn-add-gift').addEventListener('click', () => openGiftModal());
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
  btn.classList.toggle('active');
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
  }

  const qs = params.toString();
  const fullUrl = qs ? url + '?' + qs : url;

  const urlInput = document.getElementById('overlay-url-' + type);
  if (urlInput) urlInput.value = fullUrl;

  const iframe = document.getElementById('preview-' + type);
  if (iframe) {
    const previewUrl = fullUrl + (fullUrl.includes('?') ? '&' : '?') + 'preview=true';
    if (iframe.src !== previewUrl) {
      iframe.src = previewUrl;
    }
  }
}

function initOverlayPreviews() {
  ['chat', 'gifts', 'follows', 'superfan', 'topgift', 'topstreak', 'song'].forEach(type => {
    updateOverlayUrl(type);
  });
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
    const credWarning = document.getElementById('spotify-credential-warning');

    spotifyConnected = data.connected;
    if (data.connected) {
      dot.className = 'status-dot online';
      text.textContent = 'Connected';
      deviceName.textContent = data.device ? `Device: ${data.device}` : '';
      connectBtn.style.display = 'none';
      disconnectBtn.style.display = '';
      credWarning.style.display = 'none';
    } else {
      dot.className = 'status-dot';
      text.textContent = data.error || (data.has_credentials ? 'Not Connected' : 'Not Configured');
      deviceName.textContent = data.error ? `⚠ ${data.error}` : '';
      connectBtn.style.display = '';
      disconnectBtn.style.display = 'none';
      credWarning.style.display = data.has_credentials ? 'none' : '';
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
        showToast('Connected to Spotify!', 'success');
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
    document.getElementById('song-max-total').value = data.max_queue_total || 10;
    document.getElementById('song-max-user').value = data.max_queue_per_user || 2;
    document.getElementById('song-client-id').value = data.spotify_client_id || '';
    document.getElementById('song-client-secret').value = data.spotify_client_secret && data.spotify_client_secret !== '••••' ? data.spotify_client_secret : '';
    document.getElementById('song-redirect-uri').value = data.spotify_redirect_uri || 'http://127.0.0.1:5000/api/spotify/callback';

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
      spotify_client_id: document.getElementById('song-client-id').value,
      spotify_client_secret: document.getElementById('song-client-secret').value,
      spotify_redirect_uri: document.getElementById('song-redirect-uri').value,
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
      }
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
  if (!confirm('Clear the entire song queue?')) return;
  try {
    await fetch('/api/spotify/queue/clear', { method: 'POST' });
    showToast('Queue cleared', 'info');
    fetchSongQueue();
  } catch(e) {
    showToast('Failed to clear queue', 'error');
  }
}

async function fetchSongHistory() {
  try {
    const res = await fetch('/api/spotify/history');
    const history = await res.json();
    const container = document.getElementById('song-history-container');
    if (!container) return;
    if (!history || history.length === 0) {
      container.innerHTML = '<div class="song-empty small"><span>No history yet.</span></div>';
      return;
    }
    container.innerHTML = '';
    history.slice(0, 20).forEach(entry => {
      const div = document.createElement('div');
      div.className = 'song-row';
      div.innerHTML = `
        <div class="song-row-cover" style="width:32px;height:32px;"><i class="fa-solid fa-check"></i></div>
        <div style="flex:1;min-width:0;">
          <div class="song-row-title">${esc(entry.track_name)}</div>
          <div class="song-row-sub">${esc(entry.artist)} · by ${esc(entry.requested_by)}</div>
        </div>
      `;
      container.appendChild(div);
    });
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

async function saveTtsConfig() {
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
      whitelist: (document.getElementById('tts-whitelist').value || '').split('\n').map(s => s.trim()).filter(Boolean)
    }
  };
  try {
    await fetch('/api/tts/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg)
    });
  } catch(e) {
    console.error('Failed to save TTS config:', e);
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
  if (!confirm('Clear all TTS history?')) return;
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
