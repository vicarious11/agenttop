"""Sessions view — project aggregates + scrollable session history."""

from __future__ import annotations

from datetime import datetime, timedelta

from textual.app import ComposeResult
from textual.widgets import DataTable, Label, Static

from agenttop.collectors.base import BaseCollector
from agenttop.db import EventStore
from agenttop.formatting import human_cost, human_number, human_tokens

TOOL_DISPLAY = {
    "claude_code": "Claude Code",
    "cursor": "Cursor",
    "kiro": "Kiro",
    "copilot": "Copilot",
    "codex": "Codex",
    "generic": "Generic",
}

RANGE_LABELS = {0: "All time", 1: "Today", 7: "Last 7 days", 30: "Last 30 days"}


class SessionsView(Static):
    """Project aggregates at top, detailed session list below."""

    DEFAULT_CSS = """
    SessionsView {
        height: 1fr;
    }
    #project-table {
        height: auto;
        max-height: 12;
        margin: 0 1;
    }
    #sessions-table {
        height: 1fr;
        margin: 0 1;
    }
    SessionsView Label {
        padding: 0 2;
        text-style: bold;
    }
    """

    def __init__(
        self,
        collectors: list[BaseCollector],
        db: EventStore,
        days: int = 0,
    ) -> None:
        super().__init__()
        self._collectors = collectors
        self._db = db
        self._days = days

    def compose(self) -> ComposeResult:
        yield Label("By Project", id="project-label")
        yield DataTable(id="project-table")
        yield Label("Session History", id="sessions-label")
        yield DataTable(id="sessions-table")

    def on_mount(self) -> None:
        # Project aggregates table
        ptable = self.query_one("#project-table", DataTable)
        ptable.add_columns(
            "Project", "Sessions", "Messages", "Total Duration",
            "Tokens", "Cost", "Avg Msgs/Session",
        )
        ptable.cursor_type = "row"

        # Detailed sessions table
        table = self.query_one("#sessions-table", DataTable)
        table.add_columns(
            "Tool", "Project", "Start", "Duration",
            "Messages", "Tool Calls", "Tokens", "Cost",
        )
        table.cursor_type = "row"
        self._load_sessions()

    def _load_sessions(self) -> None:
        ptable = self.query_one("#project-table", DataTable)
        ptable.clear()
        table = self.query_one("#sessions-table", DataTable)
        table.clear()

        if self._days > 0:
            cutoff = datetime.now() - timedelta(days=self._days)
        else:
            cutoff = datetime(2000, 1, 1)

        label = RANGE_LABELS.get(self._days, f"Last {self._days}d")
        try:
            self.query_one("#project-label", Label).update(
                f"By Project — {label}"
            )
            self.query_one("#sessions-label", Label).update(
                f"Session History — {label}"
            )
        except Exception:
            pass

        all_sessions = []
        for collector in self._collectors:
            try:
                for s in collector.collect_sessions():
                    if s.start_time >= cutoff:
                        all_sessions.append(s)
            except Exception:
                continue

        # Also load from DB
        try:
            db_sessions = self._db.get_sessions(
                since=cutoff, limit=500
            )
            seen_ids = {s.id for s in all_sessions}
            for s in db_sessions:
                if s.id not in seen_ids:
                    all_sessions.append(s)
        except Exception:
            pass

        all_sessions.sort(key=lambda s: s.start_time, reverse=True)

        # ── Project aggregates ──
        projects: dict[str, dict] = {}
        for session in all_sessions:
            project = session.project or ""
            if "/" in project:
                project = project.rstrip("/").rsplit("/", 1)[-1]
            project = project or "(unknown)"

            if project not in projects:
                projects[project] = {
                    "sessions": 0,
                    "messages": 0,
                    "duration_s": 0.0,
                    "tokens": 0,
                    "cost": 0.0,
                }
            p = projects[project]
            p["sessions"] += 1
            p["messages"] += session.message_count
            p["tokens"] += session.total_tokens
            p["cost"] += session.estimated_cost_usd
            if session.end_time and session.end_time > session.start_time:
                p["duration_s"] += (session.end_time - session.start_time).total_seconds()

        # Sort by messages descending
        for project, p in sorted(projects.items(), key=lambda x: x[1]["messages"], reverse=True):
            dur_s = p["duration_s"]
            if dur_s >= 3600:
                dur_str = f"{dur_s / 3600:.1f}h"
            elif dur_s >= 60:
                dur_str = f"{dur_s / 60:.0f}m"
            elif dur_s > 0:
                dur_str = f"{dur_s:.0f}s"
            else:
                dur_str = "-"

            avg_msgs = p["messages"] / p["sessions"] if p["sessions"] else 0

            ptable.add_row(
                project,
                str(p["sessions"]),
                human_number(p["messages"]),
                dur_str,
                human_tokens(p["tokens"]),
                human_cost(p["cost"]),
                f"{avg_msgs:.0f}",
            )

        # ── Detailed session rows ──
        for session in all_sessions[:200]:
            tool_display = TOOL_DISPLAY.get(
                session.tool.value, session.tool.value
            )
            project = session.project or ""
            if "/" in project:
                project = project.rstrip("/").rsplit("/", 1)[-1]

            start = session.start_time.strftime("%Y-%m-%d %H:%M")

            if session.end_time and session.end_time > session.start_time:
                delta = session.end_time - session.start_time
                hours = int(delta.total_seconds() // 3600)
                mins = int((delta.total_seconds() % 3600) // 60)
                duration = f"{hours}h {mins}m" if hours else f"{mins}m"
            else:
                duration = "-"

            table.add_row(
                tool_display,
                project[:30],
                start,
                duration,
                str(session.message_count),
                str(session.tool_call_count),
                human_tokens(session.total_tokens),
                human_cost(session.estimated_cost_usd),
            )

    def action_refresh(self) -> None:
        self._load_sessions()
