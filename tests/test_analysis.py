"""Tests for the analysis engine."""

from datetime import datetime

from agenttop.analysis.workflow import analyze_workflow_local
from agenttop.models import IntentCategory, Session, ToolName
from agenttop.tui.analysis import classify_intent_local


def test_classify_intent_debugging():
    assert classify_intent_local("fix the login bug") == IntentCategory.DEBUGGING
    assert classify_intent_local("this error keeps happening") == IntentCategory.DEBUGGING


def test_classify_intent_greenfield():
    assert classify_intent_local("create a new API endpoint") == IntentCategory.GREENFIELD
    assert classify_intent_local("implement user authentication") == IntentCategory.GREENFIELD


def test_classify_intent_exploration():
    assert classify_intent_local("how does the router work?") == IntentCategory.EXPLORATION
    assert classify_intent_local("explain this function") == IntentCategory.EXPLORATION


def test_classify_intent_refactoring():
    assert classify_intent_local("refactor the database module") == IntentCategory.REFACTORING


def test_classify_intent_devops():
    assert classify_intent_local("set up the docker deployment") == IntentCategory.DEVOPS


def test_classify_intent_unknown():
    assert classify_intent_local("xyz") == IntentCategory.UNKNOWN


def test_workflow_analysis_empty():
    insights = analyze_workflow_local([])
    assert len(insights) > 0
    assert "No sessions" in insights[0]


def test_workflow_analysis_long_sessions():
    sessions = [
        Session(
            id=f"s{i}",
            tool=ToolName.CLAUDE_CODE,
            start_time=datetime(2026, 3, 1, 10, 0),
            message_count=150,
        )
        for i in range(3)
    ]
    insights = analyze_workflow_local(sessions)
    assert any("100+" in i for i in insights)


def test_workflow_analysis_repeated_projects():
    sessions = [
        Session(
            id=f"s{i}",
            tool=ToolName.CLAUDE_CODE,
            project="/my/project",
            start_time=datetime(2026, 3, 1, 10, 0),
        )
        for i in range(10)
    ]
    insights = analyze_workflow_local(sessions)
    assert any("project" in i.lower() for i in insights)
