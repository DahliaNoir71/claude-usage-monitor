/**
 * Claude Usage Monitor - Consolidated Module Functions
 * Includes all dashboard functions for all tabs
 */

// ============================================================
// Global State
// ============================================================
const APP_STATE = {
  allEntries: [],
  filteredEntries: [],
  historyPage: 1,
  historyPageSize: 50,
  plansData: {},
  plansAnalysis: null,
  settingsCache: {},
  charts: {},
};

const MONTH_NAMES = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc'];

// ============================================================
// Color Palette
// ============================================================
const C = {
  accent: '#6366f1', accentA: 'rgba(99,102,241,0.15)',
  green: '#22c55e', greenA: 'rgba(34,197,94,0.15)',
  amber: '#f59e0b', amberA: 'rgba(245,158,11,0.15)',
  red: '#ef4444', redA: 'rgba(239,68,68,0.15)',
  blue: '#3b82f6', blueA: 'rgba(59,130,246,0.15)',
  pink: '#ec4899', pinkA: 'rgba(236,72,153,0.15)',
  teal: '#14b8a6', gray: '#6b7280',
  grid: 'rgba(255,255,255,0.04)', tick: '#5a5850',
};

const baseOpts = {
  responsive: true, maintainAspectRatio: false,
  plugins: { legend: { display: false } },
  scales: {
    y: { ticks: { color: C.tick }, grid: { color: C.grid } },
    x: { ticks: { color: C.tick, maxRotation: 45 }, grid: { display: false } },
  },
};

// ============================================================
// API Helper
// ============================================================
const api = async (path, opts) => {
  const r = await fetch(path, opts);
  return r.json();
};

// ============================================================
// Color Helpers
// ============================================================
function pctColor(v) {
  if (v < 30) return 'amber';
  if (v < 70) return 'blue';
  if (v < 90) return 'green';
  return 'red';
}

function pctColorHex(v) {
  if (v < 30) return '#f59e0b';
  if (v < 70) return '#3b82f6';
  if (v < 90) return '#22c55e';
  return '#ef4444';
}

// ============================================================
// Chart Helpers
// ============================================================
function kill(id) {
  if (APP_STATE.charts[id]) {
    APP_STATE.charts[id].destroy();
    delete APP_STATE.charts[id];
  }
}

function exportChartPNG(chartId) {
  const chart = APP_STATE.charts[chartId];
  if (!chart) return;
  const url = chart.toBase64Image('image/png', 1);
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const a = document.createElement('a');
  a.href = url;
  a.download = 'claude-monitor_' + chartId.replace('Chart', '') + '_' + date + '.png';
  a.click();
}

function addExportButtons() {
  document.querySelectorAll('.chart-box').forEach(box => {
    if (box.querySelector('.btn-export-png')) return;
    const canvas = box.querySelector('canvas');
    if (!canvas) return;
    const btn = document.createElement('button');
    btn.className = 'btn-export-png';
    btn.title = 'Exporter en PNG';
    btn.innerHTML = '&#128247;';
    btn.onclick = () => exportChartPNG(canvas.id);
    box.appendChild(btn);
  });
}

// ============================================================
// Utils
// ============================================================
function timeSince(date) {
  const s = Math.floor((Date.now() - date.getTime()) / 1000);
  if (s < 60) return 'à l\'instant';
  if (s < 3600) return Math.floor(s/60) + ' min';
  if (s < 86400) return Math.floor(s/3600) + ' h';
  return Math.floor(s/86400) + ' j';
}

function formatTokens(num) {
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + 'M';
  if (num >= 1_000) return (num / 1_000).toFixed(1) + 'K';
  return num.toString();
}

function formatNumber(num) {
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + 'M';
  if (num >= 1_000) return (num / 1_000).toFixed(1) + 'K';
  return num.toString();
}

// ============================================================
// OVERVIEW
// ============================================================
async function loadOverview() {
  const [analysis, status, cycleStats, ccStatus] = await Promise.all([
    api('/api/analysis'),
    api('/api/status'),
    api('/api/cycle-stats'),
    api('/api/claude-code/status').catch(() => ({ detected: false })),
  ]);

  // Cards
  const el = document.getElementById('overviewCards');
  if (analysis.status === 'no_data') {
    el.innerHTML = '<div class="card"><div class="card-label">Aucune donnée</div><div class="card-sub">Importe un CSV ou lance un scraping depuis l\'onglet Historique.</div></div>';
    return;
  }

  const latest = analysis.latest;
  const r = analysis.recommendation;
  const ms = analysis.monthly_stats || [];
  const currentMonth = ms.length ? ms[ms.length - 1] : null;
  const prevMonth = ms.length > 1 ? ms[ms.length - 2] : null;
  const trend = r && r.stats ? r.stats.trend : 'stable';
  const trendIcon = trend === 'rising' ? '&#8599;' : trend === 'falling' ? '&#8600;' : '&#8594;';
  const trendLabel = trend === 'rising' ? 'Hausse' : trend === 'falling' ? 'Baisse' : 'Stable';

  el.innerHTML = `
    <div class="card">
      <div class="card-label">Usage ce mois</div>
      <div class="card-value ${pctColor(currentMonth ? currentMonth.max_all_models : 0)}">${currentMonth ? currentMonth.max_all_models : 0}%</div>
      <div class="card-sub">Pic All Models &middot; Moy: ${currentMonth ? currentMonth.avg_all_models : 0}%</div>
    </div>
    <div class="card">
      <div class="card-label">Mois précédent</div>
      <div class="card-value ${pctColor(prevMonth ? prevMonth.max_all_models : 0)}">${prevMonth ? prevMonth.max_all_models : '-'}${prevMonth ? '%' : ''}</div>
      <div class="card-sub">${prevMonth ? 'Pic All Models' : 'Pas de données'}</div>
    </div>
    <div class="card">
      <div class="card-label">Jours actifs</div>
      <div class="card-value accent">${currentMonth ? currentMonth.active_days : 0}</div>
      <div class="card-sub">${currentMonth ? currentMonth.entries_count : 0} ${(currentMonth?.entries_count ?? 0) > 1 ? 'mesures' : 'mesure'} ce mois</div>
    </div>
    <div class="card">
      <div class="card-label">Tendance</div>
      <div class="card-value" style="font-size:22px">${trendIcon} ${trendLabel}</div>
      <div class="card-sub">${ms.length} mois analysés</div>
    </div>
  `;

  // Freshness indicator
  const freshEl = document.createElement('div');
  freshEl.style.cssText = 'font-size:12px;color:var(--text-dim);margin:-16px 0 20px;';
  if (latest && latest.timestamp) {
    const ago = timeSince(new Date(latest.timestamp));
    const msAgo = Date.now() - new Date(latest.timestamp).getTime();
    const stale = msAgo > 24 * 3600 * 1000;
    freshEl.style.color = stale ? 'var(--amber)' : 'var(--text-dim)';
    freshEl.innerHTML = (stale ? '&#9888; ' : '') + 'Dernière mesure : il y a ' + ago;
    freshEl.title = new Date(latest.timestamp).toLocaleString('fr');
  }
  el.after(freshEl);

  // Detail cards (secondary)
  const detailEl = document.createElement('div');
  detailEl.className = 'cards';
  detailEl.style.marginBottom = '24px';
  detailEl.innerHTML = `
    <div class="card">
      <div class="card-label">All Models (actuel)</div>
      <div class="card-value ${pctColor(latest.all_models_pct)}">${latest.all_models_pct}%</div>
      <div class="card-sub">Max global: ${analysis.all_models.max_ever}% &middot; Moy: ${analysis.all_models.avg}%</div>
    </div>
    <div class="card">
      <div class="card-label">Sonnet (actuel)</div>
      <div class="card-value ${pctColor(latest.sonnet_pct || 0)}">${latest.sonnet_pct || 0}%</div>
      <div class="card-sub">${latest.reset_sonnet || '-'}</div>
    </div>
    <div class="card">
      <div class="card-label">Jours couverts</div>
      <div class="card-value accent">${analysis.days_covered}</div>
      <div class="card-sub">${status.entries_count} entrées</div>
    </div>
    <div class="card" id="resetCountdownCard" style="display:none">
      <div class="card-label">Prochain reset estimé</div>
      <div class="card-value accent" id="resetCountdown" style="font-size:20px">--</div>
      <div class="card-sub" id="resetCountdownSub"></div>
    </div>
  `;
  freshEl.after(detailEl);

  // Reset countdown
  if (cycleStats && cycleStats.has_data && cycleStats.next_reset_estimate) {
    const card = document.getElementById('resetCountdownCard');
    card.style.display = '';
    const resetDate = new Date(cycleStats.next_reset_estimate);
    const subEl = document.getElementById('resetCountdownSub');
    if (cycleStats.source === 'scraper') {
      subEl.textContent = 'Source : données scraper';
    } else if (cycleStats.median_cycle_hours) {
      subEl.textContent = 'Basé sur une moyenne de ' + cycleStats.median_cycle_hours + 'h par cycle';
    }
    if (!cycleStats.reliable) {
      subEl.textContent += ' (estimation peu fiable)';
    }
    function updateCountdown() {
      const diff = resetDate.getTime() - Date.now();
      const el = document.getElementById('resetCountdown');
      if (!el) return;
      if (diff <= 0) {
        el.textContent = 'Imminent';
        el.className = 'card-value green';
        return;
      }
      const h = Math.floor(diff / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      const s = Math.floor((diff % 60000) / 1000);
      el.textContent = '~' + (h > 0 ? h + 'h ' : '') + m + 'min ' + s + 's';
    }
    updateCountdown();
    setInterval(updateCountdown, 1000);
  }

  renderReco(document.getElementById('overviewReco'), r);
  renderVelocityChart(analysis);
  renderHourlyChart(analysis);

  // Phase 4.1: Combined timeline (web + Claude Code)
  try {
    const timeline = await api('/api/timeline/combined?days=90');
    renderCombinedTimeline(timeline);
  } catch (e) {
    console.warn('Could not load combined timeline:', e);
  }

  // Phase 3.1: Split consumption
  const splitSection = document.createElement('div');
  splitSection.className = 'chart-section';
  splitSection.style.marginTop = '24px';

  const proj = r && r.stats && r.stats.projected_usage ? r.stats.projected_usage : null;
  const currentMax = analysis.all_models ? analysis.all_models.max_ever : 0;

  if (proj) {
    const plans = [
      { key: 'pro', name: 'Pro ($20)', price: 20 },
      { key: 'max_100', name: 'Max $100', price: 100 },
      { key: 'max_200', name: 'Max $200', price: 200 },
    ];

    const barsHtml = plans.map(p => {
      const val = proj[p.key];
      if (val === null || val === undefined) return '';
      const isCurrent = p.key === analysis.current_plan;
      const capped = Math.min(val, 150);
      const barWidth = Math.max(2, Math.min(100, capped * 100 / 150));
      const color = val > 100 ? 'var(--red)' : val > 80 ? 'var(--amber)' : 'var(--green)';
      const label = val > 100 ? '⛔ Rate-limité' : val > 80 ? '⚠️ Risqué' : '✅ OK';
      return `
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
          <div style="width:100px;font-size:12px;font-weight:${isCurrent ? '600' : '400'};color:${isCurrent ? 'var(--accent)' : 'var(--text-muted)'}">${p.name}${isCurrent ? ' ●' : ''}</div>
          <div style="flex:1;height:24px;background:var(--bg-surface);border-radius:4px;overflow:hidden;position:relative">
            <div style="width:${barWidth}%;height:100%;background:${color};border-radius:4px;transition:width 0.3s"></div>
            <div style="position:absolute;right:${val > 100 ? 'auto' : '8px'};left:${val > 100 ? '8px' : 'auto'};top:50%;transform:translateY(-50%);font-size:11px;color:white;font-weight:500">${val}%</div>
          </div>
          <div style="width:100px;font-size:11px;color:var(--text-dim)">${label}</div>
        </div>
      `;
    }).join('');

    splitSection.innerHTML = `
      <div class="chart-header">
        <div>
          <div class="chart-title">Projection sur les plans</div>
          <div class="chart-subtitle">Si ton usage actuel (pic ${currentMax}%) était sur un autre plan, tu serais à :</div>
        </div>
      </div>
      <div class="chart-box">
        ${barsHtml}
        <div style="margin-top:12px;font-size:11px;color:var(--text-dim)">
          Barres : % d'utilisation projeté. Au-delà de 100% = rate-limité. Inclut le chat web + Claude Code + Desktop.
        </div>
      </div>
    `;
  } else {
    splitSection.innerHTML = `
      <div class="chart-header">
        <div>
          <div class="chart-title">Projection sur les plans</div>
          <div class="chart-subtitle">Pas assez de données pour projeter.</div>
        </div>
      </div>
      <div class="chart-box" style="padding:24px;text-align:center;color:var(--text-dim)">
        <p>Importe des données ou lance un scraping pour voir les projections.</p>
      </div>
    `;
  }
  document.getElementById('hourlyChart').parentElement.parentElement.after(splitSection);

  setTimeout(addExportButtons, 100);
}

function renderReco(container, r) {
  if (!r) return;
  const cls = r.action.includes('downgrade') ? 'downgrade' : r.action === 'upgrade' ? 'upgrade' : 'maintain';
  const icons = { downgrade: '&#128176;', maintain: '&#9989;', upgrade: '&#128200;', consider_downgrade: '&#128161;' };
  const icon = icons[r.action] || '&#128202;';
  let html = `
    <div class="reco ${cls}">
      <div class="reco-title">${icon} ${r.plan_name} recommandé</div>
      <div class="reco-body">${r.reason}</div>
      ${r.savings_yearly > 0 ? `<div class="reco-body" style="margin-top:4px;font-weight:500">Économie : $${r.savings_monthly}/mois ($${r.savings_yearly}/an)</div>` : ''}
      <div class="reco-badge" style="background:var(--bg-surface);color:var(--text-dim)">${r.action.replace('_', ' ')} &middot; confiance ${r.confidence}</div>
    </div>`;
  if (r.caveats && r.caveats.length) {
    html += `
    <div style="padding:12px 16px;border-radius:var(--radius);margin-top:8px;margin-bottom:24px;border:1px solid var(--border);background:var(--bg-card);font-size:12px;color:var(--text-muted);line-height:1.6">
      ${r.caveats.map(c => '<div style="margin-bottom:4px">&#9432; ' + c + '</div>').join('')}
    </div>`;
  }
  container.innerHTML = html;
}

function renderVelocityChart(data) {
  if (!data.daily_velocity || !data.daily_velocity.length) return;
  kill('velocityChart');
  const dv = data.daily_velocity;
  APP_STATE.charts['velocityChart'] = new Chart(document.getElementById('velocityChart'), {
    type: 'bar',
    data: {
      labels: dv.map(d => d.date.slice(5)),
      datasets: [
        { label: 'Min', data: dv.map(d => d.min), backgroundColor: 'rgba(99,102,241,0.25)', borderRadius: 4 },
        { label: 'Delta', data: dv.map(d => d.delta), backgroundColor: C.accent, borderRadius: 4 },
      ]
    },
    options: { ...baseOpts,
      plugins: { ...baseOpts.plugins, tooltip: { mode: 'index' } },
      scales: {
        x: { ...baseOpts.scales.x, stacked: true, ticks: { ...baseOpts.scales.x.ticks, autoSkip: true, maxTicksLimit: 15 } },
        y: { ...baseOpts.scales.y, stacked: true, ticks: { ...baseOpts.scales.y.ticks, callback: v => v + '%' } },
      }
    }
  });
}

function renderHourlyChart(data) {
  if (!data.hourly_distribution) return;
  kill('hourlyChart');
  const hours = Array.from({length: 24}, (_, i) => i);
  const dist = data.hourly_distribution;
  APP_STATE.charts['hourlyChart'] = new Chart(document.getElementById('hourlyChart'), {
    type: 'bar',
    data: {
      labels: hours.map(h => h + 'h'),
      datasets: [{
        data: hours.map(h => dist[h] || 0),
        backgroundColor: hours.map(h => (dist[h] || 0) > 0 ? C.accent : C.grid),
        borderRadius: 4,
      }]
    },
    options: baseOpts,
  });
}

function renderCombinedTimeline(data) {
  if (!data || !data.length) return;

  // Create section if it doesn't exist
  const hourlyChart = document.getElementById('hourlyChart');
  if (!hourlyChart) return;

  const container = hourlyChart.parentElement.parentElement;
  let section = container.querySelector('[data-timeline-section]');
  if (!section) {
    section = document.createElement('div');
    section.className = 'chart-section';
    section.setAttribute('data-timeline-section', '');
    section.style.marginTop = '24px';
    container.after(section);
  }

  kill('combinedTimeline');
  const labels = data.map(d => d.date.split('-')[2]);
  const webPct = data.map(d => d.all_models_pct || 0);
  const ccTokens = data.map(d => d.tokens_claude_code || 0);

  // Normalize tokens to make them visible on same chart (0-100 scale approximate)
  const maxTokens = Math.max(...ccTokens) || 1;
  const ccTokensNorm = ccTokens.map(t => (t / maxTokens) * 100);

  section.innerHTML = `
    <div class="chart-header">
      <div>
        <div class="chart-title">Timeline combinée</div>
        <div class="chart-subtitle">Usage web (%) vs Claude Code (tokens normalisés)</div>
      </div>
    </div>
    <div class="chart-box">
      <div class="chart-wrap" style="height:280px"><canvas id="combinedTimeline"></canvas></div>
    </div>
  `;

  APP_STATE.charts['combinedTimeline'] = new Chart(document.getElementById('combinedTimeline'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'All Models %',
          data: webPct,
          borderColor: C.accent,
          backgroundColor: C.accentA,
          fill: true,
          tension: 0.3,
          pointRadius: 2,
          yAxisID: 'y',
        },
        {
          label: 'Claude Code (tokens normalisés)',
          data: ccTokensNorm,
          borderColor: C.blue,
          backgroundColor: C.blueA,
          fill: true,
          tension: 0.3,
          pointRadius: 2,
          yAxisID: 'y1',
        },
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, labels: { color: C.tick, boxWidth: 10 } },
        tooltip: {
          callbacks: {
            afterLabel: (ctx) => {
              if (ctx.datasetIndex === 1) {
                const maxTokens = Math.max(...ccTokens);
                const actualTokens = (ctx.parsed.y / 100) * maxTokens;
                return `(~${formatNumber(actualTokens)} tokens)`;
              }
              return '';
            }
          }
        }
      },
      scales: {
        y: {
          type: 'linear',
          display: true,
          position: 'left',
          title: { display: true, text: 'Usage Web (%)', color: C.tick },
          ticks: { color: C.tick, callback: v => v + '%' },
          grid: { color: C.grid },
          max: 100,
        },
        y1: {
          type: 'linear',
          display: true,
          position: 'right',
          min: 0,
          title: { display: true, text: 'Claude Code (tokens relatifs)', color: C.tick },
          ticks: { color: C.tick },
          grid: { drawOnChartArea: false },
        },
        x: {
          ticks: { color: C.tick, maxRotation: 45, autoSkip: true, maxTicksLimit: 30 },
          grid: { display: false },
        },
      },
    },
  });
}

// ============================================================
// HISTORY
// ============================================================
async function loadHistory() {
  const entries = await api('/api/entries');
  document.getElementById('historyCount').textContent = entries.length + (entries.length > 1 ? ' entrées' : ' entrée');
  renderHistoryChart(entries);
  renderEntriesTable(entries);
}

function renderHistoryChart(entries) {
  if (!entries || !entries.length) return;
  kill('historyChart');
  const step = Math.max(1, Math.floor(entries.length / 200));
  const sampled = entries.filter((_, i) => i % step === 0);
  APP_STATE.charts['historyChart'] = new Chart(document.getElementById('historyChart'), {
    type: 'line',
    data: {
      labels: sampled.map(e => { const d = new Date(e.timestamp); return (d.getMonth()+1)+'/'+d.getDate()+' '+d.getHours()+'h'; }),
      datasets: [
        { label: 'All Models %', data: sampled.map(e => e.all_models_pct), borderColor: C.accent, backgroundColor: C.accentA, fill: true, tension: 0.2, pointRadius: 1 },
        { label: 'Sonnet %', data: sampled.map(e => e.sonnet_pct), borderColor: C.pink, backgroundColor: C.pinkA, fill: true, tension: 0.2, pointRadius: 1 },
      ]
    },
    options: { ...baseOpts,
      plugins: { legend: { display: true, labels: { color: C.tick, boxWidth: 10 } } },
      scales: { ...baseOpts.scales, y: { ...baseOpts.scales.y, max: 100 } }
    }
  });
}

function renderEntriesTable(entries) {
  APP_STATE.allEntries = entries.slice().reverse();
  const months = [...new Set(APP_STATE.allEntries.map(e => e.timestamp.slice(0, 7)))].sort().reverse();
  const sel = document.getElementById('historyMonthFilter');
  sel.innerHTML = '<option value="">Tous les mois</option>' + months.map(m => `<option value="${m}">${m}</option>`).join('');
  APP_STATE.historyPage = 1;
  applyHistoryFilter();
}

function applyHistoryFilter() {
  const monthFilter = document.getElementById('historyMonthFilter').value;
  APP_STATE.filteredEntries = monthFilter ? APP_STATE.allEntries.filter(e => e.timestamp.startsWith(monthFilter)) : APP_STATE.allEntries;
  APP_STATE.historyPage = 1;
  renderEntriesPage();
}

function renderEntriesPage() {
  const container = document.getElementById('entriesTable');
  if (!APP_STATE.filteredEntries.length) {
    container.innerHTML = '<p style="padding:16px;color:var(--text-dim)">Aucune entrée</p>';
    document.getElementById('historyPagination').innerHTML = '';
    return;
  }

  const total = APP_STATE.filteredEntries.length;
  const pageSize = APP_STATE.historyPageSize || total;
  const totalPages = pageSize > 0 ? Math.ceil(total / pageSize) : 1;
  APP_STATE.historyPage = Math.min(APP_STATE.historyPage, totalPages);
  const start = (APP_STATE.historyPage - 1) * pageSize;
  const page = pageSize > 0 ? APP_STATE.filteredEntries.slice(start, start + pageSize) : APP_STATE.filteredEntries;

  const rows = page.map(e => {
    const d = new Date(e.timestamp);
    return `<tr>
      <td>${d.toLocaleDateString('fr')}</td>
      <td>${d.toLocaleTimeString('fr', {hour:'2-digit',minute:'2-digit'})}</td>
      <td style="color:${pctColorHex(e.all_models_pct)}">${e.all_models_pct}%</td>
      <td>${e.sonnet_pct || 0}%</td>
      <td style="font-size:11px">${e.reset_all_models || '-'}</td>
      <td style="font-size:11px">${e.reset_sonnet || '-'}</td>
      <td style="font-size:11px;color:var(--text-dim)">${e.source || ''}</td>
      <td><button class="btn-delete" onclick="deleteEntry(${e.id}, this)" title="Supprimer">&#10005;</button></td>
    </tr>`;
  }).join('');
  container.innerHTML = `
    <table>
      <thead><tr><th>Date</th><th>Heure</th><th>All Models</th><th>Sonnet</th><th>Reset All</th><th>Reset Sonnet</th><th>Source</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;

  const pagEl = document.getElementById('historyPagination');
  if (totalPages <= 1) {
    pagEl.innerHTML = `<span>${total} ${total > 1 ? 'entrées' : 'entrée'}</span>`;
    return;
  }
  let pagHtml = `<button class="btn" onclick="APP_STATE.historyPage=Math.max(1,APP_STATE.historyPage-1);renderEntriesPage()" ${APP_STATE.historyPage<=1?'disabled':''}>&#8592; Préc.</button>`;
  const maxButtons = 5;
  let pStart = Math.max(1, APP_STATE.historyPage - Math.floor(maxButtons / 2));
  let pEnd = Math.min(totalPages, pStart + maxButtons - 1);
  pStart = Math.max(1, pEnd - maxButtons + 1);
  for (let p = pStart; p <= pEnd; p++) {
    pagHtml += `<button class="btn${p===APP_STATE.historyPage?' btn-accent':''}" onclick="APP_STATE.historyPage=${p};renderEntriesPage()" style="min-width:32px">${p}</button>`;
  }
  pagHtml += `<button class="btn" onclick="APP_STATE.historyPage=Math.min(${totalPages},APP_STATE.historyPage+1);renderEntriesPage()" ${APP_STATE.historyPage>=totalPages?'disabled':''}>Suiv. &#8594;</button>`;
  pagHtml += `<span style="margin-left:8px">Page ${APP_STATE.historyPage}/${totalPages} — ${total} ${total > 1 ? 'entrées' : 'entrée'}</span>`;
  pagEl.innerHTML = pagHtml;
}

// ============================================================
// CYCLES
// ============================================================
async function loadCycles() {
  const [monthly, weekly, sonnet, resets] = await Promise.all([
    api('/api/monthly'),
    api('/api/weekly'),
    api('/api/sonnet-cycles'),
    api('/api/resets'),
  ]);
  renderMonthlyChart(monthly);
  renderWeeklyChart(weekly);
  renderSonnetChart(sonnet);
  renderResetsTable(resets);
}

function renderMonthlyChart(months) {
  if (!months || !months.length) return;
  kill('monthlyChart');
  const labels = months.map(m => {
    const [y, mo] = m.month.split('-');
    return MONTH_NAMES[parseInt(mo) - 1] + ' ' + y.slice(2);
  });
  APP_STATE.charts['monthlyChart'] = new Chart(document.getElementById('monthlyChart'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'All Models pic', data: months.map(m => m.max_all_models || 0), backgroundColor: C.accent, borderRadius: 4 },
        { label: 'Sonnet pic', data: months.map(m => m.max_sonnet || 0), backgroundColor: C.pink, borderRadius: 4 },
      ]
    },
    options: { ...baseOpts,
      plugins: {
        legend: { display: true, labels: { color: C.tick, boxWidth: 10 } },
        annotation: undefined,
      },
      scales: { ...baseOpts.scales,
        y: { ...baseOpts.scales.y, max: 100, ticks: { ...baseOpts.scales.y.ticks, callback: v => v + '%' } },
      },
    },
    plugins: [{
      id: 'rateLimitLine',
      afterDraw(chart) {
        const yScale = chart.scales.y;
        const y = yScale.getPixelForValue(80);
        const ctx = chart.ctx;
        ctx.save();
        ctx.setLineDash([6, 4]);
        ctx.strokeStyle = C.red;
        ctx.lineWidth = 1;
        ctx.globalAlpha = 0.5;
        ctx.beginPath();
        ctx.moveTo(chart.chartArea.left, y);
        ctx.lineTo(chart.chartArea.right, y);
        ctx.stroke();
        ctx.restore();
      }
    }]
  });
}

function renderWeeklyChart(weeks) {
  if (!weeks || !weeks.length) return;
  kill('weeklyChart');
  APP_STATE.charts['weeklyChart'] = new Chart(document.getElementById('weeklyChart'), {
    type: 'bar',
    data: {
      labels: weeks.map(w => w.week || w.week_start || ''),
      datasets: [
        { label: 'All Models pic', data: weeks.map(w => w.max_all_models || 0), backgroundColor: C.accent, borderRadius: 4 },
        { label: 'Sonnet pic', data: weeks.map(w => w.max_sonnet || 0), backgroundColor: C.pink, borderRadius: 4 },
      ]
    },
    options: { ...baseOpts,
      plugins: { legend: { display: true, labels: { color: C.tick, boxWidth: 10 } } },
      scales: { ...baseOpts.scales,
        y: { ...baseOpts.scales.y, max: 100, ticks: { ...baseOpts.scales.y.ticks, callback: v => v + '%' } },
        x: { ...baseOpts.scales.x, ticks: { ...baseOpts.scales.x.ticks, autoSkip: true, maxTicksLimit: 12 } }
      }
    }
  });
}

function renderSonnetChart(cycles) {
  if (!cycles || !cycles.length) return;
  kill('sonnetChart');
  APP_STATE.charts['sonnetChart'] = new Chart(document.getElementById('sonnetChart'), {
    type: 'bar',
    data: {
      labels: cycles.map((c, i) => 'C' + (i + 1)),
      datasets: [{
        data: cycles.map(c => c.peak),
        backgroundColor: cycles.map(c => pctColorHex(c.peak)),
        borderRadius: 4,
      }]
    },
    options: { ...baseOpts,
      plugins: { ...baseOpts.plugins, tooltip: {
        callbacks: {
          title: (items) => {
            const idx = items[0].dataIndex;
            const c = cycles[idx];
            const start = new Date(c.start).toLocaleDateString('fr');
            const end = new Date(c.end).toLocaleDateString('fr');
            return 'Cycle ' + (idx + 1) + ' : ' + start + ' — ' + end;
          }
        }
      }},
      scales: { ...baseOpts.scales,
        y: { ...baseOpts.scales.y, max: 100, ticks: { ...baseOpts.scales.y.ticks, callback: v => v + '%' } },
        x: { ...baseOpts.scales.x, ticks: { ...baseOpts.scales.x.ticks, maxRotation: 45, autoSkip: true, maxTicksLimit: 20 } },
      }
    }
  });
}

function renderResetsTable(resets) {
  const el = document.getElementById('resetsTable');
  if (!resets || !resets.length) {
    el.innerHTML = '<p style="padding:16px;color:var(--text-dim)">Aucun reset détecté</p>';
    return;
  }
  const rows = resets.map(r => {
    const d = new Date(r.timestamp);
    return `<tr>
      <td>${d.toLocaleDateString('fr')}</td>
      <td>${d.toLocaleTimeString('fr', {hour:'2-digit',minute:'2-digit'})}</td>
      <td>${r.from_pct}%</td>
      <td>${r.to_pct}%</td>
      <td style="color:var(--red)">-${r.drop}%</td>
    </tr>`;
  }).join('');
  el.innerHTML = `
    <table>
      <thead><tr><th>Date</th><th>Heure</th><th>De</th><th>A</th><th>Drop</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ============================================================
// PLANS
// ============================================================
async function loadPlans() {
  const [plans, analysis] = await Promise.all([
    api('/api/plans'),
    api('/api/analysis'),
  ]);
  APP_STATE.plansData = plans;
  APP_STATE.plansAnalysis = analysis;
  renderPlansTable(plans, analysis);
}

function renderPlansTable(plans, analysis) {
  const planKeys = Object.keys(plans);
  const currentPlan = analysis.current_plan || '';
  const recoPlan = analysis.recommendation ? analysis.recommendation.plan : '';
  const ms = analysis.monthly_stats || [];
  const lastMonth = ms.length ? ms[ms.length - 1] : null;

  const priorityLabels = { low: 'Basse', normal: 'Normale', high: 'Haute', highest: 'Maximale' };

  let thead = '<tr><th>Plan</th>';
  planKeys.forEach(k => {
    const p = plans[k];
    const isCurrent = k === currentPlan;
    const isReco = k === recoPlan;
    thead += `<th style="${isReco ? 'background:var(--green-soft);color:var(--green)' : isCurrent ? 'background:var(--accent-soft);color:var(--accent)' : ''}">${p.name}${isCurrent ? ' (actuel)' : ''}${isReco && !isCurrent ? ' &#10004;' : ''}</th>`;
  });
  thead += '</tr>';

  const rows = [
    ['Prix/mois', k => '$' + plans[k].price],
    ['Modèles', k => (plans[k].models || []).join(', ')],
    ['Extended thinking', k => plans[k].extended_thinking || '&#10005;'],
    ['Priorité', k => priorityLabels[plans[k].priority] || plans[k].priority],
  ];

  if (lastMonth) {
    rows.push(['Ton pic (ce mois)', () => lastMonth.max_all_models + '%']);
    rows.push(['Ta moyenne (ce mois)', () => lastMonth.avg_all_models + '%']);
  }

  const proj = analysis.recommendation && analysis.recommendation.stats
    ? analysis.recommendation.stats.projected_usage
    : null;
  if (proj) {
    rows.push(['Ton usage projeté', k => {
      const val = proj[k];
      if (val === null || val === undefined) return '-';
      const color = val > 100 ? 'var(--red)' : val > 80 ? 'var(--amber)' : 'var(--green)';
      const label = val > 100 ? ' ⛔' : val > 80 ? ' ⚠️' : ' ✅';
      return `<span style="color:${color};font-weight:600">${val}%${label}</span>`;
    }]);
  }

  let tbody = '';
  rows.forEach(([label, fn]) => {
    tbody += `<tr><td style="font-weight:500">${label}</td>`;
    planKeys.forEach(k => {
      tbody += `<td>${fn(k)}</td>`;
    });
    tbody += '</tr>';
  });

  document.querySelector('#plansTable thead').innerHTML = thead;
  document.querySelector('#plansTable tbody').innerHTML = tbody;
}

function updateSimulator() {
  const pct = parseInt(document.getElementById('simSlider').value);
  document.getElementById('simValue').textContent = '+' + pct + '%';
  const ms = APP_STATE.plansAnalysis ? APP_STATE.plansAnalysis.monthly_stats || [] : [];
  const lastMonth = ms.length ? ms[ms.length - 1] : null;
  if (!lastMonth) {
    document.getElementById('simResult').textContent = 'Pas assez de données pour simuler.';
    return;
  }
  const simPeak = Math.min(100, Math.round(lastMonth.max_all_models * (1 + pct / 100)));
  const simAvg = Math.min(100, Math.round(lastMonth.avg_all_models * (1 + pct / 100)));
  let advice = '';
  if (simPeak <= 30) advice = 'Le plan Pro suffirait largement.';
  else if (simPeak <= 50) advice = 'Le plan Pro pourrait encore suffire.';
  else if (simPeak <= 80) advice = 'Le plan Max $100 serait recommandé.';
  else advice = 'Le plan Max $200 serait recommandé pour éviter les rate-limits.';
  document.getElementById('simResult').innerHTML =
    `Pic simulé : <strong>${simPeak}%</strong> &middot; Moyenne simulée : <strong>${simAvg}%</strong><br>${advice}`;
}

// ============================================================
// SETTINGS
// ============================================================
async function loadSettings() {
  const [config, status] = await Promise.all([
    api('/api/config'),
    api('/api/status'),
  ]);
  APP_STATE.settingsCache = { ...config };
  const form = document.getElementById('settingsForm');
  form.innerHTML = `
    <div class="setting-row">
      <div><div class="setting-label">Plan</div><div class="setting-desc">Ton abonnement Claude</div></div>
      <select id="cfg-plan" onchange="APP_STATE.settingsCache.plan=this.value">
        <option value="free" ${config.plan==='free'?'selected':''}>Free</option>
        <option value="pro" ${config.plan==='pro'?'selected':''}>Pro ($20)</option>
        <option value="max_100" ${config.plan==='max_100'?'selected':''}>Max $100</option>
        <option value="max_200" ${config.plan==='max_200'?'selected':''}>Max $200</option>
      </select>
    </div>
    <div class="setting-row">
      <div><div class="setting-label">Scraping automatique</div><div class="setting-desc">Scraper périodiquement en arrière-plan</div></div>
      <label class="toggle"><input type="checkbox" id="cfg-auto-scrape" ${config.auto_scrape?'checked':''} onchange="APP_STATE.settingsCache.auto_scrape=this.checked"><span class="toggle-slider"></span></label>
    </div>
    <div class="setting-row">
      <div><div class="setting-label">Intervalle de scraping</div><div class="setting-desc">Minutes entre chaque scrape</div></div>
      <input type="number" id="cfg-interval" value="${config.scrape_interval_minutes}" min="5" max="120" onchange="APP_STATE.settingsCache.scrape_interval_minutes=parseInt(this.value)">
    </div>
    <div class="setting-row">
      <div><div class="setting-label">Export CSV automatique</div><div class="setting-desc">Exporter après chaque scrape</div></div>
      <label class="toggle"><input type="checkbox" id="cfg-export" ${config.auto_export_csv?'checked':''} onchange="APP_STATE.settingsCache.auto_export_csv=this.checked"><span class="toggle-slider"></span></label>
    </div>
    <div class="setting-row">
      <div><div class="setting-label">Notifications</div><div class="setting-desc">Activer les notifications desktop</div></div>
      <label class="toggle"><input type="checkbox" id="cfg-notif" ${config.notifications_enabled?'checked':''} onchange="APP_STATE.settingsCache.notifications_enabled=this.checked"><span class="toggle-slider"></span></label>
    </div>
    <div class="setting-row">
      <div><div class="setting-label">Seuil All Models</div><div class="setting-desc">Alerte si All Models dépasse ce %</div></div>
      <input type="number" value="${config.alert_all_models_threshold || 80}" min="10" max="100" onchange="APP_STATE.settingsCache.alert_all_models_threshold=parseInt(this.value)">
    </div>
    <div class="setting-row">
      <div><div class="setting-label">Seuil Sonnet</div><div class="setting-desc">Alerte si Sonnet dépasse ce %</div></div>
      <input type="number" value="${config.alert_sonnet_threshold || 80}" min="10" max="100" onchange="APP_STATE.settingsCache.alert_sonnet_threshold=parseInt(this.value)">
    </div>
    <div class="setting-row">
      <div><div class="setting-label">Alerte sur reset</div><div class="setting-desc">Notifier quand un reset est détecté</div></div>
      <label class="toggle"><input type="checkbox" ${config.alert_on_reset!==false?'checked':''} onchange="APP_STATE.settingsCache.alert_on_reset=this.checked"><span class="toggle-slider"></span></label>
    </div>
    <div class="setting-row">
      <div><div class="setting-label">Cooldown alertes</div><div class="setting-desc">Minutes entre deux alertes du même type</div></div>
      <input type="number" value="${config.alert_cooldown_minutes || 60}" min="5" max="1440" onchange="APP_STATE.settingsCache.alert_cooldown_minutes=parseInt(this.value)">
    </div>
    <div class="setting-row">
      <div><div class="setting-label">Lancer au démarrage</div><div class="setting-desc">Démarrer automatiquement avec Windows</div></div>
      <label class="toggle"><input type="checkbox" id="cfg-startup" ${config.launch_at_startup?'checked':''} onchange="APP_STATE.settingsCache.launch_at_startup=this.checked"><span class="toggle-slider"></span></label>
    </div>
    <div style="margin:16px 0 8px;font-weight:600;color:var(--accent);border-top:1px solid var(--border);padding-top:16px">
      Extension Chrome Bridge
    </div>
    <div id="extensionStatus" style="margin-bottom:12px;font-size:13px;color:var(--text-muted)">
      Vérification…
    </div>
  `;

  document.getElementById('appInfo').innerHTML = `
    <strong>${status.app}</strong> v${status.version}<br>
    Entrées : ${status.entries_count}<br>
    Répertoire : <code style="font-family:var(--mono);font-size:12px;color:var(--accent)">${status.data_dir || '-'}</code>
  `;

  // Vérifier le statut de l'extension Chrome
  api('/api/session').then(session => {
    const el = document.getElementById('extensionStatus');
    if (!el) return;
    if (session.authenticated) {
      const lastData = session.last_data ? new Date(session.last_data).toLocaleString('fr') : 'N/A';
      el.innerHTML = `<span style="color:var(--green)">✓ Extension connectée</span> — dernière donnée : ${lastData}`;
      if (session.stale) {
        el.innerHTML += '<br><span style="color:var(--amber)">⚠ Données obsolètes (&gt; 1h). Vérifie que l\'extension est active.</span>';
      }
    } else {
      el.innerHTML = '<span style="color:var(--red)">✗ Pas de données de l\'extension Chrome.</span><br>Charge l\'extension depuis <code>extension/</code> pour collecter les données automatiquement.';
    }
  }).catch(() => {});
}

async function saveSettings() {
  await api('/api/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(APP_STATE.settingsCache),
  });
  loadOverview();
  loadSettings();
}

// ============================================================
// CLAUDE CODE SETTINGS
// ============================================================
let claudeCodeSettingsCache = {};

async function loadClaudeCodeSettings() {
  try {
    const config = await api('/api/config');
    claudeCodeSettingsCache = {
      claude_code_scan_enabled: config.claude_code_scan_enabled || false,
      claude_code_dir: config.claude_code_dir || '',
      claude_code_scan_interval_minutes: config.claude_code_scan_interval_minutes || 15,
    };

    const form = document.getElementById('claudeCodeSettingsForm');
    form.innerHTML = `
      <div class="setting-row">
        <div><div class="setting-label">Activer le scan Claude Code</div><div class="setting-desc">Analyser les sessions locales du répertoire ~/.claude/</div></div>
        <label class="toggle"><input type="checkbox" id="cfg-cc-enabled" ${claudeCodeSettingsCache.claude_code_scan_enabled?'checked':''} onchange="claudeCodeSettingsCache.claude_code_scan_enabled=this.checked"><span class="toggle-slider"></span></label>
      </div>
      <div class="setting-row">
        <div><div class="setting-label">Répertoire Claude Code</div><div class="setting-desc">Chemin personnalisé (laisser vide = ~/.claude/)</div></div>
        <input type="text" id="cfg-cc-dir" value="${claudeCodeSettingsCache.claude_code_dir}" placeholder="~/.claude/" onchange="claudeCodeSettingsCache.claude_code_dir=this.value">
      </div>
      <div class="setting-row">
        <div><div class="setting-label">Intervalle de scan</div><div class="setting-desc">Minutes entre chaque scan Claude Code</div></div>
        <input type="number" id="cfg-cc-interval" value="${claudeCodeSettingsCache.claude_code_scan_interval_minutes}" min="5" max="1440" onchange="claudeCodeSettingsCache.claude_code_scan_interval_minutes=parseInt(this.value)">
      </div>
    `;
  } catch (error) {
    console.error('Error loading Claude Code settings:', error);
    document.getElementById('claudeCodeSettingsForm').innerHTML = '<p style="color:var(--red)">Erreur lors du chargement des paramètres</p>';
  }
}

async function saveClaudeCodeSettings() {
  try {
    await api('/api/config/claude-code', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(claudeCodeSettingsCache),
    });
    loadClaudeCodeSettings();
  } catch (error) {
    console.error('Error saving Claude Code settings:', error);
    alert('Erreur lors de la sauvegarde des paramètres Claude Code');
  }
}

// ============================================================
// CLAUDE CODE
// ============================================================
async function triggerClaudeCodeScan() {
  const btn = document.getElementById('btnScanClaudeCode');
  if (btn) { btn.disabled = true; btn.textContent = 'Scan en cours…'; }
  try {
    const res = await fetch('/api/claude-code/scan', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      loadClaudeCodeData();
    } else {
      alert('Scan échoué : ' + (data.message || 'Erreur inconnue'));
    }
  } catch (e) {
    alert('Erreur lors du scan : ' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Lancer le scan'; }
  }
}

async function loadClaudeCodeData() {
  try {
    const statusRes = await fetch('/api/claude-code/status');
    const status = await statusRes.json();

    if (!status.detected) {
      document.getElementById('claudeCodeCards').innerHTML = `
        <div style="grid-column:1/-1;padding:24px;text-align:center;color:var(--text-dim)">
          Claude Code non détecté. Vérifie que le répertoire ~/.claude/ est accessible.
        </div>
      `;
      return;
    }

    const analysisRes = await fetch('/api/analysis');
    const analysis = await analysisRes.json();
    const cc = analysis.claude_code || {};

    renderClaudeCodeCards(cc);

    const dailyRes = await fetch('/api/claude-code/daily?days=30');
    const daily = await dailyRes.json();
    renderClaudeCodeDaily(daily);

    const modelsRes = await fetch('/api/claude-code/models?days=30');
    const models = await modelsRes.json();
    renderClaudeCodeModels(models, cc);

    const projectsRes = await fetch('/api/claude-code/projects');
    const projects = await projectsRes.json();
    renderClaudeCodeProjects(projects);

    const sessionsRes = await fetch('/api/claude-code/sessions?days=30');
    const sessions = await sessionsRes.json();
    renderClaudeCodeSessions(sessions);

    setTimeout(addExportButtons, 100);
  } catch (error) {
    console.error('Error loading Claude Code data:', error);
    document.getElementById('claudeCodeCards').innerHTML = `
      <div style="grid-column:1/-1;padding:24px;text-align:center;color:var(--red)">
        Erreur : ${error.message}
      </div>
    `;
  }
}

function renderClaudeCodeCards(cc) {
  if (!cc.detected) return;
  const cards = [
    { label: 'Sessions ce mois', value: cc.sessions_this_month || 0, unit: '' },
    { label: 'Tokens ce mois', value: formatNumber(cc.tokens_this_month || 0), unit: '' },
    { label: 'Coût API équiv.', value: `$${(cc.cost_equivalent_this_month || 0).toFixed(0)}`, unit: 'si facturé au token' },
    { label: 'Modèle principal', value: ((cc.primary_model || 'N/A').split('-')[1] || cc.primary_model || 'N/A').toUpperCase(), unit: '' },
  ];
  const html = cards.map(card => `
    <div class="card">
      <div class="card-label">${card.label}</div>
      <div class="card-value">${card.value}</div>
      ${card.unit ? `<div class="card-sub">${card.unit}</div>` : ''}
    </div>
  `).join('');
  document.getElementById('claudeCodeCards').innerHTML = html;
}

function renderClaudeCodeDaily(daily) {
  const ctx = document.getElementById('claudeCodeDailyChart');
  if (!ctx) return;
  kill('claudeCodeDailyChart');
  const hasModelBreakdown = daily.some(d => d.opus_tokens || d.sonnet_tokens || d.haiku_tokens);
  const chartData = hasModelBreakdown ? {
    labels: daily.map(d => d.date.split('-')[2]),
    datasets: [
      {
        label: 'Opus',
        data: daily.map(d => d.opus_tokens || 0),
        backgroundColor: 'rgba(139, 92, 246, 0.5)',
        borderColor: 'rgb(139, 92, 246)',
        stack: 'tokens',
      },
      {
        label: 'Sonnet',
        data: daily.map(d => d.sonnet_tokens || 0),
        backgroundColor: 'rgba(59, 130, 246, 0.5)',
        borderColor: 'rgb(59, 130, 246)',
        stack: 'tokens',
      },
      {
        label: 'Haiku',
        data: daily.map(d => d.haiku_tokens || 0),
        backgroundColor: 'rgba(34, 197, 94, 0.5)',
        borderColor: 'rgb(34, 197, 94)',
        stack: 'tokens',
      },
    ],
  } : {
    labels: daily.map(d => d.date.split('-')[2]),
    datasets: [{
      label: 'Tokens',
      data: daily.map(d => d.total_tokens || 0),
      backgroundColor: 'rgba(99, 102, 241, 0.5)',
      borderColor: 'rgb(99, 102, 241)',
      borderWidth: 1,
    }],
  };
  APP_STATE.charts['claudeCodeDailyChart'] = new Chart(ctx, {
    type: 'bar',
    data: chartData,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { stacked: true, grid: { color: 'rgba(255,255,255,0.05)' } },
        y: { stacked: true, grid: { color: 'rgba(255,255,255,0.05)' } },
      },
      plugins: {
        legend: { labels: { color: 'var(--text)' } },
      },
    },
  });
}

function renderClaudeCodeModels(models, cc) {
  const ctx = document.getElementById('claudeCodeModelChart');
  if (!ctx || !cc.model_split) return;
  kill('claudeCodeModelChart');
  const modelNames = Object.keys(cc.model_split);
  const modelPcts = Object.values(cc.model_split);
  const colors = {
    opus: 'rgba(139, 92, 246, 0.7)',
    sonnet: 'rgba(59, 130, 246, 0.7)',
    haiku: 'rgba(34, 197, 94, 0.7)',
  };
  APP_STATE.charts['claudeCodeModelChart'] = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: modelNames.map(m => m.charAt(0).toUpperCase() + m.slice(1)),
      datasets: [{
        data: modelPcts,
        backgroundColor: modelNames.map(m => colors[m] || 'rgba(99, 102, 241, 0.7)'),
        borderColor: 'var(--bg-card)',
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: 'var(--text)' }, position: 'bottom' },
      },
    },
  });
}

function renderClaudeCodeProjects(projects) {
  const container = document.getElementById('claudeCodeProjectsList');
  if (!projects || projects.length === 0) {
    container.innerHTML = '<p style="color:var(--text-dim)">Aucun projet détecté</p>';
    return;
  }
  const html = projects.slice(0, 5).map(p => `
    <div style="padding:8px;border-bottom:1px solid var(--border)">
      <div style="font-weight:500;color:var(--text)">${p.name}</div>
      <div style="font-size:12px;color:var(--text-muted)">${p.sessions} sessions · $${p.cost_usd.toFixed(2)}</div>
    </div>
  `).join('');
  container.innerHTML = html;
}

function renderClaudeCodeSessions(sessions) {
  const container = document.getElementById('claudeCodeSessionsTable');
  if (!sessions || sessions.length === 0) {
    container.innerHTML = '<p style="padding:24px;text-align:center;color:var(--text-dim)">Aucune session</p>';
    return;
  }
  const html = `
    <table>
      <thead>
        <tr>
          <th>Date</th>
          <th>Durée</th>
          <th>Projet</th>
          <th>Modèle</th>
          <th>Tokens</th>
          <th>Coût</th>
        </tr>
      </thead>
      <tbody>
        ${sessions.slice(0, 20).map(s => `
          <tr>
            <td>${new Date(s.start_time).toLocaleDateString('fr-FR')}</td>
            <td>${s.duration_minutes}m</td>
            <td>${(s.project_path || 'Unknown').split('/').pop()}</td>
            <td>${((s.primary_model || 'unknown').split('-')[1] || s.primary_model || '?').toUpperCase()}</td>
            <td>${formatNumber(s.total_tokens)}</td>
            <td>$${s.cost_usd.toFixed(2)}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
  container.innerHTML = html;
}

// ============================================================
// Actions
// ============================================================
function triggerScrape(btn) {
  btn.textContent = 'Géré par l\'extension Chrome';
  btn.disabled = true;
  setTimeout(() => {
    btn.textContent = 'Rafraîchir (via extension)';
    btn.disabled = false;
  }, 2000);
}

async function importCSV() {
  const file = document.getElementById('csvFile').files[0];
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  try {
    const r = await api('/api/import/csv', { method: 'POST', body: form });
    alert(r.imported + (r.imported > 1 ? ' entrées importées' : ' entrée importée'));
    loadHistory();
  } catch (e) {
    alert('Erreur d\'import');
  }
}

async function clearData() {
  await api('/api/clear', { method: 'POST' });
  loadOverview();
  loadHistory();
  loadCycles();
}

async function deleteEntry(id, btn) {
  btn.disabled = true;
  await api('/api/entry/' + id, { method: 'DELETE' });
  const row = btn.closest('tr');
  if (row) row.remove();
}
