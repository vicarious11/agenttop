"""Recommendation engine — generates actionable suggestions."""

from __future__ import annotations

from agenttop.analysis.engine import get_completion
from agenttop.config import LLMConfig
from agenttop.formatting import human_tokens
from agenttop.models import Session, Suggestion

RECOMMEND_PROMPT = """You are a developer productivity expert analyzing AI coding tool usage.

Given these session patterns:
{patterns}

And these real usage metrics:
{metrics}

And these workflow insights:
{insights}

Generate 3-5 specific, actionable recommendations to:
1. Reduce wasted tokens (exploration, repeated reads, context overflow)
2. Lower costs (model selection, caching, smaller sessions)
3. Improve workflow efficiency

For each recommendation, provide:
- Title (short, action-oriented)
- Description (1-2 sentences, specific with real numbers)
- Estimated savings (tokens or percentage)
- Priority (high/medium/low)

Format as JSON array:
[{{"title": "...", "description": "...", "savings": "...", "priority": "high"}}]"""


def generate_recommendations_llm(
    sessions: list[Session],
    insights: list[str],
    config: LLMConfig,
    claude_collector=None,
) -> list[Suggestion]:
    """Generate recommendations using LLM with real data."""
    patterns = []
    tool_stats: dict[str, dict] = {}
    for s in sessions:
        tool = s.tool.value
        if tool not in tool_stats:
            tool_stats[tool] = {"sessions": 0, "messages": 0, "tool_calls": 0}
        tool_stats[tool]["sessions"] += 1
        tool_stats[tool]["messages"] += s.message_count
        tool_stats[tool]["tool_calls"] += s.tool_call_count

    for tool, stats in tool_stats.items():
        patterns.append(
            f"- {tool}: {stats['sessions']} sessions, "
            f"{stats['messages']} messages, {stats['tool_calls']} tool calls"
        )

    # Build real metrics section from stats-cache data
    metrics_lines = []
    if claude_collector:
        model_usage = claude_collector.get_model_usage()
        for model_id, usage in model_usage.items():
            cache_read = usage.get("cacheReadInputTokens", 0)
            input_t = usage.get("inputTokens", 0)
            output_t = usage.get("outputTokens", 0)
            cache_create = usage.get("cacheCreationInputTokens", 0)
            total_input = cache_read + input_t
            hit_rate = (cache_read / total_input * 100) if total_input > 0 else 0
            metrics_lines.append(
                f"- {model_id}: input={human_tokens(input_t)}, "
                f"output={human_tokens(output_t)}, "
                f"cache_read={human_tokens(cache_read)}, "
                f"cache_create={human_tokens(cache_create)}, "
                f"cache_hit={hit_rate:.0f}%"
            )

        summary = claude_collector.get_session_summary()
        metrics_lines.append(
            f"- Total: {summary.get('totalSessions', 0)} sessions, "
            f"{summary.get('totalMessages', 0):,} messages"
        )

        hour_counts = claude_collector.get_hour_counts()
        if hour_counts:
            peak = max(hour_counts, key=lambda h: hour_counts[h])
            metrics_lines.append(
                f"- Peak hour: {peak}:00 ({hour_counts[peak]} sessions)"
            )

    result = get_completion(
        RECOMMEND_PROMPT.format(
            patterns="\n".join(patterns),
            metrics="\n".join(metrics_lines) if metrics_lines else "No detailed metrics available",
            insights="\n".join(f"- {i}" for i in insights),
        ),
        config,
        max_tokens=1024,
    )

    if result.startswith("[error]"):
        return []

    import json

    try:
        items = json.loads(result)
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        start = result.find("[")
        end = result.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                items = json.loads(result[start:end])
            except json.JSONDecodeError:
                return []
        else:
            return []

    priority_map = {"high": 2, "medium": 1, "low": 0}
    suggestions = []
    for item in items:
        suggestions.append(
            Suggestion(
                category="llm_analysis",
                title=item.get("title", "Recommendation"),
                description=item.get("description", ""),
                estimated_savings=item.get("savings"),
                priority=priority_map.get(item.get("priority", "low"), 0),
            )
        )
    return suggestions
