"""Knowledge Graph view — tree visualization of project/tool/model relationships."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Button, Static, Tree

from agenttop.collectors.base import BaseCollector
from agenttop.db import EventStore
from agenttop.formatting import human_duration_ms, human_number, human_tokens


class KnowledgeGraphView(Static):
    """Tree widget showing project/tool/model/session hierarchy."""

    DEFAULT_CSS = """
    KnowledgeGraphView {
        height: 1fr;
    }
    KnowledgeGraphView Button {
        margin: 1 2;
    }
    KnowledgeGraphView Tree {
        height: 1fr;
        margin: 0 1;
    }
    """

    def __init__(
        self,
        collectors: list[BaseCollector],
        db: EventStore,
    ) -> None:
        super().__init__()
        self._collectors = collectors
        self._db = db

    def compose(self) -> ComposeResult:
        yield Button("Refresh Graph", id="btn-refresh-kg", variant="primary")
        yield Tree("agenttop Knowledge Graph", id="kg-tree")

    def on_mount(self) -> None:
        self._build_tree()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-refresh-kg":
            self._build_tree()
            self.app.notify("Knowledge graph refreshed")

    def _build_tree(self) -> None:
        tree = self.query_one("#kg-tree", Tree)
        tree.clear()
        root = tree.root

        for collector in self._collectors:
            from agenttop.collectors.claude import ClaudeCodeCollector
            from agenttop.collectors.cursor import CursorCollector

            if isinstance(collector, ClaudeCodeCollector):
                self._build_claude_subtree(root, collector)
            elif isinstance(collector, CursorCollector):
                self._build_cursor_subtree(root, collector)
            else:
                self._build_generic_subtree(root, collector)

        root.expand()

    def _build_claude_subtree(self, root: Tree, collector) -> None:
        summary = collector.get_session_summary()
        total_sessions = summary.get("totalSessions", 0)
        total_messages = summary.get("totalMessages", 0)

        node = root.add(
            f"[orange]Claude Code[/] ({total_sessions} sessions, {human_number(total_messages)} messages)",
        )

        # -- Models --
        model_usage = collector.get_model_usage()
        if model_usage:
            models_node = node.add("[bold]Models[/]")
            for model_id, usage in sorted(
                model_usage.items(),
                key=lambda x: x[1].get("cacheReadInputTokens", 0),
                reverse=True,
            ):
                short_name = _short_model_name(model_id)
                cache_read = usage.get("cacheReadInputTokens", 0)
                output = usage.get("outputTokens", 0)
                input_t = usage.get("inputTokens", 0)
                cache_create = usage.get("cacheCreationInputTokens", 0)

                model_node = models_node.add(
                    f"[cyan]{short_name}[/] "
                    f"({human_tokens(cache_read)} cache read, "
                    f"{human_tokens(output)} output)"
                )
                model_node.add(f"Input: {human_tokens(input_t)}")
                model_node.add(f"Output: {human_tokens(output)}")
                model_node.add(f"Cache read: {human_tokens(cache_read)}")
                model_node.add(f"Cache create: {human_tokens(cache_create)}")

                # Cache hit rate
                total_input = cache_read + input_t
                if total_input > 0:
                    hit_rate = cache_read / total_input * 100
                    model_node.add(f"Cache hit rate: {hit_rate:.1f}%")

        # -- Projects --
        try:
            sessions = collector.collect_sessions()
            project_counts: dict[str, dict] = {}
            for s in sessions:
                proj = s.project or "unknown"
                if "/" in proj:
                    proj = proj.rstrip("/").rsplit("/", 1)[-1]
                if proj not in project_counts:
                    project_counts[proj] = {"prompts": 0, "sessions": 0}
                project_counts[proj]["prompts"] += s.message_count
                project_counts[proj]["sessions"] += 1

            if project_counts:
                projects_node = node.add("[bold]Projects[/]")
                for proj, counts in sorted(
                    project_counts.items(),
                    key=lambda x: x[1]["prompts"],
                    reverse=True,
                ):
                    projects_node.add(
                        f"{proj} ({human_number(counts['prompts'])} prompts, "
                        f"{counts['sessions']} sessions)"
                    )
        except Exception:
            pass

        # -- Peak Hours --
        hour_counts = collector.get_hour_counts()
        if hour_counts:
            hours_node = node.add("[bold]Peak Hours[/]")
            sorted_hours = sorted(
                hour_counts.items(),
                key=lambda x: x[1],
                reverse=True,
            )
            for hour, count in sorted_hours[:6]:
                bar = "█" * min(count, 20)
                hours_node.add(f"{int(hour):02d}:00 — {count} sessions {bar}")

        # -- Records --
        records_node = node.add("[bold]Records[/]")
        longest = summary.get("longestSession", {})
        if longest.get("messageCount"):
            duration_str = human_duration_ms(longest.get("duration", 0))
            records_node.add(
                f"Longest session: {longest['messageCount']:,} messages ({duration_str})"
            )

        first_date = summary.get("firstSessionDate")
        if first_date:
            records_node.add(f"First session: {first_date[:10]}")

        records_node.add(
            f"Total: {total_sessions} sessions, {human_number(total_messages)} messages"
        )

        node.expand()

    def _build_cursor_subtree(self, root: Tree, collector) -> None:
        try:
            stats = collector.get_stats()
            ratio = collector.get_ai_vs_human_ratio()
        except Exception:
            root.add("[cyan]Cursor[/] (error reading data)")
            return

        node = root.add(
            f"[cyan]Cursor[/] ({stats.sessions_today} sessions, "
            f"{human_number(stats.messages_today)} messages)"
        )

        if ratio.get("ai_lines", 0) + ratio.get("human_lines", 0) > 0:
            node.add(f"AI vs Human: {ratio['ai_percentage']:.0f}% AI code")
        node.add(f"Tokens: {human_tokens(stats.tokens_today)}")
        node.expand()

    def _build_generic_subtree(self, root: Tree, collector: BaseCollector) -> None:
        try:
            stats = collector.get_stats()
        except Exception:
            return

        display_name = collector.tool_name.value.replace("_", " ").title()
        node = root.add(
            f"{display_name} ({stats.sessions_today} sessions, "
            f"{human_number(stats.messages_today)} messages)"
        )
        node.add(f"Tokens: {human_tokens(stats.tokens_today)}")
        node.expand()


def _short_model_name(model_id: str) -> str:
    """Shorten model IDs: 'claude-opus-4-5-20251101' → 'opus-4-5'."""
    # Remove date suffix
    parts = model_id.split("-")
    # Check if last part is a date-like number
    if parts and len(parts[-1]) >= 8 and parts[-1].isdigit():
        parts = parts[:-1]
    name = "-".join(parts)
    # Remove 'claude-' prefix for brevity
    if name.startswith("claude-"):
        name = name[7:]
    return name
