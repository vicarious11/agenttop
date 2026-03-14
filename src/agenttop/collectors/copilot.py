"""GitHub Copilot CLI — parses ~/.copilot/ config, session-state/, and agents/."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from agenttop.collectors.base import BaseCollector
from agenttop.models import Event, Session, ToolName, ToolStats

logger = logging.getLogger(__name__)

COPILOT_DIR = Path.home() / ".copilot"
TOKENS_PER_MESSAGE = 500
COST_PER_TOKEN = 0.000003


def _extract_session_data(parsed: dict) -> dict[str, Any]:
    """Extract message count, model, and token estimate from parsed session JSON."""
    messages = parsed.get("messages", parsed.get("conversation", []))
    message_count = len(messages) if isinstance(messages, list) else 0

    model = parsed.get("model", parsed.get("settings", {}).get("model", ""))
    total_chars = 0
    for msg in (messages if isinstance(messages, list) else []):
        content = msg.get("content", "") if isinstance(msg, dict) else ""
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total_chars += len(block.get("text", ""))
    if total_chars:
        token_estimate = max(total_chars // 4, TOKENS_PER_MESSAGE)
    else:
        token_estimate = TOKENS_PER_MESSAGE

    return {
        "message_count": max(message_count, 1),
        "model": model,
        "token_estimate": token_estimate,
    }


class CopilotCollector(BaseCollector):
    """Collects data from GitHub Copilot CLI."""

    def __init__(self, copilot_dir: Path | None = None) -> None:
        self._dir = copilot_dir or COPILOT_DIR

    @property
    def tool_name(self) -> ToolName:
        return ToolName.COPILOT

    def is_available(self) -> bool:
        return self._dir.exists()

    def _get_session_files(self) -> list[Path]:
        sd = self._dir / "session-state"
        if not sd.exists():
            sd = self._dir / "history-session-state"
        if not sd.exists():
            return []
        try:
            return sorted(sd.iterdir(), key=lambda p: p.stat().st_mtime)
        except OSError:
            return []

    def _parse_session_file(self, path: Path) -> dict:
        try:
            text = path.read_text(errors="replace")
            return json.loads(text)
        except (json.JSONDecodeError, OSError):
            return {}

    def collect_events(self) -> list[Event]:
        events: list[Event] = []
        for sf in self._get_session_files():
            try:
                mtime = datetime.fromtimestamp(sf.stat().st_mtime)
            except OSError:
                continue

            parsed = self._parse_session_file(sf)
            session_data = _extract_session_data(parsed) if parsed else {
                "message_count": 1, "model": "", "token_estimate": TOKENS_PER_MESSAGE,
            }

            data: dict[str, Any] = {"file": sf.name}
            if session_data["model"]:
                data["model"] = session_data["model"]

            events.append(
                Event(
                    tool=ToolName.COPILOT,
                    event_type="session",
                    timestamp=mtime,
                    data=data,
                    token_count=session_data["token_estimate"],
                )
            )
        return events

    def collect_sessions(self) -> list[Session]:
        sessions: list[Session] = []
        for sf in self._get_session_files():
            try:
                mtime = datetime.fromtimestamp(sf.stat().st_mtime)
            except OSError:
                continue

            parsed = self._parse_session_file(sf)
            session_data = _extract_session_data(parsed) if parsed else {
                "message_count": 1, "model": "", "token_estimate": TOKENS_PER_MESSAGE,
            }

            tokens = session_data["token_estimate"]
            sessions.append(
                Session(
                    id=f"copilot-{sf.stem}",
                    tool=ToolName.COPILOT,
                    start_time=mtime,
                    message_count=session_data["message_count"],
                    total_tokens=tokens,
                    estimated_cost_usd=tokens * COST_PER_TOKEN,
                )
            )
        return sessions

    def get_stats(self, days: int = 0) -> ToolStats:
        stats = ToolStats(tool=ToolName.COPILOT)
        cutoff = (
            datetime.now() - timedelta(days=days) if days > 0
            else datetime(2000, 1, 1)
        )

        for sf in self._get_session_files():
            try:
                mtime = datetime.fromtimestamp(sf.stat().st_mtime)
            except OSError:
                continue
            if mtime < cutoff:
                continue

            parsed = self._parse_session_file(sf)
            session_data = _extract_session_data(parsed) if parsed else {
                "message_count": 1, "model": "", "token_estimate": TOKENS_PER_MESSAGE,
            }

            tokens = session_data["token_estimate"]
            stats.sessions_today += 1
            stats.messages_today += session_data["message_count"]
            stats.tokens_today += tokens
            stats.hourly_tokens[mtime.hour] += tokens

        stats.estimated_cost_today = stats.tokens_today * COST_PER_TOKEN
        if stats.messages_today > 0:
            stats.status = "active"
        return stats

    def get_feature_config(self) -> dict[str, Any]:
        """Detect Copilot feature configuration from ~/.copilot/."""
        result: dict[str, Any] = {}

        # Parse config file for user preferences
        config_path = self._dir / "config"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(errors="replace"))
                result["config"] = {
                    "exists": True,
                    "settings": {
                        k: v for k, v in config.items()
                        if isinstance(v, (str, bool, int, float))
                    },
                }
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("Failed to parse copilot config: %s", e)
                result["config"] = {"exists": True, "parse_error": True}
        else:
            result["config"] = {"exists": False}

        # Detect custom agent definitions
        agents_dir = self._dir / "agents"
        if agents_dir.exists():
            try:
                agent_files = list(agents_dir.glob("*.agent.md"))
                result["agents"] = {
                    "count": len(agent_files),
                    "names": [f.stem.removesuffix(".agent") for f in agent_files],
                }
            except OSError:
                result["agents"] = {"count": 0, "names": []}
        else:
            result["agents"] = {"count": 0, "names": []}

        return result
