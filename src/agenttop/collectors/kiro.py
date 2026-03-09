"""Kiro IDE data collector.

Parses data from ~/Library/Application Support/Kiro/:
- globalStorage/kiro.kiroagent/ for agent data
- state.vscdb — SQLite with extension state
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from agenttop.collectors.base import BaseCollector
from agenttop.config import KIRO_DIR
from agenttop.models import Event, Session, ToolName, ToolStats


class KiroCollector(BaseCollector):
    """Collects data from Kiro's local state."""

    def __init__(self, kiro_dir: Path | None = None) -> None:
        self._dir = kiro_dir or KIRO_DIR
        self._agent_dir = self._dir / "globalStorage" / "kiro.kiroagent"

    @property
    def tool_name(self) -> ToolName:
        return ToolName.KIRO

    def is_available(self) -> bool:
        return self._dir.exists()

    def _find_state_db(self) -> Path | None:
        """Find the state.vscdb file."""
        candidates = [
            self._dir / "state.vscdb",
            self._dir / "User" / "globalStorage" / "state.vscdb",
        ]
        for c in candidates:
            if c.exists():
                return c
        # Search recursively as fallback
        for p in self._dir.rglob("state.vscdb"):
            return p
        return None

    def _read_state_db(self) -> list[dict]:
        """Read key-value pairs from Kiro's state DB."""
        db_path = self._find_state_db()
        if not db_path:
            return []
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            # VSCode state DBs typically have an ItemTable
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            results = []
            for table in tables:
                try:
                    rows = conn.execute(f"SELECT * FROM [{table}] LIMIT 100").fetchall()
                    for r in rows:
                        results.append({"table": table, **dict(r)})
                except sqlite3.Error:
                    continue
            conn.close()
            return results
        except (sqlite3.Error, OSError):
            return []

    # -- BaseCollector interface --

    def collect_events(self) -> list[Event]:
        return []

    def collect_sessions(self) -> list[Session]:
        return []

    def get_stats(self, days: int = 0) -> ToolStats:
        stats = ToolStats(tool=ToolName.KIRO)
        if self.is_available():
            stats.status = "idle"
        return stats
