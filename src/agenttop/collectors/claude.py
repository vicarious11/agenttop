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
        """Return per-model token breakdown from modelUsage field."""
        data = self._parse_full_stats()
        return data.get("modelUsage", {})

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
        """Collect prompt events from history.jsonl."""
        events = []
        for rec in self._parse_history():
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
                    token_count=len(rec.get("display", "")) // 4,  # rough estimate
                )
            )
        return events

    def collect_sessions(self) -> list[Session]:
        """Build sessions from history.jsonl grouped by real sessionId."""
        sessions: dict[str, Session] = {}
        for rec in self._parse_history():
            ts_ms = rec.get("timestamp", 0)
            if not ts_ms:
                continue
            ts = datetime.fromtimestamp(ts_ms / 1000)
            project = rec.get("project", "unknown")
            # Use real sessionId when available, fall back to project+day for old entries
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
            if prompt_text and len(s.prompts) < 50:  # cap stored prompts
                s.prompts.append(prompt_text)

        # Enrich sessions with token estimates and tool call counts from stats-cache
        daily_stats = {d.get("date"): d for d in self._parse_stats_cache()}
        daily_model_tokens = {d.get("date"): d for d in self.get_daily_model_tokens()}

        # Group sessions by day for proportional allocation
        sessions_by_day: dict[str, list[Session]] = {}
        for s in sessions.values():
            day = s.start_time.strftime("%Y-%m-%d")
            sessions_by_day.setdefault(day, []).append(s)

        for day, day_sessions in sessions_by_day.items():
            # Total messages across all sessions for this day
            day_msg_total = sum(s.message_count for s in day_sessions)

            # Get real token count from dailyModelTokens if available
            dmt = daily_model_tokens.get(day)
            if dmt:
                day_tokens = sum(dmt.get("tokensByModel", {}).values())
            else:
                # Fallback: estimate tokens from message count
                day_tokens = day_msg_total * TOKENS_PER_MESSAGE_ESTIMATE

            # Get tool calls from dailyActivity
            ds = daily_stats.get(day)
            day_tool_calls = ds.get("toolCallCount", 0) if ds else 0

            for s in day_sessions:
                # Proportionally allocate based on message count
                share = s.message_count / day_msg_total if day_msg_total > 0 else 1.0
                s.total_tokens = int(day_tokens * share)
                s.tool_call_count = int(day_tool_calls * share)
                s.estimated_cost_usd = s.total_tokens * COST_PER_TOKEN

        return list(sessions.values())

    def get_stats(self, days: int = 0) -> ToolStats:
        """Aggregate stats from stats-cache.json for the dashboard.

        Args:
            days: Number of days to aggregate. 0 = all available data.
        """
        stats = ToolStats(tool=ToolName.CLAUDE_CODE)
        daily = self._parse_stats_cache()

        if days > 0:
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        else:
            cutoff = ""  # no cutoff = all data

        # Build hourly token estimates from history timestamps
        hourly: list[int] = [0] * 24
        for rec in self._parse_history():
            ts_ms = rec.get("timestamp", 0)
            if not ts_ms:
                continue
            ts = datetime.fromtimestamp(ts_ms / 1000)
            if ts.strftime("%Y-%m-%d") >= cutoff:
                hourly[ts.hour] += TOKENS_PER_MESSAGE_ESTIMATE
        stats.hourly_tokens = hourly

        # Aggregate daily stats within the time range
        for day_data in daily:
            date = day_data.get("date", "")
            if date >= cutoff:
                stats.sessions_today += day_data.get("sessionCount", 0)
                stats.messages_today += day_data.get("messageCount", 0)
                stats.tool_calls_today += day_data.get("toolCallCount", 0)

        # Use real token counts from modelUsage when showing all-time stats,
        # otherwise fall back to message-based estimates for time-filtered views
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

        # Check if recent debug logs show live activity
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
