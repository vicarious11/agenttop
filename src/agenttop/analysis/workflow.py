"""Workflow pattern analysis."""

from __future__ import annotations

from agenttop.analysis.engine import get_completion
from agenttop.config import LLMConfig
from agenttop.formatting import human_duration_ms, human_tokens
from agenttop.models import Session

WORKFLOW_PROMPT = """\
Analyze these AI coding assistant session summaries and identify workflow patterns.

Sessions:
{sessions}

For each pattern found, provide:
1. What the pattern is
2. Whether it's efficient or wasteful
3. A specific, actionable recommendation

Be concise. Focus on the top 3-5 most impactful patterns.
Format as bullet points."""


def analyze_workflow_llm(sessions: list[Session], config: LLMConfig) -> list[str]:
    """Analyze workflow patterns using LLM."""
    session_summaries = []
    for s in sessions[:20]:  # Limit to avoid huge prompts
        prompts_str = "; ".join(p[:80] for p in s.prompts[:5])
        session_summaries.append(
            f"- Tool: {s.tool.value}, Project: {s.project or 'unknown'}, "
            f"Messages: {s.message_count}, Tool calls: {s.tool_call_count}, "
            f"Prompts: {prompts_str}"
        )

    if not session_summaries:
        return ["No sessions to analyze."]

    result = get_completion(
        WORKFLOW_PROMPT.format(sessions="\n".join(session_summaries)),
        config,
        max_tokens=512,
    )

    if result.startswith("[error]"):
        return [result]

    # Parse bullet points
    insights = []
    for line in result.strip().split("\n"):
        line = line.strip().lstrip("-•*").strip()
        if line and len(line) > 10:
            insights.append(line)
    return insights or ["No significant patterns detected."]


def analyze_workflow_local(sessions: list[Session]) -> list[str]:
    """Analyze workflow patterns using local heuristics."""
    insights = []

    if not sessions:
        return ["No sessions collected yet. Use your AI tools and check back."]

    # Check for very long sessions
    long_sessions = [s for s in sessions if s.message_count > 100]
    if long_sessions:
        insights.append(
            f"{len(long_sessions)} sessions with 100+ messages detected. "
            "Long sessions lose context — try /compact or start fresh sub-sessions."
        )

    # Check for repeated project exploration
    project_counts: dict[str, int] = {}
    for s in sessions:
        p = s.project or "unknown"
        project_counts[p] = project_counts.get(p, 0) + 1

    for project, count in project_counts.items():
        if count > 5:
            insights.append(
                f"Project '{project.split('/')[-1]}' has {count} sessions. "
                "Add a CLAUDE.md with architecture notes to avoid re-exploring."
            )

    # Tool usage distribution
    tool_counts: dict[str, int] = {}
    for s in sessions:
        tool_counts[s.tool.value] = tool_counts.get(s.tool.value, 0) + 1

    if len(tool_counts) > 1:
        dominant = max(tool_counts, key=lambda k: tool_counts[k])
        insights.append(
            f"Primary tool: {dominant} ({tool_counts[dominant]} sessions). "
            f"Also using: {', '.join(k for k in tool_counts if k != dominant)}."
        )

    # Check for high tool call ratios
    high_tool_sessions = [s for s in sessions if s.tool_call_count > s.message_count * 3]
    if high_tool_sessions:
        insights.append(
            f"{len(high_tool_sessions)} sessions with very high tool call ratios. "
            "This usually means heavy file exploration — add key paths to project memory."
        )

    return insights or ["Workflow looks healthy. No significant issues detected."]


def generate_data_insights(collector) -> list[str]:
    """Generate insights from real stats-cache data (model usage, cache, temporal)."""
    insights = []
    model_usage = collector.get_model_usage()
    summary = collector.get_session_summary()

    # Cache efficiency
    for model_id, usage in model_usage.items():
        cache_read = usage.get("cacheReadInputTokens", 0)
        input_t = usage.get("inputTokens", 0)
        total_input = cache_read + input_t
        if total_input > 0 and cache_read > 0:
            ratio = cache_read / total_input * 100
            short = model_id.split("-")
            if short and len(short[-1]) >= 8 and short[-1].isdigit():
                short = short[:-1]
            name = "-".join(short)
            if name.startswith("claude-"):
                name = name[7:]
            insights.append(f"{name}: {ratio:.0f}% cache hit rate ({human_tokens(cache_read)} cached)")

    # Session quality
    longest = summary.get("longestSession", {})
    msg_count = longest.get("messageCount", 0)
    if msg_count > 1000:
        duration = human_duration_ms(longest.get("duration", 0))
        insights.append(
            f"Longest session: {msg_count:,} messages ({duration}) — "
            "consider splitting into focused sub-tasks"
        )

    # Model diversity
    if len(model_usage) > 1:
        dominant = max(
            model_usage,
            key=lambda m: sum(v for k, v in model_usage[m].items() if "Tokens" in k),
        )
        insights.append(f"Primary model: {dominant} — {len(model_usage)} models in rotation")

    # Temporal patterns
    hour_counts = collector.get_hour_counts()
    if hour_counts:
        peak_hour = max(hour_counts, key=lambda h: hour_counts[h])
        insights.append(f"Peak productivity: {peak_hour}:00 ({hour_counts[peak_hour]} sessions)")

    return insights
