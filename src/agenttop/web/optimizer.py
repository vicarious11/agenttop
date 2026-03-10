# ruff: noqa: E501
"""AI Usage Optimizer — LLM-powered workflow recommendations.

Builds a rich user profile from real collector data, cross-references
against current best practices for each tool, and uses an LLM to
identify gaps and generate personalized, actionable recommendations.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from agenttop.analysis.engine import (
    check_llm_available,
    get_completion,
    is_llm_configured,
)
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
            },
            {
                "name": "Sub-agents for parallel research",
                "description": "Define in .claude/agents/*.md with name, tools, model. Spawn explore agents for codebase search, plan agents for architecture. Each runs in separate context — doesn't bloat main conversation.",
                "impact": "Reduces main context pollution. Enables parallel investigation.",
                "detection_hint": "High tool_call_count relative to messages suggests manual exploration that could be delegated",
            },
            {
                "name": "Model selection strategy",
                "description": "Use /model to switch mid-session. Opus for complex architecture, Sonnet for general coding (default), Haiku for simple subagent tasks. Extended thinking on by default (31,999 tokens). Reduce with MAX_THINKING_TOKENS=8000 for simpler tasks.",
                "impact": "Sonnet is 5x cheaper than Opus with similar quality for most tasks.",
                "detection_hint": "Check model_usage for diversity",
            },
            {
                "name": "Prompt caching optimization",
                "description": "System prompt + CLAUDE.md + tool definitions are automatically cached. Cache reads cost 90% less. Avoid cache breakers: adding MCP tools mid-session, switching models. Use /context to check context usage.",
                "impact": "Up to 80% savings on input tokens.",
                "detection_hint": "Check cacheReadInputTokens ratio",
            },
            {
                "name": "Session hygiene with /clear and /compact",
                "description": "/clear between unrelated tasks (single most important habit). /compact <focus> for manual compaction: '/compact Focus on API changes'. Double-tap Esc for checkpoint restoration. --continue to resume last session.",
                "impact": "Prevents context pollution. Reduces token waste from stale context.",
                "detection_hint": "Long sessions (>50 messages) suggest lack of /clear usage",
            },
            {
                "name": "Skills and slash commands",
                "description": "Create .claude/commands/*.md for repetitive workflows. Define with --- frontmatter (name, description, tools). Invoke with /skill-name. Unlike CLAUDE.md, skills load on-demand only when relevant.",
                "impact": "Reduces CLAUDE.md bloat. Reusable workflows.",
                "detection_hint": "Repetitive prompt patterns suggest skill candidates",
            },
            {
                "name": "Hooks for automation",
                "description": "Configure in .claude/settings.json. Types: command, http, prompt (Haiku yes/no), agent (multi-turn). Events: PostToolUse, PreToolUse, SessionStart, etc. Example: auto-format on Edit/Write. Exit code 2 blocks action with feedback.",
                "impact": "Deterministic tasks (lint, format, test) handled without AI tokens.",
                "detection_hint": "Tool calls for formatting/linting suggest hook candidates",
            },
            {
                "name": "MCP server management",
                "description": "Each MCP server adds tool definitions consuming context even when idle. Use /context to check. Prefer CLI tools (gh, aws) over MCP when possible. ENABLE_TOOL_SEARCH=auto:5 defers loading until needed.",
                "impact": "Reduces baseline context size. Cheaper per message.",
                "detection_hint": "High input tokens relative to output may indicate context bloat",
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
            },
            {
                "name": "Four modes: Agent, Ask, Plan, Debug",
                "description": "Agent (Cmd+.): autonomous multi-file. Ask: read-only exploration. Plan: creates detailed plan before execution. Debug: hypothesis generation + log instrumentation.",
                "impact": "Plan mode prevents expensive rework. Ask mode is cheaper for exploration.",
                "detection_hint": "If user's sessions show exploration patterns, they may not be using Ask/Plan modes",
            },
            {
                "name": "Background / Cloud agents",
                "description": "Run tasks asynchronously in isolated environments at cursor.com/agent. Best for documentation, large refactors, test writing.",
                "impact": "Parallel task execution without blocking main workflow.",
                "detection_hint": "Long-running sessions may benefit from background delegation",
            },
            {
                "name": "@-mentions for targeted context",
                "description": "@file, @folder, @codebase (semantic search), @web, @docs, @git. Use @codebase to leverage indexed codebase instead of manual file hunting.",
                "impact": "Precise context = better responses. Avoids loading irrelevant files.",
                "detection_hint": "General",
            },
            {
                "name": "Notepads for reusable context",
                "description": "Store coding standards, API patterns, review checklists as reusable snippets. Team-shareable for consistency.",
                "impact": "Eliminates repeated instructions across conversations.",
                "detection_hint": "Repetitive prompts across sessions suggest notepad candidates",
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
            },
            {
                "name": "copilot-setup-steps.yml",
                "description": "Pre-install dependencies in .github/workflows/copilot-setup-steps.yml so agent can build/test immediately instead of discovering by trial-and-error.",
                "impact": "Reduces wasted Actions minutes. Faster agent execution.",
                "detection_hint": "General",
            },
            {
                "name": "Custom instructions (.github/copilot-instructions.md)",
                "description": "Repository-level + path-specific instructions (.github/instructions/*.instructions.md with applyTo globs). Custom agents in .github/agents/*.md.",
                "impact": "Agent has project context. Better code quality.",
                "detection_hint": "General",
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
            },
            {
                "name": "Steering files with inclusion modes",
                "description": "In .kiro/steering/: always (every interaction), fileMatch (glob-triggered), auto (agent decides from description), manual (#name invocation). Auto-generates product.md, tech.md, structure.md.",
                "impact": "Scoped context = less waste. fileMatch/auto avoid loading irrelevant steering.",
                "detection_hint": "General",
            },
            {
                "name": "Hooks for event-driven automation",
                "description": "Trigger on file save/create/commit. Auto-update tests, refresh README, security scan. Subagent support for parallel execution.",
                "impact": "Deterministic tasks without AI token consumption.",
                "detection_hint": "General",
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
            },
            {
                "name": "AGENTS.md instruction hierarchy",
                "description": "Global (~/.codex/AGENTS.md) -> project root (./AGENTS.md) -> per-directory. AGENTS.override.md supersedes at same level. Max 32 KiB combined (configurable).",
                "impact": "Scoped instructions improve output quality.",
                "detection_hint": "General",
            },
            {
                "name": "Sandbox configuration",
                "description": "Three modes: auto (default), read-only, full-access. Configure writable_roots, network_access in config.toml. shell_environment_policy to prevent secret leaks.",
                "impact": "Security without blocking legitimate operations.",
                "detection_hint": "General",
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
# Prompt template: gives the LLM both user profile and knowledge base
# ---------------------------------------------------------------------------

OPTIMIZER_PROMPT = """\
You are an expert AI coding tool usage optimizer. You have deep knowledge of \
every major AI coding tool's features, pricing, and best practices.

Your job: analyze this developer's REAL usage data, compare it against the \
best practices for the tools they actually use, and identify the specific \
gaps where they're leaving value on the table.

## Developer's Usage Profile

{user_profile}

## Tool-Specific Best Practices

{tool_knowledge}

## Universal Best Practices
{universal_practices}

## Your Task

1. **Grade** the developer on 5 dimensions (A/B/C/D with one-sentence justification):
   - Cache Efficiency: How well they leverage prompt caching
   - Session Hygiene: How they manage conversation context
   - Model Selection: Whether they use the right model for each task
   - Prompt Quality: Based on session patterns and intent distribution
   - Tool Utilization: How many tool features they actually use

2. **Identify missing features**: For each tool they actively use, find \
specific features from the best practices that their usage data suggests \
they're NOT using. Be specific — don't guess randomly. Only flag features \
where the data gives evidence they're missing out.

3. **Generate 3-7 recommendations** ranked by estimated impact, each with:
   - Specific action to take (not generic advice)
   - Why their data suggests they need this
   - Estimated savings (tokens, cost, or time)

4. **Overall score** (0-100) based on how optimally they're using their tools.

5. **Developer profile**: Build a concise developer bio/identity from the data:
   - What kind of developer they are (based on projects, intents, tools)
   - Their AI usage personality (power user, cautious adopter, debugger, explorer, etc.)
   - Work style observations (session patterns, time-of-day, project focus)

6. **Per-project insights** (for each project with significant usage):
   - What kind of work is happening (debugging-heavy? greenfield? refactoring?)
   - Project-specific recommendations (e.g., "agenttop sessions are long, use /compact")
   - Which tools/models are being used and whether they're optimal for this project type
   - Where they are underutilizing or wrongly utilizing their tools for this project

7. **Workflow Assessment**:
   - "current": How AI tools currently fit in the developer's workflow (2-3 sentences, be specific about patterns you see)
   - "future": What an optimized workflow would look like (2-3 sentences, concrete improvements)

8. **Anti-pattern diagnosis**: For each detected anti-pattern, explain WHY it matters
   with real numbers. Calculate wasted tokens for correction spirals. Explain context
   degradation for marathon sessions. Be harsh but constructive.

For each recommendation, include a "source" field referencing the best practice or article it's based on (e.g., "Claude Code docs: CLAUDE.md", "Anthropic prompt caching guide", "Cursor rules docs").

Return ONLY valid JSON with this structure:
{{
  "score": <0-100>,
  "developer_profile": {{
    "title": "short identity label, e.g. 'Full-Stack AI Power User'",
    "bio": "2-3 sentence developer profile based on the data",
    "traits": ["trait1", "trait2", "trait3"],
    "ai_personality": "one of: power_user, methodical_builder, debug_warrior, explorer, cautious_adopter, efficiency_optimizer"
  }},
  "grades": {{
    "cache_efficiency": {{"grade": "A-D", "detail": "one sentence with real numbers from their data"}},
    "session_hygiene": {{"grade": "A-D", "detail": "one sentence with real numbers"}},
    "model_selection": {{"grade": "A-D", "detail": "one sentence"}},
    "prompt_quality": {{"grade": "A-D", "detail": "one sentence"}},
    "tool_utilization": {{"grade": "A-D", "detail": "one sentence"}}
  }},
  "recommendations": [
    {{"title": "short actionable title", "description": "specific advice referencing their data", "priority": "high/medium/low", "savings": "estimated impact", "source": "reference to docs/article/best practice"}}
  ],
  "missing_features": [
    {{"tool": "tool name", "feature": "specific feature name", "evidence": "what in their data suggests they're not using this", "benefit": "what they'd gain"}}
  ],
  "project_insights": [
    {{"project": "name", "type": "greenfield/maintenance/debugging/refactoring/exploration", "insight": "specific observation from data", "recommendation": "actionable advice", "underutilized": "what tools/features are underused here", "recommended_model": {{"model": "model name (e.g. Sonnet 4.6, Opus 4.6, Haiku 4.5)", "reason": "why this model is optimal for this project's workload"}}}}
  ],
  "workflow": {{
    "current": "2-3 sentence assessment of current AI workflow",
    "future": "2-3 sentence vision of optimized workflow"
  }},
  "context_engineering": {{
    "assessment": "2-3 sentence assessment of how well they engineer context (prompt structure, session length, cache utilization, tool call patterns)",
    "avg_tokens_per_message": <number from profile>,
    "bloated_sessions": <number>,
    "bloated_pct": <number>,
    "cost_per_message": <number>
  }},
  "anti_patterns": [
    {{"pattern": "name", "icon": "emoji", "severity": "high/medium/low", "count": <number>, "detail": "explanation with real numbers", "fix": "actionable advice", "examples": ["example1"]}}
  ],
  "cost_forensics": {{
    "total_cost": <number>,
    "estimated_waste": <number>,
    "waste_pct": <number>,
    "cost_by_project": [{{"project": "name", "cost": <number>, "tokens": <number>}}],
    "cost_by_model": [{{"model": "id", "cost": <number>, "tokens": <number>}}]
  }},
  "prompt_analysis": {{
    "prompt_length_distribution": {{"commands_under_20": <n>, "short_20_100": <n>, "detailed_100_500": <n>, "very_detailed_500_plus": <n>, "avg_length": <n>}},
    "specificity_score": <number>,
    "correction_spirals": [],
    "repeated_prompts": [],
    "slash_commands": {{}},
    "uses_compact": <number>,
    "uses_clear": <number>
  }}
}}
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

    # Correction spirals
    correction_words = [
        "no", "wrong", "actually", "instead", "not what",
        "undo", "revert", "try again",
    ]
    spiral_sessions: list[dict[str, Any]] = []
    for sid, prompts in session_prompts.items():
        if len(prompts) < 3:
            continue
        corrections = sum(
            1 for p in prompts
            if any(w in p.lower() for w in correction_words) and len(p) < 100
        )
        if corrections >= 3 and corrections / len(prompts) > 0.15:
            s = next((s for s in sessions if s.id == sid), None)
            if s:
                spiral_sessions.append({
                    "project": s.project.split("/")[-1] if s.project else "unknown",
                    "messages": s.message_count,
                    "corrections": corrections,
                    "correction_rate": round(corrections / len(prompts) * 100),
                    "first_prompt": prompts[0][:120] if prompts else "",
                    "tokens_wasted": s.total_tokens,
                })
    result["correction_spirals"] = sorted(
        spiral_sessions, key=lambda x: x["corrections"], reverse=True,
    )[:10]

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
            "icon": "\uD83C\uDF00",
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
                for sp in spirals[:3]
            ],
        })

    # 2. Marathon sessions
    marathon_sessions = [s for s in sessions if s.message_count >= 100]
    if marathon_sessions:
        marathon_tokens = sum(s.total_tokens for s in marathon_sessions)
        patterns.append({
            "pattern": "Marathon Sessions",
            "icon": "\uD83C\uDFC3",
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
            "icon": "\uD83C\uDF2B\uFE0F",
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
            "icon": "\uD83D\uDDC4\uFE0F",
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
            "icon": "\uD83D\uDD01",
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

    # Cost by model
    cost_by_model: list[dict[str, Any]] = []
    for model_id, usage in model_usage.items():
        pricing = _match_model_pricing(model_id)
        model_cost = (
            usage.get("inputTokens", 0) / 1_000_000 * pricing["input"]
            + usage.get("outputTokens", 0) / 1_000_000 * pricing["output"]
            + usage.get("cacheReadInputTokens", 0) / 1_000_000 * pricing["cache_read"]
            + usage.get("cacheCreationInputTokens", 0) / 1_000_000 * pricing["cache_create"]
        )
        total_tokens = (
            usage.get("inputTokens", 0)
            + usage.get("outputTokens", 0)
            + usage.get("cacheReadInputTokens", 0)
        )
        cost_by_model.append({
            "model": model_id,
            "cost": round(model_cost, 2),
            "tokens": total_tokens,
        })
    cost_by_model.sort(key=lambda x: x["cost"], reverse=True)

    # Estimated waste: tokens from marathon session tails (messages after 50)
    estimated_waste = 0.0
    for s in sessions:
        if s.message_count > 50:
            # After 50 messages, roughly estimate tail fraction as wasted
            tail_fraction = (s.message_count - 50) / s.message_count
            estimated_waste += s.estimated_cost_usd * tail_fraction * 0.5

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
            # Context efficiency = tool_calls / messages (how much exploration per message)
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
        # Sessions where user sent >50 messages (context likely degraded)
        bloated_sessions = sum(1 for s in sessions if s.message_count > 50)
        # Cost efficiency: cost per useful message
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

            # Per-model cache rate
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

        # Overall cache rate
        overall_input = total_input + total_cache_read
        overall_cache_rate = (
            (total_cache_read / overall_input * 100)
            if overall_input > 0 else 0
        )

        # Output/input ratio (code generation intensity)
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
        except Exception:
            pass

    return profile


def format_profile_for_prompt(profile: dict[str, Any]) -> str:
    """Format user profile as readable text for the LLM prompt."""
    lines = []

    # Active tools
    lines.append("### Active Tools")
    for t in profile.get("active_tools", []):
        lines.append(
            f"- **{t['display_name']}**: {t['sessions']} sessions, "
            f"{t['messages']:,} messages, {t['tokens']:,} tokens, "
            f"${t['cost']:.2f} cost ({t['status']})"
        )
    lines.append(
        f"- **Totals**: {profile.get('total_tokens', 0):,} tokens, "
        f"${profile.get('total_cost', 0):.2f} cost"
    )

    # Session patterns
    lines.append("\n### Session Patterns")
    lines.append(
        f"- Total sessions: {profile.get('session_count', 0)}"
    )
    avg = profile.get("avg_messages_per_session", 0)
    lines.append(f"- Average messages/session: {avg:.1f}")
    lines.append(
        f"- Max session length: "
        f"{profile.get('max_session_messages', 0)} messages"
    )
    dist = profile.get("session_distribution", {})
    if dist:
        lines.append(
            f"- Distribution: {dist.get('short_under_10', 0)} short, "
            f"{dist.get('medium_10_to_50', 0)} medium, "
            f"{dist.get('long_50_plus', 0)} long, "
            f"{dist.get('marathon_100_plus', 0)} marathon (100+)"
        )
    ratio = profile.get("tool_call_ratio")
    if ratio is not None:
        lines.append(f"- Tool call ratio: {ratio}x (calls per message)")

    # Projects (with per-project detail)
    project_details = profile.get("project_details")
    if project_details:
        lines.append(f"\n### Projects ({profile.get('project_count', 0)} total)")
        for name, pd in list(project_details.items())[:10]:
            lines.append(f"\n**{name}**:")
            lines.append(f"  - {pd['sessions']} sessions, {pd['tokens']:,} tokens, ${pd['cost']:.2f} cost")
            lines.append(f"  - {pd['messages']} messages, {pd['tool_calls']} tool calls")
            lines.append(f"  - Tools: {', '.join(pd['tools'])}")
            if pd.get("intents"):
                top_intents = sorted(pd["intents"].items(), key=lambda x: x[1], reverse=True)[:3]
                lines.append(f"  - Work types: {', '.join(f'{i}({c})' for i, c in top_intents)}")
            if pd.get("sample_prompts"):
                lines.append(f"  - Sample prompts: {' | '.join(pd['sample_prompts'])}")
    elif profile.get("top_projects"):
        lines.append(f"\n### Projects ({profile.get('project_count', 0)} total)")
        for p, count in list(profile["top_projects"].items())[:10]:
            lines.append(f"- {p}: {count} sessions")

    # Intent distribution
    intents = profile.get("intent_distribution")
    if intents:
        lines.append("\n### Work Intent Distribution")
        total = sum(intents.values())
        for intent, count in sorted(
            intents.items(), key=lambda x: x[1], reverse=True
        ):
            pct = count / total * 100 if total > 0 else 0
            lines.append(f"- {intent}: {count} ({pct:.0f}%)")

    # Temporal
    peak = profile.get("peak_hour")
    if peak is not None:
        lines.append(f"\n### Temporal: Peak hour = {peak}:00")

    # Model usage
    mu = profile.get("model_usage")
    if mu:
        lines.append("\n### Model Usage")
        lines.append(
            f"- Overall cache hit rate: {mu['overall_cache_hit_rate']}%"
        )
        lines.append(
            f"- Output/input ratio: {mu['output_to_input_ratio']}%"
        )
        lines.append(f"- Models used: {mu['model_count']}")
        for mid, info in mu.get("models", {}).items():
            lines.append(
                f"  - {mid}: {info['total_tokens']:,} tokens "
                f"(cache: {info['cache_hit_rate']}%)"
            )

    # Context engineering metrics
    ce = profile.get("context_engineering")
    if ce:
        lines.append("\n### Context Engineering")
        lines.append(f"- Avg tokens per message: {ce['avg_tokens_per_message']:,}")
        lines.append(f"- Avg tool calls per session: {ce['avg_tool_calls_per_session']}")
        lines.append(f"- Bloated sessions (>50 msgs): {ce['bloated_sessions']} ({ce['bloated_pct']}%)")
        lines.append(f"- Cost per message: ${ce['cost_per_message']:.4f}")
        lines.append(f"- Total messages: {ce['total_messages']:,}, total cost: ${ce['total_cost']:.2f}")

    # Prompt analysis
    pa = profile.get("prompt_analysis")
    if pa:
        pld = pa.get("prompt_length_distribution", {})
        lines.append("\n### Prompt Analysis")
        lines.append(
            f"- Length distribution: {pld.get('commands_under_20', 0)} commands, "
            f"{pld.get('short_20_100', 0)} short, "
            f"{pld.get('detailed_100_500', 0)} detailed, "
            f"{pld.get('very_detailed_500_plus', 0)} very detailed"
        )
        lines.append(f"- Specificity score: {pa.get('specificity_score', 0)}% (prompts >= 100 chars)")
        lines.append(f"- Avg prompt length: {pld.get('avg_length', 0)} chars")
        sc = pa.get("slash_commands", {})
        if sc:
            lines.append(f"- Slash commands: {', '.join(f'{k}({v}x)' for k, v in sc.items())}")
        spirals = pa.get("correction_spirals", [])
        if spirals:
            lines.append(f"- Correction spirals: {len(spirals)} sessions with 3+ corrections")
        repeated = pa.get("repeated_prompts", [])
        if repeated:
            lines.append(f"- Repeated prompts: {len(repeated)} prompts used 3+ times (skill candidates)")

    # Detected anti-patterns
    aps = profile.get("anti_patterns")
    if aps:
        lines.append("\n### Detected Anti-Patterns")
        for ap in aps:
            lines.append(f"- **{ap['pattern']}** [{ap['severity']}]: {ap['detail']}")

    # Cost forensics
    cf = profile.get("cost_forensics")
    if cf:
        lines.append("\n### Cost Forensics")
        lines.append(f"- Total cost: ${cf.get('total_cost', 0):.2f}")
        lines.append(f"- Estimated waste: ${cf.get('estimated_waste', 0):.2f} ({cf.get('waste_pct', 0)}%)")
        top_projects = cf.get("cost_by_project", [])[:5]
        if top_projects:
            lines.append("- Top projects by cost: " + ", ".join(
                f"{p['project']}(${p['cost']:.2f})" for p in top_projects
            ))

    # Recent session details (top by token usage)
    sd = profile.get("session_details")
    if sd:
        lines.append(f"\n### Top Sessions by Token Usage (showing {len(sd)})")
        for s in sd[:10]:
            lines.append(
                f"- **{s['project']}** [{s['intent']}] via {s['tool']}: "
                f"{s['messages']} msgs, {s['tokens']:,} tokens, ${s['cost']:.2f}, "
                f"context_ratio={s['context_ratio']}x"
            )
            if s.get("first_prompt"):
                lines.append(f"  First prompt: \"{s['first_prompt']}\"")

    # Lifetime
    lt = profile.get("claude_lifetime")
    if lt:
        lines.append("\n### Claude Code Lifetime Stats")
        lines.append(
            f"- Total sessions: {lt.get('total_sessions', 0)}"
        )
        lines.append(
            f"- Total messages: {lt.get('total_messages', 0)}"
        )
        first = lt.get("first_session")
        if first:
            lines.append(f"- First session: {first}")

    return "\n".join(lines)


def format_tool_knowledge(active_tool_ids: set[str]) -> str:
    """Format only the knowledge for tools the user actually uses."""
    lines = []
    for tool_id, kb in KNOWLEDGE_BASE.items():
        if tool_id not in active_tool_ids:
            continue
        lines.append(f"\n### {kb['display_name']}")

        lines.append("\n**Key Features:**")
        for f in kb["features"]:
            lines.append(f"- **{f['name']}**: {f['description']}")

        lines.append("\n**Common Anti-Patterns:**")
        for ap in kb["anti_patterns"]:
            lines.append(f"- {ap}")

        benchmarks = kb.get("cost_benchmarks")
        if benchmarks:
            lines.append("\n**Cost Benchmarks:**")
            for k, v in benchmarks.items():
                lines.append(f"- {k}: {v}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main optimizer class
# ---------------------------------------------------------------------------


class AIUsageOptimizer:
    """Analyzes usage patterns and generates optimization recommendations.

    Primary path: LLM analyzes user profile + knowledge base.
    Fallback: data-driven heuristic analysis (no hardcoded guesses).
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
    ) -> dict[str, Any]:
        """Run optimization analysis.

        1. Build rich user profile from real data
        2. Try LLM analysis with profile + knowledge base
        3. Fall back to data-driven heuristics if LLM unavailable
        """
        # Build the user profile from real data
        profile = build_user_profile(
            stats, sessions, model_usage, self._claude,
        )

        # Always include the profile in the response
        result = self._try_llm_analysis(profile, stats)
        result["profile_summary"] = {
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
        }
        return result

    def _llm_not_available_error(self, message: str) -> dict[str, Any]:
        """Return an error result when no LLM is available."""
        return {
            "error": message,
            "source": "none",
            "setup_hint": (
                "The optimizer requires an LLM. Quickest setup:\n\n"
                "  brew install ollama\n"
                "  ollama pull qwen3:1.7b\n"
                "  ollama serve\n\n"
                "Then refresh and try again."
            ),
        }

    def _try_llm_analysis(
        self,
        profile: dict[str, Any],
        stats: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Run LLM-powered analysis. Requires a configured LLM."""
        if not is_llm_configured(self._config.llm):
            return self._llm_not_available_error(
                "No LLM configured. Set up Ollama (free, local) or a cloud provider."
            )

        llm_err = check_llm_available(self._config.llm)
        if llm_err:
            return self._llm_not_available_error(llm_err)

        # Build the prompt with real data
        active_tool_ids = {
            t["tool"] for t in profile.get("active_tools", [])
        }
        profile_text = format_profile_for_prompt(profile)
        tool_knowledge = format_tool_knowledge(active_tool_ids)
        universal = "\n".join(
            f"- {p}" for p in UNIVERSAL_PRACTICES
        )

        prompt = OPTIMIZER_PROMPT.format(
            user_profile=profile_text,
            tool_knowledge=tool_knowledge,
            universal_practices=universal,
        )

        raw = get_completion(
            prompt,
            self._config.llm,
            system=(
                "You are an expert AI coding tool optimizer. "
                "Analyze REAL usage data. Be specific and data-driven. "
                "Return ONLY valid JSON."
            ),
            max_tokens=4000,
        )

        if raw.startswith("[error]"):
            return self._llm_not_available_error(raw)

        try:
            cleaned = raw.strip()
            # Strip markdown code fences
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            parsed = json.loads(cleaned.strip())
            parsed["source"] = "llm"
            return parsed
        except (json.JSONDecodeError, IndexError, KeyError):
            return self._llm_not_available_error(
                "LLM returned invalid response. Try again or switch models."
            )

