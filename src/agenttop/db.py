"""SQLite event store for agenttop."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from agenttop.config import DB_PATH, ensure_config_dir
from agenttop.models import Event, Session, Suggestion, ToolName

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    session_id TEXT,
    project TEXT,
    data TEXT DEFAULT '{}',
    token_count INTEGER,
    cost_usd REAL
);

CREATE INDEX IF NOT EXISTS idx_events_tool ON events(tool);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    tool TEXT NOT NULL,
    project TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL DEFAULT 0.0,
    prompts TEXT DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_sessions_tool ON sessions(tool);
CREATE INDEX IF NOT EXISTS idx_sessions_start ON sessions(start_time);

CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool TEXT,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    estimated_savings TEXT,
    priority INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    dismissed INTEGER DEFAULT 0
);
"""


class EventStore:
    """SQLite-backed event store."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or DB_PATH
        ensure_config_dir()
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # -- Events --

    def insert_event(self, event: Event) -> int:
        cur = self._conn.execute(
            """INSERT INTO events
               (tool, event_type, timestamp, session_id, project, data, token_count, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.tool.value,
                event.event_type,
                event.timestamp.isoformat(),
                event.session_id,
                event.project,
                json.dumps(event.data),
                event.token_count,
                event.cost_usd,
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_events(
        self,
        tool: ToolName | None = None,
        since: datetime | None = None,
        event_type: str | None = None,
        limit: int = 1000,
    ) -> list[Event]:
        query = "SELECT * FROM events WHERE 1=1"
        params: list[str | int] = []
        if tool:
            query += " AND tool = ?"
            params.append(tool.value)
        if since:
            query += " AND timestamp >= ?"
            params.append(since.isoformat())
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [
            Event(
                id=r["id"],
                tool=ToolName(r["tool"]),
                event_type=r["event_type"],
                timestamp=datetime.fromisoformat(r["timestamp"]),
                session_id=r["session_id"],
                project=r["project"],
                data=json.loads(r["data"]) if r["data"] else {},
                token_count=r["token_count"],
                cost_usd=r["cost_usd"],
            )
            for r in rows
        ]

    # -- Sessions --

    def upsert_session(self, session: Session) -> None:
        self._conn.execute(
            """INSERT INTO sessions (id, tool, project, start_time, end_time,
                   message_count, tool_call_count, total_tokens, estimated_cost_usd, prompts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   end_time = excluded.end_time,
                   message_count = excluded.message_count,
                   tool_call_count = excluded.tool_call_count,
                   total_tokens = excluded.total_tokens,
                   estimated_cost_usd = excluded.estimated_cost_usd,
                   prompts = excluded.prompts""",
            (
                session.id,
                session.tool.value,
                session.project,
                session.start_time.isoformat(),
                session.end_time.isoformat() if session.end_time else None,
                session.message_count,
                session.tool_call_count,
                session.total_tokens,
                session.estimated_cost_usd,
                json.dumps(session.prompts),
            ),
        )
        self._conn.commit()

    def get_sessions(
        self,
        tool: ToolName | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Session]:
        query = "SELECT * FROM sessions WHERE 1=1"
        params: list[str | int] = []
        if tool:
            query += " AND tool = ?"
            params.append(tool.value)
        if since:
            query += " AND start_time >= ?"
            params.append(since.isoformat())
        query += " ORDER BY start_time DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [
            Session(
                id=r["id"],
                tool=ToolName(r["tool"]),
                project=r["project"],
                start_time=datetime.fromisoformat(r["start_time"]),
                end_time=datetime.fromisoformat(r["end_time"]) if r["end_time"] else None,
                message_count=r["message_count"],
                tool_call_count=r["tool_call_count"],
                total_tokens=r["total_tokens"],
                estimated_cost_usd=r["estimated_cost_usd"],
                prompts=json.loads(r["prompts"]) if r["prompts"] else [],
            )
            for r in rows
        ]

    # -- Suggestions --

    def insert_suggestion(self, s: Suggestion) -> int:
        cur = self._conn.execute(
            """INSERT INTO suggestions
               (tool, category, title, description, estimated_savings, priority, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                s.tool.value if s.tool else None,
                s.category,
                s.title,
                s.description,
                s.estimated_savings,
                s.priority,
                s.created_at.isoformat(),
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_suggestions(self, include_dismissed: bool = False) -> list[Suggestion]:
        query = "SELECT * FROM suggestions"
        if not include_dismissed:
            query += " WHERE dismissed = 0"
        query += " ORDER BY priority DESC, created_at DESC"
        rows = self._conn.execute(query).fetchall()
        return [
            Suggestion(
                id=r["id"],
                tool=ToolName(r["tool"]) if r["tool"] else None,
                category=r["category"],
                title=r["title"],
                description=r["description"],
                estimated_savings=r["estimated_savings"],
                priority=r["priority"],
                created_at=datetime.fromisoformat(r["created_at"]),
                dismissed=bool(r["dismissed"]),
            )
            for r in rows
        ]

    def dismiss_suggestion(self, suggestion_id: int) -> None:
        self._conn.execute("UPDATE suggestions SET dismissed = 1 WHERE id = ?", (suggestion_id,))
        self._conn.commit()
