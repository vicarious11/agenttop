/* agenttop — D3.js Layered Information Flow Graph v4 */

const Graph = {
  svg: null,
  simulation: null,
  container: null,
  width: 0,
  height: 0,
  _particleTimer: null,

  EDGE_STYLES: {
    token_flow:    { dash: 'none',   opacity: 0.35, particleColor: '#ff6b00' },
    message_flow:  { dash: '8,4',    opacity: 0.25, particleColor: '#00fff5' },
    model_usage:   { dash: 'none',   opacity: 0.20, particleColor: null },
    project_work:  { dash: '4,3',    opacity: 0.15, particleColor: null },
    feature_usage: { dash: '3,2',    opacity: 0.18, particleColor: '#00fff5' },
    code_gen:      { dash: '6,2,2,2', opacity: 0.22, particleColor: '#00ff88' },
  },

  _layerX(width) {
    return {
      0: width * 0.08,
      1: width * 0.30,
      2: width * 0.58,
      3: width * 0.85,
    };
  },

  render(data) {
    if (!data || !data.nodes || data.nodes.length === 0) return;

    const area = document.getElementById('graph-area');
    const rect = area.getBoundingClientRect();
    Graph.width = rect.width;
    Graph.height = rect.height;

    // Cleanup
    if (Graph._particleTimer) { clearInterval(Graph._particleTimer); Graph._particleTimer = null; }
    d3.select('#graph-svg').selectAll('*').remove();

    Graph.svg = d3.select('#graph-svg')
      .attr('width', Graph.width)
      .attr('height', Graph.height)
      .attr('viewBox', `0 0 ${Graph.width} ${Graph.height}`);

    // ── Defs ──
    const defs = Graph.svg.append('defs');

    // Glow filters
    ['glow', 'glow-strong', 'glow-soft'].forEach((id, i) => {
      const stdDev = [3, 7, 2][i];
      const f = defs.append('filter').attr('id', id)
        .attr('x', '-50%').attr('y', '-50%').attr('width', '200%').attr('height', '200%');
      f.append('feGaussianBlur').attr('stdDeviation', stdDev).attr('result', 'blur');
      const m = f.append('feMerge');
      m.append('feMergeNode').attr('in', 'blur');
      m.append('feMergeNode').attr('in', 'SourceGraphic');
    });

    // Radial gradient for center
    const cg = defs.append('radialGradient').attr('id', 'center-grad');
    cg.append('stop').attr('offset', '0%').attr('stop-color', 'rgba(255,255,255,0.15)');
    cg.append('stop').attr('offset', '100%').attr('stop-color', 'rgba(255,255,255,0)');

    // Arrow markers for directional edges
    ['#ff6b00', '#00fff5', '#00ff88', '#6644ff', '#ff9944', '#ffcc88', '#4488ff', '#ffffff', '#ffee00', '#ff00ff', '#ff4444', '#888888'].forEach(color => {
      defs.append('marker')
        .attr('id', `arrow-${color.replace('#', '')}`)
        .attr('viewBox', '0 0 10 6').attr('refX', 10).attr('refY', 3)
        .attr('markerWidth', 8).attr('markerHeight', 5)
        .attr('orient', 'auto')
        .append('path').attr('d', 'M0,0 L10,3 L0,6').attr('fill', color).attr('opacity', 0.4);
    });

    // Container for zoom/pan
    Graph.container = Graph.svg.append('g');
    Graph.svg.call(
      d3.zoom().scaleExtent([0.2, 5]).on('zoom', (e) => {
        Graph.container.attr('transform', e.transform);
      })
    );

    // ── Data prep ──
    const nodeMap = new Map(data.nodes.map(n => [n.id, { ...n }]));
    const nodes = Array.from(nodeMap.values());
    const edges = data.edges
      .filter(e => nodeMap.has(e.source) && nodeMap.has(e.target))
      .map(e => ({ ...e }));

    const maxVal = Math.max(...nodes.map(n => n.value || 1), 1);
    const logScale = (v) => Math.log2((v || 1) + 1) / Math.log2(maxVal + 1);

    const nodeRadius = (n) => {
      if (n.type === 'center') return 28;
      if (n.type === 'tool') return 14 + logScale(n.value) * 20;
      if (n.type === 'model') return 10 + logScale(n.value) * 14;
      if (n.type === 'metric') return 12 + logScale(n.value) * 10;
      if (n.type === 'feature') return 8 + logScale(n.value) * 10;
      return 6 + logScale(n.value) * 10; // project
    };

    const edgeWidth = (e) => {
      const style = Graph.EDGE_STYLES[e.edgeType] || Graph.EDGE_STYLES.token_flow;
      const base = e.edgeType === 'token_flow' ? 1.5 : 0.8;
      return base + logScale(e.value) * 3;
    };

    // ── Layered Force Simulation ──
    const layerX = Graph._layerX(Graph.width);

    Graph.simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(edges).id(d => d.id)
        .distance(d => {
          const srcLayer = typeof d.source === 'object' ? (d.source.layer || 0) : 0;
          const tgtLayer = typeof d.target === 'object' ? (d.target.layer || 0) : 0;
          const layerGap = Math.abs(srcLayer - tgtLayer);
          if (layerGap === 0) return 60;
          if (layerGap === 1) return 150;
          return 250;
        })
        .strength(0.15))
      .force('x', d3.forceX().x(d => layerX[d.layer] || Graph.width * 0.5).strength(1.2))
      .force('y', d3.forceY().y(Graph.height / 2).strength(0.04))
      .force('collide', d3.forceCollide().radius(d => nodeRadius(d) + 20))
      .velocityDecay(0.45);

    // ── Draw edges ──
    const edgeGroup = Graph.container.append('g');
    const edgePaths = edgeGroup.selectAll('path')
      .data(edges).join('path')
      .attr('class', d => `edge-path edge-${d.edgeType || 'default'}`)
      .attr('stroke', d => {
        const src = typeof d.source === 'object' ? d.source : nodeMap.get(d.source);
        return src?.color || '#333';
      })
      .attr('stroke-width', d => edgeWidth(d))
      .attr('stroke-dasharray', d => {
        const style = Graph.EDGE_STYLES[d.edgeType];
        return style ? style.dash : 'none';
      })
      .attr('stroke-opacity', d => {
        const style = Graph.EDGE_STYLES[d.edgeType];
        return style ? style.opacity : 0.2;
      })
      .attr('marker-end', d => {
        const src = typeof d.source === 'object' ? d.source : nodeMap.get(d.source);
        const color = (src?.color || '#333').replace('#', '');
        return `url(#arrow-${color})`;
      });

    // Edge labels (visible on hover)
    const edgeLabelGroup = Graph.container.append('g');
    const edgeLabels = edgeLabelGroup.selectAll('text')
      .data(edges).join('text')
      .attr('class', 'edge-label')
      .attr('text-anchor', 'middle')
      .attr('dy', -4)
      .text(d => d.label || '')
      .style('opacity', 0);

    // ── Particle layer ──
    const particleGroup = Graph.container.append('g');

    // ── Draw nodes ──
    const nodeGroup = Graph.container.append('g');
    const nodeEls = nodeGroup.selectAll('g')
      .data(nodes).join('g')
      .attr('class', d => `node node-${d.type}`)
      .style('cursor', 'pointer')
      .call(d3.drag()
        .on('start', (e, d) => {
          if (!e.active) Graph.simulation.alphaTarget(0.3).restart();
          // Pin X to layer, allow vertical drag
          d.fx = layerX[d.layer] || d.x;
          d.fy = d.y;
        })
        .on('drag', (e, d) => {
          // Only allow vertical movement, keep X pinned to layer
          d.fx = layerX[d.layer] || d.x;
          d.fy = e.y;
        })
        .on('end', (e, d) => {
          if (!e.active) Graph.simulation.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        })
      );

    nodeEls.each(function(d) {
      const g = d3.select(this);
      const r = nodeRadius(d);

      if (d.type === 'center') {
        g.append('circle').attr('r', r + 20)
          .attr('fill', 'url(#center-grad)').attr('opacity', 0.5);
        g.append('circle').attr('r', r + 8)
          .attr('fill', 'none').attr('stroke', '#fff').attr('stroke-width', 0.5)
          .attr('opacity', 0.2).attr('class', 'ring-pulse');
        g.append('circle').attr('r', r)
          .attr('fill', 'rgba(255,255,255,0.04)')
          .attr('stroke', '#fff').attr('stroke-width', 1.5)
          .attr('filter', 'url(#glow-strong)');
        g.append('text').attr('class', 'node-label node-label-center').attr('dy', 4).text(d.label);

      } else if (d.type === 'tool') {
        g.append('circle').attr('r', r + 4)
          .attr('fill', 'none').attr('stroke', d.color).attr('stroke-width', 0.5)
          .attr('opacity', d.status === 'active' ? 0.3 : 0.1)
          .attr('stroke-dasharray', d.status === 'active' ? 'none' : '2,3');
        g.append('circle').attr('r', r)
          .attr('fill', d.color + '15')
          .attr('stroke', d.color).attr('stroke-width', 1.5)
          .attr('filter', 'url(#glow)');
        g.append('text').attr('text-anchor', 'middle').attr('dy', 5)
          .attr('font-size', Math.max(10, r * 0.7))
          .attr('font-weight', '700').attr('font-family', "'SF Mono', monospace")
          .attr('fill', d.color).text(d.label[0]);
        g.append('text').attr('class', 'node-label node-label-bright').attr('dy', r + 14).text(d.label);
        // Subtitle with key metric
        const sub = d.tokens > 0 ? App.formatNum(d.tokens) + ' tok' :
                    d.messages > 0 ? App.formatNum(d.messages) + ' msg' :
                    d.sessions > 0 ? d.sessions + ' sess' : '';
        if (sub) {
          g.append('text').attr('class', 'node-label').attr('dy', r + 24)
            .attr('font-size', '8px').attr('fill', d.color).attr('opacity', 0.6).text(sub);
        }

      } else if (d.type === 'model') {
        const pts = d3.range(6).map(i => {
          const a = (i * 60 - 30) * Math.PI / 180;
          return [Math.cos(a) * r, Math.sin(a) * r];
        });
        g.append('polygon').attr('points', pts.map(p => p.join(',')).join(' '))
          .attr('fill', d.color + '12').attr('stroke', d.color).attr('stroke-width', 1.2)
          .attr('filter', 'url(#glow-soft)');
        g.append('text').attr('class', 'node-label node-label-bright').attr('dy', r + 13).text(d.label);

      } else if (d.type === 'project') {
        const s = r;
        g.append('polygon').attr('points', `0,${-s} ${s},0 0,${s} ${-s},0`)
          .attr('fill', d.color + '12').attr('stroke', d.color).attr('stroke-width', 1)
          .attr('filter', 'url(#glow-soft)');
        const lbl = d.label.length > 14 ? d.label.slice(0, 14) + '\u2026' : d.label;
        g.append('text').attr('class', 'node-label').attr('dy', r + 12).attr('font-size', '9px').text(lbl);

      } else if (d.type === 'feature') {
        // Rounded rectangle for features (Tab Complete, Composer, etc.)
        g.append('rect')
          .attr('x', -r * 1.3).attr('y', -r * 0.7)
          .attr('width', r * 2.6).attr('height', r * 1.4)
          .attr('rx', 4).attr('ry', 4)
          .attr('fill', d.color + '10').attr('stroke', d.color).attr('stroke-width', 1)
          .attr('filter', 'url(#glow-soft)');
        g.append('text').attr('class', 'node-label node-label-bright').attr('dy', 3)
          .attr('font-size', '9px').text(d.label);
        if (d.count) {
          g.append('text').attr('class', 'node-label').attr('dy', r * 0.7 + 12)
            .attr('font-size', '8px').attr('fill', d.color).attr('opacity', 0.6)
            .text(d.count.toLocaleString());
        }

      } else if (d.type === 'metric') {
        // Rounded square for metrics (AI Code ratio)
        const s = r * 0.9;
        g.append('rect')
          .attr('x', -s).attr('y', -s)
          .attr('width', s * 2).attr('height', s * 2)
          .attr('rx', 5).attr('ry', 5)
          .attr('fill', d.color + '12').attr('stroke', d.color).attr('stroke-width', 1.2)
          .attr('filter', 'url(#glow-soft)');
        g.append('text').attr('class', 'node-label node-label-bright').attr('dy', 3)
          .attr('font-size', '9px').text(d.label);
        if (d.ai_pct != null) {
          // Mini bar showing AI vs human
          const bw = s * 1.4;
          const bh = 3;
          const aiW = bw * (d.ai_pct / 100);
          g.append('rect').attr('x', -bw/2).attr('y', s + 6)
            .attr('width', bw).attr('height', bh).attr('rx', 1)
            .attr('fill', 'rgba(255,255,255,0.06)');
          g.append('rect').attr('x', -bw/2).attr('y', s + 6)
            .attr('width', aiW).attr('height', bh).attr('rx', 1)
            .attr('fill', d.color);
        }

      } else {
        g.append('circle').attr('r', r)
          .attr('fill', d.color + '15').attr('stroke', d.color).attr('stroke-width', 1);
        g.append('text').attr('class', 'node-label').attr('dy', r + 12).text(d.label);
      }
    });

    // ── Interactions ──
    const tooltip = document.getElementById('tooltip');

    nodeEls.on('click', (event, d) => {
      event.stopPropagation();
      App.showNodeDetail(d);
      edgePaths.each(function(e) {
        const sid = typeof e.source === 'object' ? e.source.id : e.source;
        const tid = typeof e.target === 'object' ? e.target.id : e.target;
        const connected = sid === d.id || tid === d.id;
        d3.select(this)
          .classed('highlighted', connected)
          .classed('dimmed', !connected);
      });
      edgeLabels.each(function(e) {
        const sid = typeof e.source === 'object' ? e.source.id : e.source;
        const tid = typeof e.target === 'object' ? e.target.id : e.target;
        d3.select(this).style('opacity', (sid === d.id || tid === d.id) ? 0.7 : 0);
      });
    });

    Graph.svg.on('click', () => {
      edgePaths.classed('highlighted', false).classed('dimmed', false);
      edgeLabels.style('opacity', 0);
    });

    nodeEls.on('mouseenter', (event, d) => {
      let html = `<div class="tooltip-title" style="color:${d.color}">
        <span>${d.label}</span>
      </div>`;
      html += `<div class="tooltip-row"><span>Type</span><span class="val">${d.type}</span></div>`;
      if (d.value) html += `<div class="tooltip-row"><span>Activity</span><span class="val">${App.formatNum(d.value)}</span></div>`;
      if (d.tokens > 0) html += `<div class="tooltip-row"><span>Tokens</span><span class="val">${App.formatNum(d.tokens)}</span></div>`;
      if (d.messages > 0) html += `<div class="tooltip-row"><span>Messages</span><span class="val">${App.formatNum(d.messages)}</span></div>`;
      if (d.sessions > 0) html += `<div class="tooltip-row"><span>Sessions</span><span class="val">${d.sessions}</span></div>`;
      if (d.cost) html += `<div class="tooltip-row"><span>Cost</span><span class="val">${App.formatCost(d.cost)}</span></div>`;
      if (d.uses) html += `<div class="tooltip-row"><span>Uses</span><span class="val">${d.uses.toLocaleString()}</span></div>`;
      if (d.count) html += `<div class="tooltip-row"><span>Count</span><span class="val">${d.count.toLocaleString()}</span></div>`;
      if (d.ai_lines != null) {
        html += `<div class="tooltip-row"><span>AI Lines</span><span class="val">${d.ai_lines.toLocaleString()}</span></div>`;
        html += `<div class="tooltip-row"><span>Human Lines</span><span class="val">${d.human_lines.toLocaleString()}</span></div>`;
      }
      if (d.cacheRead && d.inputTokens) {
        const rate = ((d.cacheRead / (d.cacheRead + d.inputTokens)) * 100).toFixed(1);
        html += `<div class="tooltip-row"><span>Cache Hit</span><span class="val">${rate}%</span></div>`;
      }
      tooltip.innerHTML = html;
      tooltip.classList.add('visible');
    });

    nodeEls.on('mousemove', (event) => {
      tooltip.style.left = (event.clientX + 12) + 'px';
      tooltip.style.top = (event.clientY - 12) + 'px';
    });

    nodeEls.on('mouseleave', () => tooltip.classList.remove('visible'));

    // ── Tick — S-curve Bezier edges ──
    Graph.simulation.on('tick', () => {
      edgePaths.attr('d', d => {
        const sx = d.source.x, sy = d.source.y, tx = d.target.x, ty = d.target.y;
        const midX = (sx + tx) / 2;
        return `M${sx},${sy} C${midX},${sy} ${midX},${ty} ${tx},${ty}`;
      });
      edgeLabels
        .attr('x', d => (d.source.x + d.target.x) / 2)
        .attr('y', d => (d.source.y + d.target.y) / 2);
      nodeEls.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    // ── Particles ──
    Graph._startParticles(edges, particleGroup);

    // ── Legend ──
    Graph._renderLegend();
  },

  _startParticles(edges, group) {
    // Only animate particles on significant edges
    const particleEdges = edges.filter(e => {
      const style = Graph.EDGE_STYLES[e.edgeType];
      return style && style.particleColor;
    });
    if (!particleEdges.length) return;

    const totalVal = particleEdges.reduce((s, e) => s + (e.value || 1), 0);

    const spawn = () => {
      let r = Math.random() * totalVal;
      let edge = particleEdges[0];
      for (const e of particleEdges) { r -= (e.value || 1); if (r <= 0) { edge = e; break; } }

      const src = edge.source, tgt = edge.target;
      if (!src?.x || !tgt?.x) return;

      const style = Graph.EDGE_STYLES[edge.edgeType] || {};
      const color = style.particleColor || src.color || '#00fff5';
      const p = group.append('circle')
        .attr('class', 'particle')
        .attr('r', 1.5 + Math.random())
        .attr('fill', color)
        .attr('filter', 'url(#glow-soft)')
        .attr('cx', src.x).attr('cy', src.y)
        .attr('opacity', 0.7);

      // Follow the S-curve Bezier path (cubic)
      const midX = (src.x + tgt.x) / 2;
      const dur = 1200 + Math.random() * 800;

      const timer = d3.timer((elapsed) => {
        const t = Math.min(elapsed / dur, 1);
        const q = 1 - t;
        // Cubic Bezier: P0=src, P1=(midX,src.y), P2=(midX,tgt.y), P3=tgt
        const x = q*q*q*src.x + 3*q*q*t*midX + 3*q*t*t*midX + t*t*t*tgt.x;
        const y = q*q*q*src.y + 3*q*q*t*src.y + 3*q*t*t*tgt.y + t*t*t*tgt.y;
        p.attr('cx', x).attr('cy', y).attr('opacity', 0.7 * (1 - t * 0.6));
        if (t >= 1) { p.remove(); timer.stop(); }
      });
    };

    Graph._particleTimer = setInterval(spawn, 180);
  },

  _renderLegend() {
    document.getElementById('graph-legend').innerHTML = `
      <div class="legend-item"><span class="legend-shape legend-circle" style="background:rgba(255,255,255,0.6);border-color:rgba(255,255,255,0.6)"></span>You</div>
      <div class="legend-item"><span class="legend-shape legend-circle" style="background:rgba(255,107,0,0.3);border-color:#ff6b00"></span>Tool</div>
      <div class="legend-item"><span class="legend-shape legend-hex" style="background:rgba(255,153,68,0.3);border-color:#ff9944"></span>Model</div>
      <div class="legend-item"><span class="legend-shape legend-diamond" style="background:rgba(102,68,255,0.3);border-color:#6644ff"></span>Project</div>
      <div class="legend-item"><span class="legend-shape legend-rect" style="background:rgba(0,255,245,0.3);border-color:#00fff5"></span>Feature</div>
      <div class="legend-item"><span class="legend-shape legend-rect" style="background:rgba(0,255,136,0.3);border-color:#00ff88"></span>Metric</div>
    `;
  },

  resize() {
    const area = document.getElementById('graph-area');
    if (!area) return;
    const rect = area.getBoundingClientRect();
    Graph.width = rect.width;
    Graph.height = rect.height;
    if (Graph.svg) {
      Graph.svg.attr('width', Graph.width).attr('height', Graph.height)
        .attr('viewBox', `0 0 ${Graph.width} ${Graph.height}`);
    }
    if (Graph.simulation) {
      const layerX = Graph._layerX(Graph.width);
      Graph.simulation.force('x', d3.forceX().x(d => layerX[d.layer] || Graph.width * 0.5).strength(0.8));
      Graph.simulation.force('y', d3.forceY().y(Graph.height / 2).strength(0.05));
      Graph.simulation.alpha(0.3).restart();
    }
  }
};

window.addEventListener('resize', () => Graph.resize());
