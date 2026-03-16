# ruff: noqa: E501
"""AI Usage Optimizer — LLM-powered workflow recommendations.

Architecture:
  1. Python computes deterministic metrics (anti-patterns, cost forensics,
     prompt analysis, context engineering, session details)
  2. These go BOTH to the LLM (as structured JSON) AND directly into the response
  3. LLM adds intelligence: grades, recommendations, developer_profile,
     project_insights, workflow, missing_features
  4. Final response merges Python metrics + LLM analysis
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from typing import Any

from agenttop.analysis.engine import get_completion
from agenttop.config import Config
from agenttop.models import Session

# ---------------------------------------------------------------------------
# Knowledge base: sourced from official docs (March 2026) for each tool.
# The LLM uses this to identify features the user isn't leveraging.
# ---------------------------------------------------------------------------

KNOWLEDGE_BASE = {
    "claude_code": {
        "display_name": "Claude Code",
        "features": [
            {
                "name": "CLAUDE.md project memory",
                "description": "Place CLAUDE.md at project root with coding style, build commands, architecture notes. Loaded every session. Use @path/to/file to import inline. Keep under 500 lines. Use CLAUDE.local.md for personal gitignored overrides.",
                "impact": "Saves ~500 tokens/session of repeated context. Improves code consistency.",
                "detection_hint": "Check if projects have CLAUDE.md files",
                "setup_guide": "1. Create CLAUDE.md at project root\n2. Add sections: ## Build Commands, ## Architecture, ## Code Style\n3. Keep under 500 lines — agent ignores overlong files\n4. For personal overrides, create CLAUDE.local.md (gitignored)\n5. Import shared configs: @path/to/shared-rules.md",
                "prompt_tips": "GOOD: 'Refactor auth module following the patterns in CLAUDE.md'\nBAD: 'Fix the code' (no context, agent wastes tokens rediscovering project conventions)\nTIP: Reference CLAUDE.md sections explicitly so the agent knows which rules apply",
            },
            {
                "name": "Sub-agents for parallel research",
                "description": "Define in .claude/agents/*.md with name, tools, model. Spawn explore agents for codebase search, plan agents for architecture. Each runs in separate context — doesn't bloat main conversation.",
                "impact": "Reduces main context pollution. Enables parallel investigation.",
                "detection_hint": "High tool_call_count relative to messages suggests manual exploration that could be delegated",
                "setup_guide": "1. Create .claude/agents/ directory\n2. Add agent files like explore.md, plan.md, review.md\n3. Each file needs --- frontmatter with: name, description, tools list\n4. Spawn with: 'Use the explore agent to find all auth-related files'\n5. Agents run in separate context — main conversation stays clean",
                "prompt_tips": "GOOD: 'Use the explore agent to find where rate limiting is implemented'\nBAD: 'Find all files related to rate limiting' (runs in main context, pollutes it)\nTIP: Delegate research to subagents, use main context only for decisions and implementation",
            },
            {
                "name": "Model selection strategy",
                "description": "Use /model to switch mid-session. Opus for complex architecture, Sonnet for general coding (default), Haiku for simple subagent tasks. Extended thinking on by default (31,999 tokens). Reduce with MAX_THINKING_TOKENS=8000 for simpler tasks.",
                "impact": "Sonnet is 5x cheaper than Opus with similar quality for most tasks.",
                "detection_hint": "Check model_usage for diversity",
                "setup_guide": "1. Default model is Sonnet (best cost/quality for coding)\n2. Switch mid-session: /model claude-opus-4-6 (for architecture decisions)\n3. For subagents, specify model in agent .md frontmatter\n4. Reduce thinking budget: export MAX_THINKING_TOKENS=8000\n5. Check current model: look at status bar or run /model",
                "prompt_tips": "GOOD: Switch to Opus BEFORE asking complex architecture questions\nBAD: Using Opus for simple file edits or formatting\nTIP: Sonnet handles 90% of coding tasks. Save Opus for system design, complex refactoring, multi-file architecture",
            },
            {
                "name": "Prompt caching optimization",
                "description": "System prompt + CLAUDE.md + tool definitions are automatically cached. Cache reads cost 90% less. Avoid cache breakers: adding MCP tools mid-session, switching models. Use /context to check context usage.",
                "impact": "Up to 80% savings on input tokens.",
                "detection_hint": "Check cacheReadInputTokens ratio",
                "setup_guide": "1. Prompt caching is automatic — no setup needed\n2. Check cache stats: /context shows cache hit rates\n3. Avoid cache breakers: don't add/remove MCP servers mid-session\n4. Don't switch models frequently — each switch invalidates cache\n5. For heavy MCP users: ENABLE_TOOL_SEARCH=auto:5 defers loading",
                "prompt_tips": "GOOD: Keep sessions focused on one task (cache stays warm)\nBAD: Switching between unrelated tasks without /clear (cache thrashes)\nTIP: Cache reads cost 90% less than cache writes. Stable sessions = massive savings",
            },
            {
                "name": "Session hygiene with /clear and /compact",
                "description": "/clear between unrelated tasks (single most important habit). /compact <focus> for manual compaction: '/compact Focus on API changes'. Double-tap Esc for checkpoint restoration. --continue to resume last session.",
                "impact": "Prevents context pollution. Reduces token waste from stale context.",
                "detection_hint": "Long sessions (>50 messages) suggest lack of /clear usage",
                "setup_guide": "1. Use /clear between unrelated tasks (most impactful habit)\n2. Use /compact <focus> to summarize context: '/compact Focus on API changes'\n3. Double-tap Esc to restore from checkpoint\n4. Use --continue to resume your last session\n5. Watch for sessions >50 messages — time to /clear or /compact",
                "prompt_tips": "GOOD: '/clear' then 'Now let's work on the payment module'\nBAD: 'Also while you're at it, fix the auth bug too' (kitchen sink session)\nTIP: One task per session. If you catch yourself saying 'also', it's time for /clear",
            },
            {
                "name": "Skills and slash commands",
                "description": "Create .claude/commands/*.md for repetitive workflows. Define with --- frontmatter (name, description, tools). Invoke with /skill-name. Unlike CLAUDE.md, skills load on-demand only when relevant.",
                "impact": "Reduces CLAUDE.md bloat. Reusable workflows.",
                "detection_hint": "Repetitive prompt patterns suggest skill candidates",
                "setup_guide": "1. Create .claude/commands/ directory\n2. Add .md files with --- frontmatter (name, description)\n3. Example: review.md with 'Review this PR for security issues'\n4. Invoke with /review in any session\n5. Skills load on-demand — don't bloat every session like CLAUDE.md",
                "prompt_tips": "GOOD: Create a /deploy skill for your deployment checklist\nBAD: Putting deployment steps in CLAUDE.md (loads every session)\nTIP: If you type the same instructions 3+ times, it should be a skill",
            },
            {
                "name": "Hooks for automation",
                "description": "Configure in .claude/settings.json. Types: command, http, prompt (Haiku yes/no), agent (multi-turn). Events: PostToolUse, PreToolUse, SessionStart, etc. Example: auto-format on Edit/Write. Exit code 2 blocks action with feedback.",
                "impact": "Deterministic tasks (lint, format, test) handled without AI tokens.",
                "detection_hint": "Tool calls for formatting/linting suggest hook candidates",
                "setup_guide": "1. Edit .claude/settings.json, add 'hooks' section\n2. Event types: PreToolUse, PostToolUse, SessionStart, Stop\n3. Hook types: command (run shell), http, prompt (Haiku y/n)\n4. Example: auto-format on file write: {event: 'PostToolUse', tools: ['Write','Edit'], command: 'prettier --write $FILE'}\n5. Exit code 2 from hook blocks the action with feedback",
                "prompt_tips": "GOOD: Use hooks for lint/format/test — deterministic, no AI needed\nBAD: Asking Claude to 'run prettier on every file you edit'\nTIP: Every hook saves AI tokens. If a task is deterministic, hook it",
            },
            {
                "name": "MCP server management",
                "description": "Each MCP server adds tool definitions consuming context even when idle. Use /context to check. Prefer CLI tools (gh, aws) over MCP when possible. ENABLE_TOOL_SEARCH=auto:5 defers loading until needed.",
                "impact": "Reduces baseline context size. Cheaper per message.",
                "detection_hint": "High input tokens relative to output may indicate context bloat",
                "setup_guide": "1. Check loaded MCP servers: /context\n2. Remove unused servers from .claude/settings.json\n3. Prefer CLI tools (gh, aws, docker) over MCP equivalents\n4. Set ENABLE_TOOL_SEARCH=auto:5 to defer MCP loading\n5. Each idle MCP server costs ~500-2000 tokens per message",
                "prompt_tips": "GOOD: Use 'gh pr create' instead of MCP GitHub server\nBAD: Loading 10 MCP servers when you only use 2\nTIP: Audit your MCP servers monthly. Remove what you don't use",
            },
        ],
        "anti_patterns": [
            "Kitchen sink sessions: mixing unrelated tasks without /clear",
            "Correction spirals: correcting 3+ times instead of /clear + better prompt",
            "Over-specified CLAUDE.md (>500 lines): agent ignores critical rules",
            "Not using subagents for exploration (manual file-by-file investigation)",
            "Running all tasks on Opus when Sonnet handles them fine",
        ],
        "cost_benchmarks": {
            "typical_daily": "$6/dev/day",
            "90th_percentile": "$12/dev/day",
            "monthly_sonnet": "$100-200/dev/month",
        },
    },
    "cursor": {
        "display_name": "Cursor",
        "features": [
            {
                "name": ".cursor/rules/*.mdc files (replaces .cursorrules)",
                "description": "Modular rules in .cursor/rules/ with YAML frontmatter. Types: alwaysApply (every chat), fileMatch (glob-triggered), auto (agent decides from description), manual (@rule-name). Keep each under 500 lines. Use @file-reference for patterns.",
                "impact": "Scoped rules = less context waste. Modular = easier maintenance.",
                "detection_hint": "Check if user has .cursorrules (legacy) vs .cursor/rules/ (current)",
                "setup_guide": "1. Create .cursor/rules/ directory in your project\n2. Add .mdc files with YAML frontmatter\n3. Types: alwaysApply, fileMatch (glob), auto, manual\n4. Example: api-rules.mdc with 'fileMatch: src/api/**/*.ts'\n5. Migrate from .cursorrules: split into modular .mdc files",
                "prompt_tips": "GOOD: 'Follow the API patterns from our cursor rules'\nBAD: 'Use REST best practices' (generic, agent has no project context)\nTIP: Write rules for YOUR project's patterns, not generic best practices",
            },
            {
                "name": "Four modes: Agent, Ask, Plan, Debug",
                "description": "Agent (Cmd+.): autonomous multi-file. Ask: read-only exploration. Plan: creates detailed plan before execution. Debug: hypothesis generation + log instrumentation.",
                "impact": "Plan mode prevents expensive rework. Ask mode is cheaper for exploration.",
                "detection_hint": "If user's sessions show exploration patterns, they may not be using Ask/Plan modes",
                "setup_guide": "1. Agent mode (Cmd+.): autonomous multi-file changes\n2. Ask mode: read-only, cheaper, great for exploration\n3. Plan mode: generates plan before executing — use for complex tasks\n4. Debug mode: hypothesis-driven debugging with log instrumentation\n5. Switch modes from the dropdown in the chat input",
                "prompt_tips": "GOOD: Use Plan mode for 'Refactor the auth system to use OAuth'\nBAD: Using Agent mode for 'What does this function do?' (Ask mode is cheaper)\nTIP: Plan first, then Agent. Never Agent directly for complex multi-file changes",
            },
            {
                "name": "Background / Cloud agents",
                "description": "Run tasks asynchronously in isolated environments at cursor.com/agent. Best for documentation, large refactors, test writing.",
                "impact": "Parallel task execution without blocking main workflow.",
                "detection_hint": "Long-running sessions may benefit from background delegation",
                "setup_guide": "1. Go to cursor.com/agent\n2. Connect your GitHub repo\n3. Assign tasks like 'Write tests for the payment module'\n4. Agent runs in isolated environment, creates PR when done\n5. Best for: docs, large refactors, test generation",
                "prompt_tips": "GOOD: 'Write comprehensive tests for src/services/' (clear scope)\nBAD: 'Improve the codebase' (too vague for background agent)\nTIP: Background agents work best with clear, scoped tasks that don't need interactive feedback",
            },
            {
                "name": "@-mentions for targeted context",
                "description": "@file, @folder, @codebase (semantic search), @web, @docs, @git. Use @codebase to leverage indexed codebase instead of manual file hunting.",
                "impact": "Precise context = better responses. Avoids loading irrelevant files.",
                "detection_hint": "General",
                "setup_guide": "1. @file — include specific file as context\n2. @folder — include directory contents\n3. @codebase — semantic search across indexed codebase\n4. @web — search the web for documentation\n5. @docs — reference Cursor's built-in docs\n6. @git — reference git history and diffs",
                "prompt_tips": "GOOD: '@codebase how is authentication implemented here?'\nBAD: 'How is auth implemented?' (agent searches blindly)\nTIP: @codebase is your best friend. Use it instead of manually hunting files",
            },
            {
                "name": "Notepads for reusable context",
                "description": "Store coding standards, API patterns, review checklists as reusable snippets. Team-shareable for consistency.",
                "impact": "Eliminates repeated instructions across conversations.",
                "detection_hint": "Repetitive prompts across sessions suggest notepad candidates",
                "setup_guide": "1. Open Command Palette > 'Create Notepad'\n2. Write reusable context: coding standards, API patterns, review checklists\n3. Reference in chat: @notepad-name\n4. Share with team via .cursor/notepads/ directory\n5. Unlike rules, notepads are opt-in per conversation",
                "prompt_tips": "GOOD: Create a 'code-review' notepad with your team's checklist\nBAD: Pasting the same review checklist in every conversation\nTIP: If you copy-paste the same instructions across sessions, make it a notepad",
            },
        ],
        "anti_patterns": [
            "Single monolithic .cursorrules instead of modular .mdc files",
            "Not scoping rules with globs — everything loads into every context",
            "Not using Plan mode before complex multi-file Agent changes",
            "Ignoring Notepads — repeating same instructions across conversations",
            "Using Agent mode for exploration (Ask mode is cheaper/safer)",
        ],
    },
    "copilot": {
        "display_name": "GitHub Copilot",
        "features": [
            {
                "name": "Copilot Coding Agent (assign to issues)",
                "description": "Assign @copilot to GitHub Issues — creates PR autonomously. Self-reviews with Code Review. Runs security scans. Pushes to copilot/ branches only.",
                "impact": "Automate routine PRs. Free up developer time for complex work.",
                "detection_hint": "General",
                "setup_guide": "1. Enable Copilot in repo settings > Features > Copilot\n2. Create a well-structured GitHub Issue with acceptance criteria\n3. Assign @copilot to the issue\n4. Copilot creates a PR on copilot/ branch\n5. Review the PR — Copilot self-reviews with Code Review",
                "prompt_tips": "GOOD: Issue: 'Add rate limiting to POST /api/users — max 10 req/min per IP, return 429'\nBAD: Issue: 'Fix the API' (too vague, agent won't know what to do)\nTIP: Write issues like you're briefing a junior dev — specific acceptance criteria",
            },
            {
                "name": "copilot-setup-steps.yml",
                "description": "Pre-install dependencies in .github/workflows/copilot-setup-steps.yml so agent can build/test immediately instead of discovering by trial-and-error.",
                "impact": "Reduces wasted Actions minutes. Faster agent execution.",
                "detection_hint": "General",
                "setup_guide": "1. Create .github/workflows/copilot-setup-steps.yml\n2. Add steps to install dependencies: npm ci, pip install, etc.\n3. Include build steps so agent can verify changes compile\n4. Add test commands so agent can run tests\n5. This runs BEFORE Copilot starts working — saves Actions minutes",
                "prompt_tips": "N/A (configuration file, not prompt-driven)",
            },
            {
                "name": "Custom instructions (.github/copilot-instructions.md)",
                "description": "Repository-level + path-specific instructions (.github/instructions/*.instructions.md with applyTo globs). Custom agents in .github/agents/*.md.",
                "impact": "Agent has project context. Better code quality.",
                "detection_hint": "General",
                "setup_guide": "1. Create .github/copilot-instructions.md for repo-wide instructions\n2. For path-specific rules: .github/instructions/*.instructions.md with applyTo globs\n3. For custom agents: .github/agents/*.md with specialized behaviors\n4. Keep instructions concise — Copilot has limited context\n5. Include: tech stack, coding style, testing requirements",
                "prompt_tips": "GOOD: Reference your custom agents: '@agent-name review this PR'\nBAD: Explaining your entire codebase in every chat\nTIP: Instructions are your project's memory. Keep them updated",
            },
        ],
        "anti_patterns": [
            "Vague issues without acceptance criteria for coding agent",
            "Not setting up copilot-setup-steps.yml — agent wastes time",
            "Missing custom instructions — Copilot has no project context",
        ],
    },
    "kiro": {
        "display_name": "Kiro",
        "features": [
            {
                "name": "Specs-driven development",
                "description": "Three-part specs in .kiro/specs/<feature>/: requirements.md (EARS notation), design.md (data flow, interfaces), tasks.md (auto-generated). Describe feature -> Kiro generates all three -> review -> execute.",
                "impact": "Front-loads planning. Reduces rework iterations significantly.",
                "detection_hint": "General",
                "setup_guide": "1. Open Kiro and describe your feature in natural language\n2. Kiro generates .kiro/specs/<feature>/requirements.md (EARS notation)\n3. Review requirements, then Kiro generates design.md (interfaces, data flow)\n4. Kiro auto-generates tasks.md from the design\n5. Execute tasks one by one — Kiro tracks progress",
                "prompt_tips": "GOOD: 'Build a user notification system that supports email, SMS, and in-app'\nBAD: 'Add notifications' (too vague for spec generation)\nTIP: The more specific your initial description, the better the generated specs. Include constraints, scale, and edge cases",
            },
            {
                "name": "Steering files with inclusion modes",
                "description": "In .kiro/steering/: always (every interaction), fileMatch (glob-triggered), auto (agent decides from description), manual (#name invocation). Auto-generates product.md, tech.md, structure.md.",
                "impact": "Scoped context = less waste. fileMatch/auto avoid loading irrelevant steering.",
                "detection_hint": "General",
                "setup_guide": "1. Kiro auto-generates .kiro/steering/product.md, tech.md, structure.md\n2. Add custom steering files in .kiro/steering/\n3. Use inclusion modes: always, fileMatch (glob), auto (AI decides), manual (#name)\n4. Example: api-conventions.md with 'fileMatch: src/api/**'\n5. Keep each file focused — don't dump everything in 'always'",
                "prompt_tips": "GOOD: Reference steering: '#api-conventions for this endpoint'\nBAD: Putting all conventions in 'always' mode (loads every interaction)\nTIP: Use fileMatch for most rules. Only truly universal rules should be 'always'",
            },
            {
                "name": "Hooks for event-driven automation",
                "description": "Trigger on file save/create/commit. Auto-update tests, refresh README, security scan. Subagent support for parallel execution.",
                "impact": "Deterministic tasks without AI token consumption.",
                "detection_hint": "General",
                "setup_guide": "1. Configure hooks in .kiro/hooks/ directory\n2. Trigger events: file save, file create, git commit\n3. Example: auto-run tests on save, refresh README on commit\n4. Supports subagent execution for parallel tasks\n5. Hooks are deterministic — no AI tokens consumed",
                "prompt_tips": "GOOD: Hook that runs 'npm test' on every file save in src/\nBAD: Asking Kiro to 'run tests after every change'\nTIP: Hooks handle the routine. Let AI focus on the creative work",
            },
        ],
        "anti_patterns": [
            "Skipping specs — jumping to agentic chat loses structured planning benefit",
            "Monolithic steering — use fileMatch and auto instead of always for everything",
            "Ignoring spec drift — specs must stay in sync with code changes",
        ],
    },
    "codex": {
        "display_name": "OpenAI Codex",
        "features": [
            {
                "name": "Profiles for model/mode switching",
                "description": "Define profiles in ~/.codex/config.toml: [profiles.deep-review] with model, reasoning_effort, approval_policy. Switch with --profile. Use 'fast' profile for routine, 'deep-review' for complex.",
                "impact": "Right model for right task. Huge cost savings on routine work.",
                "detection_hint": "General",
                "setup_guide": "1. Edit ~/.codex/config.toml\n2. Add profile sections: [profiles.fast], [profiles.deep-review]\n3. Each profile sets: model, reasoning_effort, approval_policy\n4. Switch with: codex --profile fast\n5. Example: fast profile uses o4-mini, deep-review uses o3 with high reasoning",
                "prompt_tips": "GOOD: 'codex --profile deep-review' for architecture decisions\nBAD: Using the default profile for everything\nTIP: Create at least 2 profiles: fast (routine) and deep (complex). Switch based on task",
            },
            {
                "name": "AGENTS.md instruction hierarchy",
                "description": "Global (~/.codex/AGENTS.md) -> project root (./AGENTS.md) -> per-directory. AGENTS.override.md supersedes at same level. Max 32 KiB combined (configurable).",
                "impact": "Scoped instructions improve output quality.",
                "detection_hint": "General",
                "setup_guide": "1. Create AGENTS.md at project root for project-specific instructions\n2. Add ~/.codex/AGENTS.md for global instructions\n3. Per-directory: src/api/AGENTS.md for API-specific rules\n4. Use AGENTS.override.md to supersede at same level\n5. Total size limit: 32 KiB combined (configurable)",
                "prompt_tips": "GOOD: AGENTS.md with 'Always use parameterized queries for SQL'\nBAD: AGENTS.md with entire API documentation (too long, gets ignored)\nTIP: Think of AGENTS.md as a cheat sheet, not a manual. Key rules only",
            },
            {
                "name": "Sandbox configuration",
                "description": "Three modes: auto (default), read-only, full-access. Configure writable_roots, network_access in config.toml. shell_environment_policy to prevent secret leaks.",
                "impact": "Security without blocking legitimate operations.",
                "detection_hint": "General",
                "setup_guide": "1. Edit ~/.codex/config.toml\n2. Set sandbox mode: auto (default), read-only, full-access\n3. Configure writable_roots for allowed write paths\n4. Set network_access rules\n5. Set shell_environment_policy to prevent secret leaks\n6. Never use --yolo in production repos",
                "prompt_tips": "GOOD: Configure writable_roots to limit where agent can write\nBAD: Using full-access sandbox for everything\nTIP: Start with read-only for exploration, switch to auto for implementation",
            },
        ],
        "anti_patterns": [
            "Using --yolo in production repos",
            "Not configuring shell_environment_policy — leaking env secrets",
            "Not using profiles — manually switching models",
        ],
    },
}

# Cross-tool universal best practices
UNIVERSAL_PRACTICES = [
    "Keep instruction files lean — every token competes with actual code context",
    "Use deterministic tools (linters, formatters) via hooks/scripts, not AI instructions",
    "Scope instructions with globs/file-matching instead of always-on loading",
    "Clear context between unrelated tasks — stale context degrades all AI tools",
    "Use cheap models for exploration, expensive models for architecture decisions",
    "Front-load planning (Plan mode, specs) to prevent expensive rework",
    "Batch feedback and corrections instead of one-at-a-time interactions",
]


# ---------------------------------------------------------------------------
# LLM prompt: smaller, focused on what only the LLM can do.
# Python handles all deterministic computation; LLM adds intelligence.
# ---------------------------------------------------------------------------

OPTIMIZER_PROMPT = """\
You are an expert AI coding tool optimizer. Analyze the structured usage data \
below and provide intelligent analysis.

IMPORTANT: The "computed_metrics" section contains pre-computed deterministic \
data (anti-patterns, cost forensics, prompt analysis, context engineering). \
Do NOT recompute these — they are already accurate. Focus on interpretation \
and recommendations.

## Input Data (JSON)

```json
{input_json}
```

## Your Task

Using the data above, return ONLY valid JSON with this exact structure:

```json
{{
  "score": <0-100 overall optimization score>,
  "developer_profile": {{
    "title": "<short identity, e.g. 'Full-Stack AI Power User'>",
    "bio": "<2-3 sentence profile based on the data>",
    "traits": ["<trait1>", "<trait2>", "<trait3>"],
    "ai_personality": "<one of: power_user, methodical_builder, debug_warrior, explorer, cautious_adopter, efficiency_optimizer>"
  }},
  "grades": {{
    "cache_efficiency": {{"grade": "<A/B/C/D>", "detail": "<one sentence with numbers>"}},
    "session_hygiene": {{"grade": "<A/B/C/D>", "detail": "<one sentence with numbers>"}},
    "model_selection": {{"grade": "<A/B/C/D>", "detail": "<one sentence>"}},
    "prompt_quality": {{"grade": "<A/B/C/D>", "detail": "<one sentence>"}},
    "tool_utilization": {{"grade": "<A/B/C/D>", "detail": "<one sentence>"}}
  }},
  "recommendations": [
    {{"title": "<actionable title>", "description": "<specific advice referencing their data>", "priority": "<high/medium/low>", "savings": "<estimated impact>", "source": "<reference>"}}
  ],
  "missing_features": [
    {{"tool": "<tool name>", "feature": "<feature name>", "evidence": "<data evidence>", "benefit": "<what they'd gain>"}}
  ],
  "project_insights": [
    {{"project": "<name>", "type": "<greenfield/maintenance/debugging/refactoring/exploration>", "insight": "<observation>", "recommendation": "<advice>", "underutilized": "<features>", "recommended_model": {{"model": "<name>", "reason": "<why>"}}, "recommended_tool": {{"tool": "<IDE/tool name>", "reason": "<why this tool fits this project type>"}}}}
  ],
  "workflow": {{
    "current": "<2-3 sentence current workflow assessment>",
    "future": "<2-3 sentence optimized workflow vision>"
  }}
}}
```

Rules:
- Reference REAL numbers from the data (tokens, costs, session counts)
- 3-7 recommendations, ranked by impact
- Cross-reference "feature_detection" with session patterns for missing_features. If feature_detection shows agents/commands/rules/skills are configured, do NOT flag them as missing. If feature_detection shows they're NOT configured but session patterns suggest they'd help, flag them with evidence.
- Be specific and actionable, not generic
- Return ONLY the JSON object, no markdown fences, no explanation
- **project_insights MUST include EVERY project from project_details** — not just the top one. If there are 5 projects, return 5 project_insight entries. Each must have all fields including recommended_model and recommended_tool.
- **ONLY recommend models that actually exist for the tool being used:**
  - Claude Code: claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5
  - Cursor: gpt-4o, claude-sonnet-4-6, claude-haiku-4-5, gemini-2.5-pro (or models from model_usage data)
  - Copilot: gpt-4o, claude-sonnet-4-6, o3-mini
  - Codex: codex-mini, o4-mini, o3
  - Kiro: claude-sonnet-4-6
  - NEVER invent model names like "gpt-3.5-codex" or "gpt-5.3". Use ONLY the names listed above or seen in model_usage data.
- **recommended_tool**: Recommend the best IDE/tool for each project type (e.g. Cursor for rapid prototyping, Claude Code for CLI-heavy workflows, Kiro for spec-driven features, Copilot for GitHub-integrated repos). Base this on the project's intent distribution and the tool's strengths from tool_knowledge.
- **setup_guide and prompt_tips**: Each feature in tool_knowledge now includes setup_guide (how to set it up step-by-step) and prompt_tips (good vs bad prompt examples). Reference these in recommendations when suggesting features the user should adopt. Include specific setup steps, not just "use feature X".
- When identifying missing_features, include the setup_guide from tool_knowledge so the user knows exactly HOW to enable the feature.
- When grading prompt_quality, reference the prompt_tips from tool_knowledge to explain what specifically is wrong with the user's prompts and how to improve them.
"""


# ---------------------------------------------------------------------------
# Deep analysis: prompt NLP, anti-patterns, cost forensics
# ---------------------------------------------------------------------------


def _analyze_prompts(sessions: list[Session]) -> dict[str, Any]:
    """NLP-lite analysis on all session prompts."""
    all_prompts: list[str] = []
    session_prompts: dict[str, list[str]] = {}
    for s in sessions:
        session_prompts[s.id] = s.prompts
        all_prompts.extend(s.prompts)

    if not all_prompts:
        return {
            "prompt_length_distribution": {
                "commands_under_20": 0, "short_20_100": 0,
                "detailed_100_500": 0, "very_detailed_500_plus": 0,
                "avg_length": 0,
            },
            "correction_spirals": [],
            "repeated_prompts": [],
            "slash_commands": {},
            "uses_compact": 0,
            "uses_clear": 0,
            "specificity_score": 0,
        }

    lengths = [len(p) for p in all_prompts]
    result: dict[str, Any] = {}
    result["prompt_length_distribution"] = {
        "commands_under_20": sum(1 for ln in lengths if ln < 20),
        "short_20_100": sum(1 for ln in lengths if 20 <= ln < 100),
        "detailed_100_500": sum(1 for ln in lengths if 100 <= ln < 500),
        "very_detailed_500_plus": sum(1 for ln in lengths if ln >= 500),
        "avg_length": round(sum(lengths) / len(lengths)),
    }

    # Correction spirals — populated by LLM-based conversation analysis
    # (see AIUsageOptimizer._detect_correction_spirals)
    result["correction_spirals"] = []

    # Repeated prompts (skill candidates)
    prompt_counter = Counter(p for p in all_prompts if len(p) > 15)
    result["repeated_prompts"] = [
        {"prompt": t[:150], "count": c}
        for t, c in prompt_counter.most_common(10) if c > 2
    ]

    # Slash commands
    slash_counts = Counter(
        p.split()[0] for p in all_prompts if p.startswith("/")
    )
    result["slash_commands"] = dict(slash_counts.most_common(10))
    result["uses_compact"] = slash_counts.get("/compact", 0)
    result["uses_clear"] = slash_counts.get("/clear", 0)

    # Specificity score
    result["specificity_score"] = round(
        sum(1 for ln in lengths if ln >= 100) / len(lengths) * 100, 1,
    )
    return result


def _analyze_anti_patterns(
    sessions: list[Session],
    prompt_analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect anti-patterns with severity, count, detail, fix, and examples."""
    patterns: list[dict[str, Any]] = []

    # 1. Correction spirals
    spirals = prompt_analysis.get("correction_spirals", [])
    if spirals:
        total_wasted = sum(sp["tokens_wasted"] for sp in spirals)
        patterns.append({
            "pattern": "Correction Spirals",
            "icon": "\U0001f300",
            "severity": "high",
            "count": len(spirals),
            "detail": (
                f"{len(spirals)} sessions with 3+ corrections wasting "
                f"{total_wasted:,} tokens. You're fighting the AI instead of guiding it."
            ),
            "fix": (
                "Be specific upfront: include file paths, expected behavior, and constraints "
                "in your first prompt. If the AI goes wrong, start a new session with a "
                "clearer prompt instead of correcting repeatedly."
            ),
            "examples": [
                f"{sp['project']}: {sp['corrections']} corrections in {sp['messages']} msgs "
                f"({sp['correction_rate']}% rate, {sp['tokens_wasted']:,} tokens)"
                + (f" — {sp['what_went_wrong']}" if sp.get("what_went_wrong") else "")
                for sp in spirals[:3]
            ],
        })

    # 2. Marathon sessions
    marathon_sessions = [s for s in sessions if s.message_count >= 100]
    if marathon_sessions:
        marathon_tokens = sum(s.total_tokens for s in marathon_sessions)
        patterns.append({
            "pattern": "Marathon Sessions",
            "icon": "\U0001f3c3",
            "severity": "high" if len(marathon_sessions) > 5 else "medium",
            "count": len(marathon_sessions),
            "detail": (
                f"{len(marathon_sessions)} sessions with 100+ messages "
                f"({marathon_tokens:,} tokens). After ~50 messages, context degrades "
                f"and the AI starts forgetting earlier instructions."
            ),
            "fix": (
                "Break work into focused sessions of <30 messages. Use /compact to "
                "compress context mid-session. Start new sessions for new subtasks. "
                "Use CLAUDE.md for persistent context."
            ),
            "examples": [
                f"{s.project.split('/')[-1] if s.project else 'unknown'}: "
                f"{s.message_count} msgs, {s.total_tokens:,} tokens"
                for s in sorted(marathon_sessions, key=lambda x: x.message_count, reverse=True)[:3]
            ],
        })

    # 3. Vague prompts
    specificity = prompt_analysis.get("specificity_score", 0)
    if specificity < 30:
        patterns.append({
            "pattern": "Vague Prompts",
            "icon": "\U0001f32b\ufe0f",
            "severity": "medium",
            "count": round((100 - specificity) / 100 * sum(
                len(s.prompts) for s in sessions
            )),
            "detail": (
                f"Only {specificity}% of prompts are detailed (100+ chars). "
                f"Short, vague prompts lead to more back-and-forth corrections."
            ),
            "fix": (
                "Include context in prompts: file paths, expected behavior, constraints, "
                "and examples. A detailed first prompt saves 3-5 correction messages."
            ),
            "examples": [],
        })

    # 4. No context management
    uses_compact = prompt_analysis.get("uses_compact", 0)
    uses_clear = prompt_analysis.get("uses_clear", 0)
    bloated = sum(1 for s in sessions if s.message_count > 50)
    if bloated > 3 and uses_compact == 0 and uses_clear == 0:
        patterns.append({
            "pattern": "No Context Management",
            "icon": "\U0001f5c4\ufe0f",
            "severity": "medium",
            "count": bloated,
            "detail": (
                f"{bloated} bloated sessions (>50 msgs) but never used /compact or "
                f"/clear. Context grows unbounded, degrading response quality."
            ),
            "fix": (
                "Use /compact when context feels heavy (~30-40 messages). "
                "Use /clear between distinct subtasks. Both are free and instant."
            ),
            "examples": [],
        })

    # 5. Repeated prompts (skill candidates)
    repeated = prompt_analysis.get("repeated_prompts", [])
    if repeated:
        patterns.append({
            "pattern": "Repeated Prompts",
            "icon": "\U0001f501",
            "severity": "low",
            "count": sum(r["count"] for r in repeated),
            "detail": (
                f"{len(repeated)} prompts repeated 3+ times — these are skill candidates. "
                f"Automating them would save time and tokens."
            ),
            "fix": (
                "Create custom slash commands or CLAUDE.md snippets for repeated prompts. "
                "Consider building a skill file for frequently used workflows."
            ),
            "examples": [
                f'"{r["prompt"][:80]}..." ({r["count"]}x)'
                for r in repeated[:3]
            ],
        })

    return patterns


def _build_cost_forensics(
    profile: dict[str, Any],
    sessions: list[Session],
    model_usage: dict[str, Any],
) -> dict[str, Any]:
    """Deep cost analysis with waste estimation."""
    from agenttop.collectors.claude import _match_model_pricing

    ce = profile.get("context_engineering", {})
    total_cost = ce.get("total_cost", 0.0)

    # Cost by project
    project_costs: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"cost": 0.0, "tokens": 0},
    )
    for s in sessions:
        pname = s.project.split("/")[-1] if s.project else "unknown"
        project_costs[pname]["cost"] += s.estimated_cost_usd
        project_costs[pname]["tokens"] += s.total_tokens
    cost_by_project = [
        {"project": name, "cost": round(d["cost"], 2), "tokens": d["tokens"]}
        for name, d in sorted(
            project_costs.items(), key=lambda x: x[1]["cost"], reverse=True,
        )[:10]
    ]

    # Cost by model — aggregate from Claude's detailed model_usage AND
    # from all sessions (Cursor, Codex, Copilot report model in session data)
    model_costs: dict[str, dict[str, float]] = defaultdict(
        lambda: {"cost": 0.0, "tokens": 0},
    )

    # Claude: precise per-model breakdown from stats-cache
    for model_id, usage in model_usage.items():
        pricing = _match_model_pricing(model_id)
        model_cost = (
            usage.get("inputTokens", 0) / 1_000_000 * pricing["input"]
            + usage.get("outputTokens", 0) / 1_000_000 * pricing["output"]
            + usage.get("cacheReadInputTokens", 0) / 1_000_000 * pricing["cache_read"]
            + usage.get("cacheCreationInputTokens", 0) / 1_000_000 * pricing["cache_create"]
        )
        billed_tokens = (
            usage.get("inputTokens", 0)
            + usage.get("outputTokens", 0)
        )
        model_costs[model_id]["cost"] += model_cost
        model_costs[model_id]["tokens"] += billed_tokens

    # Non-Claude tools: aggregate session-level costs by tool name
    # (these tools don't have per-model token breakdowns)
    claude_session_ids = {
        s.id for s in sessions if s.tool.value == "claude_code"
    }
    for s in sessions:
        if s.id in claude_session_ids:
            continue  # Claude already covered by model_usage above
        label = s.tool.value
        model_costs[label]["cost"] += s.estimated_cost_usd
        model_costs[label]["tokens"] += s.total_tokens

    cost_by_model = [
        {"model": model_id, "cost": round(d["cost"], 2), "tokens": int(d["tokens"])}
        for model_id, d in model_costs.items()
        if d["cost"] > 0 or d["tokens"] > 0
    ]
    cost_by_model.sort(key=lambda x: x["cost"], reverse=True)

    # Estimated waste from marathon sessions.
    # 50 messages = threshold where context windows typically bloat and model
    # performance degrades (based on Claude Code session analysis heuristics).
    # 0.5 multiplier = conservative estimate that ~half the tail tokens are
    # wasted on redundant context re-reads rather than productive output.
    marathon_threshold = 50
    waste_discount = 0.5
    estimated_waste = 0.0
    for s in sessions:
        if s.message_count > marathon_threshold:
            tail_fraction = (s.message_count - marathon_threshold) / s.message_count
            estimated_waste += s.estimated_cost_usd * tail_fraction * waste_discount

    waste_pct = round(estimated_waste / total_cost * 100, 1) if total_cost > 0 else 0

    return {
        "total_cost": round(total_cost, 2),
        "estimated_waste": round(estimated_waste, 2),
        "waste_pct": waste_pct,
        "cost_by_project": cost_by_project,
        "cost_by_model": cost_by_model,
    }


# ---------------------------------------------------------------------------
# User profile builder: extracts all real signals from collector data
# ---------------------------------------------------------------------------


def build_user_profile(
    stats: list[dict[str, Any]],
    sessions: list[Session],
    model_usage: dict[str, Any],
    claude_collector: Any | None = None,
    feature_configs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a rich user profile from real collector data."""
    profile: dict[str, Any] = {}

    # -- Active tools --
    active_tools = []
    for s in stats:
        if s.get("status") == "active" or s.get("tokens_today", 0) > 0:
            active_tools.append({
                "tool": s.get("tool", "unknown"),
                "display_name": s.get("display_name", s.get("tool", "?")),
                "sessions": s.get("sessions_today", 0),
                "messages": s.get("messages_today", 0),
                "tokens": s.get("tokens_today", 0),
                "cost": s.get("estimated_cost_today", 0.0),
                "status": s.get("status", "idle"),
            })
    profile["active_tools"] = active_tools
    profile["total_tokens"] = sum(
        t["tokens"] for t in active_tools
    )
    profile["total_cost"] = sum(t["cost"] for t in active_tools)

    # -- Session patterns --
    if sessions:
        msg_counts = [s.message_count for s in sessions]
        profile["session_count"] = len(sessions)
        profile["avg_messages_per_session"] = (
            sum(msg_counts) / len(msg_counts)
        )
        profile["max_session_messages"] = max(msg_counts)
        profile["min_session_messages"] = min(msg_counts)

        # Session length distribution
        short = sum(1 for m in msg_counts if m < 10)
        medium = sum(1 for m in msg_counts if 10 <= m < 50)
        long = sum(1 for m in msg_counts if m >= 50)
        marathon = sum(1 for m in msg_counts if m >= 100)
        profile["session_distribution"] = {
            "short_under_10": short,
            "medium_10_to_50": medium,
            "long_50_plus": long,
            "marathon_100_plus": marathon,
        }

        # Tool call ratio (exploration intensity)
        total_msgs = sum(msg_counts)
        total_tool_calls = sum(s.tool_call_count for s in sessions)
        if total_msgs > 0:
            profile["tool_call_ratio"] = round(
                total_tool_calls / total_msgs, 2
            )

        # Intent keywords (shared by per-project and global intent classification)
        intent_keywords = {
            "debugging": ["bug", "fix", "error", "debug", "crash", "issue"],
            "refactoring": ["refactor", "rename", "clean", "restructure"],
            "greenfield": ["create", "new", "implement", "build", "add"],
            "exploration": ["what", "how", "explain", "understand", "show"],
            "code_review": ["review", "check", "audit", "look at"],
            "devops": ["deploy", "docker", "ci", "pipeline", "k8s"],
            "documentation": ["doc", "readme", "comment", "describe"],
        }

        # Per-project aggregation (deep intelligence)
        project_data: dict[str, dict] = defaultdict(lambda: {
            "sessions": 0, "tokens": 0, "cost": 0.0,
            "messages": 0, "tool_calls": 0, "tools": set(),
            "intents": defaultdict(int), "sample_prompts": [],
        })
        for s in sessions:
            pname = s.project.split("/")[-1] if s.project else "unknown"
            pd = project_data[pname]
            pd["sessions"] += 1
            pd["tokens"] += s.total_tokens
            pd["cost"] += s.estimated_cost_usd
            pd["messages"] += s.message_count
            pd["tool_calls"] += s.tool_call_count
            pd["tools"].add(s.tool.value if hasattr(s.tool, 'value') else str(s.tool))
            if len(pd["sample_prompts"]) < 3 and s.prompts:
                pd["sample_prompts"].append(s.prompts[0][:100])
            # Classify intents for this project
            for prompt in s.prompts[:3]:
                prompt_lower = prompt.lower()
                for intent, keywords in intent_keywords.items():
                    if any(kw in prompt_lower for kw in keywords):
                        pd["intents"][intent] += 1
                        break

        # Convert sets to lists for JSON serialization
        profile["project_details"] = {
            name: {**data, "tools": list(data["tools"]), "intents": dict(data["intents"])}
            for name, data in sorted(project_data.items(), key=lambda x: x[1]["tokens"], reverse=True)[:10]
        }
        profile["project_count"] = len(project_data)
        profile["top_projects"] = {name: data["sessions"] for name, data in sorted(project_data.items(), key=lambda x: x[1]["sessions"], reverse=True)[:10]}

        # Intent distribution (from prompt keywords)
        intent_counts: dict[str, int] = defaultdict(int)
        for s in sessions:
            for prompt in s.prompts[:5]:  # first 5 prompts per session
                prompt_lower = prompt.lower()
                matched = False
                for intent, keywords in intent_keywords.items():
                    if any(kw in prompt_lower for kw in keywords):
                        intent_counts[intent] += 1
                        matched = True
                        break
                if not matched:
                    intent_counts["other"] += 1
        if intent_counts:
            profile["intent_distribution"] = dict(intent_counts)

        # Recent session details (top 15 by tokens for deep analysis)
        sorted_sessions = sorted(sessions, key=lambda s: s.total_tokens, reverse=True)
        session_details = []
        for s in sorted_sessions[:15]:
            pname = s.project.split("/")[-1] if s.project else "unknown"
            # Classify session intent
            session_intent = "other"
            for prompt in s.prompts[:3]:
                prompt_lower = prompt.lower()
                for intent, keywords in intent_keywords.items():
                    if any(kw in prompt_lower for kw in keywords):
                        session_intent = intent
                        break
                if session_intent != "other":
                    break
            # Context efficiency = tool_calls / messages
            context_ratio = round(s.tool_call_count / s.message_count, 1) if s.message_count > 0 else 0
            session_details.append({
                "project": pname,
                "messages": s.message_count,
                "tokens": s.total_tokens,
                "cost": round(s.estimated_cost_usd, 2),
                "tool_calls": s.tool_call_count,
                "intent": session_intent,
                "context_ratio": context_ratio,
                "tool": s.tool.value if hasattr(s.tool, 'value') else str(s.tool),
                "first_prompt": s.prompts[0][:120] if s.prompts else "",
                "start_time": s.start_time.isoformat(),
            })
        profile["session_details"] = session_details

        # Context engineering metrics
        total_msgs = sum(s.message_count for s in sessions)
        total_tool_calls_all = sum(s.tool_call_count for s in sessions)
        total_tokens_all = sum(s.total_tokens for s in sessions)
        avg_tokens_per_msg = round(total_tokens_all / total_msgs) if total_msgs > 0 else 0
        avg_tool_calls_per_session = round(total_tool_calls_all / len(sessions), 1) if sessions else 0
        bloated_sessions = sum(1 for s in sessions if s.message_count > 50)
        total_cost_all = sum(s.estimated_cost_usd for s in sessions)
        cost_per_msg = round(total_cost_all / total_msgs, 4) if total_msgs > 0 else 0
        profile["context_engineering"] = {
            "avg_tokens_per_message": avg_tokens_per_msg,
            "avg_tool_calls_per_session": avg_tool_calls_per_session,
            "bloated_sessions": bloated_sessions,
            "bloated_pct": round(bloated_sessions / len(sessions) * 100, 1) if sessions else 0,
            "cost_per_message": cost_per_msg,
            "total_messages": total_msgs,
            "total_cost": round(total_cost_all, 2),
        }

        # Temporal patterns
        hour_counts: dict[int, int] = defaultdict(int)
        for s in sessions:
            hour_counts[s.start_time.hour] += 1
        if hour_counts:
            peak_hour = max(hour_counts, key=lambda h: hour_counts[h])
            profile["peak_hour"] = peak_hour
            profile["hourly_distribution"] = dict(
                sorted(hour_counts.items())
            )

        # Deep intelligence: prompt analysis, anti-patterns, cost forensics
        profile["prompt_analysis"] = _analyze_prompts(sessions)
        profile["anti_patterns"] = _analyze_anti_patterns(
            sessions, profile["prompt_analysis"],
        )
        profile["cost_forensics"] = _build_cost_forensics(
            profile, sessions, model_usage,
        )
    else:
        profile["session_count"] = 0
        profile["avg_messages_per_session"] = 0

    # -- Model usage (Claude-specific deep data) --
    if model_usage:
        model_breakdown = {}
        total_input = 0
        total_output = 0
        total_cache_read = 0
        total_cache_create = 0

        for model_id, usage in model_usage.items():
            inp = usage.get("inputTokens", 0)
            out = usage.get("outputTokens", 0)
            cache_r = usage.get("cacheReadInputTokens", 0)
            cache_c = usage.get("cacheCreationInputTokens", 0)

            total_input += inp
            total_output += out
            total_cache_read += cache_r
            total_cache_create += cache_c

            model_input_total = inp + cache_r
            model_cache_rate = (
                (cache_r / model_input_total * 100)
                if model_input_total > 0 else 0
            )

            model_breakdown[model_id] = {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_read_tokens": cache_r,
                "cache_create_tokens": cache_c,
                "total_tokens": inp + out + cache_r,
                "cache_hit_rate": round(model_cache_rate, 1),
            }

        overall_input = total_input + total_cache_read
        overall_cache_rate = (
            (total_cache_read / overall_input * 100)
            if overall_input > 0 else 0
        )

        output_ratio = (
            (total_output / total_input * 100)
            if total_input > 0 else 0
        )

        profile["model_usage"] = {
            "models": model_breakdown,
            "model_count": len(model_breakdown),
            "overall_cache_hit_rate": round(overall_cache_rate, 1),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cache_read_tokens": total_cache_read,
            "output_to_input_ratio": round(output_ratio, 1),
        }

    # -- Claude-specific enrichment --
    if claude_collector is not None:
        try:
            hour_data = claude_collector.get_hour_counts()
            if hour_data:
                profile["claude_hour_counts"] = hour_data

            summary = claude_collector.get_session_summary()
            if summary:
                profile["claude_lifetime"] = {
                    "total_sessions": summary.get("totalSessions", 0),
                    "total_messages": summary.get("totalMessages", 0),
                    "first_session": summary.get("firstSessionDate"),
                }
        except Exception as e:
            logging.debug("Failed to enrich profile from Claude collector: %s", e)

    # -- Feature detection (ground truth for optimizer) --
    if feature_configs:
        profile["feature_detection"] = feature_configs

    return profile


def _build_llm_input(
    profile: dict[str, Any],
    active_tool_ids: set[str],
) -> dict[str, Any]:
    """Build a clean JSON payload for the LLM.

    Includes the profile data + relevant knowledge base, all as structured
    JSON instead of prose markdown.
    """
    # Extract relevant knowledge base entries
    tool_knowledge = {}
    for tool_id in active_tool_ids:
        kb = KNOWLEDGE_BASE.get(tool_id)
        if kb:
            tool_knowledge[tool_id] = {
                "display_name": kb["display_name"],
                "features": [
                    {
                        "name": f["name"],
                        "impact": f["impact"],
                        "setup_guide": f.get("setup_guide", ""),
                        "prompt_tips": f.get("prompt_tips", ""),
                    }
                    for f in kb["features"]
                ],
                "anti_patterns": kb["anti_patterns"],
                "cost_benchmarks": kb.get("cost_benchmarks"),
            }

    return {
        "profile": {
            "active_tools": profile.get("active_tools", []),
            "total_tokens": profile.get("total_tokens", 0),
            "total_cost": profile.get("total_cost", 0),
            "session_count": profile.get("session_count", 0),
            "avg_messages_per_session": profile.get("avg_messages_per_session", 0),
            "max_session_messages": profile.get("max_session_messages", 0),
            "session_distribution": profile.get("session_distribution", {}),
            "tool_call_ratio": profile.get("tool_call_ratio"),
            "intent_distribution": profile.get("intent_distribution", {}),
            "peak_hour": profile.get("peak_hour"),
            "project_details": profile.get("project_details", {}),
            "model_usage": profile.get("model_usage", {}),
        },
        "computed_metrics": {
            "context_engineering": profile.get("context_engineering", {}),
            "prompt_analysis": profile.get("prompt_analysis", {}),
            "anti_patterns": profile.get("anti_patterns", []),
            "cost_forensics": profile.get("cost_forensics", {}),
            "session_details": profile.get("session_details", []),
        },
        "tool_knowledge": tool_knowledge,
        "feature_detection": profile.get("feature_detection", {}),
        "universal_practices": UNIVERSAL_PRACTICES,
    }


# ---------------------------------------------------------------------------
# Main optimizer class
# ---------------------------------------------------------------------------


class AIUsageOptimizer:
    """Analyzes usage patterns and generates optimization recommendations.

    Python computes deterministic metrics; LLM adds intelligent analysis.
    Setup guarantees LLM is always available.
    """

    def __init__(
        self,
        config: Config | None = None,
        claude_collector: Any | None = None,
    ) -> None:
        from agenttop.config import load_config

        self._config = config or load_config()
        self._claude = claude_collector

    def analyze(
        self,
        stats: list[dict[str, Any]],
        sessions: list[Session],
        model_usage: dict[str, Any],
        feature_configs: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run optimization analysis.

        1. Build rich user profile from real data
        2. Compute deterministic metrics (anti-patterns, costs, etc.)
        3. Send structured JSON to LLM for intelligent analysis
        4. Merge Python metrics + LLM analysis into final response
        """
        # Build the user profile from real data
        profile = build_user_profile(
            stats, sessions, model_usage, self._claude, feature_configs,
        )

        # LLM-based conversation analysis: detect correction spirals
        # by reading actual conversation flow, not keyword matching
        spirals = self._detect_correction_spirals(sessions)
        profile["prompt_analysis"]["correction_spirals"] = spirals
        # Recompute anti-patterns with LLM-detected spirals
        profile["anti_patterns"] = _analyze_anti_patterns(
            sessions, profile["prompt_analysis"],
        )

        # Get LLM analysis
        llm_result = self._get_llm_analysis(profile)

        # Merge: Python-computed metrics (always accurate) + LLM intelligence
        result = self._merge_results(profile, llm_result)
        return result

    def _detect_correction_spirals(
        self,
        sessions: list[Session],
    ) -> list[dict[str, Any]]:
        """Use the LLM to analyze actual conversation flow and detect correction spirals.

        Instead of matching keywords like "no" or "wrong", sends the user's
        prompt sequence to the LLM to identify sessions where the user was
        fighting, redirecting, or repeatedly correcting the AI.
        """
        # Filter to sessions with enough messages to have spirals
        candidates = [
            s for s in sessions
            if len(s.prompts) >= 5 and s.message_count >= 8
        ]
        if not candidates:
            return []

        # Sort by message count descending — analyze the longest sessions first
        candidates.sort(key=lambda s: s.message_count, reverse=True)
        candidates = candidates[:15]  # cap to control token usage

        # Build conversation summaries for the LLM
        session_data: list[dict[str, Any]] = []
        for s in candidates:
            # Take up to 12 prompts, truncated, to show the conversation flow
            prompts_sample = [p[:120] for p in s.prompts[:12]]
            session_data.append({
                "id": s.id[:12],
                "tool": s.tool.value,
                "project": s.project.split("/")[-1] if s.project else "unknown",
                "message_count": s.message_count,
                "total_tokens": s.total_tokens,
                "user_prompts": prompts_sample,
            })

        prompt = f"""Analyze these AI coding sessions. Each entry contains the user's prompts in order (assistant responses are not shown, but you can infer the flow).

Identify sessions where the user is stuck in a CORRECTION SPIRAL — repeatedly redirecting, correcting, or fighting the AI instead of making progress. Look for:
- User rephrasing the same request multiple times
- User expressing frustration or disagreement with AI output
- User undoing or reverting AI changes
- Back-and-forth where the conversation isn't progressing
- User having to re-explain what they want

For each session with a correction spiral, explain WHAT went wrong (e.g. "user asked for X but AI kept doing Y", "unclear initial prompt led to 5 rounds of correction").

Return ONLY this JSON (no other text):
{{
  "spirals": [
    {{
      "id": "session_id",
      "corrections": <number of correction messages>,
      "correction_rate": <percentage of prompts that are corrections>,
      "what_went_wrong": "<1-sentence explanation of the spiral>"
    }}
  ]
}}

If no sessions have correction spirals, return {{"spirals": []}}.

Sessions to analyze:
{json.dumps(session_data, indent=2, default=str)}"""

        system_msg = (
            "You are a conversation analyst. Analyze user prompt sequences "
            "to detect correction spirals. Be precise — only flag sessions "
            "where the user is genuinely fighting the AI, not normal iteration. "
            "Return ONLY valid JSON, no markdown fences, no explanation."
        )

        parsed = None
        for attempt in range(3):
            raw = get_completion(
                prompt,
                self._config.llm,
                system=system_msg,
                max_tokens=2000,
            )

            if raw.startswith("[error]"):
                logging.warning("Correction spiral LLM call failed: %s", raw)
                return []

            try:
                parsed = self._extract_json(raw)
                break
            except (json.JSONDecodeError, IndexError, KeyError):
                logging.debug(
                    "Correction spiral JSON parse failed (attempt %d/3)",
                    attempt + 1,
                )

        if parsed is None:
            logging.warning("Correction spiral detection failed after 3 attempts")
            return []

        # Map LLM results back to session data
        spiral_results: list[dict[str, Any]] = []
        for spiral in parsed.get("spirals", []):
            sid_prefix = spiral.get("id", "")
            matched = next(
                (s for s in candidates if s.id[:12] == sid_prefix), None,
            )
            if matched:
                spiral_results.append({
                    "project": (
                        matched.project.split("/")[-1]
                        if matched.project else "unknown"
                    ),
                    "messages": matched.message_count,
                    "corrections": spiral.get("corrections", 0),
                    "correction_rate": spiral.get("correction_rate", 0),
                    "what_went_wrong": spiral.get("what_went_wrong", ""),
                    "first_prompt": (
                        matched.prompts[0][:120] if matched.prompts else ""
                    ),
                    "tokens_wasted": matched.total_tokens,
                })

        return sorted(
            spiral_results, key=lambda x: x["corrections"], reverse=True,
        )[:10]

    @staticmethod
    def _extract_json(raw: str) -> dict[str, Any]:
        """Extract a JSON object from potentially noisy LLM output.

        Handles markdown fences, thinking tags, and extra text around JSON.
        """
        cleaned = raw.strip()

        # Strip <think>...</think> blocks (some models emit reasoning)
        cleaned = re.sub(
            r"<think>.*?</think>", "", cleaned, flags=re.DOTALL,
        ).strip()

        # Strip markdown code fences
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

        # Try direct parse first
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Fallback: find the outermost { ... } in the response
        brace_start = cleaned.find("{")
        brace_end = cleaned.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            return json.loads(cleaned[brace_start : brace_end + 1])

        raise json.JSONDecodeError("No JSON object found", cleaned, 0)

    def _get_llm_analysis(
        self,
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        """Get LLM-powered analysis. Returns parsed JSON or error dict.

        Retries up to 2 times on invalid JSON to handle flaky model output.
        """
        active_tool_ids = {
            t["tool"] for t in profile.get("active_tools", [])
        }

        # Build structured JSON input for the LLM
        llm_input = _build_llm_input(profile, active_tool_ids)
        input_json = json.dumps(llm_input, indent=2, default=str)

        prompt = OPTIMIZER_PROMPT.format(input_json=input_json)
        system_msg = (
            "You are an expert AI coding tool optimizer. "
            "Analyze the structured usage data and return ONLY valid JSON. "
            "No markdown fences, no explanation — just the JSON object."
        )

        last_error = ""
        for attempt in range(3):
            raw = get_completion(
                prompt,
                self._config.llm,
                system=system_msg,
                max_tokens=4000,
            )

            if raw.startswith("[error]"):
                return {"error": raw, "source": "error"}

            try:
                parsed = self._extract_json(raw)
                parsed["source"] = "llm"
                return parsed
            except (json.JSONDecodeError, IndexError, KeyError):
                last_error = raw[:200] if raw else "empty response"
                logging.debug(
                    "LLM JSON parse failed (attempt %d/3): %s",
                    attempt + 1,
                    last_error,
                )

        return {
            "error": "LLM returned invalid JSON after 3 attempts. Try a different model.",
            "source": "error",
        }

    def _merge_results(
        self,
        profile: dict[str, Any],
        llm_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge Python-computed metrics with LLM analysis.

        Python metrics are always included (deterministic, accurate).
        LLM fields are included when available, with sensible defaults.
        """
        # Python-computed fields (always accurate)
        result: dict[str, Any] = {
            "anti_patterns": profile.get("anti_patterns", []),
            "cost_forensics": profile.get("cost_forensics", {}),
            "prompt_analysis": profile.get("prompt_analysis", {}),
            "context_engineering": profile.get("context_engineering", {}),
            "session_details": profile.get("session_details", []),
            "profile_summary": {
                "total_tokens": profile.get("total_tokens", 0),
                "total_cost": profile.get("total_cost", 0),
                "session_count": profile.get("session_count", 0),
                "avg_messages": profile.get(
                    "avg_messages_per_session", 0
                ),
                "cache_hit_rate": (
                    profile.get("model_usage", {})
                    .get("overall_cache_hit_rate", 0)
                ),
                "active_tools": len(profile.get("active_tools", [])),
            },
            "feature_detection": profile.get("feature_detection", {}),
        }

        # Handle LLM errors
        if llm_result.get("source") == "error":
            result["error"] = llm_result.get("error", "LLM analysis failed")
            result["source"] = "partial"
            result["setup_hint"] = (
                "The optimizer requires an LLM. Quickest setup:\n\n"
                "  brew install ollama\n"
                "  ollama pull gemma3:4b\n"
                "  ollama serve\n\n"
                "Then refresh and try again."
            )
            # Provide defaults so the frontend can still render Python metrics
            result["score"] = 0
            result["grades"] = {}
            result["recommendations"] = []
            result["missing_features"] = []
            result["project_insights"] = []
            result["workflow"] = {}
            result["developer_profile"] = {}
            return result

        # LLM-provided fields (intelligent analysis)
        result["score"] = llm_result.get("score", 0)
        result["developer_profile"] = llm_result.get("developer_profile", {})
        result["grades"] = llm_result.get("grades", {})
        result["recommendations"] = llm_result.get("recommendations", [])
        result["missing_features"] = llm_result.get("missing_features", [])
        result["project_insights"] = llm_result.get("project_insights", [])
        result["workflow"] = llm_result.get("workflow", {})
        result["source"] = "llm"

        return result
