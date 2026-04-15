"""Deterministic activity classifier — no LLM, uses real tool call data.

Classifies sessions by analyzing actual tool_breakdown (Edit, Bash, Read,
etc.) from collector data. Falls back to prompt keyword matching for tools
that don't provide tool call details.

Also computes one-shot success rate from Edit->correction->Edit patterns.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from agenttop.models import Session

ACTIVITIES = [
    "coding",
    "debugging",
    "testing",
    "exploration",
    "refactoring",
    "git_ops",
    "planning",
    "other",
]

# Tool call name -> activity mapping (Claude Code tool names)
_TOOL_TO_ACTIVITY: dict[str, str] = {
    "Edit": "coding",
    "Write": "coding",
    "NotebookEdit": "coding",
    "MultiEdit": "coding",
    "Read": "exploration",
    "Grep": "exploration",
    "Glob": "exploration",
    "LS": "exploration",
    "LSP": "exploration",
    "WebSearch": "exploration",
    "WebFetch": "exploration",
    "Bash": "coding",  # default, overridden by content
    "Agent": "planning",
    "EnterPlanMode": "planning",
    "ExitPlanMode": "planning",
    "TaskCreate": "planning",
    "TaskUpdate": "planning",
    "TaskGet": "planning",
    "TodoRead": "planning",
    "TodoWrite": "planning",
}

# Prompt keyword patterns (fallback when no tool_breakdown)
_KEYWORD_PATTERNS: list[tuple[list[str], str]] = [
    (["fix", "bug", "error", "issue", "broken", "fail",
      "crash", "debug", "why is", "not working"], "debugging"),
    (["refactor", "rename", "clean", "simplify",
      "restructure", "extract", "move"], "refactoring"),
    (["test", "spec", "coverage", "assert",
      "mock", "fixture", "pytest", "jest"], "testing"),
    (["what", "how", "explain", "show", "find",
      "where", "understand", "search"], "exploration"),
    (["plan", "design", "architect", "strategy",
      "approach", "think about"], "planning"),
    (["git ", "commit", "push", "pull", "merge",
      "branch", "rebase", "cherry"], "git_ops"),
    (["add", "create", "implement", "build",
      "new", "feature", "scaffold"], "coding"),
]


def classify_session(session: Session) -> str:
    """Classify a session into an activity category.

    Uses tool_breakdown (real data) when available,
    falls back to prompt keyword matching.
    """
    tb = session.tool_breakdown

    # If we have real tool call data, use it
    if tb:
        scores: Counter[str] = Counter()
        for tool_name, count in tb.items():
            activity = _TOOL_TO_ACTIVITY.get(tool_name, "other")
            scores[activity] += count

        # Detect debugging from prompts even when we have tool data
        for prompt in session.prompts[:5]:
            lower = prompt.lower()
            debug_kws = [
                "fix", "bug", "error", "broken",
                "fail", "crash", "debug", "not working",
            ]
            if sum(1 for kw in debug_kws if kw in lower) >= 2:
                scores["debugging"] += 5

            # Detect testing from bash-like patterns
            test_kws = [
                "pytest", "test", "jest", "vitest",
                "cargo test", "go test",
            ]
            if any(kw in lower for kw in test_kws):
                scores["testing"] += 3

            # Detect git ops
            git_kws = [
                "git ", "commit", "push", "pull",
                "merge", "rebase",
            ]
            if any(kw in lower for kw in git_kws):
                scores["git_ops"] += 3

            # Detect refactoring
            refactor_kws = [
                "refactor", "rename", "extract",
                "simplify", "move", "restructure",
            ]
            if any(kw in lower for kw in refactor_kws):
                scores["refactoring"] += 3

        if scores:
            return scores.most_common(1)[0][0]
        return "coding"  # has tool calls but no clear category

    # Fallback: keyword matching on prompts
    scores = Counter()
    for prompt in session.prompts:
        lower = prompt.lower()
        for keywords, activity in _KEYWORD_PATTERNS:
            matches = sum(1 for kw in keywords if kw in lower)
            if matches > 0:
                scores[activity] += matches

    if session.tool_call_count > 0 and not scores:
        scores["coding"] = session.tool_call_count

    if not scores:
        return "other"

    return scores.most_common(1)[0][0]


def classify_sessions(sessions: list[Session]) -> dict[str, int]:
    """Classify all sessions and return activity counts."""
    counts: Counter[str] = Counter()
    for s in sessions:
        counts[classify_session(s)] += 1
    for a in ACTIVITIES:
        if a not in counts:
            counts[a] = 0
    return dict(counts.most_common())


def compute_oneshot_rate(sessions: list[Session]) -> float:
    """Compute one-shot success rate.

    Uses tool_breakdown when available:
    - Count Edit/Write calls as "edit turns"
    - Detect retries from prompt correction patterns

    Falls back to prompt keyword analysis.
    Returns percentage 0-100.
    """
    total_edits = 0
    retry_edits = 0

    for session in sessions:
        # Count edits from tool_breakdown if available
        tb = session.tool_breakdown
        if tb:
            edits = tb.get("Edit", 0) + tb.get("Write", 0)
            total_edits += edits
        else:
            # Fallback: count edit-like prompts
            for prompt in session.prompts:
                lower = prompt.lower()
                if any(
                    kw in lower
                    for kw in [
                        "edit", "write", "fix", "change",
                        "update", "modify",
                    ]
                ):
                    total_edits += 1

        # Detect retries from prompt patterns
        prompts = session.prompts
        for i in range(len(prompts) - 1):
            next_lower = prompts[i + 1].lower()
            retry_signals = [
                "no ", "wrong", "that's not", "revert",
                "undo", "try again", "still", "doesn't work",
                "not what", "actually", "wait", "nah",
                "nai", "galat", "sahi nahi",
            ]
            if any(sig in next_lower for sig in retry_signals):
                retry_edits += 1

    if total_edits == 0:
        return 100.0
    return round((1 - retry_edits / max(total_edits, 1)) * 100, 1)


def compute_tool_frequency(
    sessions: list[Session],
) -> dict[str, int]:
    """Aggregate tool call frequency across all sessions."""
    total: Counter[str] = Counter()
    for s in sessions:
        for tool_name, count in s.tool_breakdown.items():
            total[tool_name] += count
    return dict(total.most_common())


def compute_cost_by_project(
    sessions: list[Session],
) -> list[dict[str, Any]]:
    """Cost breakdown by project, sorted by cost descending."""
    projects: dict[str, dict[str, Any]] = {}
    for s in sessions:
        name = (
            s.project.rstrip("/").rsplit("/", 1)[-1]
            if s.project else "unknown"
        )
        if name not in projects:
            projects[name] = {
                "project": name,
                "cost": 0.0,
                "sessions": 0,
                "tokens": 0,
            }
        projects[name]["cost"] += s.estimated_cost_usd
        projects[name]["sessions"] += 1
        projects[name]["tokens"] += s.total_tokens

    result = sorted(
        projects.values(), key=lambda x: x["cost"], reverse=True,
    )
    for p in result:
        p["cost"] = round(p["cost"], 2)
    return result


def compute_cost_by_model(
    model_usage: dict[str, Any],
) -> list[dict[str, Any]]:
    """Cost breakdown by model from model usage data."""
    pricing: dict[str, dict[str, float]] = {
        "opus": {"input": 15, "output": 75, "cache_read": 1.875},
        "sonnet": {"input": 3, "output": 15, "cache_read": 0.375},
        "haiku": {"input": 0.8, "output": 4, "cache_read": 0.08},
    }

    result = []
    for model_id, usage in model_usage.items():
        lower = model_id.lower()
        tier = "sonnet"
        for family in pricing:
            if family in lower:
                tier = family
                break

        p = pricing[tier]
        inp = usage.get("inputTokens", 0)
        out = usage.get("outputTokens", 0)
        cache = usage.get("cacheReadInputTokens", 0)

        cost = (
            inp / 1_000_000 * p["input"]
            + out / 1_000_000 * p["output"]
            + cache / 1_000_000 * p["cache_read"]
        )

        # Short model name
        parts = model_id.split("-")
        if (
            len(parts) > 2
            and len(parts[-1]) >= 8
            and parts[-1].isdigit()
        ):
            parts = parts[:-1]
        short = "-".join(parts)
        if short.startswith("claude-"):
            short = short[7:]

        total_tokens = inp + out + cache
        if total_tokens > 0:
            result.append({
                "model": short,
                "cost": round(cost, 2),
                "tokens": total_tokens,
            })

    return sorted(result, key=lambda x: x["cost"], reverse=True)
