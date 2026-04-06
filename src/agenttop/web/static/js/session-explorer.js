/* agenttop — Session Explorer: search, filter, detail, batch analysis */

const SessionExplorer = {
  _sessions: [],
  _filtered: [],
  _selected: new Set(),
  _activeId: null,
  _filters: { tool: '', project: '', search: '' },
  _sort: 'time',
  _analyzing: false,
  _lastShiftIdx: -1,

  async init() {
    // Initial load handled by App.refresh() which sets _sessions
  },

  async load() {
    const days = typeof App !== 'undefined' ? (App.days || 7) : 7;
    try {
      const res = await fetch(`/api/sessions?days=${days}`);
      SessionExplorer._sessions = await res.json();
      SessionExplorer._applyFilters();
      SessionExplorer.render();
    } catch (e) {
      console.error('Failed to load sessions:', e);
    }
  },

  _applyFilters() {
    let list = [...SessionExplorer._sessions];
    const f = SessionExplorer._filters;

    if (f.tool) list = list.filter(s => s.tool === f.tool);
    if (f.project) {
      const pq = f.project.toLowerCase();
      list = list.filter(s => (s.project || '').toLowerCase().includes(pq));
    }
    if (f.search) {
      const q = f.search.toLowerCase();
      list = list.filter(s => {
        const proj = (s.project || '').toLowerCase();
        const firstPrompt = ((s.prompts || [])[0] || '').toLowerCase();
        const sid = (s.id || '').toLowerCase();
        return proj.includes(q) || firstPrompt.includes(q) || sid.includes(q);
      });
    }

    if (SessionExplorer._sort === 'cost') {
      list.sort((a, b) => (b.estimated_cost_usd || 0) - (a.estimated_cost_usd || 0));
    } else if (SessionExplorer._sort === 'tokens') {
      list.sort((a, b) => (b.total_tokens || 0) - (a.total_tokens || 0));
    } else if (SessionExplorer._sort === 'duration') {
      const dur = s => {
        if (!s.start_time || !s.end_time) return 0;
        return new Date(s.end_time) - new Date(s.start_time);
      };
      list.sort((a, b) => dur(b) - dur(a));
    } else {
      // Default: newest first
      list.sort((a, b) => new Date(b.start_time || 0) - new Date(a.start_time || 0));
    }

    SessionExplorer._filtered = list;
  },

  _getTools() {
    const tools = new Set();
    SessionExplorer._sessions.forEach(s => { if (s.tool) tools.add(s.tool); });
    return [...tools].sort();
  },

  _formatDuration(s) {
    if (!s.start_time || !s.end_time) return '';
    const ms = new Date(s.end_time) - new Date(s.start_time);
    const mins = Math.round(ms / 60000);
    if (mins >= 60) return (mins / 60).toFixed(1) + 'h';
    if (mins > 0) return mins + 'm';
    return '';
  },

  _formatTimeAgo(s) {
    if (!s.start_time) return '';
    const ago = Date.now() - new Date(s.start_time).getTime();
    const hrs = Math.floor(ago / 3600000);
    if (hrs < 1) return 'now';
    if (hrs < 24) return hrs + 'h ago';
    const days = Math.floor(hrs / 24);
    if (days < 30) return days + 'd ago';
    return Math.floor(days / 30) + 'mo ago';
  },

  _toolDisplayName(tool) {
    const names = {
      claude_code: 'Claude', cursor: 'Cursor', kiro: 'Kiro',
      copilot: 'Copilot', codex: 'Codex', windsurf: 'Windsurf',
    };
    return names[tool] || tool;
  },

  _toolColor(tool) {
    return (typeof App !== 'undefined' && App.TOOL_COLORS)
      ? (App.TOOL_COLORS[tool] || '#888')
      : '#888';
  },

  _escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  render() {
    const el = document.getElementById('sessions-content');
    const badge = document.getElementById('sessions-count');
    if (!el) return;

    const total = SessionExplorer._sessions.length;
    const filtered = SessionExplorer._filtered;
    const selected = SessionExplorer._selected;
    const tools = SessionExplorer._getTools();

    if (badge) badge.textContent = total + ' sessions';

    if (total === 0) {
      el.innerHTML = '<div class="panel-empty">No sessions found for this period</div>';
      return;
    }

    // Toolbar
    const toolOpts = tools.map(t =>
      `<option value="${t}" ${SessionExplorer._filters.tool === t ? 'selected' : ''}>${SessionExplorer._toolDisplayName(t)}</option>`
    ).join('');

    const sortOpts = [
      ['time', 'Newest'], ['cost', 'Cost'], ['tokens', 'Tokens'], ['duration', 'Duration']
    ].map(([v, l]) =>
      `<option value="${v}" ${SessionExplorer._sort === v ? 'selected' : ''}>${l}</option>`
    ).join('');

    const analyzeActive = selected.size > 0 ? 'active' : '';
    const analyzeLabel = selected.size > 0
      ? `Analyze ${selected.size} Session${selected.size > 1 ? 's' : ''}`
      : 'Select sessions to analyze';

    let html = `<div class="se-container">
      <div class="se-toolbar">
        <input class="se-search" placeholder="Search by project or prompt..." value="${SessionExplorer._escapeHtml(SessionExplorer._filters.search)}">
        <select class="se-filter-tool">
          <option value="">All Tools</option>
          ${toolOpts}
        </select>
        <select class="se-sort">${sortOpts}</select>
        <button class="se-analyze-btn ${analyzeActive}" ${!analyzeActive ? 'disabled' : ''}>
          ${SessionExplorer._analyzing ? 'Analyzing...' : analyzeLabel}
        </button>
      </div>
      <div class="se-list">`;

    // Session rows — show tool, project, metrics, first prompt preview
    const display = filtered.slice(0, 100);
    display.forEach((s, idx) => {
      const proj = s.project ? (s.project.split('/').pop() || s.project) : 'unknown';
      const projLabel = proj.length > 20 ? proj.slice(0, 20) + '\u2026' : proj;
      const color = SessionExplorer._toolColor(s.tool);
      const toolName = SessionExplorer._toolDisplayName(s.tool);
      const dur = SessionExplorer._formatDuration(s);
      const timeAgo = SessionExplorer._formatTimeAgo(s);
      const tokens = s.total_tokens > 0 ? App.formatNum(s.total_tokens) : '-';
      const cost = s.estimated_cost_usd > 0 ? App.formatCost(s.estimated_cost_usd) : '-';
      const msgs = s.message_count || 0;
      const toolCalls = s.tool_call_count || 0;
      const isActive = s.id === SessionExplorer._activeId;
      const isSelected = selected.has(s.id);

      // First prompt preview
      const prompts = s.prompts || [];
      const firstPrompt = prompts.length > 0
        ? SessionExplorer._escapeHtml(prompts[0].slice(0, 60)) + (prompts[0].length > 60 ? '...' : '')
        : '';

      const cls = ['se-row', isActive ? 'active' : '', isSelected ? 'selected' : ''].filter(Boolean).join(' ');

      html += `
        <div class="${cls}" data-id="${SessionExplorer._escapeHtml(s.id)}" data-idx="${idx}">
          <input type="checkbox" class="se-check" ${isSelected ? 'checked' : ''}>
          <span class="se-dot" style="background:${color}" title="${toolName}"></span>
          <div class="se-main">
            <div class="se-row-top">
              <span class="se-project" title="${SessionExplorer._escapeHtml(s.project || '')}">${SessionExplorer._escapeHtml(projLabel)}</span>
              <span class="se-tool-label">${toolName}</span>
              <span class="se-time">${timeAgo}</span>
            </div>
            <div class="se-row-bottom">
              ${firstPrompt ? `<span class="se-preview">${firstPrompt}</span>` : ''}
            </div>
          </div>
          <div class="se-metrics">
            ${dur ? `<span class="se-metric">${dur}</span>` : ''}
            <span class="se-metric">${msgs} msg${msgs !== 1 ? 's' : ''}</span>
            <span class="se-metric">${tokens} tok</span>
            <span class="se-metric se-cost">${cost}</span>
          </div>
        </div>`;
    });

    if (filtered.length > 100) {
      html += `<div class="panel-empty" style="padding:8px;">+ ${filtered.length - 100} more sessions</div>`;
    }

    html += '</div></div>';
    el.innerHTML = html;

    // Event listeners
    SessionExplorer._bindEvents(el);
  },

  _bindEvents(container) {
    // Search
    const search = container.querySelector('.se-search');
    if (search) {
      let debounce;
      search.addEventListener('input', () => {
        clearTimeout(debounce);
        debounce = setTimeout(() => {
          SessionExplorer._filters.search = search.value;
          SessionExplorer._applyFilters();
          SessionExplorer.render();
          // Re-focus search and restore cursor
          const newSearch = document.querySelector('.se-search');
          if (newSearch) { newSearch.focus(); newSearch.selectionStart = newSearch.selectionEnd = search.value.length; }
        }, 200);
      });
    }

    // Tool filter
    const toolFilter = container.querySelector('.se-filter-tool');
    if (toolFilter) {
      toolFilter.addEventListener('change', () => {
        SessionExplorer._filters.tool = toolFilter.value;
        SessionExplorer._applyFilters();
        SessionExplorer.render();
      });
    }

    // Sort
    const sort = container.querySelector('.se-sort');
    if (sort) {
      sort.addEventListener('change', () => {
        SessionExplorer._sort = sort.value;
        SessionExplorer._applyFilters();
        SessionExplorer.render();
      });
    }

    // Analyze button
    const analyzeBtn = container.querySelector('.se-analyze-btn');
    if (analyzeBtn) {
      analyzeBtn.addEventListener('click', () => SessionExplorer.analyzeSelected());
    }

    // Row clicks and checkboxes
    container.querySelectorAll('.se-row').forEach(row => {
      const sid = row.dataset.id;
      const idx = parseInt(row.dataset.idx, 10);
      const checkbox = row.querySelector('.se-check');

      checkbox.addEventListener('click', (e) => {
        e.stopPropagation();
        if (e.shiftKey && SessionExplorer._lastShiftIdx >= 0) {
          // Range select
          const start = Math.min(SessionExplorer._lastShiftIdx, idx);
          const end = Math.max(SessionExplorer._lastShiftIdx, idx);
          const filtered = SessionExplorer._filtered;
          for (let i = start; i <= end; i++) {
            if (filtered[i]) SessionExplorer._selected.add(filtered[i].id);
          }
        } else {
          if (SessionExplorer._selected.has(sid)) {
            SessionExplorer._selected.delete(sid);
          } else {
            SessionExplorer._selected.add(sid);
          }
        }
        SessionExplorer._lastShiftIdx = idx;
        SessionExplorer.render();
      });

      row.addEventListener('click', (e) => {
        if (e.target.classList.contains('se-check')) return;
        SessionExplorer._activeId = sid;
        SessionExplorer.renderDetail(sid);
        SessionExplorer.render();
      });
    });
  },

  async renderDetail(sessionId) {
    const el = document.getElementById('sessions-content');
    if (!el) return;

    // Find session in local data first
    let session = SessionExplorer._sessions.find(s => s.id === sessionId);

    // Fetch full detail with prompts
    try {
      const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`);
      if (res.ok) {
        session = await res.json();
      }
    } catch (e) {
      console.warn('Failed to fetch session detail:', e);
    }

    if (!session) return;

    // Create or update detail panel
    let detail = el.querySelector('.se-detail');
    if (!detail) {
      detail = document.createElement('div');
      detail.className = 'se-detail';
      el.querySelector('.se-container').appendChild(detail);
    }

    const proj = session.project ? session.project.split('/').pop() : 'unknown';
    const color = SessionExplorer._toolColor(session.tool);
    const toolName = SessionExplorer._toolDisplayName(session.tool);
    const dur = SessionExplorer._formatDuration(session);
    const tokens = session.total_tokens ? App.formatNum(session.total_tokens) : '0';
    const cost = session.estimated_cost_usd ? App.formatCost(session.estimated_cost_usd) : '$0';
    const msgs = session.message_count || 0;
    const prompts = session.prompts || [];

    let promptsHtml = '';
    if (prompts.length === 0) {
      promptsHtml = '<div class="panel-empty">No prompt data available</div>';
    } else {
      promptsHtml = prompts.map((p, i) => {
        const truncated = p.length > 250 ? p.slice(0, 250) + '...' : p;
        return `
          <div class="se-prompt" data-full="${SessionExplorer._escapeHtml(p)}">
            <span class="se-prompt-num">${i + 1}</span>
            <span class="se-prompt-text" title="Click to expand">${SessionExplorer._escapeHtml(truncated)}</span>
          </div>`;
      }).join('');
    }

    detail.innerHTML = `
      <div class="se-detail-header">
        <button class="se-back">\u2190</button>
        <h3 style="flex:1;font-size:14px;">${SessionExplorer._escapeHtml(proj)}</h3>
        <span style="font-size:11px;color:${color};font-weight:600;">${toolName}</span>
      </div>
      <div class="se-detail-meta">
        ${dur ? `<span>${dur}</span>` : ''}
        <span>${msgs} messages</span>
        <span>${tokens} tokens</span>
        <span>${cost}</span>
      </div>
      <div class="se-prompts">${promptsHtml}</div>
      <div style="padding:12px;border-top:1px solid var(--border-default);">
        <button class="se-analyze-one">Analyze This Session</button>
      </div>`;

    // Slide in
    requestAnimationFrame(() => detail.classList.add('open'));

    // Back button
    detail.querySelector('.se-back').addEventListener('click', () => {
      detail.classList.remove('open');
      SessionExplorer._activeId = null;
      setTimeout(() => { if (detail.parentNode) detail.remove(); }, 200);
      SessionExplorer.render();
    });

    // Expand prompts on click
    detail.querySelectorAll('.se-prompt-text').forEach(pt => {
      pt.addEventListener('click', () => {
        if (pt.classList.contains('expanded')) {
          const truncated = pt.parentElement.dataset.full;
          pt.textContent = truncated.length > 250 ? truncated.slice(0, 250) + '...' : truncated;
          pt.classList.remove('expanded');
        } else {
          pt.textContent = pt.parentElement.dataset.full;
          pt.classList.add('expanded');
        }
      });
    });

    // Analyze single session
    detail.querySelector('.se-analyze-one').addEventListener('click', () => {
      SessionExplorer.analyzeOne(sessionId);
    });
  },

  async analyzeSelected() {
    const ids = [...SessionExplorer._selected];
    if (ids.length === 0) return;

    if (ids.length > 30 && !confirm(`Analyze ${ids.length} sessions? This may take a while.`)) {
      return;
    }

    SessionExplorer._analyzing = true;
    SessionExplorer.render();

    try {
      const res = await fetch('/api/analyze-sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_ids: ids }),
      });
      const data = await res.json();
      SessionExplorer._analyzing = false;
      SessionExplorer.render();
      SessionExplorer._showAnalysisResult(data);
    } catch (e) {
      SessionExplorer._analyzing = false;
      SessionExplorer.render();
      alert('Analysis failed: ' + e.message);
    }
  },

  async analyzeOne(sessionId) {
    const btn = document.querySelector('.se-analyze-one');
    if (btn) { btn.disabled = true; btn.textContent = 'Analyzing...'; }

    try {
      const res = await fetch('/api/analyze-sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_ids: [sessionId] }),
      });
      const data = await res.json();
      SessionExplorer._showInlineResult(data);
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = 'Analyze This Session'; }
      alert('Analysis failed: ' + e.message);
    }
  },

  _showAnalysisResult(data) {
    const el = document.getElementById('sessions-content');
    if (!el) return;

    let resultDiv = el.querySelector('.se-analysis-result');
    if (!resultDiv) {
      resultDiv = document.createElement('div');
      resultDiv.className = 'se-analysis-result';
      el.querySelector('.se-container').appendChild(resultDiv);
    }

    const score = data.score || 0;
    const scoreColor = score >= 80 ? 'var(--success)' :
                       score >= 60 ? 'var(--accent)' :
                       score >= 40 ? 'var(--warning)' : 'var(--error)';

    const recs = (data.recommendations || []).slice(0, 3);
    const aps = (data.anti_patterns || []).slice(0, 3);

    resultDiv.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
        <div>
          <span style="font-size:24px;font-weight:700;color:${scoreColor};">${score}</span>
          <span style="font-size:12px;color:var(--text-muted);">/100</span>
        </div>
        <button class="se-close-result" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:16px;">&times;</button>
      </div>
      ${aps.length > 0 ? `
        <div style="margin-bottom:8px;">
          <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">Issues Found</div>
          ${aps.map(ap => `<div style="font-size:12px;margin-bottom:2px;color:var(--warning);">${SessionExplorer._escapeHtml(ap.pattern)} (${ap.count}x)</div>`).join('')}
        </div>
      ` : ''}
      ${recs.length > 0 ? `
        <div>
          <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">Recommendations</div>
          ${recs.map(r => `<div style="font-size:12px;margin-bottom:4px;">
            <span style="color:var(--accent);">${SessionExplorer._escapeHtml(r.title || '')}</span>
            <div style="color:var(--text-secondary);font-size:11px;">${SessionExplorer._escapeHtml(r.description || '')}</div>
          </div>`).join('')}
        </div>
      ` : ''}`;

    resultDiv.querySelector('.se-close-result').addEventListener('click', () => {
      resultDiv.remove();
    });
  },

  _showInlineResult(data) {
    const detail = document.querySelector('.se-detail');
    if (!detail) return;

    const existingResult = detail.querySelector('.se-analysis-result');
    if (existingResult) existingResult.remove();

    const resultDiv = document.createElement('div');
    resultDiv.className = 'se-analysis-result';

    const score = data.score || 0;
    const scoreColor = score >= 80 ? 'var(--success)' :
                       score >= 60 ? 'var(--accent)' :
                       score >= 40 ? 'var(--warning)' : 'var(--error)';

    const profile = data.developer_profile || {};
    const aps = (data.anti_patterns || []).slice(0, 3);
    const recs = (data.recommendations || []).slice(0, 3);

    resultDiv.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
        <span style="font-size:28px;font-weight:700;color:${scoreColor};">${score}</span>
        <div>
          <div style="font-size:13px;font-weight:600;">${SessionExplorer._escapeHtml(profile.title || 'Session Analysis')}</div>
          <div style="font-size:11px;color:var(--text-muted);">${SessionExplorer._escapeHtml(profile.bio || '')}</div>
        </div>
      </div>
      ${aps.length > 0 ? aps.map(ap =>
        `<div style="font-size:12px;margin-bottom:4px;padding:6px 8px;background:var(--warning-dim);border-radius:4px;">
          <span style="color:var(--warning);">${SessionExplorer._escapeHtml(ap.pattern)}</span>
          <span style="color:var(--text-muted);"> — ${SessionExplorer._escapeHtml(ap.fix || '')}</span>
        </div>`
      ).join('') : ''}
      ${recs.length > 0 ? recs.map(r =>
        `<div style="font-size:12px;margin-bottom:4px;padding:6px 8px;background:var(--accent-dim);border-radius:4px;">
          <span style="color:var(--accent);">${SessionExplorer._escapeHtml(r.title || '')}</span>
          <div style="font-size:11px;color:var(--text-secondary);margin-top:2px;">${SessionExplorer._escapeHtml(r.description || '')}</div>
        </div>`
      ).join('') : ''}`;

    // Insert before the analyze button container
    const btnContainer = detail.querySelector('.se-analyze-one').parentElement;
    detail.insertBefore(resultDiv, btnContainer);

    // Update button
    const btn = detail.querySelector('.se-analyze-one');
    if (btn) { btn.disabled = false; btn.textContent = 'Re-analyze'; }
  },
};
