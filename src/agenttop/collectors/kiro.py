"""Kiro IDE data collector — parses state.vscdb and kiro.kiroagent/ data."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from agenttop.collectors.base import BaseCollector
from agenttop.config import KIRO_DIR
from agenttop.models import Event, Session, ToolName, ToolStats

logger = logging.getLogger(__name__)

# Keys in the VSCode state DB likely to hold Kiro session data
_KIRO_KEY_PATTERNS = ("kiro", "chat", "conversation", "session")


class KiroCollector(BaseCollector):
    """Collects data from Kiro's local state."""

    def __init__(self, kiro_dir: Path | None = None) -> None:
        self._dir = kiro_dir or KIRO_DIR
        self._agent_dir = self._dir / "globalStorage" / "kiro.kiroagent"

    @property
    def tool_name(self) -> ToolName:
        return ToolName.KIRO

    def is_available(self) -> bool:
        """Only report as available if Kiro has a state DB with data."""
        if not self._dir.exists():
            return False
        return self._find_state_db() is not None

    def _find_state_db(self) -> Path | None:
        """Find the state.vscdb file."""
        for c in (self._dir / "state.vscdb", self._dir / "User" / "globalStorage" / "state.vscdb"):
            if c.exists():
                return c
        return next(self._dir.rglob("state.vscdb"), None)

    def _read_state_db(self) -> list[dict[str, Any]]:
        """Read kiro-related key-value pairs from the state DB."""
        db_path = self._find_state_db()
        if not db_path:
            return []
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            seen: set[tuple[str, ...]] = set()
            results: list[dict[str, Any]] = []
            for table in tables:
                for pattern in _KIRO_KEY_PATTERNS:
                    try:
                        for r in conn.execute(
                            f"SELECT * FROM [{table}] WHERE key LIKE ? LIMIT 1000",
                            (f"%{pattern}%",),
                        ).fetchall():
                            key = (table, dict(r).get("key", ""))
                            if key not in seen:
                                seen.add(key)
                                results.append({"table": table, **dict(r)})
                    except sqlite3.Error:
                        continue
            conn.close()
            return results
        except (sqlite3.Error, OSError) as exc:
            logger.debug("Failed to read Kiro state DB: %s", exc)
            return []

    def _parse_kiro_sessions(self) -> list[Session]:
        """Parse session-like data from the Kiro state DB."""
        rows = self._read_state_db()
        sessions: list[Session] = []
        seen_ids: set[str] = set()

        for row in rows:
            value = row.get("value", "")
            if not isinstance(value, str):
                continue
            try:
                parsed = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                continue

            # Handle both single-object and list-of-objects shapes
            items = parsed if isinstance(parsed, list) else [parsed]
            for item in items:
                if not isinstance(item, dict):
                    continue
                session = self._extract_session(item, seen_ids)
                if session is not None:
                    sessions.append(session)

        return sessions

    def _extract_session(self, item: dict[str, Any], seen_ids: set[str]) -> Session | None:
        """Try to build a Session from a parsed JSON dict."""
        sid = str(item.get("id") or item.get("sessionId") or item.get("conversationId") or "")
        if not sid or sid in seen_ids:
            return None
        seen_ids.add(sid)

        start = self._parse_timestamp(
            item.get("timestamp") or item.get("startTime") or item.get("createdAt")
        ) or datetime.now()
        end = self._parse_timestamp(item.get("endTime") or item.get("updatedAt"))
        msgs = (item.get("messageCount") or item.get("message_count")
                or len(item.get("messages", [])) or 0)
        tokens = item.get("totalTokens") or item.get("tokens") or 0

        return Session(
            id=sid, tool=ToolName.KIRO,
            project=item.get("project") or item.get("workspace") or None,
            start_time=start, end_time=end,
            message_count=int(msgs), total_tokens=int(tokens),
        )

    @staticmethod
    def _parse_timestamp(raw: Any) -> datetime | None:
        """Best-effort timestamp parsing (epoch ms, ISO 8601, etc.)."""
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            try:
                return datetime.fromtimestamp(raw / 1000 if raw > 1e12 else raw)
            except (OSError, ValueError, OverflowError):
                return None
        if isinstance(raw, str):
            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(raw, fmt)
                except ValueError:
                    continue
        return None

    def _agent_dir_info(self) -> dict[str, Any]:
        """Return metadata about the kiro agent extension directory."""
        if not self._agent_dir.exists():
            return {"exists": False, "file_count": 0}
        try:
            files = list(self._agent_dir.iterdir())
            return {"exists": True, "file_count": len(files)}
        except OSError:
            return {"exists": True, "file_count": 0}

    # -- BaseCollector interface --

    def collect_events(self) -> list[Event]:
        return []

    def collect_sessions(self) -> list[Session]:
        return self._parse_kiro_sessions()

    def get_stats(self, days: int = 0) -> ToolStats:  # noqa: ARG002
        sessions = self._parse_kiro_sessions()
        if not sessions:
            return ToolStats(tool=ToolName.KIRO, status="idle")

        cutoff = datetime.now() - timedelta(days=days) if days > 0 else None
        filtered = (
            tuple(s for s in sessions if s.start_time >= cutoff)
            if cutoff
            else tuple(sessions)
        )

        total_messages = sum(s.message_count for s in filtered)
        total_tokens = sum(s.total_tokens for s in filtered)

        hourly: list[int] = [0] * 24
        for s in filtered:
            hourly[s.start_time.hour] += s.total_tokens or s.message_count

        return ToolStats(
            tool=ToolName.KIRO,
            sessions_today=len(filtered),
            messages_today=total_messages,
            tokens_today=total_tokens,
            status="active" if filtered else "idle",
            hourly_tokens=hourly,
        )

    def get_feature_config(self) -> dict[str, Any]:
        agent_info = self._agent_dir_info()
        kiro_keys = self._read_state_db()
        return {
            "kiro_state_keys": len(kiro_keys),
            "agent_extension": agent_info,
        }
