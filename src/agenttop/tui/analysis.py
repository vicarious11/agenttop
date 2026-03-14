"""Analysis view — model usage, temporal patterns, and data-driven insights."""

from __future__ import annotations

import json
from collections import Counter

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Label, Static
from textual.worker import Worker, WorkerState
from textual_plotext import PlotextPlot

from agenttop.collectors.base import BaseCollector
from agenttop.db import EventStore
from agenttop.formatting import human_number, human_tokens
from agenttop.models import IntentCategory

# Keep keyword-based intent classification for backward compatibility with tests
INTENT_KEYWORDS = {
    IntentCategory.DEBUGGING: ["bug", "fix", "error", "issue", "debug", "broken", "fail", "crash"],
    IntentCategory.REFACTORING: ["refactor", "rename", "clean", "restructure", "simplify", "move"],
    IntentCategory.GREENFIELD: ["create", "new", "implement", "build", "add", "scaffold", "init"],
    IntentCategory.EXPLORATION: ["what", "how", "explain", "understand", "show", "find", "where"],
    IntentCategory.CODE_REVIEW: ["review", "check", "audit", "look at", "evaluate"],
    IntentCategory.DEVOPS: ["deploy", "docker", "ci", "pipeline", "kubernetes", "k8s", "infra"],
    IntentCategory.DOCUMENTATION: ["doc", "readme", "comment", "document", "write up"],
}


def classify_intent_local(prompt: str) -> IntentCategory:
    """Classify prompt intent using keyword matching (no LLM needed)."""
    lower = prompt.lower()
    scores: dict[IntentCategory, int] = {}
    for intent, keywords in INTENT_KEYWORDS.items():
        scores[intent] = sum(1 for kw in keywords if kw in lower)
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else IntentCategory.UNKNOWN


MODEL_COLORS = {
    "opus": "orange",
    "sonnet": "cyan",
    "haiku": "green",
    "glm": "magenta",
}


def _model_color(model_id: str) -> str:
    """Pick a color based on model family."""
    lower = model_id.lower()
    for family, color in MODEL_COLORS.items():
        if family in lower:
            return color
    return "white"


def _short_model(model_id: str) -> str:
    """Shorten: 'claude-opus-4-5-20251101' → 'opus-4-5'."""
    parts = model_id.split("-")
    if parts and len(parts[-1]) >= 8 and parts[-1].isdigit():
        parts = parts[:-1]
    name = "-".join(parts)
    if name.startswith("claude-"):
        name = name[7:]
    return name


class ModelUsageChart(PlotextPlot):
    """Horizontal bar chart of token usage per model."""

    DEFAULT_CSS = """
    ModelUsageChart {
        height: 14;
        padding: 0 1;
    }
    """

    def replot(self, model_usage: dict[str, dict]) -> None:
        self.plt.clear_data()
        self.plt.clear_figure()

        if not model_usage:
            self.plt.bar(["No data"], [0], orientation="h")
            self.plt.title("Model Token Usage")
            self.plt.theme("dark")
            self.refresh()
            return

        names = []
        totals = []
        colors = []
        for model_id, usage in sorted(
            model_usage.items(),
            key=lambda x: x[1].get("inputTokens", 0) + x[1].get("outputTokens", 0),
        ):
            total = (
                usage.get("inputTokens", 0)
                + usage.get("outputTokens", 0)
            )
            if total > 0:
                names.append(_short_model(model_id))
                totals.append(total)
                colors.append(_model_color(model_id))

        if names:
            self.plt.bar(names, totals, orientation="h", color=colors, width=3 / 5)
            # Human-readable X-axis
            max_val = max(totals)
            tick_count = 5
            step = max_val / tick_count
            ticks = [step * i for i in range(tick_count + 1)]
            labels = [human_number(t) for t in ticks]
            self.plt.xticks(ticks, labels)
        else:
            self.plt.bar(["No data"], [0], orientation="h")

        self.plt.title("Model Token Usage (input + output + cache read)")
        self.plt.theme("dark")
        self.refresh()


class DailyModelChart(PlotextPlot):
    """Stacked bar chart showing daily token usage by model."""

    DEFAULT_CSS = """
    DailyModelChart {
        height: 14;
        padding: 0 1;
    }
    """

    def replot(self, daily_model_tokens: list[dict]) -> None:
        self.plt.clear_data()
        self.plt.clear_figure()

        if not daily_model_tokens:
            self.plt.bar(["No data"], [0])
            self.plt.title("Daily Model Tokens")
            self.plt.theme("dark")
            self.refresh()
            return

        dates = [d["date"][-5:] for d in daily_model_tokens]
        # Collect all model names
        all_models: set[str] = set()
        for entry in daily_model_tokens:
            all_models.update(entry.get("tokensByModel", {}).keys())

        for model_id in sorted(all_models):
            values = []
            for entry in daily_model_tokens:
                values.append(entry.get("tokensByModel", {}).get(model_id, 0))
            if any(v > 0 for v in values):
                self.plt.bar(
                    dates,
                    values,
                    label=_short_model(model_id),
                    color=_model_color(model_id),
                )

        # Human-readable Y-axis
        all_totals = []
        for entry in daily_model_tokens:
            all_totals.append(sum(entry.get("tokensByModel", {}).values()))
        if all_totals and max(all_totals) > 0:
            max_val = max(all_totals)
            tick_count = 5
            step = max_val / tick_count
            ticks = [step * i for i in range(tick_count + 1)]
            labels = [human_number(t) for t in ticks]
            self.plt.yticks(ticks, labels)

        self.plt.title("Daily Token Usage by Model")
        self.plt.ylabel("Tokens")
        self.plt.theme("dark")
        self.refresh()


class HourlyActivityChart(PlotextPlot):
    """Horizontal bar chart showing session starts by hour."""

    DEFAULT_CSS = """
    HourlyActivityChart {
        height: 14;
        padding: 0 1;
    }
    """

    def replot(self, hour_counts: dict[str, int]) -> None:
        self.plt.clear_data()
        self.plt.clear_figure()

        if not hour_counts:
            self.plt.bar(["No data"], [0], orientation="h")
            self.plt.title("Activity by Hour")
            self.plt.theme("dark")
            self.refresh()
            return

        hours = []
        counts = []
        colors = []
        max_count = max(hour_counts.values()) if hour_counts else 1
        for h in range(24):
            c = hour_counts.get(str(h), 0)
            if c > 0:
                hours.append(f"{h:02d}:00")
                counts.append(c)
                # Color intensity based on count
                if c >= max_count * 0.8:
                    colors.append("red")
                elif c >= max_count * 0.5:
                    colors.append("orange")
                elif c >= max_count * 0.3:
                    colors.append("yellow")
                else:
                    colors.append("cyan")

        if hours:
            self.plt.bar(hours, counts, orientation="h", color=colors, width=3 / 5)
        else:
            self.plt.bar(["No data"], [0], orientation="h")

        self.plt.title("Session Starts by Hour")
        self.plt.xlabel("Sessions")
        self.plt.theme("dark")
        self.refresh()


class ProjectBreakdownChart(PlotextPlot):
    """Horizontal bar chart showing prompts per project."""

    DEFAULT_CSS = """
    ProjectBreakdownChart {
        height: 14;
        padding: 0 1;
    }
    """

    def replot(self, project_counts: dict[str, int]) -> None:
        self.plt.clear_data()
        self.plt.clear_figure()

        if not project_counts:
            self.plt.bar(["No data"], [0], orientation="h")
            self.plt.title("Prompts by Project")
            self.plt.theme("dark")
            self.refresh()
            return

        # Show top 10 projects
        sorted_projects = sorted(project_counts.items(), key=lambda x: x[1])
        if len(sorted_projects) > 10:
            sorted_projects = sorted_projects[-10:]

        names = [p for p, _ in sorted_projects]
        counts = [c for _, c in sorted_projects]
        colors = ["cyan"] * len(names)
        # Highlight dominant project
        if counts:
            colors[-1] = "orange"

        self.plt.bar(names, counts, orientation="h", color=colors, width=3 / 5)
        if counts and max(counts) > 0:
            max_val = max(counts)
            tick_count = 5
            step = max_val / tick_count
            ticks = [step * i for i in range(tick_count + 1)]
            labels = [human_number(t) for t in ticks]
            self.plt.xticks(ticks, labels)

        self.plt.title("Prompts by Project")
        self.plt.theme("dark")
        self.refresh()


class IntentDistributionChart(PlotextPlot):
    """Horizontal bar chart showing intent classification of prompts."""

    DEFAULT_CSS = """
    IntentDistributionChart {
        height: 14;
        padding: 0 1;
    }
    """

    INTENT_COLORS = {
        "debugging": "red",
        "greenfield": "green",
        "exploration": "cyan",
        "refactoring": "yellow",
        "code_review": "magenta",
        "devops": "orange",
        "documentation": "white",
        "unknown": "gray",
    }

    def replot(self, intent_counts: dict[str, int]) -> None:
        self.plt.clear_data()
        self.plt.clear_figure()

        if not intent_counts:
            self.plt.bar(["No data"], [0], orientation="h")
            self.plt.title("Prompt Intent Distribution")
            self.plt.theme("dark")
            self.refresh()
            return

        # Sort by count, filter out zero
        sorted_intents = sorted(
            ((k, v) for k, v in intent_counts.items() if v > 0),
            key=lambda x: x[1],
        )

        if not sorted_intents:
            self.plt.bar(["No data"], [0], orientation="h")
            self.plt.title("Prompt Intent Distribution")
            self.plt.theme("dark")
            self.refresh()
            return

        names = [k for k, _ in sorted_intents]
        counts = [c for _, c in sorted_intents]
        colors = [self.INTENT_COLORS.get(n, "white") for n in names]

        self.plt.bar(names, counts, orientation="h", color=colors, width=3 / 5)
        self.plt.title("Prompt Intent Distribution")
        self.plt.theme("dark")
        self.refresh()


class DataInsights(Static):
    """Shows data-driven insights based on real stats."""

    DEFAULT_CSS = """
    DataInsights {
        height: auto;
        padding: 1 2;
        border: solid $accent;
    }
    """

    def update_insights(self, insights: list[str]) -> None:
        if not insights:
            self.update("[dim]No insights available. Make sure Claude Code has usage data.[/]")
            return
        text = "[bold]Data-Driven Insights[/]\n\n" + "\n".join(f"  [green]•[/] {i}" for i in insights)
        self.update(text)


def generate_data_insights(collector, sessions: list | None = None) -> list[str]:
    """Generate insights from real stats-cache data and session history."""
    insights = []
    model_usage = collector.get_model_usage()
    summary = collector.get_session_summary()

    # Model shift detection from dailyModelTokens
    daily_model_tokens = collector.get_daily_model_tokens()
    shift = _detect_model_shift(daily_model_tokens)
    if shift:
        insights.append(shift)

    # Cache efficiency per model
    for model_id, usage in model_usage.items():
        cache_read = usage.get("cacheReadInputTokens", 0)
        input_t = usage.get("inputTokens", 0)
        total_input = cache_read + input_t
        if total_input > 0 and cache_read > 0:
            ratio = cache_read / total_input * 100
            short = _short_model(model_id)
            insights.append(
                f"{short}: {ratio:.0f}% cache hit rate ({human_tokens(cache_read)} cached)"
            )

    # Session quality
    longest = summary.get("longestSession", {})
    msg_count = longest.get("messageCount", 0)
    if msg_count > 1000:
        from agenttop.formatting import human_duration_ms

        duration = human_duration_ms(longest.get("duration", 0))
        insights.append(
            f"Longest session: {msg_count:,} messages ({duration}) — "
            "consider splitting into focused sub-tasks after ~500 messages"
        )

    # Output/input ratio analysis
    for model_id, usage in model_usage.items():
        output = usage.get("outputTokens", 0)
        input_t = usage.get("inputTokens", 0)
        if input_t > 0 and output > input_t * 1.5:
            short = _short_model(model_id)
            ratio = output / input_t
            insights.append(
                f"{short}: output/input ratio {ratio:.1f}x — generating more code than prompts"
            )

    # Temporal patterns
    hour_counts = collector.get_hour_counts()
    if hour_counts:
        peak_hour = max(hour_counts, key=lambda h: hour_counts[h])
        insights.append(
            f"Peak productivity: {int(peak_hour):02d}:00 ({hour_counts[peak_hour]} sessions)"
        )

    # Per-project insights from real sessions
    if sessions:
        project_data: dict[str, dict] = {}
        for s in sessions:
            proj = s.project or "unknown"
            if "/" in proj:
                proj = proj.rstrip("/").rsplit("/", 1)[-1]
            if proj not in project_data:
                project_data[proj] = {"sessions": 0, "messages": 0}
            project_data[proj]["sessions"] += 1
            project_data[proj]["messages"] += s.message_count

        # Top 3 projects with per-project stats
        top_projects = sorted(
            project_data.items(), key=lambda x: x[1]["messages"], reverse=True
        )[:3]
        for proj, data in top_projects:
            avg = data["messages"] / data["sessions"] if data["sessions"] else 0
            descriptor = ""
            if data["sessions"] > 50:
                descriptor = " — your most active project"
            elif avg > 30:
                descriptor = " — deep-focus work"
            elif avg < 8:
                descriptor = " — quick-fire sessions"
            insights.append(
                f"{proj}: {data['sessions']} sessions, avg {avg:.0f} msgs/session{descriptor}"
            )

    # Total stats
    total_sessions = summary.get("totalSessions", 0)
    total_messages = summary.get("totalMessages", 0)
    first_date = summary.get("firstSessionDate")
    if total_sessions > 0 and first_date:
        avg_per_session = total_messages / total_sessions
        insights.append(
            f"Average {avg_per_session:.0f} messages/session across {total_sessions} sessions "
            f"(since {first_date[:10]})"
        )

    return insights


def _detect_model_shift(daily_model_tokens: list[dict]) -> str:
    """Detect model shifts from daily token data."""
    if not daily_model_tokens or len(daily_model_tokens) < 3:
        return ""

    early_models: set[str] = set()
    late_models: set[str] = set()
    mid = len(daily_model_tokens) // 2

    for entry in daily_model_tokens[:mid]:
        for m in entry.get("tokensByModel", {}):
            early_models.add(_short_model(m))
    for entry in daily_model_tokens[mid:]:
        for m in entry.get("tokensByModel", {}):
            late_models.add(_short_model(m))

    dropped = early_models - late_models
    added = late_models - early_models

    if dropped or added:
        shift_date = daily_model_tokens[mid]["date"]
        for entry in daily_model_tokens:
            models_here = {_short_model(m) for m in entry.get("tokensByModel", {})}
            if added and added.issubset(models_here):
                shift_date = entry["date"]
                break

        early_str = " + ".join(sorted(early_models))
        late_str = " + ".join(sorted(late_models))
        return (
            f"Model shift: {early_str} \u2192 {late_str} (around {shift_date})"
        )
    return ""


class AnalysisView(Static):
    """Model usage, temporal patterns, and data-driven insights."""

    DEFAULT_CSS = """
    AnalysisView {
        height: 1fr;
    }
    AnalysisView Label {
        padding: 0 2;
        text-style: bold;
    }
    AnalysisView Button {
        margin: 1 2;
    }
    #analysis-charts-row {
        height: 14;
    }
    #analysis-charts-row-2 {
        height: 14;
    }
    #analysis-charts-row-3 {
        height: 14;
    }
    """

    def __init__(self, collectors: list[BaseCollector], db: EventStore) -> None:
        super().__init__()
        self._collectors = collectors
        self._db = db

    def compose(self) -> ComposeResult:
        yield Label("Session Analysis")
        with Horizontal(id="analysis-charts-row"):
            yield ModelUsageChart(id="model-usage-chart")
            yield DailyModelChart(id="daily-model-chart")
        with Horizontal(id="analysis-charts-row-2"):
            yield HourlyActivityChart(id="hourly-chart")
            yield ProjectBreakdownChart(id="project-chart")
        with Horizontal(id="analysis-charts-row-3"):
            yield IntentDistributionChart(id="intent-chart")
        yield DataInsights()
        yield Button("Refresh Analysis", id="btn-analyze", variant="primary")

    def on_mount(self) -> None:
        self._run_analysis()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-analyze":
            self._run_analysis()

    def _run_analysis(self) -> None:
        """Run data-driven analysis using real stats-cache data."""
        from agenttop.collectors.claude import ClaudeCodeCollector

        claude_collector = None
        for c in self._collectors:
            if isinstance(c, ClaudeCodeCollector):
                claude_collector = c
                break

        if claude_collector is None:
            self.query_one(DataInsights).update_insights(
                ["No Claude Code data found. Install and use Claude Code to see analysis."]
            )
            return

        # Model Usage Chart
        model_usage = claude_collector.get_model_usage()
        try:
            self.query_one(ModelUsageChart).replot(model_usage)
        except Exception:
            pass

        # Daily Model Tokens Chart
        daily_model = claude_collector.get_daily_model_tokens()
        try:
            self.query_one(DailyModelChart).replot(daily_model)
        except Exception:
            pass

        # Hourly Activity Chart
        hour_counts = claude_collector.get_hour_counts()
        try:
            self.query_one(HourlyActivityChart).replot(hour_counts)
        except Exception:
            pass

        # Collect sessions for project breakdown and insights
        sessions = claude_collector.collect_sessions()

        # Project Breakdown Chart
        try:
            project_counts: Counter[str] = Counter()
            for s in sessions:
                proj = s.project or "unknown"
                if "/" in proj:
                    proj = proj.rstrip("/").rsplit("/", 1)[-1]
                project_counts[proj] += s.message_count
            self.query_one(ProjectBreakdownChart).replot(dict(project_counts))
        except Exception:
            pass

        # Check LLM availability for intent classification + insights
        from agenttop.analysis.engine import check_llm_available

        llm_config = self.app.config.llm
        llm_error = check_llm_available(llm_config)

        if llm_error:
            # Fall back to local intent classification for the chart
            try:
                intent_counts: Counter[str] = Counter()
                for s in sessions:
                    for prompt in s.prompts:
                        if prompt.strip():
                            intent = classify_intent_local(prompt)
                            intent_counts[intent.value] += 1
                if intent_counts:
                    self.query_one(IntentDistributionChart).replot(dict(intent_counts))
            except Exception:
                pass

            self.query_one(DataInsights).update(
                f"[bold yellow]LLM Required for Analysis[/]\n\n[dim]{llm_error}[/]"
            )
            return

        # Show loading state for LLM-powered sections
        self.query_one(DataInsights).update(
            "[bold]Analyzing with LLM...[/]\n\n[dim]Classifying intents and generating insights — this may take a moment.[/]"
        )

        # Collect prompt samples for LLM classification
        all_prompts: list[str] = []
        for s in sessions:
            for prompt in s.prompts:
                if prompt.strip():
                    all_prompts.append(prompt)

        # Run LLM calls in worker thread
        self.run_worker(
            self._run_llm_analysis(all_prompts, sessions, claude_collector, llm_config),
            name="analysis_llm",
            group="analysis",
            exclusive=True,
        )

    async def _run_llm_analysis(self, all_prompts, sessions, collector, llm_config):
        """Run LLM intent classification and workflow analysis in a thread."""
        import asyncio

        return await asyncio.to_thread(
            self._build_llm_analysis, all_prompts, sessions, collector, llm_config
        )

    def _build_llm_analysis(self, all_prompts, sessions, collector, llm_config):
        """Classify intents via LLM and generate insights. Runs in worker thread."""
        from agenttop.analysis.engine import get_completion
        from agenttop.analysis.workflow import analyze_workflow_llm

        # ── LLM Intent Classification (batch) ──
        # Sample up to 50 prompts for batch classification
        sample = all_prompts[:50]
        intent_counts: Counter[str] = Counter()

        if sample:
            numbered = "\n".join(f"{i+1}. {p[:120]}" for i, p in enumerate(sample))
            batch_prompt = (
                "Classify each prompt into exactly one category.\n"
                "Categories: debugging, refactoring, greenfield, exploration, code_review, devops, documentation\n\n"
                f"Prompts:\n{numbered}\n\n"
                "Respond with ONLY a JSON array of category names, one per prompt, in order.\n"
                'Example: ["debugging", "exploration", "greenfield"]'
            )
            result = get_completion(
                batch_prompt,
                llm_config,
                system="You classify developer prompts into categories. Respond only with a JSON array.",
                max_tokens=512,
            )

            # Parse JSON array from response
            categories = self._parse_intent_batch(result, len(sample))
            for cat in categories:
                intent_counts[cat] += 1

            # Scale up if we sampled
            if len(all_prompts) > len(sample):
                scale = len(all_prompts) / len(sample)
                intent_counts = Counter({k: int(v * scale) for k, v in intent_counts.items()})

        # ── LLM Workflow Insights ──
        insights = analyze_workflow_llm(sessions, llm_config)

        return {"intent_counts": dict(intent_counts), "insights": insights}

    @staticmethod
    def _parse_intent_batch(result: str, expected_count: int) -> list[str]:
        """Parse batch intent classification result from LLM."""
        valid_categories = {
            "debugging", "refactoring", "greenfield", "exploration",
            "code_review", "devops", "documentation",
        }

        if result.startswith("[error]"):
            return ["unknown"] * expected_count

        # Try to extract JSON array
        try:
            categories = json.loads(result)
        except json.JSONDecodeError:
            start = result.find("[")
            end = result.rfind("]") + 1
            if start >= 0 and end > start:
                try:
                    categories = json.loads(result[start:end])
                except json.JSONDecodeError:
                    return ["unknown"] * expected_count
            else:
                return ["unknown"] * expected_count

        # Validate and normalize
        normalized = []
        for cat in categories:
            cat_lower = str(cat).strip().lower()
            if cat_lower in valid_categories:
                normalized.append(cat_lower)
            else:
                normalized.append("unknown")

        # Pad if LLM returned fewer than expected
        while len(normalized) < expected_count:
            normalized.append("unknown")

        return normalized[:expected_count]

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name != "analysis_llm":
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            # Update intent chart
            intent_counts = result.get("intent_counts", {})
            if intent_counts:
                try:
                    self.query_one(IntentDistributionChart).replot(intent_counts)
                except Exception:
                    pass

            # Update insights
            insights = result.get("insights", [])
            self.query_one(DataInsights).update_insights(insights)
            self.app.notify("Analysis updated with LLM insights")

        elif event.state == WorkerState.ERROR:
            self.query_one(DataInsights).update(
                f"[bold red]LLM analysis failed[/]\n\n[dim]{event.worker.error}[/]"
            )
            self.app.notify("Analysis updated with real usage data")
