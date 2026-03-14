"""Comprehensive tests for the Cursor collector."""

import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agenttop.collectors.cursor import (
    CursorCollector,
    _COST_PER_TOKEN,
    _TOKENS_CHAT_ONLY,
    _TOKENS_COMPOSER,
    _TOKENS_TAB,
    _cost_for_tokens,
    _estimate_tokens,
    _extract_project,
)
from agenttop.models import ToolName


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_dir: Path) -> Path:
    """Create the Cursor SQLite DB with all required tables, returning the db path."""
    db_dir = tmp_dir / "ai-tracking"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "ai-code-tracking.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE ai_code_hashes ("
        "  hash TEXT, model TEXT, source TEXT, fileName TEXT,"
        "  conversationId TEXT, createdAt INTEGER"
        ")"
    )
    conn.execute(
        "CREATE TABLE conversation_summaries ("
        "  conversationId TEXT, title TEXT, tldr TEXT,"
        "  model TEXT, mode TEXT, updatedAt INTEGER"
        ")"
    )
    conn.execute(
        "CREATE TABLE scored_commits ("
        "  scoredAt INTEGER, tabLinesAdded INTEGER,"
        "  composerLinesAdded INTEGER, humanLinesAdded INTEGER"
        ")"
    )
    conn.commit()
    conn.close()
    return db_path


def _insert_code_hash(
    db_path: Path,
    *,
    hash_val: str = "abc",
    model: str = "gpt-4o",
    source: str = "composer",
    file_name: str = "/Users/user/repo/myproject/src/main.py",
    conversation_id: str = "conv-1",
    created_at: int | None = None,
) -> None:
    created_at = created_at if created_at is not None else int(datetime.now().timestamp() * 1000)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO ai_code_hashes VALUES (?, ?, ?, ?, ?, ?)",
        (hash_val, model, source, file_name, conversation_id, created_at),
    )
    conn.commit()
    conn.close()


def _insert_conversation(
    db_path: Path,
    *,
    conversation_id: str = "conv-1",
    title: str = "Fix bug",
    tldr: str = "Fixed the login bug",
    model: str = "gpt-4o",
    mode: str = "chat",
    updated_at: int | None = None,
) -> None:
    updated_at = updated_at or int(datetime.now().timestamp() * 1000)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO conversation_summaries VALUES (?, ?, ?, ?, ?, ?)",
        (conversation_id, title, tldr, model, mode, updated_at),
    )
    conn.commit()
    conn.close()


def _insert_scored_commit(
    db_path: Path,
    *,
    scored_at: int | None = None,
    tab_lines: int = 10,
    composer_lines: int = 20,
    human_lines: int = 50,
) -> None:
    scored_at = scored_at or int(datetime.now().timestamp() * 1000)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO scored_commits VALUES (?, ?, ?, ?)",
        (scored_at, tab_lines, composer_lines, human_lines),
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def cursor_env():
    """Create a temp directory with a valid Cursor DB and return (tmp_dir, db_path)."""
    tmp_dir = Path(tempfile.mkdtemp())
    db_path = _make_db(tmp_dir)
    return tmp_dir, db_path


# ---------------------------------------------------------------------------
# _estimate_tokens
# ---------------------------------------------------------------------------

def test_estimate_tokens_composer():
    assert _estimate_tokens("composer") == _TOKENS_COMPOSER


def test_estimate_tokens_tab():
    assert _estimate_tokens("tab") == _TOKENS_TAB


def test_estimate_tokens_unknown_defaults_to_composer():
    assert _estimate_tokens("unknown_source") == _TOKENS_COMPOSER
    assert _estimate_tokens("") == _TOKENS_COMPOSER


# ---------------------------------------------------------------------------
# _cost_for_tokens
# ---------------------------------------------------------------------------

def test_cost_for_tokens_known_model():
    tokens = 1000
    cost = _cost_for_tokens(tokens, "gpt-4o")
    assert cost == pytest.approx(tokens * _COST_PER_TOKEN["gpt-4o"])


def test_cost_for_tokens_unknown_model_uses_default():
    tokens = 500
    cost = _cost_for_tokens(tokens, "some-future-model")
    assert cost == pytest.approx(tokens * _COST_PER_TOKEN["default"])


def test_cost_for_tokens_zero_tokens():
    assert _cost_for_tokens(0, "gpt-4o") == 0.0


def test_cost_for_tokens_opus_model():
    tokens = 100
    cost = _cost_for_tokens(tokens, "claude-4.6-opus-high-thinking")
    assert cost == pytest.approx(tokens * _COST_PER_TOKEN["claude-4.6-opus-high-thinking"])


# ---------------------------------------------------------------------------
# _extract_project
# ---------------------------------------------------------------------------

def test_extract_project_standard_path():
    home = str(Path.home())
    result = _extract_project(f"{home}/repo/myproject/src/main.py")
    assert result == "myproject"


def test_extract_project_skips_container_dirs():
    home = str(Path.home())
    result = _extract_project(f"{home}/Desktop/projects/coolapp/index.js")
    assert result == "coolapp"


def test_extract_project_empty_string():
    assert _extract_project("") is None


def test_extract_project_relative_path():
    assert _extract_project("relative/path/file.py") is None


def test_extract_project_file_at_root_of_home():
    """A bare file directly in a container dir should return None (it's just a filename)."""
    home = str(Path.home())
    result = _extract_project(f"{home}/Desktop/file.txt")
    # "file.txt" has a dot and is the last part => None
    assert result is None


def test_extract_project_none_input():
    assert _extract_project(None) is None


def test_extract_project_non_container_first_dir():
    home = str(Path.home())
    result = _extract_project(f"{home}/myproject/src/main.py")
    assert result == "myproject"


# ---------------------------------------------------------------------------
# CursorCollector — is_available
# ---------------------------------------------------------------------------

def test_is_available_true(cursor_env):
    tmp_dir, _ = cursor_env
    collector = CursorCollector(cursor_dir=tmp_dir)
    assert collector.is_available()


def test_is_available_false():
    collector = CursorCollector(cursor_dir=Path("/nonexistent/path"))
    assert not collector.is_available()


def test_tool_name():
    collector = CursorCollector(cursor_dir=Path("/tmp"))
    assert collector.tool_name == ToolName.CURSOR


# ---------------------------------------------------------------------------
# collect_events
# ---------------------------------------------------------------------------

def test_collect_events_basic(cursor_env):
    tmp_dir, db_path = cursor_env
    now_ms = int(datetime.now().timestamp() * 1000)
    _insert_code_hash(db_path, source="composer", model="gpt-4o", created_at=now_ms)

    collector = CursorCollector(cursor_dir=tmp_dir)
    events = collector.collect_events()

    assert len(events) == 1
    event = events[0]
    assert event.tool == ToolName.CURSOR
    assert event.event_type == "ai_code"
    assert event.token_count == _TOKENS_COMPOSER
    assert event.cost_usd == pytest.approx(_cost_for_tokens(_TOKENS_COMPOSER, "gpt-4o"))
    assert event.data["source"] == "composer"
    assert event.data["model"] == "gpt-4o"


def test_collect_events_skips_zero_timestamp(cursor_env):
    tmp_dir, db_path = cursor_env
    _insert_code_hash(db_path, created_at=0)

    collector = CursorCollector(cursor_dir=tmp_dir)
    events = collector.collect_events()
    assert len(events) == 0


def test_collect_events_empty_db(cursor_env):
    tmp_dir, _ = cursor_env
    collector = CursorCollector(cursor_dir=tmp_dir)
    events = collector.collect_events()
    assert events == []


# ---------------------------------------------------------------------------
# collect_sessions — merging logic
# ---------------------------------------------------------------------------

def test_collect_sessions_with_code_and_conversation(cursor_env):
    """Session merges code hashes with conversation metadata."""
    tmp_dir, db_path = cursor_env
    now_ms = int(datetime.now().timestamp() * 1000)

    _insert_code_hash(db_path, conversation_id="c1", source="composer", created_at=now_ms)
    _insert_code_hash(db_path, hash_val="def", conversation_id="c1", source="tab",
                      created_at=now_ms + 5000)
    _insert_conversation(db_path, conversation_id="c1", title="Refactor auth",
                         tldr="Moved auth to middleware", updated_at=now_ms)

    collector = CursorCollector(cursor_dir=tmp_dir)
    sessions = collector.collect_sessions()

    assert len(sessions) == 1
    session = sessions[0]
    assert session.id == "c1"
    assert session.tool == ToolName.CURSOR
    assert session.message_count == 2
    assert session.total_tokens == _TOKENS_COMPOSER + _TOKENS_TAB
    assert "Refactor auth" in session.prompts
    assert "Moved auth to middleware" in session.prompts


def test_collect_sessions_chat_only_conversation(cursor_env):
    """Conversation with no code hashes gets chat-only token estimate."""
    tmp_dir, db_path = cursor_env
    now_ms = int(datetime.now().timestamp() * 1000)

    _insert_conversation(db_path, conversation_id="chat-only", title="Explain decorators",
                         tldr="Python decorators overview", model="gpt-4o",
                         updated_at=now_ms)

    collector = CursorCollector(cursor_dir=tmp_dir)
    sessions = collector.collect_sessions()

    assert len(sessions) == 1
    session = sessions[0]
    assert session.id == "chat-only"
    assert session.total_tokens == _TOKENS_CHAT_ONLY
    assert session.estimated_cost_usd == pytest.approx(
        _cost_for_tokens(_TOKENS_CHAT_ONLY, "gpt-4o")
    )
    assert session.message_count == 1


def test_collect_sessions_code_without_conversation(cursor_env):
    """Code hashes with no matching conversation summary still produce a session."""
    tmp_dir, db_path = cursor_env
    now_ms = int(datetime.now().timestamp() * 1000)

    _insert_code_hash(db_path, conversation_id="orphan", source="tab", created_at=now_ms)

    collector = CursorCollector(cursor_dir=tmp_dir)
    sessions = collector.collect_sessions()

    assert len(sessions) == 1
    session = sessions[0]
    assert session.id == "orphan"
    assert session.total_tokens == _TOKENS_TAB
    assert session.prompts == []


def test_collect_sessions_multiple_conversations(cursor_env):
    """Multiple conversations produce separate sessions."""
    tmp_dir, db_path = cursor_env
    now_ms = int(datetime.now().timestamp() * 1000)

    _insert_code_hash(db_path, conversation_id="c1", created_at=now_ms)
    _insert_code_hash(db_path, hash_val="xyz", conversation_id="c2", created_at=now_ms + 1000)
    _insert_conversation(db_path, conversation_id="c1", title="Session 1", updated_at=now_ms)
    _insert_conversation(db_path, conversation_id="c2", title="Session 2",
                         updated_at=now_ms + 1000)

    collector = CursorCollector(cursor_dir=tmp_dir)
    sessions = collector.collect_sessions()

    assert len(sessions) == 2
    session_ids = {s.id for s in sessions}
    assert session_ids == {"c1", "c2"}


def test_collect_sessions_project_extraction(cursor_env):
    """Session picks the most common project from file paths."""
    tmp_dir, db_path = cursor_env
    home = str(Path.home())
    now_ms = int(datetime.now().timestamp() * 1000)

    # Two files in project-a, one in project-b => project-a wins
    _insert_code_hash(db_path, hash_val="h1", conversation_id="c1",
                      file_name=f"{home}/repo/project-a/a.py", created_at=now_ms)
    _insert_code_hash(db_path, hash_val="h2", conversation_id="c1",
                      file_name=f"{home}/repo/project-a/b.py", created_at=now_ms + 100)
    _insert_code_hash(db_path, hash_val="h3", conversation_id="c1",
                      file_name=f"{home}/repo/project-b/c.py", created_at=now_ms + 200)

    collector = CursorCollector(cursor_dir=tmp_dir)
    sessions = collector.collect_sessions()

    assert len(sessions) == 1
    assert sessions[0].project == "project-a"


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

def test_get_stats_empty_db(cursor_env):
    tmp_dir, _ = cursor_env
    collector = CursorCollector(cursor_dir=tmp_dir)
    stats = collector.get_stats()

    assert stats.tool == ToolName.CURSOR
    assert stats.sessions_today == 0
    assert stats.tokens_today == 0
    assert stats.status == "idle"


def test_get_stats_with_data(cursor_env):
    tmp_dir, db_path = cursor_env
    now_ms = int(datetime.now().timestamp() * 1000)

    _insert_code_hash(db_path, hash_val="h1", conversation_id="c1", source="composer",
                      model="gpt-4o", created_at=now_ms)
    _insert_code_hash(db_path, hash_val="h2", conversation_id="c1", source="tab",
                      model="gpt-4o", created_at=now_ms + 1000)
    _insert_conversation(db_path, conversation_id="c1", updated_at=now_ms)

    collector = CursorCollector(cursor_dir=tmp_dir)
    stats = collector.get_stats()

    assert stats.sessions_today == 1  # one unique conversation
    assert stats.messages_today == 2  # two code hashes
    assert stats.tokens_today == _TOKENS_COMPOSER + _TOKENS_TAB
    expected_cost = (
        _cost_for_tokens(_TOKENS_COMPOSER, "gpt-4o")
        + _cost_for_tokens(_TOKENS_TAB, "gpt-4o")
    )
    assert stats.estimated_cost_today == pytest.approx(expected_cost)
    assert stats.status == "active"
    assert len(stats.hourly_tokens) == 24


def test_get_stats_chat_only_adds_tokens(cursor_env):
    """Chat-only conversations (in summaries but not in code hashes) add tokens."""
    tmp_dir, db_path = cursor_env
    now_ms = int(datetime.now().timestamp() * 1000)

    _insert_conversation(db_path, conversation_id="chat1", title="Question",
                         updated_at=now_ms)

    collector = CursorCollector(cursor_dir=tmp_dir)
    stats = collector.get_stats()

    assert stats.sessions_today == 1
    assert stats.tokens_today == _TOKENS_CHAT_ONLY
    assert stats.estimated_cost_today == pytest.approx(
        _cost_for_tokens(_TOKENS_CHAT_ONLY, "default")
    )


def test_get_stats_days_filter(cursor_env):
    """The days parameter filters out old data."""
    tmp_dir, db_path = cursor_env
    old_ms = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)
    recent_ms = int(datetime.now().timestamp() * 1000)

    _insert_code_hash(db_path, hash_val="old", conversation_id="c-old", created_at=old_ms)
    _insert_code_hash(db_path, hash_val="new", conversation_id="c-new", created_at=recent_ms)

    collector = CursorCollector(cursor_dir=tmp_dir)

    stats_all = collector.get_stats(days=0)
    assert stats_all.messages_today == 2

    stats_recent = collector.get_stats(days=7)
    assert stats_recent.messages_today == 1


def test_get_stats_hourly_tokens(cursor_env):
    """Hourly token buckets are populated based on code hash timestamps."""
    tmp_dir, db_path = cursor_env
    # Create a timestamp at hour 14 (2 PM)
    now = datetime.now().replace(hour=14, minute=0, second=0, microsecond=0)
    ts_ms = int(now.timestamp() * 1000)

    _insert_code_hash(db_path, source="composer", created_at=ts_ms)

    collector = CursorCollector(cursor_dir=tmp_dir)
    stats = collector.get_stats()

    assert stats.hourly_tokens[14] == _TOKENS_COMPOSER


# ---------------------------------------------------------------------------
# get_ai_vs_human_ratio
# ---------------------------------------------------------------------------

def test_ai_vs_human_ratio_basic(cursor_env):
    tmp_dir, db_path = cursor_env
    _insert_scored_commit(db_path, tab_lines=10, composer_lines=20, human_lines=70)

    collector = CursorCollector(cursor_dir=tmp_dir)
    ratio = collector.get_ai_vs_human_ratio()

    assert ratio["ai_lines"] == 30
    assert ratio["human_lines"] == 70
    assert ratio["ai_percentage"] == pytest.approx(30.0)


def test_ai_vs_human_ratio_no_commits(cursor_env):
    tmp_dir, _ = cursor_env
    collector = CursorCollector(cursor_dir=tmp_dir)
    ratio = collector.get_ai_vs_human_ratio()

    assert ratio["ai_lines"] == 0
    assert ratio["human_lines"] == 0
    assert ratio["ai_percentage"] == 0


def test_ai_vs_human_ratio_multiple_commits(cursor_env):
    tmp_dir, db_path = cursor_env
    now_ms = int(datetime.now().timestamp() * 1000)

    _insert_scored_commit(db_path, scored_at=now_ms, tab_lines=5, composer_lines=15,
                          human_lines=30)
    _insert_scored_commit(db_path, scored_at=now_ms + 1000, tab_lines=10, composer_lines=10,
                          human_lines=20)

    collector = CursorCollector(cursor_dir=tmp_dir)
    ratio = collector.get_ai_vs_human_ratio()

    assert ratio["ai_lines"] == 40  # 5+15+10+10
    assert ratio["human_lines"] == 50  # 30+20
    assert ratio["ai_percentage"] == pytest.approx(40 / 90 * 100)


def test_ai_vs_human_ratio_null_values(cursor_env):
    """Null values in scored_commits should be treated as 0."""
    tmp_dir, db_path = cursor_env
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO scored_commits VALUES (?, NULL, NULL, ?)",
        (int(datetime.now().timestamp() * 1000), 100),
    )
    conn.commit()
    conn.close()

    collector = CursorCollector(cursor_dir=tmp_dir)
    ratio = collector.get_ai_vs_human_ratio()

    assert ratio["ai_lines"] == 0
    assert ratio["human_lines"] == 100
    assert ratio["ai_percentage"] == 0.0


# ---------------------------------------------------------------------------
# Edge cases / error handling
# ---------------------------------------------------------------------------

def test_query_returns_empty_on_missing_db():
    """Querying a non-existent DB returns empty list, no exception."""
    collector = CursorCollector(cursor_dir=Path("/nonexistent"))
    result = collector._query("SELECT 1")
    assert result == []


def test_collect_sessions_empty_db(cursor_env):
    tmp_dir, _ = cursor_env
    collector = CursorCollector(cursor_dir=tmp_dir)
    sessions = collector.collect_sessions()
    assert sessions == []
