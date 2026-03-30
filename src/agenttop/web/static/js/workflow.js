/* agenttop — Workflow Intelligence UI */

const Workflow = {
  _data: null,
  _loading: false,
  _refreshInterval: null,

  // Tool colors matching existing theme
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

  // Pattern severity colors
  patternColors: {
    tool_hopping: '#ff4444',
    quick_iteration: '#ffee00',
    iterative_refinement: '#00ff88',
    parallel_exploration: '#4488ff',
    single_tool_deep_dive: '#00fff5',
  },

  init() {
    Workflow._fetch();
    // Refresh every 60 seconds
    Workflow._refreshInterval = setInterval(Workflow._fetch, 60000);
  },

  async _fetch() {
    Workflow._loading = true;
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
    } finally {
      Workflow._loading = false;
    }
  },

  _render() {
    if (!Workflow._data) return;

    const container = document.getElementById('workflow-content');
    if (!container) return;

    container.innerHTML = `
      <div class="workflow-grid">
        ${Workflow._renderEfficiencyRing()}
        ${Workflow._renderToolFlowTimeline()}
        ${Workflow._renderPatternAlerts()}
        ${Workflow._renderRecommendations()}
        ${Workflow._renderSwitchingCostMatrix()}
      </div>
    `;

    // Animate elements after render
    setTimeout(() => {
      Workflow._animateFlows();
      Workflow._animateRing();
    }, 100);
  },

  // ══════════════════════════════════════════════════════════
  // EFFICIENCY RING
  // ══════════════════════════════════════════════════════════

  _renderEfficiencyRing() {
    const patterns = Workflow._data?.patterns?.patterns || [];
    const avgEfficiency = patterns.length > 0
      ? patterns.reduce((sum, p) => sum + p.avg_efficiency, 0) / patterns.length
      : 0.5;

    const score = Math.round(avgEfficiency * 100);
    const circumference = 2 * Math.PI * 40;
    const offset = circumference - (score / 100) * circumference;

    const color = score >= 70 ? 'var(--neon-green)' : score >= 40 ? 'var(--neon-yellow)' : 'var(--neon-red)';

    return `
      <div class="workflow-section efficiency-section">
        <div class="section-header">
          <span class="section-icon">◎</span>
          <span class="section-title">Workflow Efficiency</span>
        </div>
        <div class="efficiency-ring-container">
          <svg class="efficiency-ring" viewBox="0 0 100 100">
            <circle class="ring-bg" cx="50" cy="50" r="40" />
            <circle class="ring-progress" cx="50" cy="50" r="40"
              stroke="${color}"
              stroke-dasharray="${circumference}"
              stroke-dashoffset="${offset}"
              style="--target-offset: ${offset}" />
          </svg>
          <div class="efficiency-score" style="color: ${color}">${score}<span class="score-unit">%</span></div>
        </div>
        <div class="efficiency-label">
          ${score >= 70 ? '✓ Optimal' : score >= 40 ? '⚡ Good' : '⚠ Needs Improvement'}
        </div>
      </div>
    `;
  },

  _animateRing() {
    const ring = document.querySelector('.ring-progress');
    if (ring) {
      ring.style.transition = 'stroke-dashoffset 1s ease-out';
    }
  },

  // ══════════════════════════════════════════════════════════
  // TOOL FLOW TIMELINE
  // ══════════════════════════════════════════════════════════

  _renderToolFlowTimeline() {
    const combinations = Workflow._data?.toolCombinations?.combinations || {};
    const entries = Object.entries(combinations).slice(0, 5);

    if (entries.length === 0) {
      return `
        <div class="workflow-section flow-section">
          <div class="section-header">
            <span class="section-icon">≋</span>
            <span class="section-title">Tool Flow</span>
          </div>
          <div class="flow-empty">
            <span class="empty-icon">◇</span>
            <span>Use multiple tools to see flow patterns</span>
          </div>
        </div>
      `;
    }

    const flows = entries.map(([combo, data], i) => {
      const tools = combo.split(' → ');
      const efficiency = Math.round(data.avg_efficiency * 100);
      const width = Math.max(20, Math.min(100, data.count * 10));

      return `
        <div class="flow-stream" style="--stream-index: ${i}">
          <div class="flow-tools">
            ${tools.map(t => `
              <span class="flow-tool" style="--tool-color: ${Workflow.toolColors[t] || '#888'}">
                ${Workflow._shortToolName(t)}
              </span>
            `).join('<span class="flow-arrow">→</span>')}
          </div>
          <div class="flow-bar-container">
            <div class="flow-bar" style="width: ${width}%">
              <span class="flow-count">${data.count}x</span>
            </div>
            <span class="flow-efficiency">${efficiency}%</span>
          </div>
        </div>
      `;
    }).join('');

    return `
      <div class="workflow-section flow-section">
        <div class="section-header">
          <span class="section-icon">≋</span>
          <span class="section-title">Tool Combinations</span>
        </div>
        <div class="flow-streams">
          ${flows}
        </div>
      </div>
    `;
  },

  _shortToolName(name) {
    const shortNames = {
      claude_code: 'Claude',
      cursor: 'Cursor',
      kiro: 'Kiro',
      copilot: 'Copilot',
      codex: 'Codex',
      aider: 'Aider',
      continue: 'Continue',
    };
    return shortNames[name] || name;
  },

  _animateFlows() {
    const streams = document.querySelectorAll('.flow-stream');
    streams.forEach((stream, i) => {
      stream.style.animationDelay = `${i * 0.1}s`;
      stream.classList.add('animate-in');
    });
  },

  // ══════════════════════════════════════════════════════════
  // PATTERN ALERTS
  // ══════════════════════════════════════════════════════════

  _renderPatternAlerts() {
    const patterns = Workflow._data?.patterns?.patterns || [];

    if (patterns.length === 0) {
      return `
        <div class="workflow-section patterns-section">
          <div class="section-header">
            <span class="section-icon">◈</span>
            <span class="section-title">Patterns</span>
          </div>
          <div class="patterns-empty">No patterns detected yet</div>
        </div>
      `;
    }

    const patternItems = patterns.map(p => {
      const isBad = p.name === 'tool_hopping' || p.name === 'quick_iteration';
      const color = Workflow.patternColors[p.name] || '#888';
      const icon = isBad ? '⚠' : '✓';

      return `
        <div class="pattern-item ${isBad ? 'pattern-warning' : 'pattern-good'}">
          <span class="pattern-icon" style="color: ${color}">${icon}</span>
          <div class="pattern-info">
            <span class="pattern-name">${Workflow._formatPatternName(p.name)}</span>
            <span class="pattern-freq">${p.frequency}× detected</span>
          </div>
          <div class="pattern-efficiency" style="color: ${color}">
            ${Math.round(p.avg_efficiency * 100)}%
          </div>
        </div>
      `;
    }).join('');

    return `
      <div class="workflow-section patterns-section">
        <div class="section-header">
          <span class="section-icon">◈</span>
          <span class="section-title">Detected Patterns</span>
        </div>
        <div class="patterns-list">
          ${patternItems}
        </div>
      </div>
    `;
  },

  _formatPatternName(name) {
    return name
      .split('_')
      .map(w => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ');
  },

  // ══════════════════════════════════════════════════════════
  // RECOMMENDATIONS
  // ══════════════════════════════════════════════════════════

  _renderRecommendations() {
    const recommendations = Workflow._data?.recommendations?.recommendations || [];

    // Get the most relevant recommendation
    const topRec = recommendations.find(r => r.type === 'tool_diversity') || recommendations[0];

    if (!topRec) {
      // Show task-based recommendation
      return `
        <div class="workflow-section rec-section">
          <div class="section-header">
            <span class="section-icon">💡</span>
            <span class="section-title">Recommendation</span>
          </div>
          <div class="rec-card">
            <div class="rec-task">For Debugging</div>
            <div class="rec-tool" style="color: var(--neon-orange)">Use Claude Code</div>
            <div class="rec-gain">+35% efficiency</div>
            <div class="rec-rationale">Deep context understanding and multi-file analysis</div>
          </div>
        </div>
      `;
    }

    return `
      <div class="workflow-section rec-section">
        <div class="section-header">
          <span class="section-icon">💡</span>
          <span class="section-title">Insight</span>
        </div>
        <div class="rec-card">
          <div class="rec-issue">${topRec.issue || 'Workflow Improvement'}</div>
          <div class="rec-suggestion">${topRec.recommendation}</div>
          ${topRec.potential_benefit ? `<div class="rec-benefit">${topRec.potential_benefit}</div>` : ''}
        </div>
      </div>
    `;
  },

  // ══════════════════════════════════════════════════════════
  // SWITCHING COST MATRIX
  // ══════════════════════════════════════════════════════════

  _renderSwitchingCostMatrix() {
    const costs = Workflow._data?.switchingCosts?.switching_costs || {};
    const entries = Object.entries(costs).slice(0, 6);

    if (entries.length === 0) {
      return '';
    }

    const cells = entries.map(([transition, data]) => {
      const [from, to] = transition.split(' → ');
      const loss = Math.round((data.avg_context_preservation || 0.5) * 100);
      const lossColor = loss >= 70 ? 'var(--neon-green)' : loss >= 40 ? 'var(--neon-yellow)' : 'var(--neon-red)';

      return `
        <div class="matrix-cell" title="${data.mitigation_strategy || ''}">
          <div class="matrix-from">${Workflow._shortToolName(from)}</div>
          <div class="matrix-arrow">→</div>
          <div class="matrix-to">${Workflow._shortToolName(to)}</div>
          <div class="matrix-loss" style="color: ${lossColor}">${loss}%</div>
          <div class="matrix-freq">${data.frequency}×</div>
        </div>
      `;
    }).join('');

    return `
      <div class="workflow-section matrix-section">
        <div class="section-header">
          <span class="section-icon">⬡</span>
          <span class="section-title">Context Preservation</span>
        </div>
        <div class="matrix-grid">
          ${cells}
        </div>
      </div>
    `;
  },
};

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
  Workflow.init();
});
