# Tab Navigation + PR #21 Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the floating sessions drawer with top-level tab navigation (Overview | Sessions | Analyze), fix all PR #21 review issues, and improve UX from a user perspective.

**Architecture:** Add a tab bar below the topbar. Each tab shows full-page content. The existing graph+panels become the "Overview" tab. Sessions Browse and Analyze get promoted to full-page tabs. URL hash routing enables deep linking. Server-side: build session index for O(1) lookups.

**Tech Stack:** Vanilla JS, CSS custom properties, FastAPI (Python), no new dependencies.

---

### Task 1: Add Tab Bar to HTML + CSS

**Files:**
- Modify: `src/agenttop/web/static/index.html:44-88`
- Modify: `src/agenttop/web/static/css/theme.css:81-96`

- [ ] **Step 1: Add tab bar HTML after topbar, wrap existing main in tab pane**

In `index.html`, add a `<nav id="tab-bar">` between `</header>` (line 43) and `<main>` (line 46). Wrap existing `<main>` content in a tab pane div. Add two new empty tab pane divs for Sessions and Analyze.

```html
<!-- Tab Bar -->
<nav id="tab-bar" class="tab-bar">
  <button class="tab-btn active" data-tab="overview">
    <span class="tab-icon">◈</span> Overview
    <span class="tab-badge" id="tab-badge-overview"></span>
  </button>
  <button class="tab-btn" data-tab="sessions">
    <span class="tab-icon">▣</span> Sessions
    <span class="tab-badge" id="tab-badge-sessions"></span>
  </button>
  <button class="tab-btn" data-tab="analyze">
    <span class="tab-icon">⚡</span> Analyze
    <span class="tab-badge" id="tab-badge-analyze"></span>
  </button>
</nav>
```

Wrap the existing `<main id="main">` content inside `<div class="tab-pane active" id="pane-overview">`. Add `<div class="tab-pane" id="pane-sessions">` and `<div class="tab-pane" id="pane-analyze">` as siblings.

Remove the entire `#sessions-drawer` div (lines 99-113).

- [ ] **Step 2: Add tab bar CSS + tab pane layout**

In `theme.css`, after the `#topbar` rules (~line 90), add:

```css
/* ── Tab Bar ── */
.tab-bar {
  position: fixed; top: 48px; left: 0; right: 0; z-index: 49;
  height: 36px; display: flex; align-items: stretch;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-default);
  padding: 0 var(--sp-4);
  gap: 0;
}
.tab-btn {
  display: flex; align-items: center; gap: 6px;
  padding: 0 var(--sp-4);
  font-size: var(--text-sm); font-weight: 600;
  color: var(--text-muted); background: none; border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all var(--duration-fast);
}
.tab-btn:hover { color: var(--text-secondary); background: var(--bg-hover); }
.tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
.tab-icon { font-size: var(--text-xs); }
.tab-badge {
  font-size: 10px; font-weight: 700; font-family: var(--font-mono);
  color: var(--text-dim); background: var(--bg-elevated);
  padding: 1px 6px; border-radius: 8px;
  min-width: 20px; text-align: center;
}
.tab-badge:empty { display: none; }
```

Update `#main` top from `48px` to `84px` (48px topbar + 36px tab bar):

```css
#main {
  position: fixed; top: 84px; left: 0; right: 0; bottom: 36px;
  ...
}
```

Add tab pane rules:

```css
.tab-pane { display: none; }
.tab-pane.active { display: contents; }
```

- [ ] **Step 3: Update sessions drawer CSS**

Remove or comment out the `.sessions-drawer` block (lines 130-155 of theme.css) since the drawer is being replaced by tabs.

- [ ] **Step 4: Commit**

```bash
git add src/agenttop/web/static/index.html src/agenttop/web/static/css/theme.css
git commit -m "feat: add top-level tab bar (Overview | Sessions | Analyze), remove floating drawer"
```

---

### Task 2: Tab Switching Logic in app.js

**Files:**
- Modify: `src/agenttop/web/static/js/app.js`

- [ ] **Step 1: Add tab switching to App object**

Add a `_currentTab` property and `switchTab()` method to the `App` object:

```javascript
_currentTab: 'overview',

switchTab(tabId) {
  App._currentTab = tabId;
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabId);
  });
  document.querySelectorAll('.tab-pane').forEach(pane => {
    pane.classList.toggle('active', pane.id === 'pane-' + tabId);
  });
  // Update URL hash
  history.replaceState(null, '', '#' + tabId);
  // Trigger render for the active tab
  if (tabId === 'sessions' && typeof SessionExplorer !== 'undefined') {
    SessionExplorer.renderBrowse();
  }
  if (tabId === 'analyze' && typeof SessionExplorer !== 'undefined') {
    SessionExplorer.renderAnalyze();
  }
},
```

- [ ] **Step 2: Wire up tab bar click handlers and keyboard shortcuts in init()**

In `App.init()`, after the existing keyboard shortcut block, add:

```javascript
// Tab bar click handlers
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => App.switchTab(btn.dataset.tab));
});

// Tab keyboard shortcuts
// Add to existing keydown handler:
if (e.key === 'o') App.switchTab('overview');
if (e.key === 's') App.switchTab('sessions');
if (e.key === 'a') App.switchTab('analyze');

// Restore tab from URL hash
const hash = location.hash.slice(1);
if (['overview', 'sessions', 'analyze'].includes(hash)) {
  App.switchTab(hash);
}
```

- [ ] **Step 3: Update refresh() to update tab badges**

In `App.refresh()`, after sessions data is loaded, update badges:

```javascript
// Update tab badges
const nonEmpty = App.data.sessions.filter(s => (s.message_count || 0) > 0 || (s.total_tokens || 0) > 0);
const sessBadge = document.getElementById('tab-badge-sessions');
if (sessBadge) sessBadge.textContent = nonEmpty.length;
```

Remove the old drawer-specific SessionExplorer code from `refresh()` (lines 92-101).

- [ ] **Step 4: Commit**

```bash
git add src/agenttop/web/static/js/app.js
git commit -m "feat: tab switching with URL hash routing and keyboard shortcuts (o/s/a)"
```

---

### Task 3: Refactor SessionExplorer for Full-Page Tabs

**Files:**
- Modify: `src/agenttop/web/static/js/session-explorer.js`

- [ ] **Step 1: Refactor SessionExplorer to render into separate pane containers**

Remove all drawer toggle logic (`init()` lines 16-37, `_drawerOpen` state). Replace `render()` with two independent methods: `renderBrowse()` renders into `#pane-sessions`, `renderAnalyze()` renders into `#pane-analyze`.

The new `init()` should just store a reference — no drawer event handlers:

```javascript
init() {
  // No-op now — tab switching handled by App.switchTab()
},
```

`renderBrowse()` renders the full Browse UI (search + split pane) directly into `#pane-sessions`:

```javascript
renderBrowse() {
  const el = document.getElementById('pane-sessions');
  if (!el) return;
  this._applyFilters();

  const tools = [...new Set(this._sessions.map(s => s.tool))].sort();
  const toolOpts = tools.map(t => `<option value="${t}" ${this._filters.tool === t ? 'selected' : ''}>${this._toolName(t)}</option>`).join('');
  const sortOpts = [['time','Recent'],['cost','Cost'],['tokens','Tokens']].map(([v,l]) =>
    `<option value="${v}" ${this._sort === v ? 'selected' : ''}>${l}</option>`
  ).join('');

  el.innerHTML = `
    <div class="se-page">
      <div class="se-page-header">
        <h2 class="se-page-title">Sessions</h2>
        <span class="se-page-count">${this._filtered.length} sessions</span>
      </div>
      <div class="se-toolbar">
        <input class="se-search" placeholder="Search projects, prompts..." value="${this._esc(this._filters.search)}">
        <select class="se-filter-tool"><option value="">All Tools</option>${toolOpts}</select>
        <select class="se-sort">${sortOpts}</select>
      </div>
      <div class="se-split">
        <div class="se-list">${this._renderSessionList()}</div>
        <div class="se-detail-pane" id="se-detail-pane">
          ${this._activeId ? '' : '<div class="se-detail-empty">Click a session to see details</div>'}
        </div>
      </div>
    </div>
  `;

  this._bindBrowseEvents(el);
  if (this._activeId) this._loadDetail(this._activeId);
},
```

Extract `_renderSessionList()` as a helper (uses the same loop from old `_renderBrowse` but shows up to 200 items instead of 100).

`renderAnalyze()` renders into `#pane-analyze` — same content as old `_renderAnalyze()` but full-page layout.

- [ ] **Step 2: Add full-page CSS for session panes**

Add to `theme.css`:

```css
/* ── Full-page session tabs ── */
.se-page {
  display: flex; flex-direction: column; height: 100%;
  position: fixed; top: 84px; left: 0; right: 0; bottom: 36px;
}
.se-page-header {
  display: flex; align-items: center; gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
}
.se-page-title {
  font-size: var(--text-lg); font-weight: 700; color: var(--text-primary);
}
.se-page-count {
  font-size: var(--text-xs); color: var(--text-muted);
  background: var(--bg-elevated); padding: 2px 8px; border-radius: 10px;
}
```

Update `.se-split` to use full height:

```css
.se-split { display: flex; flex: 1; min-height: 0; overflow: hidden; }
.se-list { width: 380px; overflow-y: auto; border-right: 1px solid var(--border-default); flex-shrink: 0; }
.se-detail-pane { flex: 1; overflow-y: auto; }
```

- [ ] **Step 3: Add sort dropdown binding**

In `_bindBrowseEvents`, add handler for the new sort dropdown:

```javascript
const sortEl = el.querySelector('.se-sort');
if (sortEl) sortEl.addEventListener('change', () => { this._sort = sortEl.value; this.renderBrowse(); });
```

- [ ] **Step 4: Remove old render() method and drawer references**

Delete `render()`, `_renderBrowse()`, `_activeTab`, `_drawerOpen` — they're replaced by `renderBrowse()` and `renderAnalyze()`.

- [ ] **Step 5: Commit**

```bash
git add src/agenttop/web/static/js/session-explorer.js src/agenttop/web/static/css/theme.css
git commit -m "refactor: session explorer renders into full-page tab panes"
```

---

### Task 4: Full-Page Analyze Tab

**Files:**
- Modify: `src/agenttop/web/static/js/session-explorer.js`
- Modify: `src/agenttop/web/static/css/theme.css`

- [ ] **Step 1: Implement renderAnalyze() as full-page layout**

```javascript
renderAnalyze() {
  const el = document.getElementById('pane-analyze');
  if (!el) return;
  this._applyFilters();
  const selCount = this._selected.size;

  el.innerHTML = `
    <div class="se-page">
      <div class="se-page-header">
        <h2 class="se-page-title">Analyze</h2>
        <span class="se-page-count">${selCount > 0 ? selCount + ' selected' : 'Select sessions'}</span>
      </div>
      <div class="se-analyze-layout">
        <div class="se-analyze-sidebar">
          <div class="se-analyze-toolbar">
            <button class="se-analyze-all-btn" id="se-select-recent">Select Last 10</button>
            <button class="se-analyze-btn ${selCount > 0 ? 'active' : ''}" id="se-run-analyze" ${selCount === 0 ? 'disabled' : ''}>
              ${this._analyzing ? 'Analyzing...' : 'Analyze' + (selCount > 0 ? ' (' + selCount + ')' : '')}
            </button>
          </div>
          <div class="se-analyze-list">${this._renderAnalyzeList()}</div>
        </div>
        <div class="se-analyze-result">
          ${this._analysisResult ? this._renderProfile(this._analysisResult) : '<div class="se-detail-empty">Select sessions and click Analyze to generate your developer profile</div>'}
        </div>
      </div>
    </div>
  `;

  this._bindAnalyzeEvents(el);
},
```

- [ ] **Step 2: Add analyze layout CSS**

```css
.se-analyze-layout {
  display: flex; flex: 1; min-height: 0; overflow: hidden;
}
.se-analyze-sidebar {
  width: 340px; flex-shrink: 0;
  border-right: 1px solid var(--border-default);
  display: flex; flex-direction: column;
  overflow-y: auto;
}
.se-analyze-result {
  flex: 1; overflow-y: auto; padding: var(--sp-4);
}
```

- [ ] **Step 3: Extract _renderAnalyzeList() helper**

Same checkbox list as before but rendered as a helper method for cleanliness.

- [ ] **Step 4: Update _runAnalysis() to call renderAnalyze() instead of render()**

Replace `this.render()` calls in `_runAnalysis()` with `this.renderAnalyze()`.

- [ ] **Step 5: Commit**

```bash
git add src/agenttop/web/static/js/session-explorer.js src/agenttop/web/static/css/theme.css
git commit -m "feat: full-page Analyze tab with sidebar session picker and profile card"
```

---

### Task 5: Fix O(n²) Session Lookup (PR #21 Issue #3)

**Files:**
- Modify: `src/agenttop/web/server.py:119-129`

- [ ] **Step 1: Build session index and use O(1) lookup**

Replace the session detail endpoint with an indexed lookup:

```python
def _build_session_index() -> dict[str, Any]:
    """Build a session ID → Session mapping for O(1) lookups."""
    index: dict[str, Any] = {}
    for _, collector in _collectors:
        if not collector.is_available():
            continue
        for s in collector.collect_sessions():
            index[s.id] = s
    return index


@app.get("/api/sessions/{session_id}")
def api_session_detail(session_id: str) -> JSONResponse:
    """Get full session detail including prompts."""
    _init()
    index = _build_session_index()
    session = index.get(session_id)
    if session:
        return JSONResponse(session.model_dump(mode="json"))
    return JSONResponse({"error": "Session not found"}, status_code=404)
```

- [ ] **Step 2: Commit**

```bash
git add src/agenttop/web/server.py
git commit -m "fix: O(1) session lookup via index map instead of O(n²) nested loops"
```

---

### Task 6: Fix Homebrew SHA256 Placeholder (PR #21 Issue #1)

**Files:**
- Modify: `homebrew/Formula/agenttop.rb`

- [ ] **Step 1: Add comment documenting the SHA256 workflow**

Replace the placeholder with a clear instruction and use `head` install as default until a release is tagged:

```ruby
class Agenttop < Formula
  include Language::Python::Virtualenv

  desc "htop for AI coding agents — monitor Claude Code, Cursor, Kiro, Copilot and more"
  homepage "https://github.com/vicarious11/agenttop"
  url "https://github.com/vicarious11/agenttop/archive/refs/tags/v0.1.0.tar.gz"
  # SHA256 is generated after release: shasum -a 256 agenttop-0.1.0.tar.gz
  # CI workflow (.github/workflows/release.yml) auto-updates this on tag push
  sha256 "PLACEHOLDER_SHA256"
  license "Apache-2.0"
  head "https://github.com/vicarious11/agenttop.git", branch: "main"
  ...
```

- [ ] **Step 2: Commit**

```bash
git add homebrew/Formula/agenttop.rb
git commit -m "docs: document SHA256 workflow for Homebrew formula"
```

---

### Task 7: Harden Input Validation + Security Notes (PR #21 Issues #2, #4, #5)

**Files:**
- Modify: `src/agenttop/web/server.py`

- [ ] **Step 1: Add session_id input validation**

Add validation to the session detail endpoint:

```python
import re

@app.get("/api/sessions/{session_id}")
def api_session_detail(session_id: str) -> JSONResponse:
    """Get full session detail including prompts."""
    _init()
    # Validate session_id format (alphanumeric, hyphens, underscores, max 128 chars)
    if not session_id or len(session_id) > 128 or not re.match(r'^[\w\-]+$', session_id):
        return JSONResponse({"error": "Invalid session ID"}, status_code=400)
    index = _build_session_index()
    session = index.get(session_id)
    if session:
        return JSONResponse(session.model_dump(mode="json"))
    return JSONResponse({"error": "Session not found"}, status_code=404)
```

- [ ] **Step 2: Add security note about localhost-only access to install.sh**

Add a comment at the top of `install.sh`:

```bash
# Security note: Review this script before running.
# Verify contents: curl -fsSL <url> | less
```

- [ ] **Step 3: Commit**

```bash
git add src/agenttop/web/server.py install.sh
git commit -m "fix: input validation on session endpoints, security note on install script"
```

---

### Task 8: TUI Session Limit Configurable (PR #21 Issue #6)

**Files:**
- Modify: `src/agenttop/tui/session_explorer.py`

- [ ] **Step 1: Replace hardcoded 200 with configurable limit**

Add a class-level constant and use it in `_render_table()`:

```python
MAX_DISPLAY_SESSIONS = 500  # Configurable session display limit

# In _render_table(), replace:
#   for s in filtered[:200]:
# with:
#   for s in filtered[:self.MAX_DISPLAY_SESSIONS]:
```

- [ ] **Step 2: Add specific exception types in empty except blocks**

Replace bare `except:` and `except Exception:` with specific types where possible:

```python
except (AttributeError, ValueError):
    continue
```

- [ ] **Step 3: Commit**

```bash
git add src/agenttop/tui/session_explorer.py
git commit -m "fix: configurable session display limit (500), specific exception types"
```

---

### Task 9: Extract Common Session Collection Logic (PR #21 Issue #7)

**Files:**
- Modify: `src/agenttop/web/server.py`

- [ ] **Step 1: Extract _collect_all_sessions() helper**

Several endpoints duplicate the session collection loop. Extract it:

```python
def _collect_all_sessions(days: int = 7) -> list:
    """Collect sessions from all available collectors within time window."""
    _init()
    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(days=days) if days > 0 else datetime(2000, 1, 1)
    sessions = []
    for _, collector in _collectors:
        if not collector.is_available():
            continue
        for s in collector.collect_sessions():
            if s.start_time >= cutoff:
                sessions.append(s)
    return sessions
```

Use it in `api_sessions()`, `api_workflow_chains()`, `api_workflow_patterns()`, and other endpoints that repeat this pattern.

- [ ] **Step 2: Commit**

```bash
git add src/agenttop/web/server.py
git commit -m "refactor: extract _collect_all_sessions() to deduplicate endpoint logic"
```

---

### Task 10: Verify Everything Works

- [ ] **Step 1: Run tests**

```bash
cd /Users/sakshamdutta/agenttop && pytest tests/ -v
```

Expected: All existing tests pass.

- [ ] **Step 2: Start the web server and manually verify tabs**

```bash
PYTHONPATH=src python -m uvicorn agenttop.web.server:app --port 8420
```

Open `http://localhost:8420` — verify:
- Three tabs visible below topbar
- Overview tab shows graph + panels (unchanged)
- Sessions tab shows full-page session browser
- Analyze tab shows session selector + profile card
- Keyboard shortcuts o/s/a switch tabs
- URL hash updates on tab switch

- [ ] **Step 3: Commit any final fixes**
