# ruff: noqa: E501
"""User profile builder: extracts all real signals from collector data."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from agenttop.models import Session
from agenttop.web.optimizer.analyzer import analyze_anti_patterns, analyze_prompts, build_cost_forensics
from agenttop.web.optimizer.knowledge_base import KNOWLEDGE_BASE


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
    profile["total_tokens"] = sum(t["tokens"] for t in active_tools)
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

        # Tool call ratio
        total_msgs = sum(msg_counts)
        total_tool_calls = sum(s.tool_call_count for s in sessions)
        if total_msgs > 0:
            profile["tool_call_ratio"] = round(
                total_tool_calls / total_msgs, 2
            )

        # Intent keywords
        intent_keywords = {
            "debugging": ["bug", "fix", "error", "debug", "crash", "issue"],
            "refactoring": ["refactor", "rename", "clean", "restructure"],
            "greenfield": ["create", "new", "implement", "build", "add"],
            "exploration": ["what", "how", "explain", "understand", "show"],
            "code_review": ["review", "check", "audit", "look at"],
            "devops": ["deploy", "docker", "ci", "pipeline", "k8s"],
            "documentation": ["doc", "readme", "comment", "describe"],
        }

        # Per-project aggregation
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

        # Intent distribution
        intent_counts: dict[str, int] = defaultdict(int)
        for s in sessions:
            for prompt in s.prompts[:5]:
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

        # Recent session details (top 15 by tokens)
        sorted_sessions = sorted(sessions, key=lambda s: s.total_tokens, reverse=True)
        session_details = []
        for s in sorted_sessions[:15]:
            pname = s.project.split("/")[-1] if s.project else "unknown"
            session_intent = "other"
            for prompt in s.prompts[:3]:
                prompt_lower = prompt.lower()
                for intent, keywords in intent_keywords.items():
                    if any(kw in prompt_lower for kw in keywords):
                        session_intent = intent
                        break
                if session_intent != "other":
                    break
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

        # Deep intelligence
        profile["prompt_analysis"] = analyze_prompts(sessions)
        profile["anti_patterns"] = analyze_anti_patterns(
            sessions, profile["prompt_analysis"],
        )
        profile["cost_forensics"] = build_cost_forensics(
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

    # -- Feature detection --
    if feature_configs:
        profile["feature_detection"] = feature_configs

    return profile


def build_tool_knowledge(active_tool_ids: set[str]) -> dict[str, Any]:
    """Extract relevant knowledge base entries for active tools."""
    tool_knowledge: dict[str, Any] = {}
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
    return tool_knowledge
