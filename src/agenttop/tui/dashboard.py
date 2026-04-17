"""Dashboard view — data-dense panels using native Textual widgets."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Sparkline, Static

from agenttop.analysis.classifier import (
    classify_sessions,
    compute_cost_by_model,
    compute_cost_by_project,
    compute_oneshot_rate,
)
from agenttop.collectors.base import BaseCollector
from agenttop.db import EventStore
from agenttop.formatting import check_budget, human_cost, human_number, human_tokens
from agenttop.models import Session, ToolStats

RANGE_LABELS = {
    0: "All time", 1: "Today", 7: "Last 7 days", 30: "Last 30 days",
}

TOOL_DISPLAY = {
    "claude_code": "Claude Code", "cursor": "Cursor", "kiro": "Kiro",
    "copilot": "Copilot", "codex": "Codex", "windsurf": "Windsurf",
    "continue": "Continue", "aider": "Aider", "generic": "Generic",
}

TOOL_COLORS = {
    "claude_code": "orange", "cursor": "cyan", "kiro": "green",
    "copilot": "blue", "codex": "magenta", "windsurf": "yellow",
    "continue": "red", "aider": "white", "generic": "gray",
}

ACTIVITY_COLORS = {
    "coding": "green", "debugging": "red", "testing": "yellow",
    "exploration": "cyan", "refactoring": "magenta", "git_ops": "blue",
    "planning": "orange", "other": "white",
}

BLK = "\u2588"
SPC = "\u2500"


def _hbar(val: float, mx: float, w: int = 20, color: str = "cyan") -> str:
    if mx <= 0:
        return ""
    n = int(min(val / mx, 1.0) * w)
    return f"[{color}]{BLK * n}[/]{SPC * (w - n)}"


class StatsBar(Static):
    """Top bar — colored aggregate metrics."""

    def update_stats(
        self, stats: list[ToolStats], days: int = 0,
        budget: float = 0.0, cache_rate: float = 0.0,
    ) -> None:
        t_tok = sum(s.tokens_today for s in stats)
        t_cost = sum(s.estimated_cost_today for s in stats)
        t_sess = sum(s.sessions_today for s in stats)
        t_msgs = sum(s.messages_today for s in stats)
        tools = sum(1 for s in stats if s.tokens_today > 0)
        label = RANGE_LABELS.get(days, f"Last {days}d")
        p = [
            f"[bold]{label}[/]",
            f"[cyan bold]{human_tokens(t_tok)}[/] tok",
            f"[yellow bold]{human_cost(t_cost)}[/] cost",
            f"[green bold]{t_sess}[/] sess",
            f"[blue bold]{human_number(t_msgs)}[/] msgs",
            f"[green]{tools}[/] tools",
        ]
        if cache_rate > 0:
            p.append(f"[cyan]{cache_rate:.0f}%[/] cache")
        if budget > 0:
            bi = check_budget(t_cost, budget)
            if bi.status.value == "alert":
                p.append(f"[red bold]OVER BUDGET ({bi.ratio:.0%})[/]")
            elif bi.status.value == "warning":
                p.append(f"[yellow]{bi.ratio:.0%} budget[/]")
        self.update("  " + "  [dim]|[/]  ".join(p))


class CostProjectPanel(Static):
    """Cost by project with horizontal bars."""

    def refresh_data(self, data: list[dict[str, Any]]) -> None:
        top = data[:8]
        if not top:
            self.update("[dim]No data[/]")
            return
        mx = top[0]["cost"]
        lines = []
        for r in top:
            nm = r["project"][:18].ljust(18)
            bar = _hbar(r["cost"], mx, 18, "cyan")
            lines.append(
                f"  {nm} {bar} "
                f"[yellow]{human_cost(r['cost']):>7}[/] "
                f"[dim]{r['sessions']}s[/]"
            )
        self.update("\n".join(lines))


class CostModelPanel(Static):
    """Cost by model with horizontal bars."""

    def refresh_data(self, data: list[dict[str, Any]]) -> None:
        if not data:
            self.update("[dim]No data[/]")
            return
        mx = data[0]["cost"]
        lines = []
        for r in data[:5]:
            nm = r["model"][:14].ljust(14)
            bar = _hbar(r["cost"], mx, 16, "orange")
            lines.append(
                f"  {nm} {bar} "
                f"[yellow]{human_cost(r['cost']):>7}[/] "
                f"[dim]{human_tokens(r['tokens'])}[/]"
            )
        self.update("\n".join(lines))


class ActivityPanel(Static):
    """Activity breakdown bars."""

    def refresh_data(self, counts: dict[str, int]) -> None:
        total = sum(counts.values())
        if total == 0:
            self.update("[dim]No data[/]")
            return
        lines = []
        for act, cnt in counts.items():
            if cnt == 0:
                continue
            pct = cnt / total * 100
            color = ACTIVITY_COLORS.get(act, "white")
            nm = act.replace("_", " ").ljust(13)
            bar = _hbar(cnt, total, 12, color)
            lines.append(
                f"  {nm} {bar} [{color}]{pct:4.0f}%[/] [dim]{cnt}[/]"
            )
        self.update("\n".join(lines))


class ToolsPanel(Static):
    """Tool list with status dots."""

    def refresh_data(self, stats: list[ToolStats]) -> None:
        active = [
            s for s in stats
            if s.tokens_today > 0 or s.sessions_today > 0
        ]
        if not active:
            self.update("[dim]No tools[/]")
            return
        active.sort(key=lambda s: s.tokens_today, reverse=True)
        lines = []
        for s in active:
            c = TOOL_COLORS.get(s.tool.value, "white")
            nm = TOOL_DISPLAY.get(s.tool.value, s.tool.value)
            dot = (
                "[green]\u25cf[/]"
                if s.status == "active" else "[dim]\u25cb[/]"
            )
            lines.append(
                f"  {dot} [{c} bold]{nm:<12}[/] "
                f"[dim]{s.sessions_today:>4}[/]s "
                f"[cyan]{human_tokens(s.tokens_today):>6}[/] "
                f"[yellow]{human_cost(s.estimated_cost_today):>8}[/]"
            )
        self.update("\n".join(lines))


class OneshotPanel(Static):
    """One-shot success rate — big number + bar."""

    def refresh_data(self, rate: float) -> None:
        color = (
            "green" if rate >= 80
            else "yellow" if rate >= 60
            else "red"
        )
        n = int(rate / 100 * 24)
        bar = f"[{color}]{BLK * n}[/][dim]{SPC * (24 - n)}[/]"
        self.update(
            f"\n  [{color} bold]{rate:.0f}%[/]  {bar}\n\n"
            f"  [dim]Edits that pass first try.\n"
            f"  Higher = better prompting.[/]"
        )


def _xaxis_line(labels: list[str], width: int) -> str:
    """Render a 1-line X-axis with labels spread across the width."""
    if not labels or width <= 0:
        return ""
    if len(labels) == 1:
        return labels[0].center(width)
    slots = len(labels)
    out = [" "] * width
    for i, lbl in enumerate(labels):
        pos = int(i * (width - 1) / (slots - 1))
        pos = max(0, min(width - len(lbl), pos))
        for j, ch in enumerate(lbl):
            if pos + j < width:
                out[pos + j] = ch
    return "".join(out)


class HourlyActivityPanel(Static):
    """Hourly token activity — 24-hour sparkline with axis labels."""

    def compose(self) -> ComposeResult:
        yield Static("", id="hourly-summary", classes="chart-summary")
        yield Sparkline([], id="hourly-spark")
        yield Static("", id="hourly-xaxis", classes="chart-xaxis")

    def refresh_data(self, stats: list[ToolStats]) -> None:
        hourly = [0] * 24
        for s in stats:
            for i, v in enumerate(s.hourly_tokens[:24]):
                hourly[i] += v

        try:
            spark = self.query_one("#hourly-spark", Sparkline)
            spark.data = hourly
        except Exception:
            pass

        total = sum(hourly)
        peak_idx = hourly.index(max(hourly)) if total > 0 else 0
        peak_val = max(hourly) if total > 0 else 0
        peak_label = f"{peak_idx:02d}:00" if total > 0 else "--:--"

        summary = (
            f"[bold green]{human_tokens(total)}[/] tokens    "
            f"peak [bold]{peak_label}[/] "
            f"[dim]({human_tokens(peak_val)})[/]"
        )
        width = max(self.size.width - 2, 40)
        xaxis = _xaxis_line(
            ["00", "06", "12", "18", "23"], width,
        )
        try:
            self.query_one("#hourly-summary", Static).update(summary)
            self.query_one("#hourly-xaxis", Static).update(
                f"[dim cyan]{xaxis}[/]"
            )
        except Exception:
            pass


class DailyCostSparkline(Static):
    """Daily cost sparkline with X-axis date labels."""

    def compose(self) -> ComposeResult:
        yield Static("", id="daily-summary", classes="chart-summary")
        yield Sparkline([], id="spark")
        yield Static("", id="daily-xaxis", classes="chart-xaxis")

    def refresh_data(
        self, sessions: list[Session], days: int = 30,
    ) -> None:
        daily: dict[str, float] = defaultdict(float)
        for s in sessions:
            daily[s.start_time.strftime("%Y-%m-%d")] += (
                s.estimated_cost_usd
            )
        now = datetime.now()
        nd = days if days > 0 else 30
        values: list[float] = []
        dates: list[str] = []
        for d in range(nd):
            dt = (now - timedelta(days=nd - 1 - d)).strftime("%Y-%m-%d")
            dates.append(dt)
            values.append(daily.get(dt, 0.0))

        try:
            spark = self.query_one("#spark", Sparkline)
            spark.data = values
        except Exception:
            pass

        total = sum(values)
        pos = [v for v in values if v > 0]
        avg = total / max(len(pos), 1)
        peak = max(values) if values else 0
        pidx = values.index(peak) if peak > 0 else 0
        pdate = dates[pidx][-5:] if dates else ""

        summary = (
            f"[bold yellow]{human_cost(total)}[/] total    "
            f"[yellow]{human_cost(avg)}[/]/d avg    "
            f"peak [bold]{human_cost(peak)}[/] "
            f"[dim]({pdate})[/]"
        )

        # 5 evenly-spaced date ticks across the range
        tick_indices = [
            0, len(dates) // 4, len(dates) // 2,
            3 * len(dates) // 4, len(dates) - 1,
        ] if dates else []
        tick_labels = [dates[i][-5:] for i in tick_indices] if dates else []
        width = max(self.size.width - 2, 40)
        xaxis = _xaxis_line(tick_labels, width)

        try:
            self.query_one("#daily-summary", Static).update(summary)
            self.query_one("#daily-xaxis", Static).update(
                f"[dim cyan]{xaxis}[/]"
            )
        except Exception:
            pass


class DashboardView(Static):
    """Main dashboard — 6 panels in a 2x3 grid."""

    DEFAULT_CSS = """
    DashboardView { height: 1fr; }

    StatsBar {
        dock: top; height: 3;
        background: $primary-background;
        padding: 0 2;
        content-align: center middle;
    }

    #dash-row-1 { height: 11; }
    #dash-row-2 { height: 9; }
    #dash-row-3 { height: 10; }
    #dash-row-4 { height: 1fr; }

    #cost-project, #cost-model,
    #activity, #tools, #oneshot {
        width: 1fr;
        border: round $accent 30%;
        padding: 0 1;
    }

    DailyCostSparkline, HourlyActivityPanel {
        width: 1fr;
        border: round $accent 30%;
        height: 100%;
        padding: 0 1;
    }

    .chart-summary { height: 1; color: $text; }
    .chart-xaxis   { height: 1; }

    #spark, #hourly-spark {
        height: 1fr;
        margin: 0;
    }
    #spark > .sparkline--max-color { color: $warning; }
    #spark > .sparkline--min-color { color: $accent; }
    #hourly-spark > .sparkline--max-color { color: $success; }
    #hourly-spark > .sparkline--min-color { color: $accent; }
    """

    def __init__(
        self, collectors: list[BaseCollector], db: EventStore,
        days: int = 0, budget: float = 0.0,
    ) -> None:
        super().__init__()
        self._collectors = collectors
        self._db = db
        self._days = days
        self._budget = budget

    def compose(self) -> ComposeResult:
        yield StatsBar()
        with Horizontal(id="dash-row-1"):
            p1 = CostProjectPanel(id="cost-project")
            p1.border_title = "COST BY PROJECT"
            yield p1
            p2 = CostModelPanel(id="cost-model")
            p2.border_title = "COST BY MODEL"
            yield p2
        with Horizontal(id="dash-row-2"):
            sp = DailyCostSparkline(id="daily-cost")
            sp.border_title = "DAILY COST"
            yield sp
            hp = HourlyActivityPanel(id="hourly")
            hp.border_title = "HOURLY ACTIVITY"
            yield hp
        with Horizontal(id="dash-row-3"):
            p4 = ActivityPanel(id="activity")
            p4.border_title = "ACTIVITY"
            yield p4
            p6 = OneshotPanel(id="oneshot")
            p6.border_title = "ONE-SHOT RATE"
            yield p6
        with Horizontal(id="dash-row-4"):
            p5 = ToolsPanel(id="tools")
            p5.border_title = "TOOLS"
            yield p5

    def on_mount(self) -> None:
        self.refresh_stats(self._collectors, self._days)

    def refresh_stats(
        self, collectors: list[BaseCollector],
        days: int | None = None, budget: float = 0.0,
    ) -> None:
        if days is not None:
            self._days = days
        if budget > 0:
            self._budget = budget

        all_stats: list[ToolStats] = []
        all_sessions: list[Session] = []
        model_usage: dict[str, Any] = {}
        cutoff = (
            datetime.now() - timedelta(days=self._days)
            if self._days > 0 else datetime(2000, 1, 1)
        )

        for c in collectors:
            try:
                st = c.get_stats(days=self._days)
                all_stats.append(st)
                for s in c.collect_sessions():
                    if s.start_time >= cutoff:
                        all_sessions.append(s)
                if hasattr(c, "get_model_usage"):
                    mu = c.get_model_usage()
                    if mu:
                        model_usage.update(mu)
            except Exception:
                pass

        # Cache rate
        cache_rate = 0.0
        if model_usage:
            ti = sum(
                v.get("inputTokens", 0)
                + v.get("cacheReadInputTokens", 0)
                for v in model_usage.values()
            )
            tc = sum(
                v.get("cacheReadInputTokens", 0)
                for v in model_usage.values()
            )
            if ti > 0:
                cache_rate = tc / ti * 100

        # Update panels
        for fn in [
            lambda: self.query_one(StatsBar).update_stats(
                all_stats, self._days, self._budget, cache_rate,
            ),
            lambda: self.query_one(CostProjectPanel).refresh_data(
                compute_cost_by_project(all_sessions),
            ),
            lambda: self.query_one(CostModelPanel).refresh_data(
                compute_cost_by_model(model_usage),
            ),
            lambda: self.query_one(DailyCostSparkline).refresh_data(
                all_sessions, self._days,
            ),
            lambda: self.query_one(HourlyActivityPanel).refresh_data(
                all_stats,
            ),
            lambda: self.query_one(ActivityPanel).refresh_data(
                classify_sessions(all_sessions),
            ),
            lambda: self.query_one(ToolsPanel).refresh_data(all_stats),
            lambda: self.query_one(OneshotPanel).refresh_data(
                compute_oneshot_rate(all_sessions),
            ),
        ]:
            try:
                fn()
            except Exception:
                pass
