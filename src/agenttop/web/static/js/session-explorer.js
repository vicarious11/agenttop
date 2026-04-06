/* agenttop — Session Explorer: Browse + Analyze tabs */

const SessionExplorer = {
  _sessions: [],
  _filtered: [],
  _selected: new Set(),
  _activeId: null,
  _filters: { tool: '', search: '' },
  _sort: 'time',
  _analyzing: false,
  _analysisResult: null,
  _activeTab: 'browse', // 'browse' | 'analyze'
  _drawerOpen: false,

  init() {
    const handle = document.getElementById('sessions-drawer-toggle');
    if (handle) {
      handle.addEventListener('click', (e) => {
        if (e.target.closest('#sessions-fullscreen')) return;
        SessionExplorer._drawerOpen = !SessionExplorer._drawerOpen;
        document.getElementById('sessions-drawer').classList.toggle('collapsed', !SessionExplorer._drawerOpen);
        if (SessionExplorer._drawerOpen) SessionExplorer.render();
      });
    }
    const fsBtn = document.getElementById('sessions-fullscreen');
    if (fsBtn) {
      fsBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const drawer = document.getElementById('sessions-drawer');
        if (!SessionExplorer._drawerOpen) {
          SessionExplorer._drawerOpen = true;
          drawer.classList.remove('collapsed');
        }
        drawer.classList.toggle('fullscreen');
        SessionExplorer.render();
      });
    }
  },

  // ── Filters ──

  _applyFilters() {
    let list = this._sessions.filter(s => (s.message_count || 0) > 0 || (s.total_tokens || 0) > 0);
    if (this._filters.tool) list = list.filter(s => s.tool === this._filters.tool);
    if (this._filters.search) {
      const q = this._filters.search.toLowerCase();
      list = list.filter(s =>
        (s.project || '').toLowerCase().includes(q) ||
        ((s.prompts || [])[0] || '').toLowerCase().includes(q)
      );
    }
    const sortFns = {
      time: (a, b) => new Date(b.start_time || 0) - new Date(a.start_time || 0),
      cost: (a, b) => (b.estimated_cost_usd || 0) - (a.estimated_cost_usd || 0),
      tokens: (a, b) => (b.total_tokens || 0) - (a.total_tokens || 0),
    };
    list.sort(sortFns[this._sort] || sortFns.time);
    this._filtered = list;
  },

  // ── Helpers ──

  _esc(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; },
  _toolName(t) { return { claude_code: 'Claude', cursor: 'Cursor', kiro: 'Kiro', copilot: 'Copilot', codex: 'Codex' }[t] || t; },
  _toolColor(t) { return (typeof App !== 'undefined' && App.TOOL_COLORS) ? (App.TOOL_COLORS[t] || '#888') : '#888'; },
  _dur(s) {
    if (!s.start_time || !s.end_time) return '';
    const m = Math.round((new Date(s.end_time) - new Date(s.start_time)) / 60000);
    return m >= 60 ? (m / 60).toFixed(1) + 'h' : m > 0 ? m + 'm' : '';
  },
  _ago(s) {
    if (!s.start_time) return '';
    const h = Math.floor((Date.now() - new Date(s.start_time).getTime()) / 3600000);
    return h < 1 ? 'now' : h < 24 ? h + 'h ago' : Math.floor(h / 24) + 'd ago';
  },

  // ── Main render ──

  render() {
    const el = document.getElementById('sessions-content');
    if (!el) return;
    this._applyFilters();

    const badge = document.getElementById('sessions-count');
    if (badge) badge.textContent = this._filtered.length + ' sessions';

    const browseActive = this._activeTab === 'browse' ? 'active' : '';
    const analyzeActive = this._activeTab === 'analyze' ? 'active' : '';

    el.innerHTML = `
      <div class="se-tabs">
        <button class="se-tab ${browseActive}" data-tab="browse">Browse</button>
        <button class="se-tab ${analyzeActive}" data-tab="analyze">Analyze</button>
      </div>
      <div class="se-tab-content">
        ${this._activeTab === 'browse' ? this._renderBrowse() : this._renderAnalyze()}
      </div>
    `;

    // Tab switching
    el.querySelectorAll('.se-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        this._activeTab = btn.dataset.tab;
        this.render();
      });
    });

    // Bind events for active tab
    if (this._activeTab === 'browse') this._bindBrowseEvents(el);
    else this._bindAnalyzeEvents(el);
  },

  // ══════════════════════════════════════
  //  BROWSE TAB
  // ══════════════════════════════════════

  _renderBrowse() {
    const tools = [...new Set(this._sessions.map(s => s.tool))].sort();
    const toolOpts = tools.map(t => `<option value="${t}" ${this._filters.tool === t ? 'selected' : ''}>${this._toolName(t)}</option>`).join('');

    let html = `
      <div class="se-browse">
        <div class="se-toolbar">
          <input class="se-search" placeholder="Search..." value="${this._esc(this._filters.search)}">
          <select class="se-filter-tool"><option value="">All</option>${toolOpts}</select>
        </div>
        <div class="se-split">
          <div class="se-list">`;

    this._filtered.slice(0, 100).forEach((s, i) => {
      const proj = s.project ? s.project.split('/').pop() : 'unknown';
      const name = proj.length > 18 ? proj.slice(0, 18) + '…' : proj;
      const color = this._toolColor(s.tool);
      const active = s.id === this._activeId ? ' active' : '';
      const prompt = (s.prompts || [])[0] || '';
      const preview = prompt ? this._esc(prompt.slice(0, 50)) + (prompt.length > 50 ? '...' : '') : '';
      const cost = s.estimated_cost_usd > 0 ? App.formatCost(s.estimated_cost_usd) : '';

      html += `
        <div class="se-row${active}" data-id="${this._esc(s.id)}" data-idx="${i}">
          <span class="se-dot" style="background:${color}"></span>
          <div class="se-row-info">
            <span class="se-row-name">${this._esc(name)}</span>
            <span class="se-row-meta">${this._toolName(s.tool)} · ${this._ago(s)}${cost ? ' · ' + cost : ''}</span>
            ${preview ? `<span class="se-row-preview">${preview}</span>` : ''}
          </div>
        </div>`;
    });

    html += `</div><div class="se-detail-pane" id="se-detail-pane">`;
    html += this._activeId ? '' : '<div class="se-detail-empty">Click a session to see details</div>';
    html += `</div></div></div>`;
    return html;
  },

  _bindBrowseEvents(el) {
    const search = el.querySelector('.se-search');
    if (search) {
      let t;
      search.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => { this._filters.search = search.value; this.render(); }, 200); });
    }
    const toolF = el.querySelector('.se-filter-tool');
    if (toolF) toolF.addEventListener('change', () => { this._filters.tool = toolF.value; this.render(); });

    el.querySelectorAll('.se-row').forEach(row => {
      row.addEventListener('click', () => {
        this._activeId = row.dataset.id;
        this._loadDetail(row.dataset.id);
        el.querySelectorAll('.se-row').forEach(r => r.classList.remove('active'));
        row.classList.add('active');
      });
    });

    if (this._activeId) this._loadDetail(this._activeId);
  },

  async _loadDetail(sid) {
    const pane = document.getElementById('se-detail-pane');
    if (!pane) return;
    pane.innerHTML = '<div class="se-detail-empty">Loading...</div>';

    let session = this._sessions.find(s => s.id === sid);
    try {
      const res = await fetch(`/api/sessions/${encodeURIComponent(sid)}`);
      if (res.ok) session = await res.json();
    } catch (e) { /* use local */ }
    if (!session) { pane.innerHTML = '<div class="se-detail-empty">Not found</div>'; return; }

    const proj = session.project ? session.project.split('/').pop() : 'unknown';
    const prompts = session.prompts || [];
    const msgs = session.message_count || 0;
    const dur = this._dur(session);
    const tokens = session.total_tokens ? App.formatNum(session.total_tokens) : '0';
    const cost = session.estimated_cost_usd ? App.formatCost(session.estimated_cost_usd) : '$0';
    const toolCalls = session.tool_call_count || 0;
    const started = session.start_time ? new Date(session.start_time).toLocaleString() : '';

    pane.innerHTML = `
      <div class="se-detail-head">
        <h3>${this._esc(proj)}</h3>
        <span class="se-detail-tool" style="color:${this._toolColor(session.tool)}">${this._toolName(session.tool)}</span>
      </div>
      <div class="se-detail-stats">
        ${dur ? `<span>${dur}</span>` : ''}<span>${msgs} msgs</span><span>${toolCalls} calls</span><span>${tokens} tok</span><span>${cost}</span>
      </div>
      <div class="se-detail-stats">${started} · ${prompts.length} prompts</div>
      <div class="se-detail-prompts">
        ${prompts.length === 0 ? '<div class="se-detail-empty">No prompts</div>' :
          prompts.map((p, i) => `<div class="se-prompt"><span class="se-prompt-n">${i + 1}</span><span class="se-prompt-t">${this._esc(p.length > 300 ? p.slice(0, 300) + '...' : p)}</span></div>`).join('')}
      </div>
    `;
  },

  // ══════════════════════════════════════
  //  ANALYZE TAB
  // ══════════════════════════════════════

  _renderAnalyze() {
    const selected = this._selected;
    const selCount = selected.size;

    let html = '<div class="se-analyze">';

    // Profile card (if analysis done)
    if (this._analysisResult) {
      html += this._renderProfile(this._analysisResult);
    }

    // Session picker
    html += `
      <div class="se-analyze-picker">
        <div class="se-analyze-toolbar">
          <span class="se-analyze-label">${selCount > 0 ? selCount + ' selected' : 'Select sessions to analyze'}</span>
          <button class="se-analyze-all-btn" id="se-select-recent">Select Last 10</button>
          <button class="se-analyze-btn ${selCount > 0 ? 'active' : ''}" id="se-run-analyze" ${selCount === 0 ? 'disabled' : ''}>
            ${this._analyzing ? 'Analyzing...' : 'Analyze' + (selCount > 0 ? ' (' + selCount + ')' : '')}
          </button>
        </div>
        <div class="se-analyze-list">`;

    this._filtered.slice(0, 50).forEach((s, i) => {
      const proj = s.project ? s.project.split('/').pop() : 'unknown';
      const name = proj.length > 20 ? proj.slice(0, 20) + '…' : proj;
      const checked = selected.has(s.id);
      const cost = s.estimated_cost_usd > 0 ? App.formatCost(s.estimated_cost_usd) : '';

      html += `
        <label class="se-analyze-row ${checked ? 'checked' : ''}" data-id="${this._esc(s.id)}">
          <input type="checkbox" ${checked ? 'checked' : ''}>
          <span class="se-dot" style="background:${this._toolColor(s.tool)}"></span>
          <span class="se-analyze-name">${this._esc(name)}</span>
          <span class="se-analyze-meta">${this._toolName(s.tool)} · ${(s.message_count || 0)} msgs${cost ? ' · ' + cost : ''}</span>
        </label>`;
    });

    html += '</div></div></div>';
    return html;
  },

  _bindAnalyzeEvents(el) {
    // Checkbox toggles
    el.querySelectorAll('.se-analyze-row input').forEach(cb => {
      cb.addEventListener('change', () => {
        const sid = cb.closest('.se-analyze-row').dataset.id;
        if (cb.checked) this._selected.add(sid); else this._selected.delete(sid);
        this.render();
      });
    });

    // Select last 10
    const selBtn = el.querySelector('#se-select-recent');
    if (selBtn) {
      selBtn.addEventListener('click', () => {
        this._selected.clear();
        this._filtered.slice(0, 10).forEach(s => this._selected.add(s.id));
        this.render();
      });
    }

    // Run analysis
    const runBtn = el.querySelector('#se-run-analyze');
    if (runBtn) {
      runBtn.addEventListener('click', () => this._runAnalysis());
    }
  },

  async _runAnalysis() {
    if (this._selected.size === 0) return;
    this._analyzing = true;
    this.render();

    const title = document.querySelector('.sessions-drawer-title');
    if (title) title.textContent = 'Sessions — analyzing...';

    try {
      const res = await fetch('/api/analyze-sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_ids: [...this._selected] }),
      });
      this._analysisResult = await res.json();
      if (title) title.textContent = `Sessions — Score: ${this._analysisResult.score || '?'}/100`;
    } catch (e) {
      if (title) title.textContent = 'Sessions — analysis failed';
    }
    this._analyzing = false;
    this.render();
  },

  _renderProfile(data) {
    const score = data.score || 0;
    const dp = data.developer_profile || {};
    const grades = data.grades || {};
    const strengths = (data.strengths || []).slice(0, 3);
    const aps = (data.anti_patterns || []).slice(0, 3);
    const recs = (data.recommendations || []).slice(0, 3);

    const icons = { power_user: '⚡', debug_warrior: '🛡️', explorer: '🧭', methodical_builder: '🏗️', cautious_adopter: '🎯', efficiency_optimizer: '⚙️' };
    const icon = icons[dp.ai_personality] || '👤';
    const scoreColor = score >= 80 ? '#34d399' : score >= 60 ? '#2dd4bf' : score >= 40 ? '#fbbf24' : '#f87171';
    const circ = 2 * Math.PI * 28;
    const off = circ - (score / 100) * circ;

    const gradeMap = { session_hygiene: '🧹 Hygiene', prompt_quality: '✍️ Prompts', cost_efficiency: '💰 Cost', cache_efficiency: '⚡ Cache', tool_utilization: '🔧 Tools' };
    const gNum = { A: 100, B: 75, C: 50, D: 25 };
    const gCol = { A: '#34d399', B: '#2dd4bf', C: '#fbbf24', D: '#f87171' };

    return `
      <div class="profile-card">
        <div class="profile-avatar">
          <svg viewBox="0 0 64 64" width="56" height="56">
            <circle cx="32" cy="32" r="28" fill="none" stroke="#27272a" stroke-width="4"/>
            <circle cx="32" cy="32" r="28" fill="none" stroke="${scoreColor}" stroke-width="4"
              stroke-dasharray="${circ}" stroke-dashoffset="${off}" stroke-linecap="round" transform="rotate(-90 32 32)"/>
          </svg>
          <span class="profile-avatar-icon">${icon}</span>
          <span class="profile-avatar-score" style="color:${scoreColor}">${score}</span>
        </div>
        <div class="profile-right">
          <div class="profile-title">${this._esc(dp.title || 'Developer')}</div>
          <div class="profile-bio">${this._esc(dp.bio || '')}</div>
          ${(dp.traits || []).length > 0 ? `<div class="profile-traits">${dp.traits.slice(0, 4).map(t => `<span class="profile-trait">${this._esc(t)}</span>`).join('')}</div>` : ''}
        </div>
      </div>
      <div class="profile-stats">
        ${Object.entries(grades).map(([k, v]) => {
          const g = v.grade || '?';
          return `<div class="profile-stat"><div class="profile-stat-header"><span>${gradeMap[k] || k}</span><span style="color:${gCol[g] || '#71717a'};font-weight:700">${g}</span></div><div class="profile-stat-bar"><div class="profile-stat-fill" style="width:${gNum[g] || 50}%;background:${gCol[g] || '#71717a'}"></div></div></div>`;
        }).join('')}
      </div>
      ${strengths.length > 0 ? `<div class="profile-section"><div class="profile-section-title">Powers</div>${strengths.map(s => `<div class="profile-power"><span class="profile-power-icon">${s.icon || '✓'}</span><span><strong>${this._esc(s.title || '')}</strong> — ${this._esc(s.detail || '')}</span></div>`).join('')}</div>` : ''}
      ${aps.length > 0 ? `<div class="profile-section"><div class="profile-section-title">Weaknesses</div>${aps.map(a => `<div class="profile-weakness"><span>${this._esc(a.pattern || '')}</span><span class="profile-weakness-count">${a.count || 0}x</span></div>`).join('')}</div>` : ''}
      ${recs.length > 0 ? `<div class="profile-section"><div class="profile-section-title">Quests</div>${recs.map(r => `<div class="profile-quest"><span class="profile-quest-dot" style="background:${{ high: '#f87171', medium: '#fbbf24', low: '#2dd4bf' }[r.priority] || '#71717a'}"></span><div><div class="profile-quest-title">${this._esc(r.title || '')}</div>${r.savings ? `<div class="profile-quest-reward">${this._esc(r.savings)}</div>` : ''}</div></div>`).join('')}</div>` : ''}
    `;
  },
};

document.addEventListener('DOMContentLoaded', () => SessionExplorer.init());
