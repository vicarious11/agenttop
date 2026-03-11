"""Claude Code data collector.

Reads data from ~/.claude/ using TWO sources (in priority order):

1. projects/**/*.jsonl — Per-session conversation logs with exact per-message
   token usage (input_tokens, output_tokens, cache_read, cache_create),
   model IDs, timestamps, tool calls, and project paths.  This is the
   canonical source and exists in all modern Claude Code installations.

2. stats-cache.json + history.jsonl — Legacy/aggregate files that Claude Code
   *may* maintain.  Used as a supplement for data not yet in projects/ (e.g.
   hourly distribution, daily activity that predates the projects/ format).

Token accounting
----------------
- "billed tokens" = input_tokens + output_tokens  (the meaningful usage metric)
- "cache tokens"  = cache_read + cache_create      (shown separately)
- "cost"          = all four components × per-model pricing  (accurate billing)

The previous implementation summed cache_read into the headline token count,
inflating it ~380× (3.8B vs 10M actual).
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from agenttop.collectors.base import BaseCollector
from agenttop.config import CLAUDE_DIR
from agenttop.models import Event, Session, ToolName, ToolStats

logger = logging.getLogger(__name__)

# Fallback estimate when exact counts unavailable (legacy path only)
TOKENS_PER_MESSAGE_ESTIMATE = 800
COST_PER_TOKEN = 0.000006

# Per-model pricing (USD per million tokens)
MODEL_PRICING: dict[str, dict[str, float]] = {
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
    return MODEL_PRICING["claude-sonnet-4-5"]


def _decode_project_path(encoded: str) -> str:
    """Best-effort decode of encoded project dir name to a path.

    NOTE: This encoding is ambiguous — hyphens in real dir names are
    indistinguishable from path separators. Treat result as a fallback
    label only; the authoritative project path comes from the ``cwd``
    field of user entries in the session JSONL.
    """
    return "/" + encoded.lstrip("-").replace("-", "/")


# ── Parsed types from a single JSONL entry ──


class _ParsedMessage:
    """One assistant turn parsed from a session JSONL."""

    __slots__ = (
        "timestamp", "model", "input_tokens", "output_tokens",
        "cache_read", "cache_create", "tool_calls", "content_type",
    )

    def __init__(
        self,
        timestamp: datetime | None,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read: int,
        cache_create: int,
        tool_calls: int,
        content_type: str,
    ) -> None:
        self.timestamp = timestamp
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read = cache_read
        self.cache_create = cache_create
        self.tool_calls = tool_calls
        self.content_type = content_type


class _ParsedSession:
    """Aggregated data for one session (one .jsonl file)."""

    __slots__ = (
        "session_id", "project", "start_time", "end_time",
        "user_messages", "prompts", "messages",
        "input_tokens", "output_tokens", "cache_read", "cache_create",
        "tool_calls", "models_used", "_cwd_set",
    )

    def __init__(self, session_id: str, project: str) -> None:
        self.session_id = session_id
        self.project = project
        self.start_time: datetime | None = None
        self.end_time: datetime | None = None
        self.user_messages: int = 0
        self.prompts: list[str] = []
        self.messages: list[_ParsedMessage] = []
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cache_read: int = 0
        self.cache_create: int = 0
        self.tool_calls: int = 0
        self.models_used: dict[str, int] = defaultdict(int)
        self._cwd_set: bool = False

    @property
    def billed_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def cost(self) -> float:
        """Compute cost using per-message model pricing for accuracy."""
        if self.messages:
            total = 0.0
            for msg in self.messages:
                if msg.model.startswith("<") or msg.model == "unknown":
                    continue
                p = _match_model_pricing(msg.model)
                total += msg.input_tokens / 1_000_000 * p["input"]
                total += msg.output_tokens / 1_000_000 * p["output"]
                total += msg.cache_read / 1_000_000 * p["cache_read"]
                total += msg.cache_create / 1_000_000 * p["cache_create"]
            return total
        # Fallback for sessions with no parsed messages
        pricing = _match_model_pricing("claude-sonnet-4-5")
        return (
            self.input_tokens / 1_000_000 * pricing["input"]
            + self.output_tokens / 1_000_000 * pricing["output"]
            + self.cache_read / 1_000_000 * pricing["cache_read"]
            + self.cache_create / 1_000_000 * pricing["cache_create"]
        )


class ClaudeCodeCollector(BaseCollector):
    """Collects data from Claude Code's local files.

    Primary source: ~/.claude/projects/**/*.jsonl (per-session logs)
    Secondary source: ~/.claude/stats-cache.json + history.jsonl (legacy)
    """

    # Cache TTL: re-parse projects/ at most every 60 seconds
    _CACHE_TTL = 60.0

    def __init__(self, claude_dir: Path | None = None) -> None:
        self._dir = claude_dir or CLAUDE_DIR
        self._session_cache: list[_ParsedSession] | None = None
        self._cache_time: float = 0.0

    @property
    def tool_name(self) -> ToolName:
        return ToolName.CLAUDE_CODE

    def is_available(self) -> bool:
        return self._dir.exists()

    # ──────────────────────────────────────────────────────────
    #  PRIMARY: Parse projects/**/*.jsonl
    # ──────────────────────────────────────────────────────────

    def _parse_all_project_sessions(self) -> list[_ParsedSession]:
        """Parse every session JSONL under projects/. Cached after first call."""
        if (
            self._session_cache is not None
            and (time.monotonic() - self._cache_time) < self._CACHE_TTL
        ):
            return self._session_cache

        projects_dir = self._dir / "projects"
        if not projects_dir.exists():
            self._session_cache = []
            return self._session_cache

        sessions: list[_ParsedSession] = []

        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue

            project_path = _decode_project_path(project_dir.name)

            # Main session files (top-level .jsonl in project dir)
            for jsonl_file in project_dir.glob("*.jsonl"):
                session = self._parse_session_jsonl(jsonl_file, project_path)
                if session is not None:
                    sessions.append(session)

            # Subagent session files
            for jsonl_file in project_dir.glob("*/subagents/*.jsonl"):
                session = self._parse_session_jsonl(jsonl_file, project_path)
                if session is not None:
                    sessions.append(session)

        self._session_cache = sessions
        self._cache_time = time.monotonic()
        return sessions

    def _parse_session_jsonl(
        self, path: Path, project_path: str,
    ) -> _ParsedSession | None:
        """Parse a single session .jsonl file into a _ParsedSession."""
        # Extract session ID from filename (uuid.jsonl)
        session_id = path.stem

        session = _ParsedSession(session_id=session_id, project=project_path)

        try:
            with open(path, errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    entry_type = entry.get("type")
                    ts_str = entry.get("timestamp")
                    ts = _parse_timestamp(ts_str) if ts_str else None

                    if entry_type == "user":
                        self._process_user_entry(entry, ts, session)
                    elif entry_type == "assistant":
                        self._process_assistant_entry(entry, ts, session)

        except OSError as e:
            logger.debug("Failed to read %s: %s", path, e)
            return None

        # Skip empty sessions (e.g. file-history-snapshot only)
        if session.user_messages == 0 and not session.messages:
            return None

        return session

    def _process_user_entry(
        self, entry: dict, ts: datetime | None, session: _ParsedSession,
    ) -> None:
        """Extract user message data from a 'user' type entry."""
        session.user_messages += 1

        if ts:
            if session.start_time is None or ts < session.start_time:
                session.start_time = ts
            if session.end_time is None or ts > session.end_time:
                session.end_time = ts

        # Capture prompt text (cap at 50 to avoid memory bloat)
        msg = entry.get("message", {})
        content = msg.get("content", "")
        if isinstance(content, str) and content and len(session.prompts) < 50:
            session.prompts.append(content)
        elif isinstance(content, list):
            # Content can be a list of blocks
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text and len(session.prompts) < 50:
                        session.prompts.append(text)
                        break

        # Use cwd from the first user entry as the canonical project path
        # (more accurate than the decoded dir name which is ambiguous)
        cwd = entry.get("cwd")
        if cwd and not session._cwd_set:
            session.project = cwd
            session._cwd_set = True

    def _process_assistant_entry(
        self, entry: dict, ts: datetime | None, session: _ParsedSession,
    ) -> None:
        """Extract token usage and tool calls from an 'assistant' type entry."""
        msg = entry.get("message", {})
        usage = msg.get("usage", {})
        model = msg.get("model", "unknown")

        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        cache_create = usage.get("cache_creation_input_tokens", 0)

        # Count tool_use content blocks
        tool_calls = 0
        content_type = "text"
        for block in msg.get("content", []):
            block_type = block.get("type", "")
            if block_type == "tool_use":
                tool_calls += 1
                content_type = "tool_use"

        if ts:
            if session.start_time is None or ts < session.start_time:
                session.start_time = ts
            if session.end_time is None or ts > session.end_time:
                session.end_time = ts

        parsed = _ParsedMessage(
            timestamp=ts,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read=cache_read,
            cache_create=cache_create,
            tool_calls=tool_calls,
            content_type=content_type,
        )
        session.messages.append(parsed)

        # Accumulate session totals
        session.input_tokens += input_tokens
        session.output_tokens += output_tokens
        session.cache_read += cache_read
        session.cache_create += cache_create
        session.tool_calls += tool_calls
        session.models_used[model] += 1

    # ──────────────────────────────────────────────────────────
    #  SECONDARY: Legacy stats-cache.json + history.jsonl
    # ──────────────────────────────────────────────────────────

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

    def _parse_full_stats(self) -> dict:
        """Parse entire stats-cache.json."""
        path = self._dir / "stats-cache.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _parse_history(self) -> list[dict]:
        """Parse history.jsonl → list of prompt records."""
        path = self._dir / "history.jsonl"
        if not path.exists():
            return []
        records: list[dict] = []
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError as e:
            logger.debug("Failed to read history.jsonl: %s", e)
        return records

    # ── Projects / memory ──

    def _get_project_memories(self) -> dict[str, str]:
        """Return {project_path: memory_content} for all projects with MEMORY.md."""
        results: dict[str, str] = {}
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

    # ──────────────────────────────────────────────────────────
    #  Public API: model usage, tokens, cost
    # ──────────────────────────────────────────────────────────

    def get_model_usage(self) -> dict[str, dict[str, Any]]:
        """Return per-model token breakdown.

        Prefers projects/ data. Falls back to stats-cache.json.
        """
        sessions = self._parse_all_project_sessions()
        if sessions:
            return self._model_usage_from_sessions(sessions)
        # Fallback to stats-cache.json
        data = self._parse_full_stats()
        return data.get("modelUsage", {})

    def _model_usage_from_sessions(
        self, sessions: list[_ParsedSession],
    ) -> dict[str, dict[str, Any]]:
        """Aggregate per-model token usage from parsed sessions."""
        models: dict[str, dict[str, int]] = defaultdict(
            lambda: {
                "inputTokens": 0, "outputTokens": 0,
                "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0,
            },
        )
        for session in sessions:
            for msg in session.messages:
                # Skip synthetic/internal entries (0 tokens, not a real model)
                if msg.model.startswith("<") or msg.model == "unknown":
                    continue
                m = models[msg.model]
                m["inputTokens"] += msg.input_tokens
                m["outputTokens"] += msg.output_tokens
                m["cacheReadInputTokens"] += msg.cache_read
                m["cacheCreationInputTokens"] += msg.cache_create
        return dict(models)

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
        # Prefer projects/ data
        sessions = self._parse_all_project_sessions()
        if sessions:
            hours: dict[str, int] = defaultdict(int)
            for s in sessions:
                if s.start_time:
                    hours[str(s.start_time.hour)] += 1
            return dict(hours)
        # Fallback
        data = self._parse_full_stats()
        return data.get("hourCounts", {})

    def get_session_summary(self) -> dict:
        """Return totalSessions, totalMessages, longestSession, firstSessionDate."""
        sessions = self._parse_all_project_sessions()
        if sessions:
            total_msgs = sum(s.user_messages for s in sessions)
            first = min(
                (s.start_time for s in sessions if s.start_time),
                default=None,
            )
            longest = max(sessions, key=lambda s: s.user_messages, default=None)
            return {
                "totalSessions": len(sessions),
                "totalMessages": total_msgs,
                "longestSession": {
                    "id": longest.session_id if longest else "",
                    "messages": longest.user_messages if longest else 0,
                },
                "firstSessionDate": first.isoformat() if first else None,
            }
        # Fallback
        data = self._parse_full_stats()
        return {
            "totalSessions": data.get("totalSessions", 0),
            "totalMessages": data.get("totalMessages", 0),
            "longestSession": data.get("longestSession", {}),
            "firstSessionDate": data.get("firstSessionDate"),
        }

    def get_real_token_count(self) -> int:
        """Sum BILLED tokens (input + output) across all models.

        Does NOT include cache_read or cache_create — those inflate the
        number ~380× and make the headline stat meaningless.
        """
        sessions = self._parse_all_project_sessions()
        if sessions:
            return sum(s.billed_tokens for s in sessions)
        # Fallback to stats-cache.json (input + output only)
        total = 0
        for usage in self.get_model_usage().values():
            total += usage.get("inputTokens", 0)
            total += usage.get("outputTokens", 0)
        return total

    def get_cache_token_count(self) -> int:
        """Sum cache tokens (read + create) for supplementary display."""
        sessions = self._parse_all_project_sessions()
        if sessions:
            return sum(s.cache_read + s.cache_create for s in sessions)
        total = 0
        for usage in self.get_model_usage().values():
            total += usage.get("cacheReadInputTokens", 0)
            total += usage.get("cacheCreationInputTokens", 0)
        return total

    def get_real_cost(self) -> float:
        """Calculate real cost using per-model pricing.

        Includes all four components (input, output, cache_read, cache_create)
        because all are billed (cache at reduced rates).
        """
        sessions = self._parse_all_project_sessions()
        if sessions:
            return sum(s.cost() for s in sessions)
        # Fallback to stats-cache.json
        total_cost = 0.0
        for model_id, usage in self.get_model_usage().items():
            pricing = _match_model_pricing(model_id)
            total_cost += usage.get("inputTokens", 0) / 1_000_000 * pricing["input"]
            total_cost += usage.get("outputTokens", 0) / 1_000_000 * pricing["output"]
            total_cost += usage.get("cacheReadInputTokens", 0) / 1_000_000 * pricing["cache_read"]
            total_cost += usage.get("cacheCreationInputTokens", 0) / 1_000_000 * pricing["cache_create"]
        return total_cost

    # ──────────────────────────────────────────────────────────
    #  BaseCollector interface
    # ──────────────────────────────────────────────────────────

    def collect_events(self) -> list[Event]:
        """Collect prompt events from projects/ (primary) or history.jsonl (fallback)."""
        sessions = self._parse_all_project_sessions()
        if sessions:
            return self._events_from_sessions(sessions)
        return self._events_from_history()

    def _events_from_sessions(self, sessions: list[_ParsedSession]) -> list[Event]:
        """Build Event list from parsed project sessions."""
        events: list[Event] = []
        for session in sessions:
            for prompt in session.prompts:
                # Approximate timestamp from session start + index offset
                ts = session.start_time or datetime.now()
                events.append(Event(
                    tool=ToolName.CLAUDE_CODE,
                    event_type="message",
                    timestamp=ts,
                    session_id=session.session_id,
                    project=session.project,
                    data={"prompt": prompt},
                    token_count=len(prompt) // 4,
                ))
        return events

    def _events_from_history(self) -> list[Event]:
        """Build Event list from legacy history.jsonl."""
        events: list[Event] = []
        for rec in self._parse_history():
            ts_ms = rec.get("timestamp", 0)
            if not ts_ms:
                continue
            ts = datetime.fromtimestamp(ts_ms / 1000)
            events.append(Event(
                tool=ToolName.CLAUDE_CODE,
                event_type="message",
                timestamp=ts,
                project=rec.get("project"),
                data={"prompt": rec.get("display", "")},
                token_count=len(rec.get("display", "")) // 4,
            ))
        return events

    def collect_sessions(self) -> list[Session]:
        """Build sessions from projects/ (primary) or history.jsonl (fallback)."""
        parsed = self._parse_all_project_sessions()
        if parsed:
            return self._sessions_from_parsed(parsed)
        return self._sessions_from_history()

    def _sessions_from_parsed(self, parsed: list[_ParsedSession]) -> list[Session]:
        """Convert _ParsedSession objects to public Session model."""
        sessions: list[Session] = []
        for p in parsed:
            sessions.append(Session(
                id=p.session_id,
                tool=ToolName.CLAUDE_CODE,
                project=p.project,
                start_time=p.start_time or datetime.now(),
                end_time=p.end_time,
                message_count=p.user_messages,
                tool_call_count=p.tool_calls,
                total_tokens=p.billed_tokens,
                estimated_cost_usd=p.cost(),
                prompts=p.prompts,
            ))
        return sessions

    def _sessions_from_history(self) -> list[Session]:
        """Build sessions from legacy history.jsonl (fallback).

        Uses an intermediate mutable dict to accumulate data, then
        constructs immutable Session objects in a single pass.
        """
        # Accumulate into plain dicts (mutable), then freeze into Session
        accum: dict[str, dict[str, Any]] = {}
        for rec in self._parse_history():
            ts_ms = rec.get("timestamp", 0)
            if not ts_ms:
                continue
            ts = datetime.fromtimestamp(ts_ms / 1000)
            project = rec.get("project", "unknown")
            sid = rec.get("sessionId") or f"claude-{ts.strftime('%Y-%m-%d')}-{project}"

            if sid not in accum:
                accum[sid] = {
                    "project": project, "start": ts, "end": ts,
                    "count": 0, "prompts": [],
                }
            a = accum[sid]
            a["count"] += 1
            a["end"] = max(a["end"], ts)
            prompt_text = rec.get("display", "")
            if prompt_text and len(a["prompts"]) < 50:
                a["prompts"].append(prompt_text)

        # Build immutable Session objects
        results: list[Session] = []
        for sid, a in accum.items():
            tokens = a["count"] * TOKENS_PER_MESSAGE_ESTIMATE
            results.append(Session(
                id=sid,
                tool=ToolName.CLAUDE_CODE,
                project=a["project"],
                start_time=a["start"],
                end_time=a["end"],
                message_count=a["count"],
                total_tokens=tokens,
                estimated_cost_usd=tokens * COST_PER_TOKEN,
                prompts=a["prompts"],
            ))
        return results

    def get_stats(self, days: int = 0) -> ToolStats:
        """Aggregate stats for the dashboard.

        Uses projects/ data as primary source with accurate token counts.
        Falls back to stats-cache.json + history.jsonl for legacy setups.
        """
        if days > 0:
            cutoff = datetime.now() - timedelta(days=days)
        else:
            cutoff = datetime(2000, 1, 1)

        parsed_sessions = self._parse_all_project_sessions()

        if parsed_sessions:
            return self._stats_from_sessions(parsed_sessions, cutoff)

        # Fallback: legacy stats-cache.json + history.jsonl
        return self._stats_from_legacy(cutoff, days)

    def _stats_from_sessions(
        self,
        sessions: list[_ParsedSession],
        cutoff: datetime,
    ) -> ToolStats:
        """Build ToolStats from parsed project sessions."""
        stats = ToolStats(tool=ToolName.CLAUDE_CODE)
        hourly: list[int] = [0] * 24
        seen_sessions: set[str] = set()

        for s in sessions:
            if s.start_time and s.start_time < cutoff:
                continue

            if s.session_id not in seen_sessions:
                seen_sessions.add(s.session_id)
                stats.sessions_today += 1

            stats.messages_today += s.user_messages
            stats.tool_calls_today += s.tool_calls
            stats.tokens_today += s.billed_tokens
            stats.estimated_cost_today += s.cost()

            # Hourly distribution
            for msg in s.messages:
                if msg.timestamp:
                    hourly[msg.timestamp.hour] += msg.input_tokens + msg.output_tokens

        stats.hourly_tokens = hourly

        if stats.messages_today > 0:
            stats.status = "active"

        return stats

    def _stats_from_legacy(self, cutoff: datetime, days: int) -> ToolStats:
        """Build ToolStats from legacy stats-cache.json + history.jsonl."""
        stats = ToolStats(tool=ToolName.CLAUDE_CODE)
        daily = self._parse_stats_cache()
        cutoff_str = cutoff.strftime("%Y-%m-%d") if days > 0 else ""
        cache_dates: set[str] = set()

        for day_data in daily:
            date = day_data.get("date", "")
            if date >= cutoff_str:
                cache_dates.add(date)
                stats.sessions_today += day_data.get("sessionCount", 0)
                stats.messages_today += day_data.get("messageCount", 0)
                stats.tool_calls_today += day_data.get("toolCallCount", 0)

        # Supplement with history.jsonl for dates NOT in cache
        hourly: list[int] = [0] * 24
        history_sessions: set[str] = set()
        for rec in self._parse_history():
            ts_ms = rec.get("timestamp", 0)
            if not ts_ms:
                continue
            ts = datetime.fromtimestamp(ts_ms / 1000)
            day_str = ts.strftime("%Y-%m-%d")
            if days > 0 and day_str < cutoff_str:
                continue
            hourly[ts.hour] += TOKENS_PER_MESSAGE_ESTIMATE
            if day_str not in cache_dates:
                stats.messages_today += 1
                sid = rec.get("sessionId", "")
                if sid and sid not in history_sessions:
                    history_sessions.add(sid)
                    stats.sessions_today += 1
        stats.hourly_tokens = hourly

        # Token and cost estimates
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

        return stats

    def get_daily_history(self, days: int = 30) -> list[dict]:
        """Return daily stats for the last N days."""
        daily = self._parse_stats_cache()
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return [d for d in daily if d.get("date", "") >= cutoff]


def _parse_timestamp(ts_str: str) -> datetime | None:
    """Parse ISO 8601 timestamp string → datetime. Returns None on failure."""
    try:
        # Handle 'Z' suffix and fractional seconds
        ts_str = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_str)
        # Convert to local time (naive) for consistency with rest of codebase
        return dt.replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None
