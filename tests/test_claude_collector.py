"""Comprehensive tests for the Claude Code collector.

Covers: _ParsedMessage, _ParsedSession, _parse_timestamp, _match_model_pricing,
JSONL parsing, token accounting, cost calculation, and session collection.
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from agenttop.collectors.claude import (
    ClaudeCodeCollector,
    MODEL_PRICING,
    _ParsedMessage,
    _ParsedSession,
    _match_model_pricing,
    _parse_timestamp,
)
from agenttop.models import ToolName


# ── Helpers ──────────────────────────────────────────────────


def _make_user_entry(
    timestamp: str = "2026-03-12T10:00:00Z",
    content: str | list = "fix the bug",
    cwd: str = "/Users/test/myproject",
) -> dict:
    """Build a user-type JSONL entry."""
    return {
        "type": "user",
        "timestamp": timestamp,
        "message": {"content": content},
        "cwd": cwd,
    }


def _make_assistant_entry(
    timestamp: str = "2026-03-12T10:00:05Z",
    model: str = "claude-sonnet-4-5-20250514",
    input_tokens: int = 1000,
    output_tokens: int = 500,
    cache_read: int = 5000,
    cache_create: int = 2000,
    content: list | None = None,
) -> dict:
    """Build an assistant-type JSONL entry."""
    if content is None:
        content = [{"type": "text", "text": "Here's the fix"}]
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_create,
            },
            "content": content,
        },
    }


def _write_session_jsonl(
    base_dir: Path,
    project_name: str,
    session_id: str,
    entries: list[dict],
) -> Path:
    """Write entries as a .jsonl file under projects/{project_name}/{session_id}.jsonl."""
    project_dir = base_dir / "projects" / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = project_dir / f"{session_id}.jsonl"
    lines = [json.dumps(e) for e in entries]
    jsonl_path.write_text("\n".join(lines))
    return jsonl_path


@pytest.fixture()
def tmp_claude_dir() -> Path:
    """Return a fresh temp directory to use as the Claude data dir."""
    return Path(tempfile.mkdtemp())


# ── _ParsedMessage tests ────────────────────────────────────


class TestParsedMessage:
    def test_slots(self):
        """_ParsedMessage stores all expected attributes via __slots__."""
        msg = _ParsedMessage(
            timestamp=datetime(2026, 3, 12, 10, 0),
            model="claude-sonnet-4-5-20250514",
            input_tokens=1000,
            output_tokens=500,
            cache_read=5000,
            cache_create=2000,
            tool_calls=3,
            content_type="tool_use",
        )
        assert msg.timestamp == datetime(2026, 3, 12, 10, 0)
        assert msg.model == "claude-sonnet-4-5-20250514"
        assert msg.input_tokens == 1000
        assert msg.output_tokens == 500
        assert msg.cache_read == 5000
        assert msg.cache_create == 2000
        assert msg.tool_calls == 3
        assert msg.content_type == "tool_use"

    def test_no_dict(self):
        """_ParsedMessage uses __slots__ so has no __dict__."""
        msg = _ParsedMessage(
            timestamp=None, model="x", input_tokens=0, output_tokens=0,
            cache_read=0, cache_create=0, tool_calls=0, content_type="text",
        )
        assert not hasattr(msg, "__dict__")


# ── _ParsedSession tests ────────────────────────────────────


class TestParsedSession:
    def test_billed_tokens_excludes_cache(self):
        """billed_tokens = input + output, NOT cache."""
        session = _ParsedSession(session_id="s1", project="/proj")
        session.input_tokens = 1000
        session.output_tokens = 500
        session.cache_read = 50000
        session.cache_create = 20000
        assert session.billed_tokens == 1500

    def test_cost_with_messages(self):
        """cost() uses per-message model pricing when messages exist."""
        session = _ParsedSession(session_id="s1", project="/proj")
        msg = _ParsedMessage(
            timestamp=None,
            model="claude-sonnet-4-5-20250514",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_read=1_000_000,
            cache_create=1_000_000,
            tool_calls=0,
            content_type="text",
        )
        session.messages.append(msg)
        # sonnet-4-5: input=3.0, output=15.0, cache_read=0.3, cache_create=3.75
        expected = 3.0 + 15.0 + 0.3 + 3.75
        assert session.cost() == pytest.approx(expected)

    def test_cost_fallback_no_messages(self):
        """cost() falls back to sonnet-4-5 pricing when no messages exist."""
        session = _ParsedSession(session_id="s1", project="/proj")
        session.input_tokens = 1_000_000
        session.output_tokens = 1_000_000
        session.cache_read = 1_000_000
        session.cache_create = 1_000_000
        expected = 3.0 + 15.0 + 0.3 + 3.75
        assert session.cost() == pytest.approx(expected)

    def test_cost_skips_unknown_model(self):
        """cost() skips messages with unknown or synthetic model IDs."""
        session = _ParsedSession(session_id="s1", project="/proj")
        session.messages.append(_ParsedMessage(
            timestamp=None, model="unknown",
            input_tokens=1_000_000, output_tokens=1_000_000,
            cache_read=0, cache_create=0, tool_calls=0, content_type="text",
        ))
        session.messages.append(_ParsedMessage(
            timestamp=None, model="<system>",
            input_tokens=1_000_000, output_tokens=1_000_000,
            cache_read=0, cache_create=0, tool_calls=0, content_type="text",
        ))
        assert session.cost() == 0.0

    def test_cost_multiple_models(self):
        """cost() accumulates across messages with different models."""
        session = _ParsedSession(session_id="s1", project="/proj")
        # Sonnet message
        session.messages.append(_ParsedMessage(
            timestamp=None, model="claude-sonnet-4-5-20250514",
            input_tokens=1_000_000, output_tokens=0,
            cache_read=0, cache_create=0, tool_calls=0, content_type="text",
        ))
        # Opus message
        session.messages.append(_ParsedMessage(
            timestamp=None, model="claude-opus-4-5-20250514",
            input_tokens=1_000_000, output_tokens=0,
            cache_read=0, cache_create=0, tool_calls=0, content_type="text",
        ))
        # sonnet input=3.0, opus input=15.0
        assert session.cost() == pytest.approx(3.0 + 15.0)


# ── _parse_timestamp tests ──────────────────────────────────


class TestParseTimestamp:
    def test_iso_with_z_suffix(self):
        """Parses ISO 8601 with Z suffix."""
        result = _parse_timestamp("2026-03-12T10:00:00Z")
        assert result is not None
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 12
        assert result.hour == 10
        assert result.tzinfo is None  # converted to naive

    def test_fractional_seconds(self):
        """Parses ISO 8601 with fractional seconds."""
        result = _parse_timestamp("2026-03-12T10:00:00.123456Z")
        assert result is not None
        assert result.second == 0
        assert result.microsecond == 123456

    def test_with_offset(self):
        """Parses ISO 8601 with explicit timezone offset."""
        result = _parse_timestamp("2026-03-12T10:00:00+05:30")
        assert result is not None
        assert result.tzinfo is None

    def test_returns_none_on_garbage(self):
        """Returns None for unparseable strings."""
        assert _parse_timestamp("not-a-timestamp") is None

    def test_returns_none_on_empty(self):
        """Returns None for empty string."""
        assert _parse_timestamp("") is None


# ── _match_model_pricing tests ──────────────────────────────


class TestMatchModelPricing:
    def test_exact_prefix_sonnet(self):
        """Matches claude-sonnet-4-5 prefix with version suffix."""
        pricing = _match_model_pricing("claude-sonnet-4-5-20250514")
        assert pricing == MODEL_PRICING["claude-sonnet-4-5"]

    def test_exact_prefix_opus(self):
        """Matches claude-opus-4-5 prefix."""
        pricing = _match_model_pricing("claude-opus-4-5-20250514")
        assert pricing == MODEL_PRICING["claude-opus-4-5"]

    def test_exact_prefix_haiku(self):
        """Matches claude-haiku-4-5 prefix."""
        pricing = _match_model_pricing("claude-haiku-4-5-20250301")
        assert pricing == MODEL_PRICING["claude-haiku-4-5"]

    def test_opus_4_6(self):
        """Matches claude-opus-4-6 prefix."""
        pricing = _match_model_pricing("claude-opus-4-6-20260101")
        assert pricing == MODEL_PRICING["claude-opus-4-6"]

    def test_fallback_to_sonnet(self):
        """Unknown model ID falls back to sonnet-4-5 pricing."""
        pricing = _match_model_pricing("totally-unknown-model")
        assert pricing == MODEL_PRICING["claude-sonnet-4-5"]

    def test_glm_model(self):
        """Matches glm-4.7 model."""
        pricing = _match_model_pricing("glm-4.7")
        assert pricing == MODEL_PRICING["glm-4.7"]


# ── JSONL parsing tests ─────────────────────────────────────


class TestParseSessionJsonl:
    def test_basic_user_and_assistant(self, tmp_claude_dir: Path):
        """Parses a minimal session with one user + one assistant entry."""
        entries = [
            _make_user_entry(),
            _make_assistant_entry(),
        ]
        _write_session_jsonl(tmp_claude_dir, "test-project", "sess-001", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        sessions = collector._parse_all_project_sessions()

        assert len(sessions) == 1
        s = sessions[0]
        assert s.session_id == "sess-001"
        assert s.user_messages == 1
        assert len(s.messages) == 1
        assert s.input_tokens == 1000
        assert s.output_tokens == 500
        assert s.cache_read == 5000
        assert s.cache_create == 2000

    def test_user_content_as_list_of_blocks(self, tmp_claude_dir: Path):
        """Parses user entries where content is a list of blocks."""
        entries = [
            _make_user_entry(content=[
                {"type": "text", "text": "hello from block"},
                {"type": "image", "source": "..."},
            ]),
            _make_assistant_entry(),
        ]
        _write_session_jsonl(tmp_claude_dir, "proj", "sess-002", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        sessions = collector._parse_all_project_sessions()
        assert sessions[0].prompts == ["hello from block"]

    def test_cwd_sets_project_path(self, tmp_claude_dir: Path):
        """First user entry's cwd overrides the decoded project dir name."""
        entries = [
            _make_user_entry(cwd="/real/project/path"),
            _make_assistant_entry(),
        ]
        _write_session_jsonl(tmp_claude_dir, "encoded-name", "sess-003", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        sessions = collector._parse_all_project_sessions()
        assert sessions[0].project == "/real/project/path"

    def test_tool_use_counted(self, tmp_claude_dir: Path):
        """Tool use blocks in assistant content are counted."""
        entries = [
            _make_user_entry(),
            _make_assistant_entry(content=[
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {}},
                {"type": "tool_use", "id": "t2", "name": "Edit", "input": {}},
                {"type": "text", "text": "Done"},
            ]),
        ]
        _write_session_jsonl(tmp_claude_dir, "proj", "sess-004", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        sessions = collector._parse_all_project_sessions()
        assert sessions[0].tool_calls == 2
        assert sessions[0].messages[0].content_type == "tool_use"

    def test_empty_session_skipped(self, tmp_claude_dir: Path):
        """Sessions with no user messages and no assistant messages are skipped."""
        entries = [
            {"type": "system", "timestamp": "2026-03-12T10:00:00Z", "data": "init"},
        ]
        _write_session_jsonl(tmp_claude_dir, "proj", "sess-005", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        sessions = collector._parse_all_project_sessions()
        assert len(sessions) == 0

    def test_malformed_json_lines_skipped(self, tmp_claude_dir: Path):
        """Malformed JSON lines are skipped without crashing."""
        project_dir = tmp_claude_dir / "projects" / "proj"
        project_dir.mkdir(parents=True)
        jsonl_path = project_dir / "sess-006.jsonl"
        lines = [
            "NOT VALID JSON",
            json.dumps(_make_user_entry()),
            "{broken",
            json.dumps(_make_assistant_entry()),
        ]
        jsonl_path.write_text("\n".join(lines))

        collector = ClaudeCodeCollector(tmp_claude_dir)
        sessions = collector._parse_all_project_sessions()
        assert len(sessions) == 1
        assert sessions[0].user_messages == 1

    def test_multiple_sessions_across_projects(self, tmp_claude_dir: Path):
        """Collector finds sessions across multiple project directories."""
        entries_a = [_make_user_entry(), _make_assistant_entry()]
        entries_b = [_make_user_entry(cwd="/other"), _make_assistant_entry()]
        _write_session_jsonl(tmp_claude_dir, "project-a", "s1", entries_a)
        _write_session_jsonl(tmp_claude_dir, "project-b", "s2", entries_b)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        sessions = collector._parse_all_project_sessions()
        assert len(sessions) == 2
        session_ids = {s.session_id for s in sessions}
        assert session_ids == {"s1", "s2"}

    def test_timestamps_set_start_and_end(self, tmp_claude_dir: Path):
        """start_time and end_time are derived from entry timestamps."""
        entries = [
            _make_user_entry(timestamp="2026-03-12T08:00:00Z"),
            _make_assistant_entry(timestamp="2026-03-12T08:00:05Z"),
            _make_user_entry(timestamp="2026-03-12T09:30:00Z", content="second msg"),
            _make_assistant_entry(timestamp="2026-03-12T09:30:10Z"),
        ]
        _write_session_jsonl(tmp_claude_dir, "proj", "sess-ts", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        sessions = collector._parse_all_project_sessions()
        s = sessions[0]
        assert s.start_time == datetime(2026, 3, 12, 8, 0, 0)
        assert s.end_time == datetime(2026, 3, 12, 9, 30, 10)

    def test_models_used_tracked(self, tmp_claude_dir: Path):
        """models_used dict counts per-model assistant messages."""
        entries = [
            _make_user_entry(),
            _make_assistant_entry(model="claude-sonnet-4-5-20250514"),
            _make_user_entry(timestamp="2026-03-12T10:01:00Z", content="more"),
            _make_assistant_entry(
                timestamp="2026-03-12T10:01:05Z",
                model="claude-opus-4-5-20250514",
            ),
            _make_user_entry(timestamp="2026-03-12T10:02:00Z", content="again"),
            _make_assistant_entry(
                timestamp="2026-03-12T10:02:05Z",
                model="claude-sonnet-4-5-20250514",
            ),
        ]
        _write_session_jsonl(tmp_claude_dir, "proj", "sess-models", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        sessions = collector._parse_all_project_sessions()
        s = sessions[0]
        assert s.models_used["claude-sonnet-4-5-20250514"] == 2
        assert s.models_used["claude-opus-4-5-20250514"] == 1


# ── Token accounting tests ──────────────────────────────────


class TestTokenAccounting:
    def test_get_real_token_count(self, tmp_claude_dir: Path):
        """get_real_token_count sums billed tokens (input + output) only."""
        entries = [
            _make_user_entry(),
            _make_assistant_entry(
                input_tokens=1000, output_tokens=500,
                cache_read=50000, cache_create=20000,
            ),
            _make_user_entry(timestamp="2026-03-12T10:01:00Z", content="more"),
            _make_assistant_entry(
                timestamp="2026-03-12T10:01:05Z",
                input_tokens=2000, output_tokens=800,
                cache_read=30000, cache_create=10000,
            ),
        ]
        _write_session_jsonl(tmp_claude_dir, "proj", "sess-tok", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        assert collector.get_real_token_count() == (1000 + 500 + 2000 + 800)

    def test_get_cache_token_count(self, tmp_claude_dir: Path):
        """get_cache_token_count sums cache_read + cache_create only."""
        entries = [
            _make_user_entry(),
            _make_assistant_entry(
                input_tokens=1000, output_tokens=500,
                cache_read=50000, cache_create=20000,
            ),
        ]
        _write_session_jsonl(tmp_claude_dir, "proj", "sess-cache", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        assert collector.get_cache_token_count() == 50000 + 20000

    def test_tokens_not_inflated_by_cache(self, tmp_claude_dir: Path):
        """Regression: billed tokens must NOT include cache tokens."""
        entries = [
            _make_user_entry(),
            _make_assistant_entry(
                input_tokens=100, output_tokens=50,
                cache_read=1_000_000, cache_create=500_000,
            ),
        ]
        _write_session_jsonl(tmp_claude_dir, "proj", "sess-inflate", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        # Billed should be 150, NOT 1,500,150
        assert collector.get_real_token_count() == 150
        assert collector.get_cache_token_count() == 1_500_000


# ── Cost calculation tests ──────────────────────────────────


class TestCostCalculation:
    def test_get_real_cost_single_model(self, tmp_claude_dir: Path):
        """get_real_cost uses per-model pricing for all 4 components."""
        entries = [
            _make_user_entry(),
            _make_assistant_entry(
                model="claude-sonnet-4-5-20250514",
                input_tokens=1_000_000,
                output_tokens=1_000_000,
                cache_read=1_000_000,
                cache_create=1_000_000,
            ),
        ]
        _write_session_jsonl(tmp_claude_dir, "proj", "sess-cost", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        cost = collector.get_real_cost()
        # sonnet-4-5: 3.0 + 15.0 + 0.3 + 3.75
        assert cost == pytest.approx(22.05)

    def test_get_real_cost_opus_model(self, tmp_claude_dir: Path):
        """get_real_cost with opus pricing."""
        entries = [
            _make_user_entry(),
            _make_assistant_entry(
                model="claude-opus-4-5-20250514",
                input_tokens=1_000_000,
                output_tokens=1_000_000,
                cache_read=1_000_000,
                cache_create=1_000_000,
            ),
        ]
        _write_session_jsonl(tmp_claude_dir, "proj", "sess-opus", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        cost = collector.get_real_cost()
        # opus-4-5: 15.0 + 75.0 + 1.5 + 18.75
        assert cost == pytest.approx(110.25)

    def test_get_real_cost_multi_session(self, tmp_claude_dir: Path):
        """get_real_cost sums cost across multiple sessions."""
        for i, model in enumerate(["claude-sonnet-4-5-20250514", "claude-haiku-4-5-20250301"]):
            entries = [
                _make_user_entry(),
                _make_assistant_entry(
                    model=model,
                    input_tokens=1_000_000, output_tokens=0,
                    cache_read=0, cache_create=0,
                ),
            ]
            _write_session_jsonl(tmp_claude_dir, "proj", f"sess-multi-{i}", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        cost = collector.get_real_cost()
        # sonnet input=3.0 + haiku input=0.8
        assert cost == pytest.approx(3.8)


# ── Public API / collect methods ────────────────────────────


class TestCollectorPublicApi:
    def test_collect_events_from_projects(self, tmp_claude_dir: Path):
        """collect_events builds Event objects from project sessions."""
        entries = [
            _make_user_entry(content="first prompt"),
            _make_assistant_entry(),
            _make_user_entry(
                timestamp="2026-03-12T10:01:00Z", content="second prompt",
            ),
            _make_assistant_entry(timestamp="2026-03-12T10:01:05Z"),
        ]
        _write_session_jsonl(tmp_claude_dir, "proj", "sess-ev", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        events = collector.collect_events()
        assert len(events) == 2
        assert events[0].tool == ToolName.CLAUDE_CODE
        prompts = {e.data["prompt"] for e in events}
        assert prompts == {"first prompt", "second prompt"}

    def test_collect_sessions_from_projects(self, tmp_claude_dir: Path):
        """collect_sessions builds Session objects with correct fields."""
        entries = [
            _make_user_entry(content="do the thing"),
            _make_assistant_entry(
                input_tokens=500, output_tokens=200,
                cache_read=1000, cache_create=500,
                content=[
                    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}},
                    {"type": "text", "text": "ok"},
                ],
            ),
        ]
        _write_session_jsonl(tmp_claude_dir, "proj", "sess-pub", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        sessions = collector.collect_sessions()
        assert len(sessions) == 1
        s = sessions[0]
        assert s.id == "sess-pub"
        assert s.tool == ToolName.CLAUDE_CODE
        assert s.message_count == 1
        assert s.tool_call_count == 1
        assert s.total_tokens == 700  # 500 + 200, NOT including cache
        assert s.estimated_cost_usd > 0
        assert s.prompts == ["do the thing"]

    def test_get_model_usage(self, tmp_claude_dir: Path):
        """get_model_usage aggregates per-model token breakdown."""
        entries = [
            _make_user_entry(),
            _make_assistant_entry(
                model="claude-sonnet-4-5-20250514",
                input_tokens=100, output_tokens=50,
                cache_read=200, cache_create=80,
            ),
        ]
        _write_session_jsonl(tmp_claude_dir, "proj", "sess-mu", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        usage = collector.get_model_usage()
        assert "claude-sonnet-4-5-20250514" in usage
        m = usage["claude-sonnet-4-5-20250514"]
        assert m["inputTokens"] == 100
        assert m["outputTokens"] == 50
        assert m["cacheReadInputTokens"] == 200
        assert m["cacheCreationInputTokens"] == 80

    def test_get_hour_counts(self, tmp_claude_dir: Path):
        """get_hour_counts returns session distribution by hour."""
        entries = [
            _make_user_entry(timestamp="2026-03-12T14:00:00Z"),
            _make_assistant_entry(timestamp="2026-03-12T14:00:05Z"),
        ]
        _write_session_jsonl(tmp_claude_dir, "proj", "sess-hr", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        hours = collector.get_hour_counts()
        assert hours.get("14") == 1

    def test_is_available(self, tmp_claude_dir: Path):
        """is_available returns True when the dir exists."""
        collector = ClaudeCodeCollector(tmp_claude_dir)
        assert collector.is_available()

    def test_is_not_available(self):
        """is_available returns False for nonexistent dir."""
        collector = ClaudeCodeCollector(Path("/nonexistent/path"))
        assert not collector.is_available()

    def test_tool_name(self, tmp_claude_dir: Path):
        """tool_name returns CLAUDE_CODE."""
        collector = ClaudeCodeCollector(tmp_claude_dir)
        assert collector.tool_name == ToolName.CLAUDE_CODE

    def test_no_projects_dir_returns_empty(self, tmp_claude_dir: Path):
        """When projects/ doesn't exist, session-based methods return empty."""
        collector = ClaudeCodeCollector(tmp_claude_dir)
        assert collector._parse_all_project_sessions() == []
        assert collector.get_real_token_count() == 0
        assert collector.get_cache_token_count() == 0
        assert collector.get_real_cost() == 0.0

    def test_session_cache_reuse(self, tmp_claude_dir: Path):
        """Parsed sessions are cached and reused within TTL."""
        entries = [_make_user_entry(), _make_assistant_entry()]
        _write_session_jsonl(tmp_claude_dir, "proj", "sess-cache-test", entries)

        collector = ClaudeCodeCollector(tmp_claude_dir)
        first = collector._parse_all_project_sessions()
        second = collector._parse_all_project_sessions()
        # Same list object (cached)
        assert first is second
