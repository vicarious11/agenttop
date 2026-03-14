"""Tests for data collectors."""

import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from agenttop.collectors.claude import ClaudeCodeCollector
from agenttop.collectors.copilot import CopilotCollector
from agenttop.collectors.cursor import (
    CursorCollector,
    _AGENT_PRICE,
    _CHAT_PRICE,
    CURSOR_AGENT_CONTEXT_WINDOW,
    CURSOR_CHAT_CONTEXT_WINDOW,
    CURSOR_DEFAULT_CONTEXT_PCT,
    CURSOR_DEFAULT_INFERENCE_S,
    CURSOR_OUTPUT_TOKENS_PER_SEC,
)
from agenttop.collectors.kiro import KiroCollector
from agenttop.models import ToolName


def test_claude_collector_unavailable():
    """Claude collector returns empty data when dir doesn't exist."""
    c = ClaudeCodeCollector(Path("/nonexistent"))
    assert not c.is_available()
    assert c.tool_name == ToolName.CLAUDE_CODE


def test_claude_collector_stats_cache():
    """Claude collector parses stats-cache.json correctly."""
    tmp = Path(tempfile.mkdtemp())
    today = datetime.now().strftime("%Y-%m-%d")
    stats_data = {
        "version": 2,
        "dailyActivity": [
            {
                "date": today,
                "messageCount": 100,
                "sessionCount": 3,
                "toolCallCount": 50,
            }
        ],
    }
    (tmp / "stats-cache.json").write_text(json.dumps(stats_data))

    c = ClaudeCodeCollector(tmp)
    assert c.is_available()
    stats = c.get_stats()
    assert stats.sessions_today == 3
    assert stats.messages_today == 100
    assert stats.tool_calls_today == 50


def test_claude_collector_history():
    """Claude collector parses history.jsonl correctly."""
    tmp = Path(tempfile.mkdtemp())
    # Create a stats-cache.json too so get_stats works
    (tmp / "stats-cache.json").write_text('{"version":2,"dailyActivity":[]}')

    now_ms = int(datetime.now().timestamp() * 1000)
    lines = [
        json.dumps({"display": "fix the bug", "timestamp": now_ms, "project": "/test"}),
        json.dumps({"display": "add tests", "timestamp": now_ms + 1000, "project": "/test"}),
    ]
    (tmp / "history.jsonl").write_text("\n".join(lines))

    c = ClaudeCodeCollector(tmp)
    events = c.collect_events()
    assert len(events) == 2
    assert events[0].data["prompt"] == "fix the bug"

    sessions = c.collect_sessions()
    assert len(sessions) >= 1
    assert sessions[0].message_count == 2


def test_cursor_collector_unavailable():
    """Cursor collector returns empty data when neither dir exists."""
    c = CursorCollector(Path("/nonexistent"), ws_dir=Path("/nonexistent_ws"))
    assert not c.is_available()
    assert c.tool_name == ToolName.CURSOR


def test_kiro_collector_unavailable():
    """Kiro collector returns empty data when dir doesn't exist."""
    c = KiroCollector(Path("/nonexistent"))
    assert not c.is_available()
    assert c.tool_name == ToolName.KIRO


def test_claude_collector_project_memories():
    """Claude collector detects project memory files."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "stats-cache.json").write_text('{"version":2,"dailyActivity":[]}')

    proj_dir = tmp / "projects" / "my-project" / "memory"
    proj_dir.mkdir(parents=True)
    (proj_dir / "MEMORY.md").write_text("# Key patterns\n- Something important")

    c = ClaudeCodeCollector(tmp)
    memories = c._get_project_memories()
    assert len(memories) == 1
    assert "Something important" in list(memories.values())[0]


# ---------------------------------------------------------------------------
# CursorCollector._compute_session_cost
# ---------------------------------------------------------------------------

class TestComputeSessionCost:
    """Tests for CursorCollector._compute_session_cost."""

    def _collector(self) -> CursorCollector:
        return CursorCollector(Path("/nonexistent"))

    def test_agent_mode_with_kv_timing(self) -> None:
        """Agent mode with real timing data uses KV message count and inference ms."""
        c = self._collector()
        session = {"mode": "agent", "context_pct": 50.0, "lines_added": 0}
        kv = {"message_count": 4, "inference_ms": 20_000}  # 5s avg per message
        inp, out, cost = c._compute_session_cost(session, kv)

        # input = 4 * (50/100 * 200_000 * 0.6) = 4 * 60_000 = 240_000
        assert inp == 240_000
        # output = 4 * (5s * 50 tok/s) = 4 * 250 = 1_000
        assert out == 1_000
        assert cost > 0
        # cost uses agent pricing
        expected = (inp * _AGENT_PRICE["input"] + out * _AGENT_PRICE["output"]) / 1_000_000
        assert abs(cost - expected) < 0.0001

    def test_chat_mode_with_kv_timing(self) -> None:
        """Chat mode uses chat pricing rates."""
        c = self._collector()
        session = {"mode": "chat", "context_pct": 20.0, "lines_added": 0}
        kv = {"message_count": 2, "inference_ms": 10_000}
        inp, out, cost = c._compute_session_cost(session, kv)

        # input = 2 * (20/100 * 32_000 * 0.6) = 2 * 3_840 = 7_680
        assert inp == 7_680
        expected = (inp * _CHAT_PRICE["input"] + out * _CHAT_PRICE["output"]) / 1_000_000
        assert abs(cost - expected) < 0.0001

    def test_no_kv_data_falls_back_to_defaults(self) -> None:
        """Without KV timing, uses context_pct + lines_added fallback."""
        c = self._collector()
        session = {"mode": "chat", "context_pct": 10.0, "lines_added": 0}
        inp, out, cost = c._compute_session_cost(session, None)

        expected_inp = int(10.0 / 100 * CURSOR_CHAT_CONTEXT_WINDOW)
        expected_out = max(0 * 5, int(CURSOR_DEFAULT_INFERENCE_S * CURSOR_OUTPUT_TOKENS_PER_SEC))
        assert inp == expected_inp
        assert out == expected_out
        assert cost > 0

    def test_no_kv_data_lines_added_drives_output(self) -> None:
        """Without KV timing, output tokens are driven by lines_added when large."""
        c = self._collector()
        session = {"mode": "agent", "context_pct": 5.0, "lines_added": 500}
        inp, out, cost = c._compute_session_cost(session, None)

        expected_out = max(500 * 5, int(CURSOR_DEFAULT_INFERENCE_S * CURSOR_OUTPUT_TOKENS_PER_SEC))
        assert out == expected_out

    def test_zero_context_pct_uses_default(self) -> None:
        """context_pct=0 falls back to CURSOR_DEFAULT_CONTEXT_PCT."""
        c = self._collector()
        session = {"mode": "chat", "context_pct": 0.0, "lines_added": 0}
        kv = {"message_count": 1, "inference_ms": 0}
        inp, out, cost = c._compute_session_cost(session, kv)

        # Should use CURSOR_DEFAULT_CONTEXT_PCT, not 0
        assert inp > 0

    def test_missing_kv_entry_treated_as_no_kv(self) -> None:
        """kv=None and kv={} both fall back to the no-timing path."""
        c = self._collector()
        session = {"mode": "chat", "context_pct": 8.0, "lines_added": 0}
        inp_none, out_none, _ = c._compute_session_cost(session, None)
        inp_empty, out_empty, _ = c._compute_session_cost(session, {})
        assert inp_none == inp_empty
        assert out_none == out_empty


# ---------------------------------------------------------------------------
# CopilotCollector.collect_sessions — workspace detection
# ---------------------------------------------------------------------------

_ws_db_counter = 0


def _make_vscode_workspace_db(tmp_dir: Path, session_id: str, project_folder: str | None = None) -> Path:
    """Create a minimal VSCode workspace DB with Copilot session data."""
    global _ws_db_counter
    _ws_db_counter += 1
    ws_dir = tmp_dir / f"ws{_ws_db_counter}"
    ws_dir.mkdir(parents=True)
    db_path = ws_dir / "state.vscdb"

    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
    state = json.dumps({"sessionId": session_id, "inputState": {"chatMode": "ask"}})
    conn.execute(
        "INSERT INTO ItemTable VALUES (?, ?)",
        ("memento/interactive-session-view-copilot", state),
    )
    conn.commit()
    conn.close()

    if project_folder:
        (ws_dir / "workspace.json").write_text(json.dumps({"folder": f"file://{project_folder}"}))

    return db_path


class TestCopilotCollectSessions:
    """Tests for CopilotCollector.collect_sessions."""

    def test_detects_session_from_vscode_workspace(self, tmp_path: Path) -> None:
        """A VSCode workspace DB with Copilot session data produces a Session."""
        ws_dir = tmp_path / "workspaceStorage"
        ws_dir.mkdir()
        _make_vscode_workspace_db(ws_dir, session_id="abc123", project_folder="/home/user/myproject")

        c = CopilotCollector.__new__(CopilotCollector)
        c._dir = tmp_path / "copilot"
        c._vscode_ws_dir = ws_dir
        c._global_dir = tmp_path / "global"

        sessions = c.collect_sessions()
        assert len(sessions) == 1
        assert sessions[0].tool == ToolName.COPILOT
        assert sessions[0].project == "myproject"
        assert sessions[0].id == "copilot-abc123"

    def test_deduplicates_same_session_id(self, tmp_path: Path) -> None:
        """Two workspace DBs with the same session ID yield one Session."""
        ws_dir = tmp_path / "workspaceStorage"
        ws_dir.mkdir()
        _make_vscode_workspace_db(ws_dir, session_id="dup-id")
        _make_vscode_workspace_db(ws_dir, session_id="dup-id")

        c = CopilotCollector.__new__(CopilotCollector)
        c._dir = tmp_path / "copilot"
        c._vscode_ws_dir = ws_dir
        c._global_dir = tmp_path / "global"

        sessions = c.collect_sessions()
        ids = [s.id for s in sessions]
        assert ids.count("copilot-dup-id") == 1

    def test_no_vscode_dir_returns_empty(self, tmp_path: Path) -> None:
        c = CopilotCollector.__new__(CopilotCollector)
        c._dir = tmp_path / "copilot"
        c._vscode_ws_dir = tmp_path / "nonexistent"
        c._global_dir = tmp_path / "global"

        sessions = c.collect_sessions()
        assert sessions == []

    def test_get_model_usage_returns_zero_tokens(self, tmp_path: Path) -> None:
        """Copilot get_model_usage must not return fabricated token counts."""
        ws_dir = tmp_path / "workspaceStorage"
        ws_dir.mkdir()
        _make_vscode_workspace_db(ws_dir, session_id="s1")

        c = CopilotCollector.__new__(CopilotCollector)
        c._dir = tmp_path / "copilot"
        c._vscode_ws_dir = ws_dir
        c._global_dir = tmp_path / "global"

        usage = c.get_model_usage()
        assert "copilot/auto" in usage
        assert usage["copilot/auto"]["inputTokens"] == 0
        assert usage["copilot/auto"]["outputTokens"] == 0


# ---------------------------------------------------------------------------
# Multi-collector aggregation for /api/models and /api/hours
# ---------------------------------------------------------------------------

class TestMultiCollectorAggregation:
    """Tests for the aggregation logic used by /api/models and /api/hours."""

    def _make_mock_collector(self, model_usage: dict, hourly_tokens: list[int]) -> object:
        """Build a minimal collector stub."""
        from unittest.mock import MagicMock
        from agenttop.models import ToolStats

        collector = MagicMock()
        collector.is_available.return_value = True
        collector.get_model_usage.return_value = model_usage
        stats = ToolStats(tool=ToolName.CLAUDE_CODE)
        stats.hourly_tokens = hourly_tokens
        collector.get_stats.return_value = stats
        return collector

    def test_api_models_merges_overlapping_keys(self) -> None:
        """Two collectors reporting the same model key merge token counts."""
        combined: dict = {}
        for usage in [
            {"claude-sonnet": {"inputTokens": 100, "outputTokens": 50}},
            {"claude-sonnet": {"inputTokens": 200, "outputTokens": 80}},
        ]:
            for model, data in usage.items():
                if model in combined:
                    for k, v in data.items():
                        combined[model][k] = combined[model].get(k, 0) + v
                else:
                    combined[model] = dict(data)

        assert combined["claude-sonnet"]["inputTokens"] == 300
        assert combined["claude-sonnet"]["outputTokens"] == 130

    def test_api_models_distinct_keys_kept_separate(self) -> None:
        combined: dict = {}
        for usage in [
            {"cursor-agent": {"inputTokens": 500, "outputTokens": 100}},
            {"copilot/auto": {"inputTokens": 0, "outputTokens": 0, "sessionCount": 3}},
        ]:
            for model, data in usage.items():
                if model in combined:
                    for k, v in data.items():
                        combined[model][k] = combined[model].get(k, 0) + v
                else:
                    combined[model] = dict(data)

        assert "cursor-agent" in combined
        assert "copilot/auto" in combined
        assert combined["copilot/auto"]["sessionCount"] == 3

    def test_api_hours_sums_across_collectors(self) -> None:
        """Hourly token counts are summed across collectors."""
        combined: dict[str, int] = {}
        for hourly in [
            [0] * 9 + [100] + [0] * 14,   # hour 9: 100
            [0] * 9 + [200] + [0] * 14,   # hour 9: 200
        ]:
            for hour, tokens in enumerate(hourly):
                if tokens > 0:
                    combined[str(hour)] = combined.get(str(hour), 0) + tokens

        assert combined.get("9") == 300

    def test_api_hours_empty_collectors_produce_empty_result(self) -> None:
        combined: dict[str, int] = {}
        for hourly in [[0] * 24, [0] * 24]:
            for hour, tokens in enumerate(hourly):
                if tokens > 0:
                    combined[str(hour)] = combined.get(str(hour), 0) + tokens
        assert combined == {}
