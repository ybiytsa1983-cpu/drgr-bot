/* DRGR VM Chrome Extension -- popup.js */
(function() {
  'use strict';

  const DEFAULT_VM_URL = 'http://localhost:5005';
  let vmUrl = DEFAULT_VM_URL;

  // --- chrome.storage guard ---
  function getVmUrl(cb) {
    if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
      chrome.storage.local.get(['vmUrl'], function(data) {
        vmUrl = data.vmUrl || DEFAULT_VM_URL;
        document.getElementById('vmUrl').value = vmUrl;
        if (cb) cb();
      });
    } else {
      vmUrl = DEFAULT_VM_URL;
      document.getElementById('vmUrl').value = vmUrl;
      if (cb) cb();
    }
  }

  // --- API fetch ---
  function apiFetch(path, opts) {
    var url = vmUrl + path;
    return fetch(url, opts).then(function(r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  // --- Tabs ---
  document.querySelectorAll('.tab').forEach(function(tab) {
    tab.addEventListener('click', function() {
      document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
      document.querySelectorAll('.panel').forEach(function(p) { p.classList.remove('active'); });
      tab.classList.add('active');
      var panel = document.getElementById('panel-' + tab.dataset.tab);
      if (panel) panel.classList.add('active');
    });
  });

  // --- Status ---
  window.refreshStatus = function() {
    apiFetch('/extension/report')
      .then(function(d) {
        document.getElementById('reportArea').textContent = d.report || JSON.stringify(d.data, null, 2);
        // Build status rows
        var h = d.data || {};
        var rows = '';
        rows += statusRow('Ollama', h.ollama && h.ollama.available);
        rows += statusRow('LM Studio', h.lmstudio && h.lmstudio.available);
        rows += statusRow('TG Bot', h.bot && h.bot.running);
        rows += statusRow('.env', h.env_exists);
        rows += statusRow('bot.py', h.bot_script_exists);
        document.getElementById('statusRows').innerHTML = rows;
      })
      .catch(function(e) {
        document.getElementById('reportArea').textContent = 'Error: ' + e.message;
        document.getElementById('statusRows').innerHTML = '<div style="color:red">Cannot connect to VM</div>';
      });
  };

  function statusRow(name, ok) {
    return '<div class="status-row"><span><span class="dot ' + (ok ? 'dot-green' : 'dot-red') + '"></span>' + name + '</span><span>' + (ok ? 'OK' : 'OFF') + '</span></div>';
  }

  // --- Open VM ---
  window.openVM = function() {
    if (typeof chrome !== 'undefined' && chrome.tabs && chrome.tabs.create) {
      chrome.tabs.create({ url: vmUrl });
    } else {
      window.open(vmUrl, '_blank');
    }
  };

  // --- Sandbox ---
  window.runSandbox = function() {
    var code = document.getElementById('sandboxCode').value.trim();
    if (!code) return;
    document.getElementById('sandboxResult').textContent = 'Running...';
    apiFetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: code })
    })
      .then(function(d) {
        document.getElementById('sandboxResult').textContent = d.reply || d.error || 'No response';
      })
      .catch(function(e) {
        document.getElementById('sandboxResult').textContent = 'Error: ' + e.message;
      });
  };

  // --- Settings ---
  window.saveCfg = function() {
    var url = document.getElementById('vmUrl').value.trim();
    if (!url) return;
    vmUrl = url;
    if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
      chrome.storage.local.set({ vmUrl: url }, function() {
        alert('Saved: ' + url);
      });
    } else {
      alert('URL set: ' + url + '\n(chrome.storage unavailable, saved for this session only)');
    }
  };

  // --- Init ---
  getVmUrl(function() {
    window.refreshStatus();
  });
})();
