# Session Explorer + UX Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the generic neon cyberpunk UI with a crafted dark theme, add an interactive session explorer with drill-down and multi-select LLM analysis, and remove the 10-session optimizer cap.

**Architecture:** New CSS design system replaces neon.css. Session explorer becomes the main interactive panel with list/detail split view. New `/api/sessions/{id}` and `/api/analyze-sessions` endpoints enable selective analysis. Optimizer drawer moves to a right-side slide panel.

**Tech Stack:** Python 3.10+, FastAPI, vanilla JS, D3.js, CSS custom properties

---

### Task 1: New CSS Design System (theme.css)

**Files:**
- Create: `src/agenttop/web/static/css/theme.css`
- Modify: `src/agenttop/web/static/index.html:8` (swap stylesheet link)

This replaces the entire neon.css. The new design language: slate/zinc backgrounds, teal primary accent, amber warnings, rose errors. No neon glow, no animated grid, no scan lines. System font stack, 8px spacing grid, subtle shadows.

- [ ] **Step 1: Create theme.css with design tokens and reset**

```css
/* ═══════════════════════════════════════════════════════
   agenttop — Crafted Dark Theme
   ═══════════════════════════════════════════════════════ */

:root {
  /* Surface colors — zinc/slate family */
  --bg-root: #09090b;
  --bg-surface: #18181b;
  --bg-elevated: #27272a;
  --bg-card: #1e1e23;
  --bg-hover: rgba(255, 255, 255, 0.04);
  --bg-active: rgba(255, 255, 255, 0.06);

  /* Border */
  --border-default: rgba(255, 255, 255, 0.08);
  --border-subtle: rgba(255, 255, 255, 0.05);
  --border-focus: #2dd4bf;

  /* Text */
  --text-primary: #fafafa;
  --text-secondary: #a1a1aa;
  --text-muted: #71717a;
  --text-dim: #52525b;

  /* Accent — teal */
  --accent: #2dd4bf;
  --accent-dim: rgba(45, 212, 191, 0.15);
  --accent-hover: #5eead4;

  /* Semantic */
  --success: #34d399;
  --success-dim: rgba(52, 211, 153, 0.12);
  --warning: #fbbf24;
  --warning-dim: rgba(251, 191, 36, 0.12);
  --error: #f87171;
  --error-dim: rgba(248, 113, 113, 0.12);
  --info: #60a5fa;
  --info-dim: rgba(96, 165, 250, 0.12);

  /* Tool colors — muted versions */
  --tool-claude: #f97316;
  --tool-cursor: #22d3ee;
  --tool-kiro: #34d399;
  --tool-copilot: #60a5fa;
  --tool-codex: #c084fc;
  --tool-windsurf: #facc15;

  /* Typography */
  --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  --font-mono: 'SF Mono', 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
  --text-xs: 11px;
  --text-sm: 12px;
  --text-base: 13px;
  --text-md: 14px;
  --text-lg: 16px;
  --text-xl: 20px;

  /* Spacing — 4px base */
  --sp-1: 4px;
  --sp-2: 8px;
  --sp-3: 12px;
  --sp-4: 16px;
  --sp-5: 20px;
  --sp-6: 24px;
  --sp-8: 32px;
  --sp-10: 40px;

  /* Radius */
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
  --radius-xl: 12px;

  /* Shadows */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.3);
  --shadow-md: 0 2px 8px rgba(0,0,0,0.4);
  --shadow-lg: 0 4px 16px rgba(0,0,0,0.5);

  /* Transitions */
  --ease-out: cubic-bezier(0.25, 0.46, 0.45, 0.94);
  --duration-fast: 120ms;
  --duration-normal: 200ms;

  /* Legacy aliases for existing JS that references old var names */
  --neon-cyan: var(--accent);
  --neon-orange: var(--tool-claude);
  --neon-green: var(--success);
  --neon-yellow: var(--warning);
  --neon-red: var(--error);
  --neon-blue: var(--info);
  --neon-magenta: var(--tool-codex);
  --neon-purple: var(--tool-codex);
  --neon-white: var(--text-primary);
  --bg-deep: var(--bg-root);
  --bg-dark: var(--bg-surface);
  --bg-panel: var(--bg-surface);
  --border-dim: var(--border-subtle);
  --border-glow: var(--border-focus);
  --panel-radius: var(--radius-lg);
  --font-mono: var(--font-mono);
  --ease-spring: var(--ease-out);
}

*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

html, body {
  height: 100%;
  background: var(--bg-root);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-base);
  overflow: hidden;
  -webkit-font-smoothing: antialiased;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-default); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-dim); }
```

- [ ] **Step 2: Add layout styles (topbar, main grid, panels)**

Add to theme.css — the topbar, main 2-column layout, panel base styles, tool bar. These replace the existing neon.css layout sections. Keep the same HTML structure and IDs so existing JS works.

Key layout changes:
- Remove `.bg-grid`, `.bg-scan`, `.bg-vignette` (no animated backgrounds)
- `.glass-panel` becomes a simple card with border + shadow (no backdrop-blur)
- Main grid: `grid-template-columns: 1fr 420px` (graph left, data right)
- Panels use consistent padding/spacing from the token system

- [ ] **Step 3: Add component styles (buttons, badges, charts, session rows, model bars, cost bars, hourly chart)**

All the component-level styles that panels.js, stats.js, graph.js reference. Port every class from neon.css that's referenced by JS, but with the new design language. Key classes:
- `.session-row`, `.model-row`, `.cost-row` — clean rows, no glow
- `.hour-bar` — teal fill, no glow
- `.neon-btn` → keep class name, restyle as solid teal button
- `.panel-badge` — subtle pill with muted background
- `.neon-select` — clean select with border

- [ ] **Step 4: Add optimizer/drawer styles**

The optimizer drawer styles: `.drawer`, `.collapsed`, `.fullscreen`, score circle, grade cards, recommendation cards, anti-pattern cards, dev profile, cost forensics, prompt analysis, all from optimizer.js. Port every class used by optimizer.js with new design language.

- [ ] **Step 5: Add detail overlay + tooltip + animation styles**

Node detail overlay, tooltip, fade-in animations. Keep `.hidden` class. Remove all glow/pulse animations, keep functional transitions only.

- [ ] **Step 6: Swap stylesheet in index.html**

Change line 8 from `neon.css` to `theme.css`.

- [ ] **Step 7: Verify dashboard loads**

Run: `PYTHONPATH=src .venv/bin/python -m uvicorn agenttop.web.server:app --port 8420 --reload`

Open http://localhost:8420 and verify all panels render with the new theme. Check: topbar, graph, model usage, hourly, sessions, cost, optimizer drawer.

- [ ] **Step 8: Commit**

```bash
git add src/agenttop/web/static/css/theme.css src/agenttop/web/static/index.html
git commit -m "feat: replace neon cyberpunk theme with crafted dark design system"
```

---

### Task 2: Backend — Session Detail + Selective Analysis Endpoints

**Files:**
- Modify: `src/agenttop/web/server.py:102-116` (update `/api/sessions`, add new endpoints)
- Modify: `src/agenttop/web/optimizer/__init__.py:62-63,182-189` (remove cap, add selective analyze method)
- Test: `tests/test_server_sessions.py`

- [ ] **Step 1: Write failing test for `/api/sessions/{id}`**

```python
# tests/test_server_sessions.py
"""Tests for session detail and selective analysis endpoints."""
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from agenttop.web.server import app

client = TestClient(app)


def _mock_session(sid="test-123", tool="claude_code", project="/tmp/proj",
                  tokens=1000, cost=0.5, prompts=None):
    """Create a mock Session object."""
    from datetime import datetime
    from agenttop.models import Session, ToolName
    return Session(
        id=sid,
        tool=ToolName.CLAUDE_CODE if tool == "claude_code" else ToolName.CURSOR,
        project=project,
        start_time=datetime(2026, 1, 1, 10, 0),
        end_time=datetime(2026, 1, 1, 11, 0),
        message_count=10,
        tool_call_count=5,
        total_tokens=tokens,
        estimated_cost_usd=cost,
        prompts=prompts or ["fix the bug", "add tests"],
    )


class TestSessionDetail:
    def test_session_found(self):
        mock_collector = MagicMock()
        mock_collector.is_available.return_value = True
        mock_collector.collect_sessions.return_value = [_mock_session()]

        with patch("agenttop.web.server._collectors", [("Claude Code", mock_collector)]):
            with patch("agenttop.web.server._config", MagicMock()):
                resp = client.get("/api/sessions/test-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "test-123"
        assert data["prompts"] == ["fix the bug", "add tests"]

    def test_session_not_found(self):
        mock_collector = MagicMock()
        mock_collector.is_available.return_value = True
        mock_collector.collect_sessions.return_value = [_mock_session()]

        with patch("agenttop.web.server._collectors", [("Claude Code", mock_collector)]):
            with patch("agenttop.web.server._config", MagicMock()):
                resp = client.get("/api/sessions/nonexistent")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_server_sessions.py -v`
Expected: FAIL — no route for `/api/sessions/{id}`

- [ ] **Step 3: Implement `/api/sessions/{id}` endpoint**

Add to `server.py` after the existing `/api/sessions` endpoint (after line 116):

```python
@app.get("/api/sessions/{session_id}")
def api_session_detail(session_id: str) -> JSONResponse:
    """Get full session detail including prompts."""
    _init()
    for _, collector in _collectors:
        if not collector.is_available():
            continue
        for s in collector.collect_sessions():
            if s.id == session_id:
                return JSONResponse(s.model_dump(mode="json"))
    return JSONResponse({"error": "Session not found"}, status_code=404)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_server_sessions.py -v`
Expected: PASS

- [ ] **Step 5: Write failing test for `/api/analyze-sessions`**

Add to `tests/test_server_sessions.py`:

```python
class TestAnalyzeSessions:
    def test_analyze_selected_sessions(self):
        sessions = [_mock_session("s1", prompts=["build auth"]),
                    _mock_session("s2", prompts=["fix login bug"])]
        mock_collector = MagicMock()
        mock_collector.is_available.return_value = True
        mock_collector.collect_sessions.return_value = sessions
        mock_collector.tool_name = MagicMock(value="claude_code")
        mock_collector.get_feature_config.return_value = {}

        mock_config = MagicMock()
        mock_claude = MagicMock()
        mock_claude.is_available.return_value = True
        mock_claude.get_model_usage.return_value = {}

        with patch("agenttop.web.server._collectors", [("Claude Code", mock_collector)]), \
             patch("agenttop.web.server._config", mock_config), \
             patch("agenttop.web.server._claude", mock_claude), \
             patch("agenttop.web.optimizer.AIUsageOptimizer.analyze") as mock_analyze:
            mock_analyze.return_value = {"score": 75, "source": "llm"}
            resp = client.post("/api/analyze-sessions",
                               json={"session_ids": ["s1", "s2"]})
        assert resp.status_code == 200
        data = resp.json()
        assert "score" in data

    def test_analyze_empty_ids(self):
        with patch("agenttop.web.server._config", MagicMock()):
            resp = client.post("/api/analyze-sessions", json={"session_ids": []})
        assert resp.status_code == 400
```

- [ ] **Step 6: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_server_sessions.py::TestAnalyzeSessions -v`
Expected: FAIL

- [ ] **Step 7: Implement `/api/analyze-sessions` endpoint**

Add to `server.py`:

```python
class AnalyzeSessionsRequest(BaseModel):
    session_ids: list[str]


@app.post("/api/analyze-sessions")
async def api_analyze_sessions(req: AnalyzeSessionsRequest) -> JSONResponse:
    """Analyze user-selected sessions via the optimizer pipeline."""
    if not req.session_ids:
        return JSONResponse({"error": "No session IDs provided"}, status_code=400)

    _init()
    from agenttop.web.optimizer import AIUsageOptimizer

    # Collect all sessions, filter to requested IDs
    requested = set(req.session_ids)
    selected_sessions: list = []
    feature_configs: dict[str, Any] = {}
    for _, collector in _collectors:
        if collector.is_available():
            for s in collector.collect_sessions():
                if s.id in requested:
                    selected_sessions.append(s)
            fc = collector.get_feature_config()
            if fc:
                feature_configs[collector.tool_name.value] = fc

    if not selected_sessions:
        return JSONResponse({"error": "No matching sessions found"}, status_code=404)

    stats = _get_all_stats(0)
    model_usage = _claude.get_model_usage() if _claude and _claude.is_available() else {}

    optimizer = AIUsageOptimizer(_config, claude_collector=_claude)
    try:
        result = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None, optimizer.analyze, stats, selected_sessions,
                model_usage, feature_configs,
            ),
            timeout=300.0,
        )
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Analysis timed out"}, status_code=504)

    return JSONResponse(result)
```

- [ ] **Step 8: Remove the 10-session hard cap in optimizer**

In `src/agenttop/web/optimizer/__init__.py`, change line 63:

Old: `_MAX_NEW_PER_MAP_RUN = 10`
New: `_MAX_NEW_PER_MAP_RUN = 50`

And in `_analyze_sessions_map` at line 186, change the top-session slice from `[:30]` to `[:100]`:

Old: ``)[:30]`
New: ``)[:100]`

- [ ] **Step 9: Run all tests**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_server_sessions.py tests/test_optimizer.py -v`
Expected: ALL PASS

- [ ] **Step 10: Commit**

```bash
git add src/agenttop/web/server.py src/agenttop/web/optimizer/__init__.py tests/test_server_sessions.py
git commit -m "feat: add session detail endpoint and selective analysis API

- GET /api/sessions/{id} returns full session with prompts
- POST /api/analyze-sessions accepts session_ids array for targeted LLM analysis
- Raise MAP cap from 10 to 50 sessions per run"
```

---

### Task 3: Session Explorer Frontend

**Files:**
- Create: `src/agenttop/web/static/js/session-explorer.js`
- Modify: `src/agenttop/web/static/index.html` (new session explorer section, add script tag)
- Modify: `src/agenttop/web/static/js/app.js` (call SessionExplorer.init)
- Modify: `src/agenttop/web/static/css/theme.css` (session explorer styles)

- [ ] **Step 1: Create session-explorer.js — data fetching and state**

```javascript
/* agenttop — Session Explorer */

const SessionExplorer = {
  _sessions: [],
  _filtered: [],
  _selected: new Set(),
  _activeId: null,
  _detail: null,
  _filters: { tool: '', project: '', search: '' },
  _sort: 'time',
  _analyzing: false,

  async init() {
    await SessionExplorer.load();
  },

  async load() {
    const days = typeof App !== 'undefined' ? App.days : 7;
    try {
      const res = await fetch(`/api/sessions?days=${days || 7}`);
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
    if (f.project) list = list.filter(s => (s.project || '').includes(f.project));
    if (f.search) {
      const q = f.search.toLowerCase();
      list = list.filter(s => {
        const proj = (s.project || '').toLowerCase();
        const firstPrompt = ((s.prompts || [])[0] || '').toLowerCase();
        return proj.includes(q) || firstPrompt.includes(q) || (s.id || '').includes(q);
      });
    }

    // Sort
    if (SessionExplorer._sort === 'cost') {
      list.sort((a, b) => (b.estimated_cost_usd || 0) - (a.estimated_cost_usd || 0));
    } else if (SessionExplorer._sort === 'tokens') {
      list.sort((a, b) => (b.total_tokens || 0) - (a.total_tokens || 0));
    } else {
      list.sort((a, b) => {
        const ta = new Date(b.start_time || 0).getTime();
        const tb = new Date(a.start_time || 0).getTime();
        return ta - tb;
      });
    }

    SessionExplorer._filtered = list;
  },

  // ... render, renderDetail, analyzeSelected defined in next steps
};
```

- [ ] **Step 2: Add session list rendering**

Add `render()` method to SessionExplorer. This renders the full explorer panel: filter bar at top, scrollable session list below. Each row has a checkbox, tool dot, project name, duration, cost, token count, time ago. Clicking a row opens detail. Shift-click selects range.

Key structure:
```html
<div class="se-toolbar">
  <input class="se-search" placeholder="Search sessions...">
  <select class="se-filter-tool">...</select>
  <select class="se-sort">...</select>
  <button class="se-analyze-btn" disabled>Analyze Selected (0)</button>
</div>
<div class="se-list">
  <div class="se-row" data-id="...">
    <input type="checkbox" class="se-check">
    <span class="se-dot" style="background:..."></span>
    <span class="se-project">project-name</span>
    <span class="se-dur">1.2h</span>
    <span class="se-cost">$4.50</span>
    <span class="se-tokens">120K</span>
    <span class="se-time">2h ago</span>
  </div>
  ...
</div>
```

Wire up event listeners: checkbox toggles selection, row click opens detail, search input filters, sort select reorders.

- [ ] **Step 3: Add session detail panel**

Add `renderDetail(session)` method. When a session row is clicked, fetch full detail from `/api/sessions/{id}` and render a slide-in panel on the right side:

```html
<div class="se-detail">
  <div class="se-detail-header">
    <button class="se-back">&larr;</button>
    <h3>project-name</h3>
    <span class="se-tool-badge">Claude Code</span>
  </div>
  <div class="se-detail-meta">
    <span>1h 23m</span> <span>45 messages</span> <span>120K tokens</span> <span>$4.50</span>
  </div>
  <div class="se-prompts">
    <div class="se-prompt">
      <span class="se-prompt-time">10:00</span>
      <span class="se-prompt-text">fix the authentication bug in...</span>
      <span class="se-prompt-tokens">2.1K</span>
    </div>
    ...
  </div>
  <button class="se-analyze-one">Analyze This Session</button>
</div>
```

The prompt list shows all prompts from the session with timestamps. Each prompt is expandable (click to show full text, default shows first 200 chars).

- [ ] **Step 4: Add batch analysis UI**

Add `analyzeSelected()` method. When the "Analyze Selected (N)" button is clicked:
1. Show confirmation if N > 30: "This may take a while. Continue?"
2. POST to `/api/analyze-sessions` with `{ session_ids: [...] }`
3. Show progress indicator in the toolbar
4. On result, render a summary panel below the session list with score, key findings

Also add `analyzeOne(sessionId)` for the single-session "Analyze This Session" button.

- [ ] **Step 5: Add session explorer styles to theme.css**

```css
/* ── Session Explorer ── */
.se-container { display: flex; flex-direction: column; height: 100%; }

.se-toolbar {
  display: flex; gap: var(--sp-2); padding: var(--sp-3);
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
}
.se-search {
  flex: 1; padding: var(--sp-2) var(--sp-3);
  background: var(--bg-elevated); border: 1px solid var(--border-default);
  border-radius: var(--radius-md); color: var(--text-primary);
  font-size: var(--text-sm); outline: none;
}
.se-search:focus { border-color: var(--accent); }
.se-search::placeholder { color: var(--text-muted); }

.se-filter-tool, .se-sort {
  padding: var(--sp-1) var(--sp-2); background: var(--bg-elevated);
  border: 1px solid var(--border-default); border-radius: var(--radius-md);
  color: var(--text-secondary); font-size: var(--text-xs);
}

.se-analyze-btn {
  padding: var(--sp-2) var(--sp-3); background: var(--accent);
  color: var(--bg-root); border: none; border-radius: var(--radius-md);
  font-size: var(--text-sm); font-weight: 600; cursor: pointer;
  opacity: 0.5; pointer-events: none;
}
.se-analyze-btn.active { opacity: 1; pointer-events: auto; }
.se-analyze-btn:hover { background: var(--accent-hover); }

.se-list { flex: 1; overflow-y: auto; }

.se-row {
  display: flex; align-items: center; gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3); border-bottom: 1px solid var(--border-subtle);
  cursor: pointer; transition: background var(--duration-fast);
}
.se-row:hover { background: var(--bg-hover); }
.se-row.active { background: var(--bg-active); border-left: 2px solid var(--accent); }
.se-row.selected { background: var(--accent-dim); }

.se-check { accent-color: var(--accent); cursor: pointer; }
.se-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.se-project { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--text-sm); }
.se-dur, .se-cost, .se-tokens, .se-time {
  font-size: var(--text-xs); color: var(--text-muted); font-family: var(--font-mono);
  flex-shrink: 0;
}
.se-cost { color: var(--tool-claude); min-width: 50px; text-align: right; }
.se-tokens { min-width: 45px; text-align: right; }
.se-time { min-width: 45px; text-align: right; }

/* Detail slide-in */
.se-detail {
  position: absolute; top: 0; right: 0; bottom: 0; width: 50%;
  background: var(--bg-surface); border-left: 1px solid var(--border-default);
  display: flex; flex-direction: column; z-index: 10;
  transform: translateX(100%); transition: transform var(--duration-normal) var(--ease-out);
}
.se-detail.open { transform: translateX(0); }

.se-detail-header {
  display: flex; align-items: center; gap: var(--sp-3);
  padding: var(--sp-4); border-bottom: 1px solid var(--border-default);
}
.se-back {
  background: none; border: none; color: var(--text-secondary);
  font-size: var(--text-lg); cursor: pointer; padding: var(--sp-1);
}
.se-back:hover { color: var(--text-primary); }

.se-detail-meta {
  display: flex; gap: var(--sp-4); padding: var(--sp-3) var(--sp-4);
  font-size: var(--text-xs); color: var(--text-muted);
  border-bottom: 1px solid var(--border-subtle);
}

.se-prompts { flex: 1; overflow-y: auto; padding: var(--sp-2); }

.se-prompt {
  display: flex; gap: var(--sp-2); padding: var(--sp-2) var(--sp-3);
  border-radius: var(--radius-md); margin-bottom: var(--sp-1);
}
.se-prompt:hover { background: var(--bg-hover); }
.se-prompt-time { font-size: var(--text-xs); color: var(--text-dim); min-width: 40px; font-family: var(--font-mono); }
.se-prompt-text {
  flex: 1; font-size: var(--text-sm); color: var(--text-secondary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: pointer;
}
.se-prompt-text.expanded { white-space: normal; word-break: break-word; }

.se-analyze-one {
  margin: var(--sp-3); padding: var(--sp-2) var(--sp-4);
  background: var(--accent-dim); color: var(--accent); border: 1px solid var(--accent);
  border-radius: var(--radius-md); cursor: pointer; font-size: var(--text-sm);
}
.se-analyze-one:hover { background: var(--accent); color: var(--bg-root); }

/* Analysis results inline */
.se-analysis-result {
  padding: var(--sp-4); background: var(--bg-elevated);
  border-top: 1px solid var(--border-default);
}
```

- [ ] **Step 6: Update index.html — replace sessions panel with explorer**

Replace the existing sessions panel (lines 98-108) with a larger session explorer section. Also add the script tag for session-explorer.js.

```html
<!-- Session Explorer (replaces old Recent Sessions) -->
<div id="sessions-panel" class="panel sessions-panel">
  <div class="panel-header">
    <div class="panel-title">Sessions</div>
    <div id="sessions-count" class="panel-badge"></div>
  </div>
  <div id="sessions-content" class="panel-body" style="position:relative;"></div>
</div>
```

Add before `</body>`:
```html
<script src="/static/js/session-explorer.js"></script>
```

- [ ] **Step 7: Wire into app.js**

In `app.js`, in the `refresh()` method, after `App.data.sessions = await sessionsRes.json()`, replace `Panels.renderSessions(App.data.sessions)` with:

```javascript
SessionExplorer._sessions = App.data.sessions;
SessionExplorer._applyFilters();
SessionExplorer.render();
```

- [ ] **Step 8: Verify session explorer works**

Reload dashboard. Test:
1. Session list renders with search/filter/sort
2. Click a session → detail slides in with prompt history
3. Select multiple sessions via checkboxes
4. "Analyze Selected" button activates when sessions selected

- [ ] **Step 9: Commit**

```bash
git add src/agenttop/web/static/js/session-explorer.js src/agenttop/web/static/index.html src/agenttop/web/static/js/app.js src/agenttop/web/static/css/theme.css
git commit -m "feat: add interactive session explorer with detail view and batch analysis

- Search, filter by tool, sort by time/cost/tokens
- Click session to see full prompt history
- Multi-select sessions for batch LLM analysis
- Replaces static session list"
```

---

### Task 4: Optimizer Panel Rework (Drawer → Side Panel)

**Files:**
- Modify: `src/agenttop/web/static/index.html` (restructure optimizer from drawer to panel)
- Modify: `src/agenttop/web/static/js/optimizer.js` (update toggle logic)
- Modify: `src/agenttop/web/static/css/theme.css` (optimizer as side panel)

- [ ] **Step 1: Update index.html — move optimizer to side panel**

Replace the bottom drawer markup with a right-side slide panel:

```html
<!-- Optimizer Side Panel -->
<aside id="optimizer-panel" class="side-panel collapsed">
  <div class="side-panel-header" id="drawer-toggle">
    <span class="side-panel-title">AI Optimizer</span>
    <div class="side-panel-controls">
      <span class="side-panel-expand" id="drawer-fullscreen" title="Expand">⛶</span>
      <span class="side-panel-close" id="drawer-chevron">&times;</span>
    </div>
  </div>
  <div id="optimizer-content" class="side-panel-body"></div>
</aside>
```

Add a trigger button in the topbar:
```html
<button id="optimizer-trigger" class="topbar-btn" title="AI Optimizer">
  <span>Optimizer</span>
</button>
```

- [ ] **Step 2: Update optimizer.js toggle logic**

Update `Optimizer.init()` and toggle methods to work with the side panel instead of a drawer. The `collapsed` class slides it offscreen to the right. `expanded` slides it in. `fullscreen` makes it full width.

- [ ] **Step 3: Add side panel styles to theme.css**

```css
.side-panel {
  position: fixed; top: 0; right: 0; bottom: 0;
  width: 560px; max-width: 100vw;
  background: var(--bg-surface); border-left: 1px solid var(--border-default);
  z-index: 100; display: flex; flex-direction: column;
  transform: translateX(100%); transition: transform var(--duration-normal) var(--ease-out);
  box-shadow: var(--shadow-lg);
}
.side-panel:not(.collapsed) { transform: translateX(0); }
.side-panel.fullscreen { width: 100vw; }
```

- [ ] **Step 4: Verify optimizer works as side panel**

Click "Optimizer" button in topbar. Panel slides in from right. Escape closes it. All existing optimizer features work.

- [ ] **Step 5: Commit**

```bash
git add src/agenttop/web/static/index.html src/agenttop/web/static/js/optimizer.js src/agenttop/web/static/css/theme.css
git commit -m "refactor: move optimizer from bottom drawer to right side panel"
```

---

### Task 5: Polish and Integration Testing

**Files:**
- Modify: `src/agenttop/web/static/css/theme.css` (final polish)
- Modify: `src/agenttop/web/static/js/app.js` (cleanup)
- Test: `tests/test_server_sessions.py`

- [ ] **Step 1: Run all existing tests**

Run: `PYTHONPATH=src .venv/bin/pytest tests/ -v`
Expected: ALL PASS (243 existing + new session tests)

- [ ] **Step 2: Test all API endpoints manually**

```bash
curl -s http://localhost:8420/api/stats | python3 -m json.tool | head -5
curl -s http://localhost:8420/api/sessions?days=7 | python3 -m json.tool | head -5
curl -s "http://localhost:8420/api/sessions/$(curl -s http://localhost:8420/api/sessions?days=7 | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')" | python3 -m json.tool | head -10
curl -s -X POST http://localhost:8420/api/analyze-sessions -H 'Content-Type: application/json' -d '{"session_ids":[]}' | python3 -m json.tool
```

- [ ] **Step 3: Visual QA checklist**

Open http://localhost:8420 and verify:
- [ ] No neon glow anywhere
- [ ] Clean typography hierarchy
- [ ] Session explorer: search works, filter works, sort works
- [ ] Session detail: prompts display, back button works
- [ ] Multi-select: checkboxes work, "Analyze" button enables
- [ ] Optimizer: opens as side panel, score renders, all sections display
- [ ] Graph: D3 renders correctly with new colors
- [ ] Model usage bars: clean, no glow
- [ ] Hourly chart: teal bars
- [ ] Cost breakdown: tool colors preserved
- [ ] No JS console errors

- [ ] **Step 4: Remove old neon.css**

Once theme.css is verified working, delete the old file:

```bash
git rm src/agenttop/web/static/css/neon.css
```

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: remove old neon.css, polish theme and integration"
```
