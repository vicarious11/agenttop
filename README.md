# agenttop

[![PyPI](https://img.shields.io/pypi/v/agenttop)](https://pypi.org/project/agenttop/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)

**htop for AI coding agents** — zero-config monitoring + AI-powered optimizer for Claude Code, Cursor, Kiro, Codex, and Copilot.

<!-- TODO: Add screenshot of web dashboard here -->
<!-- ![agenttop web dashboard](assets/screenshots/dashboard.png) -->

## Why agenttop?

Every AI coding tool tracks its own usage in its own format. agenttop reads them all, shows you the full picture, and tells you what to fix.

| Feature | **agenttop** | ccusage | Tokscale | Agent Stats | Toktrack |
|---------|:-----------:|:-------:|:--------:|:-----------:|:--------:|
| Multi-tool support | **5 tools** | 2 | 10 | 3 | 4 |
| AI-powered optimizer | **Yes** | No | No | No | No |
| Anti-pattern detection | **Yes** | No | No | No | No |
| Cost forensics | **Yes** | No | No | Basic | No |
| Knowledge graph | **Yes** | No | No | No | No |
| Prompt intelligence | **Yes** | No | No | No | No |
| TUI + Web dashboard | **Both** | CLI | CLI+Web | Web | CLI |
| Zero-config | **Yes** | Yes | Yes | No | Yes |
| Privacy-first (local) | **Yes** | Yes | Yes | No | Yes |

**No other tool has an LLM-powered optimizer.** agenttop doesn't just show you numbers — it grades your workflow, detects anti-patterns, finds features you're missing, and gives you specific recommendations backed by your actual usage data.

## Quick Start

```bash
pip install agenttop
agenttop web
```

That's it. Open `http://localhost:8420` and see your usage across all tools — no API keys, no config, no sign-up.

The dashboard works immediately with your local data. The AI-powered optimizer is optional (see below).

## AI-Powered Optimizer

The optimizer analyzes your usage patterns and generates personalized recommendations. It detects:

- **Anti-patterns** — repeated failed tool calls, overly long sessions, exploration loops
- **Cost forensics** — which projects and models burn the most tokens and why
- **Prompt intelligence** — classifies your prompts (debugging, greenfield, refactoring) and spots inefficiencies
- **Feature gaps** — identifies tool features you're not using (CLAUDE.md, custom slash commands, etc.)
- **Developer profiling** — maps your workflow style and suggests improvements

### Configure a provider

The optimizer needs an LLM. Pick one:

**Anthropic** (default — just set the env var):
```bash
export ANTHROPIC_API_KEY=sk-ant-...
agenttop web
```

**Ollama** (free, local, no API key):
```bash
brew install ollama && ollama pull llama3.2 && ollama serve
agenttop web --provider ollama
```

**OpenAI:**
```bash
export OPENAI_API_KEY=sk-...
agenttop web --provider openai --model gpt-4o-mini
```

**OpenRouter:**
```bash
export OPENROUTER_API_KEY=sk-or-...
agenttop web --provider openrouter --model openrouter/google/gemini-2.0-flash-001
```

Or configure via `~/.agenttop/config.toml` — run `agenttop init` to generate it.

You can also set env vars: `AGENTTOP_LLM_PROVIDER`, `AGENTTOP_LLM_MODEL`, `AGENTTOP_LLM_BASE_URL`.

## Commands

| Command | Description |
|---------|-------------|
| `agenttop` | Launch interactive TUI dashboard |
| `agenttop web` | Launch web dashboard at `localhost:8420` |
| `agenttop web --provider ollama` | Web dashboard with Ollama optimizer |
| `agenttop web --port 9000` | Web dashboard on custom port |
| `agenttop stats` | Quick stats summary (non-interactive) |
| `agenttop analyze` | Run workflow analysis |
| `agenttop proxy` | Start local API proxy on port 9120 |
| `agenttop init` | Create config at `~/.agenttop/config.toml` |

## Supported Tools

| Tool | Data Source | What's Tracked |
|------|-----------|----------------|
| Claude Code | `~/.claude/` | Messages, sessions, tool calls, costs, project memory |
| Cursor | `~/.cursor/ai-tracking/` | AI code generation, conversations, AI vs human ratio |
| Kiro | `~/Library/Application Support/Kiro/` | Agent activity |
| Codex | `~/.codex/` | Sessions, token usage |
| Copilot | `~/.config/github-copilot/` | Completions, suggestions |
| Any tool | Local proxy | Token counts, latency, costs |

## How It Works

```
  ~/.claude/  ~/.cursor/  ~/...Kiro/  ~/.codex/  ~/.config/github-copilot/
       │           │          │          │              │
       └─────────┐ │ ┌────────┘          │    ┌────────┘
                 ▼ ▼ ▼                   ▼    ▼
              ┌─────────────────────────────────┐
              │         Collectors               │
              │  (claude, cursor, kiro, codex,   │
              │   copilot, proxy)                │
              └──────────────┬──────────────────┘
                             ▼
              ┌──────────────────────────────────┐
              │     Models (Event, Session)       │
              └──────────────┬──────────────────┘
                             ▼
                ┌────────────┴────────────┐
                ▼                         ▼
   ┌────────────────────┐   ┌─────────────────────┐
   │   Web Dashboard    │   │    TUI Dashboard     │
   │  (FastAPI + D3)    │   │    (Textual)         │
   └────────┬───────────┘   └─────────────────────┘
            ▼
   ┌────────────────────┐
   │    Optimizer        │
   │  (LLM + fallback)  │
   └────────────────────┘
```

## Why not just check my billing page?

Your billing page is a credit card statement. agenttop is a financial advisor.

The billing page tells you what you spent. agenttop tells you *why* — which projects drain tokens, which prompts waste cycles, which features would cut your costs in half, and what anti-patterns are silently inflating your usage.

## Using the Proxy

For tools that don't store data locally, use the built-in proxy:

```bash
agenttop proxy --port 9120
```

Then point your tool at the proxy:

```bash
export ANTHROPIC_BASE_URL=http://localhost:9120/anthropic
export OPENAI_BASE_URL=http://localhost:9120/openai
```

## Keyboard Shortcuts (TUI)

| Key | Action |
|-----|--------|
| `d` | Dashboard view |
| `s` | Sessions view |
| `a` | Analysis view |
| `r` | Recommendations view |
| `q` | Quit |
| `?` | Help |

## Development

```bash
git clone https://github.com/vicarious11/agenttop
cd agenttop
pip install -e ".[dev]"
pytest

# Web dashboard
agenttop web

# TUI
agenttop
```

## Adding a New Collector

1. Create `src/agenttop/collectors/your_tool.py`
2. Subclass `BaseCollector` and implement:
   - `tool_name` — return a `ToolName` enum value
   - `is_available()` — check if the tool's data exists
   - `collect_events()` — parse events from local data
   - `collect_sessions()` — aggregate into sessions
   - `get_stats()` — return dashboard stats
3. Register in `tui/app.py` and `web/server.py`

## License

Apache 2.0
