"""Tests for data collectors."""

import json
import tempfile
from datetime import datetime
from pathlib import Path

from agenttop.collectors.claude import ClaudeCodeCollector
from agenttop.collectors.cursor import CursorCollector
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
    """Cursor collector returns empty data when dir doesn't exist."""
    c = CursorCollector(Path("/nonexistent"))
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
