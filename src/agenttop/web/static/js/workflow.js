/* agenttop — Workflow Intelligence UI (Redesigned) */

const Workflow = {
  _data: null,
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

      Workflow._data = { patterns, recommendations, switchingCosts, toolCombinations };
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

    container.innerHTML = `
      <div class="wf-container">
        <!-- Top: Key Insight Card -->
        ${Workflow._renderInsightCard()}

        <!-- Middle: Quick Stats Row -->
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
            <div class="wf-stat-label">Tools Used</div>
          </div>
        </div>

        <!-- Tool Usage Bars -->
        ${Workflow._renderToolUsage(toolDist)}

        <!-- Patterns (if any interesting ones) -->
        ${Workflow._renderPatternsSection()}
      </div>
    `;
  },

  _renderInsightCard() {
    const recommendations = Workflow._data?.recommendations?.recommendations || [];
    const patterns = Workflow._data?.patterns?.patterns || [];

    // Find the most actionable insight
    let insight = null;
    let insightType = 'tip';

    // Check for tool diversity issues
    const toolRec = recommendations.find(r => r.type === 'tool_diversity');
    if (toolRec) {
      insight = {
        title: '💡 Tip',
        message: toolRec.recommendation,
        detail: toolRec.potential_benefit || ''
      };
      insightType = 'warning';
    }

    // Check for bad patterns
    const badPattern = patterns.find(p => p.name === 'tool_hopping');
    if (badPattern) {
      insight = {
        title: '⚠️ Tool Hopping Detected',
        message: 'You switched between tools frequently. This can fragment context.',
        detail: 'Try sticking with one tool per task for better focus.'
      };
      insightType = 'warning';
    }

    // If everything is good, show a positive message
    if (!insight) {
      const efficiency = Math.round(((Workflow._data?.patterns?.metrics?.avg_efficiency_score || 0.5) * 100));
      if (efficiency >= 70) {
        insight = {
          title: '✅ Great Workflow',
          message: 'Your tool usage is efficient. Keep it up!',
          detail: ''
        };
        insightType = 'success';
      } else {
        insight = {
          title: '💡 Recommendation',
          message: 'For debugging tasks, try using Claude Code for +35% efficiency.',
          detail: 'It excels at deep context understanding and multi-file analysis.'
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

    // Only show interesting patterns (not just single_tool_deep_dive)
    const interestingPatterns = patterns.filter(p =>
      p.name !== 'single_tool_deep_dive' ||
      patterns.length === 1
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

  _getEfficiencyColor(score) {
    if (score >= 70) return 'var(--neon-green)';
    if (score >= 40) return 'var(--neon-yellow)';
    return 'var(--neon-red)';
  },
};

document.addEventListener('DOMContentLoaded', () => {
  Workflow.init();
});
