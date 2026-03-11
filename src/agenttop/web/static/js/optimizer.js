/* agenttop — AI Usage Optimizer UI */

const Optimizer = {
  _expanded: false,
  _fullscreen: false,
  _cached: null,
  _loading: false,

  init() {
    const drawer = document.getElementById('optimizer-drawer');
    const handle = document.getElementById('drawer-toggle');
    const fsBtn = document.getElementById('drawer-fullscreen');
    const chevron = document.getElementById('drawer-chevron');

    drawer.classList.add('collapsed');

    // Pre-fetch analysis in background
    Optimizer._prefetch();

    // Toggle drawer on handle click (but not fullscreen button)
    handle.addEventListener('click', (e) => {
      if (e.target.closest('#drawer-fullscreen')) return;
      Optimizer._toggle();
    });

    // Fullscreen button
    fsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!Optimizer._expanded) {
        Optimizer._expand();
      }
      Optimizer._fullscreen = !Optimizer._fullscreen;
      drawer.classList.toggle('fullscreen', Optimizer._fullscreen);
    });

    // Escape: exit fullscreen first, then close drawer
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (Optimizer._fullscreen) {
          Optimizer._fullscreen = false;
          drawer.classList.remove('fullscreen');
          e.stopPropagation();
        } else if (Optimizer._expanded) {
          Optimizer._collapse();
        }
      }
    });
  },

  _toggle() {
    if (Optimizer._expanded) {
      Optimizer._collapse();
    } else {
      Optimizer._expand();
    }
  },

  _expand() {
    const drawer = document.getElementById('optimizer-drawer');
    Optimizer._expanded = true;
    drawer.classList.remove('collapsed');
    Optimizer._renderContent();
  },

  _collapse() {
    const drawer = document.getElementById('optimizer-drawer');
    Optimizer._expanded = false;
    Optimizer._fullscreen = false;
    drawer.classList.add('collapsed');
    drawer.classList.remove('fullscreen');
  },

  _renderContent() {
    if (Optimizer._loading) {
      Optimizer._renderLoading();
    } else if (Optimizer._cached) {
      Optimizer._renderResults(Optimizer._cached);
    } else {
      Optimizer._renderInitial();
    }
  },

  async _prefetch() {
    Optimizer._loading = true;
    Optimizer._updateHandle();
    try {
      const res = await fetch('/api/optimize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days: 0 }),
      });
      if (!res.ok) {
        Optimizer._loading = false;
        Optimizer._updateHandle();
        return;
      }
      const data = await res.json();
      if (!data.error || data.source === 'partial') {
        Optimizer._cached = data;
        try { sessionStorage.setItem('agenttop-optimizer', JSON.stringify(data)); } catch(e) { console.warn('Failed to cache optimizer results:', e); }
      }
    } catch(e) {
      // silent — user can still click Analyze
    }
    Optimizer._loading = false;
    Optimizer._updateHandle();
    // If drawer is open, refresh content
    if (Optimizer._expanded) Optimizer._renderContent();
  },

  _updateHandle() {
    const title = document.querySelector('.drawer-title');
    if (!title) return;
    if (Optimizer._loading) {
      title.textContent = 'AI Usage Optimizer (analyzing...)';
    } else if (Optimizer._cached) {
      const score = Optimizer._cached.score;
      if (score != null && score > 0) {
        title.textContent = `AI Usage Optimizer — Score: ${score}/100`;
      } else {
        title.textContent = 'AI Usage Optimizer';
      }
    } else {
      title.textContent = 'AI Usage Optimizer';
    }
  },

  _renderLoading() {
    const content = document.getElementById('optimizer-content');
    content.innerHTML = `<div class="loading-pulse">Building usage profile & analyzing patterns...</div>`;
  },

  _renderInitial() {
    const content = document.getElementById('optimizer-content');
    content.innerHTML = `
      <div class="optimizer-trigger">
        <p style="color:var(--text-secondary);margin-bottom:16px;">
          Analyzes your real usage data across all AI tools, cross-references
          against current best practices, and identifies what you're missing.
        </p>
        <button class="neon-btn" id="analyze-btn" onclick="Optimizer.analyze()">
          Analyze My Workflow
        </button>
      </div>
    `;
  },

  async analyze() {
    const content = document.getElementById('optimizer-content');
    const btn = document.getElementById('analyze-btn');
    if (btn) btn.disabled = true;

    Optimizer._loading = true;
    Optimizer._updateHandle();
    content.innerHTML = `<div class="loading-pulse">Building usage profile & analyzing patterns...</div>`;

    try {
      const res = await fetch('/api/optimize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days: typeof App !== 'undefined' ? App.days : 0 }),
      });

      // Handle non-JSON responses (e.g. server 500)
      const text = await res.text();
      let data;
      try {
        data = JSON.parse(text);
      } catch (parseErr) {
        Optimizer._loading = false;
        Optimizer._updateHandle();
        content.innerHTML = `
          <div style="text-align:center;padding:24px;color:var(--neon-red);">
            Server returned an error. Check your LLM provider is running and configured.
            <br><br>
            <pre style="text-align:left;background:var(--bg-card);padding:12px;border-radius:6px;font-size:11px;color:var(--text-secondary);max-width:500px;margin:0 auto;white-space:pre-wrap;overflow:auto;max-height:200px;">${text.slice(0, 500)}</pre>
            <br>
            <button class="neon-btn" onclick="Optimizer.analyze()">Retry</button>
          </div>
        `;
        return;
      }

      Optimizer._loading = false;
      Optimizer._updateHandle();

      if (data.source === 'error' && !data.anti_patterns) {
        // Full error — no usable data at all
        content.innerHTML = `
          <div style="text-align:center;padding:40px 24px;">
            <div style="font-size:48px;margin-bottom:16px;">\uD83D\uDD0C</div>
            <h3 style="color:var(--neon-yellow);margin-bottom:12px;">${data.error || 'LLM not available'}</h3>
            ${data.setup_hint ? `<pre style="text-align:left;background:var(--bg-card);padding:16px;border-radius:8px;margin:16px auto;max-width:500px;color:var(--text-secondary);white-space:pre-wrap;">${data.setup_hint}</pre>` : ''}
            <button class="neon-btn" onclick="Optimizer.analyze()" style="margin-top:16px;">Retry</button>
          </div>
        `;
        return;
      }

      // Success or partial (has Python metrics even if LLM failed)
      Optimizer._cached = data;
      try { sessionStorage.setItem('agenttop-optimizer', JSON.stringify(data)); } catch(e) { console.warn('Failed to cache optimizer results:', e); }
      Optimizer._renderResults(data);
    } catch (err) {
      Optimizer._loading = false;
      Optimizer._updateHandle();
      content.innerHTML = `
        <div style="text-align:center;padding:24px;color:var(--neon-red);">
          Network error: ${err.message}
          <br><br>
          <button class="neon-btn" onclick="Optimizer.analyze()">Retry</button>
        </div>
      `;
    }
  },

  _renderResults(data) {
    const content = document.getElementById('optimizer-content');
    const formatNum = (n) => {
      if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
      if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
      return n.toLocaleString();
    };
    let html = '<div class="animate-in">';

    // Partial warning banner (LLM failed but Python metrics available)
    if (data.source === 'partial') {
      html += `
        <div style="padding:10px 14px;border-radius:6px;background:rgba(255,238,0,0.06);border:1px solid rgba(255,238,0,0.2);margin-bottom:16px;font-size:11px;color:var(--neon-yellow);">
          LLM unavailable — showing data-driven metrics only. ${data.error || ''}
          <button class="neon-btn" onclick="Optimizer.analyze()" style="margin-left:12px;padding:4px 12px;font-size:10px;">Retry</button>
        </div>
      `;
    }

    // Score circle
    const score = data.score || 0;
    const circumference = 2 * Math.PI * 42;
    const offset = circumference - (score / 100) * circumference;
    const scoreColor = score >= 80 ? 'var(--neon-green)' :
                       score >= 60 ? 'var(--neon-cyan)' :
                       score >= 40 ? 'var(--neon-yellow)' : 'var(--neon-red)';

    const sourceLabel = data.source === 'llm' ? 'AI-Powered Analysis' :
                        data.source === 'partial' ? 'Data-Driven Metrics' : 'Analysis';

    html += `
      <div class="score-container">
        <div class="score-circle">
          <svg viewBox="0 0 100 100">
            <circle class="bg" cx="50" cy="50" r="42" />
            <circle class="progress" cx="50" cy="50" r="42"
              stroke="${scoreColor}"
              stroke-dasharray="${circumference}"
              stroke-dashoffset="${offset}" />
          </svg>
          <div class="score-number" style="color:${scoreColor}">${score}</div>
        </div>
        <div>
          <div style="font-size:20px;font-weight:700;margin-bottom:4px;">
            ${score >= 80 ? 'Excellent' : score >= 60 ? 'Good' : score >= 40 ? 'Needs Work' : 'Poor'} Usage
          </div>
          <div class="score-label">${sourceLabel}</div>
    `;

    // Profile summary mini-stats
    const ps = data.profile_summary;
    if (ps) {
      html += `<div style="display:flex;gap:16px;margin-top:8px;font-size:11px;color:var(--text-secondary);">
        <span>${formatNum(ps.total_tokens)} tokens</span>
        <span>$${(ps.total_cost || 0).toFixed(2)} cost</span>
        <span>${ps.session_count} sessions</span>
        <span>${ps.active_tools} tools</span>
        ${ps.cache_hit_rate ? `<span>${ps.cache_hit_rate}% cache</span>` : ''}
      </div>`;
    }

    html += `</div></div>`;

    // Developer profile / bio
    const dp = data.developer_profile;
    if (dp && dp.title) {
      const personalityIcons = {
        'power_user': '\u26A1', 'debug_warrior': '\uD83D\uDEE1\uFE0F',
        'explorer': '\uD83E\uDDED', 'methodical_builder': '\uD83C\uDFD7\uFE0F',
        'cautious_adopter': '\uD83C\uDFAF', 'efficiency_optimizer': '\u2699\uFE0F',
      };
      const icon = personalityIcons[dp.ai_personality] || '\uD83D\uDC64';
      html += `
        <div class="dev-profile-section">
          <div class="dev-profile-header">
            <span class="dev-profile-icon">${icon}</span>
            <span class="dev-profile-title">${dp.title}</span>
          </div>
          <p class="dev-profile-bio">${dp.bio}</p>
          ${dp.traits && dp.traits.length > 0 ? `
            <div class="dev-profile-traits">
              ${dp.traits.map(t => `<span class="trait-chip">${t}</span>`).join('')}
            </div>
          ` : ''}
        </div>
      `;
    }

    // Context engineering card
    const ce = data.context_engineering;
    if (ce && ce.total_messages > 0) {
      const bloatColor = ce.bloated_pct > 30 ? 'var(--neon-red)' : ce.bloated_pct > 10 ? 'var(--neon-yellow)' : 'var(--neon-green)';
      const cpmColor = ce.cost_per_message > 0.05 ? 'var(--neon-red)' : ce.cost_per_message > 0.01 ? 'var(--neon-yellow)' : 'var(--neon-green)';
      html += `
        <div class="context-eng-section">
          <h3>Context Engineering</h3>
          <div class="ce-grid">
            <div class="ce-stat">
              <div class="ce-value">${formatNum(ce.avg_tokens_per_message)}</div>
              <div class="ce-label">Tokens / Message</div>
            </div>
            <div class="ce-stat">
              <div class="ce-value">${ce.avg_tool_calls_per_session}</div>
              <div class="ce-label">Tool Calls / Session</div>
            </div>
            <div class="ce-stat">
              <div class="ce-value" style="color:${bloatColor}">${ce.bloated_sessions} <small>(${ce.bloated_pct}%)</small></div>
              <div class="ce-label">Bloated Sessions (&gt;50 msgs)</div>
            </div>
            <div class="ce-stat">
              <div class="ce-value" style="color:${cpmColor}">$${ce.cost_per_message.toFixed(4)}</div>
              <div class="ce-label">Cost / Message</div>
            </div>
          </div>
        </div>
      `;
    }

    // Anti-patterns section
    const aps = data.anti_patterns;
    if (aps && aps.length > 0) {
      html += '<div class="anti-patterns-section"><h3>Detected Anti-Patterns</h3>';
      aps.forEach(ap => {
        const sev = (ap.severity || 'medium').toLowerCase();
        html += `
          <div class="ap-card ${sev}">
            <div class="ap-header">
              <span class="ap-icon">${ap.icon || '\u26A0\uFE0F'}</span>
              <span class="ap-name">${ap.pattern}</span>
              <span class="ap-severity ${sev}">${sev}</span>
              <span class="ap-count">${ap.count}x</span>
            </div>
            <div class="ap-detail">${ap.detail}</div>
            <div class="ap-fix">${ap.fix}</div>
            ${ap.examples && ap.examples.length > 0 ? `
              <div class="ap-examples">
                ${ap.examples.map(e => `<div class="ap-example">${e}</div>`).join('')}
              </div>
            ` : ''}
          </div>
        `;
      });
      html += '</div>';
    }

    // Session deep-dive
    const sd = data.session_details;
    if (sd && sd.length > 0) {
      html += '<div class="session-deep-section"><h3>Top Sessions (by token usage)</h3>';
      const intentIcons = {
        'debugging': '\uD83D\uDC1B', 'greenfield': '\uD83C\uDFD7\uFE0F', 'refactoring': '\u267B\uFE0F',
        'exploration': '\uD83D\uDD0D', 'devops': '\u2699\uFE0F', 'documentation': '\uD83D\uDCDD',
        'code_review': '\uD83D\uDC41\uFE0F', 'other': '\uD83D\uDCE6',
      };
      sd.slice(0, 8).forEach(s => {
        const icon = intentIcons[s.intent] || '\uD83D\uDCE6';
        const msgClass = s.messages > 50 ? 'warn' : s.messages > 20 ? 'mid' : 'ok';
        html += `
          <div class="sd-card" onclick="this.classList.toggle('expanded')">
            <div class="sd-header">
              <span class="sd-icon">${icon}</span>
              <span class="sd-project">${s.project}</span>
              <span class="sd-intent">${s.intent}</span>
              <span class="sd-tool">${s.tool}</span>
            </div>
            <div class="sd-metrics">
              <span class="sd-metric ${msgClass}">${s.messages} msgs</span>
              <span class="sd-metric">${formatNum(s.tokens)} tok</span>
              <span class="sd-metric">$${s.cost.toFixed(2)}</span>
              <span class="sd-metric">${s.context_ratio}x ctx</span>
            </div>
            ${s.first_prompt ? `<div class="sd-prompt">"${s.first_prompt}"</div>` : ''}
          </div>
        `;
      });
      html += '</div>';
    }

    // Cost forensics section
    const cf = data.cost_forensics;
    if (cf && cf.total_cost > 0) {
      const wasteColor = cf.waste_pct > 15 ? 'var(--neon-red)' : cf.waste_pct > 5 ? 'var(--neon-yellow)' : 'var(--neon-green)';
      html += `
        <div class="cost-forensics-section">
          <h3>Cost Forensics</h3>
          <div class="cf-summary">
            <div class="cf-stat">
              <div class="cf-value">$${cf.total_cost.toFixed(2)}</div>
              <div class="cf-label">Total Spend</div>
            </div>
            <div class="cf-stat">
              <div class="cf-value" style="color:${wasteColor}">$${cf.estimated_waste.toFixed(2)}</div>
              <div class="cf-label">Estimated Waste</div>
            </div>
            <div class="cf-stat">
              <div class="cf-value" style="color:${wasteColor}">${cf.waste_pct}%</div>
              <div class="cf-label">Waste Rate</div>
            </div>
          </div>
      `;
      const cbp = cf.cost_by_project || [];
      if (cbp.length > 0) {
        const maxCost = cbp[0].cost || 1;
        html += '<div class="cf-projects">';
        cbp.slice(0, 6).forEach(p => {
          const pct = Math.round((p.cost / maxCost) * 100);
          html += `
            <div class="cf-bar-row">
              <span class="cf-bar-label">${p.project}</span>
              <div class="cf-bar-track"><div class="cf-bar-fill" style="width:${pct}%"></div></div>
              <span class="cf-bar-value">$${p.cost.toFixed(2)}</span>
            </div>
          `;
        });
        html += '</div>';
      }
      const cbm = cf.cost_by_model || [];
      if (cbm.length > 0) {
        html += '<div class="cf-models">';
        cbm.forEach(m => {
          html += `
            <div class="cf-model-row">
              <span class="cf-model-name">${m.model}</span>
              <span class="cf-model-cost">$${m.cost.toFixed(2)}</span>
              <span class="cf-model-tokens">${formatNum(m.tokens)} tok</span>
            </div>
          `;
        });
        html += '</div>';
      }
      if (cf.estimated_waste > 1) {
        html += `<div class="cf-saving">Reducing marathon sessions could save ~$${cf.estimated_waste.toFixed(2)}/period</div>`;
      }
      html += '</div>';
    }

    // Prompt intelligence section
    const pa = data.prompt_analysis;
    if (pa && pa.prompt_length_distribution) {
      const pld = pa.prompt_length_distribution;
      const total = (pld.commands_under_20 || 0) + (pld.short_20_100 || 0) + (pld.detailed_100_500 || 0) + (pld.very_detailed_500_plus || 0);
      const specColor = pa.specificity_score >= 60 ? 'var(--neon-green)' : pa.specificity_score >= 30 ? 'var(--neon-yellow)' : 'var(--neon-red)';
      html += `
        <div class="prompt-analysis-section">
          <h3>Prompt Intelligence</h3>
          <div class="pa-grid">
            <div class="pa-stat">
              <div class="pa-value" style="color:${specColor}">${pa.specificity_score}%</div>
              <div class="pa-label">Specificity Score</div>
            </div>
            <div class="pa-stat">
              <div class="pa-value">${pld.avg_length}</div>
              <div class="pa-label">Avg Length (chars)</div>
            </div>
            <div class="pa-stat">
              <div class="pa-value">${pld.detailed_100_500 + pld.very_detailed_500_plus}</div>
              <div class="pa-label">Detailed Prompts</div>
            </div>
          </div>
      `;
      if (total > 0) {
        const cmdPct = (pld.commands_under_20 / total * 100).toFixed(1);
        const shortPct = (pld.short_20_100 / total * 100).toFixed(1);
        const detPct = (pld.detailed_100_500 / total * 100).toFixed(1);
        const richPct = (pld.very_detailed_500_plus / total * 100).toFixed(1);
        html += `
          <div class="pa-bar">
            <div class="pa-segment cmd" style="width:${cmdPct}%" title="Commands: ${pld.commands_under_20}"></div>
            <div class="pa-segment short" style="width:${shortPct}%" title="Short: ${pld.short_20_100}"></div>
            <div class="pa-segment detailed" style="width:${detPct}%" title="Detailed: ${pld.detailed_100_500}"></div>
            <div class="pa-segment rich" style="width:${richPct}%" title="Rich: ${pld.very_detailed_500_plus}"></div>
          </div>
          <div class="pa-legend">
            <span class="pa-legend-item"><span class="pa-dot cmd"></span> Commands (&lt;20)</span>
            <span class="pa-legend-item"><span class="pa-dot short"></span> Short (20-100)</span>
            <span class="pa-legend-item"><span class="pa-dot detailed"></span> Detailed (100-500)</span>
            <span class="pa-legend-item"><span class="pa-dot rich"></span> Rich (500+)</span>
          </div>
        `;
      }
      const sc = pa.slash_commands || {};
      const scKeys = Object.keys(sc);
      if (scKeys.length > 0) {
        html += '<div class="pa-commands">';
        scKeys.forEach(cmd => {
          html += `<span class="pa-command">${cmd} <small>${sc[cmd]}x</small></span>`;
        });
        html += '</div>';
      }
      html += '</div>';
    }

    // Grade cards
    if (data.grades && Object.keys(data.grades).length > 0) {
      html += '<div class="grades-grid">';
      const gradeNames = {
        cache_efficiency: 'Cache Efficiency',
        session_hygiene: 'Session Hygiene',
        model_selection: 'Model Selection',
        prompt_quality: 'Prompt Quality',
        tool_utilization: 'Tool Utilization',
      };
      for (const [key, info] of Object.entries(data.grades)) {
        const grade = info.grade || 'B';
        const gradeClass = ['A','B','C','D'].includes(grade) ? `grade-${grade}` : '';
        html += `
          <div class="grade-card ${gradeClass}">
            <div class="grade-letter">${grade}</div>
            <div class="grade-name">${gradeNames[key] || key}</div>
            <div class="grade-detail">${info.detail || ''}</div>
          </div>
        `;
      }
      html += '</div>';
    }

    // Recommendations
    if (data.recommendations && data.recommendations.length > 0) {
      html += '<div class="recommendations-section"><h3>Recommendations</h3>';
      data.recommendations.forEach(rec => {
        const priority = (rec.priority || 'medium').toLowerCase();
        html += `
          <div class="rec-card">
            <span class="rec-priority ${priority}">${priority}</span>
            <div class="rec-body">
              <h4>${rec.title}</h4>
              <p>${rec.description}</p>
              ${rec.savings ? `<div class="rec-savings">${rec.savings}</div>` : ''}
            </div>
          </div>
        `;
      });
      html += '</div>';
    }

    // Missing features
    if (data.missing_features && data.missing_features.length > 0) {
      html += '<div class="missing-section"><h3>Features You\'re Not Using</h3>';
      data.missing_features.forEach(f => {
        html += `
          <div class="missing-card">
            <div>
              <span class="tool-tag">${f.tool}</span>
              <span class="feature-name">${f.feature}</span>
            </div>
            ${f.evidence ? `<div class="feature-evidence">${f.evidence}</div>` : ''}
            <div class="feature-benefit">${f.benefit}</div>
          </div>
        `;
      });
      html += '</div>';
    }

    // Project insights
    if (data.project_insights && data.project_insights.length > 0) {
      html += '<div class="project-insights-section"><h3>Project Intelligence</h3>';
      data.project_insights.forEach(pi => {
        const typeBadges = {
          'greenfield': '\uD83C\uDFD7\uFE0F', 'debugging': '\uD83D\uDC1B', 'refactoring': '\u267B\uFE0F',
          'exploration': '\uD83D\uDD0D', 'devops': '\u2699\uFE0F', 'documentation': '\uD83D\uDCDD',
          'code_review': '\uD83D\uDC41\uFE0F', 'other': '\uD83D\uDCE6', 'general': '\uD83D\uDCE6',
        };
        const badge = typeBadges[pi.type] || '\uD83D\uDCE6';
        html += `
          <div class="project-insight-card">
            <div class="pi-header">
              <span class="pi-type">${badge}</span>
              <span class="pi-name">${pi.project}</span>
              <span class="pi-type-label">${pi.type}</span>
            </div>
            <div class="pi-stats">${pi.insight}</div>
            <div class="pi-rec">${pi.recommendation}</div>
            ${pi.recommended_model ? `<div class="pi-model-rec"><span class="pi-model-label">Recommended model:</span> <strong>${pi.recommended_model.model}</strong> — ${pi.recommended_model.reason}</div>` : ''}
            ${pi.underutilized && pi.underutilized !== 'None detected' ? `<div class="pi-underutil">Underutilized: ${pi.underutilized}</div>` : ''}
          </div>
        `;
      });
      html += '</div>';
    }

    // Workflow vision
    if (data.workflow && data.workflow.current) {
      html += `<div class="workflow-section">
        <h3>Workflow Assessment</h3>
        <div class="workflow-grid">
          <div class="workflow-col current">
            <div class="wf-label">Current Workflow</div>
            <p>${data.workflow.current}</p>
          </div>
          <div class="workflow-col future">
            <div class="wf-label">Optimized Workflow</div>
            <p>${data.workflow.future}</p>
          </div>
        </div>
      </div>`;
    }

    // Sources from recommendations
    const sources = (data.recommendations || [])
      .filter(r => r.source)
      .map(r => r.source)
      .filter((v, i, a) => a.indexOf(v) === i);
    if (sources.length > 0) {
      html += '<div class="sources-section"><h3>Sources & References</h3><ul>';
      sources.forEach(s => {
        const urlMatch = s.match(/(https?:\/\/[^\s]+)/);
        if (urlMatch) {
          const label = s.replace(urlMatch[0], '').replace(/\s*[—-]\s*$/, '').trim();
          html += `<li><a href="${urlMatch[0]}" target="_blank" rel="noopener">${label || urlMatch[0]}</a></li>`;
        } else {
          html += `<li>${s}</li>`;
        }
      });
      html += '</ul></div>';
    }

    // No recommendations = good!
    if ((!data.recommendations || data.recommendations.length === 0) &&
        (!data.missing_features || data.missing_features.length === 0) &&
        (!data.anti_patterns || data.anti_patterns.length === 0)) {
      html += `<div style="text-align:center;padding:24px;color:var(--neon-green);">
        No issues detected — you're using your tools well!
      </div>`;
    }

    html += `
      <div style="text-align:center;margin-top:20px;">
        <button class="neon-btn" onclick="Optimizer.analyze()">Re-analyze</button>
      </div>
    `;

    html += '</div>';
    content.innerHTML = html;
  }
};

document.addEventListener('DOMContentLoaded', () => {
  Optimizer.init();
  // Restore cached results from sessionStorage
  try {
    const cached = sessionStorage.getItem('agenttop-optimizer');
    if (cached) {
      Optimizer._cached = JSON.parse(cached);
      Optimizer._updateHandle();
    }
  } catch(e) { console.warn('Failed to restore cached optimizer results:', e); }
});
