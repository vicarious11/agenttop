# agenttop

**You're mass-spending on AI coding tools and you have no idea where the money goes.**

agenttop reads your local usage data from Claude Code, Cursor, Kiro, Codex, and Copilot — then an LLM analyzes your actual workflow and tells you exactly what you're doing wrong.

![agenttop optimizer — AI-powered workflow analysis](assets/screenshots/optimizer.png)

### Install

```bash
pip install agenttop
agenttop web
```

That's it. `agenttop web` handles everything:
1. Installs Ollama if missing (brew on macOS, install script on Linux)
2. Starts the Ollama server
3. Pulls the model (~1GB, one-time)
4. Opens the dashboard at `localhost:8420`

It reads `~/.claude/`, `~/.cursor/`, `~/.codex/`, `~/.config/github-copilot/`, and Kiro data dirs — whatever you have installed.

---

### The optimizer finds problems you didn't know you had

This isn't a dashboard that shows you a number and leaves. The optimizer runs your usage data through an LLM and comes back with:

**Anti-patterns you're repeating** — correction spirals where you keep fixing errors instead of starting fresh. Marathon sessions where you hit 100+ messages and the AI starts forgetting your instructions. Exploration loops where you're manually reading files instead of using sub-agents.

**Cost forensics** — not "you spent $X this month" but *which project is burning tokens, which model is overkill for what you're doing, and how much you'd save by switching*.

**Features you're paying for but not using** — CLAUDE.md, custom slash commands, prompt caching, sub-agents. The tools you use have capabilities you've never touched. The optimizer knows which ones would actually help based on your patterns.

**Developer profiling** — maps your workflow style (debug warrior, explorer, builder) and gives you targeted advice instead of generic tips.

![agenttop recommendations — anti-patterns and cost analysis](assets/screenshots/recommendations.png)

---

### Knowledge graph

Every tool, model, project, and feature — connected. See which model eats which project's budget at a glance.

![agenttop knowledge graph — force-directed visualization](assets/screenshots/knowledge-graph.png)

---

### Optimizer setup

`agenttop web` auto-installs Ollama and pulls the model on first run. No manual setup needed.

If you prefer a cloud provider instead:

**Or use a cloud provider:**
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

### Supported tools

| Tool | Data source | What's tracked |
|------|------------|----------------|
| Claude Code | `~/.claude/` | Sessions, tokens, tool calls, costs, models, projects |
| Cursor | `~/.cursor/ai-tracking/` | AI code gen, conversations, AI vs human ratio |
| Kiro | `~/Library/Application Support/Kiro/` | Agent activity |
| Codex | `~/.codex/` | Sessions, token usage |
| Copilot | `~/.config/github-copilot/` | Completions, suggestions |
| Any tool | Local proxy | Token counts, latency, costs |

### Commands

```
agenttop              # TUI dashboard
agenttop web          # web dashboard (localhost:8420)
agenttop stats        # quick summary
agenttop analyze      # workflow analysis
agenttop init         # generate config
agenttop proxy        # API proxy for unsupported tools
```

Flags: `--days 7` (time range), `--provider ollama` (LLM), `--model name` (model), `--port 9000` (port).

### How it works

```
~/.claude/  ~/.cursor/  ~/...Kiro/  ~/.codex/  ~/.config/github-copilot/
     |           |          |          |              |
     v           v          v          v              v
                      Collectors
                          |
                    Event / Session
                          |
                +---------+---------+
                |                   |
          Web Dashboard         TUI Dashboard
          (D3 + FastAPI)        (Textual)
                |
            Optimizer
            (LLM-powered)
```

Collectors read local data dirs. No network calls, no telemetry, no cloud. The optimizer is the only component that calls an LLM (local Ollama by default).

### Proxy

For tools that don't store data locally:

```bash
agenttop proxy
export ANTHROPIC_BASE_URL=http://localhost:9120/anthropic
export OPENAI_BASE_URL=http://localhost:9120/openai
```

### Development

```bash
git clone https://github.com/vicarious11/agenttop
cd agenttop
pip install -e ".[dev]"
pytest
agenttop web
```

### License

Apache 2.0
