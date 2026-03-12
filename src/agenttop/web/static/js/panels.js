/* agenttop — Data Panels: Models, Hourly, Sessions, Cost */

const Panels = {
  MODEL_PRICING: {
    opus:           { input: 15,   output: 75,  cache: 1.875 },
    sonnet:         { input: 3,    output: 15,  cache: 0.30  },
    haiku:          { input: 0.80, output: 4,   cache: 0.08  },
    glm:            { input: 1,    output: 2,   cache: 0.5   },
    cursor_agent:   { input: 3,    output: 15,  cache: 0.30  },
    cursor_chat:    { input: 0.80, output: 4,   cache: 0.08  },
    copilot:        { input: 0,    output: 0,   cache: 0     },
  },

  MODEL_COLORS: {
    opus:         '#ff6b00',
    sonnet:       '#ff9944',
    haiku:        '#ffcc88',
    glm:          '#00ff88',
    cursor_agent: '#00d4ff',
    cursor_chat:  '#66e8ff',
    copilot:      '#8b5cf6',
  },

  modelDisplayName(id) {
    const mid = id.toLowerCase();
    const extractVer = (m, fam) => {
      const idx = m.indexOf(fam) + fam.length;
      const rest = m.slice(idx).replace(/^-/, '');
      const match = rest.match(/^(\d+)[.-](\d+)/);
      return match ? `${match[1]}.${match[2]}` : '';
    };
    if (mid.includes('opus'))         { const v = extractVer(mid, 'opus');   return v ? `Opus ${v}` : 'Opus'; }
    if (mid.includes('sonnet'))       { const v = extractVer(mid, 'sonnet'); return v ? `Sonnet ${v}` : 'Sonnet'; }
    if (mid.includes('haiku'))        { const v = extractVer(mid, 'haiku');  return v ? `Haiku ${v}` : 'Haiku'; }
    if (mid.includes('glm'))          { const m2 = mid.match(/glm[- ]?(\d+\.?\d*)/); return m2 ? `GLM ${m2[1]}` : 'GLM'; }
    if (mid === 'cursor-agent')       return 'Cursor Agent';
    if (mid === 'cursor-chat')        return 'Cursor Chat';
    if (mid.startsWith('cursor'))     return 'Cursor';
    if (mid.includes('copilot'))      return 'Copilot';
    if (mid.includes('gpt-4'))        return mid.includes('mini') ? 'GPT-4o mini' : 'GPT-4o';
    if (mid.includes('gemini'))       { const m2 = mid.match(/gemini[- ]?([a-z0-9.]+)/); return m2 ? `Gemini ${m2[1]}` : 'Gemini'; }
    if (mid === '<synthetic>')        return 'Internal / Synthetic';
    return id;
  },

  getModelFamily(id) {
    const mid = id.toLowerCase();
    if (mid.includes('opus'))         return 'opus';
    if (mid.includes('sonnet'))       return 'sonnet';
    if (mid.includes('haiku'))        return 'haiku';
    if (mid.includes('glm'))          return 'glm';
    if (mid === 'cursor-agent')       return 'cursor_agent';
    if (mid.startsWith('cursor'))     return 'cursor_chat';
    if (mid.includes('copilot'))      return 'copilot';
    if (mid.includes('gpt'))          return 'cursor_chat';   // GPT-based Cursor models
    return 'sonnet';
  },

  estimateCost(modelId, input, output, cache) {
    const fam = Panels.getModelFamily(modelId);
    const p = Panels.MODEL_PRICING[fam] || Panels.MODEL_PRICING.sonnet;
    return (input * p.input + output * p.output + cache * p.cache) / 1_000_000;
  },

  /* ═══════════════════════════════════════════════════════
     MODEL USAGE — Segmented horizontal bars per model
     ═══════════════════════════════════════════════════════ */
  renderModels(modelData) {
    const el = document.getElementById('model-content');
    if (!modelData || Object.keys(modelData).length === 0) {
      el.innerHTML = '<div class="panel-empty">No model data available</div>';
      return;
    }

    const models = Object.entries(modelData).map(([id, usage]) => {
      const input  = usage.inputTokens || 0;
      const output = usage.outputTokens || 0;
      const cache  = usage.cacheReadInputTokens || 0;
      const total  = input + output + cache;
      const cost   = Panels.estimateCost(id, input, output, cache);
      const color  = Panels.MODEL_COLORS[Panels.getModelFamily(id)] || '#ff9944';
      return { id, name: Panels.modelDisplayName(id), input, output, cache, total, cost, color };
    }).filter(m => m.total > 0 && !m.id.includes('synthetic')).sort((a, b) => b.total - a.total);

    if (models.length === 0) {
      el.innerHTML = '<div class="panel-empty">No model activity</div>';
      return;
    }

    const maxTotal = Math.max(...models.map(m => m.total), 1);

    el.innerHTML = models.map(m => {
      const iPct = (m.input  / maxTotal * 100).toFixed(2);
      const oPct = (m.output / maxTotal * 100).toFixed(2);
      const cPct = (m.cache  / maxTotal * 100).toFixed(2);
      return `
        <div class="model-row">
          <div class="model-info">
            <span class="model-name" style="color:${m.color}">${m.name}</span>
            <span class="model-stats">
              <span class="model-tokens">${App.formatNum(m.total)}</span>
              <span class="model-cost">${App.formatCost(m.cost)}</span>
            </span>
          </div>
          <div class="model-bar-track">
            <div class="model-seg seg-input" style="width:${iPct}%" title="Input: ${App.formatNum(m.input)}"></div>
            <div class="model-seg seg-output" style="width:${oPct}%" title="Output: ${App.formatNum(m.output)}"></div>
            <div class="model-seg seg-cache" style="width:${cPct}%" title="Cache: ${App.formatNum(m.cache)}"></div>
          </div>
        </div>
      `;
    }).join('');
  },

  /* ═══════════════════════════════════════════════════════
     HOURLY ACTIVITY — 24-column bar chart
     ═══════════════════════════════════════════════════════ */
  renderHourly(hourData) {
    const el = document.getElementById('hourly-content');
    const badge = document.getElementById('hourly-total');
    if (!hourData || Object.keys(hourData).length === 0) {
      el.innerHTML = '<div class="panel-empty">No hourly data</div>';
      return;
    }

    const hours = Array.from({ length: 24 }, (_, i) => ({
      hour: i,
      count: hourData[String(i)] || 0,
    }));
    const total = hours.reduce((s, h) => s + h.count, 0);
    const max = Math.max(...hours.map(h => h.count), 1);
    const now = new Date().getHours();

    if (badge) badge.textContent = `${App.formatNum(total)} events`;

    el.innerHTML = `
      <div class="hourly-chart">
        ${hours.map(h => {
          const pct = Math.max((h.count / max * 100), 2);
          const isNow = h.hour === now;
          const intensity = h.count / max;
          const opacity = 0.25 + intensity * 0.75;
          const showLabel = h.hour % 4 === 0;
          const label = h.hour === 0 ? '12a' : h.hour < 12 ? `${h.hour}a` : h.hour === 12 ? '12p' : `${h.hour - 12}p`;
          return `
            <div class="hour-col ${isNow ? 'hour-now' : ''}" title="${label}: ${h.count.toLocaleString()} events">
              <div class="hour-bar-wrap">
                <div class="hour-bar" style="height:${pct}%;opacity:${opacity}"></div>
              </div>
              ${showLabel ? `<div class="hour-label">${label}</div>` : '<div class="hour-label-spacer"></div>'}
            </div>
          `;
        }).join('')}
      </div>
    `;
  },

  /* ═══════════════════════════════════════════════════════
     RECENT SESSIONS — Compact scrollable list
     ═══════════════════════════════════════════════════════ */
  renderSessions(sessions) {
    const el = document.getElementById('sessions-content');
    const badge = document.getElementById('sessions-count');
    if (!sessions || sessions.length === 0) {
      el.innerHTML = '<div class="panel-empty">No sessions found</div>';
      return;
    }

    if (badge) badge.textContent = `${sessions.length} total`;
    // Only show sessions with a known project name
    const filtered = sessions.filter(s => s.project && s.project !== 'unknown');
    const top = filtered.slice(0, 20);

    el.innerHTML = `
      <div class="sessions-list">
        ${top.map((s, i) => {
          const proj = s.project ? (s.project.split('/').pop() || s.project) : 'unknown';
          const projLabel = proj.length > 18 ? proj.slice(0, 18) + '\u2026' : proj;
          const tokens = s.total_tokens || 0;
          const tool = s.tool || 'unknown';
          const color = App.TOOL_COLORS[tool] || '#888';
          const msgCount = (s.events || []).length;

          let dur = '';
          if (s.start_time && s.end_time) {
            const ms = new Date(s.end_time) - new Date(s.start_time);
            const mins = Math.round(ms / 60000);
            if (mins >= 60) dur = `${(mins / 60).toFixed(1)}h`;
            else if (mins > 0) dur = `${mins}m`;
          }

          let timeAgo = '';
          if (s.start_time) {
            const ago = Date.now() - new Date(s.start_time).getTime();
            const hrs = Math.floor(ago / 3600000);
            if (hrs < 1) timeAgo = 'now';
            else if (hrs < 24) timeAgo = `${hrs}h ago`;
            else timeAgo = `${Math.floor(hrs / 24)}d ago`;
          }

          return `
            <div class="session-row" style="animation-delay:${i * 30}ms">
              <span class="session-dot" style="background:${color};box-shadow:0 0 4px ${color}"></span>
              <span class="session-project" title="${s.project || ''}">${projLabel}</span>
              ${dur ? `<span class="session-badge session-dur">${dur}</span>` : ''}
              ${msgCount > 0 ? `<span class="session-badge session-msgs">${msgCount} msg</span>` : ''}
              <span class="session-tokens">${tokens > 0 ? App.formatNum(tokens) : '-'}</span>
              <span class="session-time">${timeAgo}</span>
            </div>
          `;
        }).join('')}
      </div>
    `;
  },

  /* ═══════════════════════════════════════════════════════
     COST BREAKDOWN — Bars per tool
     ═══════════════════════════════════════════════════════ */
  renderCost(stats) {
    const el = document.getElementById('cost-content');
    const badge = document.getElementById('cost-total-badge');
    if (!stats || stats.length === 0) {
      el.innerHTML = '<div class="panel-empty">No cost data</div>';
      return;
    }

    const items = stats
      .filter(s => (s.estimated_cost_today || 0) > 0 || (s.tokens_today || 0) > 0)
      .sort((a, b) => (b.estimated_cost_today || 0) - (a.estimated_cost_today || 0));

    if (items.length === 0) {
      el.innerHTML = '<div class="panel-empty">No cost data available</div>';
      return;
    }

    const totalCost = items.reduce((s, i) => s + (i.estimated_cost_today || 0), 0);
    const totalTokens = items.reduce((s, i) => s + (i.tokens_today || 0), 0);
    const maxCost = Math.max(...items.map(i => i.estimated_cost_today || 0), 0.01);

    if (badge) badge.textContent = App.formatCost(totalCost);

    el.innerHTML = `
      <div class="cost-summary">
        <div class="cost-sum-item">
          <span class="cost-sum-val" style="color:var(--neon-orange)">${App.formatCost(totalCost)}</span>
          <span class="cost-sum-label">total cost</span>
        </div>
        <div class="cost-sum-item">
          <span class="cost-sum-val" style="color:var(--neon-cyan)">${App.formatNum(totalTokens)}</span>
          <span class="cost-sum-label">total tokens</span>
        </div>
        <div class="cost-sum-item">
          <span class="cost-sum-val" style="color:var(--neon-green)">${totalTokens > 0 ? '$' + (totalCost / totalTokens * 1_000_000).toFixed(2) : '$0'}</span>
          <span class="cost-sum-label">per M tokens</span>
        </div>
      </div>
      ${items.map(s => {
        const cost = s.estimated_cost_today || 0;
        const pct = Math.max((cost / maxCost * 100), 1).toFixed(1);
        const color = App.TOOL_COLORS[s.tool] || '#888';
        return `
          <div class="cost-row">
            <div class="cost-info">
              <span class="cost-dot" style="background:${color}"></span>
              <span class="cost-name">${s.display_name}</span>
            </div>
            <div class="cost-bar-track">
              <div class="cost-bar-fill" style="width:${pct}%;background:${color};box-shadow:0 0 8px ${color}40"></div>
            </div>
            <span class="cost-value">${App.formatCost(cost)}</span>
          </div>
        `;
      }).join('')}
    `;
  },
};
