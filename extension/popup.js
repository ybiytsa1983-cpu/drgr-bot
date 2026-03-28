// popup.js — DRGR Bot Control Extension

const DEFAULT_VM_URL = 'http://localhost:5001';
const VM_URL_FALLBACKS = [
  'http://localhost:5001',
  'http://127.0.0.1:5001',
  'http://localhost:5000',
  'http://127.0.0.1:5000',
];

// ── helpers ──────────────────────────────────────────────────────────────────

async function getVmUrl() {
  return new Promise(resolve => {
    chrome.storage.local.get({ vmUrl: DEFAULT_VM_URL }, d => resolve(d.vmUrl));
  });
}

function normalizeVmUrl(url) {
  return String(url || DEFAULT_VM_URL).trim().replace(/\/+$/, '');
}

function vmUrlCandidates(primary) {
  const seen = new Set();
  const out = [];
  [primary, ...VM_URL_FALLBACKS].forEach(u => {
    const norm = normalizeVmUrl(u);
    if (!norm || seen.has(norm)) return;
    seen.add(norm);
    out.push(norm);
  });
  return out;
}

async function apiFetch(path, opts = {}) {
  const configuredBase = normalizeVmUrl(await getVmUrl());
  const candidates = vmUrlCandidates(configuredBase);
  let lastError = null;

  for (const base of candidates) {
    try {
      const response = await fetch(base + path, opts);
      if (response.ok && base !== configuredBase) {
        chrome.storage.local.set({ vmUrl: base });
      }
      return response;
    } catch (e) {
      lastError = e;
    }
  }

  throw lastError || new Error('VM недоступна');
}

function setBadge(id, text, cls) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.className = 'badge ' + cls;
}

function setMsg(id, text, color) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.style.color = color || '#888';
}

// ── tabs ─────────────────────────────────────────────────────────────────────

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    const panel = document.getElementById('tab-' + tab);
    if (panel) panel.classList.add('active');
  });
});

// ── status tab ───────────────────────────────────────────────────────────────

async function refreshStatus() {
  setBadge('st-vm',  '…', 'badge-unknown');
  setBadge('st-bot', '…', 'badge-unknown');
  setMsg('statusMsg', '');
  try {
    const r = await apiFetch('/health');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();

    setBadge('st-vm', d.vm === 'ok' ? 'online' : d.vm, d.vm === 'ok' ? 'badge-ok' : 'badge-stopped');

    const botStatus = d.bot || 'unknown';
    const botCls = botStatus === 'running' ? 'badge-running' : botStatus === 'not_started' || botStatus === 'stopped' ? 'badge-stopped' : 'badge-unknown';
    setBadge('st-bot', botStatus, botCls);

    const projEl = document.getElementById('st-projects');
    if (projEl) projEl.textContent = d.projects_count != null ? d.projects_count : '—';
  } catch (e) {
    setBadge('st-vm',  'offline', 'badge-stopped');
    setBadge('st-bot', 'неизвестно', 'badge-unknown');
    setMsg('statusMsg', 'VM недоступна: ' + e.message, '#f66');
  }
}

document.getElementById('btnRefresh').addEventListener('click', refreshStatus);

document.getElementById('btnStart').addEventListener('click', async () => {
  setMsg('statusMsg', 'Запуск…');
  try {
    const r = await apiFetch('/bot/start', { method: 'POST' });
    const d = await r.json();
    setMsg('statusMsg', 'Бот: ' + d.status, '#4ec94e');
    setTimeout(refreshStatus, 800);
  } catch (e) {
    setMsg('statusMsg', 'Ошибка: ' + e.message, '#f66');
  }
});

document.getElementById('btnStop').addEventListener('click', async () => {
  setMsg('statusMsg', 'Остановка…');
  try {
    const r = await apiFetch('/bot/stop', { method: 'POST' });
    const d = await r.json();
    setMsg('statusMsg', 'Бот: ' + d.status, '#f44');
    setTimeout(refreshStatus, 800);
  } catch (e) {
    setMsg('statusMsg', 'Ошибка: ' + e.message, '#f66');
  }
});

document.getElementById('btnReport').addEventListener('click', async () => {
  const box = document.getElementById('reportBox');
  box.style.display = 'block';
  box.textContent = 'Загрузка…';
  try {
    const r = await apiFetch('/extension/report');
    const d = await r.json();
    box.textContent = d.report || JSON.stringify(d, null, 2);
  } catch (e) {
    box.textContent = 'Ошибка: ' + e.message;
  }
});

document.getElementById('btnOpenVM').addEventListener('click', async () => {
  const base = await getVmUrl();
  chrome.tabs.create({ url: base });
});

// ── sandbox tab ──────────────────────────────────────────────────────────────

let _sbEndpoint = '/api/goose';
let _sbPayloadKey = 'query';

function sbSetActive(endpoint, key) {
  _sbEndpoint = endpoint;
  _sbPayloadKey = key;
  document.querySelectorAll('.sandbox-actions .btn').forEach(b => b.style.opacity = '1');
  // no direct ref needed; rely on click handler below
}

document.getElementById('sbGoose').addEventListener('click', function () {
  sbSetActive('/api/goose', 'query');
  setResult('sbResult', 'Выбран: Goose AI — нажмите ➤ Отправить');
});

document.getElementById('sb3d').addEventListener('click', function () {
  sbSetActive('/api/generate-3d', 'prompt');
  setResult('sbResult', 'Выбран: 3D Generator — нажмите ➤ Отправить');
});

document.getElementById('sbVideo').addEventListener('click', function () {
  sbSetActive('/api/generate-video', 'prompt');
  setResult('sbResult', 'Выбран: Video Generator — нажмите ➤ Отправить');
});

function setResult(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

document.getElementById('sbSend').addEventListener('click', async () => {
  const input = document.getElementById('sbInput').value.trim();
  if (!input) {
    setResult('sbResult', '⚠ Введите запрос');
    return;
  }
  setResult('sbResult', 'Отправка…');
  try {
    const body = { [_sbPayloadKey]: input };
    const r = await apiFetch(_sbEndpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    setResult('sbResult', d.result || JSON.stringify(d, null, 2));
  } catch (e) {
    setResult('sbResult', 'Ошибка: ' + e.message);
  }
});

document.getElementById('sbClear').addEventListener('click', () => {
  document.getElementById('sbInput').value = '';
  setResult('sbResult', '—');
});

// ── settings tab ─────────────────────────────────────────────────────────────

async function loadSettings() {
  const url = await getVmUrl();
  document.getElementById('cfgUrl').value = normalizeVmUrl(url);
}

document.getElementById('btnSaveCfg').addEventListener('click', () => {
  const url = normalizeVmUrl(document.getElementById('cfgUrl').value) || DEFAULT_VM_URL;
  chrome.storage.local.set({ vmUrl: url }, () => {
    setMsg('cfgMsg', '✓ Сохранено', '#4ec94e');
    setTimeout(() => setMsg('cfgMsg', ''), 2000);
  });
});

document.getElementById('btnTestConn').addEventListener('click', async () => {
  setMsg('cfgMsg', 'Проверка…');
  try {
    const r = await apiFetch('/health');
    if (r.ok) {
      const d = await r.json();
      const activeUrl = normalizeVmUrl(await getVmUrl());
      setMsg('cfgMsg', `✓ Подключено: ${activeUrl} (vm: ${d.vm})`, '#4ec94e');
    } else {
      setMsg('cfgMsg', `✗ HTTP ${r.status}`, '#f66');
    }
  } catch (e) {
    setMsg('cfgMsg', '✗ ' + e.message, '#f66');
  }
});

// ── init ─────────────────────────────────────────────────────────────────────

loadSettings();
refreshStatus();
