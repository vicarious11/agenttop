/* agenttop — Stats Ribbon v2 */

const Stats = {
  _prevValues: {},

  render(stats) {
    const ribbon = document.getElementById('stats-ribbon');
    if (!stats || stats.length === 0) {
      ribbon.innerHTML = '';
      return;
    }

    const totals = {
      tokens: stats.reduce((s, t) => s + (t.tokens_today || 0), 0),
      cost: stats.reduce((s, t) => s + (t.estimated_cost_today || 0), 0),
      sessions: stats.reduce((s, t) => s + (t.sessions_today || 0), 0),
      messages: stats.reduce((s, t) => s + (t.messages_today || 0), 0),
      tools: stats.filter(t => t.status === 'active').length,
    };

    const items = [
      { key: 'tokens', label: 'Tokens', value: App.formatNum(totals.tokens), raw: totals.tokens, color: 'var(--neon-cyan)' },
      { key: 'cost', label: 'Cost', value: App.formatCost(totals.cost), raw: totals.cost, color: 'var(--neon-orange)' },
      { key: 'sessions', label: 'Sessions', value: totals.sessions.toLocaleString(), raw: totals.sessions, color: 'var(--neon-green)' },
      { key: 'messages', label: 'Messages', value: App.formatNum(totals.messages), raw: totals.messages, color: 'var(--neon-magenta)' },
      { key: 'tools', label: 'Active', value: `${totals.tools}/${stats.length}`, raw: totals.tools, color: 'var(--neon-blue)' },
    ];

    ribbon.innerHTML = items.map(item => `
      <div class="stat-card">
        <div class="stat-value" style="color:${item.color}" id="stat-${item.key}">${item.value}</div>
        <div class="stat-label">${item.label}</div>
        <svg class="stat-spark" id="spark-${item.key}"></svg>
      </div>
    `).join('');

    Stats._drawSparklines(stats);
  },

  _drawSparklines(stats) {
    // Aggregate hourly tokens
    const hourly = new Array(24).fill(0);
    stats.forEach(t => {
      (t.hourly_tokens || []).forEach((v, i) => { if (i < 24) hourly[i] += v; });
    });

    const draw = (id, data, color) => {
      const el = document.getElementById(id);
      if (!el) return;
      const w = 56, h = 14;
      const max = Math.max(...data, 1);
      const line = d3.line()
        .x((_, i) => (i / (data.length - 1)) * w)
        .y(d => h - 1 - (d / max) * (h - 3))
        .curve(d3.curveBasis);

      const svg = d3.select(`#${id}`).attr('viewBox', `0 0 ${w} ${h}`);
      svg.selectAll('*').remove();
      svg.append('path').attr('d', line(data)).style('stroke', color);
    };

    draw('spark-tokens', hourly, 'var(--neon-cyan)');

    // Per-tool message sparklines
    const msgHourly = new Array(24).fill(0);
    stats.forEach(t => {
      (t.hourly_tokens || []).forEach((v, i) => { if (i < 24) msgHourly[i] += v > 0 ? 1 : 0; });
    });
    draw('spark-messages', msgHourly, 'var(--neon-magenta)');
  },

  updateLive(data) {
    if (!data) return;
    const updates = {
      tokens: App.formatNum(data.tokens || 0),
      cost: App.formatCost(data.cost || 0),
      sessions: (data.sessions || 0).toLocaleString(),
      messages: App.formatNum(data.messages || 0),
    };

    for (const [key, value] of Object.entries(updates)) {
      const el = document.getElementById(`stat-${key}`);
      if (el && el.textContent !== value) {
        el.textContent = value;
        // Pop animation
        el.style.transform = 'scale(1.15)';
        setTimeout(() => { el.style.transform = 'scale(1)'; }, 200);
      }
    }
  }
};
