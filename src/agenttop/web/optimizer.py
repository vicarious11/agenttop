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
    {{"project": "<name>", "type": "<greenfield/maintenance/debugging/refactoring/exploration>", "insight": "<observation>", "recommendation": "<advice>", "underutilized": "<features>", "recommended_model": {{"model": "<name>", "reason": "<why>"}}}}
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
- Only flag missing features where data gives evidence
- Be specific and actionable, not generic
- Return ONLY the JSON object, no markdown fences, no explanation
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
                    {"name": f["name"], "impact": f["impact"]}
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
    ) -> dict[str, Any]:
        """Run optimization analysis.

        1. Build rich user profile from real data
        2. Compute deterministic metrics (anti-patterns, costs, etc.)
        3. Send structured JSON to LLM for intelligent analysis
        4. Merge Python metrics + LLM analysis into final response
        """
        # Build the user profile from real data
        profile = build_user_profile(
            stats, sessions, model_usage, self._claude,
        )

        # Get LLM analysis
        llm_result = self._get_llm_analysis(profile)

        # Merge: Python-computed metrics (always accurate) + LLM intelligence
        result = self._merge_results(profile, llm_result)
        return result

    def _get_llm_analysis(
        self,
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        """Get LLM-powered analysis. Returns parsed JSON or error dict."""
        active_tool_ids = {
            t["tool"] for t in profile.get("active_tools", [])
        }

        # Build structured JSON input for the LLM
        llm_input = _build_llm_input(profile, active_tool_ids)
        input_json = json.dumps(llm_input, indent=2, default=str)

        prompt = OPTIMIZER_PROMPT.format(input_json=input_json)

        raw = get_completion(
            prompt,
            self._config.llm,
            system=(
                "You are an expert AI coding tool optimizer. "
                "Analyze the structured usage data and return ONLY valid JSON. "
                "No markdown fences, no explanation — just the JSON object."
            ),
            max_tokens=4000,
        )

        if raw.startswith("[error]"):
            return {"error": raw, "source": "error"}

        try:
            cleaned = raw.strip()
            # Strip markdown code fences if present
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            parsed = json.loads(cleaned.strip())
            parsed["source"] = "llm"
            return parsed
        except (json.JSONDecodeError, IndexError, KeyError):
            return {
                "error": "LLM returned invalid JSON. Try again or switch models.",
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
