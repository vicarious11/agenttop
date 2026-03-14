"""OpenAI Codex CLI data collector.

Parses data from ~/.codex/:
- history.jsonl — command history with timestamps
- sessions/YYYY/MM/DD/rollout-*.jsonl — full conversation transcripts
- config.toml — model selection, reasoning_effort
- .codex-global-state.json — prompt history, agent mode, electron state
- sqlite/codex-dev.db — automations, automation_runs, inbox_items
- models_cache.json — cached model names
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from agenttop.collectors.base import BaseCollector
from agenttop.models import Event, Session, ToolName, ToolStats

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

logger = logging.getLogger(__name__)

CODEX_DIR = Path.home() / ".codex"
TOKENS_PER_MESSAGE = 600
COST_PER_TOKEN = 0.000005


def _safe_read_json(path: Path) -> Any:
    """Read and parse a JSON file, returning None on any error."""
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _safe_read_toml(path: Path) -> dict[str, Any]:
    """Read and parse a TOML file, returning empty dict on any error."""
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _parse_timestamp(ts: Any) -> datetime | None:
    """Convert a timestamp value (int, float, or ISO string) to datetime."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts if ts < 1e12 else ts / 1000)
    try:
        return datetime.fromisoformat(str(ts))
    except ValueError:
        return None


class CodexCollector(BaseCollector):
    """Collects data from OpenAI Codex CLI."""

    def __init__(self, codex_dir: Path | None = None) -> None:
        self._dir = codex_dir or CODEX_DIR

    @property
    def tool_name(self) -> ToolName:
        return ToolName.CODEX

    def is_available(self) -> bool:
        return self._dir.exists()

    # ── File parsers ─────────────────────────────────────────────

    def _parse_history(self) -> list[dict[str, Any]]:
        """Parse history.jsonl into a list of records."""
        path = self._dir / "history.jsonl"
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
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
        """List all rollout session files sorted by path."""
        sessions_dir = self._dir / "sessions"
        if not sessions_dir.exists():
            return []
        return sorted(sessions_dir.rglob("rollout-*.jsonl"))

    def _parse_session_file(self, path: Path) -> list[dict[str, Any]]:
        """Parse a single rollout JSONL session file."""
        records: list[dict[str, Any]] = []
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

    # ── New enrichment parsers ───────────────────────────────────

    def _parse_global_state(self) -> dict[str, Any]:
        """Read .codex-global-state.json for prompt history, agent mode, etc."""
        path = self._dir / ".codex-global-state.json"
        raw = _safe_read_json(path)
        if not isinstance(raw, dict):
            return {}

        result: dict[str, Any] = {}

        prompt_history = raw.get("prompt-history")
        if isinstance(prompt_history, list):
            result["prompt_history"] = list(prompt_history)

        agent_mode = raw.get("agent-mode")
        if agent_mode is not None:
            result["agent_mode"] = agent_mode

        # Collect other electron-persisted-atom-state keys
        skip_keys = {"prompt-history", "agent-mode"}
        extra: dict[str, Any] = {
            k: v for k, v in raw.items() if k not in skip_keys
        }
        if extra:
            result["electron_state"] = extra

        return result

    def _parse_codex_db(self) -> dict[str, Any]:
        """Query codex-dev.db for automations, runs, and inbox items."""
        db_path = self._dir / "sqlite" / "codex-dev.db"
        if not db_path.exists():
            return {}

        result: dict[str, Any] = {}
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Discover which tables exist
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor.fetchall()}

            if "automations" in tables:
                cursor.execute("SELECT count(*) as cnt FROM automations")
                count = cursor.fetchone()[0]
                names: list[str] = []
                statuses: list[str] = []
                cursor.execute("SELECT name, status FROM automations")
                for row in cursor.fetchall():
                    if row[0]:
                        names.append(str(row[0]))
                    if row[1]:
                        statuses.append(str(row[1]))
                result["automations"] = {
                    "count": count,
                    "names": names,
                    "statuses": statuses,
                }

            if "automation_runs" in tables:
                cursor.execute("SELECT count(*) as cnt FROM automation_runs")
                run_count = cursor.fetchone()[0]
                last_run = None
                try:
                    cursor.execute("SELECT max(created_at) FROM automation_runs")
                    raw_ts = cursor.fetchone()[0]
                    if raw_ts is not None:
                        last_run = str(raw_ts)
                except sqlite3.OperationalError:
                    pass
                result["automation_runs"] = {
                    "count": run_count,
                    "last_run": last_run,
                }

            if "inbox_items" in tables:
                cursor.execute("SELECT count(*) as cnt FROM inbox_items")
                result["inbox_items"] = {
                    "count": cursor.fetchone()[0],
                }

            conn.close()
        except (sqlite3.Error, OSError) as exc:
            logger.debug("Failed to read codex-dev.db: %s", exc)
        return result

    def _parse_models_cache(self) -> list[str]:
        """Read models_cache.json and return model name strings."""
        path = self._dir / "models_cache.json"
        raw = _safe_read_json(path)
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw if isinstance(item, str)]

    def _parse_config(self) -> dict[str, Any]:
        """Read config.toml for model selection and reasoning_effort."""
        path = self._dir / "config.toml"
        raw = _safe_read_toml(path)
        if not raw:
            return {}

        result: dict[str, Any] = {}
        model = raw.get("model")
        if model is not None:
            result["model"] = model
        reasoning = raw.get("reasoning_effort")
        if reasoning is not None:
            result["reasoning_effort"] = reasoning

        # Include other top-level keys that may be useful
        skip_keys = {"model", "reasoning_effort"}
        for key, val in raw.items():
            if key not in skip_keys:
                result[key] = val

        return result

    # ── Enriched public API ──────────────────────────────────────

    def get_feature_config(self) -> dict[str, Any]:
        """Return combined feature configuration from all Codex sources."""
        config: dict[str, Any] = {}

        global_state = self._parse_global_state()
        if global_state:
            config["global_state"] = global_state

        db_info = self._parse_codex_db()
        if db_info:
            config["database"] = db_info

        models = self._parse_models_cache()
        if models:
            config["models_cache"] = models

        toml_config = self._parse_config()
        if toml_config:
            config["config"] = toml_config

        return config

    def collect_events(self) -> list[Event]:
        """Collect events from history.jsonl and automation_runs."""
        events: list[Event] = []

        # Events from history.jsonl
        for rec in self._parse_history():
            dt = _parse_timestamp(rec.get("timestamp") or rec.get("ts"))
            if dt is None:
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

        # Events from automation_runs in codex-dev.db
        db_path = self._dir / "sqlite" / "codex-dev.db"
        if db_path.exists():
            try:
                conn = sqlite3.connect(str(db_path))
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='automation_runs'"
                )
                if cursor.fetchone():
                    cursor.execute(
                        "SELECT * FROM automation_runs ORDER BY rowid"
                    )
                    for row in cursor.fetchall():
                        row_dict = dict(row)
                        raw_ts = row_dict.get("created_at") or row_dict.get("timestamp")
                        dt = _parse_timestamp(raw_ts)
                        if dt is None:
                            continue
                        events.append(
                            Event(
                                tool=ToolName.CODEX,
                                event_type="automation_run",
                                timestamp=dt,
                                data={
                                    k: v for k, v in row_dict.items()
                                    if k not in ("created_at", "timestamp")
                                },
                                token_count=TOKENS_PER_MESSAGE,
                            )
                        )
                conn.close()
            except (sqlite3.Error, OSError) as exc:
                logger.debug("Failed to read automation_runs: %s", exc)

        return events

    def collect_sessions(self) -> list[Session]:
        """Collect sessions from rollout files, falling back to prompt history."""
        sessions: list[Session] = []
        session_files = self._list_session_files()

        for sf in session_files:
            records = self._parse_session_file(sf)
            if not records:
                continue
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

        # If no rollout files exist, create sessions from prompt history
        if not session_files:
            global_state = self._parse_global_state()
            prompt_history = global_state.get("prompt_history", [])
            if prompt_history:
                now = datetime.now()
                for idx, prompt in enumerate(prompt_history):
                    prompt_text = str(prompt) if prompt else ""
                    if not prompt_text:
                        continue
                    sessions.append(
                        Session(
                            id=f"codex-prompt-{idx}",
                            tool=ToolName.CODEX,
                            start_time=now,
                            end_time=now,
                            message_count=1,
                            total_tokens=TOKENS_PER_MESSAGE,
                            estimated_cost_usd=TOKENS_PER_MESSAGE * COST_PER_TOKEN,
                            prompts=[prompt_text],
                        )
                    )

        return sessions

    def get_stats(self, days: int = 0) -> ToolStats:
        """Return aggregated stats for the dashboard."""
        stats = ToolStats(tool=ToolName.CODEX)
        cutoff = (
            datetime.now() - timedelta(days=days)
            if days > 0
            else datetime(2000, 1, 1)
        )

        for ev in self.collect_events():
            if ev.timestamp >= cutoff:
                stats.messages_today += 1
                stats.tokens_today += TOKENS_PER_MESSAGE
                stats.hourly_tokens[ev.timestamp.hour] += TOKENS_PER_MESSAGE

        for s in self.collect_sessions():
            if s.start_time >= cutoff:
                stats.sessions_today += 1

        stats.estimated_cost_today = stats.tokens_today * COST_PER_TOKEN
        if stats.messages_today > 0:
            stats.status = "active"
        return stats
