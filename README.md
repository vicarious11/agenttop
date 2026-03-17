# agenttop

`htop` for AI coding agents. Monitor every token, dollar, and session across Claude Code, Cursor, Kiro, Codex, and Copilot — from a single dashboard.

```
git clone https://github.com/vicarious11/agenttop && cd agenttop
python3 install.py    # one-time: venv, deps, Ollama, model pull
./start               # opens http://localhost:8420
```

Works on **macOS, Linux, and Windows**. Only needs Python 3.10+. No global installs, no Docker, no API keys. Everything runs locally in a virtualenv.

![agenttop optimizer — AI-powered workflow analysis](assets/screenshots/optimizer.png)

---

## Why this exists

You're mass-spending on AI coding tools and you have no idea where the money goes. Every tool stores usage data locally — JSONL files, SQLite databases, workspace state — but none of them show you the full picture. agenttop reads all of it, normalizes it into a unified model, and gives you a real-time dashboard with an AI-powered optimizer that tells you what you're doing wrong.

No telemetry. No cloud uploads. Your data never leaves your machine.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              YOUR MACHINE                                   │
│                                                                             │
│   ~/.claude/           ~/.cursor/          ~/Library/.../Kiro/              │
│   ├── projects/        ├── ai-tracking/    └── User/globalStorage/          │
│   │   └── **/*.jsonl   │   └── ai-code-    │   └── state.vscdb             │
│   ├── statsig/         │       tracking.db │                                │
│   │   └── *.json       ├── ide_state.json  ~/.codex/                       │
│   └── settings.json    └── projects/       ├── .codex-global-state.json    │
│                                            ├── sqlite/codex-dev.db         │
│   ~/.config/github-copilot/                └── config.toml                 │
│   └── session-state/*.json                                                  │
│                                                                             │
│         │                  │               │               │                │
│         ▼                  ▼               ▼               ▼                │
│   ┌─────────────────────────────────────────────────────────────┐           │
│   │                    COLLECTOR LAYER                          │           │
│   │                                                             │           │
│   │  ClaudeCodeCollector  CursorCollector   KiroCollector       │           │
│   │  CopilotCollector     CodexCollector    ProxyCollector      │           │
│   │                                                             │           │
│   │  Each collector implements:                                 │           │
│   │    collect_events()    → list[Event]                        │           │
│   │    collect_sessions()  → list[Session]                      │           │
│   │    get_stats(days)     → ToolStats                          │           │
│   │    get_feature_config()→ dict  (ground-truth detection)     │           │
│   └─────────────────────┬───────────────────────────────────────┘           │
│                         │                                                   │
│                         ▼                                                   │
│   ┌─────────────────────────────────────────────────────────────┐           │
│   │                     MODEL LAYER                             │           │
│   │                                                             │           │
│   │  Event       — tool, event_type, timestamp, tokens, cost    │           │
│   │  Session     — id, tool, project, messages, tokens, cost,   │           │
│   │                prompts, start_time, end_time                │           │
│   │  ToolStats   — sessions, messages, tokens, cost, hourly[]   │           │
│   │  ToolName    — claude_code | cursor | kiro | codex | copilot│           │
│   └─────────────────────┬───────────────────────────────────────┘           │
│                         │                                                   │
│              ┌──────────┴──────────┐                                        │
│              ▼                     ▼                                        │
│   ┌───────────────────┐  ┌──────────────────────────────────┐              │
│   │   WEB DASHBOARD   │  │         TUI DASHBOARD            │              │
│   │   (FastAPI + D3)  │  │         (Textual)                │              │
│   │                   │  │                                   │              │
│   │  /api/stats       │  │  Real-time terminal dashboard    │              │
│   │  /api/sessions    │  │  with session explorer and       │              │
│   │  /api/models      │  │  knowledge graph (ASCII)         │              │
│   │  /api/hours       │  └──────────────────────────────────┘              │
│   │  /api/graph       │                                                    │
│   │  /api/optimize    │                                                    │
│   │  /ws (realtime)   │                                                    │
│   └────────┬──────────┘                                                    │
│            │                                                                │
│            ▼                                                                │
│   ┌──────────────────────────────────────────────────────────┐             │
│   │              OPTIMIZER (Map-Reduce-Generate)                 │             │
│   │                                                           │             │
│   │  ┌── MAP ─────────────┐   ┌── REDUCE ────────────────┐   │             │
│   │  │ Per-session LLM    │   │ Deterministic score       │   │             │
│   │  │ (top 30, cached)   │──▶│ 5 dims × 20 = 0-100     │   │             │
│   │  │ + Python metrics   │   │ + anti_patterns, costs    │   │             │
│   │  └────────────────────┘   └──────────┬───────────────┘   │             │
│   │                                      │                    │             │
│   │  ┌── GENERATE ────────┐              │                    │             │
│   │  │ Single LLM call    │◀─────────────┘                    │             │
│   │  │ ~2K token input    │  ┌────────────────────┐           │             │
│   │  │ Prose: recs,       │──│ Ollama/Anthropic/  │           │             │
│   │  │ profile, insights  │  │ OpenAI/OpenRouter  │           │             │
│   │  └────────────────────┘  └────────────────────┘           │             │
│   │                                                           │             │
│   │  _merge_results() → { score, grades, anti_patterns,       │             │
│   │    cost_forensics, recommendations, developer_profile,    │             │
│   │    project_insights, workflow, feature_detection }         │             │
│   └──────────────────────────────────────────────────────────┘             │
│                                                                             │
│   ┌──────────────────────────────────────────────────────────┐             │
│   │                  FRONTEND (SPA)                           │             │
│   │                                                           │             │
│   │  index.html ─── Vanilla JS, no frameworks                │             │
│   │  ├── graph.js     D3 force-directed knowledge graph      │             │
│   │  ├── panels.js    Model usage, sessions, cost breakdown  │             │
│   │  ├── optimizer.js Optimizer drawer with full analysis     │             │
│   │  ├── stats.js     Real-time stat counters                │             │
│   │  ├── app.js       WebSocket + routing                    │             │
│   │  └── neon.css     Cyberpunk theme (CSS custom properties)│             │
│   └──────────────────────────────────────────────────────────┘             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Sources — What Each Tool Stores Locally

agenttop is a read-only parasite on your AI tools' local data. Here's exactly what it reads, how, and what you get.

### Claude Code (`~/.claude/`)

Claude Code is the richest data source. Every conversation is a JSONL file with per-message token accounting.

```
~/.claude/
├── projects/                          # One subdir per workspace path
│   └── {encoded-path}/
│       ├── *.jsonl                     # Conversation logs (one JSON per line)
│       ├── CLAUDE.md                   # Project memory
│       └── memory/                    # Persistent memory files
├── agents/                            # Custom agent definitions (*.md)
├── commands/                          # Custom slash commands
├── rules/                             # Coding rules (global + project)
├── skills/                            # Skill definitions
├── statsig/                           # Feature gate configs
├── settings.json                      # User settings (hooks, permissions)
└── .claude.json                       # MCP server config
```

**What agenttop extracts:**

| File | Data | Method |
|------|------|--------|
| `projects/**/*.jsonl` | Every message: role, model, `inputTokens`, `outputTokens`, `cacheReadInputTokens`, `cacheCreationInputTokens`, tool calls, timestamps | Line-by-line JSON parse |
| `projects/**/CLAUDE.md` | Project memory existence per project | Path check |
| `agents/*.md` | Custom agent names and count | Directory listing |
| `commands/**/*` | Slash command names (recursive) | `rglob` |
| `rules/` | Global + project rule counts | Split scan |
| `skills/` | Skill definitions (files + directories) | Mixed scan |
| `settings.json` | Hook configuration (pre/post tool use) | JSON parse |
| `.claude.json` or `mcp.json` | MCP server names and count | JSON parse |

**Token accuracy:** Exact. Claude Code writes `inputTokens`, `outputTokens`, `cacheReadInputTokens`, and `cacheCreationInputTokens` per message. No estimation needed.

**Cost model:** Per-model pricing from official rates. Supports Opus 4.6, Sonnet 4.6, Haiku 4.5 with distinct input/output/cache rates.

**Retention:** Indefinite. Claude Code never deletes conversation logs. Data accumulates forever. A heavy user will have 1GB+ in `~/.claude/projects/`.

**Feature detection:** `claude_features.py` runs 10 detection functions (`detect_agents`, `detect_commands`, `detect_rules`, `detect_skills`, `detect_plans`, `detect_tasks`, `detect_hooks`, `detect_project_memory`, `detect_mcp_servers`, `detect_all_features`) to build a ground-truth map of what the user has configured. The optimizer uses this to avoid recommending features you already have.

### Cursor (`~/.cursor/`)

Cursor stores AI interactions in a SQLite database and workspace metadata in JSON.

```
~/.cursor/
├── ai-tracking/
│   └── ai-code-tracking.db            # SQLite: all AI interactions
├── ide_state.json                     # Recently viewed files (relative → absolute path mapping)
├── projects/                          # One dir per workspace (encoded path)
│   └── {encoded-workspace-path}/
│       ├── mcps/                      # MCP configs
│       └── terminals/                 # Terminal state
├── plans/                             # AI-generated plans
├── skills-cursor/                     # Cursor skills
└── mcp.json                           # MCP server configuration
```

**Database schema (`ai-code-tracking.db`):**

```sql
-- Every AI-generated code block (tab completion, composer, chat)
CREATE TABLE ai_code_hashes (
    hash TEXT PRIMARY KEY,
    source TEXT NOT NULL,        -- 'tab', 'composer', 'chat'
    fileExtension TEXT,
    fileName TEXT,               -- relative path (e.g., 'src/main.py')
    requestId TEXT,
    conversationId TEXT,         -- groups into sessions
    timestamp INTEGER,
    createdAt INTEGER NOT NULL,
    model TEXT                   -- 'claude-3.5-sonnet', 'gpt-4o', etc.
);

-- Conversation metadata
CREATE TABLE conversation_summaries (
    conversationId TEXT PRIMARY KEY,
    title TEXT,                  -- AI-generated conversation title
    tldr TEXT,                   -- AI-generated summary
    overview TEXT,
    summaryBullets TEXT,
    model TEXT,
    mode TEXT,                   -- 'composer', 'chat', etc.
    updatedAt INTEGER NOT NULL
);

-- AI vs human code contribution per git commit
CREATE TABLE scored_commits (
    commitHash TEXT NOT NULL,
    branchName TEXT NOT NULL,
    scoredAt INTEGER NOT NULL,
    tabLinesAdded INTEGER,       -- lines from tab completions
    composerLinesAdded INTEGER,  -- lines from composer
    humanLinesAdded INTEGER,     -- lines written by human
    commitMessage TEXT,
    PRIMARY KEY (commitHash, branchName)
);

-- When Cursor started tracking this machine
CREATE TABLE tracking_state (
    key TEXT PRIMARY KEY,        -- 'trackingStartTime'
    value TEXT                   -- JSON: {"timestamp": 1765446866553}
);
```

**Token accuracy:** Estimated. Cursor doesn't expose real token counts. agenttop uses conservative per-source estimates: composer ~800 tokens, tab completion ~150 tokens, chat-only conversation ~2000 tokens.

**Project mapping:** Cursor stores relative file paths (`docs/analysis/rcaissue.md`), not absolute. agenttop resolves these by cross-referencing `ide_state.json` (which maps relative → absolute for recently viewed files) and parsing `~/.cursor/projects/` directory names (which encode workspace paths like `Users-sakshamdutta-Desktop-repo-cody`).

**Retention:** Cursor prunes old data every 2-4 weeks. The `ai-code-tracking.db` stays small (typically <5MB).

**Feature detection:** Reports tracking start date, AI vs human code ratio, table row counts, and DB file size.

### Codex (`~/.codex/`)

OpenAI's Codex CLI stores global state in JSON and automation data in SQLite.

```
~/.codex/
├── .codex-global-state.json           # Electron-style persisted state
│   └── electron.extra.atom-state      # Nested JSON containing:
│       ├── prompt-history             # Array of past prompts
│       └── agent-mode                 # Current mode setting
├── sqlite/
│   └── codex-dev.db                   # Automations, runs, inbox
├── config.toml                        # User configuration
├── models_cache.json                  # Available models list
├── instructions.md                    # Global instructions
└── rollouts/                          # Session rollout files
    └── *.json
```

**What agenttop extracts:**

| Source | Data |
|--------|------|
| `.codex-global-state.json` | Prompt history (full text), agent mode, electron state keys |
| `sqlite/codex-dev.db` | Automations (names, statuses), automation runs (count, last run), inbox items |
| `config.toml` | Model selection, reasoning effort, other settings |
| `models_cache.json` | List of available model names |
| `rollouts/*.json` | Session files with timing and message data |

**Token accuracy:** Estimated at ~600 tokens per interaction (Codex doesn't expose counts).

**Retention:** Codex archives old rollouts but keeps global state and the SQLite DB indefinitely.

### Copilot (`~/.config/github-copilot/`)

GitHub Copilot stores session state as JSON files.

```
~/.config/github-copilot/           # or ~/.copilot/
├── session-state/                    # or history-session-state/
│   └── *.json                        # Per-session JSON files
├── config                            # JSON config with user preferences
└── agents/
    └── *.agent.md                    # Custom agent definitions
```

**Session JSON structure:** Each file may contain `messages` or `conversation` arrays with per-message `content` (string or block array), plus `model` and `settings` fields.

**Token accuracy:** Content-based estimation. agenttop parses message content, divides character count by 4 for a token estimate, with a floor of 500 tokens per session.

**Cost model:** Returns `$0.00` — Copilot is subscription-based, not per-token.

**Retention:** Session state files are ephemeral and may be cleared between IDE restarts.

**Feature detection:** Reports config file settings and custom agent definitions.

### Kiro (`~/Library/Application Support/Kiro/`)

AWS Kiro stores workspace state in a VS Code-compatible SQLite database.

```
~/Library/Application Support/Kiro/
└── User/
    └── globalStorage/
        └── state.vscdb               # SQLite: ItemTable with kiro/* keys
```

**What agenttop reads:** Queries the `ItemTable` for keys matching `kiro%`, `chat%`, `conversation%`, and `session%` patterns. Values are JSON blobs containing session IDs, message counts, token counts, and timestamps.

**Token accuracy:** Depends on what Kiro stores in state. Falls back to message-count estimation when token fields are absent.

**Retention:** Persists as long as the VS Code-style storage exists.

---

## Optimizer Pipeline — Map-Reduce-Generate

The optimizer uses a three-phase architecture that eliminates truncation, produces deterministic scores, and scales to any number of sessions.

```
                    collect_sessions()    get_stats()    get_feature_config()
                         │                    │                  │
                         ▼                    ▼                  ▼
                  ┌─────────────────────────────────────────────────┐
                  │           build_user_profile()                  │
                  │                                                 │
                  │  Aggregates ALL data into a structured profile: │
                  │  • active_tools, total_tokens, total_cost       │
                  │  • projects, model_usage, intent_distribution   │
                  │  • feature_detection (ground truth)             │
                  └───────────────────┬─────────────────────────────┘
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         ▼                            ▼                            ▼
  ┌──────────────────┐    ┌────────────────────┐    ┌────────────────────┐
  │  PHASE 1: MAP    │    │  Python Metrics    │    │  Cost Forensics    │
  │  (per-session    │    │  (deterministic)   │    │  (deterministic)   │
  │   LLM calls)     │    │                    │    │                    │
  │                  │    │  _analyze_prompts  │    │  _build_cost_      │
  │  Top 30 sessions │    │  _analyze_anti_    │    │    forensics       │
  │  by cost, max 10 │    │    patterns        │    │                    │
  │  new per run,    │    │                    │    │  waste by project  │
  │  concurrent,     │    │  length dist,      │    │  waste by model    │
  │  FULL prompts,   │    │                    │    │                    │
  │  cached by ID    │    │                    │    │                    │
  │                  │    │  slash cmds,       │    │  waste rate %      │
  │  Per session:    │    │  specificity       │    │                    │
  │  • intent        │    └────────┬───────────┘    └────────┬───────────┘
  │  • had_spiral    │             │                         │
  │  • prompt_quality│             │                         │
  │  • wasted_effort │             │                         │
  │  • actionable_fix│             │                         │
  └────────┬─────────┘             │                         │
           │                       │                         │
           └───────────────────────┼─────────────────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │   PHASE 2: REDUCE            │
                    │   (pure Python, deterministic)│
                    │                              │
                    │   _compute_deterministic_    │
                    │     score()                   │
                    │                              │
                    │   5 dimensions × 20 pts:     │
                    │   1. Session hygiene (spirals)│
                    │   2. Prompt quality (waste)   │
                    │   3. Cost efficiency          │
                    │   4. Cache efficiency         │
                    │   5. Tool utilization         │
                    │                              │
                    │   Score: 0-100 (traceable)   │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │   PHASE 3: GENERATE          │
                    │   (single LLM call)          │
                    │                              │
                    │   Input: ~2K tokens of       │
                    │   pre-computed metrics        │
                    │                              │
                    │   LLM writes prose about     │
                    │   facts — does NOT compute   │
                    │   any numbers                │
                    │                              │
                    │   Output:                    │
                    │   • developer_profile        │
                    │   • recommendations          │
                    │   • project_insights         │
                    │   • missing_features         │
                    │   • workflow assessment       │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │   _merge_results()           │
                    │                              │
                    │   Deterministic score/grades  │
                    │   + Python metrics            │
                    │   + LLM prose                 │
                    │   → final JSON response       │
                    └──────────────────────────────┘
```

**Key design principles:**
- **Zero truncation** — MAP phase sends FULL prompts per session (not 8 truncated ones)
- **Deterministic scores** — score is computed from LLM-classified session ratios, not hallucinated by the LLM
- **Batch-write caching** — session cache written once after all MAP analyses complete (not per-session), stored at `~/.agenttop/session_cache.json`
- **Progressive enrichment** — max 10 new sessions analyzed per run (sorted by cost). Cached sessions from previous runs still contribute. Score stabilizes after ~3 runs
- **Concurrent MAP** — cloud providers (Anthropic, OpenAI, OpenRouter) use 4 parallel workers; Ollama uses 1 (configurable via `map_concurrency` in config)
- **Graceful degradation** — if LLM is unavailable, Python metrics + fallback scoring still render
- **Score confidence** — output includes `confidence: "full"/"partial"` and `sessions_analyzed` count so the user knows sample size

### Knowledge Base Architecture

The optimizer includes a curated `KNOWLEDGE_BASE` dict with per-tool entries, each containing:

- **features** — name, description, impact, detection hint, **setup guide** (step-by-step), **prompt tips** (good/bad examples)
- **anti_patterns** — common mistakes per tool
- **cost_benchmarks** — typical daily/monthly spend (Claude Code)

This is hardcoded and always available offline. The `kb_refresh.py` module augments it daily:

```
Hardcoded KNOWLEDGE_BASE (always works)
         │
         ├── Startup: check ~/.agenttop/knowledge_base.json cache
         │   ├── Cache fresh (<24h)? → merge cached updates
         │   └── Cache stale/missing? → fetch from GitHub repos
         │       ├── Success? → save cache + merge
         │       └── No internet? → use hardcoded (fine)
         │
         └── Every 24h: repeat refresh cycle (background, non-blocking)
```

**What the LLM sees:** For each project in your data, the LLM receives the tool's KB features + your actual usage metrics. It produces per-project `recommended_model` (constrained to real models per tool) and `recommended_tool` (which IDE fits best for each project type).

**Model constraints:** The prompt explicitly lists valid models per tool (e.g., Claude Code: `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5`). The LLM cannot invent model names.

**Feature detection pipeline:** Each collector's `get_feature_config()` returns ground-truth data about what the user has configured (e.g., "16 agents, 40 commands, 13 rules, 65 skills, 2 MCP servers"). This flows through `server.py` → `optimizer.analyze()` → `build_user_profile()` → `_build_llm_input()` → LLM prompt. The LLM cross-references this with session patterns to produce accurate "missing features" recommendations — it won't tell you to set up CLAUDE.md if you already have one.

---

## Knowledge Graph

The force-directed graph connects every tool, model, project, and feature. Edge thickness = token flow. Node size = activity.

```
        You ──────── Claude Code ──────── Opus 4.6
         │               │ ╲               │
         │               │  ╲──── Sonnet 4.6 ────── project-A
         │               │                          project-B
         │               │
         ├────── Cursor ──────── Composer (943 uses)
         │          │ ╲
         │          │  ╲──── Tab Complete (254 uses)
         │          │
         ├────── Kiro
         │
         └────── Codex
```

Built by `GraphBuilder` in `graph_builder.py`. Data sources:
- **Tool → Model edges:** Claude uses `get_model_usage()` with exact token counts. Cursor extracts model names from `ai_code_hashes`.
- **Tool → Project edges:** `collect_sessions()` returns sessions with `project` field. Multiple tools working on the same project get cross-connected.
- **Cursor-specific nodes:** Source types (tab, composer, chat), AI vs human code ratio from `scored_commits`.

![agenttop knowledge graph — force-directed visualization](assets/screenshots/knowledge-graph.png)

---

## API Endpoints

| Endpoint | Method | Description | Query Params |
|----------|--------|-------------|--------------|
| `/api/stats` | GET | Aggregated stats from all available collectors | `days` (0=all) |
| `/api/sessions` | GET | Recent sessions across all tools (max 200) | `days` (default 7) |
| `/api/models` | GET | Claude model usage breakdown (input/output/cache tokens) | — |
| `/api/hours` | GET | Hourly token distribution merged from all tools | `days` (0=all) |
| `/api/graph` | GET | D3-compatible knowledge graph (nodes + edges) | `days` (0=all) |
| `/api/optimize` | POST | Full optimizer analysis (Python metrics + LLM) | Body: `{"days": 0}` |
| `/api/optimize-stream` | GET | SSE streaming: progress events during MAP, then final result. Returns cached result instantly if fresh | `days` (0=all) |
| `/api/kb-refresh` | POST | Manually trigger knowledge base refresh from official docs | — |
| `/ws` | WebSocket | Real-time stat updates (send days preference as text) | — |

**Optimizer caching:** The first `/api/optimize` call runs at server startup in the background. Subsequent calls return the cached result for up to 5 minutes. Session analyses are cached permanently at `~/.agenttop/session_cache.json` — only new sessions trigger LLM calls. The SSE endpoint (`/api/optimize-stream`) also checks the cache first, so reopening the optimizer drawer is instant within the TTL window.

**Knowledge base refresh:** The `KNOWLEDGE_BASE` (per-tool features, setup guides, anti-patterns, prompt tips) is hardcoded and always works offline. On startup and every 24 hours, a background task fetches updates from official GitHub repos (README changes, new features) and merges them into the in-memory KB. Cache stored at `~/.agenttop/knowledge_base.json`. Manual trigger: `POST /api/kb-refresh`.

---

## Project Structure

```
agenttop/
├── src/agenttop/
│   ├── collectors/              # Data collectors (one per tool)
│   │   ├── base.py              # BaseCollector ABC (53 lines)
│   │   ├── claude.py            # Claude Code — JSONL parser (782 lines)
│   │   ├── claude_features.py   # Feature detection functions (161 lines)
│   │   ├── cursor.py            # Cursor — SQLite + workspace resolution (498 lines)
│   │   ├── codex.py             # Codex — global state + SQLite + TOML (394 lines)
│   │   ├── copilot.py           # Copilot — session JSON parser (199 lines)
│   │   ├── kiro.py              # Kiro — VS Code state DB (196 lines)
│   │   └── proxy.py             # Transparent API proxy collector (188 lines)
│   ├── analysis/                # Analysis engine
│   │   ├── engine.py            # Multi-provider LLM client via litellm (159 lines)
│   │   ├── intent.py            # Session intent classification
│   │   ├── recommend.py         # Recommendation generation
│   │   └── workflow.py          # Workflow analysis
│   ├── web/                     # Web dashboard
│   │   ├── server.py            # FastAPI server + API endpoints + KB refresh
│   │   ├── optimizer.py         # Hybrid optimizer engine + KNOWLEDGE_BASE
│   │   ├── kb_refresh.py        # Background KB refresh from official docs
│   │   ├── graph_builder.py     # D3 knowledge graph builder (447 lines)
│   │   └── static/              # Frontend SPA
│   │       ├── index.html       # Single page shell
│   │       ├── css/neon.css     # Cyberpunk theme
│   │       └── js/
│   │           ├── app.js       # WebSocket + routing
│   │           ├── graph.js     # D3 force-directed graph
│   │           ├── panels.js    # Model usage, sessions, costs
│   │           ├── optimizer.js # Optimizer drawer
│   │           └── stats.js     # Real-time counters
│   ├── tui/                     # Terminal UI (Textual)
│   │   ├── app.py               # Main TUI application
│   │   ├── dashboard.py         # Dashboard screen
│   │   ├── sessions.py          # Session explorer
│   │   ├── knowledge_graph.py   # ASCII knowledge graph
│   │   ├── analysis.py          # Analysis panel
│   │   └── suggestions.py       # Suggestion panel
│   ├── models.py                # Pydantic models (110 lines)
│   ├── config.py                # Config management + TOML (160 lines)
│   ├── db.py                    # SQLite event store
│   ├── cli.py                   # Click CLI entry point
│   └── formatting.py            # Output formatting utils
├── tests/
│   ├── test_collectors.py       # Collector unit tests
│   ├── test_claude_features.py  # Feature detection tests (43 tests)
│   ├── test_collector_features.py # All collectors' get_feature_config() (30 tests)
│   ├── test_optimizer.py        # Optimizer unit tests
│   └── ...
├── install.py                   # Cross-platform setup (Windows/macOS/Linux)
├── start                        # Generated launcher (created by install.py)
├── pyproject.toml               # Project metadata + dependencies
└── CLAUDE.md                    # Project instructions for AI assistants
```

**Line count by subsystem:**

| Subsystem | Lines | Description |
|-----------|-------|-------------|
| Collectors | 2,283 | Data extraction from 5 tools + proxy |
| Optimizer | 1,089 | Hybrid Python + LLM analysis engine |
| Graph builder | 447 | D3-compatible knowledge graph |
| Web server | 280 | FastAPI + WebSocket + API endpoints |
| LLM engine | 159 | Multi-provider client (Ollama/Anthropic/OpenAI/OpenRouter) |
| Models | 110 | Pydantic data models |
| Config | 160 | TOML config + env var overrides |
| **Total backend** | **4,528** | |

---

## The Optimizer — What It Actually Does

### Scoring Methodology (Deterministic, 0-100)

The score is computed from real data ratios — never hallucinated by the LLM. Five dimensions, each 0-20 points:

| Dimension | Source | How It's Calculated |
|-----------|--------|---------------------|
| **Session Hygiene** (0-20) | MAP phase LLM classifications | `sessions_without_spirals / total_analyzed × 20` |
| **Prompt Quality** (0-20) | MAP phase LLM classifications | `sessions_without_wasted_effort / total_analyzed × 20` |
| **Cost Efficiency** (0-20) | Python cost forensics | `(1 - waste_pct / 100) × 20` |
| **Cache Efficiency** (0-20) | Claude model_usage data | `cache_hit_rate / 100 × 20` |
| **Tool Utilization** (0-20) | Feature detection ground truth | `features_configured / features_available × 20` |

Every score traces to specific data. Example: "Session hygiene: 14/20 — 23/30 analyzed sessions had no correction spirals."

Letter grades: A = 85-100%, B = 65-84%, C = 45-64%, D = 0-44% of dimension max.

**Fallback:** When no LLM session analyses are available, dimensions 1-2 fall back to heuristic counting (session message length, prompt specificity score).

### Anti-Pattern Detection (Python, deterministic)

The optimizer scans your sessions for these patterns:

**Correction Spirals** — Detected by the MAP phase: each session's full prompt sequence is sent to the LLM, which identifies sessions where the user was repeatedly correcting, redirecting, or fighting the AI. More accurate than keyword matching because the LLM reads the actual conversation flow.

**Marathon Sessions** — Sessions with 100+ messages. After ~50 messages, context degrades — the AI starts forgetting earlier instructions, repeating itself, or contradicting its own code. agenttop counts these and estimates wasted tokens.

**No Context Management** — Sessions with 50+ messages that never used `/compact` or `/clear`. The context grows unbounded, degrading response quality and increasing cost per message.

**Repeated Prompts** — Prompts repeated 3+ times across sessions. These are automation candidates — they should be CLAUDE.md rules, custom commands, or skills instead of manual re-typing.

### Cost Forensics (Python, deterministic)

- **Per-project cost breakdown** — which project is burning the most money
- **Per-model cost breakdown** — which model is overkill for what you're doing
- **Waste estimation** — tokens spent in correction spirals + marathon session degradation
- **Waste rate** — percentage of total spend that's estimated waste

### Prompt Intelligence (Python, deterministic)

- **Length distribution** — commands (<20 chars), short (20-100), detailed (100-500), rich (500+)
- **Specificity score** — percentage of prompts that include file paths, function names, or technical detail
- **Slash command usage** — frequency of `/compact`, `/clear`, `/model`, etc.

### LLM Analysis — GENERATE Phase (requires Ollama or cloud provider)

A single LLM call receives pre-computed metrics (~2K tokens, not the full profile dump) and returns prose:

- **Developer profile** — title, bio, traits, AI personality type
- **Recommendations** — 3-7 specific, actionable, prioritized by impact, with estimated savings
- **Missing features** — cross-referenced against `feature_detection` ground truth
- **Project insights** — per-project analysis with type classification and model recommendations
- **Workflow assessment** — current vs optimized workflow vision

The LLM does NOT compute scores or grades — those are pre-computed and passed as facts.

### Session Cache & Performance

Per-session LLM analyses are cached at `~/.agenttop/session_cache.json` (compact JSON, batch-written once per run). Sessions are immutable — once analyzed, they're cached forever and never re-analyzed.

**Timing by scenario:**

| Scenario | Time | Why |
|----------|------|-----|
| Ollama, warm cache (all sessions cached) | ~20s | Profile + GENERATE only |
| Ollama, cold cache (10 new sessions) | ~55-65s | 10 × 5s MAP + GENERATE |
| Cloud provider (concurrency=4), cold | ~25-35s | 10/4 batches × 5s + GENERATE |
| Second click (any provider, within 5 min) | Instant | SSE cache hit |

**Performance optimizations:**
- **Collector cache priming** — sessions collected first, priming the 300s internal cache so `get_stats()` and `get_model_usage()` don't re-parse JSONL files
- **MAP session cap** — max 10 new sessions per run (top by cost). Remaining uncached sessions analyzed on subsequent runs (progressive enrichment)
- **Concurrent MAP** — `ThreadPoolExecutor` with 1 worker for Ollama, 4 for cloud (configurable via `map_concurrency` in config.toml)
- **Batch cache writes** — session cache written once after all MAP analyses complete, not per-session (eliminates 10-30 disk writes)
- **LLM timeouts** — MAP calls: 30s, GENERATE call: 60s
- **SSE cache check** — `/api/optimize-stream` returns cached result immediately if fresh, skipping the full pipeline

![agenttop recommendations — anti-patterns and cost analysis](assets/screenshots/recommendations.png)

---

## Configuration

Default: zero config. Ollama + gemma3:4b runs locally, no API keys needed.

To customize, create `~/.agenttop/config.toml`:

```toml
[llm]
provider = "ollama"              # ollama | anthropic | openai | openrouter
model = "ollama/gemma3:4b"       # any litellm-compatible model
base_url = "http://localhost:11434"
max_budget_per_day = 1.0         # USD spending cap
map_concurrency = 0              # 0 = auto (1 for Ollama, 4 for cloud)

[proxy]
enabled = false
port = 9120
```

**Environment variable overrides** (take precedence over config file):

```bash
AGENTTOP_LLM_PROVIDER=anthropic
AGENTTOP_LLM_MODEL=claude-haiku-4-5-20251001
AGENTTOP_LLM_BASE_URL=https://api.anthropic.com
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Docker (Isolated Sandbox)

Run agenttop in a container — your AI tool data is mounted read-only, nothing is modified on the host.

```bash
# One command
docker compose up -d        # builds + runs, opens http://localhost:8420

# Or manually
docker build -t agenttop .
docker run -d --name agenttop \
  -p 8420:8420 \
  -v ~/.claude:/data/.claude:ro \
  -v ~/.cursor:/data/.cursor:ro \
  -v agenttop-data:/data/.agenttop \
  agenttop
```

**With cloud LLM (no Ollama in container):**

```bash
docker run -d --name agenttop \
  -p 8420:8420 \
  -v ~/.claude:/data/.claude:ro \
  -e AGENTTOP_LLM_PROVIDER=anthropic \
  -e AGENTTOP_LLM_MODEL=claude-haiku-4-5-20251001 \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  agenttop
```

**Environment variables for Docker:**

| Variable | Default | Purpose |
|----------|---------|---------|
| `CLAUDE_DIR` | `/data/.claude` | Path to Claude Code data inside container |
| `CURSOR_DIR` | `/data/.cursor` | Path to Cursor data inside container |
| `KIRO_DIR` | `/data/.kiro` | Path to Kiro data inside container |
| `AGENTTOP_DIR` | `/data/.agenttop` | Persistent config + optimizer cache |

### Performance Overhead

| Metric | Native | Docker | Overhead |
|--------|--------|--------|----------|
| Image size | — | ~330 MB | One-time pull |
| Memory (idle) | ~80 MB | ~250 MB | +170 MB (Python + pip packages in separate layer) |
| Memory (optimizing) | ~150 MB | ~320 MB | Same +170 MB baseline |
| CPU (idle) | <1% | <1% | Negligible |
| CPU (MAP phase) | 100% 1 core | 100% 1 core | Negligible |
| JSONL parsing | ~5s | ~5-6s | +10-20% (volume mount I/O vs native fs) |
| LLM calls | — | — | Zero (network, not disk) |
| Startup | ~2s | ~3s | +1s container init |

**Bottom line:** ~170 MB extra memory, ~10-20% slower on JSONL file parsing (Docker volume mount overhead), everything else identical. LLM calls go over the network regardless so Docker adds zero overhead there. The optimizer cache (`session_cache.json`) persists in a Docker volume across restarts.

**Ollama inside Docker:** Not included by default (adds 2GB+ to image). Use a cloud provider, or run Ollama on the host and point to it:

```bash
docker run -d --name agenttop \
  -p 8420:8420 \
  -v ~/.claude:/data/.claude:ro \
  -e AGENTTOP_LLM_BASE_URL=http://host.docker.internal:11434 \
  agenttop
```

---

## Commands

```
agenttop              # TUI dashboard (terminal)
agenttop web          # Web dashboard with optimizer (localhost:8420)
agenttop stats        # Quick CLI summary
agenttop analyze      # Workflow analysis (CLI)
agenttop init         # Generate ~/.agenttop/config.toml
agenttop proxy        # API proxy for unsupported tools
```

`--days 7` to filter by time range. `--provider` / `--model` to override LLM. `--port` to change port.

---

## Adding a New Collector

1. Create `src/agenttop/collectors/yourtool.py`
2. Subclass `BaseCollector`:

```python
class YourToolCollector(BaseCollector):
    @property
    def tool_name(self) -> ToolName:
        return ToolName.YOUR_TOOL  # add to ToolName enum first

    def is_available(self) -> bool:
        return self._data_path.exists()

    def collect_events(self) -> list[Event]: ...
    def collect_sessions(self) -> list[Session]: ...
    def get_stats(self, days: int = 0) -> ToolStats: ...

    def get_feature_config(self) -> dict[str, Any]:
        # Return ground-truth feature detection
        return {"feature_x": True, "agent_count": 5}
```

3. Register in `web/server.py` `_init()`:

```python
_collectors = [
    ...
    ("Your Tool", YourToolCollector()),
]
```

4. Add to `KNOWLEDGE_BASE` in `optimizer.py` for feature recommendations
5. Add tests in `tests/`

---

## Development

```bash
git clone https://github.com/vicarious11/agenttop
cd agenttop
python3 install.py --no-ollama    # skip Ollama for dev
source .venv/bin/activate
pytest                    # 211 tests
ruff check src/           # lint
```

**Key test files:**
- `tests/test_collectors.py` — collector unit tests with mock filesystems
- `tests/test_claude_features.py` — 43 tests for feature detection functions
- `tests/test_collector_features.py` — 30 tests for all collectors' `get_feature_config()`
- `tests/test_optimizer.py` — optimizer anti-patterns, cost forensics, prompt analysis

---

## Feedback & Troubleshooting

**Score seems wrong?** The score is deterministic — computed from LLM-classified session ratios. Check `~/.agenttop/session_cache.json` to see how individual sessions were classified. Delete the file to force re-analysis. Note: on the first few runs, the score has `confidence: "partial"` because only 10 new sessions are analyzed per run. After ~3 runs, all 30 top sessions are cached and the score stabilizes to `confidence: "full"`.

**First run is slow?** The MAP phase analyzes up to 10 uncached sessions per run (~5s each on gemma3:4b). Cold cache on Ollama takes ~60s; cloud providers with 4x concurrency take ~25-35s. Subsequent runs only process new sessions. The second click within 5 minutes is instant (cached).

**LLM timeouts?** MAP calls timeout at 30s each, GENERATE at 60s. The server allows 180s total. If you're hitting timeouts with local Ollama, try a smaller model or switch to a cloud provider in `~/.agenttop/config.toml`.

**Feature detection inaccurate?** Each collector's `get_feature_config()` returns ground-truth data. If the optimizer recommends a feature you already have, check the feature detection output in the API response's `feature_detection` field.

**Report issues:** [github.com/vicarious11/agenttop/issues](https://github.com/vicarious11/agenttop/issues)

---

## License

Apache 2.0
