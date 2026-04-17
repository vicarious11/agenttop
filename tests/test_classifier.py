"""Tests for agenttop.analysis.classifier.

Covers activity classification (tool-breakdown path + keyword-fallback path),
one-shot rate computation, tool frequency aggregation, and cost breakdowns
by project and by model.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from agenttop.analysis.classifier import (
    classify_session,
    classify_sessions,
    compute_cost_by_model,
    compute_cost_by_project,
    compute_oneshot_rate,
    compute_tool_frequency,
)
from agenttop.models import Session, ToolName


def _make_session(
    *,
    sid: str = "s1",
    project: str = "/Users/dev/foo",
    tool_breakdown: dict[str, int] | None = None,
    prompts: list[str] | None = None,
    tool_call_count: int = 0,
    total_tokens: int = 0,
    estimated_cost_usd: float = 0.0,
) -> Session:
    return Session(
        id=sid,
        tool=ToolName.CLAUDE_CODE,
        project=project,
        start_time=datetime(2026, 4, 17, 10, 0, 0),
        end_time=datetime(2026, 4, 17, 10, 30, 0),
        message_count=len(prompts or []),
        tool_call_count=tool_call_count,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated_cost_usd,
        prompts=prompts or [],
        tool_breakdown=tool_breakdown or {},
    )


# ─── classify_session: tool-breakdown path ──────────────────────────────


class TestClassifyWithToolBreakdown:
    def test_edit_heavy_session_is_coding(self) -> None:
        s = _make_session(tool_breakdown={"Edit": 10, "Read": 2})
        assert classify_session(s) == "coding"

    def test_read_heavy_session_is_exploration(self) -> None:
        s = _make_session(tool_breakdown={"Read": 15, "Grep": 5, "Edit": 1})
        assert classify_session(s) == "exploration"

    def test_agent_and_task_calls_is_planning(self) -> None:
        s = _make_session(
            tool_breakdown={"Agent": 4, "TaskCreate": 3, "Edit": 1},
        )
        assert classify_session(s) == "planning"

    def test_debug_bump_overrides_small_edit_count(self) -> None:
        # When tool pressure is light, debug-keyword bump flips to debugging.
        s = _make_session(
            tool_breakdown={"Edit": 1},
            prompts=["fix the bug causing the crash in auth"],
        )
        assert classify_session(s) == "debugging"

    def test_heavy_edit_beats_debug_bump(self) -> None:
        # Heavy editing dominates even if prompt mentions bugs — intended
        # design: real tool-call volume outweighs keyword nudges.
        s = _make_session(
            tool_breakdown={"Edit": 10, "Bash": 5},
            prompts=["fix the bug causing the crash in auth"],
        )
        assert classify_session(s) == "coding"

    def test_unknown_tool_falls_into_other(self) -> None:
        s = _make_session(tool_breakdown={"MysteryTool": 3})
        # Unmapped tools bucket into "other".
        assert classify_session(s) == "other"


# ─── classify_session: keyword-fallback path ────────────────────────────


class TestClassifyWithPromptsOnly:
    def test_debugging_keywords(self) -> None:
        s = _make_session(prompts=["fix the error on the login page"])
        assert classify_session(s) == "debugging"

    def test_refactoring_keywords(self) -> None:
        s = _make_session(
            prompts=["refactor this module and rename the helper"],
        )
        assert classify_session(s) == "refactoring"

    def test_exploration_keywords(self) -> None:
        s = _make_session(
            prompts=["explain how the caching layer works"],
        )
        assert classify_session(s) == "exploration"

    def test_tool_calls_without_prompt_match_default_to_coding(self) -> None:
        s = _make_session(prompts=["zzz"], tool_call_count=5)
        assert classify_session(s) == "coding"

    def test_empty_session_is_other(self) -> None:
        assert classify_session(_make_session()) == "other"


# ─── classify_sessions aggregation ──────────────────────────────────────


def test_classify_sessions_returns_all_activities_with_zero_fill() -> None:
    sessions = [
        _make_session(sid="a", tool_breakdown={"Edit": 5}),
        _make_session(sid="b", tool_breakdown={"Read": 5}),
    ]
    counts = classify_sessions(sessions)
    # Every activity category is present (zero-filled)
    assert set(counts.keys()) == {
        "coding", "debugging", "testing", "exploration",
        "refactoring", "git_ops", "planning", "other",
    }
    assert counts["coding"] == 1
    assert counts["exploration"] == 1
    assert counts["debugging"] == 0


# ─── compute_oneshot_rate ───────────────────────────────────────────────


class TestOneshotRate:
    def test_all_edits_no_retries_is_100(self) -> None:
        sessions = [
            _make_session(
                tool_breakdown={"Edit": 5},
                prompts=["add a new endpoint", "looks great thanks"],
            ),
        ]
        assert compute_oneshot_rate(sessions) == 100.0

    def test_retry_signal_drops_rate(self) -> None:
        sessions = [
            _make_session(
                tool_breakdown={"Edit": 4},
                prompts=["do X", "no wrong, try again"],
            ),
        ]
        rate = compute_oneshot_rate(sessions)
        assert 0 <= rate < 100

    def test_no_edits_returns_100(self) -> None:
        # No edits = no denominator = "perfect" (nothing to retry on)
        sessions = [_make_session(prompts=["what does this do"])]
        assert compute_oneshot_rate(sessions) == 100.0

    def test_hinglish_retry_signals_recognised(self) -> None:
        sessions = [
            _make_session(
                tool_breakdown={"Edit": 2},
                prompts=["add button", "nai galat hai"],
            ),
        ]
        # "nai" and "galat" should both trigger the retry counter
        assert compute_oneshot_rate(sessions) < 100


# ─── compute_tool_frequency ─────────────────────────────────────────────


def test_tool_frequency_aggregates_across_sessions() -> None:
    sessions = [
        _make_session(sid="a", tool_breakdown={"Edit": 5, "Read": 3}),
        _make_session(sid="b", tool_breakdown={"Edit": 2, "Bash": 4}),
    ]
    freq = compute_tool_frequency(sessions)
    assert freq["Edit"] == 7
    assert freq["Read"] == 3
    assert freq["Bash"] == 4
    # most_common ordering: Edit (7) > Bash (4) > Read (3)
    assert list(freq.keys())[0] == "Edit"


def test_tool_frequency_empty_returns_empty() -> None:
    assert compute_tool_frequency([]) == {}


# ─── compute_cost_by_project ────────────────────────────────────────────


class TestCostByProject:
    def test_aggregates_and_sorts_desc(self) -> None:
        sessions = [
            _make_session(sid="a", project="/Users/dev/foo",
                          estimated_cost_usd=3.0),
            _make_session(sid="b", project="/Users/dev/foo",
                          estimated_cost_usd=2.0),
            _make_session(sid="c", project="/Users/dev/bar",
                          estimated_cost_usd=10.0),
        ]
        result = compute_cost_by_project(sessions)
        assert [r["project"] for r in result] == ["bar", "foo"]
        assert result[0]["cost"] == 10.0
        assert result[1]["cost"] == 5.0
        assert result[1]["sessions"] == 2

    def test_handles_unknown_project(self) -> None:
        s = _make_session(project="", estimated_cost_usd=1.0)
        result = compute_cost_by_project([s])
        assert result[0]["project"] == "unknown"

    def test_costs_are_rounded_to_2dp(self) -> None:
        s = _make_session(
            project="/a", estimated_cost_usd=1.23456,
        )
        assert compute_cost_by_project([s])[0]["cost"] == 1.23


# ─── compute_cost_by_model ──────────────────────────────────────────────


class TestCostByModel:
    def test_opus_pricing(self) -> None:
        usage = {
            "claude-opus-4-6-20260101": {
                "inputTokens": 1_000_000,
                "outputTokens": 1_000_000,
                "cacheReadInputTokens": 0,
            },
        }
        [row] = compute_cost_by_model(usage)
        # opus: $15 input + $75 output = $90 per 1M each
        assert row["cost"] == pytest.approx(90.0)
        assert row["model"] == "opus-4-6"

    def test_haiku_pricing(self) -> None:
        usage = {
            "claude-haiku-4-5": {
                "inputTokens": 1_000_000, "outputTokens": 1_000_000,
            },
        }
        [row] = compute_cost_by_model(usage)
        # haiku: $0.8 + $4 = $4.80
        assert row["cost"] == pytest.approx(4.8)

    def test_unknown_model_defaults_to_sonnet_tier(self) -> None:
        usage = {
            "gpt-4-turbo": {
                "inputTokens": 1_000_000, "outputTokens": 1_000_000,
            },
        }
        [row] = compute_cost_by_model(usage)
        # sonnet fallback: $3 + $15 = $18
        assert row["cost"] == pytest.approx(18.0)

    def test_zero_token_models_excluded(self) -> None:
        usage = {"opus": {"inputTokens": 0, "outputTokens": 0}}
        assert compute_cost_by_model(usage) == []

    def test_sorted_by_cost_desc(self) -> None:
        usage = {
            "haiku": {"inputTokens": 1_000_000, "outputTokens": 0},
            "opus":  {"inputTokens": 1_000_000, "outputTokens": 0},
        }
        rows = compute_cost_by_model(usage)
        assert rows[0]["model"] == "opus"
        assert rows[1]["model"] == "haiku"
