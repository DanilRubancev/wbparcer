/**
 * WB Parser — Frontend SPA (Vanilla JS + Chart.js)
 * Wildberries marketplace analytics dashboard
 */

// ─── API client ──────────────────────────────────────────────────────────────
// Flask сам раздаёт фронтенд, поэтому API всегда на том же ориджине что и страница.
const API_BASE = '';

let authToken = null;
let currentUser = null;

async function api(method, path, body) {
  const headers = { 'Content-Type': 'application/json' };
  if (authToken) headers['X-Auth-Token'] = authToken;
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// ─── State ────────────────────────────────────────────────────────────────────
let page = 'search';
let searches = [];
let dashboards = [];
let viewSearchId = null;
let analytics = null;
let products = [];
let chartInstances = {};
let pollTimer = null;
let sortField = null;   // 'price' | 'rating' | 'feedbacks' | null
let sortDir = 'desc';   // 'asc' | 'desc'

// ─── Theme ────────────────────────────────────────────────────────────────────
let theme = 'dark';
function setTheme(t) {
  theme = t;
  document.documentElement.setAttribute('data-theme', t);
}
function toggleTheme() {
  setTheme(theme === 'dark' ? 'light' : 'dark');
  localStorage.setItem('wb_theme', theme);
  renderApp();
}

// ─── Toast ────────────────────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const wrap = document.getElementById('toast-container');
  if (!wrap) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const icon = type === 'error' ? '✕' : type === 'success' ? '✓' : 'ℹ';
  el.innerHTML = `<span style="font-size:16px">${icon}</span> ${escHtml(msg)}`;
  wrap.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ─── Utils ────────────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function fmtPrice(n) {
  return n ? n.toLocaleString('ru-RU') + ' ₽' : '—';
}
function fmtNum(n) {
  return n?.toLocaleString('ru-RU') ?? '—';
}
function fmtDate(s) {
  if (!s) return '';
  const d = new Date(s);
  return d.toLocaleDateString('ru-RU', { day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit' });
}
function stars(rating) {
  const full = Math.floor(rating);
  const half = rating - full >= 0.5;
  return '★'.repeat(full) + (half ? '½' : '') + '☆'.repeat(5 - full - (half ? 1 : 0));
}

// Chart.js defaults per theme
function getChartDefaults() {
  const isDark = theme === 'dark';
  return {
    textColor: isDark ? '#E8E6E3' : '#1A1814',
    mutedColor: isDark ? '#7A7875' : '#6B6A66',
    gridColor: isDark ? 'rgba(255,255,255,.06)' : 'rgba(0,0,0,.06)',
    bgColor: isDark ? '#1A1815' : '#FAFAF8',
  };
}

const CHART_COLORS = [
  '#E8415F','#42A5F5','#66BB6A','#FFA726','#AB47BC',
  '#26C6DA','#FFCA28','#A1887F','#78909C','#EF5350'
];

function destroyCharts() {
  Object.values(chartInstances).forEach(c => c.destroy());
  chartInstances = {};
}

// ─── Router ───────────────────────────────────────────────────────────────────
function navigate(p, searchId) {
  destroyCharts();
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  page = p;
  viewSearchId = searchId || null;
  renderApp();
}

// ─── Data loaders ─────────────────────────────────────────────────────────────
async function loadSearches() {
  try {
    searches = await api('GET', '/api/searches');
  } catch { searches = []; }
}
async function loadDashboards() {
  try {
    dashboards = await api('GET', '/api/dashboards');
  } catch { dashboards = []; }
}
async function loadAnalytics(searchId) {
  analytics = null; products = [];
  try {
    [analytics, products] = await Promise.all([
      api('GET', `/api/searches/${searchId}/analytics`),
      api('GET', `/api/searches/${searchId}/products`),
    ]);
  } catch (e) {
    toast(e.message, 'error');
  }
}

// ─── Render ───────────────────────────────────────────────────────────────────
function renderApp() {
  const root = document.getElementById('app');
  if (!authToken) {
    root.innerHTML = renderAuth();
    bindAuth();
    return;
  }
  root.innerHTML = renderLayout();
  bindLayout();

  if (page === 'search') renderSearchPage();
  else if (page === 'dashboard') renderDashboardPage();
  else if (page === 'saved') renderSavedPage();

  // Re-init lucide icons
  if (window.lucide) lucide.createIcons();
}

// ─── Auth ─────────────────────────────────────────────────────────────────────
let authMode = 'login';
function renderAuth() {
  return `
  <div class="auth-wrap">
    <div class="auth-card">
      <div class="auth-logo">
        <div class="auth-logo-icon">
          ${wbLogoSvg(24)}
        </div>
      </div>
      <h1 class="auth-title">WB Parser</h1>
      <p class="auth-sub">${authMode === 'login' ? 'Войдите в аккаунт' : 'Создайте аккаунт'}</p>
      <div id="auth-error"></div>
      <div class="form-group">
        <label class="form-label">Имя пользователя</label>
        <input class="form-input" id="auth-username" type="text" placeholder="demo" autocomplete="username" />
      </div>
      <div class="form-group">
        <label class="form-label">Пароль</label>
        <input class="form-input" id="auth-password" type="password" placeholder="${authMode === 'login' ? 'demo123' : 'Минимум 6 символов'}" autocomplete="${authMode === 'login' ? 'current-password' : 'new-password'}" />
      </div>
      <button class="btn btn-primary btn-full" id="auth-submit">
        ${authMode === 'login' ? 'Войти' : 'Зарегистрироваться'}
      </button>
      ${authMode === 'register' ? `
      <div class="form-group" style="margin-top: 12px;">
        <label class="checkbox-label" style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
          <input type="checkbox" id="register-consent" style="width: 16px; height: 16px; cursor: pointer;">
          <span style="font-size: 12px; color: var(--text-m);">
            Я принимаю <a href="https://docs.google.com/document/d/1y_1bcSHD8Uk0zHwFGxYz1OPzi0v9wVbJpM4hczHldXs/edit?usp=sharing" target="_blank" style="color: var(--accent); text-decoration: underline;">условия использования</a> и даю согласие на обработку персональных данных
          </span>
        </label>
      </div>
      ` : ''}
      <p class="auth-switch">
        ${authMode === 'login'
          ? 'Нет аккаунта? <a id="auth-switch">Зарегистрироваться</a>'
          : 'Уже есть аккаунт? <a id="auth-switch">Войти</a>'
        }
      </p>
      ${authMode === 'login' ? '<p class="auth-switch" style="margin-top:8px;font-size:12px;color:var(--text-f)">Демо: demo / demo123</p>' : ''}
    </div>
  </div>`;
}

function bindAuth() {
  document.getElementById('auth-switch')?.addEventListener('click', () => {
    authMode = authMode === 'login' ? 'register' : 'login';
    renderApp();
  });
  document.getElementById('auth-submit')?.addEventListener('click', submitAuth);
  document.getElementById('auth-password')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') submitAuth();
  });
}

async function submitAuth() {
  const username = document.getElementById('auth-username')?.value.trim();
  const password = document.getElementById('auth-password')?.value;
  const errEl = document.getElementById('auth-error');
  if (!username || !password) {
    errEl.innerHTML = `<div class="error-msg">Заполните все поля</div>`;
    return;
  }
  if (authMode === 'register') {
    const consentCheckbox = document.getElementById('register-consent');
    if (!consentCheckbox || !consentCheckbox.checked) {
      errEl.innerHTML = `<div class="error-msg">Необходимо принять условия использования</div>`;
      return;
    }
  }
  
  try {
    const endpoint = authMode === 'login' ? '/api/auth/login' : '/api/auth/register';
    const data = await api('POST', endpoint, { username, password });
    authToken = data.token;
    localStorage.setItem('wb_token', data.token);
    localStorage.setItem('wb_username', data.username);
    currentUser = data.username;
    await Promise.all([loadSearches(), loadDashboards()]);
    navigate('search');
  } catch (e) {
    if (errEl) errEl.innerHTML = `<div class="error-msg">${escHtml(e.message)}</div>`;
  }
}

// ─── Layout ───────────────────────────────────────────────────────────────────
function renderLayout() {
  const isDark = theme === 'dark';
  const moonSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
  const sunSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>`;

  const pages = [
    { id: 'search', label: 'Новый анализ', icon: 'search' },
    { id: 'saved', label: 'Сохранённые', icon: 'layout-dashboard' },
  ];

  return `
  <div class="app-layout">
    <aside class="sidebar">
      <div class="sidebar-logo">
        <div class="sidebar-logo-icon">${wbLogoSvg(20)}</div>
        <div>
          <div class="sidebar-logo-text">WB Parser</div>
          <div class="sidebar-logo-sub">Маркетплейс аналитика</div>
        </div>
      </div>
      <nav class="sidebar-nav">
        <div class="nav-group">
          <div class="nav-label">Меню</div>
          ${pages.map(p => `
            <button class="nav-item ${page === p.id ? 'active' : ''}" data-nav="${p.id}">
              <i data-lucide="${p.icon}" width="16" height="16"></i>
              ${escHtml(p.label)}
              ${p.id === 'search' && searches.length > 0 ? `<span class="badge badge-neutral" style="margin-left:auto">${searches.length}</span>` : ''}
            </button>
          `).join('')}
        </div>
        ${searches.length > 0 ? `
        <div class="nav-group" style="margin-top:12px">
          <div class="nav-label">Последние поиски</div>
          ${searches.slice(0, 6).map(s => `
            <button class="nav-item" data-nav="dashboard" data-sid="${s.id}">
              <i data-lucide="bar-chart-2" width="14" height="14"></i>
              <span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:140px">${escHtml(s.query)}</span>
              <span class="status-dot status-${s.status}" style="margin-left:auto"></span>
            </button>
          `).join('')}
        </div>` : ''}
      </nav>
      <div class="sidebar-bottom">
        <div class="user-chip">
          <div class="user-avatar">${(currentUser || 'U')[0].toUpperCase()}</div>
          <div class="user-name">${escHtml(currentUser || '')}</div>
          <button class="btn-icon" id="btn-logout" title="Выйти">
            <i data-lucide="log-out" width="15" height="15"></i>
          </button>
        </div>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <span class="topbar-title" id="topbar-title"></span>
        <button class="theme-toggle" id="theme-toggle" title="Переключить тему">
          ${isDark ? sunSvg : moonSvg}
        </button>
      </header>
      <div class="content" id="main-content"></div>
    </div>
  </div>
  <div class="toast-container" id="toast-container"></div>`;
}

function bindLayout() {
  document.querySelectorAll('[data-nav]').forEach(el => {
    el.addEventListener('click', () => {
      const p = el.dataset.nav;
      const sid = el.dataset.sid;
      if (sid) openDashboard(parseInt(sid));
      else navigate(p);
    });
  });
  document.getElementById('btn-logout')?.addEventListener('click', logout);
  document.getElementById('theme-toggle')?.addEventListener('click', toggleTheme);
}

async function logout() {
  localStorage.removeItem('wb_token');
  localStorage.removeItem('wb_username');
  try { await api('POST', '/api/auth/logout'); } catch {}
  authToken = null; currentUser = null;
  renderApp();
}

// ─── Search Page ──────────────────────────────────────────────────────────────
function renderSearchPage() {
  setTitle('Новый анализ');
  const el = document.getElementById('main-content');
  el.innerHTML = `
    <div class="search-hero">
      <h1>Анализ товаров Wildberries</h1>
      <p>Введите поисковый запрос, артикул товара или ссылку на страницу WB — получите детальный дашборд</p>
      <div class="search-bar">
        <input class="search-input" id="q-input" type="text"
          placeholder="Наушники беспроводные / 12345678 / https://wildberries.ru/..." />
        <button class="btn-search" id="btn-start">Анализировать</button>
      </div>
      <div class="search-hints">
        <div class="search-hint-item">🔍 Ключевое слово</div>
        <div class="search-hint-item">🔢 Артикул товара</div>
        <div class="search-hint-item">🔗 Ссылка на WB</div>
      </div>
    </div>

    <div class="section-title">
      История поисков
      ${searches.length > 0 ? `<span class="badge badge-neutral">${searches.length}</span>` : ''}
    </div>
    ${renderSearchList()}
  `;

  document.getElementById('btn-start')?.addEventListener('click', startSearch);
  document.getElementById('q-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') startSearch();
  });
  bindSearchCards();
}

function renderSearchList() {
  if (!searches.length) {
    return `<div class="empty-state">
      <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
      <p>Поиски пока не выполнялись.<br>Введите запрос выше, чтобы начать.</p>
    </div>`;
  }
  return `<div class="searches-list">
    ${searches.map(s => `
      <div class="search-card" data-sid="${s.id}">
        <div class="search-card-icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 3h18v18H3z" rx="2"/><path d="M7 8h10M7 12h6M7 16h4"/>
          </svg>
        </div>
        <div class="search-card-info">
          <div class="search-card-query">${escHtml(s.query)}</div>
          <div class="search-card-meta">
            <span class="status-dot status-${s.status}"></span>
            <span>${statusLabel(s.status)}</span>
            ${s.product_count > 0 ? `<span class="dot"></span><span>${s.product_count} товаров</span>` : ''}
            <span class="dot"></span>
            <span>${fmtDate(s.created_at)}</span>
          </div>
        </div>
        <div style="display:flex;gap:6px">
          ${s.status === 'done' ? `<button class="btn btn-outline btn-sm" data-open="${s.id}">Открыть</button>` : ''}
          <button class="btn btn-danger btn-sm" data-del="${s.id}">✕</button>
        </div>
      </div>
    `).join('')}
  </div>`;
}

function bindSearchCards() {
  document.querySelectorAll('[data-open]').forEach(b => {
    b.addEventListener('click', e => { e.stopPropagation(); openDashboard(parseInt(b.dataset.open)); });
  });
  document.querySelectorAll('.search-card').forEach(card => {
    card.addEventListener('click', () => {
      const sid = parseInt(card.dataset.sid);
      const s = searches.find(x => x.id === sid);
      if (s?.status === 'done') openDashboard(sid);
    });
  });
  document.querySelectorAll('[data-del]').forEach(b => {
    b.addEventListener('click', async e => {
      e.stopPropagation();
      const sid = parseInt(b.dataset.del);
      try {
        await api('DELETE', `/api/searches/${sid}`);
        searches = searches.filter(s => s.id !== sid);
        renderSearchPage();
        toast('Поиск удалён', 'success');
      } catch (e) { toast(e.message, 'error'); }
    });
  });
}

// ─── Search ───────────────────────────────────────────────────────────────────
async function startSearch() {
  const input = document.getElementById('q-input');
  const query = input?.value.trim();
  if (!query) { toast('Введите запрос', 'error'); return; }

  const btn = document.getElementById('btn-start');
  if (btn) { btn.textContent = 'Парсим...'; btn.disabled = true; }

  try {
    const data = await api('POST', '/api/searches', { query });
    searches.unshift({ id: data.id, query, status: 'pending', product_count: 0, created_at: new Date().toISOString() });
    input.value = '';
    renderSearchPage();
    toast('Парсинг запущен!', 'success');
    startPoll(data.id);
  } catch (e) {
    toast(e.message, 'error');
    if (btn) { btn.textContent = 'Анализировать'; btn.disabled = false; }
  } finally {
    if (btn) { btn.textContent = 'Анализировать'; btn.disabled = false; }
  }
}

function startPoll(searchId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const s = await api('GET', `/api/searches/${searchId}`);
      const idx = searches.findIndex(x => x.id === searchId);
      if (idx !== -1) searches[idx] = s;
      
      if (s.status === 'done' || s.status === 'error') {
        clearInterval(pollTimer); pollTimer = null;
        if (s.status === 'done') {
          toast(`Готово! Найдено ${s.product_count} товаров`, 'success');
        } else {
          toast('Ошибка парсинга. Попробуйте другой запрос.', 'error');
        }
        // ← ВОТ ЭТА СТРОКА — обновляем страницу поиска
        if (page === 'search') renderSearchPage();
      } else {
        // Обновляем только статус в реальном времени (без полной перерисовки)
        if (page === 'search') {
          const listEl = document.querySelector('.searches-list');
          if (listEl) listEl.outerHTML = renderSearchList();
          bindSearchCards();
        }
      }
    } catch {}
  }, 2500);
}

// ─── Sorting helper ──────────────────────────────────────────────────────────
function getSortedProducts() {
  if (!sortField) return products;
  const sorted = [...products];
  sorted.sort((a, b) => {
    const va = a[sortField] ?? 0;
    const vb = b[sortField] ?? 0;
    return sortDir === 'asc' ? va - vb : vb - va;
  });
  return sorted;
}

// ─── Dashboard Page ───────────────────────────────────────────────────────────
async function openDashboard(searchId) {
  viewSearchId = searchId;
  page = 'dashboard';
  setTitle('Дашборд');
  const el = document.getElementById('main-content');
  if (el) el.innerHTML = `<div class="loader"><div class="spinner"></div><p>Загружаем аналитику...</p></div>`;
  renderApp();

  await loadAnalytics(searchId);
  renderDashboardPage();
}

function renderDashboardPage() {
  setTitle('Дашборд');
  const el = document.getElementById('main-content');
  if (!el) return;

  if (!analytics) {
    el.innerHTML = `<div class="loader"><div class="spinner"></div><p>Загружаем...</p></div>`;
    return;
  }

  const s = analytics.search;
  const kpi = analytics.kpi;

  const isSaved = dashboards.some(d => d.search_id === viewSearchId);

  el.innerHTML = `
    <button class="back-btn" id="btn-back">
      ← Назад к поискам
    </button>

    <div class="dash-header">
      <div class="dash-header-info">
        <div class="dash-query">${escHtml(s.query)}</div>
        <div class="dash-meta">
          <span>${analytics.total_products} товаров</span>
          <span>·</span>
          <span>${fmtDate(s.created_at)}</span>
          <span>·</span>
          <span class="badge badge-${s.status === 'done' ? 'success' : 'warning'}">${statusLabel(s.status)}</span>
        </div>
      </div>
      <div class="dash-actions">
        ${!isSaved ? `<button class="btn btn-outline" id="btn-save-dash">💾 Сохранить</button>` : `<span class="badge badge-success">✓ Сохранён</span>`}
      </div>
    </div>

    ${analytics.total_products === 0 ? `
      <div class="empty-state">
        <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
        <p>Товары не найдены. Попробуйте другой запрос.</p>
      </div>` : `

    <!-- KPI Cards -->
    <div class="kpi-grid">
      ${kpiCard('💰', 'Средняя цена', fmtPrice(kpi.avg_price), '#CC2D52')}
      ${kpiCard('📊', 'Медиана цены', fmtPrice(kpi.median_price), '#0277BD')}
      ${kpiCard('⬆', 'Макс. скидка', kpi.max_discount + '%', '#2E7D32')}
      ${kpiCard('⭐', 'Средний рейтинг', (kpi.avg_rating || 0).toFixed(2), '#E65100')}
      ${kpiCard('💬', 'Всего отзывов', fmtNum(kpi.total_feedbacks), '#7B1FA2')}
      ${kpiCard('🏷', 'Брендов', fmtNum(kpi.brands_count), '#00838F')}
      ${kpiCard('⬇', 'Мин. цена', fmtPrice(kpi.min_price), '#F57F17')}
      ${kpiCard('⬆', 'Макс. цена', fmtPrice(kpi.max_price), '#4E342E')}
    </div>

    <!-- Charts -->
    <div class="charts-grid">
      <!-- Price distribution -->
      <div class="chart-card col-8">
        <div class="chart-title">Распределение цен</div>
        <div class="chart-sub">Количество товаров в каждом ценовом диапазоне</div>
        <div class="chart-wrap"><canvas id="chart-price"></canvas></div>
      </div>

      <!-- Rating distribution -->
      <div class="chart-card col-4">
        <div class="chart-title">Распределение рейтингов</div>
        <div class="chart-sub">По шкале 0–5</div>
        <div class="chart-wrap"><canvas id="chart-rating"></canvas></div>
      </div>

      <!-- Brand top -->
      <div class="chart-card col-6">
        <div class="chart-title">Топ брендов</div>
        <div class="chart-sub">По количеству товаров в выдаче</div>
        <div class="chart-wrap tall"><canvas id="chart-brands"></canvas></div>
      </div>

      <!-- Discount distribution -->
      <div class="chart-card col-6">
        <div class="chart-title">Диапазоны скидок</div>
        <div class="chart-sub">Сколько товаров с какой скидкой</div>
        <div class="chart-wrap"><canvas id="chart-discount"></canvas></div>
      </div>

      <!-- Price vs Rating scatter -->
      <div class="chart-card col-8">
        <div class="chart-title">Цена vs Рейтинг</div>
        <div class="chart-sub">Корреляция цены и рейтинга товаров</div>
        <div class="chart-wrap scatter"><canvas id="chart-scatter"></canvas></div>
      </div>

      <!-- Supplier top -->
      <div class="chart-card col-4">
        <div class="chart-title">Топ продавцов</div>
        <div class="chart-sub">По количеству товаров</div>
        <div class="chart-wrap tall"><canvas id="chart-suppliers"></canvas></div>
      </div>
    </div>

    <!-- Products table -->
    <div class="table-wrap">
      <div class="table-header">
        <span style="font-weight:700;font-size:14px">Таблица товаров</span>
        <span class="badge badge-neutral">${products.length} записей</span>
        <div class="sort-controls">
          <span class="sort-label">Сортировка:</span>
          <button class="sort-btn ${sortField === 'price' ? 'active' : ''}" data-sort="price">
            Цена ${sortField === 'price' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
          </button>
          <button class="sort-btn ${sortField === 'rating' ? 'active' : ''}" data-sort="rating">
            Рейтинг ${sortField === 'rating' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
          </button>
          <button class="sort-btn ${sortField === 'feedbacks' ? 'active' : ''}" data-sort="feedbacks">
            Отзывы ${sortField === 'feedbacks' ? (sortDir === 'asc' ? '↑' : '↓') : ''}
          </button>
          ${sortField ? '<button class="sort-btn sort-reset" data-sort="reset">✕ Сброс</button>' : ''}
        </div>
      </div>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Артикул</th>
              <th>Название</th>
              <th>Бренд</th>
              <th class="th-sortable" data-sort="price">Цена ${sortField === 'price' ? (sortDir === 'asc' ? '↑' : '↓') : '⇅'}</th>
              <th>Цена до скидки</th>
              <th>Скидка</th>
              <th class="th-sortable" data-sort="rating">Рейтинг ${sortField === 'rating' ? (sortDir === 'asc' ? '↑' : '↓') : '⇅'}</th>
              <th class="th-sortable" data-sort="feedbacks">Отзывы ${sortField === 'feedbacks' ? (sortDir === 'asc' ? '↑' : '↓') : '⇅'}</th>
              <th>Поставщик</th>
            </tr>
          </thead>
          <tbody>
            ${getSortedProducts().slice(0, 100).map(p => `
              <tr>
                <td><a href="https://www.wildberries.ru/catalog/${p.article}/detail.aspx" target="_blank" style="font-family:var(--font-mono);font-size:12px;color:var(--accent);text-decoration:none" title="Открыть на Wildberries">${p.article}</a></td>
                <td class="td-name" title="${escHtml(p.name)}">${escHtml(p.name)}</td>
                <td>${escHtml(p.brand || '—')}</td>
                <td class="td-price">${fmtPrice(p.price)}</td>
                <td><span class="td-price-old">${p.price_original > p.price ? fmtPrice(p.price_original) : '—'}</span></td>
                <td>${p.discount > 0 ? `<span class="badge badge-success">-${p.discount}%</span>` : '—'}</td>
                <td>
                  <span class="stars">${p.rating > 0 ? stars(p.rating).substring(0,5) : ''}</span>
                  <span class="rating-num">${p.rating > 0 ? p.rating.toFixed(1) : '—'}</span>
                </td>
                <td>${fmtNum(p.feedbacks)}</td>
                <td style="max-width:160px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escHtml(p.supplier || '—')}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
    `}
  `;

  // Bind buttons
  document.getElementById('btn-back')?.addEventListener('click', () => navigate('search'));
  document.getElementById('btn-save-dash')?.addEventListener('click', saveDashboard);

  // Bind sort buttons (both in controls bar and in table headers)
  document.querySelectorAll('[data-sort]').forEach(btn => {
    btn.addEventListener('click', () => {
      const field = btn.dataset.sort;
      if (field === 'reset') {
        sortField = null;
        sortDir = 'desc';
      } else if (sortField === field) {
        sortDir = sortDir === 'desc' ? 'asc' : 'desc';
      } else {
        sortField = field;
        sortDir = 'desc';
      }
      renderDashboardPage();
    });
  });

  if (analytics.total_products > 0) {
    setTimeout(renderCharts, 50);
  }
}

function kpiCard(emoji, label, value, color) {
  return `
  <div class="kpi-card">
    <div class="kpi-icon" style="background:${color}18">
      <span style="font-size:20px">${emoji}</span>
    </div>
    <div class="kpi-body">
      <div class="kpi-value">${value}</div>
      <div class="kpi-label">${label}</div>
    </div>
  </div>`;
}

function renderCharts() {
  const cd = getChartDefaults();
  Chart.defaults.color = cd.textColor;
  Chart.defaults.font.family = 'Inter, sans-serif';
  Chart.defaults.font.size = 12;

  const baseOptions = {
    responsive: true,
    maintainAspectRatio: true,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: cd.bgColor,
        borderColor: cd.gridColor,
        borderWidth: 1,
        titleColor: cd.textColor,
        bodyColor: cd.mutedColor,
        padding: 10,
        cornerRadius: 8,
      }
    },
    scales: {
      x: {
        grid: { color: cd.gridColor },
        ticks: { color: cd.mutedColor },
        border: { display: false },
      },
      y: {
        grid: { color: cd.gridColor },
        ticks: { color: cd.mutedColor },
        border: { display: false },
        beginAtZero: true,
      }
    }
  };

  // 1. Price distribution (Bar)
  const pd = analytics.price_distribution;
  if (pd.length && document.getElementById('chart-price')) {
    chartInstances['price'] = new Chart(document.getElementById('chart-price'), {
      type: 'bar',
      data: {
        labels: pd.map(d => d.range),
        datasets: [{
          label: 'Товаров',
          data: pd.map(d => d.count),
          backgroundColor: CHART_COLORS[0] + 'CC',
          borderColor: CHART_COLORS[0],
          borderWidth: 1,
          borderRadius: 4,
          hoverBackgroundColor: CHART_COLORS[0],
        }]
      },
      options: { ...baseOptions }
    });
  }

  // 2. Rating distribution (Bar)
  const rd = analytics.rating_distribution;
  if (rd.length && document.getElementById('chart-rating')) {
    chartInstances['rating'] = new Chart(document.getElementById('chart-rating'), {
      type: 'bar',
      data: {
        labels: rd.map(d => d.range),
        datasets: [{
          label: 'Товаров',
          data: rd.map(d => d.count),
          backgroundColor: CHART_COLORS[3] + 'CC',
          borderColor: CHART_COLORS[3],
          borderWidth: 1,
          borderRadius: 4,
        }]
      },
      options: { ...baseOptions }
    });
  }

  // 3. Brands (Horizontal bar)
  const brands = analytics.brand_top;
  if (brands.length && document.getElementById('chart-brands')) {
    chartInstances['brands'] = new Chart(document.getElementById('chart-brands'), {
      type: 'bar',
      data: {
        labels: brands.map(b => b.brand),
        datasets: [{
          label: 'Товаров',
          data: brands.map(b => b.count),
          backgroundColor: brands.map((_, i) => CHART_COLORS[i % CHART_COLORS.length] + 'CC'),
          borderColor: brands.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]),
          borderWidth: 1,
          borderRadius: 4,
        }]
      },
      options: {
        ...baseOptions,
        indexAxis: 'y',
        plugins: { ...baseOptions.plugins, legend: { display: false } },
      }
    });
  }

  // 4. Discount distribution (Doughnut)
  const dd = analytics.discount_distribution;
  if (dd.length && document.getElementById('chart-discount')) {
    chartInstances['discount'] = new Chart(document.getElementById('chart-discount'), {
      type: 'doughnut',
      data: {
        labels: dd.map(d => d.range),
        datasets: [{
          data: dd.map(d => d.count),
          backgroundColor: CHART_COLORS.slice(0, dd.length).map(c => c + 'DD'),
          borderColor: CHART_COLORS.slice(0, dd.length),
          borderWidth: 2,
          hoverOffset: 6,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { display: true, position: 'bottom',
            labels: { color: cd.mutedColor, padding: 12, font: { size: 11 } }
          },
          tooltip: baseOptions.plugins.tooltip,
        },
        cutout: '60%',
      }
    });
  }

  // 5. Price vs Rating (Scatter)
  const pvr = analytics.price_vs_rating;
  if (pvr.length && document.getElementById('chart-scatter')) {
    chartInstances['scatter'] = new Chart(document.getElementById('chart-scatter'), {
      type: 'scatter',
      data: {
        datasets: [{
          label: 'Товары',
          data: pvr.map(p => ({ x: p.price, y: p.rating, name: p.name })),
          backgroundColor: CHART_COLORS[0] + '99',
          borderColor: CHART_COLORS[0],
          borderWidth: 1,
          pointRadius: 5,
          pointHoverRadius: 8,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            ...baseOptions.plugins.tooltip,
            callbacks: {
              label: ctx => {
                const d = ctx.raw;
                return [`${d.name || ''}`, `Цена: ${fmtPrice(d.x)}`, `Рейтинг: ${d.y}`];
              }
            }
          }
        },
        scales: {
          x: {
            ...baseOptions.scales.x,
            title: { display: true, text: 'Цена (₽)', color: cd.mutedColor },
            ticks: { ...baseOptions.scales.x.ticks, callback: v => fmtPrice(v) },
          },
          y: {
            ...baseOptions.scales.y,
            title: { display: true, text: 'Рейтинг', color: cd.mutedColor },
            min: 0, max: 5.5,
          }
        }
      }
    });
  }

  // 6. Suppliers (Doughnut)
  const sup = analytics.supplier_top;
  if (sup.length && document.getElementById('chart-suppliers')) {
    chartInstances['suppliers'] = new Chart(document.getElementById('chart-suppliers'), {
      type: 'doughnut',
      data: {
        labels: sup.map(s => s.supplier.substring(0, 20)),
        datasets: [{
          data: sup.map(s => s.count),
          backgroundColor: CHART_COLORS.slice(0, sup.length).map(c => c + 'CC'),
          borderColor: CHART_COLORS.slice(0, sup.length),
          borderWidth: 2,
          hoverOffset: 6,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { display: true, position: 'bottom',
            labels: { color: cd.mutedColor, padding: 8, font: { size: 10 } }
          },
          tooltip: baseOptions.plugins.tooltip,
        },
        cutout: '55%',
      }
    });
  }
}

// ─── Save Dashboard ───────────────────────────────────────────────────────────
async function saveDashboard() {
  if (!viewSearchId || !analytics) return;
  const title = `${analytics.search.query} — ${fmtDate(analytics.search.created_at)}`;
  try {
    await api('POST', '/api/dashboards', { search_id: viewSearchId, title });
    await loadDashboards();
    toast('Дашборд сохранён!', 'success');
    renderDashboardPage();
  } catch (e) {
    toast(e.message, 'error');
  }
}

// ─── Saved Dashboards Page ────────────────────────────────────────────────────
async function renderSavedPage() {
  setTitle('Сохранённые дашборды');
  await loadDashboards();
  const el = document.getElementById('main-content');
  if (!el) return;

  el.innerHTML = `
    <div class="section-title">
      Сохранённые дашборды
      ${dashboards.length > 0 ? `<span class="badge badge-neutral">${dashboards.length}</span>` : ''}
    </div>
    ${dashboards.length === 0 ? `
      <div class="empty-state">
        <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>
        <p>Нет сохранённых дашбордов.<br>Откройте анализ и нажмите «Сохранить».</p>
      </div>
    ` : `
      <div class="saved-grid">
        ${dashboards.map(d => `
          <div class="saved-card" data-sid="${d.search_id}">
            <div class="saved-card-title">📊 ${escHtml(d.title)}</div>
            <div class="saved-card-meta">
              ${d.product_count} товаров · ${fmtDate(d.created_at)}
            </div>
            <button class="saved-card-del" data-del-dash="${d.id}" title="Удалить">✕</button>
          </div>
        `).join('')}
      </div>
    `}
  `;

  document.querySelectorAll('.saved-card').forEach(card => {
    card.addEventListener('click', e => {
      if (e.target.closest('[data-del-dash]')) return;
      openDashboard(parseInt(card.dataset.sid));
    });
  });
  document.querySelectorAll('[data-del-dash]').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      try {
        await api('DELETE', `/api/dashboards/${btn.dataset.delDash}`);
        await renderSavedPage();
        toast('Удалено', 'success');
      } catch (e) { toast(e.message, 'error'); }
    });
  });
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function setTitle(t) {
  const el = document.getElementById('topbar-title');
  if (el) el.textContent = t;
  document.title = `${t} — WB Parser`;
}

function statusLabel(s) {
  return { pending: 'Ожидает', running: 'Парсинг...', done: 'Готово', error: 'Ошибка' }[s] || s;
}

function wbLogoSvg(size = 24) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect width="24" height="24" rx="4" fill="white" fill-opacity="0.15"/>
    <path d="M5 7L8.5 17L12 9L15.5 17L19 7" stroke="white" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}

// ─── Boot ─────────────────────────────────────────────────────────────────────
async function boot() {
  // 1. Восстанавливаем тему
  const savedTheme = localStorage.getItem('wb_theme');
  if (savedTheme === 'light' || savedTheme === 'dark') {
    setTheme(savedTheme);
  } else {
    setTheme('dark');
  }
  
  // 2. Восстанавливаем токен
  const savedToken = localStorage.getItem('wb_token');
  if (savedToken) {
    authToken = savedToken;
    
    // 3. ПРОВЕРЯЕМ, работает ли токен на сервере
    try {
      // Делаем простой запрос, который требует авторизации
      await api('GET', '/api/searches');
      
      // Если дошли сюда — токен валидный
      const savedUsername = localStorage.getItem('wb_username');
      if (savedUsername) {
        currentUser = savedUsername;
      }
      
      // Загружаем данные
      await Promise.all([loadSearches(), loadDashboards()]);
      
    } catch (e) {
      // Токен невалидный (сервер перезапустился или сессия истекла)
      console.warn('Токен невалиден, очищаем', e);
      localStorage.removeItem('wb_token');
      localStorage.removeItem('wb_username');
      authToken = null;
      currentUser = null;
    }
  }
  
  renderApp();
  if (window.lucide) lucide.createIcons();
}

boot();