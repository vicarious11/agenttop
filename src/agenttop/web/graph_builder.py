"""Build a D3-compatible knowledge graph showing information flow."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from agenttop.collectors.base import BaseCollector
from agenttop.collectors.claude import ClaudeCodeCollector
from agenttop.collectors.cursor import CursorCollector

TOOL_COLORS: dict[str, str] = {
    "claude_code": "#ff6b00",
    "cursor": "#00fff5",
    "kiro": "#00ff88",
    "copilot": "#4488ff",
    "codex": "#ff00ff",
    "windsurf": "#ffee00",
    "continue": "#ff4444",
    "aider": "#ffffff",
    "generic": "#888888",
}

MODEL_COLORS: dict[str, str] = {
    "opus": "#ff6b00",
    "sonnet": "#ff9944",
    "haiku": "#ffcc88",
    "glm": "#00ff88",
}

TOKENS_PER_MSG_ESTIMATE = 800


def _model_display_name(model_id: str) -> str:
    """Turn 'claude-opus-4-5-20251101' into 'Opus 4.5'."""
    mid = model_id.lower()
    if "opus" in mid:
        ver = _extract_version(mid, "opus")
        return f"Opus {ver}" if ver else "Opus"
    if "sonnet" in mid:
        ver = _extract_version(mid, "sonnet")
        return f"Sonnet {ver}" if ver else "Sonnet"
    if "haiku" in mid:
        ver = _extract_version(mid, "haiku")
        return f"Haiku {ver}" if ver else "Haiku"
    if "glm" in mid:
        m = re.search(r"glm[- ]?(\d+\.?\d*)", mid)
        return f"GLM {m.group(1)}" if m else "GLM"
    return model_id


def _extract_version(mid: str, family: str) -> str:
    idx = mid.index(family) + len(family)
    rest = mid[idx:].lstrip("-")
    m = re.match(r"(\d+)[.-](\d+)", rest)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    return ""


def _short_model(name: str) -> str:
    """Shorten cursor model names like 'claude-3.5-sonnet' → 'Sonnet 3.5'."""
    low = name.lower()
    for fam in ("opus", "sonnet", "haiku"):
        if fam in low:
            m = re.search(r"(\d+[.\-]?\d*)", low)
            ver = m.group(1).replace("-", ".") if m else ""
            return f"{fam.title()} {ver}".strip()
    if "gpt" in low:
        return name  # keep GPT names as-is
    if "gemini" in low:
        return name
    # Generic: just capitalize
    return name.split("/")[-1] if "/" in name else name


class GraphBuilder:
    """Builds a rich D3 force-graph showing information flow across tools."""

    def __init__(
        self,
        collectors: list[tuple[str, BaseCollector]],
        claude: ClaudeCodeCollector | None = None,
        days: int = 0,
    ) -> None:
        self._collectors = collectors
        self._claude = claude
        self._days = days

    def build(self) -> dict[str, list[dict[str, Any]]]:
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        node_ids: set[str] = set()

        # ── Center node: the developer ──
        nodes.append({
            "id": "you",
            "type": "center",
            "label": "You",
            "value": 0,
            "color": "#ffffff",
            "status": "active",
            "layer": 0,
        })
        node_ids.add("you")

        total_value = 0

        # ── Tool nodes: ALL tools with any activity ──
        for name, collector in self._collectors:
            if not collector.is_available():
                continue
            tool_id = collector.tool_name.value
            stats = collector.get_stats(days=self._days)

            tokens = stats.tokens_today
            messages = stats.messages_today
            sessions = stats.sessions_today

            if tokens == 0 and messages == 0 and sessions == 0:
                continue

            # Activity value: tokens > messages > sessions
            if tokens > 0:
                activity = tokens
            elif messages > 0:
                activity = messages * TOKENS_PER_MSG_ESTIMATE
            elif sessions > 0:
                activity = sessions * 2000
            else:
                continue
            total_value += activity

            nodes.append({
                "id": tool_id,
                "type": "tool",
                "label": name,
                "value": activity,
                "color": TOOL_COLORS.get(tool_id, "#888888"),
                "status": stats.status,
                "sessions": sessions,
                "messages": messages,
                "tokens": tokens,
                "cost": stats.estimated_cost_today,
                "layer": 1,
            })
            node_ids.add(tool_id)

            # Edge: You → Tool
            if tokens > 0:
                edges.append({
                    "source": "you",
                    "target": tool_id,
                    "value": activity,
                    "label": f"{tokens:,} tokens",
                    "edgeType": "token_flow",
                })
            elif messages > 0:
                edges.append({
                    "source": "you",
                    "target": tool_id,
                    "value": activity,
                    "label": f"{messages:,} messages",
                    "edgeType": "message_flow",
                })
            elif sessions > 0:
                edges.append({
                    "source": "you",
                    "target": tool_id,
                    "value": sessions * 2000,
                    "label": f"{sessions} sessions",
                    "edgeType": "message_flow",
                })

            # ── Cursor-specific: models and code ratio ──
            if isinstance(collector, CursorCollector):
                self._add_cursor_data(
                    collector, tool_id, nodes, edges, node_ids,
                )

        nodes[0]["value"] = total_value

        # ── Claude model breakdown ──
        if self._claude and self._claude.is_available():
            self._add_claude_models(nodes, edges, node_ids)

        # ── Projects across all tools ──
        self._add_projects(nodes, edges, node_ids)

        return {"nodes": nodes, "edges": edges}

    # ─────────────────────────────────────────────────────────
    #  Claude model nodes
    # ─────────────────────────────────────────────────────────
    def _add_claude_models(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        node_ids: set[str],
    ) -> None:
        model_usage = self._claude.get_model_usage()
        for model_id, usage in model_usage.items():
            inp = usage.get("inputTokens", 0)
            out = usage.get("outputTokens", 0)
            cache_read = usage.get("cacheReadInputTokens", 0)
            cache_create = usage.get("cacheCreationInputTokens", 0)
            # Use billed tokens (input + output) for sizing — NOT cache
            billed = inp + out
            if billed == 0:
                continue

            color = "#ff9944"
            for family, c in MODEL_COLORS.items():
                if family in model_id.lower():
                    color = c
                    break

            display = _model_display_name(model_id)
            mid = f"model-{model_id}"

            if mid not in node_ids:
                nodes.append({
                    "id": mid,
                    "type": "model",
                    "label": display,
                    "value": billed,
                    "color": color,
                    "status": "active",
                    "inputTokens": inp,
                    "outputTokens": out,
                    "cacheRead": cache_read,
                    "cacheCreate": cache_create,
                    "layer": 2,
                })
                node_ids.add(mid)

            if "claude_code" in node_ids:
                edges.append({
                    "source": "claude_code",
                    "target": mid,
                    "value": billed,
                    "label": display,
                    "edgeType": "model_usage",
                })

    # ─────────────────────────────────────────────────────────
    #  Cursor-specific: models used, code sources, AI ratio
    # ─────────────────────────────────────────────────────────
    def _add_cursor_data(
        self,
        collector: CursorCollector,
        tool_id: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        node_ids: set[str],
    ) -> None:
        # Models used by Cursor (from ai_code_hashes events)
        try:
            events = collector.collect_events()
        except Exception:
            events = []

        model_counts: dict[str, int] = defaultdict(int)
        source_counts: dict[str, int] = defaultdict(int)
        file_ext_counts: dict[str, int] = defaultdict(int)

        for event in events:
            if not event.data:
                continue
            model = event.data.get("model", "")
            if model:
                model_counts[model] += 1
            source = event.data.get("source", "")
            if source:
                source_counts[source] += 1
            fname = event.data.get("file", "")
            if fname and "." in fname:
                ext = fname.rsplit(".", 1)[-1].lower()
                file_ext_counts[ext] += 1

        # Add cursor model nodes (top 4)
        for model, count in sorted(
            model_counts.items(), key=lambda x: x[1], reverse=True
        )[:4]:
            display = _short_model(model)
            mid = f"cmodel-{model}"
            val = count * TOKENS_PER_MSG_ESTIMATE

            if mid not in node_ids:
                nodes.append({
                    "id": mid,
                    "type": "model",
                    "label": display,
                    "value": val,
                    "color": "#00fff5",
                    "status": "active",
                    "uses": count,
                    "layer": 2,
                })
                node_ids.add(mid)

            edges.append({
                "source": tool_id,
                "target": mid,
                "value": val,
                "label": f"{count:,} uses",
                "edgeType": "model_usage",
            })

        # Add source-type nodes (tab completion, composer, etc.)
        for source, count in sorted(
            source_counts.items(), key=lambda x: x[1], reverse=True
        )[:3]:
            sid = f"csrc-{source}"
            val = count * 200

            if sid not in node_ids:
                label_map = {
                    "tab": "Tab Complete",
                    "composer": "Composer",
                    "chat": "Chat",
                    "inline": "Inline Edit",
                    "terminal": "Terminal",
                }
                nodes.append({
                    "id": sid,
                    "type": "feature",
                    "label": label_map.get(source, source.title()),
                    "value": val,
                    "color": "#00fff5",
                    "status": "active",
                    "count": count,
                    "layer": 2,
                })
                node_ids.add(sid)

            edges.append({
                "source": tool_id,
                "target": sid,
                "value": val,
                "label": f"{count:,}",
                "edgeType": "feature_usage",
            })

        # AI vs Human code ratio
        try:
            ratio = collector.get_ai_vs_human_ratio()
        except Exception:
            ratio = None

        if ratio:
            ai = ratio.get("ai_lines", 0)
            human = ratio.get("human_lines", 0)
            total = ai + human
            if total > 0:
                pct = ratio.get("ai_percentage", 0)
                aid = "ai-code-ratio"
                nodes.append({
                    "id": aid,
                    "type": "metric",
                    "label": f"AI Code {pct:.0f}%",
                    "value": ai * 10,
                    "color": "#00ff88",
                    "status": "active",
                    "ai_lines": ai,
                    "human_lines": human,
                    "ai_pct": pct,
                    "layer": 2,
                })
                node_ids.add(aid)
                edges.append({
                    "source": tool_id,
                    "target": aid,
                    "value": ai * 10,
                    "label": f"{ai:,} AI lines",
                    "edgeType": "code_gen",
                })

    # ─────────────────────────────────────────────────────────
    #  Projects: connect to ALL tools that work on them
    # ─────────────────────────────────────────────────────────
    def _add_projects(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        node_ids: set[str],
    ) -> None:
        project_tokens: dict[str, int] = defaultdict(int)
        project_tools: dict[str, set[str]] = defaultdict(set)

        cutoff = (
            datetime.now() - timedelta(days=self._days)
            if self._days > 0
            else datetime(2000, 1, 1)
        )

        for _, collector in self._collectors:
            if not collector.is_available():
                continue
            tool_id = collector.tool_name.value
            if tool_id not in node_ids:
                continue
            for session in collector.collect_sessions():
                if session.start_time < cutoff:
                    continue
                if session.project:
                    proj = session.project.split("/")[-1] or session.project
                    project_tokens[proj] += session.total_tokens
                    project_tools[proj].add(tool_id)

        all_projects = sorted(
            project_tokens.items(), key=lambda x: x[1], reverse=True
        )

        for proj_name, tokens in all_projects:
            if tokens == 0:
                continue
            pid = f"proj-{proj_name}"
            tools_using = project_tools.get(proj_name, set())
            multi_tool = len(tools_using) > 1

            if pid not in node_ids:
                nodes.append({
                    "id": pid,
                    "type": "project",
                    "label": proj_name,
                    "value": tokens,
                    "color": "#ffee00" if multi_tool else "#6644ff",
                    "status": "active",
                    "multiTool": multi_tool,
                    "layer": 3,
                })
                node_ids.add(pid)

            # Connect to EVERY tool that works on this project
            for tool_id in tools_using:
                if tool_id in node_ids:
                    edges.append({
                        "source": tool_id,
                        "target": pid,
                        "value": tokens,
                        "label": proj_name,
                        "edgeType": "project_work",
                    })

