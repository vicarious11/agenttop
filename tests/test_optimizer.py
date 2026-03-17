# ruff: noqa: E501
"""Tests for the optimizer module — Map-Reduce-Generate architecture."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agenttop.models import Session, ToolName
from agenttop.web.optimizer import (
    AIUsageOptimizer,
    _build_cost_forensics,
    _compute_deterministic_score,
    _load_session_cache,
    _save_session_cache,
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


# ---------------------------------------------------------------------------
# Session Cache Tests
# ---------------------------------------------------------------------------


class TestSessionCache:
    """Tests for session cache load/save."""

    def test_load_missing_file(self, tmp_path: Path) -> None:
        with patch(
            "agenttop.web.optimizer._SESSION_CACHE_PATH",
            tmp_path / "nonexistent.json",
        ):
            assert _load_session_cache() == {}

    def test_load_invalid_json(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "session_cache.json"
        cache_path.write_text("not json")
        with patch(
            "agenttop.web.optimizer._SESSION_CACHE_PATH",
            cache_path,
        ):
            assert _load_session_cache() == {}

    def test_roundtrip(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "session_cache.json"
        data = {"sess-1": {"intent": "debugging", "had_spiral": False}}
        with patch(
            "agenttop.web.optimizer._SESSION_CACHE_PATH",
            cache_path,
        ):
            _save_session_cache(data)
            loaded = _load_session_cache()
        assert loaded == data

    def test_save_creates_parent_dir(self, tmp_path: Path) -> None:
        cache_path = tmp_path / "subdir" / "session_cache.json"
        with patch(
            "agenttop.web.optimizer._SESSION_CACHE_PATH",
            cache_path,
        ):
            _save_session_cache({"test": {"a": 1}})
        assert cache_path.exists()


# ---------------------------------------------------------------------------
# Deterministic Score Tests
# ---------------------------------------------------------------------------


class TestDeterministicScore:
    """Tests for _compute_deterministic_score."""

    def test_with_session_analyses(self) -> None:
        """Score uses LLM session classifications when available."""
        profile: dict[str, Any] = {
            "all_sessions": [],
            "session_count": 10,
            "prompt_analysis": {},
            "cost_forensics": {"waste_pct": 10, "total_cost": 100, "estimated_waste": 10},
            "model_usage": {"overall_cache_hit_rate": 80.0},
            "feature_detection": {},
        }
        analyses = {
            "s1": {"had_spiral": False, "wasted_effort": ""},
            "s2": {"had_spiral": False, "wasted_effort": ""},
            "s3": {"had_spiral": True, "wasted_effort": "unclear prompt"},
        }
        result = _compute_deterministic_score(profile, analyses)

        assert result["score"] > 0
        assert "session_hygiene" in result["grades"]
        assert "prompt_quality" in result["grades"]
        # 2/3 spiral-free = ~13.3/20
        assert result["breakdown"]["session_hygiene"] == pytest.approx(13.3, abs=0.1)
        # 2/3 no wasted effort = ~13.3/20
        assert result["breakdown"]["prompt_quality"] == pytest.approx(13.3, abs=0.1)

    def test_without_session_analyses_falls_back(self) -> None:
        """Score falls back to heuristic when no session analyses."""
        sessions = [_make_session(message_count=30) for _ in range(5)]
        profile: dict[str, Any] = {
            "all_sessions": sessions,
            "session_count": 5,
            "prompt_analysis": {"specificity_score": 50, "correction_spirals": []},
            "cost_forensics": {"waste_pct": 0, "total_cost": 10, "estimated_waste": 0},
            "model_usage": {"overall_cache_hit_rate": 0},
            "feature_detection": {},
        }
        result = _compute_deterministic_score(profile, None)

        assert result["score"] >= 0
        # All sessions under 50 messages = 20/20 hygiene
        assert result["breakdown"]["session_hygiene"] == 20.0

    def test_score_range(self) -> None:
        """Score is always 0-100."""
        profile: dict[str, Any] = {
            "all_sessions": [],
            "session_count": 0,
            "prompt_analysis": {},
            "cost_forensics": {},
            "model_usage": {},
            "feature_detection": {},
        }
        result = _compute_deterministic_score(profile, {})
        assert 0 <= result["score"] <= 100

    def test_zero_sessions_gives_zero_hygiene(self) -> None:
        """No sessions should yield 0 hygiene, not a perfect score."""
        profile: dict[str, Any] = {
            "all_sessions": [],
            "session_count": 0,
            "prompt_analysis": {},
            "cost_forensics": {},
            "model_usage": {},
            "feature_detection": {},
        }
        result = _compute_deterministic_score(profile, None)
        assert result["breakdown"]["session_hygiene"] == 0.0


# ---------------------------------------------------------------------------
# Merge Results Tests
# ---------------------------------------------------------------------------


class TestMergeResults:
    """Tests for AIUsageOptimizer._merge_results."""

    def test_llm_error_returns_partial_with_deterministic_score(self) -> None:
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
            "deterministic_score": {
                "score": 42,
                "grades": {"session_hygiene": {"grade": "B", "detail": "test"}},
                "breakdown": {},
            },
        }
        llm_result = {"error": "LLM failed", "source": "error"}
        result = opt._merge_results(profile, llm_result)

        assert result["source"] == "partial"
        assert result["error"] == "LLM failed"
        # Python metrics still present
        assert len(result["anti_patterns"]) == 1
        assert result["cost_forensics"]["total_cost"] == 10.0
        # Deterministic score preserved even on LLM error
        assert result["score"] == 42
        assert "session_hygiene" in result["grades"]
        # LLM prose fields have defaults
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
            "deterministic_score": {
                "score": 67,
                "grades": {"session_hygiene": {"grade": "B", "detail": "test"}},
                "breakdown": {},
            },
        }
        llm_result = {
            "source": "llm",
            "developer_profile": {"title": "Power User"},
            "recommendations": [{"title": "Use caching"}],
            "missing_features": [],
            "project_insights": [],
            "workflow": {"current": "manual", "future": "automated"},
        }
        result = opt._merge_results(profile, llm_result)

        assert result["source"] == "llm"
        # Score is deterministic, not from LLM
        assert result["score"] == 67
        assert result["developer_profile"]["title"] == "Power User"
        assert result["anti_patterns"] == []


# ---------------------------------------------------------------------------
# MAP Phase Tests
# ---------------------------------------------------------------------------


class TestMapPhase:
    """Tests for per-session LLM analysis."""

    def test_analyze_single_session_success(self) -> None:
        opt = _make_optimizer()
        session = _make_session(
            prompts=["Fix the auth bug in login.py", "That worked, thanks"],
            message_count=5,
            total_tokens=2000,
        )

        mock_response = json.dumps({
            "intent": "debugging",
            "had_spiral": False,
            "spiral_detail": "",
            "prompt_quality": "Clear first prompt with file path",
            "outcome": "resolved",
            "wasted_effort": "",
            "actionable_fix": "",
        })

        with patch(
            "agenttop.web.optimizer.get_completion",
            return_value=mock_response,
        ):
            result = opt._analyze_single_session(session)

        assert result is not None
        assert result["intent"] == "debugging"
        assert result["had_spiral"] is False
        assert result["wasted_effort"] == ""

    def test_analyze_single_session_with_spiral(self) -> None:
        opt = _make_optimizer()
        session = _make_session(
            prompts=["Fix X", "No not that", "I said X", "Wrong again", "Ugh"],
            message_count=10,
            total_tokens=5000,
        )

        mock_response = json.dumps({
            "intent": "debugging",
            "had_spiral": True,
            "spiral_detail": "user asked for X but AI kept doing Y",
            "prompt_quality": "Vague first prompt without specifics",
            "outcome": "abandoned",
            "wasted_effort": "unclear initial prompt led to 4 corrections",
            "actionable_fix": "Include file path and expected behavior upfront",
        })

        with patch(
            "agenttop.web.optimizer.get_completion",
            return_value=mock_response,
        ):
            result = opt._analyze_single_session(session)

        assert result is not None
        assert result["had_spiral"] is True
        assert "X but AI kept doing Y" in result["spiral_detail"]

    def test_analyze_single_session_no_prompts(self) -> None:
        opt = _make_optimizer()
        session = _make_session(prompts=[])
        result = opt._analyze_single_session(session)
        assert result is None

    def test_analyze_single_session_llm_error(self) -> None:
        opt = _make_optimizer()
        session = _make_session(prompts=["test prompt"])

        with patch(
            "agenttop.web.optimizer.get_completion",
            return_value="[error] timeout",
        ):
            result = opt._analyze_single_session(session)

        assert result is None

    def test_analyze_sessions_map_caches(self) -> None:
        opt = _make_optimizer()
        sessions = [
            _make_session(id="cached-1", estimated_cost_usd=1.0, prompts=["test"]),
            _make_session(id="new-1", estimated_cost_usd=2.0, prompts=["fix bug"]),
        ]
        existing_cache = {
            "cached-1": {"intent": "debugging", "had_spiral": False},
        }

        mock_response = json.dumps({
            "intent": "greenfield",
            "had_spiral": False,
            "spiral_detail": "",
            "prompt_quality": "ok",
            "outcome": "resolved",
            "wasted_effort": "",
            "actionable_fix": "",
        })

        with patch(
            "agenttop.web.optimizer.get_completion",
            return_value=mock_response,
        ) as mock_llm, patch(
            "agenttop.web.optimizer._save_session_cache",
        ):
            result = opt._analyze_sessions_map(sessions, existing_cache)

        # Only new-1 should have been sent to LLM
        assert mock_llm.call_count == 1
        assert "cached-1" in result
        assert "new-1" in result
        # Original cache dict must NOT have been mutated (immutability)
        assert "new-1" not in existing_cache

    def test_spirals_from_analyses(self) -> None:
        opt = _make_optimizer()
        sessions = [
            _make_session(
                id="s1", project="/home/user/myproject",
                prompts=["fix bug"], message_count=20, total_tokens=5000,
            ),
            _make_session(
                id="s2", project="/home/user/other",
                prompts=["add feature"], message_count=5, total_tokens=1000,
            ),
        ]
        analyses = {
            "s1": {"had_spiral": True, "spiral_detail": "kept doing wrong thing"},
            "s2": {"had_spiral": False, "spiral_detail": ""},
        }

        spirals = opt._spirals_from_analyses(sessions, analyses)
        assert len(spirals) == 1
        assert spirals[0]["project"] == "myproject"
        assert spirals[0]["tokens_wasted"] == 5000
        # corrections estimated from prompt count (1 prompt * 0.3 = min 3)
        assert spirals[0]["corrections"] >= 3
        assert spirals[0]["correction_rate"] > 0


# ---------------------------------------------------------------------------
# GENERATE Phase Tests
# ---------------------------------------------------------------------------


class TestGeneratePhase:
    """Tests for _get_llm_analysis (synthesis)."""

    def test_invalid_json_returns_error(self) -> None:
        opt = _make_optimizer()
        profile: dict[str, Any] = {
            "active_tools": [{"tool": "claude_code"}],
            "deterministic_score": {"score": 50, "grades": {}},
            "anti_patterns": [],
            "cost_forensics": {},
            "session_count": 5,
            "session_distribution": {},
            "intent_distribution": {},
            "project_details": {},
            "feature_detection": {},
        }

        with patch(
            "agenttop.web.optimizer.get_completion",
            return_value="not json at all",
        ):
            result = opt._get_llm_analysis(profile, {})

        assert result["source"] == "error"
        assert "invalid JSON" in result["error"]

    def test_error_response_propagated(self) -> None:
        opt = _make_optimizer()
        profile: dict[str, Any] = {
            "active_tools": [],
            "deterministic_score": {"score": 0, "grades": {}},
            "anti_patterns": [],
            "cost_forensics": {},
            "feature_detection": {},
        }

        with patch(
            "agenttop.web.optimizer.get_completion",
            return_value="[error] API key invalid.",
        ):
            result = opt._get_llm_analysis(profile, {})

        assert result["source"] == "error"
        assert "[error]" in result["error"]


# ---------------------------------------------------------------------------
# Cost Forensics Tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# _extract_json Tests
# ---------------------------------------------------------------------------


class TestExtractJson:
    """Tests for AIUsageOptimizer._extract_json edge cases."""

    def test_clean_json(self) -> None:
        result = AIUsageOptimizer._extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_markdown_fences(self) -> None:
        raw = '```json\n{"key": "value"}\n```'
        result = AIUsageOptimizer._extract_json(raw)
        assert result == {"key": "value"}

    def test_think_tags(self) -> None:
        raw = '<think>Let me analyze...</think>\n{"key": "value"}'
        result = AIUsageOptimizer._extract_json(raw)
        assert result == {"key": "value"}

    def test_brace_extraction_fallback(self) -> None:
        raw = 'Here is the result: {"key": "value"} end of response'
        result = AIUsageOptimizer._extract_json(raw)
        assert result == {"key": "value"}

    def test_no_json_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            AIUsageOptimizer._extract_json("no json here")
