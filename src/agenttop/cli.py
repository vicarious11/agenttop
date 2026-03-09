"""CLI entry point for agenttop."""

from __future__ import annotations

import os

import click

from agenttop import __version__

DAYS_HELP = (
    "Time range in days. 0=all time, 1=today, 7=last week, 30=last month."
)


@click.group(invoke_without_command=True)
@click.version_option(version=__version__)
@click.option("--days", default=0, help=DAYS_HELP)
@click.pass_context
def main(ctx: click.Context, days: int) -> None:
    """agenttop — htop for AI coding agents.

    Monitor token usage, costs, and workflows across Claude Code,
    Cursor, Kiro, and any AI tool via local proxy.
    """
    ctx.ensure_object(dict)
    ctx.obj["days"] = days
    if ctx.invoked_subcommand is None:
        _launch_tui(days)


@main.command()
@click.option("--days", default=0, help=DAYS_HELP)
def dashboard(days: int) -> None:
    """Launch the interactive TUI dashboard."""
    _launch_tui(days)


@main.command()
def init() -> None:
    """Initialize agenttop configuration."""
    from agenttop.config import init_config

    path = init_config()
    click.echo(f"Config written to {path}")
    click.echo()

    # Check if Ollama is running (default provider)
    ollama_ok = _check_ollama()
    if ollama_ok:
        click.echo(click.style("  [ready] Ollama detected — optimizer will use local LLM", fg="green"))
    else:
        click.echo("  Ollama not detected. To enable the AI-powered optimizer:")
        click.echo()
        click.echo("    brew install ollama          # install")
        click.echo("    ollama pull qwen3:1.7b       # download model (~1GB)")
        click.echo("    ollama serve                 # start (keep running)")
        click.echo()
        click.echo("  Or use a cloud provider instead (edit config.toml):")

    # Detect available cloud API keys
    _KEY_CHECKS = [
        ("Anthropic", "ANTHROPIC_API_KEY"),
        ("OpenAI", "OPENAI_API_KEY"),
        ("OpenRouter", "OPENROUTER_API_KEY"),
    ]
    for name, env_var in _KEY_CHECKS:
        if os.environ.get(env_var):
            click.echo(click.style(f"  [found] {name} API key detected ({env_var})", fg="green"))

    click.echo()
    click.echo("Data monitoring works without an LLM — just launch: agenttop web")


@main.command()
@click.option("--days", default=0, help=DAYS_HELP)
def stats(days: int) -> None:
    """Show quick stats summary (non-interactive)."""
    from agenttop.collectors.claude import ClaudeCodeCollector
    from agenttop.collectors.codex import CodexCollector
    from agenttop.collectors.copilot import CopilotCollector
    from agenttop.collectors.cursor import CursorCollector
    from agenttop.collectors.kiro import KiroCollector
    from agenttop.config import load_config

    config = load_config()
    range_label = _range_label(days)

    click.echo(f"agenttop — AI Tool Usage Summary ({range_label})\n")
    click.echo("=" * 60)

    collectors = [
        ("Claude Code", ClaudeCodeCollector(config.claude_dir)),
        ("Cursor", CursorCollector(config.cursor_dir)),
        ("Kiro", KiroCollector(config.kiro_dir)),
        ("Codex", CodexCollector()),
        ("Copilot", CopilotCollector()),
    ]

    from agenttop.formatting import human_cost, human_tokens

    total_tokens = 0
    total_cost = 0.0

    for name, collector in collectors:
        if not collector.is_available():
            click.echo(f"\n  {name:<12} [not found]")
            continue
        s = collector.get_stats(days=days)
        total_tokens += s.tokens_today
        total_cost += s.estimated_cost_today
        click.echo(f"\n  {name:<12} [{s.status}]")
        click.echo(f"    Sessions:    {s.sessions_today}")
        click.echo(f"    Messages:    {s.messages_today:,}")
        click.echo(f"    Tool calls:  {s.tool_calls_today}")
        click.echo(f"    Est. tokens: {human_tokens(s.tokens_today)}")
        click.echo(f"    Est. cost:   {human_cost(s.estimated_cost_today)}")

        # Extra info for Cursor
        if isinstance(collector, CursorCollector):
            ratio = collector.get_ai_vs_human_ratio()
            if ratio["ai_lines"] + ratio["human_lines"] > 0:
                click.echo(
                    f"    AI/human:    {ratio['ai_percentage']:.0f}%"
                )

    click.echo(f"\n{'=' * 60}")
    click.echo(
        f"  TOTAL: {human_tokens(total_tokens)} tokens | "
        f"{human_cost(total_cost)} est. cost"
    )
    click.echo("=" * 60)
    click.echo("Run `agenttop` for the interactive dashboard.")


@main.command()
@click.option("--days", default=0, help=DAYS_HELP)
def analyze(days: int) -> None:
    """Run workflow analysis and show recommendations."""
    from datetime import datetime, timedelta

    from agenttop.analysis.workflow import analyze_workflow_local
    from agenttop.collectors.claude import ClaudeCodeCollector
    from agenttop.collectors.cursor import CursorCollector
    from agenttop.config import load_config

    config = load_config()
    range_label = _range_label(days)

    if days > 0:
        cutoff = datetime.now() - timedelta(days=days)
    else:
        cutoff = datetime(2000, 1, 1)

    click.echo(f"agenttop — Workflow Analysis ({range_label})\n")

    all_sessions = []
    claude = ClaudeCodeCollector(config.claude_dir)
    if claude.is_available():
        for s in claude.collect_sessions():
            if s.start_time >= cutoff:
                all_sessions.append(s)

    cursor = CursorCollector(config.cursor_dir)
    if cursor.is_available():
        for s in cursor.collect_sessions():
            if s.start_time >= cutoff:
                all_sessions.append(s)

    insights = analyze_workflow_local(all_sessions)

    click.echo("Insights:")
    for insight in insights:
        click.echo(f"  • {insight}")

    click.echo("\nRun `agenttop` for the full interactive dashboard.")


@main.command()
@click.option("--port", default=8420, help="Port for the web dashboard.")
@click.option("--no-browser", is_flag=True, help="Don't auto-open browser.")
@click.option(
    "--provider",
    type=click.Choice(["anthropic", "openai", "ollama", "openrouter"], case_sensitive=False),
    default=None,
    help="LLM provider for the optimizer.",
)
@click.option("--model", default=None, help="LLM model name for the optimizer.")
def web(port: int, no_browser: bool, provider: str | None, model: str | None) -> None:
    """Launch the web dashboard with knowledge graph."""
    import uvicorn

    from agenttop.config import CONFIG_FILE

    _apply_cli_overrides(provider, model)

    if not CONFIG_FILE.exists():
        click.echo("Tip: Run `agenttop init` to enable AI-powered optimizer")

    from agenttop.web.server import app

    url = f"http://localhost:{port}"
    click.echo(f"Dashboard running at {url} — Ctrl+C to stop")

    if not no_browser:
        import webbrowser

        webbrowser.open(url)

    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    except KeyboardInterrupt:
        click.echo("\nDashboard stopped.")


@main.command()
@click.option("--port", default=9120, help="Port for the proxy server.")
def proxy(port: int) -> None:
    """Start the local API proxy for generic tool monitoring."""
    import asyncio

    from agenttop.collectors.proxy import ProxyCollector, run_proxy
    from agenttop.config import ProxyConfig

    config = ProxyConfig(enabled=True, port=port)
    collector = ProxyCollector(config)

    click.echo(f"Starting agenttop proxy on http://127.0.0.1:{port}")
    click.echo(
        "Set your AI tool's base URL to this address "
        "to capture token usage."
    )
    click.echo("Press Ctrl+C to stop.\n")

    try:
        asyncio.run(run_proxy(config, collector))
    except KeyboardInterrupt:
        click.echo("\nProxy stopped.")


def _check_ollama() -> bool:
    """Quick check if Ollama is running locally."""
    import urllib.request

    try:
        req = urllib.request.Request("http://localhost:11434", method="GET")
        with urllib.request.urlopen(req, timeout=2):
            return True
    except Exception:
        return False


def _apply_cli_overrides(provider: str | None, model: str | None) -> None:
    """Set env vars so load_config() picks up CLI flag overrides."""
    if provider:
        os.environ["AGENTTOP_LLM_PROVIDER"] = provider
    if model:
        os.environ["AGENTTOP_LLM_MODEL"] = model


def _range_label(days: int) -> str:
    labels = {0: "all time", 1: "today", 7: "last 7 days", 30: "last 30 days"}
    return labels.get(days, f"last {days} days")


def _launch_tui(days: int = 0) -> None:
    """Launch the Textual TUI."""
    from agenttop.tui.app import AgentTop

    app = AgentTop(days=days)
    app.run()
