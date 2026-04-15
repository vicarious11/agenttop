<p align="center">
  <img src="assets/logo.png" alt="agenttop" width="120">
</p>

<h1 align="center">agenttop</h1>

<p align="center">
  <b>See where your AI coding tokens and money actually go.</b>
  <br>
  <sub>htop for Claude Code, Cursor, Kiro, Codex, and Copilot.</sub>
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#what-you-see">Screenshots</a> ·
  <a href="#features">Features</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#ai-analysis">AI Analysis</a> ·
  <a href="#architecture">Architecture</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python">
  <img src="https://img.shields.io/github/license/vicarious11/agenttop" alt="License">
  <img src="https://img.shields.io/badge/tools-5%20supported-green" alt="Tools">
  <img src="https://img.shields.io/badge/telemetry-zero-brightgreen" alt="No telemetry">
</p>

---

![agenttop web dashboard](assets/screenshots/optimizer.png)

> Every AI coding tool stores usage data locally — JSONL logs, SQLite databases, workspace state — but none of them show you the full picture. agenttop reads all of it, normalizes it, and gives you a real-time dashboard with AI-powered analysis. 5 tools. One view. Nothing leaves your machine.

---

## Install

```bash
git clone https://github.com/vicarious11/agenttop && cd agenttop && ./setup.sh
```

That's it. Handles Python, venv, deps, everything. Then:

```bash
source .venv/bin/activate
agenttop                # terminal dashboard
agenttop web            # web dashboard at localhost:8420
agenttop stats          # quick CLI summary
agenttop init           # configure LLM for AI analysis
```

Requirements: Python 3.10+. No Docker. No API keys needed. macOS, Linux, Windows.

Keyboard: `d` dashboard · `s` sessions · `e` explorer · `a` analysis · `k` graph · `1-4` time range · `q` quit

## What You See

### Terminal Dashboard

```
All time  17.8M tok  $687 cost  265 sess  5.6K msgs  5 tools  87% cache

COST BY PROJECT                    COST BY MODEL
apex-trading-engine ████████ $284  opus-4-6    ████████████ $412
vaultkeeper         █████    $148  sonnet-4-6  █████        $198
phantom-search      ████      $97  haiku-4-5   ██            $76
neon-ui             ██        $63
dataweave           ██        $51

DAILY COST (30d)                   ACTIVITY BREAKDOWN
▁▃▅▇█▇▅▃▁▂▄▆█▇▅▃▁▂▅▇█▇▅▃▁▃▅▇    coding       ████████  42%
total $687  avg $23/day  peak $45  debugging    ████      21%
                                   testing      ███       15%
TOOLS                              exploration  ██         9%
● Claude Code  180 sess  $469
● Cursor        45 sess  $107     ONE-SHOT RATE
● Kiro          20 sess   $53     87%  ██████████████████░░
● Codex         12 sess   $53     edits that pass first try
● Copilot        8 sess    $5     higher = better prompting
```

Six panels. No plotext. Pure Rich text rendering. All data computed from actual tool calls, not keyword guessing.

### Web Dashboard

Three tabs: **Overview** · **Sessions** · **Analyze**

- **Overview** — force-directed knowledge graph (D3), model usage (input/output/cache), hourly activity, cost breakdown, workflow intelligence
- **Sessions** — full-page browser with Google-style pagination. Search by project or prompt. Sort by cost, time, tokens. Click any session to see complete prompt history
- **Analyze** — select sessions (All / Last 10 / Top Cost), run LLM analysis, get a deep-dive report with score, grades, cost forensics by project and model, anti-patterns, recommendations with estimated savings

Keyboard: `o` overview · `s` sessions · `a` analyze. URL hash routing (`#sessions`, `#analyze`) for deep links.

## Features

### Data Extraction

| Tool | Data Source | What agenttop extracts |
|------|------------|----------------------|
| **Claude Code** | `~/.claude/projects/**/*.jsonl` | Exact per-message token counts (input, output, cache read, cache create). Per-message model ID. **Every tool call name** (Edit, Bash, Read, Grep, Agent, Write — extracted from `tool_use` content blocks). Up to 50 user prompts per session. Project path from `cwd` field. Cost from per-model pricing. |
| **Cursor** | `~/.cursor/ai-tracking/ai-code-tracking.db` | Conversations from SQLite. Source type (tab/composer/chat). AI vs human code ratio from `scored_commits`. Model per code hash. Project resolution via `ide_state.json` workspace mapping. |
| **Kiro** | `~/Library/.../Kiro/User/globalStorage/state.vscdb` | Session data from VS Code state DB. Keys matching `kiro%`, `chat%`, `session%` patterns. Message counts and timestamps. |
| **Codex** | `~/.codex/` | Prompt history from `.codex-global-state.json`. Session files from `sessions/` rollouts. Automation data from SQLite. Config (model, reasoning effort). |
| **Copilot** | `~/.config/github-copilot/session-state/` | Per-session JSON with message content. Model extraction. Custom agent detection. Token estimation from content length. |

All read-only. agenttop never modifies your tool data.

### Activity Classification

Deterministic. No LLM. Classified from **actual tool call data** when available (Claude Code), falls back to prompt keywords for other tools.

| Activity | How it's detected |
|----------|------------------|
| **coding** | Edit, Write, MultiEdit tool calls |
| **debugging** | Bug/error/fix keywords in prompts + Edit/Bash patterns |
| **testing** | Bash calls with pytest/jest/vitest/cargo test |
| **exploration** | Read, Grep, Glob calls without edits |
| **refactoring** | Refactor/rename/extract keywords + Edit patterns |
| **git ops** | Bash calls with git commands |
| **planning** | EnterPlanMode, TaskCreate, Agent tool calls |
| **other** | Everything else |

### One-Shot Success Rate

Percentage of edit turns that pass without retry. Detects `Edit -> correction prompt -> Edit` retry cycles in your prompt history. Higher percentage = better prompting, less wasted tokens.

When `tool_breakdown` is available (Claude Code), uses actual Edit/Write call counts. Falls back to prompt analysis for other tools.

### Cost Analysis

- **Cost by project** — which project burns the most money, with session count
- **Cost by model** — opus vs sonnet vs haiku spend, computed from actual per-model pricing (input/output/cache rates)
- **Daily cost sparkline** — 30-day unicode trend with total, average, and peak
- **Cache hit rate** — from actual `cacheReadInputTokens` vs `inputTokens` in Claude Code data

### Session Data Model

Each session stores:

```python
Session(
    tool_breakdown={"Edit": 5, "Bash": 3, "Read": 12, "Grep": 4},  # actual tool calls
    models_used={"claude-opus-4-6": 8, "claude-sonnet-4-6": 12},    # per-message model
    prompts=["fix the race condition in...", ...],                    # up to 50
    total_tokens=48291,          # exact for Claude, estimated for others
    estimated_cost_usd=12.47,    # per-model pricing
    message_count=23,
    tool_call_count=24,
    # + id, tool, project, start_time, end_time
)
```

## AI Analysis

Optional. Select sessions, run LLM analysis, get a report.

**Three-phase pipeline (Map-Reduce-Generate):**

1. **MAP** — batches selected sessions into a single LLM call with full prompt history. Classifies each: intent, correction spirals, prompt quality, wasted effort. Results cached per session ID — sessions are immutable, never re-analyzed.

2. **REDUCE** — pure Python, no LLM. Deterministic score from 5 dimensions (0-20 points each):

   | Dimension | Source | Formula |
   |-----------|--------|---------|
   | Session hygiene | MAP classifications | `spiral_free_sessions / total x 20` |
   | Prompt quality | MAP classifications | `no_waste_sessions / total x 20` |
   | Cost efficiency | Python cost forensics | `(1 - waste_pct / 100) x 20` |
   | Cache efficiency | Claude model_usage | `cache_hit_rate / 100 x 20` |
   | Tool utilization | Feature detection | `features_used / available x 20` |

3. **GENERATE** — single LLM call with ~2K tokens of pre-computed metrics. LLM writes prose (developer profile, recommendations, project insights). Does NOT compute any numbers — those come from REDUCE.

Score is fully traceable. "Session hygiene: 14/20 — 23/30 sessions had no correction spirals."

**LLM providers:** Ollama (free, local — nothing leaves your machine), Anthropic, OpenAI, OpenRouter.

```bash
agenttop init  # interactive setup wizard
```

## Demo Mode

Safe for recordings and screenshots. Generates realistic fake data — 10 projects, 265 sessions across 5 tools, with handwritten prompts that read like real engineering work.

```bash
agenttop --demo        # terminal with fake data
agenttop web --demo    # web dashboard with fake data
```

Deterministic. Same screenshots every time.

## How It Works

```
~/.claude/  ~/.cursor/  ~/.codex/  ~/.config/github-copilot/  ~/Library/.../Kiro/
     |           |          |              |                        |
     v           v          v              v                        v
  COLLECTORS — parse tool-specific local files
  │  Claude: JSONL → exact tokens, tool names, model per message
  │  Cursor: SQLite → conversations, AI vs human ratio, models
  │  Codex:  JSON + SQLite → prompts, automations, rollouts
  │  Copilot: JSON → session messages, model, agents
  │  Kiro:   SQLite → VS Code state keys
  │
  └──> unified Session model (tool_breakdown, models_used, prompts, tokens, cost)
          │
          ├──> WEB DASHBOARD (FastAPI + D3 + vanilla JS, port 8420)
          │    overview (knowledge graph) | sessions (paginated) | analyze
          │
          ├──> TERMINAL DASHBOARD (Textual + Rich)
          │    dashboard | sessions | explorer | analysis | graph
          │
          └──> OPTIMIZER (Map-Reduce-Generate, optional)
               MAP: batch LLM call, cached per session
               REDUCE: deterministic score 0-100
               GENERATE: prose recommendations
```

## Configuration

Zero config by default. For AI analysis:

```bash
agenttop init
```

or manually:

```toml
# ~/.agenttop/config.toml
[llm]
provider = "ollama"           # ollama | anthropic | openai | openrouter
model = "ollama/gemma3:4b"    # any litellm-compatible model
```

Environment variable overrides: `AGENTTOP_LLM_PROVIDER`, `AGENTTOP_LLM_MODEL`, `ANTHROPIC_API_KEY`.

## No Telemetry

Zero. No data collection. No cloud uploads. No analytics. Everything runs locally. With Ollama, nothing leaves your machine at all.

## License

Apache 2.0

## Contributors

Built with [@AbhilashSri](https://github.com/AbhilashSri) (workflow intelligence, code reviews), [@Mohit]() and [@Akshit]() (testing, UX).
