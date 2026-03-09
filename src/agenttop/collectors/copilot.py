"""GitHub Copilot CLI data collector.

Parses data from ~/.copilot/:
- config — user preferences (JSON, no extension)
- session-state/ — active session storage
- agents/*.agent.md — custom agent definitions
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from agenttop.collectors.base import BaseCollector
from agenttop.models import Event, Session, ToolName, ToolStats

COPILOT_DIR = Path.home() / ".copilot"
TOKENS_PER_MESSAGE = 500
COST_PER_TOKEN = 0.000003


class CopilotCollector(BaseCollector):
    """Collects data from GitHub Copilot CLI."""

    def __init__(self, copilot_dir: Path | None = None) -> None:
        self._dir = copilot_dir or COPILOT_DIR

    @property
    def tool_name(self) -> ToolName:
        return ToolName.COPILOT

    def is_available(self) -> bool:
        return self._dir.exists()

    def _get_session_files(self) -> list[Path]:
        sd = self._dir / "session-state"
        if not sd.exists():
            # Also check legacy location
            sd = self._dir / "history-session-state"
        if not sd.exists():
            return []
        return sorted(sd.iterdir(), key=lambda p: p.stat().st_mtime)

    def _parse_session_file(self, path: Path) -> dict:
        try:
            text = path.read_text(errors="replace")
            return json.loads(text)
        except (json.JSONDecodeError, OSError):
            return {}

    def collect_events(self) -> list[Event]:
        events = []
        for sf in self._get_session_files():
            mtime = datetime.fromtimestamp(sf.stat().st_mtime)
            events.append(
                Event(
                    tool=ToolName.COPILOT,
                    event_type="session",
                    timestamp=mtime,
                    data={"file": sf.name},
                    token_count=TOKENS_PER_MESSAGE,
                )
            )
        return events

    def collect_sessions(self) -> list[Session]:
        sessions = []
        for sf in self._get_session_files():
            mtime = datetime.fromtimestamp(sf.stat().st_mtime)
            sessions.append(
                Session(
                    id=f"copilot-{sf.stem}",
                    tool=ToolName.COPILOT,
                    start_time=mtime,
                    message_count=1,
                    total_tokens=TOKENS_PER_MESSAGE,
                    estimated_cost_usd=TOKENS_PER_MESSAGE * COST_PER_TOKEN,
                )
            )
        return sessions

    def get_stats(self, days: int = 0) -> ToolStats:
        stats = ToolStats(tool=ToolName.COPILOT)
        if days > 0:
            cutoff = datetime.now() - timedelta(days=days)
        else:
            cutoff = datetime(2000, 1, 1)

        for sf in self._get_session_files():
            mtime = datetime.fromtimestamp(sf.stat().st_mtime)
            if mtime >= cutoff:
                stats.sessions_today += 1
                stats.messages_today += 1
                stats.tokens_today += TOKENS_PER_MESSAGE
                stats.hourly_tokens[mtime.hour] += TOKENS_PER_MESSAGE

        stats.estimated_cost_today = stats.tokens_today * COST_PER_TOKEN
        if stats.messages_today > 0:
            stats.status = "active"
        return stats
