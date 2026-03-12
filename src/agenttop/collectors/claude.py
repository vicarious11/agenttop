"""Claude Code data collector.

Parses data from ~/.claude/:
- stats-cache.json — daily messageCount, sessionCount, toolCallCount
- history.jsonl — every prompt with timestamp + project path
- debug/{session}.txt — debug logs (tool calls, errors)
- projects/*/memory/MEMORY.md — per-project memory files
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from agenttop.collectors.base import BaseCollector
from agenttop.config import CLAUDE_DIR
from agenttop.models import Event, Session, ToolName, ToolStats

# Rough token-per-message estimate when exact counts unavailable
TOKENS_PER_MESSAGE_ESTIMATE = 800
# Approximate cost per token (blended input/output for Sonnet)
COST_PER_TOKEN = 0.000006

# Per-model pricing (USD per million tokens)
MODEL_PRICING = {
    "claude-opus-4-5": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_create": 18.75},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_create": 18.75},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_create": 3.75},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_create": 3.75},
    "claude-haiku-4-5": {"input": 0.8, "output": 4.0, "cache_read": 0.08, "cache_create": 1.0},
    "glm-4.7": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_create": 3.75},
}


def _match_model_pricing(model_id: str) -> dict[str, float]:
    """Match a model ID to its pricing tier (handles version suffixes)."""
    for prefix, pricing in MODEL_PRICING.items():
        if model_id.startswith(prefix):
            return pricing
    # Default to Sonnet pricing for unknown models
    return MODEL_PRICING["claude-sonnet-4-5"]


class ClaudeCodeCollector(BaseCollector):
    """Collects data from Claude Code's local files."""

    def __init__(self, claude_dir: Path | None = None) -> None:
        self._dir = claude_dir or CLAUDE_DIR
        self._last_history_offset: int = 0

    @property
    def tool_name(self) -> ToolName:
        return ToolName.CLAUDE_CODE

    def is_available(self) -> bool:
        return self._dir.exists()

    # -- Stats cache --

    def _parse_stats_cache(self) -> list[dict]:
        """Parse stats-cache.json → list of daily activity dicts."""
        path = self._dir / "stats-cache.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text())
            return data.get("dailyActivity", [])
        except (json.JSONDecodeError, KeyError):
            return []

    # -- History --

    def _parse_history(self) -> list[dict]:
        """Parse history.jsonl → list of prompt records."""
        path = self._dir / "history.jsonl"
        if not path.exists():
            return []
        records = []
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            pass
        return records

    # -- Debug logs --

    def _parse_debug_log(self, path: Path) -> dict:
        """Extract tool calls and errors from a debug log file."""
        tool_calls = 0
        errors = 0
        try:
            text = path.read_text(errors="replace")
            tool_calls = len(re.findall(r"Tool(?:Use|Result|call)", text, re.IGNORECASE))
            errors = len(re.findall(r"(?:error|Error|ERROR)", text))
        except OSError:
            pass
        return {"tool_calls": tool_calls, "errors": errors}

    def _list_debug_sessions(self) -> list[Path]:
        """List debug log files."""
        debug_dir = self._dir / "debug"
        if not debug_dir.exists():
            return []
        return sorted(debug_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)

    # -- Projects / memory --

    def _get_project_memories(self) -> dict[str, str]:
        """Return {project_path: memory_content} for all projects with MEMORY.md."""
        results = {}
        projects_dir = self._dir / "projects"
        if not projects_dir.exists():
            return results
        for memory_file in projects_dir.rglob("MEMORY.md"):
            project_key = str(memory_file.parent.parent.name)
            try:
                results[project_key] = memory_file.read_text()
            except OSError:
                continue
        return results

    # -- Rich stats-cache.json data --

    def _parse_full_stats(self) -> dict:
        """Parse entire stats-cache.json (not just dailyActivity)."""
        path = self._dir / "stats-cache.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def get_model_usage(self) -> dict[str, dict]:
        """Return per-model token breakdown.

        Tries stats-cache.json modelUsage first (legacy).
        Falls back to aggregating usage from project JSONL files (Claude Code v2.x).
        """
        data = self._parse_full_stats()
        cached = data.get("modelUsage", {})
        if cached:
            return cached

        # Derive from project JSONL files
        usage: dict[str, dict] = {}
        for raw in self._parse_project_files():
            model = raw.get("model") or "claude-sonnet-4-6"
            if model not in usage:
                usage[model] = {
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "cacheReadInputTokens": 0,
                    "cacheCreationInputTokens": 0,
                }
            usage[model]["inputTokens"] += raw.get("input_tokens", 0)
            usage[model]["outputTokens"] += raw.get("output_tokens", 0)
            usage[model]["cacheReadInputTokens"] += raw.get("cache_read_tokens", 0)
            usage[model]["cacheCreationInputTokens"] += raw.get("cache_creation_tokens", 0)
        return usage

    def get_daily_model_tokens(self, days: int = 0) -> list[dict]:
        """Return daily per-model token breakdown."""
        data = self._parse_full_stats()
        entries = data.get("dailyModelTokens", [])
        if days > 0:
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            entries = [e for e in entries if e.get("date", "") >= cutoff]
        return entries

    def get_hour_counts(self) -> dict[str, int]:
        """Return session start distribution by hour."""
        data = self._parse_full_stats()
        return data.get("hourCounts", {})

    def get_session_summary(self) -> dict:
        """Return totalSessions, totalMessages, longestSession, firstSessionDate."""
        data = self._parse_full_stats()
        return {
            "totalSessions": data.get("totalSessions", 0),
            "totalMessages": data.get("totalMessages", 0),
            "longestSession": data.get("longestSession", {}),
            "firstSessionDate": data.get("firstSessionDate"),
        }

    def get_real_token_count(self) -> int:
        """Sum actual tokens across all models from modelUsage."""
        total = 0
        for usage in self.get_model_usage().values():
            total += usage.get("inputTokens", 0)
            total += usage.get("outputTokens", 0)
            total += usage.get("cacheReadInputTokens", 0)
        return total

    def get_real_cost(self) -> float:
        """Calculate real cost using per-model pricing from modelUsage."""
        total_cost = 0.0
        for model_id, usage in self.get_model_usage().items():
            pricing = _match_model_pricing(model_id)
            total_cost += usage.get("inputTokens", 0) / 1_000_000 * pricing["input"]
            total_cost += usage.get("outputTokens", 0) / 1_000_000 * pricing["output"]
            total_cost += usage.get("cacheReadInputTokens", 0) / 1_000_000 * pricing["cache_read"]
            total_cost += usage.get("cacheCreationInputTokens", 0) / 1_000_000 * pricing["cache_create"]
        return total_cost

    # -- BaseCollector interface --

    def collect_events(self) -> list[Event]:
        """Collect prompt events from history.jsonl or projects directory."""
        # Legacy path: history.jsonl (only when projects directory unavailable)
        history = self._parse_history()
        if history and not self._project_sessions_available():
            events = []
            for rec in history:
                ts_ms = rec.get("timestamp", 0)
                if not ts_ms:
                    continue
                ts = datetime.fromtimestamp(ts_ms / 1000)
                events.append(
                    Event(
                        tool=ToolName.CLAUDE_CODE,
                        event_type="message",
                        timestamp=ts,
                        project=rec.get("project"),
                        data={"prompt": rec.get("display", "")},
                        token_count=len(rec.get("display", "")) // 4,
                    )
                )
            return events

        # Newer path: ~/.claude/projects/ session files
        events = []
        for s in self._parse_project_files():
            events.append(
                Event(
                    tool=ToolName.CLAUDE_CODE,
                    event_type="message",
                    timestamp=s["start_time"],
                    project=s["project"],
                    data={"prompt": s["prompts"][0] if s["prompts"] else ""},
                    token_count=s["input_tokens"] + s["output_tokens"],
                )
            )
        return events

    def collect_sessions(self) -> list[Session]:
        """Build sessions from history.jsonl or projects directory."""
        # Legacy path: history.jsonl (only when projects directory unavailable)
        history = self._parse_history()
        if history and not self._project_sessions_available():
            sessions: dict[str, Session] = {}
            for rec in history:
                ts_ms = rec.get("timestamp", 0)
                if not ts_ms:
                    continue
                ts = datetime.fromtimestamp(ts_ms / 1000)
                project = rec.get("project", "unknown")
                sid = rec.get("sessionId") or f"claude-{ts.strftime('%Y-%m-%d')}-{project}"

                if sid not in sessions:
                    sessions[sid] = Session(
                        id=sid,
                        tool=ToolName.CLAUDE_CODE,
                        project=project,
                        start_time=ts,
                        end_time=ts,
                        message_count=0,
                        prompts=[],
                    )
                s = sessions[sid]
                s.message_count += 1
                s.end_time = max(s.end_time, ts) if s.end_time else ts
                prompt_text = rec.get("display", "")
                if prompt_text and len(s.prompts) < 50:
                    s.prompts.append(prompt_text)

            # Enrich sessions with token estimates and tool call counts from stats-cache
            daily_stats = {d.get("date"): d for d in self._parse_stats_cache()}
            daily_model_tokens = {d.get("date"): d for d in self.get_daily_model_tokens()}

            sessions_by_day: dict[str, list[Session]] = {}
            for s in sessions.values():
                day = s.start_time.strftime("%Y-%m-%d")
                sessions_by_day.setdefault(day, []).append(s)

            for day, day_sessions in sessions_by_day.items():
                day_msg_total = sum(s.message_count for s in day_sessions)
                dmt = daily_model_tokens.get(day)
                if dmt:
                    day_tokens = sum(dmt.get("tokensByModel", {}).values())
                else:
                    day_tokens = day_msg_total * TOKENS_PER_MESSAGE_ESTIMATE
                ds = daily_stats.get(day)
                day_tool_calls = ds.get("toolCallCount", 0) if ds else 0
                for s in day_sessions:
                    share = s.message_count / day_msg_total if day_msg_total > 0 else 1.0
                    s.total_tokens = int(day_tokens * share)
                    s.tool_call_count = int(day_tool_calls * share)
                    s.estimated_cost_usd = s.total_tokens * COST_PER_TOKEN
            return list(sessions.values())

        # Newer path: ~/.claude/projects/ session files
        result = []
        for raw in self._parse_project_files():
            total_tokens = raw["input_tokens"] + raw["output_tokens"]
            model = raw["model"] or "claude-sonnet-4-5"
            pricing = _match_model_pricing(model)
            cost = (
                raw["input_tokens"] / 1_000_000 * pricing["input"]
                + raw["output_tokens"] / 1_000_000 * pricing["output"]
                + raw["cache_creation_tokens"] / 1_000_000 * pricing["cache_create"]
                + raw["cache_read_tokens"] / 1_000_000 * pricing["cache_read"]
            )
            result.append(
                Session(
                    id=raw["session_id"],
                    tool=ToolName.CLAUDE_CODE,
                    project=raw["project"],
                    start_time=raw["start_time"],
                    end_time=raw["end_time"],
                    message_count=raw["message_count"],
                    tool_call_count=raw["tool_call_count"],
                    total_tokens=total_tokens,
                    estimated_cost_usd=cost,
                    prompts=raw["prompts"],
                )
            )
        return result

    def get_stats(self, days: int = 0) -> ToolStats:
        """Aggregate stats from stats-cache.json / history.jsonl or projects directory.

        Uses stats-cache.json for dates it covers, then supplements with
        live data from history.jsonl for any dates beyond the cache.
        Falls back to the newer ~/.claude/projects/ format when those files
        are absent (Claude Code >= 2.x).

        Args:
            days: Number of days to aggregate. 0 = all available data.
        """
        stats = ToolStats(tool=ToolName.CLAUDE_CODE)

        if days > 0:
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        else:
            cutoff = ""  # no cutoff = all data

        # -- Newer projects-directory path --
        if self._project_sessions_available():
            hourly: list[int] = [0] * 24
            seen_sessions: set[str] = set()
            for raw in self._parse_project_files():
                ts: datetime = raw["start_time"]
                day_str = ts.strftime("%Y-%m-%d")
                if cutoff and day_str < cutoff:
                    continue
                sid = raw["session_id"]
                if sid not in seen_sessions:
                    seen_sessions.add(sid)
                    stats.sessions_today += 1
                stats.messages_today += raw["message_count"]
                stats.tool_calls_today += raw["tool_call_count"]
                tokens = raw["input_tokens"] + raw["output_tokens"]
                stats.tokens_today += tokens
                hourly[ts.hour] += tokens
                model = raw["model"] or "claude-sonnet-4-5"
                pricing = _match_model_pricing(model)
                stats.estimated_cost_today += (
                    raw["input_tokens"] / 1_000_000 * pricing["input"]
                    + raw["output_tokens"] / 1_000_000 * pricing["output"]
                    + raw["cache_creation_tokens"] / 1_000_000 * pricing["cache_create"]
                    + raw["cache_read_tokens"] / 1_000_000 * pricing["cache_read"]
                )
            stats.hourly_tokens = hourly
            if stats.messages_today > 0:
                stats.status = "active"
            return stats

        # -- Legacy path: stats-cache.json + history.jsonl --
        daily = self._parse_stats_cache()
        cache_dates: set[str] = set()
        for day_data in daily:
            date = day_data.get("date", "")
            if date >= cutoff:
                cache_dates.add(date)
                stats.sessions_today += day_data.get("sessionCount", 0)
                stats.messages_today += day_data.get("messageCount", 0)
                stats.tool_calls_today += day_data.get("toolCallCount", 0)

        hourly2: list[int] = [0] * 24
        history_sessions: set[str] = set()
        for rec in self._parse_history():
            ts_ms = rec.get("timestamp", 0)
            if not ts_ms:
                continue
            ts2 = datetime.fromtimestamp(ts_ms / 1000)
            day_str = ts2.strftime("%Y-%m-%d")
            if day_str < cutoff:
                continue
            hourly2[ts2.hour] += TOKENS_PER_MESSAGE_ESTIMATE
            if day_str not in cache_dates:
                stats.messages_today += 1
                sid = rec.get("sessionId", "")
                if sid and sid not in history_sessions:
                    history_sessions.add(sid)
                    stats.sessions_today += 1
        stats.hourly_tokens = hourly2

        if days == 0:
            real_tokens = self.get_real_token_count()
            if real_tokens > 0:
                stats.tokens_today = real_tokens
                stats.estimated_cost_today = self.get_real_cost()
            else:
                stats.tokens_today = stats.messages_today * TOKENS_PER_MESSAGE_ESTIMATE
                stats.estimated_cost_today = stats.tokens_today * COST_PER_TOKEN
        else:
            stats.tokens_today = stats.messages_today * TOKENS_PER_MESSAGE_ESTIMATE
            stats.estimated_cost_today = stats.tokens_today * COST_PER_TOKEN

        if stats.messages_today > 0:
            stats.status = "active"

        if stats.status == "idle":
            debug_files = self._list_debug_sessions()
            if debug_files:
                latest_mtime = debug_files[0].stat().st_mtime
                latest_dt = datetime.fromtimestamp(latest_mtime)
                if (datetime.now() - latest_dt).total_seconds() < 300:
                    stats.status = "active"

        return stats

    def get_daily_history(self, days: int = 30) -> list[dict]:
        """Return daily stats for the last N days."""
        daily = self._parse_stats_cache()
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return [d for d in daily if d.get("date", "") >= cutoff]

    # -- Projects directory (newer Claude Code format) --

    def _parse_project_files(self) -> list[dict]:
        """Parse all session JSONL files from ~/.claude/projects/.

        Handles the newer Claude Code format where each session is stored as
        a JSONL file under ~/.claude/projects/{project-dir}/{session-id}.jsonl
        with per-message records typed 'user' | 'assistant' | 'queue-operation'.
        """
        projects_dir = self._dir / "projects"
        if not projects_dir.exists():
            return []

        all_sessions: dict[str, dict] = {}

        for jsonl_file in projects_dir.rglob("*.jsonl"):
            try:
                with open(jsonl_file, errors="replace") as f:
                    lines = f.readlines()
            except OSError:
                continue

            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue

                rec_type = rec.get("type")
                session_id = rec.get("sessionId", "")
                ts_str = rec.get("timestamp", "")
                if not session_id or not ts_str:
                    continue

                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
                except (ValueError, AttributeError):
                    continue

                if session_id not in all_sessions:
                    all_sessions[session_id] = {
                        "session_id": session_id,
                        "project": rec.get("cwd") or str(jsonl_file.parent.name),
                        "start_time": ts,
                        "end_time": ts,
                        "message_count": 0,
                        "prompts": [],
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cache_creation_tokens": 0,
                        "cache_read_tokens": 0,
                        "tool_call_count": 0,
                        "model": None,
                    }

                s = all_sessions[session_id]
                if ts < s["start_time"]:
                    s["start_time"] = ts
                if ts > s["end_time"]:
                    s["end_time"] = ts

                if rec_type == "user":
                    s["message_count"] += 1
                    cwd = rec.get("cwd")
                    if cwd:
                        s["project"] = cwd
                    msg = rec.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, str) and content and len(s["prompts"]) < 50:
                        s["prompts"].append(content[:500])
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text = item.get("text", "")
                                if text and len(s["prompts"]) < 50:
                                    s["prompts"].append(text[:500])

                elif rec_type == "assistant":
                    msg = rec.get("message", {})
                    usage = msg.get("usage", {})
                    model = msg.get("model", "")
                    if model:
                        s["model"] = model
                    s["input_tokens"] += usage.get("input_tokens", 0)
                    s["output_tokens"] += usage.get("output_tokens", 0)
                    s["cache_creation_tokens"] += usage.get("cache_creation_input_tokens", 0)
                    s["cache_read_tokens"] += usage.get("cache_read_input_tokens", 0)
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "tool_use":
                                s["tool_call_count"] += 1

        return list(all_sessions.values())

    def _project_sessions_available(self) -> bool:
        """True when the newer projects-directory format has session data."""
        projects_dir = self._dir / "projects"
        if not projects_dir.exists():
            return False
        return any(projects_dir.rglob("*.jsonl"))
