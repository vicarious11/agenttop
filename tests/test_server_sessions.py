"""Tests for session detail and selective analysis endpoints."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agenttop.models import Session, ToolName
from agenttop.web.server import app

client = TestClient(app)


def _mock_session(
    sid: str = "test-123",
    tool: str = "claude_code",
    project: str = "/tmp/proj",
    tokens: int = 1000,
    cost: float = 0.5,
    prompts: list[str] | None = None,
) -> Session:
    return Session(
        id=sid,
        tool=ToolName.CLAUDE_CODE if tool == "claude_code" else ToolName.CURSOR,
        project=project,
        start_time=datetime(2026, 1, 1, 10, 0),
        end_time=datetime(2026, 1, 1, 11, 0),
        message_count=10,
        tool_call_count=5,
        total_tokens=tokens,
        estimated_cost_usd=cost,
        prompts=prompts or ["fix the bug", "add tests"],
    )


class TestSessionDetail:
    def test_session_found(self):
        mock_collector = MagicMock()
        mock_collector.is_available.return_value = True
        mock_collector.collect_sessions.return_value = [_mock_session()]

        with patch("agenttop.web.server._collectors", [("Claude Code", mock_collector)]), \
             patch("agenttop.web.server._config", MagicMock()):
            resp = client.get("/api/sessions/test-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "test-123"
        assert "prompts" in data
        assert data["prompts"] == ["fix the bug", "add tests"]

    def test_session_not_found(self):
        mock_collector = MagicMock()
        mock_collector.is_available.return_value = True
        mock_collector.collect_sessions.return_value = [_mock_session()]

        with patch("agenttop.web.server._collectors", [("Claude Code", mock_collector)]), \
             patch("agenttop.web.server._config", MagicMock()):
            resp = client.get("/api/sessions/nonexistent")
        assert resp.status_code == 404


class TestAnalyzeSessions:
    def test_empty_ids_rejected(self):
        with patch("agenttop.web.server._config", MagicMock()):
            resp = client.post("/api/analyze-sessions", json={"session_ids": []})
        assert resp.status_code == 400

    def test_no_matching_sessions(self):
        mock_collector = MagicMock()
        mock_collector.is_available.return_value = True
        mock_collector.collect_sessions.return_value = [_mock_session("other-id")]
        mock_collector.get_feature_config.return_value = {}

        with patch("agenttop.web.server._collectors", [("Claude Code", mock_collector)]), \
             patch("agenttop.web.server._config", MagicMock()):
            resp = client.post("/api/analyze-sessions", json={"session_ids": ["nonexistent"]})
        assert resp.status_code == 404

    def test_analyze_selected_sessions(self):
        sessions = [
            _mock_session("s1", prompts=["build auth"]),
            _mock_session("s2", prompts=["fix login bug"]),
        ]
        mock_collector = MagicMock()
        mock_collector.is_available.return_value = True
        mock_collector.collect_sessions.return_value = sessions
        mock_collector.tool_name = MagicMock(value="claude_code")
        mock_collector.get_feature_config.return_value = {}

        mock_claude = MagicMock()
        mock_claude.is_available.return_value = True
        mock_claude.get_model_usage.return_value = {}

        with patch("agenttop.web.server._collectors", [("Claude Code", mock_collector)]), \
             patch("agenttop.web.server._config", MagicMock()), \
             patch("agenttop.web.server._claude", mock_claude), \
             patch("agenttop.web.optimizer.AIUsageOptimizer.analyze") as mock_analyze:
            mock_analyze.return_value = {"score": 75, "source": "llm"}
            resp = client.post(
                "/api/analyze-sessions",
                json={"session_ids": ["s1", "s2"]},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["score"] == 75
