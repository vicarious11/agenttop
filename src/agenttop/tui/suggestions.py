"""Suggestions view — LLM-powered workflow report card."""

from __future__ import annotations

from collections import Counter

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Button, Static
from textual.worker import Worker, WorkerState

from agenttop.collectors.base import BaseCollector
from agenttop.db import EventStore
from agenttop.formatting import human_cost, human_number, human_tokens


def _short_model(model_id: str) -> str:
    parts = model_id.split("-")
    if parts and len(parts[-1]) >= 8 and parts[-1].isdigit():
        parts = parts[:-1]
    name = "-".join(parts)
    if name.startswith("claude-"):
        name = name[7:]
    return name


def _short_project(project: str) -> str:
    """Extract short project name from path."""
    if "/" in project:
        project = project.rstrip("/").rsplit("/", 1)[-1]
    return project or "(unknown)"


class SuggestionsContent(Static):
    """Rich text display for suggestions."""

    DEFAULT_CSS = """
    SuggestionsContent {
        padding: 1 2;
        height: auto;
    }
    """


class SuggestionsView(Static):
    """LLM-powered workflow report card based on real usage data."""

    DEFAULT_CSS = """
    SuggestionsView {
        height: 1fr;
    }
    SuggestionsView Button {
        margin: 1 2;
    }
    #suggestions-scroll {
        height: 1fr;
    }
    """

    def __init__(self, collectors: list[BaseCollector], db: EventStore) -> None:
        super().__init__()
        self._collectors = collectors
        self._db = db

    def compose(self) -> ComposeResult:
        yield Button("Refresh", id="btn-suggest", variant="primary")
        with VerticalScroll(id="suggestions-scroll"):
            yield SuggestionsContent(id="suggestions-content")

    def on_mount(self) -> None:
        self._generate()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-suggest":
            self._generate()

    def _generate(self) -> None:
        """Generate personalized report card from real data via LLM."""
        from agenttop.collectors.claude import ClaudeCodeCollector

        claude = None
        for c in self._collectors:
            if isinstance(c, ClaudeCodeCollector):
                claude = c

        if not claude or not claude.is_available():
            self._set_content(
                "[dim]No AI tool data found. Use Claude Code and check back.[/]"
            )
            return

        # Check LLM availability
        from agenttop.analysis.engine import check_llm_available

        llm_config = self.app.config.llm
        llm_error = check_llm_available(llm_config)
        if llm_error:
            self._set_content(
                "[bold yellow]LLM Required for Analysis[/]\n\n"
                f"[dim]{llm_error}[/]"
            )
            return

        # Show loading state
        self._set_content("[bold]Generating report card...[/]\n\n[dim]Querying LLM — this may take a few seconds.[/]")

        # Run LLM analysis in a worker thread
        self.run_worker(
            self._run_llm_analysis(claude, llm_config),
            name="suggestions_llm",
            group="suggestions",
            exclusive=True,
        )

    async def _run_llm_analysis(self, claude, llm_config) -> str:
        """Gather data and call LLM in a thread, return formatted result."""
        import asyncio

        return await asyncio.to_thread(self._build_llm_report, claude, llm_config)

    def _build_llm_report(self, claude, llm_config) -> str:
        """Gather stats and call LLM for analysis. Runs in worker thread."""
        from agenttop.analysis.engine import get_completion
        from agenttop.analysis.workflow import generate_data_insights

        # Gather all data (same as before — fast, local)
        sessions = claude.collect_sessions()
        model_usage = claude.get_model_usage()
        summary = claude.get_session_summary()
        memories = claude._get_project_memories()
        total_cost = claude.get_real_cost()
        total_tokens = claude.get_real_token_count()
        first_date = (summary.get("firstSessionDate") or "")[:10]

        # Project breakdown
        project_prompts: Counter[str] = Counter()
        project_sessions: Counter[str] = Counter()
        for s in sessions:
            proj = _short_project(s.project or "unknown")
            project_prompts[proj] += s.message_count
            project_sessions[proj] += 1

        total_prompts = sum(project_prompts.values())
        total_sessions = len(sessions)

        # Session size distribution
        sizes = [s.message_count for s in sessions]
        under10 = sum(1 for s in sizes if s <= 10)
        mid_range = sum(1 for s in sizes if 11 <= s <= 50)
        over50 = sum(1 for s in sizes if s > 50)
        median_size = sorted(sizes)[len(sizes) // 2] if sizes else 0

        # Prompt analysis
        prompts_with_paste = 0
        prompt_lengths: list[int] = []
        history = claude._parse_history()
        for rec in history:
            pasted = rec.get("pastedContents")
            if pasted and isinstance(pasted, dict) and len(pasted) > 0:
                prompts_with_paste += 1
            display = rec.get("display", "")
            if display:
                prompt_lengths.append(len(display))

        avg_prompt_len = sum(prompt_lengths) / len(prompt_lengths) if prompt_lengths else 0

        # Model cost breakdown
        model_cost_lines = []
        from agenttop.collectors.claude import _match_model_pricing
        for model_id, usage in sorted(
            model_usage.items(),
            key=lambda x: x[1].get("inputTokens", 0) + x[1].get("outputTokens", 0),
            reverse=True,
        ):
            pricing = _match_model_pricing(model_id)
            model_cost = (
                usage.get("inputTokens", 0) / 1_000_000 * pricing["input"]
                + usage.get("outputTokens", 0) / 1_000_000 * pricing["output"]
                + usage.get("cacheReadInputTokens", 0) / 1_000_000 * pricing["cache_read"]
                + usage.get("cacheCreationInputTokens", 0) / 1_000_000 * pricing["cache_create"]
            )
            cache_read = usage.get("cacheReadInputTokens", 0)
            input_t = usage.get("inputTokens", 0)
            total_input = cache_read + input_t
            cache_hit = (cache_read / total_input * 100) if total_input > 0 else 0
            model_cost_lines.append(
                f"  {_short_model(model_id)}: {human_cost(model_cost)}, "
                f"input={human_tokens(input_t)}, output={human_tokens(usage.get('outputTokens', 0))}, "
                f"cache_hit={cache_hit:.0f}%"
            )

        # Projects with CLAUDE.md status
        top_projects = project_prompts.most_common(5)
        project_lines = []
        for proj, cnt in top_projects:
            has_memory = any(proj in k for k in memories)
            status = "has CLAUDE.md" if has_memory else "NO CLAUDE.md"
            sess = project_sessions.get(proj, 0)
            pct = cnt / total_prompts * 100 if total_prompts else 0
            project_lines.append(
                f"  {proj}: {human_number(cnt)} prompts ({pct:.0f}%), {sess} sessions, {status}"
            )

        # Build structured summary for LLM
        data_summary = f"""USAGE DATA SUMMARY
==================
Period: since {first_date}
Total: {total_sessions} sessions, {human_number(total_prompts)} prompts, {human_tokens(total_tokens)} tokens, ~{human_cost(total_cost)} cost

SESSION PATTERNS
  Under 10 messages: {under10} ({under10 / total_sessions * 100 if total_sessions else 0:.0f}%)
  11-50 messages: {mid_range} ({mid_range / total_sessions * 100 if total_sessions else 0:.0f}%)
  Over 50 messages: {over50} ({over50 / total_sessions * 100 if total_sessions else 0:.0f}%)
  Median session: {median_size} messages

PROJECTS (top {len(top_projects)})
{chr(10).join(project_lines)}

MODEL COSTS
{chr(10).join(model_cost_lines)}

PROMPT QUALITY
  Average prompt length: {avg_prompt_len:.0f} chars
  Prompts with pasted content: {prompts_with_paste}/{total_prompts} ({prompts_with_paste / total_prompts * 100 if total_prompts else 0:.0f}%)
"""

        # Call LLM for full analysis
        prompt = f"""You are a developer productivity analyst reviewing AI coding tool usage data.

Analyze the following usage data and produce a concise workflow report card. Use plain text formatting (no markdown headers, no **, no ##). Use CAPS for section titles. Use simple dashes for bullet points.

Structure your response as:

YOUR WORKFLOW PROFILE
- Summary of usage patterns, dominant project, session behavior

SCORE CARDS
For each area, give a letter grade (A/B/C/D) and 1-2 line explanation:
- Session Hygiene: grade based on session length distribution (too many short restarts = bad, too many 100+ message sessions = bad)
- Project Focus: grade based on CLAUDE.md coverage for active projects
- Cost Efficiency: grade based on model mix and cost per message
- Prompt Quality: grade based on prompt lengths and pasted content usage

TOP 3 ACTIONS
Numbered, specific, actionable recommendations with real numbers from the data.

Here is the data:

{data_summary}"""

        result = get_completion(prompt, llm_config, max_tokens=1024)

        if result.startswith("[error]"):
            return f"[bold red]LLM Error[/]\n\n[dim]{result}[/]"

        return result

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name != "suggestions_llm":
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            self._set_content(result)
        elif event.state == WorkerState.ERROR:
            self._set_content(
                "[bold red]Analysis failed[/]\n\n"
                f"[dim]{event.worker.error}[/]"
            )

    def _set_content(self, text: str) -> None:
        content = self.query_one("#suggestions-content", SuggestionsContent)
        content.update(text)
