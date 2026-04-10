"""Interactive session explorer — browse, select, and analyze sessions via LLM."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from agenttop.collectors.base import BaseCollector
from agenttop.db import EventStore
from agenttop.formatting import human_cost, human_tokens
from agenttop.models import Session

TOOL_DISPLAY = {
    "claude_code": "Claude Code",
    "cursor": "Cursor",
    "kiro": "Kiro",
    "copilot": "Copilot",
    "codex": "Codex",
    "generic": "Generic",
}


def _fmt_duration(s: Session) -> str:
    if s.end_time and s.end_time > s.start_time:
        delta = s.end_time - s.start_time
        hours = int(delta.total_seconds() // 3600)
        mins = int((delta.total_seconds() % 3600) // 60)
        return f"{hours}h {mins}m" if hours else f"{mins}m"
    return "-"


# ─────────────────────────────────────────────────
#  Session Detail Screen
# ─────────────────────────────────────────────────

class SessionDetailScreen(Screen[None]):
    """Screen showing session prompts with analyze option."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("a", "analyze", "Analyze"),
    ]

    CSS = """
    SessionDetailScreen { background: $surface; }
    .detail-container { height: 1fr; padding: 1 2; }
    .detail-title { text-style: bold; padding: 0 0 1 0; }
    .detail-stats { height: auto; padding: 0 0 1 0; color: $text-muted; }
    .prompt-scroll { height: 1fr; border: solid $accent; }
    .prompt-line { padding: 0 1; }
    .detail-btns { height: 3; padding: 1 0 0 0; }
    """

    def __init__(self, session: Session, collectors: list[BaseCollector]) -> None:
        super().__init__()
        self._session = session
        self._collectors = collectors

    def compose(self) -> ComposeResult:
        s = self._session
        project = s.project.rstrip("/").rsplit("/", 1)[-1] if s.project else "(unknown)"
        tool = TOOL_DISPLAY.get(s.tool.value, s.tool.value)
        dur = _fmt_duration(s)

        with Vertical(classes="detail-container"):
            yield Label(f"[bold]{project}[/bold]  —  {tool}", classes="detail-title")
            yield Label(
                f"Duration: {dur}  |  Messages: {s.message_count}  |  "
                f"Tokens: {human_tokens(s.total_tokens)}  |  "
                f"Cost: {human_cost(s.estimated_cost_usd)}  |  "
                f"Started: {s.start_time.strftime('%Y-%m-%d %H:%M')}",
                classes="detail-stats",
            )
            prompts = s.prompts or []
            if prompts:
                with VerticalScroll(classes="prompt-scroll"):
                    for i, prompt in enumerate(prompts, 1):
                        text = prompt.replace("\n", " ")
                        if len(text) > 500:
                            text = text[:500] + "…"
                        yield Label(f"[dim]{i:>3}.[/dim] {text}", classes="prompt-line")
            else:
                yield Label("[dim]No prompt data for this session[/dim]", classes="prompt-scroll")

            with Horizontal(classes="detail-btns"):
                yield Button("Analyze This Session", id="analyze-single", variant="primary")
                yield Button("Back", id="back-detail")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-detail":
            self.dismiss(None)
        elif event.button.id == "analyze-single":
            self.action_analyze()

    def action_analyze(self) -> None:
        self.app.push_screen(AnalysisScreen([self._session], self._collectors))

    def action_go_back(self) -> None:
        self.dismiss(None)


# ─────────────────────────────────────────────────
#  Analysis Screen
# ─────────────────────────────────────────────────

class AnalysisScreen(Screen[None]):
    """Screen that runs LLM analysis on selected sessions."""

    BINDINGS = [Binding("escape", "go_back", "Back")]

    CSS = """
    AnalysisScreen { background: $surface; }
    .analysis-container { height: 1fr; padding: 1 2; }
    .analysis-title { text-style: bold; padding: 0 0 1 0; }
    .analysis-output { height: 1fr; border: solid $accent; padding: 1; }
    .analysis-btns { height: 3; padding: 1 0 0 0; }
    """

    def __init__(self, sessions: list[Session], collectors: list[BaseCollector]) -> None:
        super().__init__()
        self._sessions = sessions
        self._collectors = collectors

    def compose(self) -> ComposeResult:
        n = len(self._sessions)
        with Vertical(classes="analysis-container"):
            yield Label(
                f"[bold]Analyzing {n} session{'s' if n != 1 else ''}...[/bold]",
                id="analysis-title", classes="analysis-title",
            )
            yield VerticalScroll(
                Label(
                    "[dim]Running LLM analysis... This may take a moment.[/dim]",
                    id="analysis-output",
                ),
                classes="analysis-output",
            )
            with Horizontal(classes="analysis-btns"):
                yield Button("Back", id="back-analysis")

    def on_mount(self) -> None:
        self.run_worker(self._run_analysis, thread=True)

    async def _run_analysis(self) -> None:
        try:
            from agenttop.config import load_config
            from agenttop.web.optimizer import AIUsageOptimizer

            config = load_config()

            stats: list[dict[str, Any]] = []
            feature_configs: dict[str, Any] = {}
            for collector in self._collectors:
                try:
                    s = collector.get_stats()
                    d = s.model_dump()
                    d["display_name"] = TOOL_DISPLAY.get(
                        collector.tool_name.value, collector.tool_name.value
                    )
                    stats.append(d)
                    fc = collector.get_feature_config()
                    if fc:
                        feature_configs[collector.tool_name.value] = fc
                except Exception:
                    continue

            model_usage: dict[str, Any] = {}
            for c in self._collectors:
                if hasattr(c, "get_model_usage"):
                    try:
                        model_usage = c.get_model_usage()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    break

            optimizer = AIUsageOptimizer(config)
            result = optimizer.analyze(stats, self._sessions, model_usage, feature_configs)
            self.app.call_from_thread(self._display_result, result)
        except Exception as e:
            self.app.call_from_thread(self._display_error, str(e))

    def _display_result(self, result: dict[str, Any]) -> None:
        score = result.get("score", 0)
        color = (
            "green" if score >= 80 else
            "cyan" if score >= 60 else
            "yellow" if score >= 40 else
            "red"
        )

        lines: list[str] = [f"[bold {color}]═══ Score: {score}/100 ═══[/bold {color}]", ""]

        dp = result.get("developer_profile", {})
        if dp.get("title"):
            lines.append(f"[bold]{dp['title']}[/bold]")
        if dp.get("bio"):
            lines += [f"[dim]{dp['bio']}[/dim]", ""]

        grades = result.get("grades", {})
        if grades:
            lines.append("[bold]Grades:[/bold]")
            names = {
                "cache_efficiency": "Cache",
                "session_hygiene": "Hygiene",
                "model_selection": "Model",
                "prompt_quality": "Prompts",
                "tool_utilization": "Tools",
            }
            for key, info in grades.items():
                g = info.get("grade", "?")
                gc = {"A": "green", "B": "cyan", "C": "yellow", "D": "red"}.get(g, "white")
                lines.append(f"  [{gc}]{g}[/{gc}] {names.get(key, key)}: {info.get('detail', '')}")
            lines.append("")

        aps = result.get("anti_patterns", [])
        if aps:
            lines.append("[bold]Issues:[/bold]")
            for ap in aps[:5]:
                sev = ap.get("severity", "medium")
                sc = {"high": "red", "medium": "yellow", "low": "cyan"}.get(sev, "white")
                lines.append(f"  [{sc}]• {ap.get('pattern', '')}[/{sc}] ({ap.get('count', 0)}x)")
                if ap.get("fix"):
                    lines.append(f"    [dim]{ap['fix']}[/dim]")
            lines.append("")

        recs = result.get("recommendations", [])
        if recs:
            lines.append("[bold]Recommendations:[/bold]")
            for rec in recs[:5]:
                p = rec.get("priority", "medium")
                pc = {"high": "red", "medium": "yellow", "low": "cyan"}.get(p, "white")
                lines.append(f"  [{pc}]■[/{pc}] [bold]{rec.get('title', '')}[/bold]")
                if rec.get("description"):
                    lines.append(f"    {rec['description']}")
            lines.append("")

        cf = result.get("cost_forensics", {})
        if cf.get("total_cost", 0) > 0:
            lines.append(f"[bold]Cost:[/bold] ${cf['total_cost']:.2f}")
            if cf.get("estimated_waste", 0) > 0:
                waste_pct = cf.get('waste_pct', 0)
                lines.append(
                    f"  [yellow]Waste: ${cf['estimated_waste']:.2f} ({waste_pct}%)[/yellow]"
                )

        try:
            self.query_one("#analysis-title", Label).update(
                f"[bold]Analysis Complete — {len(self._sessions)} session(s)[/bold]"
            )
            self.query_one("#analysis-output", Label).update("\n".join(lines))
        except Exception:
            pass

    def _display_error(self, error: str) -> None:
        try:
            self.query_one("#analysis-title", Label).update("[bold red]Analysis Failed[/bold red]")
            self.query_one("#analysis-output", Label).update(
                f"[red]{error}[/red]\n\n[dim]Run 'agenttop init' to configure LLM.[/dim]"
            )
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-analysis":
            self.dismiss(None)

    def action_go_back(self) -> None:
        self.dismiss(None)


# ─────────────────────────────────────────────────
#  Main Explorer View (tab content)
# ─────────────────────────────────────────────────

class SessionExplorerView(Static):
    """Interactive session explorer with search, select, and LLM analysis."""

    DEFAULT_CSS = """
    SessionExplorerView { height: 1fr; }
    .explorer-toolbar { height: 3; padding: 0 1; }
    .explorer-toolbar Input { width: 40; }
    .explorer-toolbar Select { width: 18; }
    .explorer-toolbar Button { margin-left: 1; }
    #session-table { height: 1fr; margin: 0 1; }
    .status-bar { height: 1; padding: 0 2; color: $text-muted; }
    """

    BINDINGS = [
        Binding("space", "toggle_select", "Select", show=True),
        Binding("ctrl+a", "select_all", "All"),
        Binding("enter", "view_detail", "Detail", show=True),
        Binding("f5", "analyze_selected", "Analyze", show=True),
    ]

    def __init__(self, collectors: list[BaseCollector], db: EventStore, days: int = 0) -> None:
        super().__init__()
        self._collectors = collectors
        self._db = db
        self._days = days
        self._sessions: list[Session] = []
        self._filtered: list[Session] = []
        self._selected: set[str] = set()
        self._search = ""

    def compose(self) -> ComposeResult:
        with Horizontal(classes="explorer-toolbar"):
            yield Input(placeholder="Search project or prompt...", id="search-input")
            yield Select(
                [("All Tools", ""), ("Claude", "claude_code"), ("Cursor", "cursor"),
                 ("Kiro", "kiro"), ("Copilot", "copilot"), ("Codex", "codex")],
                value="", id="tool-filter",
            )
            yield Button("Analyze Selected", id="analyze-btn", variant="primary", disabled=True)
        yield DataTable(id="session-table")
        yield Label("", id="status-bar", classes="status-bar")

    def on_mount(self) -> None:
        table = self.query_one("#session-table", DataTable)
        table.add_columns("✓", "Tool", "Project", "Start", "Dur", "Msgs", "Tokens", "Cost")
        table.cursor_type = "row"
        self._load_sessions()

    def _load_sessions(self) -> None:
        if self._days > 0:
            cutoff = datetime.now() - timedelta(days=self._days)
        else:
            cutoff = datetime(2000, 1, 1)
        sessions: list[Session] = []
        for collector in self._collectors:
            try:
                for s in collector.collect_sessions():
                    if s.start_time >= cutoff:
                        sessions.append(s)
            except Exception:
                continue
        try:
            seen = {s.id for s in sessions}
            for s in self._db.get_sessions(since=cutoff, limit=500):
                if s.id not in seen:
                    sessions.append(s)
        except Exception:
            pass
        # Filter out empty/junk sessions (0 messages AND 0 tokens)
        sessions = [s for s in sessions if s.message_count > 0 or s.total_tokens > 0]
        sessions.sort(key=lambda s: s.start_time, reverse=True)
        self._sessions = sessions
        self._apply_filters()

    def _apply_filters(self) -> None:
        filtered = list(self._sessions)
        try:
            tool_val = self.query_one("#tool-filter", Select).value
            if tool_val:
                filtered = [s for s in filtered if s.tool.value == tool_val]
        except Exception:
            pass
        if self._search:
            q = self._search.lower()
            filtered = [
                s for s in filtered
                if q in (s.project or "").lower()
                or q in (s.id or "").lower()
                or any(q in (p or "").lower() for p in (s.prompts or [])[:3])
            ]
        self._filtered = filtered
        self._render_table()

    def _render_table(self) -> None:
        table = self.query_one("#session-table", DataTable)
        table.clear()
        for s in self._filtered:
            tool = TOOL_DISPLAY.get(s.tool.value, s.tool.value)
            project = s.project.rstrip("/").rsplit("/", 1)[-1] if s.project else "(unknown)"
            project = (project[:25] + "…") if len(project) > 25 else project
            check = "[bold green]✓[/bold green]" if s.id in self._selected else "[dim]·[/dim]"
            table.add_row(
                check, tool, project, s.start_time.strftime("%m-%d %H:%M"),
                _fmt_duration(s), str(s.message_count),
                human_tokens(s.total_tokens), human_cost(s.estimated_cost_usd),
                key=s.id,
            )
        total, shown, sel = len(self._sessions), len(self._filtered), len(self._selected)
        status = f"{shown}/{total} sessions" + (f" | {sel} selected" if sel else "")
        try:
            self.query_one("#status-bar", Label).update(status)
        except Exception:
            pass

    def _update_btn(self) -> None:
        try:
            btn = self.query_one("#analyze-btn", Button)
            n = len(self._selected)
            btn.disabled = n == 0
            btn.label = f"Analyze {n}" if n else "Analyze Selected"
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self._search = event.value
            self._apply_filters()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "tool-filter":
            self._apply_filters()

    def action_toggle_select(self) -> None:
        table = self.query_one("#session-table", DataTable)
        if table.cursor_row is None:
            return
        try:
            sid = list(table.rows.keys())[table.cursor_row].value
        except (IndexError, KeyError):
            return
        if sid in self._selected:
            self._selected.discard(sid)
        else:
            self._selected.add(sid)
        self._render_table()
        self._update_btn()
        n = len(self._selected)
        if n > 0:
            self.notify(f"{n} session{'s' if n > 1 else ''} selected — press F5 to analyze")

    def action_select_all(self) -> None:
        if len(self._selected) == len(self._filtered):
            self._selected.clear()
        else:
            self._selected = {s.id for s in self._filtered}
        self._render_table()
        self._update_btn()

    def action_view_detail(self) -> None:
        table = self.query_one("#session-table", DataTable)
        if table.cursor_row is None:
            return
        try:
            sid = list(table.rows.keys())[table.cursor_row].value
        except (IndexError, KeyError):
            return
        session = next((s for s in self._sessions if s.id == sid), None)
        if session:
            self.app.push_screen(SessionDetailScreen(session, self._collectors))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "analyze-btn":
            self.action_analyze_selected()

    def action_analyze_selected(self) -> None:
        if not self._selected:
            self.notify("No sessions selected. Press Space to select.", severity="warning")
            return
        selected = [s for s in self._sessions if s.id in self._selected]
        self.app.push_screen(AnalysisScreen(selected, self._collectors))

    def action_refresh(self) -> None:
        self._load_sessions()
