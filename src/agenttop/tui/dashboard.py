"""Dashboard view — rich charts and htop-style overview."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import DataTable, Static
from textual_plotext import PlotextPlot

from agenttop.collectors.base import BaseCollector
from agenttop.db import EventStore
from agenttop.formatting import (
    check_budget,
    human_cost,
    human_number,
    human_tokens,
)
from agenttop.models import ToolStats

RANGE_LABELS = {0: "All time", 1: "Today", 7: "Last 7 days", 30: "Last 30 days"}

TOOL_DISPLAY = {
    "claude_code": "Claude Code",
    "cursor": "Cursor",
    "kiro": "Kiro",
    "copilot": "Copilot",
    "codex": "Codex",
    "windsurf": "Windsurf",
    "continue": "Continue",
    "aider": "Aider",
    "generic": "Generic",
}

TOOL_COLORS = {
    "claude_code": "orange",
    "cursor": "cyan",
    "kiro": "green",
    "copilot": "blue",
    "codex": "magenta",
    "windsurf": "yellow",
    "continue": "red",
    "aider": "white",
    "generic": "gray",
}

STATUS_ICONS = {
    "active": "[green]●[/]",
    "idle": "[dim]○[/]",
    "error": "[red]✗[/]",
}


class StatsBar(Static):
    """Top bar showing aggregate stats."""

    DEFAULT_CSS = """
    StatsBar {
        dock: top;
        height: 3;
        background: $primary-background;
        color: $text;
        padding: 0 2;
        content-align: center middle;
    }
    """

    def update_stats(
        self,
        stats_list: list[ToolStats],
        days: int = 0,
        budget: float = 0.0,
    ) -> None:
        total_tokens = sum(s.tokens_today for s in stats_list)
        total_cost = sum(s.estimated_cost_today for s in stats_list)
        total_sessions = sum(s.sessions_today for s in stats_list)
        total_messages = sum(s.messages_today for s in stats_list)
        active = sum(1 for s in stats_list if s.status == "active")

        label = RANGE_LABELS.get(days, f"Last {days}d")

        # Build base message
        base_message = (
            f"  {label}: {human_tokens(total_tokens)} tokens | "
            f"{human_cost(total_cost)} est. cost | "
            f"{total_sessions} sessions | {human_number(total_messages)} messages | "
            f"{active} active"
        )

        # Add budget indicator if budget is configured
        if self._budget > 0:
            budget_info = check_budget(total_cost, self._budget)
            if budget_info.status == "alert":
                budget_msg = f" | [red]⚠️ OVER BUDGET ({budget_info.ratio:.0%})[/red]"
                base_message += budget_msg
            elif budget_info.status == "warning":
                budget_msg = f" | [yellow]⚠️ {budget_info.ratio:.0%} of budget[/yellow]"
                base_message += budget_msg

        self.update(
            base_message + "  [dim]\\[1] today [2] 7d [3] 30d [4] all[/]"
        )


class TokenFlowChart(PlotextPlot):
    """Area chart showing token flow by hour across tools."""

    DEFAULT_CSS = """
    TokenFlowChart {
        height: 14;
        padding: 0 1;
    }
    """

    def replot(self, stats_list: list[ToolStats]) -> None:
        self.plt.clear_data()
        self.plt.clear_figure()
        hours = list(range(24))

        has_data = False
        for stats in stats_list:
            if any(v > 0 for v in stats.hourly_tokens):
                has_data = True
                name = TOOL_DISPLAY.get(stats.tool.value, stats.tool.value)
                color = TOOL_COLORS.get(stats.tool.value, "white")
                self.plt.plot(
                    hours,
                    [float(t) for t in stats.hourly_tokens],
                    fillx=True,
                    label=name,
                    color=color,
                    marker="braille",
                )

        if not has_data:
            self.plt.plot(hours, [0.0] * 24, marker="braille")

        self.plt.title("Token Flow by Hour")
        self.plt.xlabel("Hour of Day")
        self.plt.ylabel("Tokens")
        self.plt.theme("dark")
        # Human-readable Y-axis ticks
        all_vals = []
        for stats in stats_list:
            all_vals.extend(stats.hourly_tokens)
        if all_vals and max(all_vals) > 0:
            max_val = max(all_vals)
            tick_count = 5
            step = max_val / tick_count
            ticks = [step * i for i in range(tick_count + 1)]
            labels = [human_number(t) for t in ticks]
            self.plt.yticks(ticks, labels)
        self.refresh()


class ToolBreakdownChart(PlotextPlot):
    """Horizontal bar chart — token usage per tool."""

    DEFAULT_CSS = """
    ToolBreakdownChart {
        height: 14;
        padding: 0 1;
    }
    """

    def replot(self, stats_list: list[ToolStats]) -> None:
        self.plt.clear_data()
        self.plt.clear_figure()

        tools = []
        tokens = []
        colors = []
        for s in sorted(stats_list, key=lambda x: x.tokens_today):
            if s.tokens_today > 0:
                tools.append(TOOL_DISPLAY.get(s.tool.value, s.tool.value))
                tokens.append(s.tokens_today)
                colors.append(TOOL_COLORS.get(s.tool.value, "white"))

        if tools:
            self.plt.bar(
                tools,
                tokens,
                orientation="h",
                color=colors,
                width=3 / 5,
            )
        else:
            self.plt.bar(["No data"], [0], orientation="h")

        self.plt.title("Tokens by Tool")
        self.plt.xlabel("Tokens")
        self.plt.theme("dark")
        # Human-readable X-axis ticks for horizontal bar
        if tokens:
            max_val = max(tokens)
            tick_count = 5
            step = max_val / tick_count
            ticks = [step * i for i in range(tick_count + 1)]
            labels = [human_number(t) for t in ticks]
            self.plt.xticks(ticks, labels)
        self.refresh()


class DailyUsageChart(PlotextPlot):
    """Bar chart showing daily message counts."""

    DEFAULT_CSS = """
    DailyUsageChart {
        height: 14;
        padding: 0 1;
    }
    """

    def replot(self, daily_data: list[dict]) -> None:
        self.plt.clear_data()
        self.plt.clear_figure()

        if daily_data:
            dates = [d["date"][-5:] for d in daily_data]  # MM-DD
            msgs = [d.get("messageCount", 0) for d in daily_data]
            self.plt.bar(dates, msgs, color="orange", marker="sd")
        else:
            self.plt.bar(["N/A"], [0])

        self.plt.title("Daily Messages")
        self.plt.ylabel("Messages")
        self.plt.theme("dark")
        # Human-readable Y-axis ticks
        if daily_data:
            max_val = max(d.get("messageCount", 0) for d in daily_data)
            if max_val > 0:
                tick_count = 5
                step = max_val / tick_count
                ticks = [step * i for i in range(tick_count + 1)]
                labels = [human_number(t) for t in ticks]
                self.plt.yticks(ticks, labels)
        self.refresh()


class DashboardView(Static):
    """Rich dashboard with charts and table."""

    DEFAULT_CSS = """
    DashboardView {
        height: 1fr;
    }
    #charts-row {
        height: 14;
    }
    #charts-row-2 {
        height: 14;
    }
    #tool-table {
        height: 1fr;
        margin: 0 1;
    }
    """

    def __init__(
        self,
        collectors: list[BaseCollector],
        db: EventStore,
        days: int = 0,
        budget: float = 0.0,
    ) -> None:
        super().__init__()
        self._collectors = collectors
        self._db = db
        self._days = days
        self._budget = budget

    def compose(self) -> ComposeResult:
        yield StatsBar()
        with Horizontal(id="charts-row"):
            yield TokenFlowChart(id="token-flow")
            yield ToolBreakdownChart(id="tool-breakdown")
        with Horizontal(id="charts-row-2"):
            yield DailyUsageChart(id="daily-usage")
        yield DataTable(id="tool-table")

    def on_mount(self) -> None:
        table = self.query_one("#tool-table", DataTable)
        table.add_columns(
            "Status", "Tool", "Sessions", "Messages",
            "Tool Calls", "Tokens", "Est. Cost",
        )
        table.cursor_type = "row"
        self.refresh_stats(self._collectors, self._days)

    def refresh_stats(
        self,
        collectors: list[BaseCollector],
        days: int | None = None,
    ) -> None:
        if days is not None:
            self._days = days

        table = self.query_one("#tool-table", DataTable)
        table.clear()

        all_stats: list[ToolStats] = []

        for collector in collectors:
            try:
                stats = collector.get_stats(days=self._days)
                all_stats.append(stats)

                icon = STATUS_ICONS.get(stats.status, "?")
                name = TOOL_DISPLAY.get(
                    stats.tool.value, stats.tool.value
                )
                table.add_row(
                    icon,
                    name,
                    str(stats.sessions_today),
                    human_number(stats.messages_today),
                    str(stats.tool_calls_today),
                    human_tokens(stats.tokens_today),
                    human_cost(stats.estimated_cost_today),
                )
            except Exception:
                pass

        # Update charts
        try:
            self.query_one(StatsBar).update_stats(all_stats, self._days, self._budget)
            self.query_one(TokenFlowChart).replot(all_stats)
            self.query_one(ToolBreakdownChart).replot(all_stats)
        except Exception:
            pass

        # Daily usage chart — get from Claude collector if available
        try:
            from agenttop.collectors.claude import ClaudeCodeCollector

            for c in collectors:
                if isinstance(c, ClaudeCodeCollector):
                    daily = c.get_daily_history(
                        days=self._days if self._days > 0 else 90
                    )
                    self.query_one(DailyUsageChart).replot(daily)
                    break
        except Exception:
            pass
