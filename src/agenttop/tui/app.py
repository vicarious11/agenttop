"""Main Textual application for agenttop."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, TabbedContent, TabPane

from agenttop.collectors.base import BaseCollector
from agenttop.collectors.claude import ClaudeCodeCollector
from agenttop.collectors.codex import CodexCollector
from agenttop.collectors.copilot import CopilotCollector
from agenttop.collectors.cursor import CursorCollector
from agenttop.collectors.kiro import KiroCollector
from agenttop.config import load_config
from agenttop.db import EventStore
from agenttop.tui.analysis import AnalysisView
from agenttop.tui.dashboard import DashboardView, StatsBar
from agenttop.tui.knowledge_graph import KnowledgeGraphView
from agenttop.tui.sessions import SessionsView
from agenttop.tui.suggestions import SuggestionsView

TIME_RANGES = [
    (1, "Today"),
    (7, "Last 7 days"),
    (30, "Last 30 days"),
    (0, "All time"),
]


class AgentTop(App):
    """htop for AI coding agents."""

    TITLE = "agenttop"
    SUB_TITLE = "htop for AI coding agents"
    CSS = """
    Screen {
        background: $surface;
    }
    TabbedContent {
        height: 1fr;
    }
    TabPane {
        padding: 0;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("d", "switch_tab('dashboard')", "Dashboard", show=True),
        Binding("s", "switch_tab('sessions')", "Sessions", show=True),
        Binding("a", "switch_tab('analysis')", "Analysis", show=True),
        Binding("k", "switch_tab('knowledge-graph')", "Graph", show=True),
        Binding("r", "switch_tab('suggestions')", "Suggest", show=True),
        Binding("1", "set_range(1)", "Today"),
        Binding("2", "set_range(7)", "7 days"),
        Binding("3", "set_range(30)", "30 days"),
        Binding("4", "set_range(0)", "All time"),
        Binding("question_mark", "help", "Help"),
    ]

    def __init__(self, days: int = 0) -> None:
        super().__init__()
        self.config = load_config()
        self.db = EventStore()
        self.collectors: list[BaseCollector] = []
        self.days = days
        self._init_collectors()

    def _init_collectors(self) -> None:
        candidates = [
            ClaudeCodeCollector(self.config.claude_dir),
            CursorCollector(self.config.cursor_dir),
            KiroCollector(self.config.kiro_dir),
            CodexCollector(),
            CopilotCollector(),
        ]
        self.collectors = [c for c in candidates if c.is_available()]

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            with TabPane("Dashboard", id="dashboard"):
                yield DashboardView(self.collectors, self.db, self.days)
            with TabPane("Sessions", id="sessions"):
                yield SessionsView(self.collectors, self.db, self.days)
            with TabPane("Analysis", id="analysis"):
                yield AnalysisView(self.collectors, self.db)
            with TabPane("Knowledge Graph", id="knowledge-graph"):
                yield KnowledgeGraphView(self.collectors, self.db)
            with TabPane("Suggestions", id="suggestions"):
                yield SuggestionsView(self.collectors, self.db)
        yield Footer()

    def action_switch_tab(self, tab_id: str) -> None:
        tabbed = self.query_one(TabbedContent)
        tabbed.active = tab_id

    def action_set_range(self, days: int) -> None:
        self.days = days
        label = next(
            (name for d, name in TIME_RANGES if d == days), f"{days}d"
        )
        self.notify(f"Time range: {label}", title="Range")
        self._refresh_data()

    def action_help(self) -> None:
        self.notify(
            "[d]ashboard [s]essions [a]nalysis [k]nowledge graph [r]ecommend | "
            "Range: [1] today [2] 7d [3] 30d [4] all | [q]uit",
            title="Help",
        )

    def on_mount(self) -> None:
        self.set_interval(self.config.refresh_interval, self._refresh_data)
        self._refresh_data()

    def _refresh_data(self) -> None:
        dashboard = self.query_one(DashboardView)
        budget = self.config.llm.max_budget_per_day if self.days <= 1 else 0.0
        dashboard.refresh_stats(self.collectors, self.days, budget)
