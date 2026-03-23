/**
 * Claude Usage Monitor Bridge — Service Worker
 * Collecte les données d'usage depuis claude.ai et les envoie au backend local.
 */

const BACKEND_URL = 'http://127.0.0.1:8420';
const ALARM_NAME = 'scrape-usage';
const DEFAULT_INTERVAL_MINUTES = 30;

// ── Initialisation ──────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(() => {
  setupAlarm();
});

chrome.runtime.onStartup.addListener(() => {
  setupAlarm();
});

// Répondre aux messages du popup
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.action === 'scrape_now') {
    scrapeAndPush().then(() => sendResponse({ ok: true }));
    return true; // async response
  }
  if (message.action === 'update_interval') {
    const minutes = message.minutes || DEFAULT_INTERVAL_MINUTES;
    chrome.storage.local.set({ scrapeIntervalMinutes: minutes }, () => {
      chrome.alarms.clear(ALARM_NAME, () => {
        chrome.alarms.create(ALARM_NAME, { periodInMinutes: minutes });
        sendResponse({ ok: true });
      });
    });
    return true;
  }
  if (message.action === 'get_status') {
    chrome.storage.local.get(['lastScrape', 'scrapeIntervalMinutes'], (result) => {
      sendResponse({
        lastScrape: result.lastScrape || null,
        intervalMinutes: result.scrapeIntervalMinutes || DEFAULT_INTERVAL_MINUTES,
      });
    });
    return true;
  }
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) {
    scrapeAndPush();
  }
});

// ── Logique principale ───────────────────────────────────────────────────────

async function scrapeAndPush() {
  // 1. Récupérer les cookies claude.ai
  let sessionCookie, orgCookie;
  try {
    [sessionCookie, orgCookie] = await Promise.all([
      chrome.cookies.get({ url: 'https://claude.ai', name: 'sessionKey' }),
      chrome.cookies.get({ url: 'https://claude.ai', name: 'lastActiveOrg' }),
    ]);
  } catch (e) {
    updateStatus({ error: 'cookies_error', message: String(e) });
    return;
  }

  if (!sessionCookie?.value || !orgCookie?.value) {
    updateStatus({ error: 'not_logged_in', message: 'Non connecté à claude.ai' });
    return;
  }

  // 2. Appel API usage (TLS natif Chrome — Cloudflare ne bloque pas)
  const orgId = orgCookie.value;
  let raw;
  try {
    const resp = await fetch(
      `https://claude.ai/api/organizations/${orgId}/usage`,
      {
        method: 'GET',
        headers: {
          'anthropic-client-platform': 'web_claude_ai',
          'anthropic-client-version': '1.0.0',
          accept: 'application/json',
          'content-type': 'application/json',
        },
        credentials: 'include',
      }
    );

    if (resp.status === 401) {
      updateStatus({ error: 'session_expired', message: 'Session expirée — reconnectez-vous à claude.ai' });
      return;
    }
    if (!resp.ok) {
      updateStatus({ error: 'api_error', status: resp.status, message: `HTTP ${resp.status}` });
      return;
    }
    raw = await resp.json();
  } catch (e) {
    updateStatus({ error: 'fetch_error', message: String(e) });
    return;
  }

  // 3. Parser la réponse
  const parsed = parseApiResponse(raw);
  if (!parsed) {
    updateStatus({ error: 'parse_error', message: 'Données d\'usage manquantes dans la réponse' });
    return;
  }

  // 4. POST vers le backend local
  try {
    const pushResp = await fetch(`${BACKEND_URL}/api/bridge/usage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(parsed),
    });
    const pushResult = await pushResp.json();
    updateStatus({
      ok: true,
      data: parsed,
      entry_id: pushResult.entry_id,
      timestamp: new Date().toISOString(),
    });
  } catch (_e) {
    // Backend non joignable — stocker quand même les données localement
    updateStatus({
      ok: false,
      error: 'backend_unreachable',
      message: 'Backend local non joignable',
      data: parsed,
      timestamp: new Date().toISOString(),
    });
  }
}

// ── Parsing ──────────────────────────────────────────────────────────────────

function parseApiResponse(data) {
  const sevenDay = data.seven_day || {};
  const sevenDaySonnet = data.seven_day_sonnet || {};
  const fiveHour = data.five_hour || {};

  const allModels = sevenDay.utilization;
  if (allModels === null || allModels === undefined) return null;

  return {
    all_models_pct: Math.round(allModels),
    sonnet_pct: Math.round(sevenDaySonnet.utilization || 0),
    session_utilization: Math.round(fiveHour.utilization || 0),
    reset_all_models: formatReset(sevenDay.resets_at),
    reset_sonnet: formatReset(sevenDaySonnet.resets_at),
    session_reset: formatReset(fiveHour.resets_at),
  };
}

function formatReset(resetAt) {
  if (!resetAt) return null;
  try {
    const dt = new Date(resetAt);
    const days = ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam'];
    return (
      days[dt.getDay()] +
      ' ' +
      String(dt.getHours()).padStart(2, '0') +
      ':' +
      String(dt.getMinutes()).padStart(2, '0')
    );
  } catch {
    return resetAt;
  }
}

// ── Statut et badge ──────────────────────────────────────────────────────────

function updateStatus(status) {
  chrome.storage.local.set({ lastScrape: status });

  if (status.data) {
    const pct = status.data.all_models_pct;
    chrome.action.setBadgeText({ text: pct + '%' });
    chrome.action.setBadgeBackgroundColor({
      color: pct >= 90 ? '#ef4444' : pct >= 70 ? '#f59e0b' : '#22c55e',
    });
  } else if (status.error) {
    chrome.action.setBadgeText({ text: '!' });
    chrome.action.setBadgeBackgroundColor({ color: '#ef4444' });
  }
}

// ── Alarm setup ──────────────────────────────────────────────────────────────

function setupAlarm() {
  chrome.storage.local.get('scrapeIntervalMinutes', (result) => {
    const interval = result.scrapeIntervalMinutes || DEFAULT_INTERVAL_MINUTES;
    chrome.alarms.get(ALARM_NAME, (existing) => {
      if (!existing) {
        chrome.alarms.create(ALARM_NAME, { periodInMinutes: interval });
      }
    });
    // Scraper immédiatement au démarrage
    scrapeAndPush();
  });
}
