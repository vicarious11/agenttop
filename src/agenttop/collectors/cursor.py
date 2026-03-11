"""Cursor IDE data collector.

Reads data from ~/.cursor/ai-tracking/ai-code-tracking.db using ALL tables:

1. ai_code_hashes — AI-generated code per file (hash, model, source, file, conversation)
2. conversation_summaries — conversation metadata (title, TLDR, model, mode)
3. scored_commits — AI vs human lines per commit (tab, composer, human)
4. tracked_file_content — full file content tracked by Cursor
5. ai_deleted_files — files deleted by AI

Token estimation strategy (Cursor doesn't expose real token counts):
- Composer interactions: ~800 tokens per code hash (prompt + generated code)
- Tab completions: ~150 tokens per code hash (inline suggestions)
- Conversations with no code hashes: ~2000 tokens (chat-only)
These are conservative estimates based on typical Cursor usage patterns.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from agenttop.collectors.base import BaseCollector
from agenttop.config import CURSOR_DIR
from agenttop.models import Event, Session, ToolName, ToolStats

# Token estimates by source type (Cursor doesn't store real token counts)
_TOKENS_COMPOSER = 800       # composer generates larger code blocks
_TOKENS_TAB = 150            # tab completions are small inline suggestions
_TOKENS_CHAT_ONLY = 2000     # conversation with no tracked code output

# Model-specific cost per token (USD)
_COST_PER_TOKEN: dict[str, float] = {
    "claude-4.6-opus-high-thinking": 0.000075,  # premium model
    "claude-4.6-opus": 0.000060,
    "claude-3.5-sonnet": 0.000015,
    "gpt-4o": 0.000010,
    "gpt-4o-mini": 0.000001,
    "default": 0.000003,  # Cursor's default model (likely gpt-4o-mini)
}

# Directories that are containers, not project names
_CONTAINER_DIRS = {
    "repo", "repos", "desktop", "projects", "dev", "src", "code", "work", "documents",
}


def _extract_project(filepath: str) -> str | None:
    """Extract project name from an absolute file path.

    Walks past the home directory and any container dirs (repo/, Desktop/, etc.)
    to find the actual project directory name.
    """
    if not filepath or not filepath.startswith("/"):
        return None
    from pathlib import Path as _P

    home = str(_P.home())
    rel = filepath[len(home) + 1:] if filepath.startswith(home + "/") else filepath.lstrip("/")
    parts = rel.split("/")

    for i, part in enumerate(parts):
        if part.lower() not in _CONTAINER_DIRS:
            if "." in part and i == len(parts) - 1:
                return None
            return part
    return None


def _estimate_tokens(source: str) -> int:
    """Estimate tokens for a single code hash based on its source type."""
    if source == "composer":
        return _TOKENS_COMPOSER
    if source == "tab":
        return _TOKENS_TAB
    # Unknown source — use composer estimate as safe default
    return _TOKENS_COMPOSER


def _cost_for_tokens(tokens: int, model: str) -> float:
    """Compute estimated cost for a token count and model."""
    rate = _COST_PER_TOKEN.get(model, _COST_PER_TOKEN["default"])
    return tokens * rate


class CursorCollector(BaseCollector):
    """Collects data from Cursor's local SQLite database."""

    def __init__(self, cursor_dir: Path | None = None) -> None:
        self._dir = cursor_dir or CURSOR_DIR
        self._db_path = self._dir / "ai-tracking" / "ai-code-tracking.db"

    @property
    def tool_name(self) -> ToolName:
        return ToolName.CURSOR

    def is_available(self) -> bool:
        return self._db_path.exists()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        """Execute a query and return rows as dicts. Returns [] on error."""
        try:
            conn = self._connect()
            rows = conn.execute(sql, params).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except (sqlite3.Error, OSError):
            return []

    # -- Data access --

    def _get_conversations(self, since_ms: int = 0) -> list[dict]:
        return self._query(
            "SELECT * FROM conversation_summaries WHERE updatedAt >= ? ORDER BY updatedAt DESC",
            (since_ms,),
        )

    def _get_ai_code_hashes(self, since_ms: int = 0) -> list[dict]:
        return self._query(
            "SELECT * FROM ai_code_hashes WHERE createdAt >= ? ORDER BY createdAt DESC",
            (since_ms,),
        )

    def _get_scored_commits(self, since_ms: int = 0) -> list[dict]:
        return self._query(
            "SELECT * FROM scored_commits WHERE scoredAt >= ? ORDER BY scoredAt DESC",
            (since_ms,),
        )

    # -- BaseCollector interface --

    def collect_events(self) -> list[Event]:
        """Collect events from Cursor AI tracking DB."""
        events = []
        for code in self._get_ai_code_hashes():
            ts_ms = code.get("createdAt") or code.get("timestamp") or 0
            if not ts_ms:
                continue
            source = code.get("source", "")
            model = code.get("model", "")
            tokens = _estimate_tokens(source)
            events.append(
                Event(
                    tool=ToolName.CURSOR,
                    event_type="ai_code",
                    timestamp=datetime.fromtimestamp(ts_ms / 1000),
                    session_id=code.get("conversationId"),
                    project=_extract_project(code.get("fileName", "")),
                    token_count=tokens,
                    cost_usd=_cost_for_tokens(tokens, model),
                    data={
                        "source": source,
                        "file": code.get("fileName", ""),
                        "model": model,
                    },
                )
            )
        return events

    def collect_sessions(self) -> list[Session]:
        """Build sessions by merging conversation_summaries with ai_code_hashes.

        Groups code hashes by conversationId, enriches with conversation metadata
        (title, TLDR) when available, and estimates tokens by source type.
        """
        # Index conversation summaries by ID
        conv_by_id: dict[str, dict] = {}
        for conv in self._get_conversations():
            cid = conv.get("conversationId", "")
            if cid:
                conv_by_id[cid] = conv

        # Group code hashes by conversationId
        hash_groups: dict[str, list[dict]] = defaultdict(list)
        for code in self._get_ai_code_hashes():
            cid = code.get("conversationId") or "unknown"
            hash_groups[cid].append(code)

        # All conversation IDs (union of both sources)
        all_ids = set(conv_by_id.keys()) | set(hash_groups.keys())

        sessions = []
        for cid in all_ids:
            entries = hash_groups.get(cid, [])
            conv = conv_by_id.get(cid)

            # Compute timestamps from code hashes
            timestamps = []
            projects: Counter[str] = Counter()
            models: Counter[str] = Counter()
            total_tokens = 0
            total_cost = 0.0

            for entry in entries:
                ts_ms = entry.get("createdAt") or entry.get("timestamp") or 0
                if ts_ms:
                    timestamps.append(datetime.fromtimestamp(ts_ms / 1000))

                source = entry.get("source", "")
                model = entry.get("model", "default")
                tokens = _estimate_tokens(source)
                total_tokens += tokens
                total_cost += _cost_for_tokens(tokens, model)

                proj = _extract_project(entry.get("fileName", ""))
                if proj:
                    projects[proj] += 1
                if model:
                    models[model] += 1

            # Use conversation updatedAt as fallback timestamp
            if conv and not timestamps:
                updated_ms = conv.get("updatedAt", 0)
                if updated_ms:
                    timestamps.append(datetime.fromtimestamp(updated_ms / 1000))
                total_tokens = _TOKENS_CHAT_ONLY
                total_cost = _cost_for_tokens(
                    _TOKENS_CHAT_ONLY,
                    conv.get("model", "default"),
                )

            if not timestamps:
                continue

            start = min(timestamps)
            end = max(timestamps)

            # Build prompts from conversation metadata
            prompts: list[str] = []
            if conv:
                title = conv.get("title", "")
                tldr = conv.get("tldr", "")
                if title:
                    prompts.append(title)
                if tldr:
                    prompts.append(tldr)

            # Pick the most common project
            project = projects.most_common(1)[0][0] if projects else None

            sessions.append(
                Session(
                    id=cid,
                    tool=ToolName.CURSOR,
                    project=project,
                    start_time=start,
                    end_time=end,
                    message_count=max(len(entries), 1),
                    total_tokens=total_tokens,
                    estimated_cost_usd=total_cost,
                    prompts=prompts,
                )
            )

        return sessions

    def get_stats(self, days: int = 0) -> ToolStats:
        """Aggregate stats for the dashboard.

        Args:
            days: Number of days to aggregate. 0 = all available data.
        """
        stats = ToolStats(tool=ToolName.CURSOR)
        if days > 0:
            since = datetime.now() - timedelta(days=days)
        else:
            since = datetime(2000, 1, 1)
        since_ms = int(since.timestamp() * 1000)

        convs = self._get_conversations(since_ms=since_ms)
        codes = self._get_ai_code_hashes(since_ms=since_ms)

        # Count unique conversations from code hashes
        conv_ids_from_hashes = {c.get("conversationId") for c in codes if c.get("conversationId")}
        conv_ids_from_summaries = {c.get("conversationId") for c in convs}
        unique_sessions = conv_ids_from_hashes | conv_ids_from_summaries

        stats.sessions_today = len(unique_sessions)
        stats.messages_today = len(codes)
        stats.tool_calls_today = len(codes)

        # Estimate tokens from actual code hashes (not flat per-conversation)
        total_tokens = 0
        total_cost = 0.0
        hourly = [0] * 24

        for code in codes:
            source = code.get("source", "")
            model = code.get("model", "default")
            tokens = _estimate_tokens(source)
            total_tokens += tokens
            total_cost += _cost_for_tokens(tokens, model)

            ts_ms = code.get("createdAt", 0)
            if ts_ms:
                hour = datetime.fromtimestamp(ts_ms / 1000).hour
                hourly[hour] += tokens

        # Add estimated tokens for chat-only conversations (no code hashes)
        chat_only_convs = conv_ids_from_summaries - conv_ids_from_hashes
        for _ in chat_only_convs:
            total_tokens += _TOKENS_CHAT_ONLY
            total_cost += _cost_for_tokens(_TOKENS_CHAT_ONLY, "default")

        stats.tokens_today = total_tokens
        stats.estimated_cost_today = total_cost
        stats.hourly_tokens = hourly

        if codes or convs:
            stats.status = "active"

        return stats

    def get_ai_vs_human_ratio(self) -> dict:
        """Calculate AI vs human code contribution ratio from scored commits."""
        commits = self._get_scored_commits()
        total_ai = 0
        total_human = 0
        for c in commits:
            tab = c.get("tabLinesAdded") or 0
            composer = c.get("composerLinesAdded") or 0
            human = c.get("humanLinesAdded") or 0
            total_ai += tab + composer
            total_human += human
        total = total_ai + total_human
        return {
            "ai_lines": total_ai,
            "human_lines": total_human,
            "ai_percentage": (total_ai / total * 100) if total > 0 else 0,
        }
