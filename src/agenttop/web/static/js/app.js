/* agenttop — Main application controller v3 */

const App = {
  days: 0,
  ws: null,
  data: { graph: null, stats: [], models: {}, hours: {}, sessions: [] },

  TOOL_COLORS: {
    claude_code: '#ff6b00',
    cursor: '#00fff5',
    kiro: '#00ff88',
    copilot: '#4488ff',
    codex: '#ff00ff',
    windsurf: '#ffee00',
    continue: '#ff4444',
    aider: '#ffffff',
  },

  formatNum(n) {
    if (n == null) return '0';
    if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return n.toLocaleString();
  },

  formatCost(n) {
    if (n == null || n === 0) return '$0';
    if (n >= 1000) return '$' + (n / 1000).toFixed(1) + 'K';
    if (n >= 1) return '$' + n.toFixed(2);
    if (n >= 0.01) return '$' + n.toFixed(2);
    return '$' + n.toFixed(3);
  },

  async init() {
    const select = document.getElementById('time-range');
    select.addEventListener('change', () => {
      App.days = parseInt(select.value, 10);
      App._syncWSDays();
      App.refresh();
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
      const map = { '1': '1', '2': '7', '3': '30', '4': '0' };
      if (map[e.key]) {
        select.value = map[e.key];
        App.days = parseInt(map[e.key], 10);
        App._syncWSDays();
        App.refresh();
      }
      // Escape closes detail overlay
      if (e.key === 'Escape') {
        document.getElementById('node-detail').classList.add('hidden');
      }
    });

    // Detail overlay close
    document.getElementById('detail-close').addEventListener('click', () => {
      document.getElementById('node-detail').classList.add('hidden');
    });

    await App.refresh();
    App.connectWS();
  },

  async refresh() {
    try {
      const [graphRes, statsRes, modelsRes, hoursRes, sessionsRes, budgetRes] = await Promise.all([
        fetch(`/api/graph?days=${App.days}`),
        fetch(`/api/stats?days=${App.days}`),
        fetch('/api/models'),
        fetch('/api/hours'),
        fetch(`/api/sessions?days=${App.days || 7}`),
        fetch(`/api/budget?days=${App.days}`),
      ]);

      App.data.graph    = await graphRes.json();
      App.data.stats    = await statsRes.json();
      App.data.models   = await modelsRes.json();
      App.data.hours    = await hoursRes.json();
      App.data.sessions = await sessionsRes.json();
      App.data.budget   = await budgetRes.json();

      // Render all panels
      Graph.render(App.data.graph);
      Stats.render(App.data.stats, App.data.budget);
      App.renderToolBar(App.data.stats);
      Panels.renderModels(App.data.models);
      Panels.renderHourly(App.data.hours);
      Panels.renderSessions(App.data.sessions);
      Panels.renderCost(App.data.stats);
    } catch (err) {
      console.error('Failed to load data:', err);
    }
  },

  renderToolBar(stats) {
    const bar = document.getElementById('tool-bar');
    if (!stats || stats.length === 0) { bar.innerHTML = ''; return; }

    bar.innerHTML = stats.map(s => {
      const color = App.TOOL_COLORS[s.tool] || '#888';
      const active = s.status === 'active';
      const cls = active ? 'active' : 'idle';
      const val = s.tokens_today > 0 ? App.formatNum(s.tokens_today) :
                  s.messages_today > 0 ? `${App.formatNum(s.messages_today)} msgs` :
                  s.sessions_today > 0 ? `${s.sessions_today} sess` : 'idle';
      return `<div class="tool-chip ${cls}">
        <span class="dot" style="background:${color};color:${color}"></span>
        <span>${s.display_name}</span>
        <span class="chip-value">${val}</span>
      </div>`;
    }).join('');
  },

  connectWS() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    try {
      App.ws = new WebSocket(`${proto}//${location.host}/ws`);
      App.ws.onopen = () => {
        // Send current days preference so WS matches the view
        App.ws.send(String(App.days));
      };
      App.ws.onmessage = (event) => {
        try { Stats.updateLive(JSON.parse(event.data)); } catch(e) {}
      };
      App.ws.onclose = () => setTimeout(() => App.connectWS(), 5000);
      App.ws.onerror = () => App.ws.close();
    } catch(e) {
      setTimeout(() => App.connectWS(), 5000);
    }
  },

  // Notify WS when days changes
  _syncWSDays() {
    if (App.ws && App.ws.readyState === WebSocket.OPEN) {
      App.ws.send(String(App.days));
    }
  },

  showNodeDetail(node) {
    const overlay = document.getElementById('node-detail');
    overlay.classList.remove('hidden');
    const el = document.getElementById('detail-content');

    const f = App.formatNum;
    const fc = App.formatCost;
    const color = node.color || 'var(--neon-cyan)';

    let sections = [];

    // Name
    sections.push(`
      <div class="detail-section">
        <div class="detail-label">Node</div>
        <div class="detail-value" style="color:${color};text-shadow:0 0 8px ${color}40">${node.label}</div>
      </div>
    `);

    // Type badge
    const typeBadge = {
      center: '\u25C9 Developer',
      tool: '\u25CF Tool',
      model: '\u2B21 Model',
      project: '\u25C6 Project',
    }[node.type] || node.type;
    sections.push(`
      <div class="detail-section">
        <div class="detail-label">Type</div>
        <div class="detail-value" style="font-size:12px">${typeBadge}</div>
      </div>
    `);

    // Tokens with bar
    if (node.value > 0) {
      const maxVal = Math.max(...(App.data.graph?.nodes || []).map(n => n.value || 0), 1);
      const pct = Math.min(100, (node.value / maxVal) * 100);
      sections.push(`
        <div class="detail-section">
          <div class="detail-label">Tokens</div>
          <div class="detail-value">${f(node.value)}</div>
          <div class="detail-bar">
            <div class="detail-bar-fill" style="width:${pct}%;background:${color}"></div>
          </div>
        </div>
      `);
    }

    // Tool-specific
    if (node.type === 'tool') {
      if (node.sessions != null) sections.push(`
        <div class="detail-section">
          <div class="detail-label">Sessions</div>
          <div class="detail-value">${f(node.sessions)}</div>
        </div>
      `);
      if (node.messages != null) sections.push(`
        <div class="detail-section">
          <div class="detail-label">Messages</div>
          <div class="detail-value">${f(node.messages)}</div>
        </div>
      `);
      if (node.cost != null) sections.push(`
        <div class="detail-section">
          <div class="detail-label">Estimated Cost</div>
          <div class="detail-value" style="color:var(--neon-orange)">${fc(node.cost)}</div>
        </div>
      `);
    }

    // Model-specific
    if (node.type === 'model') {
      const total = (node.inputTokens || 0) + (node.outputTokens || 0) + (node.cacheRead || 0);
      const items = [
        ['Input', node.inputTokens, 'var(--neon-cyan)'],
        ['Output', node.outputTokens, 'var(--neon-orange)'],
        ['Cache Read', node.cacheRead, 'var(--neon-green)'],
      ];
      items.forEach(([label, val, c]) => {
        if (!val) return;
        const pct = (val / total * 100).toFixed(1);
        sections.push(`
          <div class="detail-section">
            <div class="detail-label">${label}</div>
            <div class="detail-value" style="color:${c}">${f(val)} <span style="font-size:10px;color:var(--text-dim)">(${pct}%)</span></div>
            <div class="detail-bar">
              <div class="detail-bar-fill" style="width:${pct}%;background:${c}"></div>
            </div>
          </div>
        `);
      });
    }

    // Connected edges
    const edges = (App.data.graph?.edges || []).filter(e => {
      const sid = e.source?.id || e.source;
      const tid = e.target?.id || e.target;
      return sid === node.id || tid === node.id;
    });
    if (edges.length > 0) {
      const listItems = edges.map(e => {
        const sid = e.source?.id || e.source;
        const otherId = sid === node.id ? (e.target?.id || e.target) : sid;
        const other = (App.data.graph?.nodes || []).find(n => n.id === otherId);
        return `<li><span style="color:${other?.color || 'inherit'}">${other?.label || otherId}</span><span class="val">${f(e.value)}</span></li>`;
      }).join('');
      sections.push(`
        <div class="detail-section">
          <div class="detail-label">Connections</div>
          <ul class="detail-list">${listItems}</ul>
        </div>
      `);
    }

    el.innerHTML = sections.join('');
  }
};

document.addEventListener('DOMContentLoaded', () => App.init());
