# Phase 1: Web UI Session Explorer + Unlimited Analysis + UX Overhaul

## Problem

1. Sessions panel is a dumb list — no detail view, no chat history, no interaction
2. Optimizer hardcodes top-30-by-cost / max-10-new — user can't choose what to analyze
3. Dashboard looks "AI-generated" — generic neon cyberpunk, no personality or craft
4. No way to drill into a session to see what was actually discussed

## Design

### A. Session Explorer (new panel replacing "Recent Sessions")

**Session List (left side of panel):**
- Compact rows: tool icon + project name + duration + cost + token count + time ago
- Multi-select with checkboxes (shift-click for range, ctrl-click for toggle)
- Filter bar: by tool, by project, by date range, by cost threshold
- Sort: by time (default), cost, tokens, duration
- Search: fuzzy match against project name and first prompt

**Session Detail (right side, slide-in on click):**
- Header: tool, project, start/end time, duration, tokens, cost, model(s) used
- Chat timeline: scrollable list of prompts with timestamps
- Each prompt shows: first 300 chars expandable to full, token count badge
- If session was previously LLM-analyzed: show classification (intent, outcome, spiral status)
- "Analyze This Session" button → sends to optimizer MAP phase, shows result inline

**Batch Analysis:**
- "Analyze Selected (N)" button in toolbar when checkboxes are active
- No cap — user picks what they want (warn if >50: "This may take a while")
- Progress bar with per-session status (analyzing... done / cached)
- Results appear as a summary drawer below the session list (reuses optimizer GENERATE phase)

### B. Optimizer Changes

- Remove `_MAX_NEW_PER_MAP_RUN = 10` hard limit
- New POST endpoint: `/api/analyze-sessions` accepts `{ session_ids: string[] }`
  - Runs MAP on selected sessions (respects cache)
  - Runs REDUCE + GENERATE on just those sessions
  - Returns full optimizer-shaped result scoped to selection
- Keep existing `/api/optimize` as "analyze everything" (backward compat)
- SSE streaming for batch progress: `/api/analyze-sessions-stream`

### C. UX Overhaul — "Not AI-Generated"

**Design language shift:**
- Kill the neon glow/cyberpunk — move to a crafted dark theme with subtle depth
- Color palette: slate/zinc backgrounds, muted accent colors (teal primary, amber warnings, rose errors), no neon
- Typography: system font stack, clear hierarchy (weight + size, not color glow)
- Spacing: generous whitespace, consistent 8px grid, no cramped panels
- Cards: subtle border + shadow, no glass/blur effects
- Animations: functional only (expand/collapse, loading states), no gratuitous glow pulses
- Data visualization: clean D3 charts with proper axes/labels, no "cyber" aesthetic

**Layout restructure:**
- Top: minimal nav bar with tool status dots + time range selector + search
- Main area: responsive 2-column grid (graph left, panels right) → collapses to single column on narrow
- Panels: collapsible sections with clear headers, not stacked cards
- Session explorer: gets its own full-width section (most important panel)
- Optimizer: slide-in side panel (right) instead of bottom drawer
- Remove: redundant stat ribbons, duplicate info across panels

**Interaction patterns:**
- Click session → detail slides in from right
- Select sessions → toolbar appears with "Analyze" action
- Hover states: subtle highlight, no glow
- Loading: skeleton placeholders, not spinners
- Empty states: helpful text ("No sessions found for this period"), not blank

### D. API Additions

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/sessions/{id}` | GET | Full session detail with prompts |
| `/api/analyze-sessions` | POST | Analyze selected sessions by ID |
| `/api/analyze-sessions-stream` | GET (SSE) | Streaming progress for batch analysis |

### E. File Plan

**Modified:**
- `src/agenttop/web/server.py` — new endpoints, remove session limit
- `src/agenttop/web/optimizer/__init__.py` — remove 10-cap, add selective analysis
- `src/agenttop/web/static/css/neon.css` — full redesign (rename to `theme.css`)
- `src/agenttop/web/static/index.html` — restructured layout
- `src/agenttop/web/static/js/panels.js` — session explorer panel
- `src/agenttop/web/static/js/optimizer.js` — side panel instead of drawer
- `src/agenttop/web/static/js/app.js` — updated orchestration
- `src/agenttop/web/static/js/stats.js` — simplified top bar

**New:**
- `src/agenttop/web/static/js/session-explorer.js` — session list + detail + batch analysis
- `src/agenttop/web/static/css/theme.css` — new design system (replaces neon.css)

## Non-Goals

- TUI changes (Phase 2)
- Brew/winget packaging (Phase 3)
- Changing the optimizer's REDUCE/GENERATE logic (just removing the cap and adding selective input)
- Mobile optimization (desktop-first, responsive is fine)
