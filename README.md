# agenttop

`htop` for AI coding agents. See where your tokens and money actually go.

![agenttop web dashboard](assets/screenshots/optimizer.png)

## The problem

You use Claude Code, Cursor, Copilot — maybe all three. You're spending $500+/month and have zero visibility. Each tool buries usage data in local files nobody reads. You don't know which sessions waste money, which model is overkill, or if you're even getting better at prompting.

## The fix

```bash
git clone https://github.com/vicarious11/agenttop && cd agenttop && ./setup.sh
./run.sh
# open localhost:8420
```

That's it. Reads your local AI tool data. Shows everything in one dashboard. Nothing leaves your machine.

## What you get

**One dashboard for all your AI tools** — Claude Code, Cursor, Kiro, Codex, Copilot. Total tokens, total cost, session history, model usage, hourly patterns. All in one place.

**Session-level analysis** — Browse every session. Search by project. Sort by cost. Click any session to see the full prompt history. Select sessions and run AI analysis to find correction spirals, wasted tokens, and bad prompting patterns.

**A score (0-100)** — Deterministic. Computed from 5 dimensions: session hygiene, prompt quality, cost efficiency, cache hit rate, tool utilization. Not vibes — actual data ratios.

**Cost forensics** — Which project burned the most money. Which model is overkill. How much you wasted in marathon sessions where context degraded. Dollar amounts, not percentages.

**Recommendations that reference your data** — "Session X cost $31 and had 3 correction spirals. Use /compact after 50 messages." Not generic tips.

## Install

```bash
# from source (recommended)
git clone https://github.com/vicarious11/agenttop && cd agenttop && ./setup.sh

# or pip
pip install agenttop
```

## Run

```bash
./run.sh              # web dashboard at localhost:8420
.venv/bin/agenttop    # terminal dashboard
agenttop init         # configure LLM for AI analysis
```

## How it works

Reads local files your tools already create. Read-only. No API keys needed. No Docker. No cloud.

```
~/.claude/projects/**/*.jsonl     → Claude Code sessions, tokens, costs
~/.cursor/ai-tracking/*.db        → Cursor conversations, models, code stats
~/.codex/.codex-global-state.json → Codex prompts, automations
~/.config/github-copilot/         → Copilot session state
~/Library/.../Kiro/state.vscdb    → Kiro workspace data
                |
                v
        agenttop (localhost:8420)
                |
                v
        dashboard + AI analysis (optional, local Ollama or cloud LLM)
```

## No telemetry

Zero. Your data stays on your machine. If you use Ollama for analysis, nothing leaves your laptop at all.

## License

Apache 2.0
