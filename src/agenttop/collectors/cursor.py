"""Cursor IDE data collector.

Parses data from Cursor's workspaceStorage SQLite databases:
  ~/Library/Application Support/Cursor/User/workspaceStorage/*/state.vscdb

Per-workspace tables used:
- composer.composerData  → allComposers list (sessions, names, linesAdded, mode)
- aiService.prompts      → list of prompts with text
- aiService.generations  → list of AI generations with timestamps

Falls back to ~/.cursor/ai-tracking/ai-code-tracking.db when workspaceStorage
is unavailable (Windows / Linux / older Cursor).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from agenttop.collectors.base import BaseCollector
from agenttop.config import CURSOR_DIR
from agenttop.models import Event, Session, ToolName, ToolStats

# Cursor workspaceStorage path (macOS)
CURSOR_WS_DIR = Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "workspaceStorage"
# Cursor global KV database (macOS)
CURSOR_GLOBAL_DB = Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "state.vscdb"

# ── Token / cost model ────────────────────────────────────────────────────────
# Agent mode uses Claude Sonnet (200 K context, Sonnet pricing).
# Chat  mode uses cursor-small / lighter models (32 K context, GPT-4o-mini tier).
#
# We estimate tokens per message as:
#   input  = avg_context_pct × context_window   (context grows linearly → 0.6× final)
#   output = avg_inference_seconds × OUTPUT_TOKENS_PER_SEC
#
# When timing / context data is unavailable we fall back to conservative defaults
# calibrated so that all-time totals roughly match Cursor's billing history.

CURSOR_AGENT_CONTEXT_WINDOW = 200_000   # Claude 3.5/3.7 Sonnet context
CURSOR_CHAT_CONTEXT_WINDOW  =  32_000   # cursor-small / GPT-4o-mini context
CURSOR_CONTEXT_GROWTH_FACTOR = 0.6      # context grows linearly; avg ≈ 60 % of final
CURSOR_DEFAULT_CONTEXT_PCT   = 15.0     # fallback when contextUsagePercent == 0
CURSOR_OUTPUT_TOKENS_PER_SEC = 50       # streaming throughput for Sonnet
CURSOR_DEFAULT_INFERENCE_S   = 15.0     # per-message fallback (no timing data)

# USD per million tokens — sourced from cursor.com/pricing (checked March 2026).
# Agent mode bills at Claude Sonnet rates; Chat mode at cursor-small / GPT-4o-mini rates.
_AGENT_PRICE = {"input": 3.00, "output": 15.00}   # Claude Sonnet
_CHAT_PRICE  = {"input": 0.15, "output":  0.60}   # cursor-small / GPT-4o-mini

# Legacy fallbacks (unused on modern data paths)
TOKENS_PER_CONVERSATION_ESTIMATE = 2_000
TOKENS_PER_PROMPT_ESTIMATE        =   800

_CONTAINER_DIRS = {
    "repo", "repos", "desktop", "projects", "dev", "src", "code", "work", "documents",
    "applications", "apps", "sites", "workspace", "workspaces", "home", "users",
}


def _project_from_path(filepath: str) -> str | None:
    """Extract project name from an absolute file path."""
    if not filepath or not filepath.startswith("/"):
        return None
    home = str(Path.home())
    rel = filepath[len(home) + 1:] if filepath.startswith(home + "/") else filepath.lstrip("/")
    parts = rel.split("/")
    for i, part in enumerate(parts):
        if part.lower() not in _CONTAINER_DIRS:
            if "." in part and i == len(parts) - 1:
                return None
            return part
    return None


class CursorCollector(BaseCollector):
    """Collects data from Cursor's local SQLite databases."""

    def __init__(self, cursor_dir: Path | None = None, ws_dir: Path | None = None) -> None:
        self._dir = cursor_dir or CURSOR_DIR
        self._db_path = self._dir / "ai-tracking" / "ai-code-tracking.db"
        self._ws_dir = ws_dir if ws_dir is not None else CURSOR_WS_DIR

    @property
    def tool_name(self) -> ToolName:
        return ToolName.CURSOR

    def is_available(self) -> bool:
        return self._ws_dir.exists() or self._db_path.exists()

    # -- workspaceStorage helpers --

    def _workspace_dbs(self) -> list[tuple[Path, str | None]]:
        """Yield (db_path, project_path) for all Cursor workspace databases."""
        if not self._ws_dir.exists():
            return []
        result = []
        for db_file in self._ws_dir.rglob("state.vscdb"):
            project = None
            ws_json = db_file.parent / "workspace.json"
            if ws_json.exists():
                try:
                    import json
                    d = __import__("json").loads(ws_json.read_text())
                    folder = d.get("folder", "")
                    if folder:
                        project = folder.replace("file://", "")
                except Exception:
                    pass
            result.append((db_file, project))
        return result

    def _read_db_key(self, db_path: Path, key: str) -> object:
        """Read a single JSON value from ItemTable by key."""
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
            conn.close()
            if row:
                import json
                return json.loads(row["value"])
        except (sqlite3.Error, OSError, ValueError):
            pass
        return None

    def _get_global_kv_data(self) -> dict[str, dict]:
        """Read composerData entries from the global Cursor KV database.

        Returns a dict keyed by composerId:
          message_count       – assistant messages with timingInfo (real AI responses)
          inference_ms        – total RPC-send→settle time (actual model inference, not RTT)
          project_from_files  – project name from first codeBlock fsPath
          context_pct         – contextUsagePercent at end of session
          lines_added         – totalLinesAdded
        """
        import json

        if not CURSOR_GLOBAL_DB.exists():
            return {}

        result: dict[str, dict] = {}
        try:
            conn = sqlite3.connect(str(CURSOR_GLOBAL_DB))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'"
            ).fetchall()
            conn.close()
        except (sqlite3.Error, OSError):
            return {}

        for row in rows:
            key: str = row["key"]
            composer_id = key.split(":", 1)[1] if ":" in key else ""
            if not composer_id:
                continue
            val = row["value"]
            if not val:
                continue
            try:
                data = json.loads(val)
            except (ValueError, TypeError):
                continue

            conversation = data.get("conversation") or []
            message_count = 0
            inference_ms = 0          # rpcSend → settle (pure model time)
            project_from_files: str | None = None

            for msg in conversation:
                if not isinstance(msg, dict) or msg.get("type") != 2:
                    continue
                timing = msg.get("timingInfo")
                if isinstance(timing, dict):
                    message_count += 1
                    rpc  = timing.get("clientRpcSendTime", 0) or 0
                    settle = timing.get("clientSettleTime", 0) or 0
                    if settle > rpc:
                        inference_ms += settle - rpc

                if project_from_files is None:
                    for cb in msg.get("codeBlocks") or []:
                        if isinstance(cb, dict):
                            uri = cb.get("uri") or {}
                            fspath = uri.get("fsPath", "") if isinstance(uri, dict) else ""
                            if fspath:
                                project_from_files = _project_from_path(fspath)
                                break

            result[composer_id] = {
                "message_count": message_count,
                "inference_ms": inference_ms,
                "project_from_files": project_from_files,
                "context_pct": data.get("contextUsagePercent", 0.0) or 0.0,
                "lines_added": data.get("totalLinesAdded", 0) or 0,
            }

        return result

    def _parse_workspace_sessions(
        self, db_path: Path, project: str | None, since_ms: int
    ) -> dict[str, dict]:
        """Read composer sessions from one workspace DB.

        Returns a dict keyed by composerId with raw session data.
        Only sessions created after *since_ms* are included.
        """
        sessions: dict[str, dict] = {}
        data = self._read_db_key(db_path, "composer.composerData")
        if not isinstance(data, dict):
            return sessions
        for comp in data.get("allComposers", []):
            cid = comp.get("composerId", "")
            if not cid:
                continue
            created_ms = comp.get("createdAt", 0) or 0
            updated_ms = comp.get("lastUpdatedAt", created_ms) or created_ms
            if since_ms and created_ms < since_ms:
                continue
            sessions[cid] = {
                "session_id": cid,
                "project": project,
                "created_ms": created_ms,
                "updated_ms": updated_ms,
                "name": comp.get("name", ""),
                "mode": comp.get("unifiedMode", "chat"),
                "lines_added": comp.get("totalLinesAdded", 0) or 0,
                "lines_removed": comp.get("totalLinesRemoved", 0) or 0,
                "context_pct": comp.get("contextUsagePercent", 0.0) or 0.0,
                "files_changed": comp.get("filesChangedCount", 0) or 0,
                "prompts": [],
                "tokens": 0,
            }
        return sessions

    def _attach_prompts(
        self, sessions: dict[str, dict], db_path: Path, project: str | None
    ) -> None:
        """Attach prompts from aiService.prompts to the most recent session for this workspace."""
        prompts = self._read_db_key(db_path, "aiService.prompts")
        if not isinstance(prompts, list):
            return
        ws_sessions = [s for s in sessions.values() if s["project"] == project]
        if not ws_sessions:
            return
        target = max(ws_sessions, key=lambda s: s["created_ms"])
        for p in prompts:
            if isinstance(p, dict):
                txt = p.get("text", "")
                if txt and len(target["prompts"]) < 50:
                    target["prompts"].append(txt[:500])

    def _attach_generation_tokens(
        self, sessions: dict[str, dict], db_path: Path, project: str | None, since_ms: int
    ) -> None:
        """Add token estimates from aiService.generations to the most recent workspace session."""
        gens = self._read_db_key(db_path, "aiService.generations")
        if not isinstance(gens, list):
            return
        ws_sessions = [s for s in sessions.values() if s["project"] == project]
        if not ws_sessions:
            return
        target = max(ws_sessions, key=lambda s: s["created_ms"])
        for g in gens:
            if not isinstance(g, dict):
                continue
            g_ms = g.get("unixMs", 0) or 0
            if since_ms and g_ms < since_ms:
                continue
            target["tokens"] += TOKENS_PER_PROMPT_ESTIMATE

    def _enrich_with_kv(self, sessions: dict[str, dict], kv: dict[str, dict]) -> None:
        """Enrich sessions with global KV data (timing, context, lines, project)."""
        for s in sessions.values():
            kv_entry = kv.get(s["session_id"])
            if not kv_entry:
                continue
            if not s["project"] and kv_entry["project_from_files"]:
                s["project"] = kv_entry["project_from_files"]
            if kv_entry["message_count"] > 0:
                s["message_count"] = kv_entry["message_count"]
            if kv_entry["context_pct"]:
                s["context_pct"] = kv_entry["context_pct"]
            if kv_entry["lines_added"]:
                s["lines_added"] = kv_entry["lines_added"]

    def _compute_costs_for_sessions(self, sessions: dict[str, dict], kv: dict[str, dict]) -> None:
        """Compute and attach cost fields (input_tokens, output_tokens, estimated_cost) to all sessions."""
        for s in sessions.values():
            kv_entry = kv.get(s["session_id"])
            inp, out, cost = self._compute_session_cost(s, kv_entry)
            s["input_tokens"] = inp
            s["output_tokens"] = out
            s["tokens"] = inp + out
            s["estimated_cost"] = cost

    def _get_all_workspace_data(self, since: datetime | None = None) -> list[dict]:
        """Aggregate composer sessions from all workspace databases."""
        since_ms = int(since.timestamp() * 1000) if since else 0
        sessions: dict[str, dict] = {}

        for db_path, project in self._workspace_dbs():
            sessions.update(self._parse_workspace_sessions(db_path, project, since_ms))
            self._attach_prompts(sessions, db_path, project)
            self._attach_generation_tokens(sessions, db_path, project, since_ms)

        kv = self._get_global_kv_data()
        self._enrich_with_kv(sessions, kv)
        self._compute_costs_for_sessions(sessions, kv)

        return list(sessions.values())

    def _compute_session_cost(self, s: dict, kv: dict | None) -> tuple[int, int, float]:
        """Return (input_tokens, output_tokens, cost_usd) for one session.

        Model:
          input  = message_count × avg_context_pct × context_window × growth_factor
          output = message_count × avg_inference_seconds × OUTPUT_TOKENS_PER_SEC

        Message count priority:
          1. Real KV timing count (most accurate)
          2. Lines-added heuristic (agent sessions that generated code)
          3. Default = 1  (never use prompts list — those are workspace-level, not per session)
        """
        mode = s.get("mode", "chat")
        kv_msgs      = (kv or {}).get("message_count", 0) or 0
        kv_inference = (kv or {}).get("inference_ms",   0) or 0
        context_pct  = s.get("context_pct") or CURSOR_DEFAULT_CONTEXT_PCT
        lines_added  = s.get("lines_added", 0) or 0

        if mode == "agent":
            window    = CURSOR_AGENT_CONTEXT_WINDOW
            inp_price = _AGENT_PRICE["input"]
            out_price = _AGENT_PRICE["output"]
        else:
            window    = CURSOR_CHAT_CONTEXT_WINDOW
            inp_price = _CHAT_PRICE["input"]
            out_price = _CHAT_PRICE["output"]

        if kv_msgs > 0:
            # Best case: real message count + inference timing from KV
            # Context grows linearly → average = 60 % of final pct
            avg_ctx_pct    = context_pct * CURSOR_CONTEXT_GROWTH_FACTOR
            input_per_msg  = int(avg_ctx_pct / 100 * window)
            avg_inf_s      = kv_inference / 1000 / kv_msgs if kv_inference else CURSOR_DEFAULT_INFERENCE_S
            output_per_msg = int(avg_inf_s * CURSOR_OUTPUT_TOKENS_PER_SEC)
            total_input    = input_per_msg  * kv_msgs
            total_output   = output_per_msg * kv_msgs
        else:
            # No timing data — treat as a single request at peak context.
            # Input  = context at peak (already includes all prior turns implicitly).
            # Output = lines of code × ~5 tokens/line, or one default response.
            total_input  = int(context_pct / 100 * window)
            total_output = max(lines_added * 5, int(CURSOR_DEFAULT_INFERENCE_S * CURSOR_OUTPUT_TOKENS_PER_SEC))

        cost = (total_input * inp_price + total_output * out_price) / 1_000_000
        return total_input, total_output, cost

    # -- Legacy ai-code-tracking.db helpers --

    def _connect_legacy(self) -> sqlite3.Connection | None:
        if not self._db_path.exists():
            return None
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _get_conversations(self, since_ms: int = 0) -> list[dict]:
        conn = self._connect_legacy()
        if not conn:
            return []
        try:
            rows = conn.execute(
                "SELECT * FROM conversation_summaries WHERE updatedAt >= ? ORDER BY updatedAt DESC",
                (since_ms,),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except (sqlite3.Error, OSError):
            return []

    def _get_scored_commits(self, since_ms: int = 0) -> list[dict]:
        conn = self._connect_legacy()
        if not conn:
            return []
        try:
            rows = conn.execute(
                "SELECT * FROM scored_commits WHERE scoredAt >= ? ORDER BY scoredAt DESC",
                (since_ms,),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except (sqlite3.Error, OSError):
            return []

    # -- BaseCollector interface --

    def collect_events(self) -> list[Event]:
        events = []
        if self._ws_dir.exists():
            for s in self._get_all_workspace_data():
                created_ms = s["created_ms"]
                if not created_ms:
                    continue
                ts = datetime.fromtimestamp(created_ms / 1000)
                events.append(
                    Event(
                        tool=ToolName.CURSOR,
                        event_type="composer",
                        timestamp=ts,
                        session_id=s["session_id"],
                        project=_project_from_path(s["project"] or ""),
                        data={
                            "name": s["name"],
                            "mode": s["mode"],
                            "lines_added": s["lines_added"],
                        },
                        token_count=s["tokens"] or TOKENS_PER_PROMPT_ESTIMATE,
                    )
                )
        return events

    def collect_sessions(self) -> list[Session]:
        if self._ws_dir.exists():
            sessions = []
            for s in self._get_all_workspace_data():
                created_ms = s["created_ms"]
                if not created_ms:
                    continue
                start = datetime.fromtimestamp(created_ms / 1000)
                end_ms = s["updated_ms"] or created_ms
                end = datetime.fromtimestamp(end_ms / 1000)
                project = _project_from_path(s["project"] or "") if s["project"] else None
                sessions.append(
                    Session(
                        id=s["session_id"],
                        tool=ToolName.CURSOR,
                        project=project,
                        start_time=start,
                        end_time=end,
                        message_count=max(1, s.get("message_count") or len(s["prompts"])),
                        total_tokens=s.get("tokens") or TOKENS_PER_CONVERSATION_ESTIMATE,
                        estimated_cost_usd=s.get("estimated_cost", 0.0),
                        prompts=s["prompts"],
                    )
                )
            return sessions

        # Legacy: conversation_summaries
        sessions = []
        for conv in self._get_conversations():
            updated_ms = conv.get("updatedAt", 0)
            if not updated_ms:
                continue
            ts = datetime.fromtimestamp(updated_ms / 1000)
            sessions.append(
                Session(
                    id=conv.get("conversationId", "unknown"),
                    tool=ToolName.CURSOR,
                    start_time=ts,
                    end_time=ts,
                    message_count=1,
                    total_tokens=TOKENS_PER_CONVERSATION_ESTIMATE,
                    estimated_cost_usd=TOKENS_PER_CONVERSATION_ESTIMATE * COST_PER_TOKEN,
                    prompts=[conv.get("title", ""), conv.get("tldr", "")],
                )
            )
        return sessions

    def get_stats(self, days: int = 0) -> ToolStats:
        stats = ToolStats(tool=ToolName.CURSOR)
        if days > 0:
            since = datetime.now() - timedelta(days=days)
        else:
            since = datetime(2000, 1, 1)

        if self._ws_dir.exists():
            hourly: list[int] = [0] * 24
            seen: set[str] = set()
            for s in self._get_all_workspace_data(since=since):
                created_ms = s["created_ms"]
                if not created_ms:
                    continue
                ts = datetime.fromtimestamp(created_ms / 1000)
                sid = s["session_id"]
                if sid not in seen:
                    seen.add(sid)
                    stats.sessions_today += 1
                msg_count = max(1, s.get("message_count") or len(s["prompts"]))
                stats.messages_today += msg_count
                stats.tokens_today += s.get("tokens") or TOKENS_PER_CONVERSATION_ESTIMATE
                stats.tool_calls_today += s["lines_added"] > 0
                hourly[ts.hour] += s.get("tokens") or TOKENS_PER_CONVERSATION_ESTIMATE
                stats.estimated_cost_today += s.get("estimated_cost", 0.0)
            stats.hourly_tokens = hourly
            if stats.sessions_today > 0:
                stats.status = "active"
            return stats

        # Legacy path
        since_ms = int(since.timestamp() * 1000)
        convs = self._get_conversations(since_ms=since_ms)
        stats.sessions_today = len(convs)
        stats.messages_today = len(convs)
        stats.tokens_today = len(convs) * TOKENS_PER_CONVERSATION_ESTIMATE
        stats.estimated_cost_today = stats.tokens_today * COST_PER_TOKEN
        if convs:
            stats.status = "active"
        return stats

    def get_model_usage(self) -> dict[str, dict]:
        """Return per-mode token breakdown with correct input/output split."""
        agent: dict[str, int] = {"inputTokens": 0, "outputTokens": 0}
        chat:  dict[str, int] = {"inputTokens": 0, "outputTokens": 0}
        for s in self._get_all_workspace_data():
            bucket = agent if s.get("mode") == "agent" else chat
            bucket["inputTokens"]  += s.get("input_tokens",  0)
            bucket["outputTokens"] += s.get("output_tokens", 0)
        result = {}
        if agent["inputTokens"] + agent["outputTokens"]:
            result["cursor-agent"] = agent
        if chat["inputTokens"] + chat["outputTokens"]:
            result["cursor-chat"] = chat
        return result

    def get_ai_vs_human_ratio(self) -> dict:
        """Calculate AI vs human code contribution ratio from scored commits."""
        commits = self._get_scored_commits()
        total_ai = 0
        total_human = 0
        for c in commits:
            tab = c.get("tabLinesAdded") or 0
            composer = c.get("composerLinesAdded") or 0
            human = c.get("humanLinesAdded") or 0
            total_ai += tab + composer
            total_human += human
        total = total_ai + total_human
        return {
            "ai_lines": total_ai,
            "human_lines": total_human,
            "ai_percentage": (total_ai / total * 100) if total > 0 else 0,
        }
