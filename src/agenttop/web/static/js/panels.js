/* agenttop — Data Panels: Models, Hourly, Sessions, Cost */

const Panels = {
  MODEL_PRICING: {
    opus:   { input: 15,   output: 75,  cache: 1.875 },
    sonnet: { input: 3,    output: 15,  cache: 0.30  },
    haiku:  { input: 0.80, output: 4,   cache: 0.08  },
    glm:    { input: 1,    output: 2,   cache: 0.5   },
  },

  MODEL_COLORS: {
    opus:   '#ff6b00',
    sonnet: '#ff9944',
    haiku:  '#ffcc88',
    glm:    '#00ff88',
  },

  modelDisplayName(id) {
    const mid = id.toLowerCase();
    const extractVer = (m, fam) => {
      const idx = m.indexOf(fam) + fam.length;
      const rest = m.slice(idx).replace(/^-/, '');
      const match = rest.match(/^(\d+)[.-](\d+)/);
      return match ? `${match[1]}.${match[2]}` : '';
    };
    if (mid.includes('opus'))   { const v = extractVer(mid, 'opus');   return v ? `Opus ${v}` : 'Opus'; }
    if (mid.includes('sonnet')) { const v = extractVer(mid, 'sonnet'); return v ? `Sonnet ${v}` : 'Sonnet'; }
    if (mid.includes('haiku'))  { const v = extractVer(mid, 'haiku');  return v ? `Haiku ${v}` : 'Haiku'; }
    if (mid.includes('glm'))    { const m2 = mid.match(/glm[- ]?(\d+\.?\d*)/); return m2 ? `GLM ${m2[1]}` : 'GLM'; }
    return id;
  },

  getModelFamily(id) {
    const mid = id.toLowerCase();
    if (mid.includes('opus'))   return 'opus';
    if (mid.includes('sonnet')) return 'sonnet';
    if (mid.includes('haiku'))  return 'haiku';
    if (mid.includes('glm'))    return 'glm';
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
      const billed = input + output;
      const total  = billed + cache;
      const cost   = Panels.estimateCost(id, input, output, cache);
      const color  = Panels.MODEL_COLORS[Panels.getModelFamily(id)] || '#ff9944';
      return { id, name: Panels.modelDisplayName(id), input, output, cache, billed, total, cost, color };
    }).filter(m => m.total > 0).sort((a, b) => b.billed - a.billed);

    if (models.length === 0) {
      el.innerHTML = '<div class="panel-empty">No model activity</div>';
      return;
    }

    const maxBilled = Math.max(...models.map(m => m.billed), 1);

    el.innerHTML = models.map(m => {
      const iPct = (m.input  / maxBilled * 100).toFixed(2);
      const oPct = (m.output / maxBilled * 100).toFixed(2);
      return `
        <div class="model-row" title="In: ${App.formatNum(m.input)} | Out: ${App.formatNum(m.output)} | Cache: ${App.formatNum(m.cache)}">
          <div class="model-info">
            <span class="model-name" style="color:${m.color}">${m.name}</span>
            <span class="model-stats">
              <span class="model-tokens">${App.formatNum(m.billed)}</span>
              <span class="model-cost">${App.formatCost(m.cost)}</span>
            </span>
          </div>
          <div class="model-bar-track">
            <div class="model-seg seg-input" style="width:${iPct}%" title="Input: ${App.formatNum(m.input)}"></div>
            <div class="model-seg seg-output" style="width:${oPct}%" title="Output: ${App.formatNum(m.output)}"></div>
          </div>
          <div class="model-breakdown">
            <span>in ${App.formatNum(m.input)}</span>
            <span>out ${App.formatNum(m.output)}</span>
            ${m.cache > 0 ? `<span>cache ${App.formatNum(m.cache)}</span>` : ''}
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
     DAILY COST — Histogram of cost per day
     ═══════════════════════════════════════════════════════ */
  _localDayKey(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  },

  renderDailyCost(sessions, days) {
    const el = document.getElementById('daily-cost-content');
    const summary = document.getElementById('daily-cost-summary');
    if (!sessions || sessions.length === 0) {
      el.innerHTML = '<div class="panel-empty">No cost data</div>';
      if (summary) summary.textContent = '';
      return;
    }

    const byDay = {};
    let earliest = null;
    sessions.forEach(s => {
      if (!s.start_time) return;
      const cost = s.estimated_cost_usd || 0;
      const start = new Date(s.start_time);
      const key = Panels._localDayKey(start);
      byDay[key] = (byDay[key] || 0) + cost;
      if (earliest === null || start < earliest) earliest = start;
    });

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    let nDays;
    if (days > 0) {
      nDays = days;
    } else if (earliest) {
      const earliestDay = new Date(earliest);
      earliestDay.setHours(0, 0, 0, 0);
      const spanDays = Math.round((today - earliestDay) / 86400000) + 1;
      nDays = Math.max(spanDays, 7);
    } else {
      nDays = 7;
    }

    // Auto-bucket so bars stay readable: daily ≤60d, weekly ≤365d, monthly beyond
    let bucketDays, unit, unitLabel;
    if (nDays <= 60)       { bucketDays = 1;  unit = 'd';  unitLabel = '/d'; }
    else if (nDays <= 365) { bucketDays = 7;  unit = 'wk'; unitLabel = '/wk'; }
    else                   { bucketDays = 30; unit = 'mo'; unitLabel = '/mo'; }

    const nBuckets = Math.ceil(nDays / bucketDays);
    const bars = [];
    for (let i = 0; i < nBuckets; i++) {
      const endOffset = (nBuckets - 1 - i) * bucketDays;
      const startOffset = endOffset + bucketDays - 1;
      let cost = 0;
      for (let off = endOffset; off <= startOffset; off++) {
        const d = new Date(today);
        d.setDate(today.getDate() - off);
        cost += byDay[Panels._localDayKey(d)] || 0;
      }
      const bucketStart = new Date(today);
      bucketStart.setDate(today.getDate() - startOffset);
      const label = unit === 'mo'
        ? bucketStart.toISOString().slice(0, 7)   // YYYY-MM
        : Panels._localDayKey(bucketStart).slice(5);  // MM-DD
      bars.push({ cost, label });
    }

    const max = Math.max(...bars.map(b => b.cost), 0.001);
    const total = bars.reduce((s, b) => s + b.cost, 0);
    const nonZero = bars.filter(b => b.cost > 0);
    const avg = nonZero.length > 0 ? total / nonZero.length : 0;
    const peakBar = bars.reduce((a, b) => b.cost > a.cost ? b : a, bars[0]);

    if (summary) {
      summary.textContent = peakBar.cost > 0
        ? `peak ${App.formatCost(peakBar.cost)} ${peakBar.label}`
        : '';
    }

    el.innerHTML = `
      <div class="daily-chart">
        ${bars.map(b => {
          const pct = Math.max((b.cost / max * 100), b.cost > 0 ? 2 : 0);
          const intensity = b.cost / max;
          const opacity = b.cost > 0 ? (0.35 + intensity * 0.65) : 0.1;
          return `
            <div class="day-col" title="${b.label}: ${App.formatCost(b.cost)}">
              <div class="day-bar-wrap">
                <div class="day-bar" style="height:${pct}%;opacity:${opacity}"></div>
              </div>
            </div>
          `;
        }).join('')}
      </div>
      <div class="daily-foot">
        <span>total ${App.formatCost(total)}</span>
        <span>avg ${App.formatCost(avg)}${unitLabel}</span>
        <span>${nBuckets} × ${bucketDays > 1 ? bucketDays + 'd' : 'day'}</span>
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
    const top = sessions.slice(0, 20);

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

  /* ═══════════════════════════════════════════════════════
     ACTIVITY BREAKDOWN + ONE-SHOT RATE
     ═══════════════════════════════════════════════════════ */

  ACTIVITY_COLORS: {
    coding: '#34d399', debugging: '#f87171', testing: '#fbbf24',
    exploration: '#22d3ee', refactoring: '#c084fc', git_ops: '#60a5fa',
    planning: '#f97316', other: '#71717a',
  },

  renderActivity(data) {
    const el = document.getElementById('activity-content');
    const badge = document.getElementById('oneshot-badge');
    if (!data || !data.activities) {
      el.innerHTML = '<div class="panel-empty">No activity data</div>';
      return;
    }

    const acts = data.activities;
    const rate = data.oneshot_rate || 0;
    const total = Object.values(acts).reduce((s, v) => s + v, 0);

    if (badge) {
      const rateColor = rate >= 80 ? 'var(--success)' : rate >= 60 ? 'var(--warning)' : 'var(--error)';
      badge.innerHTML = `<span style="color:${rateColor};font-weight:700">${rate.toFixed(0)}% one-shot</span>`;
    }

    if (total === 0) {
      el.innerHTML = '<div class="panel-empty">No sessions</div>';
      return;
    }

    const maxVal = Math.max(...Object.values(acts));

    el.innerHTML = Object.entries(acts)
      .filter(([, v]) => v > 0)
      .map(([act, count]) => {
        const pct = (count / total * 100).toFixed(0);
        const color = Panels.ACTIVITY_COLORS[act] || '#71717a';
        const barW = Math.max((count / maxVal * 100), 2).toFixed(1);
        const name = act.replace('_', ' ');
        return `
          <div class="activity-row">
            <span class="activity-name">${name}</span>
            <div class="activity-bar-track">
              <div class="activity-bar-fill" style="width:${barW}%;background:${color}"></div>
            </div>
            <span class="activity-pct" style="color:${color}">${pct}%</span>
            <span class="activity-count">${count}</span>
          </div>`;
      }).join('');
  },

  /* ═══════════════════════════════════════════════════════
     COST BY PROJECT
     ═══════════════════════════════════════════════════════ */

  renderProjectCost(data) {
    const el = document.getElementById('project-cost-content');
    if (!data || !data.cost_by_project || data.cost_by_project.length === 0) {
      el.innerHTML = '<div class="panel-empty">No project data</div>';
      return;
    }

    const projects = data.cost_by_project;
    const maxCost = projects[0].cost || 1;

    el.innerHTML = projects.map(p => {
      const barW = Math.max((p.cost / maxCost * 100), 2).toFixed(1);
      return `
        <div class="pcost-row">
          <span class="pcost-name">${p.project}</span>
          <div class="pcost-bar-track">
            <div class="pcost-bar-fill" style="width:${barW}%"></div>
          </div>
          <span class="pcost-val">${App.formatCost(p.cost)}</span>
          <span class="pcost-sess">${p.sessions}s</span>
        </div>`;
    }).join('');
  },
};
