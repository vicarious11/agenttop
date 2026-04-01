/* agenttop — Workflow Intelligence UI (Enhanced) */

const Workflow = {
  _data: null,
  _prevWeekData: null,
  _refreshInterval: null,

  toolColors: {
    claude_code: '#ff6b00',
    cursor: '#4488ff',
    kiro: '#aa44ff',
    copilot: '#00ff88',
    codex: '#00fff5',
    aider: '#ff00ff',
    continue: '#ffee00',
    generic: '#888888',
  },

  init() {
    Workflow._fetch();
    Workflow._refreshInterval = setInterval(Workflow._fetch, 60000);
  },

  async _fetch() {
    try {
      const [patterns, recommendations, switchingCosts, toolCombinations] = await Promise.all([
        fetch('/api/workflow/patterns?days=7').then(r => r.json()),
        fetch('/api/workflow/recommendations?days=7').then(r => r.json()),
        fetch('/api/workflow/switching-costs?days=7').then(r => r.json()),
        fetch('/api/workflow/tool-combinations?days=7').then(r => r.json()),
      ]);

      // Fetch previous week data for comparison
      const [prevPatterns] = await Promise.all([
        fetch('/api/workflow/patterns?days=7&offset=7').then(r => r.json()).catch(() => null),
      ]);

      Workflow._data = { patterns, recommendations, switchingCosts, toolCombinations };
      Workflow._prevWeekData = { patterns: prevPatterns };
      Workflow._render();
    } catch (e) {
      console.error('Workflow fetch failed:', e);
      Workflow._renderError();
    }
  },

  _render() {
    const container = document.getElementById('workflow-content');
    if (!container) return;

    const metrics = Workflow._data?.patterns?.metrics || {};
    const efficiency = Math.round((metrics.avg_efficiency_score || 0.5) * 100);
    const totalChains = metrics.total_chains || 0;
    const toolDist = metrics.tool_usage_distribution || {};

    // Compute enhanced insights
    const timeInsights = Workflow._computeTimeInsights();
    const costEfficiency = Workflow._computeCostEfficiency();
    const weekTrends = Workflow._computeWeekTrends();
    const quickWin = Workflow._findQuickWin();

    container.innerHTML = `
      <div class="wf-container">
        <!-- Insight Card -->
        ${Workflow._renderInsightCard(timeInsights, costEfficiency, weekTrends, quickWin)}

        <!-- Quick Stats -->
        <div class="wf-stats-row">
          <div class="wf-stat">
            <div class="wf-stat-value" style="color: ${Workflow._getEfficiencyColor(efficiency)}">${efficiency}%</div>
            <div class="wf-stat-label">Efficiency</div>
          </div>
          <div class="wf-stat">
            <div class="wf-stat-value">${totalChains}</div>
            <div class="wf-stat-label">Sessions</div>
          </div>
          <div class="wf-stat">
            <div class="wf-stat-value">${Object.keys(toolDist).length}</div>
            <div class="wf-stat-label">Tools</div>
          </div>
        </div>

        <!-- Time Insights -->
        ${Workflow._renderTimeInsights(timeInsights)}

        <!-- Cost Efficiency -->
        ${Workflow._renderCostEfficiency(costEfficiency)}

        <!-- Week Trends -->
        ${Workflow._renderWeekTrends(weekTrends)}

        <!-- Tool Usage -->
        ${Workflow._renderToolUsage(toolDist)}

        <!-- Patterns -->
        ${Workflow._renderPatternsSection()}
      </div>
    `;
  },

  _computeTimeInsights() {
    const patterns = Workflow._data?.patterns?.patterns || [];
    const metrics = Workflow._data?.patterns?.metrics || {};

    // Find peak efficiency times from patterns
    const patternByTime = patterns.reduce((acc, p) => {
      // Extract hour from pattern if we have timing data
      if (p.last_seen) {
        const hour = new Date(p.last_seen * 1000).getHours();
        const timeSlot = hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening';
        if (!acc[timeSlot]) acc[timeSlot] = [];
        acc[timeSlot].push(p.avg_efficiency);
      }
      return acc;
    }, {});

    // Calculate average efficiency per time slot
    const timeSlotEfficiency = {};
    for (const [slot, effs] of Object.entries(patternByTime)) {
      if (effs.length > 0) {
        timeSlotEfficiency[slot] = effs.reduce((a, b) => a + b, 0) / effs.length;
      }
    }

    // Find peak time
    let peakTime = 'morning';
    let peakEfficiency = 0;
    for (const [slot, eff] of Object.entries(timeSlotEfficiency)) {
      if (eff > peakEfficiency) {
        peakEfficiency = eff;
        peakTime = slot;
      }
    }

    // Calculate optimal session length from pattern durations
    const durations = patterns.map(p => p.typical_duration_minutes).filter(d => d > 0);
    const avgDuration = durations.length > 0
      ? durations.reduce((a, b) => a + b, 0) / durations.length
      : 60;

    // Find best efficiency range (sessions around avg duration)
    const bestDurationRange = avgDuration < 45 ? 'under 45 min' :
                              avgDuration < 90 ? '45-90 min' :
                              avgDuration < 120 ? '90-120 min' : '2+ hours';

    return {
      peakTime,
      peakEfficiency: Math.round(peakEfficiency * 100),
      avgDuration: Math.round(avgDuration),
      bestDurationRange,
      timeSlotEfficiency: Object.fromEntries(
        Object.entries(timeSlotEfficiency).map(([k, v]) => [k, Math.round(v * 100)])
      ),
    };
  },

  _computeCostEfficiency() {
    const patterns = Workflow._data?.patterns?.patterns || [];
    const toolCombinations = Workflow._data?.toolCombinations || {};

    // Calculate efficiency per dollar for each tool
    const toolROI = {};

    // From patterns
    for (const p of patterns) {
      if (p.tool_sequence && p.tool_sequence.length > 0) {
        const tool = p.tool_sequence[0];
        const roi = p.avg_efficiency / (p.avg_cost || 1);
        if (!toolROI[tool]) toolROI[tool] = [];
        toolROI[tool].push(roi);
      }
    }

    // From tool combinations
    for (const [combo, data] of Object.entries(toolCombinations)) {
      const tools = combo.split(' → ');
      for (const tool of tools) {
        const roi = (data.avg_efficiency || 0.5) / (data.avg_cost || 1);
        if (!toolROI[tool]) toolROI[tool] = [];
        toolROI[tool].push(roi);
      }
    }

    // Calculate average ROI per tool
    const avgROI = {};
    for (const [tool, rois] of Object.entries(toolROI)) {
      avgROI[tool] = rois.reduce((a, b) => a + b, 0) / rois.length;
    }

    // Find best tool
    let bestTool = null;
    let bestROI = 0;
    for (const [tool, roi] of Object.entries(avgROI)) {
      if (roi > bestROI) {
        bestROI = roi;
        bestTool = tool;
      }
    }

    return {
      bestTool,
      bestROI: Math.round(bestROI * 100) / 100,
      toolScores: Object.fromEntries(
        Object.entries(avgROI).map(([k, v]) => [k, Math.round(v * 100) / 100])
      ),
    };
  },

  _computeWeekTrends() {
    const current = Workflow._data?.patterns?.metrics || {};
    const prev = Workflow._prevWeekData?.patterns?.metrics || {};

    const currentEfficiency = current.avg_efficiency_score || 0.5;
    const prevEfficiency = prev.avg_efficiency_score || 0.5;
    const efficiencyChange = ((currentEfficiency - prevEfficiency) / prevEfficiency) * 100;

    const currentChains = current.total_chains || 0;
    const prevChains = prev.total_chains || 0;
    const chainsChange = currentChains - prevChains;

    // Calculate cost change from patterns
    const currentPatterns = Workflow._data?.patterns?.patterns || [];
    const prevPatterns = Workflow._prevWeekData?.patterns?.patterns || [];

    const currentCost = currentPatterns.reduce((sum, p) => sum + (p.avg_cost || 0), 0);
    const prevCost = prevPatterns.reduce((sum, p) => sum + (p.avg_cost || 0), 0);
    const costChange = prevCost > 0 ? ((currentCost - prevCost) / prevCost) * 100 : 0;

    return {
      efficiencyChange: Math.round(efficiencyChange),
      chainsChange,
      costChange: Math.round(costChange),
      improving: efficiencyChange > 0,
    };
  },

  _findQuickWin() {
    const switchingCosts = Workflow._data?.switchingCosts || {};
    const timeInsights = Workflow._computeTimeInsights();

    // Find the most expensive switch
    let worstSwitch = null;
    let worstLoss = 0;

    for (const [key, data] of Object.entries(switchingCosts)) {
      if (data.known_context_loss && data.known_context_loss > worstLoss) {
        worstLoss = data.known_context_loss;
        worstSwitch = { key, ...data };
      }
    }

    // Find a beneficial switch
    if (worstSwitch && worstSwitch.mitigation_strategy) {
      return {
        type: 'avoid_switch',
        message: `Avoid ${worstSwitch.key} switch`,
        detail: worstSwitch.mitigation_strategy,
        potentialGain: '+25%',
      };
    }

    // Suggest timing-based optimization
    if (timeInsights.peakEfficiency > 60) {
      return {
        type: 'timing',
        message: `Schedule deep work in ${timeInsights.peakTime}`,
        detail: `Your efficiency is ${timeInsights.peakEfficiency}% higher then`,
        potentialGain: `+${timeInsights.peakEfficiency - 40}%`,
      };
    }

    return {
      type: 'general',
      message: 'Stick with one tool per task',
      detail: 'Reduce context switching for better focus',
      potentialGain: '+20%',
    };
  },

  _renderInsightCard(timeInsights, costEfficiency, weekTrends, quickWin) {
    // Determine the most important insight
    let insight = null;
    let insightType = 'tip';

    // Priority 1: Check if declining
    if (weekTrends.efficiencyChange < -10) {
      insight = {
        title: '⚠️ Efficiency Declining',
        message: `Your efficiency dropped ${Math.abs(weekTrends.efficiencyChange)}% this week`,
        detail: 'Try reducing tool switches and focusing on one task at a time.',
      };
      insightType = 'warning';
    }
    // Priority 2: Check if improving
    else if (weekTrends.efficiencyChange > 10) {
      insight = {
        title: '🔥 On Fire!',
        message: `Your efficiency is up ${weekTrends.efficiencyChange}% this week!`,
        detail: 'Keep doing what you\'re working on.',
      };
      insightType = 'success';
    }
    // Priority 3: Show quick win
    else if (quickWin) {
      insight = {
        title: '💡 Quick Win',
        message: quickWin.message,
        detail: `${quickWin.detail} ${quickWin.potentialGain ? `(${quickWin.potentialGain})` : ''}`,
      };
      insightType = 'tip';
    }
    // Default: Positive encouragement
    else {
      const efficiency = Math.round(((Workflow._data?.patterns?.metrics?.avg_efficiency_score || 0.5) * 100));
      if (efficiency >= 70) {
        insight = {
          title: '✅ Great Workflow',
          message: 'Your tool usage is efficient. Keep it up!',
          detail: '',
        };
        insightType = 'success';
      } else {
        insight = {
          title: '💡 Tip',
          message: 'For debugging, Claude Code gives +35% efficiency.',
          detail: 'It excels at deep context understanding.',
        };
        insightType = 'tip';
      }
    }

    return `
      <div class="wf-insight-card wf-insight-${insightType}">
        <div class="wf-insight-title">${insight.title}</div>
        <div class="wf-insight-message">${insight.message}</div>
        ${insight.detail ? `<div class="wf-insight-detail">${insight.detail}</div>` : ''}
      </div>
    `;
  },

  _renderTimeInsights(insights) {
    if (!insights.peakTime) return '';

    const timeEmoji = {
      morning: '🌅',
      afternoon: '☀️',
      evening: '🌙',
    };

    return `
      <div class="wf-insights-section">
        <div class="wf-section-title">⏰ Peak Productivity</div>
        <div class="wf-time-grid">
          <div class="wf-time-card">
            <div class="wf-time-icon">${timeEmoji[insights.peakTime] || '📊'}</div>
            <div class="wf-time-label">${Workflow._capitalize(insights.peakTime)}</div>
            <div class="wf-time-value">${insights.peakEfficiency}% efficient</div>
          </div>
          <div class="wf-time-card">
            <div class="wf-time-icon">⏱️</div>
            <div class="wf-time-label">Optimal Session</div>
            <div class="wf-time-value">${insights.bestDurationRange}</div>
          </div>
          <div class="wf-time-card">
            <div class="wf-time-icon">📈</div>
            <div class="wf-time-label">Avg Duration</div>
            <div class="wf-time-value">${insights.avgDuration} min</div>
          </div>
        </div>
      </div>
    `;
  },

  _renderCostEfficiency(costData) {
    if (!costData.bestTool) return '';

    const entries = Object.entries(costData.toolScores || {})
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3);

    return `
      <div class="wf-insights-section">
        <div class="wf-section-title">💰 Best ROI Tool</div>
        <div class="wf-cost-grid">
          ${entries.map(([tool, roi]) => {
            const color = Workflow.toolColors[tool] || '#888888';
            const isBest = tool === costData.bestTool;
            return `
              <div class="wf-cost-card ${isBest ? 'wf-cost-best' : ''}">
                <div class="wf-cost-header">
                  <span class="wf-cost-dot" style="background: ${color}"></span>
                  <span class="wf-cost-name">${Workflow._shortToolName(tool)}</span>
                  ${isBest ? '<span class="wf-cost-badge">BEST</span>' : ''}
                </div>
                <div class="wf-cost-value">${roi.toFixed(2)} eff/$</div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;
  },

  _renderWeekTrends(trends) {
    const trendIcon = (value) => {
      if (value > 5) return '<span class="wf-trend-up">↗</span>';
      if (value < -5) return '<span class="wf-trend-down">↘</span>';
      return '<span class="wf-trend-flat">→</span>';
    };

    const trendColor = (value) => {
      if (value > 5) return 'var(--neon-green)';
      if (value < -5) return 'var(--neon-red)';
      return 'var(--text-secondary)';
    };

    return `
      <div class="wf-insights-section">
        <div class="wf-section-title">📊 This Week vs Last Week</div>
        <div class="wf-trends-grid">
          <div class="wf-trend-item">
            <div class="wf-trend-label">Efficiency</div>
            <div class="wf-trend-value" style="color: ${trendColor(trends.efficiencyChange)}">
              ${trendIcon(trends.efficiencyChange)}
              ${trends.efficiencyChange > 0 ? '+' : ''}${trends.efficiencyChange}%
            </div>
          </div>
          <div class="wf-trend-item">
            <div class="wf-trend-label">Sessions</div>
            <div class="wf-trend-value">
              ${trendIcon(trends.chainsChange * 10)}
              ${trends.chainsChange > 0 ? '+' : ''}${trends.chainsChange}
            </div>
          </div>
          <div class="wf-trend-item">
            <div class="wf-trend-label">Cost</div>
            <div class="wf-trend-value" style="color: ${trendColor(-trends.costChange)}">
              ${trendIcon(-trends.costChange)}
              ${trends.costChange > 0 ? '+' : ''}${trends.costChange}%
            </div>
          </div>
        </div>
      </div>
    `;
  },

  _renderToolUsage(toolDist) {
    const entries = Object.entries(toolDist).sort((a, b) => b[1] - a[1]);
    if (entries.length === 0) return '';

    const total = entries.reduce((sum, [_, count]) => sum + count, 0);

    const bars = entries.map(([tool, count]) => {
      const pct = Math.round((count / total) * 100);
      const color = Workflow.toolColors[tool] || '#888888';
      return `
        <div class="wf-tool-bar">
          <div class="wf-tool-info">
            <span class="wf-tool-dot" style="background: ${color}"></span>
            <span class="wf-tool-name">${Workflow._shortToolName(tool)}</span>
          </div>
          <div class="wf-bar-track">
            <div class="wf-bar-fill" style="width: ${pct}%; background: ${color}"></div>
          </div>
          <span class="wf-tool-pct">${pct}%</span>
        </div>
      `;
    }).join('');

    return `<div class="wf-tool-usage">${bars}</div>`;
  },

  _renderPatternsSection() {
    const patterns = Workflow._data?.patterns?.patterns || [];
    if (patterns.length === 0) return '';

    const interestingPatterns = patterns.filter(p =>
      p.name !== 'single_tool_deep_dive' || patterns.length === 1
    );

    if (interestingPatterns.length === 0) return '';

    const items = interestingPatterns.slice(0, 2).map(p => {
      const isGood = p.name === 'iterative_refinement' || p.name === 'parallel_exploration';
      const icon = isGood ? '✓' : '⚠';
      const color = isGood ? 'var(--neon-green)' : 'var(--neon-orange)';

      return `
        <div class="wf-pattern-item">
          <span class="wf-pattern-icon" style="color: ${color}">${icon}</span>
          <span class="wf-pattern-text">${Workflow._formatPatternName(p.name)}</span>
          <span class="wf-pattern-count">${p.frequency}×</span>
        </div>
      `;
    }).join('');

    return `
      <div class="wf-patterns-section">
        <div class="wf-section-label">Detected Patterns</div>
        <div class="wf-patterns-list">${items}</div>
      </div>
    `;
  },

  _renderError() {
    const container = document.getElementById('workflow-content');
    if (!container) return;

    container.innerHTML = `
      <div class="wf-container">
        <div class="wf-insight-card wf-insight-tip">
          <div class="wf-insight-title">💡 Getting Started</div>
          <div class="wf-insight-message">Use multiple AI tools to see workflow insights here.</div>
          <div class="wf-insight-detail">We'll analyze your patterns and suggest improvements.</div>
        </div>
      </div>
    `;
  },

  _shortToolName(name) {
    const names = {
      claude_code: 'Claude',
      cursor: 'Cursor',
      kiro: 'Kiro',
      copilot: 'Copilot',
      codex: 'Codex',
      aider: 'Aider',
      continue: 'Continue',
    };
    return names[name] || name;
  },

  _formatPatternName(name) {
    return name.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
  },

  _capitalize(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
  },

  _getEfficiencyColor(score) {
    if (score >= 70) return 'var(--neon-green)';
    if (score >= 40) return 'var(--neon-yellow)';
    return 'var(--neon-red)';
  },
};

document.addEventListener('DOMContentLoaded', () => {
  Workflow.init();
});
