// ─── WebSocket ────────────────────────────────────────────────────────
let ws = null;
let wsReconnectTimer = null;
let wsConnected = false;
let _searchResults = [];

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    wsConnected = true;
    setWsStatus(true);
    clearTimeout(wsReconnectTimer);
    startPing();
  };

  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === 'log') appendLog(msg.data);
      if (msg.type === 'status') updateStatusFromWS(msg.data);
    } catch {}
  };

  ws.onclose = () => {
    wsConnected = false;
    setWsStatus(false);
    wsReconnectTimer = setTimeout(connectWS, 3000);
  };

  ws.onerror = () => ws.close();
}

let pingInterval = null;
function startPing() {
  clearInterval(pingInterval);
  pingInterval = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send('ping');
  }, 20000);
}

function setWsStatus(ok) {
  const el = document.getElementById('ws-status');
  if (!el) return;
  el.innerHTML = ok
    ? '<span class="dot green"></span> Real-time подключено'
    : '<span class="dot gray"></span> Переподключение...';
}

// ─── Logs ──────────────────────────────────────────────────────────────
function appendLog(entry) {
  const container = document.getElementById('log-container');
  if (!container) return;

  const el = document.createElement('div');
  el.className = `log-entry ${entry.level || 'info'}`;

  const mode = entry.mode || 'TEST';
  const modeClass = mode === 'LIVE' ? 'live' : 'test';

  const timeSpan = document.createElement('span');
  timeSpan.className = 'log-time';
  timeSpan.textContent = entry.time || '';

  const modeSpan = document.createElement('span');
  modeSpan.className = `log-mode ${modeClass}`;
  modeSpan.textContent = `[${mode}]`;

  const msgSpan = document.createElement('span');
  msgSpan.className = 'log-msg';
  msgSpan.textContent = entry.message || '';

  el.appendChild(timeSpan);
  el.appendChild(modeSpan);
  el.appendChild(msgSpan);

  container.appendChild(el);

  const autoScroll = document.getElementById('auto-scroll');
  if (!autoScroll || autoScroll.checked) {
    container.scrollTop = container.scrollHeight;
  }

  const count = container.querySelectorAll('.log-entry').length;
  if (count > 500) container.removeChild(container.firstChild);
}

function clearLogs() {
  const c = document.getElementById('log-container');
  if (c) c.innerHTML = '';
}

// ─── Status ────────────────────────────────────────────────────────────
function updateStatusFromWS(data) {
  updateBotStatusUI(data.running, data.mode, data.balance);
}

function updateBotStatusUI(running, mode, balance) {
  const statusDot = document.getElementById('status-dot');
  const statusText = document.getElementById('status-text');
  const startBtn = document.getElementById('start-btn');
  const stopBtn = document.getElementById('stop-btn');
  const modeBadge = document.getElementById('mode-badge');
  const balanceEl = document.getElementById('balance-value');

  if (statusDot) {
    statusDot.className = `dot ${running ? 'red' : 'gray'}`;
  }
  if (statusText) {
    statusText.textContent = running ? 'РАБОТАЕТ' : 'ОСТАНОВЛЕН';
  }
  if (startBtn) startBtn.disabled = running;
  if (stopBtn) stopBtn.disabled = !running;
  if (modeBadge) {
    modeBadge.className = `mode-badge ${mode === 'LIVE' ? 'live' : 'test'}`;
    const dotSpan = document.createElement('span');
    dotSpan.className = `dot ${running ? (mode === 'LIVE' ? 'red' : 'green') : 'gray'}`;
    modeBadge.textContent = '';
    modeBadge.appendChild(dotSpan);
    modeBadge.appendChild(document.createTextNode('\u00A0' + mode));
  }
  if (balanceEl && balance !== undefined) {
    balanceEl.textContent = `${balance.toFixed(2)} ${window.CURRENCY_SYMBOL || '₽'}`;
  }
}

// ─── Bot Control ───────────────────────────────────────────────────────
async function startBot() {
  const btn = document.getElementById('start-btn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Запуск...'; }

  const res = await apiPost('/api/bot/start');
  if (res.success) {
    showToast('✅ ' + res.message, 'success');
    refreshStatus();
  } else {
    showToast('❌ ' + res.message, 'error');
  }
  if (btn) { btn.disabled = false; btn.innerHTML = '▶ СТАРТ'; }
}

async function stopBot() {
  const btn = document.getElementById('stop-btn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Остановка...'; }

  const res = await apiPost('/api/bot/stop');
  if (res.success) {
    showToast('🛑 ' + res.message, 'warning');
    refreshStatus();
  } else {
    showToast('❌ ' + res.message, 'error');
  }
  if (btn) { btn.disabled = false; btn.innerHTML = '⏹ СТОП'; }
}

async function refreshStatus() {
  const data = await apiFetch('/api/bot/status');
  updateBotStatusUI(data.running, data.mode, data.balance);

  const s = data.stats || {};
  setEl('total-trades', s.total_trades ?? 0);
  setEl('total-profit', formatMoney(s.total_profit ?? 0));
  setEl('daily-profit', formatMoney(s.daily_profit ?? 0));
}

// ─── Mode Switch ───────────────────────────────────────────────────────
async function setMode(mode) {
  if (window._botRunning) {
    showToast('⚠️ Остановите бота перед сменой режима', 'warning');
    return;
  }
  const res = await apiPost('/api/settings/mode', { mode });
  if (res.success) {
    showToast(mode === 'LIVE' ? '🔴 Переключено в РЕАЛЬНЫЙ режим' : '🧪 Переключено в ТЕСТОВЫЙ режим',
      mode === 'LIVE' ? 'error' : 'success');
    setTimeout(() => location.reload(), 800);
  }
}

// ─── Items ─────────────────────────────────────────────────────────────
let searchTimeout = null;
let selectedItem = null;

function setupItemSearch() {
  const input = document.getElementById('item-search-input');
  const results = document.getElementById('search-results');
  if (!input || !results) return;

  input.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    const q = input.value.trim();
    if (q.length < 3) { results.style.display = 'none'; return; }
    searchTimeout = setTimeout(() => doSearch(q), 400);
  });

  document.addEventListener('click', (e) => {
    if (!e.target.closest('.search-wrap')) results.style.display = 'none';
  });
}

async function doSearch(q) {
  const appId = document.getElementById('app-id-select')?.value || 730;
  const results = document.getElementById('search-results');
  results.innerHTML = '<div style="padding:12px;color:var(--text-muted)"><span class="spinner"></span> Поиск...</div>';
  results.style.display = 'block';

  const data = await apiFetch(`/api/items/search?q=${encodeURIComponent(q)}&app_id=${appId}`);
  if (!data.results || !data.results.length) {
    results.innerHTML = '<div style="padding:12px;color:var(--text-muted)">Ничего не найдено</div>';
    return;
  }

  _searchResults = data.results;
  results.textContent = '';
  data.results.forEach((item, index) => {
    const row = document.createElement('div');
    row.className = 'search-item';
    row.addEventListener('click', () => selectSearchItem(_searchResults[index]));

    const img = document.createElement('img');
    img.src = item.icon_url || '/static/no-image.png';
    img.onerror = function() { this.src = '/static/no-image.png'; };

    const info = document.createElement('div');

    const nameEl = document.createElement('div');
    nameEl.className = 'search-item-name';
    nameEl.textContent = item.name;

    const priceEl = document.createElement('div');
    priceEl.className = 'search-item-price';
    priceEl.textContent = `${item.price_text} · ${item.sell_listings} листингов`;

    info.appendChild(nameEl);
    info.appendChild(priceEl);
    row.appendChild(img);
    row.appendChild(info);
    results.appendChild(row);
  });
}

function selectSearchItem(item) {
  selectedItem = item;
  document.getElementById('item-search-input').value = item.name;
  document.getElementById('search-results').style.display = 'none';
  document.getElementById('item-name-display').textContent = item.name;
  document.getElementById('item-hash-display').textContent = item.hash_name;
  document.getElementById('item-url-display').textContent = item.steam_url;
  document.getElementById('selected-item-preview').style.display = 'flex';
  if (item.icon_url) {
    document.getElementById('selected-item-img').src = item.icon_url;
  }
}

async function addItem() {
  const btn = document.getElementById('add-item-btn');
  let name, hash_name, app_id, steam_url, image_url;

  if (selectedItem) {
    name = selectedItem.name;
    hash_name = selectedItem.hash_name;
    app_id = selectedItem.app_id;
    steam_url = selectedItem.steam_url;
    image_url = selectedItem.icon_url;
  } else {
    const manualInput = document.getElementById('item-manual-input');
    name = manualInput?.value.trim();
    if (!name) { showToast('⚠️ Введите название предмета', 'warning'); return; }
    hash_name = name;
    app_id = parseInt(document.getElementById('app-id-select')?.value || 730);
    steam_url = `https://steamcommunity.com/market/listings/${app_id}/${encodeURIComponent(name)}`;
    image_url = '';
  }

  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Добавление...'; }

  const res = await apiPost('/api/items/add', { name, hash_name, app_id, steam_url, image_url });
  showToast(res.success ? '✅ ' + res.message : '❌ ' + res.message, res.success ? 'success' : 'error');

  if (res.success) {
    setTimeout(() => location.reload(), 500);
  }
  if (btn) { btn.disabled = false; btn.innerHTML = '+ Добавить'; }
}

async function removeItem(id, name) {
  if (!confirm(`Удалить "${name}" из мониторинга?`)) return;
  const res = await fetch(`/api/items/${id}`, { method: 'DELETE' });
  const data = await res.json();
  showToast(data.success ? '✅ Удалено' : '❌ Ошибка', data.success ? 'success' : 'error');
  if (data.success) setTimeout(() => location.reload(), 400);
}

async function refreshItemPrice(itemId, btn) {
  if (btn) { btn.innerHTML = '<span class="spinner"></span>'; btn.disabled = true; }
  const data = await apiFetch(`/api/items/price/${itemId}`);
  if (data.success) {
    const card = document.getElementById(`item-card-${itemId}`);
    if (card) {
      const lowEl = card.querySelector('.price-low');
      const medEl = card.querySelector('.price-med');
      const discEl = card.querySelector('.price-disc');
      if (lowEl) lowEl.textContent = data.lowest_price_raw;
      if (medEl) medEl.textContent = data.median_price_raw;
      if (discEl) {
        discEl.textContent = `${data.discount}%`;
        discEl.style.color = data.should_buy ? 'var(--green)' : 'var(--text-muted)';
      }
      if (data.should_buy) {
        card.style.borderColor = 'var(--green)';
        card.title = data.reason;
      }
    }
    showToast(`💹 ${data.lowest_price_raw} / ${data.median_price_raw} (скидка ${data.discount}%)`, 'success');
  } else {
    showToast('❌ ' + data.error, 'error');
  }
  if (btn) { btn.innerHTML = '↻'; btn.disabled = false; }
}

// ─── Settings ──────────────────────────────────────────────────────────
async function saveSettings() {
  const form = document.getElementById('settings-form');
  if (!form) return;

  const data = {};
  form.querySelectorAll('[name]').forEach(el => {
    if (el.type === 'checkbox') data[el.name] = el.checked ? '1' : '0';
    else data[el.name] = el.value;
  });

  const threshold = parseFloat(data.buy_threshold);
  if (isNaN(threshold) || threshold < 17) {
    showToast('⚠️ Минимальный порог покупки — 17%', 'warning');
    return;
  }

  const btn = document.getElementById('save-settings-btn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Сохранение...'; }

  const res = await apiPost('/api/settings/save', data);
  showToast(res.success ? '✅ Настройки сохранены' : '❌ ' + res.message, res.success ? 'success' : 'error');
  if (btn) { btn.disabled = false; btn.innerHTML = '💾 Сохранить'; }
}

async function testTelegram() {
  const btn = document.getElementById('test-tg-btn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Отправка...'; }
  const res = await apiPost('/api/telegram/test', {});
  showToast(res.success ? '✅ ' + res.message : '❌ ' + res.message, res.success ? 'success' : 'error');
  if (btn) { btn.disabled = false; btn.innerHTML = '📨 Тест'; }
}

async function resetVirtualBalance() {
  if (!confirm('Сбросить виртуальный баланс до начального значения?')) return;
  const res = await apiPost('/api/virtual_balance/reset', {});
  showToast(res.success ? '✅ ' + res.message : '❌ Ошибка', res.success ? 'success' : 'error');
  if (res.success) setTimeout(() => location.reload(), 500);
}

// ─── Tabs ──────────────────────────────────────────────────────────────
function switchTab(tabId) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.querySelector(`[data-tab="${tabId}"]`)?.classList.add('active');
  document.getElementById(`tab-${tabId}`)?.classList.add('active');
}

// ─── Utils ─────────────────────────────────────────────────────────────
async function apiFetch(url) {
  try {
    const res = await fetch(url);
    return await res.json();
  } catch { return {}; }
}

async function apiPost(url, data = {}) {
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    return await res.json();
  } catch { return { success: false, message: 'Ошибка сети' }; }
}

function setEl(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function formatMoney(v) {
  return (v || 0).toFixed(2) + ' ' + (window.CURRENCY_SYMBOL || '₽');
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function showToast(msg, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  const span = document.createElement('span');
  span.style.flex = '1';
  span.textContent = msg;
  toast.appendChild(span);
  container.appendChild(toast);
  setTimeout(() => { toast.style.opacity = '0'; toast.style.transition = 'opacity .3s'; setTimeout(() => toast.remove(), 300); }, 4000);
}

// ─── Init ──────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  connectWS();
  setupItemSearch();

  if (document.getElementById('start-btn')) {
    setInterval(refreshStatus, 10000);
    refreshStatus();
  }

  document.querySelectorAll('[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  const firstTab = document.querySelector('[data-tab]');
  if (firstTab) switchTab(firstTab.dataset.tab);
});
