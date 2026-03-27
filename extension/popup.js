// ── Config ────────────────────────────────────────────────────────────────────
const DEFAULT_VM = 'http://localhost:5001';
let _vmUrl = DEFAULT_VM;

chrome.storage.local.get(['vmUrl'], (r) => {
  _vmUrl = r.vmUrl || DEFAULT_VM;
  document.getElementById('vm-url-input').value = _vmUrl;
  refresh();
  loadSettings();
});

document.getElementById('save-url-btn').addEventListener('click', () => {
  _vmUrl = document.getElementById('vm-url-input').value.trim() || DEFAULT_VM;
  chrome.storage.local.set({ vmUrl: _vmUrl }, () => {
    refresh();
  });
});

// ── Tab switcher ──────────────────────────────────────────────────────────────
function switchTab(name) {
  ['status', 'sandbox', 'settings'].forEach(t => {
    document.getElementById('tab-' + t).style.display = t === name ? 'block' : 'none';
    const btn = document.getElementById('nav-' + t);
    if (btn) btn.classList.toggle('active', t === name);
  });
}

// ── Tile helper ───────────────────────────────────────────────────────────────
function tile(id, cls, text) {
  const el = document.getElementById('t-' + id);
  if (!el) return;
  el.className = 'tile ' + cls;
  el.querySelector('.t-val').textContent = text;
}

// ── Health refresh ────────────────────────────────────────────────────────────
async function refresh() {
  const status = document.getElementById('ctrl-status');
  try {
    const r = await fetch(_vmUrl + '/health', { signal: AbortSignal.timeout(4000) });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const h = await r.json();
    applyHealth(h);
    status.textContent = '✅ VM доступна';
    status.style.color = '#4caf50';
  } catch (e) {
    ['ollama','lmstudio','tgwui','roocode','sd','comfyui','vvm','tgbot'].forEach(id => {
      tile(id, 'off', '—');
    });
    status.textContent = '❌ VM недоступна: ' + e.message;
    status.style.color = '#f44336';
  }
}

function applyHealth(h) {
  if (!h) return;
  const ol = h.ollama || {};
  if (ol.status === 'ok') tile('ollama', 'ok', '✓ ' + (ol.models || []).length + ' мод.');
  else if (ol.status === 'no_url') tile('ollama', 'warn', '⚠ нет URL');
  else tile('ollama', 'err', '✗ офлайн');

  const lm = h.lmstudio || {};
  if (lm.status === 'ok') tile('lmstudio', 'ok', '✓ ' + (lm.models || []).length + ' мод.');
  else tile('lmstudio', lm.status === 'no_url' ? 'warn' : 'off', lm.status === 'ok' ? '✓' : '✗');

  const tw = h.tgwui || {};
  tile('tgwui', tw.status === 'ok' ? 'ok' : 'off', tw.status === 'ok' ? '✓ онлайн' : '✗');

  const rc = h.roocode || {};
  tile('roocode', rc.status === 'ok' ? 'ok' : 'off', rc.status === 'ok' ? '✓ онлайн' : '✗');

  const sd = h.sd || {};
  tile('sd', sd.status === 'ok' ? 'ok' : 'off', sd.status === 'ok' ? '✓ онлайн' : '✗');

  const cu = h.comfyui || {};
  tile('comfyui', cu.status === 'ok' ? 'ok' : 'off', cu.status === 'ok' ? '✓ онлайн' : '✗');

  const vv = h.vision_vm || {};
  tile('vvm', vv.status === 'ok' ? 'ok' : 'off', vv.status === 'ok' ? '✓ онлайн' : '✗');

  const tb = h.tg_bot || {};
  if (tb.status === 'ok') tile('tgbot', 'ok', '✓ @' + (tb.username || 'bot'));
  else if (tb.status === 'no_token') tile('tgbot', 'warn', '⚠ нет токена');
  else tile('tgbot', 'err', '✗ не запущен');
}

// ── Bot controls ──────────────────────────────────────────────────────────────
async function botStart() {
  const s = document.getElementById('ctrl-status');
  s.textContent = '⏳ Запускаю...'; s.style.color = '#9cdcfe';
  try {
    const r = await fetch(_vmUrl + '/bot/start', { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      s.textContent = d.status === 'already_running' ? '✅ Уже запущен' : '✅ Запущен (PID ' + d.pid + ')';
      s.style.color = '#4caf50';
    } else {
      s.textContent = '❌ ' + d.error; s.style.color = '#f44336';
    }
    setTimeout(refresh, 1500);
  } catch (e) { s.textContent = '❌ ' + e.message; s.style.color = '#f44336'; }
}

async function botStop() {
  const s = document.getElementById('ctrl-status');
  s.textContent = '⏳ Останавливаю...'; s.style.color = '#9cdcfe';
  try {
    const r = await fetch(_vmUrl + '/bot/stop', { method: 'POST' });
    const d = await r.json();
    s.textContent = d.ok ? '⏹ Остановлен' : '❌ ' + d.error;
    s.style.color = d.ok ? '#ffc107' : '#f44336';
    setTimeout(refresh, 800);
  } catch (e) { s.textContent = '❌ ' + e.message; s.style.color = '#f44336'; }
}

// ── Sandbox (code execution) ──────────────────────────────────────────────────
async function runCode() {
  const code = document.getElementById('code-area').value.trim();
  if (!code) {
    setOutStatus('Редактор пуст', 'inf');
    return;
  }
  const lang = document.getElementById('lang-sel').value;
  const btn = document.getElementById('run-code-btn');
  btn.disabled = true; btn.textContent = '⏳…';
  setOutStatus('⏳ Выполняю...', 'inf');
  document.getElementById('output-area').textContent = '';

  try {
    const r = await fetch(_vmUrl + '/api/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, lang }),
      signal: AbortSignal.timeout(65000)
    });
    const d = await r.json();
    if (d.error) {
      document.getElementById('output-area').textContent = d.error;
      setOutStatus('❌ Ошибка', 'err');
    } else {
      const out = (d.output || '').trim() || '(нет вывода)';
      document.getElementById('output-area').textContent = out;
      if (d.ok) setOutStatus('✅ rc=0', 'ok');
      else setOutStatus('⚠ rc=' + d.returncode, 'err');
    }
  } catch (e) {
    document.getElementById('output-area').textContent = e.message;
    setOutStatus('❌ ' + e.message, 'err');
  } finally {
    btn.disabled = false; btn.textContent = '▶ Запустить';
  }
}

function clearOut() {
  document.getElementById('output-area').textContent = 'Вывод появится здесь...';
  setOutStatus('Нажмите ▶ Запустить', 'inf');
}

function setOutStatus(msg, cls) {
  const el = document.getElementById('out-status');
  el.textContent = msg;
  el.className = cls;
}

// ── Settings ──────────────────────────────────────────────────────────────────
const _KEYS = ['BOT_TOKEN', 'OLLAMA_URL', 'LMS_URL', 'TGWUI_URL', 'ROOCODE_URL'];

async function loadSettings() {
  try {
    const r = await fetch(_vmUrl + '/settings', { signal: AbortSignal.timeout(4000) });
    const cfg = await r.json();
    _KEYS.forEach(k => {
      const el = document.getElementById('s-' + k);
      if (!el) return;
      if (cfg[k] && cfg[k] !== 'set') el.value = cfg[k];
      else if (cfg[k] === 'set') el.placeholder = 'уже настроен — введите новый для замены';
    });
  } catch (e) { /* VM offline — ignore */ }
}

async function saveSettings() {
  const s = document.getElementById('settings-status');
  const payload = {};
  _KEYS.forEach(k => {
    const el = document.getElementById('s-' + k);
    if (el && el.value.trim()) payload[k] = el.value.trim();
  });
  s.textContent = '⏳ Сохраняю...'; s.style.color = '#9cdcfe';
  try {
    await fetch(_vmUrl + '/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(5000)
    });
    s.textContent = '✅ Сохранено'; s.style.color = '#4caf50';
    setTimeout(refresh, 2000);
  } catch (e) {
    s.textContent = '❌ ' + e.message; s.style.color = '#f44336';
  }
}

function openVM() {
  chrome.tabs.create({ url: _vmUrl });
}

// ── Enter key in sandbox ──────────────────────────────────────────────────────
document.getElementById('code-area').addEventListener('keydown', (e) => {
  if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); runCode(); }
});

// Auto-refresh health every 30s
setInterval(refresh, 30000);
