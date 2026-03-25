'use strict';

const DEFAULT_PORT = 5001;

// ── helpers ──────────────────────────────────────────────────────────────────

function getPort(cb) {
  if (typeof chrome !== 'undefined' && chrome.storage) {
    chrome.storage.local.get(['drgrPort'], (r) => {
      cb(parseInt(r.drgrPort) || DEFAULT_PORT);
    });
  } else {
    cb(DEFAULT_PORT);
  }
}

function savePort(port) {
  if (typeof chrome !== 'undefined' && chrome.storage) {
    chrome.storage.local.set({ drgrPort: port });
  }
}

function openTab(url) {
  if (typeof chrome !== 'undefined' && chrome.tabs) {
    chrome.tabs.create({ url });
  } else {
    window.open(url, '_blank');
  }
}

// ── status check ─────────────────────────────────────────────────────────────

function checkStatus(port) {
  const dot  = document.getElementById('dot');
  const text = document.getElementById('status-text');
  const footer = document.getElementById('footer');

  dot.className = 'dot';
  text.textContent = 'Проверка…';

  fetch(`http://localhost:${port}/health`, { signal: AbortSignal.timeout(3000) })
    .then(r => r.json())
    .then(data => {
      dot.className = 'dot online';
      text.textContent = `Онлайн · localhost:${port}`;
      footer.textContent = `DRGR Bot · ${data.version || 'v1.0'} · порт ${port}`;
    })
    .catch(() => {
      dot.className = 'dot offline';
      text.textContent = `Не доступен (порт ${port})`;
      footer.textContent = 'Запустите ЗАПУСТИТЬ_БОТА.bat';
    });
}

// ── init ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  const portInput = document.getElementById('portInput');

  getPort(port => {
    portInput.value = port;
    checkStatus(port);

    const base = () => `http://localhost:${parseInt(portInput.value) || DEFAULT_PORT}`;

    document.getElementById('openUI').onclick       = () => openTab(base() + '/');
    document.getElementById('openChat').onclick     = () => openTab(base() + '/#chat');
    document.getElementById('openResearch').onclick = () => openTab(base() + '/#research');
    document.getElementById('openImagegen').onclick = () => openTab(base() + '/#imagegen');
    document.getElementById('checkHealth').onclick  = () => {
      checkStatus(parseInt(portInput.value) || DEFAULT_PORT);
    };

    document.getElementById('savePort').onclick = () => {
      const p = parseInt(portInput.value);
      if (p > 0 && p < 65536) {
        savePort(p);
        checkStatus(p);
      }
    };
  });
});
