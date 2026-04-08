/* agenttop — Session Explorer: full-page Browse + Analyze tabs with pagination */

const SessionExplorer = {
  _sessions: [],
  _filtered: [],
  _selected: new Set(),
  _activeId: null,
  _filters: { tool: '', search: '' },
  _sort: 'time',
  _page: 1,
  _pageSize: 25,
  _analyzing: false,
  _analysisResult: null,

  init() {
    // Tab rendering handled by App.switchTab()
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

  _totalPages() {
    return Math.max(1, Math.ceil(this._filtered.length / this._pageSize));
  },

  _pageSlice() {
    const start = (this._page - 1) * this._pageSize;
    return this._filtered.slice(start, start + this._pageSize);
  },

  _renderPagination() {
    const total = this._totalPages();
    if (total <= 1) return '';

    const current = this._page;
    const pages = [];

    // Google-style: show 1 ... 4 5 [6] 7 8 ... 20
    pages.push(1);
    if (current > 4) pages.push('...');
    for (let i = Math.max(2, current - 2); i <= Math.min(total - 1, current + 2); i++) {
      pages.push(i);
    }
    if (current < total - 3) pages.push('...');
    if (total > 1) pages.push(total);

    // Deduplicate
    const unique = [];
    for (const p of pages) {
      if (unique[unique.length - 1] !== p) unique.push(p);
    }

    return `
      <div class="se-pagination">
        <button class="se-page-btn" data-page="prev" ${current === 1 ? 'disabled' : ''}>&lsaquo;</button>
        ${unique.map(p =>
          p === '...'
            ? '<span class="se-page-ellipsis">\u2026</span>'
            : `<button class="se-page-btn ${p === current ? 'active' : ''}" data-page="${p}">${p}</button>`
        ).join('')}
        <button class="se-page-btn" data-page="next" ${current === total ? 'disabled' : ''}>&rsaquo;</button>
      </div>
    `;
  },

  _bindPagination(el) {
    el.querySelectorAll('.se-page-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const val = btn.dataset.page;
        if (val === 'prev') this._page = Math.max(1, this._page - 1);
        else if (val === 'next') this._page = Math.min(this._totalPages(), this._page + 1);
        else this._page = parseInt(val, 10);
        this.renderBrowse();
      });
    });
  },

  // ══════════════════════════════════════
  //  BROWSE TAB (full-page)
  // ══════════════════════════════════════

  renderBrowse() {
    const el = document.getElementById('pane-sessions');
    if (!el) return;
    this._applyFilters();

    // Clamp page
    if (this._page > this._totalPages()) this._page = this._totalPages();

    const tools = [...new Set(this._sessions.map(s => s.tool))].sort();
    const toolOpts = tools.map(t => `<option value="${t}" ${this._filters.tool === t ? 'selected' : ''}>${this._toolName(t)}</option>`).join('');
    const sortOpts = [['time', 'Recent'], ['cost', 'Cost'], ['tokens', 'Tokens']].map(([v, l]) =>
      `<option value="${v}" ${this._sort === v ? 'selected' : ''}>${l}</option>`
    ).join('');

    const start = (this._page - 1) * this._pageSize + 1;
    const end = Math.min(this._page * this._pageSize, this._filtered.length);
    const rangeText = this._filtered.length > 0
      ? `${start}\u2013${end} of ${this._filtered.length}`
      : '0 sessions';

    el.innerHTML = `
      <div class="se-page">
        <div class="se-page-header">
          <h2 class="se-page-title">Sessions</h2>
          <span class="se-page-count">${rangeText}</span>
        </div>
        <div class="se-toolbar">
          <input class="se-search" placeholder="Search projects, prompts..." value="${this._esc(this._filters.search)}">
          <select class="se-filter-tool"><option value="">All Tools</option>${toolOpts}</select>
          <select class="se-sort">${sortOpts}</select>
        </div>
        <div class="se-split">
          <div class="se-list-container">
            <div class="se-list">${this._renderSessionList()}</div>
            ${this._renderPagination()}
          </div>
          <div class="se-detail-pane" id="se-detail-pane">
            ${this._activeId ? '' : '<div class="se-detail-empty">Click a session to see details</div>'}
          </div>
        </div>
      </div>
    `;

    this._bindBrowseEvents(el);
    this._bindPagination(el);
    if (this._activeId) this._loadDetail(this._activeId);
  },

  _renderSessionList() {
    const slice = this._pageSlice();
    if (slice.length === 0) {
      return '<div class="se-detail-empty">No sessions found</div>';
    }

    let html = '';
    const offset = (this._page - 1) * this._pageSize;
    slice.forEach((s, i) => {
      const proj = s.project ? s.project.split('/').pop() : 'unknown';
      const name = proj.length > 22 ? proj.slice(0, 22) + '\u2026' : proj;
      const color = this._toolColor(s.tool);
      const active = s.id === this._activeId ? ' active' : '';
      const prompt = (s.prompts || [])[0] || '';
      const preview = prompt ? this._esc(prompt.slice(0, 60)) + (prompt.length > 60 ? '...' : '') : '';
      const cost = s.estimated_cost_usd > 0 ? App.formatCost(s.estimated_cost_usd) : '';
      const dur = this._dur(s);

      html += `
        <div class="se-row${active}" data-id="${this._esc(s.id)}" data-idx="${offset + i}">
          <span class="se-dot" style="background:${color}"></span>
          <div class="se-row-info">
            <span class="se-row-name">${this._esc(name)}</span>
            <span class="se-row-meta">${this._toolName(s.tool)} \u00b7 ${this._ago(s)}${dur ? ' \u00b7 ' + dur : ''}${cost ? ' \u00b7 ' + cost : ''}</span>
            ${preview ? `<span class="se-row-preview">${preview}</span>` : ''}
          </div>
        </div>`;
    });
    return html;
  },

  _bindBrowseEvents(el) {
    const search = el.querySelector('.se-search');
    if (search) {
      let t;
      search.addEventListener('input', () => {
        clearTimeout(t);
        t = setTimeout(() => {
          this._filters.search = search.value;
          this._page = 1;
          this.renderBrowse();
        }, 200);
      });
    }
    const toolF = el.querySelector('.se-filter-tool');
    if (toolF) toolF.addEventListener('change', () => { this._filters.tool = toolF.value; this._page = 1; this.renderBrowse(); });
    const sortEl = el.querySelector('.se-sort');
    if (sortEl) sortEl.addEventListener('change', () => { this._sort = sortEl.value; this._page = 1; this.renderBrowse(); });

    el.querySelectorAll('.se-row').forEach(row => {
      row.addEventListener('click', () => {
        this._activeId = row.dataset.id;
        this._loadDetail(row.dataset.id);
        el.querySelectorAll('.se-row').forEach(r => r.classList.remove('active'));
        row.classList.add('active');
      });
    });
  },

  async _loadDetail(sid) {
    const pane = document.getElementById('se-detail-pane');
    if (!pane) return;
    pane.innerHTML = '<div class="se-detail-empty">Loading...</div>';

    let session = this._sessions.find(s => s.id === sid);
    try {
      const res = await fetch(`/api/sessions/${encodeURIComponent(sid)}`);
      if (res.ok) session = await res.json();
    } catch (_e) { /* use local */ }
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
      <div class="se-detail-stats">${started} \u00b7 ${prompts.length} prompts</div>
      <div class="se-detail-prompts">
        ${prompts.length === 0 ? '<div class="se-detail-empty">No prompts</div>' :
          prompts.map((p, i) => `<div class="se-prompt"><span class="se-prompt-n">${i + 1}</span><span class="se-prompt-t">${this._esc(p.length > 300 ? p.slice(0, 300) + '...' : p)}</span></div>`).join('')}
      </div>
    `;
  },

  // ══════════════════════════════════════
  //  ANALYZE TAB (full-page)
  // ══════════════════════════════════════

  renderAnalyze() {
    const el = document.getElementById('pane-analyze');
    if (!el) return;
    this._applyFilters();
    const selCount = this._selected.size;
    const totalCost = [...this._selected].reduce((sum, id) => {
      const s = this._filtered.find(x => x.id === id);
      return sum + (s ? (s.estimated_cost_usd || 0) : 0);
    }, 0);

    el.innerHTML = `
      <div class="se-page">
        <div class="se-page-header">
          <h2 class="se-page-title">Analyze</h2>
          <span class="se-page-count">${selCount > 0 ? selCount + ' of ' + this._filtered.length + ' selected' : this._filtered.length + ' sessions'}</span>
          ${selCount > 0 ? `<span class="se-page-count">${App.formatCost(totalCost)} total</span>` : ''}
        </div>
        <div class="se-analyze-layout">
          <div class="se-analyze-sidebar">
            <div class="se-analyze-actions">
              <div class="se-action-group">
                <span class="se-action-label">Quick select</span>
                <div class="se-action-btns">
                  <button class="se-action-btn" id="se-select-all" title="Select all sessions">All</button>
                  <button class="se-action-btn" id="se-select-10" title="Select 10 most recent sessions">Last 10</button>
                  <button class="se-action-btn" id="se-select-costly" title="Select top 10 most expensive sessions">Top Cost</button>
                  <button class="se-action-btn" id="se-select-none" title="Clear selection"${selCount === 0 ? ' disabled' : ''}>Clear</button>
                </div>
              </div>
              <button class="se-run-btn ${selCount > 0 ? 'active' : ''}" id="se-run-analyze" ${selCount === 0 ? 'disabled' : ''}
                title="${selCount > 0 ? 'Run LLM analysis on ' + selCount + ' sessions' : 'Select sessions first'}">
                ${this._analyzing
                  ? '<span class="se-spinner"></span> Analyzing\u2026'
                  : selCount > 0 ? 'Analyze ' + selCount + ' sessions' : 'Analyze'}
              </button>
            </div>
            <div class="se-analyze-list">${this._renderAnalyzeList()}</div>
          </div>
          <div class="se-analyze-result">
            ${this._analysisResult ? this._renderProfile(this._analysisResult) : `
              <div class="se-empty-state">
                <div class="se-empty-icon">&#x2694;&#xFE0F;</div>
                <div class="se-empty-title">Developer Profile</div>
                <div class="se-empty-desc">Select sessions from the left panel and click <strong>Analyze</strong> to generate your AI-powered developer profile with grades, strengths, and recommendations.</div>
                <div class="se-empty-hint">Tip: Use <strong>Top Cost</strong> to find your most expensive sessions</div>
              </div>
            `}
          </div>
        </div>
      </div>
    `;

    this._bindAnalyzeEvents(el);
  },

  _renderAnalyzeList() {
    if (this._filtered.length === 0) {
      return '<div class="se-detail-empty">No sessions available</div>';
    }
    let html = '';
    this._filtered.forEach(s => {
      const proj = s.project ? s.project.split('/').pop() : 'unknown';
      const name = proj.length > 20 ? proj.slice(0, 20) + '\u2026' : proj;
      const checked = this._selected.has(s.id);
      const cost = s.estimated_cost_usd > 0 ? App.formatCost(s.estimated_cost_usd) : '';
      const dur = this._dur(s);
      const ago = this._ago(s);
      const msgs = s.message_count || 0;
      const titleParts = [name, this._toolName(s.tool), msgs + ' messages'];
      if (dur) titleParts.push(dur);
      if (cost) titleParts.push(cost);

      html += `
        <label class="se-analyze-row ${checked ? 'checked' : ''}" data-id="${this._esc(s.id)}" title="${titleParts.join(' \u2014 ')}">
          <input type="checkbox" ${checked ? 'checked' : ''}>
          <span class="se-dot" style="background:${this._toolColor(s.tool)}"></span>
          <div class="se-analyze-info">
            <span class="se-analyze-name">${this._esc(name)}</span>
            <span class="se-analyze-meta">${this._toolName(s.tool)} \u00b7 ${msgs} msgs${dur ? ' \u00b7 ' + dur : ''}${cost ? ' \u00b7 ' + cost : ''}</span>
          </div>
          <span class="se-analyze-ago">${ago}</span>
        </label>`;
    });
    return html;
  },

  _bindAnalyzeEvents(el) {
    el.querySelectorAll('.se-analyze-row input').forEach(cb => {
      cb.addEventListener('change', () => {
        const sid = cb.closest('.se-analyze-row').dataset.id;
        if (cb.checked) this._selected.add(sid); else this._selected.delete(sid);
        this.renderAnalyze();
      });
    });

    const bind = (id, fn) => { const b = el.querySelector('#' + id); if (b) b.addEventListener('click', fn); };

    bind('se-select-all', () => {
      this._selected = new Set(this._filtered.map(s => s.id));
      this.renderAnalyze();
    });
    bind('se-select-10', () => {
      this._selected.clear();
      this._filtered.slice(0, 10).forEach(s => this._selected.add(s.id));
      this.renderAnalyze();
    });
    bind('se-select-costly', () => {
      this._selected.clear();
      [...this._filtered].sort((a, b) => (b.estimated_cost_usd || 0) - (a.estimated_cost_usd || 0))
        .slice(0, 10).forEach(s => this._selected.add(s.id));
      this.renderAnalyze();
    });
    bind('se-select-none', () => {
      this._selected.clear();
      this.renderAnalyze();
    });

    bind('se-run-analyze', () => this._runAnalysis());
  },

  async _runAnalysis() {
    if (this._selected.size === 0) return;
    this._analyzing = true;
    this.renderAnalyze();

    try {
      const res = await fetch('/api/analyze-sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_ids: [...this._selected] }),
      });
      this._analysisResult = await res.json();
      const badge = document.getElementById('tab-badge-analyze');
      if (badge) badge.textContent = (this._analysisResult.score || '?') + '/100';
    } catch (_e) {
      this._analysisResult = null;
    }
    this._analyzing = false;
    this.renderAnalyze();
  },

  _renderProfile(data) {
    const score = data.score || 0;
    const dp = data.developer_profile || {};
    const grades = data.grades || {};
    const strengths = (data.strengths || []).slice(0, 3);
    const aps = (data.anti_patterns || []).slice(0, 3);
    const recs = (data.recommendations || []).slice(0, 3);

    const icons = { power_user: '\u26a1', debug_warrior: '\ud83d\udee1\ufe0f', explorer: '\ud83e\udded', methodical_builder: '\ud83c\udfd7\ufe0f', cautious_adopter: '\ud83c\udfaf', efficiency_optimizer: '\u2699\ufe0f' };
    const icon = icons[dp.ai_personality] || '\ud83d\udc64';
    const scoreColor = score >= 80 ? '#34d399' : score >= 60 ? '#2dd4bf' : score >= 40 ? '#fbbf24' : '#f87171';
    const circ = 2 * Math.PI * 28;
    const off = circ - (score / 100) * circ;

    const gradeMap = { session_hygiene: '\ud83e\uddf9 Hygiene', prompt_quality: '\u270d\ufe0f Prompts', cost_efficiency: '\ud83d\udcb0 Cost', cache_efficiency: '\u26a1 Cache', tool_utilization: '\ud83d\udd27 Tools' };
    const gNum = { A: 100, B: 75, C: 50, D: 25 };
    const gCol = { A: '#34d399', B: '#2dd4bf', C: '#fbbf24', D: '#f87171' };

    return `
      <div class="profile-card">
        <div class="profile-avatar">
          <svg viewBox="0 0 64 64" width="72" height="72">
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
      ${strengths.length > 0 ? `<div class="profile-section"><div class="profile-section-title">Powers</div>${strengths.map(s => `<div class="profile-power"><span class="profile-power-icon">${s.icon || '\u2713'}</span><span><strong>${this._esc(s.title || '')}</strong> \u2014 ${this._esc(s.detail || '')}</span></div>`).join('')}</div>` : ''}
      ${aps.length > 0 ? `<div class="profile-section"><div class="profile-section-title">Weaknesses</div>${aps.map(a => `<div class="profile-weakness"><span>${this._esc(a.pattern || '')}</span><span class="profile-weakness-count">${a.count || 0}x</span></div>`).join('')}</div>` : ''}
      ${recs.length > 0 ? `<div class="profile-section"><div class="profile-section-title">Quests</div>${recs.map(r => `<div class="profile-quest"><span class="profile-quest-dot" style="background:${{ high: '#f87171', medium: '#fbbf24', low: '#2dd4bf' }[r.priority] || '#71717a'}"></span><div><div class="profile-quest-title">${this._esc(r.title || '')}</div>${r.savings ? `<div class="profile-quest-reward">${this._esc(r.savings)}</div>` : ''}</div></div>`).join('')}</div>` : ''}
    `;
  },
};

document.addEventListener('DOMContentLoaded', () => SessionExplorer.init());
