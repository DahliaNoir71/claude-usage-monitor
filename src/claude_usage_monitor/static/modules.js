/**
 * Claude Code specific functions for dashboard
 */

async function loadClaudeCodeData() {
  try {
    // Load status
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

    // Load analysis data
    const analysisRes = await fetch('/api/analysis');
    const analysis = await analysisRes.json();
    const cc = analysis.claude_code || {};

    // Render KPI cards
    renderClaudeCodeCards(cc);

    // Load daily usage
    const dailyRes = await fetch('/api/claude-code/daily?days=30');
    const daily = await dailyRes.json();
    renderClaudeCodeDaily(daily);

    // Load models breakdown
    const modelsRes = await fetch('/api/claude-code/models?days=30');
    const models = await modelsRes.json();
    renderClaudeCodeModels(models, cc);

    // Load projects
    const projectsRes = await fetch('/api/claude-code/projects');
    const projects = await projectsRes.json();
    renderClaudeCodeProjects(projects);

    // Load sessions
    const sessionsRes = await fetch('/api/claude-code/sessions?days=30');
    const sessions = await sessionsRes.json();
    renderClaudeCodeSessions(sessions);

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
    { label: 'Coût API équiv.', value: `$${(cc.cost_equivalent_this_month || 0).toFixed(2)}`, unit: '' },
    { label: 'Modèle principal', value: (cc.primary_model || 'N/A').split('-')[1].toUpperCase(), unit: '' },
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

  const chartData = {
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
  };

  if (charts.claudeCodeDaily) charts.claudeCodeDaily.destroy();
  charts.claudeCodeDaily = new Chart(ctx, {
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

  const modelNames = Object.keys(cc.model_split);
  const modelPcts = Object.values(cc.model_split);
  const colors = {
    opus: 'rgba(139, 92, 246, 0.7)',
    sonnet: 'rgba(59, 130, 246, 0.7)',
    haiku: 'rgba(34, 197, 94, 0.7)',
  };

  if (charts.claudeCodeModels) charts.claudeCodeModels.destroy();
  charts.claudeCodeModels = new Chart(ctx, {
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
      <div style="font-size:12px;color:var(--text-muted)">${p.sessions} sessions · $${p.cost.toFixed(2)}</div>
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
            <td>${s.primary_model.split('-')[1].toUpperCase()}</td>
            <td>${formatNumber(s.total_tokens)}</td>
            <td>$${s.cost_usd.toFixed(2)}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;

  container.innerHTML = html;
}

function formatNumber(num) {
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + 'M';
  if (num >= 1_000) return (num / 1_000).toFixed(1) + 'K';
  return num.toString();
}
