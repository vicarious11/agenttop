"""GitHub Copilot data collector.

Parses data from VSCode's workspaceStorage for the github.copilot-chat extension:
  ~/Library/Application Support/Code/User/workspaceStorage/*/state.vscdb

Keys used:
- memento/interactive-session-view-copilot  → active session IDs (one per workspace)
- GitHub.copilot-chat                       → workspace-level Copilot settings/state

Also falls back to ~/.copilot/ if present (Copilot CLI / older installations).

Note: VSCode does not persist full Copilot chat history locally. The collector
reports detected sessions (one per workspace where Copilot was used) as a
conservative lower bound.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from agenttop.collectors.base import BaseCollector
from agenttop.models import Event, Session, ToolName, ToolStats

# VSCode workspaceStorage (macOS)
VSCODE_WS_DIR = Path.home() / "Library" / "Application Support" / "Code" / "User" / "workspaceStorage"
# VSCode globalStorage for Copilot
COPILOT_GLOBAL_DIR = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Code"
    / "User"
    / "globalStorage"
    / "github.copilot-chat"
)
# Legacy Copilot CLI dir
COPILOT_CLI_DIR = Path.home() / ".copilot"

TOKENS_PER_SESSION = 500
COST_PER_TOKEN = 0.000003


class CopilotCollector(BaseCollector):
    """Collects data from GitHub Copilot (VSCode extension)."""

    def __init__(self, copilot_dir: Path | None = None) -> None:
        self._dir = copilot_dir or COPILOT_CLI_DIR
        self._vscode_ws_dir = VSCODE_WS_DIR
        self._global_dir = COPILOT_GLOBAL_DIR

    @property
    def tool_name(self) -> ToolName:
        return ToolName.COPILOT

    def is_available(self) -> bool:
        return (
            self._global_dir.exists()
            or self._dir.exists()
        )

    # -- VSCode workspaceStorage helpers --

    def _get_vscode_sessions(self) -> list[dict]:
        """Scan VSCode workspaceStorage for workspaces where Copilot was used."""
        if not self._vscode_ws_dir.exists():
            return []

        sessions = []
        for db_file in self._vscode_ws_dir.rglob("state.vscdb"):
            try:
                conn = sqlite3.connect(str(db_file))
                conn.row_factory = sqlite3.Row

                # Check if Copilot was active in this workspace
                row = conn.execute(
                    "SELECT value FROM ItemTable WHERE key='memento/interactive-session-view-copilot'"
                ).fetchone()
                conn.close()

                if not row:
                    continue

                import json
                state = json.loads(row["value"])
                sid = state.get("sessionId", "")
                if not sid:
                    continue

                # Use DB file mtime as the session timestamp (best available proxy)
                mtime = datetime.fromtimestamp(db_file.stat().st_mtime)

                # Try to resolve project path from workspace.json
                project = None
                ws_json = db_file.parent / "workspace.json"
                if ws_json.exists():
                    try:
                        d = json.loads(ws_json.read_text())
                        folder = d.get("folder", "")
                        if folder:
                            project = folder.replace("file://", "")
                    except Exception:
                        pass

                sessions.append({
                    "session_id": sid,
                    "project": project,
                    "timestamp": mtime,
                    "mode": state.get("inputState", {}).get("chatMode", "ask"),
                })
            except (sqlite3.Error, OSError, ValueError):
                continue

        return sessions

    # -- Legacy ~/.copilot helpers --

    def _get_legacy_session_files(self) -> list[Path]:
        for subdir in ("session-state", "history-session-state"):
            sd = self._dir / subdir
            if sd.exists():
                return sorted(sd.iterdir(), key=lambda p: p.stat().st_mtime)
        return []

    # -- BaseCollector interface --

    def collect_events(self) -> list[Event]:
        events = []
        for s in self._get_vscode_sessions():
            events.append(
                Event(
                    tool=ToolName.COPILOT,
                    event_type="session",
                    timestamp=s["timestamp"],
                    session_id=s["session_id"],
                    data={"mode": s["mode"], "project": s["project"]},
                    token_count=TOKENS_PER_SESSION,
                )
            )
        # Legacy
        for sf in self._get_legacy_session_files():
            events.append(
                Event(
                    tool=ToolName.COPILOT,
                    event_type="session",
                    timestamp=datetime.fromtimestamp(sf.stat().st_mtime),
                    data={"file": sf.name},
                    token_count=TOKENS_PER_SESSION,
                )
            )
        return events

    def collect_sessions(self) -> list[Session]:
        sessions = []
        seen: set[str] = set()

        for s in self._get_vscode_sessions():
            sid = s["session_id"]
            if sid in seen:
                continue
            seen.add(sid)

            project_raw = s["project"] or ""
            project = None
            if project_raw:
                # Take last meaningful path component
                parts = project_raw.rstrip("/").split("/")
                project = parts[-1] if parts else None

            sessions.append(
                Session(
                    id=f"copilot-{sid}",
                    tool=ToolName.COPILOT,
                    project=project,
                    start_time=s["timestamp"],
                    end_time=s["timestamp"],
                    message_count=1,
                    total_tokens=TOKENS_PER_SESSION,
                    estimated_cost_usd=0.0,
                )
            )

        # Legacy
        for sf in self._get_legacy_session_files():
            mtime = datetime.fromtimestamp(sf.stat().st_mtime)
            sessions.append(
                Session(
                    id=f"copilot-{sf.stem}",
                    tool=ToolName.COPILOT,
                    start_time=mtime,
                    message_count=1,
                    total_tokens=TOKENS_PER_SESSION,
                    estimated_cost_usd=0.0,
                )
            )
        return sessions

    def get_stats(self, days: int = 0) -> ToolStats:
        stats = ToolStats(tool=ToolName.COPILOT)
        cutoff = (datetime.now() - timedelta(days=days)) if days > 0 else datetime(2000, 1, 1)

        hourly: list[int] = [0] * 24
        seen: set[str] = set()

        for s in self._get_vscode_sessions():
            if s["timestamp"] < cutoff:
                continue
            sid = s["session_id"]
            if sid not in seen:
                seen.add(sid)
                stats.sessions_today += 1
                stats.messages_today += 1
                stats.tokens_today += TOKENS_PER_SESSION
                hourly[s["timestamp"].hour] += TOKENS_PER_SESSION

        for sf in self._get_legacy_session_files():
            mtime = datetime.fromtimestamp(sf.stat().st_mtime)
            if mtime >= cutoff:
                stats.sessions_today += 1
                stats.messages_today += 1
                stats.tokens_today += TOKENS_PER_SESSION
                hourly[mtime.hour] += TOKENS_PER_SESSION

        stats.hourly_tokens = hourly
        # Copilot is subscription-based; no per-token cost
        stats.estimated_cost_today = 0.0
        if stats.sessions_today > 0:
            stats.status = "active"
        return stats

    def get_model_usage(self) -> dict[str, dict]:
        """Return Copilot session activity as a synthetic model usage entry.

        Copilot routes across multiple models (GPT-4o, Claude, etc.) internally;
        we report aggregate session counts under a single 'copilot/auto' key.
        """
        sessions = self._get_vscode_sessions()
        count = len(sessions)
        if count == 0:
            return {}
        estimated_tokens = count * TOKENS_PER_SESSION
        return {
            "copilot/auto": {
                "inputTokens": estimated_tokens,
                "outputTokens": 0,
                "cacheReadInputTokens": 0,
            }
        }
