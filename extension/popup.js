/**
 * Claude Usage Monitor Bridge — Popup script
 */

const BACKEND_URL = 'http://127.0.0.1:8420';

// ── DOM refs ─────────────────────────────────────────────────────────────────

const connectionDot  = document.getElementById('connectionDot');
const statusBar      = document.getElementById('statusBar');
const dataSection    = document.getElementById('dataSection');
const allModelsPct   = document.getElementById('allModelsPct');
const sonnetPct      = document.getElementById('sonnetPct');
const sessionPct     = document.getElementById('sessionPct');
const resetAllModels = document.getElementById('resetAllModels');
const timestampRow   = document.getElementById('timestampRow');
const intervalSelect = document.getElementById('intervalSelect');
const btnRefresh     = document.getElementById('btnRefresh');
const btnDashboard   = document.getElementById('btnDashboard');
const backendStatus  = document.getElementById('backendStatus');

// ── Init ─────────────────────────────────────────────────────────────────────

async function init() {
  // Charger le statut actuel depuis le service worker
  chrome.runtime.sendMessage({ action: 'get_status' }, (resp) => {
    if (resp) {
      intervalSelect.value = String(resp.intervalMinutes || 30);
      renderStatus(resp.lastScrape);
    }
  });

  // Vérifier le backend
  checkBackend();
}

// ── Render ────────────────────────────────────────────────────────────────────

function renderStatus(lastScrape) {
  if (!lastScrape) {
    setStatus('loading', 'En attente du premier scrape…');
    connectionDot.className = 'dot dot-unknown';
    return;
  }

  if (lastScrape.error === 'not_logged_in') {
    setStatus('error', 'Non connecté à claude.ai');
    connectionDot.className = 'dot dot-error';
    dataSection.style.display = 'none';
    return;
  }

  if (lastScrape.error === 'session_expired') {
    setStatus('error', 'Session expirée — reconnectez-vous à claude.ai');
    connectionDot.className = 'dot dot-error';
    dataSection.style.display = 'none';
    return;
  }

  if (lastScrape.error && !lastScrape.data) {
    setStatus('error', lastScrape.message || lastScrape.error);
    connectionDot.className = 'dot dot-error';
    dataSection.style.display = 'none';
    return;
  }

  if (lastScrape.data) {
    const d = lastScrape.data;
    const backendOk = lastScrape.ok !== false;

    connectionDot.className = 'dot ' + (backendOk ? 'dot-ok' : 'dot-warn');
    setStatus(
      backendOk ? 'ok' : 'warn',
      backendOk ? 'Connecté · données envoyées au backend' : 'Données collectées · backend non joignable'
    );

    dataSection.style.display = 'block';
    setPctValue(allModelsPct, d.all_models_pct);
    setPctValue(sonnetPct, d.sonnet_pct);
    setPctValue(sessionPct, d.session_utilization);

    const resets = [
      d.reset_all_models ? `Tous: ${d.reset_all_models}` : null,
      d.reset_sonnet ? `Sonnet: ${d.reset_sonnet}` : null,
    ].filter(Boolean).join('  ·  ');
    resetAllModels.textContent = resets ? `Reset: ${resets}` : '';

    if (lastScrape.timestamp) {
      timestampRow.textContent = 'Mis à jour ' + timeAgo(lastScrape.timestamp);
    }
  }
}

function setPctValue(el, pct) {
  el.textContent = pct + '%';
  el.className = 'metric-value ' + (pct >= 90 ? 'pct-red' : pct >= 70 ? 'pct-amber' : 'pct-green');
}

function setStatus(type, text) {
  statusBar.textContent = text;
  statusBar.className = 'status-bar status-' + type;
}

function timeAgo(iso) {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return 'il y a ' + diff + ' s';
  if (diff < 3600) return 'il y a ' + Math.floor(diff / 60) + ' min';
  if (diff < 86400) return 'il y a ' + Math.floor(diff / 3600) + ' h';
  return 'il y a ' + Math.floor(diff / 86400) + ' j';
}

// ── Backend check ─────────────────────────────────────────────────────────────

async function checkBackend() {
  try {
    const resp = await fetch(`${BACKEND_URL}/api/status`, { signal: AbortSignal.timeout(2000) });
    if (resp.ok) {
      const data = await resp.json();
      backendStatus.textContent = `Backend v${data.version || '?'} · ${BACKEND_URL}`;
    } else {
      backendStatus.textContent = 'Backend: erreur HTTP ' + resp.status;
    }
  } catch {
    backendStatus.textContent = 'Backend non joignable sur ' + BACKEND_URL;
  }
}

// ── Événements ────────────────────────────────────────────────────────────────

btnRefresh.addEventListener('click', () => {
  btnRefresh.disabled = true;
  btnRefresh.textContent = 'Scraping…';
  chrome.runtime.sendMessage({ action: 'scrape_now' }, () => {
    // Attendre un peu puis recharger le statut
    setTimeout(() => {
      chrome.runtime.sendMessage({ action: 'get_status' }, (resp) => {
        if (resp) renderStatus(resp.lastScrape);
        btnRefresh.disabled = false;
        btnRefresh.textContent = 'Rafraîchir';
      });
    }, 1500);
  });
});

btnDashboard.addEventListener('click', () => {
  chrome.tabs.create({ url: BACKEND_URL });
});

intervalSelect.addEventListener('change', () => {
  const minutes = parseInt(intervalSelect.value, 10);
  chrome.runtime.sendMessage({ action: 'update_interval', minutes });
});

// ── Start ─────────────────────────────────────────────────────────────────────

init();
