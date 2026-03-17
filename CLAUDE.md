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

## Optimizer Architecture (optimizer.py) — Map-Reduce-Generate
The optimizer uses a three-phase architecture for scalable, accurate analysis:

**Phase 1 — MAP (per-session LLM calls, cached, concurrent):**
- Top 30 sessions by cost, max 10 new (uncached) per run (progressive enrichment)
- Each call classifies: intent, spirals, prompt quality, outcome, wasted effort
- Results cached by session ID in `~/.agenttop/session_cache.json` (never re-analyzed)
- Concurrent: 1 worker for Ollama, 4 for cloud (configurable via `map_concurrency` in config)
- Batch cache write: single disk write after all MAP analyses complete (not per-session)
- LLM timeout: 30s per MAP call. Cold run: ~55s Ollama, ~25s cloud
- Functions: `_analyze_single_session()`, `_analyze_sessions_map()`, `_get_map_concurrency()`

**Phase 2 — REDUCE (pure Python, deterministic):**
- Aggregates per-session LLM outputs into deterministic score (0-100)
- 5 dimensions × 20 points: session hygiene, prompt quality, cost efficiency, cache efficiency, tool utilization
- Session hygiene and prompt quality use LLM classifications (spiral-free ratio, wasted-effort ratio)
- Cost/cache/tool dimensions use Python-computed metrics (unchanged)
- Functions: `_compute_deterministic_score()`, `_analyze_prompts()`, `_analyze_anti_patterns()`, `_build_cost_forensics()`

**Phase 3 — GENERATE (single LLM call, small input):**
- Input: pre-computed metrics + session observations (~2K tokens, not full profile dump)
- Output: developer profile, recommendations, project insights, workflow assessment
- LLM writes prose about pre-computed facts — does NOT compute any numbers
- Functions: `_get_llm_analysis()` with `SYNTHESIS_PROMPT`

**Merge:** `_merge_results()` outputs the same JSON shape the frontend expects

Output schema: `{anti_patterns, cost_forensics, prompt_analysis, context_engineering, session_details, profile_summary, score, grades, developer_profile, recommendations, missing_features, project_insights, workflow, feature_detection, source}`

**Performance architecture:**
- Collector cache TTL: 300s (matches server-level cache). Sessions collected first to prime cache; `get_stats()`/`get_model_usage()` hit cached data
- SSE endpoint (`/api/optimize-stream`) returns cached result instantly if within 5-min TTL
- `get_completion()` accepts `timeout` param: 30s for MAP, 60s for GENERATE
- `LLMConfig.map_concurrency`: 0=auto (1 Ollama, 4 cloud), or explicit override
- Score includes `confidence: "full"/"partial"` and `sessions_analyzed` count

## Testing
```bash
pytest                    # all tests
pytest tests/ -k test_optimizer  # optimizer tests
```

## Common Tasks
- Adding a new collector: subclass `BaseCollector` in `collectors/`, register in `server.py`
- Adding a tool to knowledge base: add entry to `KNOWLEDGE_BASE` dict in `optimizer.py`
- Adding optimizer output fields: update `SYNTHESIS_PROMPT` JSON schema, `_merge_results()` in optimizer.py, and `optimizer.js` `_renderResults()`
- Adding session analysis fields: update `SESSION_ANALYSIS_PROMPT` in optimizer.py and `_analyze_single_session()` field extraction
