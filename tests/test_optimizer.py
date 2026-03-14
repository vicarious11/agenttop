"""Tests for the optimizer module."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

from agenttop.models import Session, ToolName
from agenttop.web.optimizer import (
    AIUsageOptimizer,
    _build_cost_forensics,
    _extract_json,
)


def _make_session(**kwargs: Any) -> Session:
    """Helper to create a Session with defaults."""
    defaults: dict[str, Any] = {
        "id": "test-1",
        "tool": ToolName.CLAUDE_CODE,
        "start_time": datetime(2026, 3, 1, 10, 0),
        "message_count": 10,
        "estimated_cost_usd": 0.50,
    }
    defaults.update(kwargs)
    return Session(**defaults)


def _make_optimizer() -> AIUsageOptimizer:
    """Create an AIUsageOptimizer without loading config."""
    opt = object.__new__(AIUsageOptimizer)
    opt._config = MagicMock()
    opt._claude = None
    return opt


class TestMergeResults:
    """Tests for AIUsageOptimizer._merge_results."""

    def test_llm_error_returns_partial_with_python_metrics(self) -> None:
        opt = _make_optimizer()
        profile = {
            "anti_patterns": [{"pattern": "test", "severity": "low"}],
            "cost_forensics": {"total_cost": 10.0},
            "prompt_analysis": {},
            "context_engineering": {},
            "session_details": [],
            "total_tokens": 1000,
            "total_cost": 10.0,
            "session_count": 5,
        }
        llm_result = {"error": "LLM failed", "source": "error"}
        result = opt._merge_results(profile, llm_result)

        assert result["source"] == "partial"
        assert result["error"] == "LLM failed"
        # Python metrics still present
        assert len(result["anti_patterns"]) == 1
        assert result["cost_forensics"]["total_cost"] == 10.0
        # LLM fields have defaults
        assert result["score"] == 0
        assert result["grades"] == {}
        assert result["recommendations"] == []

    def test_llm_success_merges_both(self) -> None:
        opt = _make_optimizer()
        profile = {
            "anti_patterns": [],
            "cost_forensics": {},
            "prompt_analysis": {},
            "context_engineering": {},
            "session_details": [],
            "total_tokens": 500,
            "total_cost": 5.0,
            "session_count": 2,
        }
        llm_result = {
            "source": "llm",
            "score": 85,
            "developer_profile": {"title": "Power User"},
            "grades": {"cache_efficiency": {"grade": "A"}},
            "recommendations": [{"title": "Use caching"}],
            "missing_features": [],
            "project_insights": [],
            "workflow": {"current": "manual", "future": "automated"},
        }
        result = opt._merge_results(profile, llm_result)

        assert result["source"] == "llm"
        assert result["score"] == 85
        assert result["developer_profile"]["title"] == "Power User"
        assert result["anti_patterns"] == []


class TestGetLlmAnalysis:
    """Tests for AIUsageOptimizer._get_llm_analysis."""

    def test_invalid_json_returns_error(self) -> None:
        opt = _make_optimizer()
        profile: dict[str, Any] = {"active_tools": [{"tool": "claude_code"}]}

        with patch(
            "agenttop.web.optimizer.get_completion",
            return_value="not json at all",
        ):
            result = opt._get_llm_analysis(profile)

        assert result["source"] == "error"
        assert "invalid JSON" in result["error"]

    def test_error_response_propagated(self) -> None:
        opt = _make_optimizer()
        profile: dict[str, Any] = {"active_tools": []}

        with patch(
            "agenttop.web.optimizer.get_completion",
            return_value="[error] API key invalid.",
        ):
            result = opt._get_llm_analysis(profile)

        assert result["source"] == "error"
        assert "[error]" in result["error"]


class TestCostForensics:
    """Tests for _build_cost_forensics."""

    def test_no_waste_below_threshold(self) -> None:
        sessions = [_make_session(message_count=30, estimated_cost_usd=1.0)]
        profile = {"context_engineering": {"total_cost": 1.0}}
        result = _build_cost_forensics(profile, sessions, {})
        assert result["estimated_waste"] == 0.0

    def test_waste_detected_for_marathon_sessions(self) -> None:
        sessions = [_make_session(message_count=100, estimated_cost_usd=2.0)]
        profile = {"context_engineering": {"total_cost": 2.0}}
        result = _build_cost_forensics(profile, sessions, {})
        assert result["estimated_waste"] > 0

    def test_empty_sessions(self) -> None:
        result = _build_cost_forensics({}, [], {})
        assert result["total_cost"] == 0
        assert result["estimated_waste"] == 0.0


class TestExtractJson:
    """Tests for _extract_json."""

    def test_raw_json_object(self) -> None:
        result = _extract_json('{"score": 80, "source": "llm"}')
        assert result == {"score": 80, "source": "llm"}

    def test_fenced_json_block(self) -> None:
        text = '```json\n{"score": 90}\n```'
        result = _extract_json(text)
        assert result == {"score": 90}

    def test_fenced_no_language_tag(self) -> None:
        text = '```\n{"key": "value"}\n```'
        result = _extract_json(text)
        assert result == {"key": "value"}

    def test_json_embedded_in_prose(self) -> None:
        text = 'Here is the analysis: {"score": 75, "recommendations": []} Great work!'
        result = _extract_json(text)
        assert result == {"score": 75, "recommendations": []}

    def test_malformed_json_returns_none(self) -> None:
        result = _extract_json("not json at all")
        assert result is None

    def test_malformed_fenced_block_returns_none(self) -> None:
        result = _extract_json("```json\n{broken\n```")
        assert result is None

    def test_empty_string_returns_none(self) -> None:
        result = _extract_json("")
        assert result is None

    def test_nested_json_object(self) -> None:
        text = '{"grades": {"cache": {"grade": "A"}}, "score": 85}'
        result = _extract_json(text)
        assert result is not None
        assert result["score"] == 85
        assert result["grades"]["cache"]["grade"] == "A"
