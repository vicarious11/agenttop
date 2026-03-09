"""Tests for the SQLite event store."""

import tempfile
from datetime import datetime
from pathlib import Path

from agenttop.db import EventStore
from agenttop.models import Event, Session, Suggestion, ToolName


def make_store() -> EventStore:
    tmp = tempfile.mktemp(suffix=".db")
    return EventStore(db_path=Path(tmp))


def test_insert_and_get_event():
    store = make_store()
    ev = Event(
        tool=ToolName.CLAUDE_CODE,
        event_type="message",
        timestamp=datetime(2026, 3, 1, 10, 0, 0),
        session_id="s1",
        project="/test",
        data={"prompt": "hello"},
        token_count=100,
        cost_usd=0.001,
    )
    eid = store.insert_event(ev)
    assert eid > 0

    events = store.get_events(tool=ToolName.CLAUDE_CODE)
    assert len(events) == 1
    assert events[0].event_type == "message"
    assert events[0].data["prompt"] == "hello"
    store.close()


def test_upsert_session():
    store = make_store()
    s = Session(
        id="test-session-1",
        tool=ToolName.CURSOR,
        project="/my-project",
        start_time=datetime(2026, 3, 1, 9, 0),
        end_time=datetime(2026, 3, 1, 10, 0),
        message_count=15,
        tool_call_count=5,
        total_tokens=5000,
        estimated_cost_usd=0.05,
        prompts=["fix the bug", "add tests"],
    )
    store.upsert_session(s)

    sessions = store.get_sessions(tool=ToolName.CURSOR)
    assert len(sessions) == 1
    assert sessions[0].message_count == 15
    assert sessions[0].prompts == ["fix the bug", "add tests"]

    # Upsert with updated values
    s.message_count = 20
    store.upsert_session(s)
    sessions = store.get_sessions(tool=ToolName.CURSOR)
    assert len(sessions) == 1
    assert sessions[0].message_count == 20
    store.close()


def test_suggestions():
    store = make_store()
    sug = Suggestion(
        tool=ToolName.CLAUDE_CODE,
        category="memory",
        title="Add CLAUDE.md",
        description="No project memory found.",
        estimated_savings="~2000 tokens/session",
        priority=2,
    )
    sid = store.insert_suggestion(sug)
    assert sid > 0

    suggestions = store.get_suggestions()
    assert len(suggestions) == 1
    assert suggestions[0].title == "Add CLAUDE.md"

    store.dismiss_suggestion(sid)
    suggestions = store.get_suggestions()
    assert len(suggestions) == 0

    suggestions = store.get_suggestions(include_dismissed=True)
    assert len(suggestions) == 1
    store.close()


def test_event_filtering():
    store = make_store()
    for i in range(5):
        store.insert_event(
            Event(
                tool=ToolName.CLAUDE_CODE if i < 3 else ToolName.CURSOR,
                event_type="message",
                timestamp=datetime(2026, 3, 1, 10, i),
            )
        )

    assert len(store.get_events(tool=ToolName.CLAUDE_CODE)) == 3
    assert len(store.get_events(tool=ToolName.CURSOR)) == 2
    assert len(store.get_events(since=datetime(2026, 3, 1, 10, 2))) == 3
    store.close()
