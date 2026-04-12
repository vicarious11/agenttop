# agenttop

`htop` for AI coding agents.

```bash
git clone https://github.com/vicarious11/agenttop && cd agenttop && ./setup.sh
./run.sh    # localhost:8420
```

![agenttop dashboard](assets/screenshots/optimizer.png)

Monitors **Claude Code**, **Cursor**, **Kiro**, **Codex**, **Copilot**. Reads the local files they already write (`~/.claude/`, `~/.cursor/`, etc). Read-only. Nothing leaves your machine.

## what it does

- unified dashboard across all your AI coding tools
- every session, every prompt, every token, every dollar — one place
- search sessions by project, sort by cost, view full prompt history
- AI analysis: scores you 0-100 on session hygiene, prompt quality, cost efficiency, cache usage, tool utilization
- cost forensics: spend by project, by model, estimated waste from marathon sessions
- detects anti-patterns: correction spirals, context blowup, repeated prompts, model overkill

## install

```bash
git clone https://github.com/vicarious11/agenttop && cd agenttop && ./setup.sh
```

or `pip install agenttop`

## run

```bash
./run.sh              # web dashboard
.venv/bin/agenttop    # terminal dashboard
agenttop init         # set up LLM for analysis (ollama/anthropic/openai)
```

## data sources

```
~/.claude/projects/**/*.jsonl        exact token counts per message
~/.cursor/ai-tracking/*.db           conversations, models, AI vs human ratio
~/.codex/.codex-global-state.json    prompts, automations
~/.config/github-copilot/            session state
~/Library/.../Kiro/state.vscdb       workspace data
```

## no telemetry

zero. local only. ollama = nothing leaves your machine.

## license

Apache 2.0
