# agenttop — AI Usage Dashboard & Optimizer

## Project Overview
`agenttop` is an `htop`-style monitoring dashboard for AI coding agents. It collects real usage data from Claude Code, Cursor, Kiro, Copilot, and Codex, then displays it in a neon-cyberpunk web dashboard with an AI-powered optimizer that generates personalized recommendations.

## Architecture

### Layers
```
Collectors → Models → Database → Web Server → Dashboard (SPA)
                                      ↓
                              Optimizer (LLM + fallback)
```

### Key Directories
- `src/agenttop/collectors/` — Per-tool data collectors (claude.py, cursor.py, etc.)
- `src/agenttop/models.py` — Core data models: Event, Session, ToolStats
- `src/agenttop/db.py` — SQLite event store
- `src/agenttop/analysis/` — LLM engine, intent classification, recommendations
- `src/agenttop/web/` — FastAPI server, optimizer, graph builder
- `src/agenttop/web/static/` — SPA frontend (index.html, JS, CSS)
- `src/agenttop/tui/` — Terminal UI (textual-based, alternative to web)

### Data Flow
1. **Collectors** read tool-specific data dirs (`~/.claude/`, `~/.cursor/`, etc.)
2. **Models** normalize into Events and Sessions
3. **Web server** aggregates via `/api/stats`, `/api/sessions`, `/api/models`, `/api/hours`
4. **Optimizer** (`/api/optimize` POST) builds a user profile, tries LLM analysis, falls back to data-driven heuristics
5. **Frontend** renders: force-directed graph, model usage, hourly activity, sessions, cost breakdown, optimizer drawer

## Build & Run
```bash
# Install (editable)
pip install -e ".[dev]"

# Web dashboard
PYTHONPATH=src python -m uvicorn agenttop.web.server:app --port 8420

# TUI
agenttop

# Tests
pytest
```

## Code Style
- Python 3.10+, type hints everywhere
- Ruff for linting (line-length 100, select E/F/I/N/W)
- `# ruff: noqa: E501` at top of files with long strings (optimizer.py)
- Collections: prefer `defaultdict`, `Counter` from `collections`
- Async: FastAPI endpoints, sync collectors
- Frontend: vanilla JS, no frameworks, CSS custom properties for theming

## Key Design Decisions
- **No frameworks on frontend** — vanilla JS + D3 for the graph, keeps it fast and dependency-free
- **LLM-optional optimizer** — works fully offline with data-driven fallback; LLM just adds depth
- **Knowledge base in code** — `KNOWLEDGE_BASE` dict in optimizer.py contains per-tool best practices sourced from official docs
- **Real data only** — optimizer never guesses; every recommendation is backed by actual usage metrics from the profile

## Optimizer Architecture (optimizer.py)
The optimizer is the most complex module:
1. `build_user_profile()` — aggregates sessions into a rich profile (tools, sessions, projects, intents, model usage, per-project details)
2. `format_profile_for_prompt()` — converts profile to markdown for LLM consumption
3. `OPTIMIZER_PROMPT` — instructs LLM to grade, recommend, and identify missing features
4. `_data_driven_fallback()` — heuristic fallback generating: scores, grades, recommendations, developer profile, project insights, workflow assessment
5. `_check_feature_evidence()` — per-feature detection using profile data

Output schema: `{score, developer_profile, grades, recommendations, missing_features, project_insights, workflow, source}`

## Testing
```bash
pytest                    # all tests
pytest tests/ -k test_optimizer  # optimizer tests
```

## Common Tasks
- Adding a new collector: subclass `BaseCollector` in `collectors/`, register in `server.py`
- Adding a tool to knowledge base: add entry to `KNOWLEDGE_BASE` dict in `optimizer.py`
- Adding optimizer output fields: update `OPTIMIZER_PROMPT` JSON schema, `_data_driven_fallback()` return dict, and `optimizer.js` `_renderResults()`
