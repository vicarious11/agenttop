"""OpenAI Codex CLI data collector.

Parses data from ~/.codex/:
- history.jsonl — command history with timestamps
- sessions/YYYY/MM/DD/rollout-*.jsonl — full conversation transcripts
- config.toml — model selection, settings
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from agenttop.collectors.base import BaseCollector
from agenttop.models import Event, Session, ToolName, ToolStats

CODEX_DIR = Path.home() / ".codex"
TOKENS_PER_MESSAGE = 600
COST_PER_TOKEN = 0.000005


class CodexCollector(BaseCollector):
    """Collects data from OpenAI Codex CLI."""

    def __init__(self, codex_dir: Path | None = None) -> None:
        self._dir = codex_dir or CODEX_DIR

    @property
    def tool_name(self) -> ToolName:
        return ToolName.CODEX

    def is_available(self) -> bool:
        return self._dir.exists()

    def _parse_history(self) -> list[dict]:
        path = self._dir / "history.jsonl"
        if not path.exists():
            return []
        records = []
        try:
            for line in path.read_text().splitlines():
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
        return records

    def _list_session_files(self) -> list[Path]:
        sessions_dir = self._dir / "sessions"
        if not sessions_dir.exists():
            return []
        return sorted(sessions_dir.rglob("rollout-*.jsonl"))

    def _parse_session_file(self, path: Path) -> list[dict]:
        records = []
        try:
            for line in path.read_text().splitlines():
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
        return records

    def collect_events(self) -> list[Event]:
        events = []
        for rec in self._parse_history():
            ts = rec.get("timestamp") or rec.get("ts")
            if not ts:
                continue
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts if ts < 1e12 else ts / 1000)
            else:
                try:
                    dt = datetime.fromisoformat(str(ts))
                except ValueError:
                    continue
            events.append(
                Event(
                    tool=ToolName.CODEX,
                    event_type="command",
                    timestamp=dt,
                    data={"command": rec.get("command", rec.get("prompt", ""))},
                    token_count=TOKENS_PER_MESSAGE,
                )
            )
        return events

    def collect_sessions(self) -> list[Session]:
        sessions = []
        for sf in self._list_session_files():
            records = self._parse_session_file(sf)
            if not records:
                continue
            # Use file mod time as session time
            mtime = datetime.fromtimestamp(sf.stat().st_mtime)
            sessions.append(
                Session(
                    id=f"codex-{sf.stem}",
                    tool=ToolName.CODEX,
                    start_time=mtime,
                    end_time=mtime,
                    message_count=len(records),
                    total_tokens=len(records) * TOKENS_PER_MESSAGE,
                    estimated_cost_usd=len(records) * TOKENS_PER_MESSAGE * COST_PER_TOKEN,
                )
            )
        return sessions

    def get_stats(self, days: int = 0) -> ToolStats:
        stats = ToolStats(tool=ToolName.CODEX)
        if days > 0:
            cutoff = datetime.now() - timedelta(days=days)
        else:
            cutoff = datetime(2000, 1, 1)

        events = self.collect_events()
        for ev in events:
            if ev.timestamp >= cutoff:
                stats.messages_today += 1
                stats.tokens_today += TOKENS_PER_MESSAGE
                stats.hourly_tokens[ev.timestamp.hour] += TOKENS_PER_MESSAGE

        sessions = self.collect_sessions()
        for s in sessions:
            if s.start_time >= cutoff:
                stats.sessions_today += 1

        stats.estimated_cost_today = stats.tokens_today * COST_PER_TOKEN
        if stats.messages_today > 0:
            stats.status = "active"
        return stats
