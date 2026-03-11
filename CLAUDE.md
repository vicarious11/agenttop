# agenttop — AI Usage Dashboard & Optimizer

## Project Overview
`agenttop` is an `htop`-style monitoring dashboard for AI coding agents. It collects real usage data from Claude Code, Cursor, Kiro, Copilot, and Codex, then displays it in a neon-cyberpunk web dashboard with an AI-powered optimizer that generates personalized recommendations.

## Architecture

### Layers
```
Collectors → Models → Database → Web Server → Dashboard (SPA)
                                      ↓
                              Optimizer (Python metrics + LLM)
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
4. **Optimizer** (`/api/optimize` POST) builds a user profile, computes deterministic metrics, sends structured JSON to LLM for intelligent analysis
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
- **LLM-required optimizer** — setup guarantees a working LLM (Ollama auto-installed/pulled with `gemma3:4b` by default, or cloud provider verified). Python computes deterministic metrics; LLM adds intelligent analysis. Default model chosen for reliable structured JSON output and litellm compatibility (no thinking mode issues)
- **Knowledge base in code** — `KNOWLEDGE_BASE` dict in optimizer.py contains per-tool best practices sourced from official docs
- **Real data only** — optimizer never guesses; every recommendation is backed by actual usage metrics from the profile

## Optimizer Architecture (optimizer.py)
The optimizer is the most complex module. It uses a hybrid approach:

**Python-computed (deterministic, always accurate):**
1. `build_user_profile()` — aggregates sessions into a rich profile (tools, sessions, projects, intents, model usage, per-project details)
2. `_analyze_prompts()` — NLP-lite prompt analysis (correction spirals, repeated prompts, slash commands, specificity)
3. `_analyze_anti_patterns()` — detects anti-patterns with severity, examples, and fixes
4. `_build_cost_forensics()` — cost analysis with waste estimation by project and model

**LLM-powered (intelligent analysis):**
5. `_build_llm_input()` — converts profile + metrics into structured JSON for the LLM (not prose)
6. `OPTIMIZER_PROMPT` — instructs LLM to grade, recommend, and identify missing features
7. `_merge_results()` — combines Python metrics + LLM analysis into final response

Output schema: `{anti_patterns, cost_forensics, prompt_analysis, context_engineering, session_details, profile_summary, score, developer_profile, grades, recommendations, missing_features, project_insights, workflow, source}`

## Testing
```bash
pytest                    # all tests
pytest tests/ -k test_optimizer  # optimizer tests
```

## Common Tasks
- Adding a new collector: subclass `BaseCollector` in `collectors/`, register in `server.py`
- Adding a tool to knowledge base: add entry to `KNOWLEDGE_BASE` dict in `optimizer.py`
- Adding optimizer output fields: update `OPTIMIZER_PROMPT` JSON schema, `_merge_results()` in optimizer.py, and `optimizer.js` `_renderResults()`
