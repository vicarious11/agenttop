# agenttop

**You're mass-spending on AI coding tools and you have no idea where the money goes.**

agenttop reads your local usage data from Claude Code, Cursor, Kiro, Codex, and Copilot — then an LLM analyzes your actual workflow and tells you exactly what you're doing wrong.

![agenttop optimizer — AI-powered workflow analysis](assets/screenshots/optimizer.png)

## Quick start

```bash
git clone https://github.com/vicarious11/agenttop && cd agenttop
./setup.sh
./run.sh        # http://localhost:8420
```

That's it. `setup.sh` handles Python, virtualenv, dependencies, and Ollama. Nothing installed globally.

Or if you prefer pip:
```bash
pip install agenttop
agenttop web
```

---

## System architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Local filesystem                       │
│                                                          │
│  ~/.claude/     ~/.cursor/     ~/Library/.../Kiro/        │
│  ~/.codex/      ~/.config/github-copilot/                │
└────┬───────────────┬──────────────┬──────────────┬───────┘
     │               │              │              │
     ▼               ▼              ▼              ▼
┌─────────────────────────────────────────────────────────┐
│                     Collectors                           │
│                                                          │
│  ClaudeCodeCollector   CursorCollector   KiroCollector   │
│  CopilotCollector      CodexCollector                    │
│                                                          │
│  Each reads tool-specific data dirs and normalizes into  │
│  Events and Sessions (Pydantic models)                   │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
              ┌────────────────────┐
              │   Models layer     │
              │                    │
              │  Event             │
              │  Session           │
              │  ToolStats         │
              │  SessionIntent     │
              └─────────┬──────────┘
                        │
           ┌────────────┼────────────┐
           │                         │
           ▼                         ▼
┌────────────────────┐    ┌────────────────────┐
│   Web dashboard    │    │   TUI dashboard    │
│   (FastAPI + D3)   │    │   (Textual)        │
│                    │    │                    │
│  /api/stats        │    │  StatsBar          │
│  /api/sessions     │    │  TokenFlowChart    │
│  /api/models       │    │  ToolBreakdown     │
│  /api/hours        │    │  SessionsView      │
│  /api/optimize     │    └────────────────────┘
│                    │
│  Static SPA:       │
│  force-directed    │
│  graph, model      │
│  usage, hourly     │
│  activity, cost    │
│  breakdown         │
└─────────┬──────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────┐
│                      Optimizer                            │
│                                                          │
│  ┌─────────────────────┐    ┌──────────────────────┐     │
│  │  Python (determin.) │    │  LLM (intelligent)   │     │
│  │                     │    │                      │     │
│  │  build_user_profile │    │  grades              │     │
│  │  _analyze_prompts   │    │  recommendations     │     │
│  │  _analyze_anti_     │    │  developer_profile   │     │
│  │    patterns         │    │  project_insights    │     │
│  │  _build_cost_       │    │  missing_features    │     │
│  │    forensics        │    │  workflow analysis   │     │
│  └─────────┬───────────┘    └──────────┬───────────┘     │
│            │                           │                 │
│            └─────────┬─────────────────┘                 │
│                      ▼                                   │
│              _merge_results()                            │
│              Final JSON response                         │
└──────────────────────────────────────────────────────────┘
```

### Data flow

```
1. COLLECT   Collectors read local data dirs (no network calls)
                 │
2. NORMALIZE Events + Sessions (Pydantic models with token counts, costs, timestamps)
                 │
3. AGGREGATE /api/stats computes per-tool totals, hourly distributions
                 │
4. ANALYZE   Optimizer builds a user profile from sessions:
                 │
                 ├── Python computes: anti-patterns, cost forensics,
                 │   prompt analysis, context engineering
                 │
                 └── LLM adds: grades, recommendations, developer profile,
                     project insights, missing features
                 │
5. RENDER    Frontend renders: knowledge graph, model usage chart,
             hourly activity, sessions table, optimizer drawer
```

### Optimizer pipeline (detail)

The optimizer is the most complex module. It uses a hybrid approach so that deterministic metrics are always accurate, and the LLM only handles what requires intelligence.

```
Sessions from all collectors
         │
         ▼
┌─────────────────────────────────┐
│ build_user_profile()            │  Aggregates: tools used, session count,
│                                 │  projects, intents, model usage,
│                                 │  per-project details, prompt history
└────────────┬────────────────────┘
             │
    ┌────────┴────────────────────────────────┐
    │                                         │
    ▼                                         ▼
┌──────────────────┐                ┌──────────────────┐
│ Python metrics   │                │ LLM analysis     │
│                  │                │                  │
│ _analyze_prompts │                │ Profile → JSON   │
│   correction     │                │ → OPTIMIZER_     │
│   spirals,       │                │   PROMPT         │
│   repeated       │                │ → get_completion │
│   prompts,       │                │                  │
│   specificity    │                │ Returns:         │
│                  │                │  score (0-100)   │
│ _analyze_anti_   │                │  grades (A-F)    │
│   patterns       │                │  recommendations │
│   severity,      │                │  developer_      │
│   examples,      │                │    profile       │
│   fixes          │                │  missing_        │
│                  │                │    features      │
│ _build_cost_     │                │  project_        │
│   forensics      │                │    insights      │
│   waste by       │                │  workflow        │
│   project/model  │                │                  │
└────────┬─────────┘                └────────┬─────────┘
         │                                   │
         └──────────┬────────────────────────┘
                    ▼
           _merge_results()
           Combines Python metrics + LLM analysis
           into final JSON response
```

---

## What the optimizer finds

This isn't a dashboard that shows you a number and leaves. The optimizer runs your real usage data through an LLM and comes back with:

**Anti-patterns you're repeating** — correction spirals where you keep fixing errors instead of starting fresh. Marathon sessions where you hit 100+ messages and the AI starts forgetting your instructions. Exploration loops where you're manually reading files instead of using sub-agents.

**Cost forensics** — not "you spent $X this month" but *which project is burning tokens, which model is overkill for what you're doing, and how much you'd save by switching*.

**Features you're paying for but not using** — CLAUDE.md, custom slash commands, prompt caching, sub-agents. The tools you use have capabilities you've never touched. The optimizer knows which ones would actually help based on your patterns.

**Developer profiling** — maps your workflow style (debug warrior, explorer, builder) and gives you targeted advice instead of generic tips.

![agenttop recommendations — anti-patterns and cost analysis](assets/screenshots/recommendations.png)

---

## Knowledge graph

Every tool, model, project, and feature — connected. See which model eats which project's budget at a glance.

![agenttop knowledge graph — force-directed visualization](assets/screenshots/knowledge-graph.png)

---

## Supported tools

| Tool | Data source | What's tracked |
|------|------------|----------------|
| Claude Code | `~/.claude/projects/**/*.jsonl` | Sessions, tokens (input/output/cache), tool calls, costs, models, projects |
| Cursor | `~/.cursor/ai-tracking/ai-code-tracking.db` | AI code gen, conversations, AI vs human ratio, commit scoring |
| Kiro | `~/Library/Application Support/Kiro/` | Agent activity via `state.vscdb` |
| Codex | `~/.codex/` | Sessions, token usage, command history |
| Copilot | `~/.copilot/` | Session state files |
| Any tool | Local proxy (`agenttop proxy`) | Token counts, latency, costs |

### How collectors work

Each collector implements the `BaseCollector` interface:

```
BaseCollector (ABC)
  ├── tool_name       → ToolName enum
  ├── is_available()  → does this tool's data dir exist?
  ├── collect_events()    → list[Event]
  ├── collect_sessions()  → list[Session]
  └── get_stats(days)     → ToolStats (tokens, cost, sessions, hourly)
```

Adding a new tool: subclass `BaseCollector` in `collectors/`, register in `server.py`.

---

## How each tool stores data locally

Each AI coding tool stores usage data differently — different formats, locations, and retention policies. This section documents exactly what's on disk and what agenttop reads.

### Claude Code

```
~/.claude/
├── projects/                          # One dir per project (path-encoded name)
│   └── -Users-you-Desktop-myproject/
│       ├── {uuid}.jsonl               # One file per session (main conversation)
│       ├── {uuid}/
│       │   └── subagents/
│       │       └── {uuid}.jsonl       # Subagent session logs
│       └── CLAUDE.md                  # Project memory
├── stats-cache.json                   # Legacy aggregate stats (daily activity, model usage)
├── history.jsonl                      # Legacy prompt history
├── agents/                            # Custom agent definitions (.md)
├── commands/                          # Custom slash commands
├── rules/                             # User rules (.md)
├── skills/                            # Installed skills
└── plans/                             # Saved plans
```

**Primary data: `projects/**/*.jsonl`**

Each JSONL file is one conversation session. Every line is a JSON object with a `type` field:

```json
// type: "user" — your prompt
{
  "type": "user",
  "timestamp": "2026-03-04T06:04:52.131Z",
  "cwd": "/Users/you/Desktop/myproject",
  "sessionId": "06d41b1f-...",
  "message": { "role": "user", "content": "fix the auth bug" },
  "version": "2.1.66",
  "gitBranch": "main"
}

// type: "assistant" — Claude's response with exact token counts
{
  "type": "assistant",
  "timestamp": "2026-03-04T06:04:57.701Z",
  "message": {
    "model": "claude-opus-4-6",
    "usage": {
      "input_tokens": 3,
      "output_tokens": 11,
      "cache_read_input_tokens": 10426,
      "cache_creation_input_tokens": 10797
    },
    "content": [
      { "type": "thinking", "thinking": "..." },
      { "type": "text", "text": "..." },
      { "type": "tool_use", "name": "Edit", "input": { ... } }
    ]
  }
}

// type: "file-history-snapshot" — file state checkpoints
```

**Token accounting:**
- `input_tokens + output_tokens` = billed tokens (what you pay for)
- `cache_read_input_tokens` = served from cache (billed at 10x discount)
- `cache_creation_input_tokens` = new cache entries (billed at ~1.25x)
- agenttop separates these — the old bug was summing cache into the headline, inflating 380x

**Retention:** Claude Code keeps everything forever. Sessions accumulate indefinitely. A heavy user can see `~/.claude/projects/` grow to 1GB+. No automatic cleanup.

**Typical sizes:**
- Single session JSONL: 500KB–3MB (depends on conversation length)
- Total `projects/` dir: 100MB–1GB+ for active users

---

### Cursor

```
~/.cursor/
└── ai-tracking/
    └── ai-code-tracking.db            # SQLite database (~3MB)

~/Library/Application Support/Cursor/  # macOS only
└── User/
    ├── workspaceStorage/              # Per-workspace state (~100MB total)
    │   └── {hash}/
    │       ├── state.vscdb            # SQLite: ItemTable with composer data
    │       └── workspace.json         # Maps hash → project path
    └── globalStorage/
        └── state.vscdb                # Global state with KV timing data (~3GB)
```

**Primary data: `ai-code-tracking.db`**

SQLite database with these tables:

```sql
-- Every AI-generated code fragment (hashed)
CREATE TABLE ai_code_hashes (
    hash TEXT PRIMARY KEY,
    source TEXT NOT NULL,         -- "composer", "tab", "human"
    fileExtension TEXT,
    fileName TEXT,                -- full path → project extraction
    conversationId TEXT,
    model TEXT,                   -- can be NULL for tab completions
    createdAt INTEGER NOT NULL    -- unix ms
);

-- Conversation metadata (often empty — Cursor doesn't always populate this)
CREATE TABLE conversation_summaries (
    conversationId TEXT PRIMARY KEY,
    title TEXT, tldr TEXT, overview TEXT,
    model TEXT, mode TEXT,        -- "agent" or "chat"
    updatedAt INTEGER NOT NULL
);

-- AI vs human code in each commit
CREATE TABLE scored_commits (
    commitHash TEXT, branchName TEXT,
    tabLinesAdded INTEGER, composerLinesAdded INTEGER,
    humanLinesAdded INTEGER,
    scoredAt INTEGER NOT NULL,
    PRIMARY KEY (commitHash, branchName)
);
```

**Token estimation:** Cursor doesn't store real token counts anywhere. agenttop estimates:
- Composer interactions: ~800 tokens (code generation)
- Tab completions: ~150 tokens (inline suggestions)
- Chat-only conversations: ~2000 tokens

**Retention:** Cursor cleans old data aggressively. The `ai_code_hashes` table typically covers only the last 2–4 weeks. Older entries are pruned on Cursor updates or periodically. `workspaceStorage/` dirs are also cleaned when workspaces are removed. The `globalStorage/state.vscdb` can grow very large (3GB+) but Cursor manages its lifecycle.

**Important:** `conversation_summaries` is often empty (0 rows). Cursor doesn't reliably populate this table. Most data comes from `ai_code_hashes`.

---

### Codex (OpenAI)

```
~/.codex/
├── config.toml                        # Model selection (e.g., gpt-5.3-codex)
├── auth.json                          # Authentication
├── models_cache.json                  # Available models cache (~200KB)
├── .codex-global-state.json           # Global state
├── sessions/
│   └── YYYY/MM/DD/
│       └── rollout-{uuid}.jsonl       # Full conversation transcripts
├── archived_sessions/                 # Completed sessions moved here
├── rules/                             # Custom rules
├── skills/                            # Installed skills
└── sqlite/                            # Internal state DB
```

**Session files: `sessions/YYYY/MM/DD/rollout-*.jsonl`**

Each rollout file is one session. Lines are JSON objects with conversation turns. File modification time is used as session timestamp.

**Retention:** Codex keeps session files indefinitely, organized by date. `archived_sessions/` stores completed sessions. No automatic pruning observed. Total dir is typically 30–50MB.

**Token estimation:** Codex doesn't expose token counts in local files. agenttop uses ~600 tokens/message estimate.

---

### Kiro (AWS)

```
~/Library/Application Support/Kiro/    # macOS
├── state.vscdb                        # SQLite: extension state (or in User/globalStorage/)
└── globalStorage/
    └── kiro.kiroagent/                # Agent-specific data
```

**Data source: `state.vscdb`**

VSCode-format SQLite database with an `ItemTable`. Kiro stores agent activity as key-value pairs. agenttop scans for Kiro-related keys to detect session activity.

**Retention:** Follows VSCode's storage lifecycle. Data persists until the extension is uninstalled or workspaces are cleaned.

**Note:** Kiro collector is minimal — it detects presence and activity but doesn't yet extract detailed session/token data (Kiro's local data format is not well documented).

---

### GitHub Copilot

```
~/.copilot/                            # Copilot CLI data (if exists)
├── config                             # User preferences (JSON, no extension)
├── session-state/                     # Active session files
│   └── {session-id}                   # JSON files, one per session
└── agents/
    └── *.agent.md                     # Custom agent definitions
```

**Data source: `session-state/` files**

Each file represents one session. File modification time is used as timestamp.

**Retention:** Session state files persist while sessions are active. Copilot manages cleanup. The directory is typically small.

**Cost:** Copilot is subscription-based ($10–39/month) with no per-token billing. agenttop reports session counts but cost is always $0 per-token (the subscription cost isn't tracked since it's a flat fee).

---

### Retention summary

| Tool | Format | Retention | Typical size | Cleanup behavior |
|------|--------|-----------|-------------|------------------|
| Claude Code | JSONL files | **Forever** — never cleaned | 100MB–1GB+ | Manual only (`rm ~/.claude/projects/...`) |
| Cursor | SQLite DB | **2–4 weeks** — old hashes pruned | 3MB DB, 3GB+ global state | Automatic on updates, workspace removal |
| Codex | JSONL + SQLite | **Forever** — archived, not deleted | 30–50MB | Sessions archived but kept |
| Kiro | SQLite (vscdb) | **VSCode lifecycle** | Small | Cleaned with extension/workspace removal |
| Copilot | JSON files | **Session-scoped** | Small | Cleaned when sessions end |

**Key insight:** Claude Code is the richest data source (exact per-message token counts, model IDs, cache breakdown). Cursor is the trickiest (no real token counts, aggressive cleanup, data split across multiple SQLite DBs). Codex stores full transcripts but no token metadata. Kiro and Copilot have minimal local data.

---

## LLM configuration

`agenttop web` auto-installs Ollama and pulls the model on first run. No manual setup needed.

To use a cloud provider instead:

```bash
# Anthropic
export ANTHROPIC_API_KEY=sk-ant-...
agenttop web --provider anthropic --model claude-haiku-4-5-20251001

# OpenAI
export OPENAI_API_KEY=sk-...
agenttop web --provider openai --model gpt-4o-mini

# OpenRouter
export OPENROUTER_API_KEY=sk-or-...
agenttop web --provider openrouter --model openrouter/google/gemini-2.0-flash-001
```

Run `agenttop init` to generate a config file at `~/.agenttop/config.toml`.

---

## Commands

```
agenttop              # TUI dashboard (terminal)
agenttop web          # Web dashboard (localhost:8420)
agenttop stats        # Quick summary to stdout
agenttop analyze      # Workflow analysis
agenttop init         # Generate ~/.agenttop/config.toml
agenttop proxy        # API proxy for unsupported tools
```

Flags: `--days 7` (time range), `--provider ollama` (LLM), `--model name` (model), `--port 9000` (port).

---

## API proxy

For tools that don't store data locally, run the transparent proxy to capture token usage:

```bash
agenttop proxy
export ANTHROPIC_BASE_URL=http://localhost:9120/anthropic
export OPENAI_BASE_URL=http://localhost:9120/openai
```

The proxy logs every request/response to the local event store. No data leaves your machine.

---

## API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stats?days=7` | GET | Per-tool aggregated stats (tokens, cost, sessions) |
| `/api/sessions?days=7` | GET | Session list with prompts, projects, costs |
| `/api/models` | GET | Token usage breakdown by model |
| `/api/hours` | GET | Hourly token distribution (24h histogram) |
| `/api/optimize` | POST | Run the optimizer (returns full analysis JSON) |
| `/api/graph` | GET | Knowledge graph nodes and edges for D3 |

---

## Development

```bash
git clone https://github.com/vicarious11/agenttop
cd agenttop
./setup.sh --no-ollama
source .venv/bin/activate
pytest
```

### Project structure

```
src/agenttop/
├── cli.py                    # Click CLI (agenttop command)
├── config.py                 # Config loading (~/.agenttop/config.toml)
├── models.py                 # Event, Session, ToolStats, Intent
├── db.py                     # SQLite event store
├── collectors/
│   ├── base.py               # BaseCollector ABC
│   ├── claude.py             # Claude Code (JSONL parser)
│   ├── cursor.py             # Cursor (workspace DB reader)
│   ├── copilot.py            # GitHub Copilot
│   ├── kiro.py               # Kiro
│   └── codex.py              # Codex
├── analysis/
│   ├── engine.py             # LLM completion wrapper (litellm)
│   └── intents.py            # Session intent classification
├── web/
│   ├── server.py             # FastAPI app + API routes
│   ├── optimizer.py          # Hybrid optimizer (Python + LLM)
│   ├── graph_builder.py      # Knowledge graph builder
│   └── static/               # SPA frontend (vanilla JS + D3)
│       ├── index.html
│       ├── css/neon.css
│       └── js/
│           ├── app.js         # Main app loop
│           ├── panels.js      # Model usage, sessions
│           ├── optimizer.js   # Optimizer drawer
│           └── graph.js       # Force-directed graph (D3)
└── tui/
    ├── app.py                # Textual app
    ├── dashboard.py          # Stats bar, charts
    └── sessions.py           # Session browser
```

### Key design decisions

- **No frontend frameworks** — vanilla JS + D3 for the graph. Fast, zero build step.
- **Hybrid optimizer** — Python computes deterministic metrics (always accurate). LLM adds intelligent analysis (grades, recommendations). Neither alone is sufficient.
- **Real data only** — the optimizer never guesses. Every recommendation is backed by actual usage metrics.
- **Local-first** — no network calls except the optional LLM. Collectors read filesystem only.
- **Knowledge base in code** — `KNOWLEDGE_BASE` dict in `optimizer.py` contains per-tool best practices sourced from official docs. The LLM cross-references this against your actual usage.

---

## Privacy

All data stays local. Collectors only read files on your filesystem. The only network call is the optimizer's LLM request (local Ollama by default). No telemetry, no cloud sync, no accounts.

## License

Apache 2.0
