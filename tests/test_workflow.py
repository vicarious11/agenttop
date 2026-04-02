"""Tests for workflow intelligence module."""

import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from agenttop.models import Session, ToolName
from agenttop.workflow.analyzer import WorkflowAnalyzer
from agenttop.workflow.correlator import SessionCorrelator
from agenttop.workflow.knowledge_base import get_pattern_info, get_recommendation_for_task, get_switching_cost
from agenttop.workflow.models import (
    ToolTransition,
    WorkflowChain,
    WorkflowPattern,
    WorkflowRecommendation,
)
from agenttop.workflow.patterns import WorkflowPatternDetector


# --- Test Fixtures ---


def _create_session(
    tool: ToolName,
    start_time: datetime,
    end_time: datetime | None = None,
    project: str | None = None,
    message_count: int = 10,
    total_tokens: int = 1000,
    estimated_cost_usd: float = 0.10,
) -> Session:
    """Helper to create a test session."""
    return Session(
        id=str(uuid.uuid4()),
        tool=tool,
        start_time=start_time,
        end_time=end_time,
        project=project,
        message_count=message_count,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated_cost_usd,
    )


# --- SessionCorrelator Tests ---


def test_correlator_empty_sessions():
    """Correlator handles empty session list."""
    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time([])
    assert chains == []

    chains = correlator.correlate_by_project([])
    assert chains == []


def test_correlator_single_session():
    """Correlator requires at least 2 sessions to form a chain."""
    correlator = SessionCorrelator()
    now = datetime.now()
    sessions = [_create_session(ToolName.CLAUDE_CODE, now)]

    chains = correlator.correlate_by_time(sessions)
    assert len(chains) == 0  # Single session doesn't form a chain


def test_correlate_by_time_basic():
    """Basic time-based correlation groups nearby sessions."""
    correlator = SessionCorrelator()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5)),
        _create_session(ToolName.CURSOR, now - timedelta(minutes=3), now),
        _create_session(ToolName.CLAUDE_CODE, now + timedelta(hours=2)),  # Too far - new chain
        _create_session(ToolName.KIRO, now + timedelta(hours=2, minutes=5)),
    ]

    chains = correlator.correlate_by_time(sessions, max_gap_minutes=30)
    assert len(chains) == 2

    # First chain has 2 sessions
    assert len(chains[0].session_ids) == 2
    assert set(chains[0].tools) == {"claude_code", "cursor"}

    # Second chain has 2 sessions
    assert len(chains[1].session_ids) == 2
    assert set(chains[1].tools) == {"claude_code", "kiro"}


def test_correlate_by_project():
    """Project-based correlation groups sessions by project."""
    correlator = SessionCorrelator()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(hours=3), project="/Users/test/project1"),
        _create_session(ToolName.CURSOR, now - timedelta(hours=2), project="/Users/test/project1"),
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(hours=1), project="/Users/test/project2"),
        _create_session(ToolName.KIRO, now, project="/Users/test/project1"),
    ]

    chains = correlator.correlate_by_project(sessions, max_gap_hours=1.5)
    # Should group first 2 project1 sessions within gap (Kiro is too far - 2 hours from cursor)
    assert len(chains) == 1
    assert len(chains[0].session_ids) == 2  # Only first 2 project1 sessions within gap


def test_detect_tool_transitions():
    """Tool transition detection identifies switches between tools."""
    correlator = SessionCorrelator()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5)),
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=3), now - timedelta(minutes=1)),  # Same tool - no transition
        _create_session(ToolName.CURSOR, now),
    ]

    chains = correlator.correlate_by_time(sessions)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    # Should have 1 transition: claude_code -> cursor
    assert len(transitions) == 1
    assert transitions[0].from_tool == "claude_code"
    assert transitions[0].to_tool == "cursor"
    assert transitions[0].project_match is True  # Both have None project, so they match


def test_transition_with_same_project():
    """Transitions within same project detected correctly."""
    correlator = SessionCorrelator()
    now = datetime.now()
    project = "/Users/test/project"

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5), project=project),
        _create_session(ToolName.CURSOR, now, project=project),
    ]

    chains = correlator.correlate_by_time(sessions)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    assert len(transitions) == 1
    assert transitions[0].project_match is True


def test_estimate_context_preservation_with_none_end_time():
    """Context preservation handles None end_time gracefully."""
    correlator = SessionCorrelator()
    now = datetime.now()

    from_session = _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), end_time=None)
    to_session = _create_session(ToolName.CURSOR, now, end_time=None)

    score = correlator._estimate_context_preservation(from_session, to_session)

    # Should not crash and should return a valid score
    assert 0.0 <= score <= 1.0


def test_tool_usage_distribution():
    """Tool usage distribution calculated correctly."""
    correlator = SessionCorrelator()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now),
        _create_session(ToolName.CLAUDE_CODE, now + timedelta(hours=1)),
        _create_session(ToolName.CURSOR, now + timedelta(hours=2)),
    ]

    distribution = correlator.get_tool_usage_distribution(sessions)

    assert distribution["claude_code"] == 2
    assert distribution["cursor"] == 1


def test_transition_matrix():
    """Transition frequency matrix built correctly."""
    correlator = SessionCorrelator()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5)),
        _create_session(ToolName.CURSOR, now - timedelta(minutes=3), now),
        _create_session(ToolName.CLAUDE_CODE, now + timedelta(minutes=5)),
        _create_session(ToolName.CURSOR, now + timedelta(minutes=10)),
    ]

    chains = correlator.correlate_by_time(sessions, max_gap_minutes=30)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    matrix = correlator.get_transition_matrix(transitions)

    # Should have 3 transitions: claude->cursor, cursor->claude, claude->cursor
    assert matrix["claude_code"]["cursor"] == 2
    assert matrix["cursor"]["claude_code"] == 1


# --- WorkflowPatternDetector Tests ---


def test_pattern_detector_empty_chains():
    """Pattern detector handles empty chains list."""
    detector = WorkflowPatternDetector()
    patterns = detector.detect_patterns([], [])
    assert patterns == []


def test_pattern_detector_single_tool_pattern():
    """Single tool chains detected as 'single_tool_deep_dive'."""
    detector = WorkflowPatternDetector()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5)),
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=3), now),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)

    patterns = detector.detect_patterns(chains, [])

    assert len(patterns) == 1
    assert patterns[0].name == "single_tool_deep_dive"
    assert patterns[0].frequency == 1


def test_pattern_detector_tool_hopping():
    """Tool hopping pattern detected correctly."""
    detector = WorkflowPatternDetector()
    now = datetime.now()

    # Create sessions with rapid tool switches (need 4 sessions for 3 transitions)
    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=25), now - timedelta(minutes=20)),
        _create_session(ToolName.CURSOR, now - timedelta(minutes=18), now - timedelta(minutes=15)),
        _create_session(ToolName.KIRO, now - timedelta(minutes=12), now - timedelta(minutes=10)),
        _create_session(ToolName.COPILOT, now - timedelta(minutes=8), now - timedelta(minutes=5)),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions, max_gap_minutes=30)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    patterns = detector.detect_patterns(chains, transitions)

    assert len(patterns) == 1
    assert patterns[0].name == "tool_hopping"


def test_pattern_detector_quick_iteration():
    """Quick iteration pattern detected with rapid back-and-forth."""
    detector = WorkflowPatternDetector()
    now = datetime.now()

    # Need 3 sessions for 2 transitions (same 2 tools, rapid switching)
    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=8), now - timedelta(minutes=5)),
        _create_session(ToolName.CURSOR, now - timedelta(minutes=3), now - timedelta(minutes=1)),
        _create_session(ToolName.CLAUDE_CODE, now),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    patterns = detector.detect_patterns(chains, transitions)

    assert len(patterns) == 1
    # Should detect quick_iteration (2 tools, 2+ transitions, avg gap < 5 min)
    assert patterns[0].name == "quick_iteration"


def test_pattern_detector_iterative_refinement():
    """Iterative refinement pattern detected with progressive tools."""
    detector = WorkflowPatternDetector()
    now = datetime.now()

    # Need a chain that's not tool_hopping and shows progression
    # Copilot (level 1) -> Cursor (level 2) -> Claude Code (level 3)
    # Duration should be longer to avoid tool_hopping detection
    sessions = [
        _create_session(ToolName.COPILOT, now - timedelta(minutes=50), now - timedelta(minutes=40)),
        _create_session(ToolName.CURSOR, now - timedelta(minutes=35), now - timedelta(minutes=25)),
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=20), now),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions, max_gap_minutes=30)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    patterns = detector.detect_patterns(chains, transitions)

    assert len(patterns) == 1
    assert patterns[0].name == "iterative_refinement"


def test_pattern_efficiency_calculation():
    """Pattern efficiency score calculated correctly."""
    detector = WorkflowPatternDetector()
    now = datetime.now()

    # Create efficient chain (2 sessions for a chain)
    sessions = [
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=10),
            now - timedelta(minutes=5),
            total_tokens=1000,
        ),
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=3),
            now,
            total_tokens=1000,
        ),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)

    efficiency = detector.calculate_pattern_efficiency(
        WorkflowPattern(
            name="test",
            description="Test pattern",
            tool_sequence=["claude_code"],
            frequency=1,
            avg_efficiency=0.0,
            avg_tokens=0,
            avg_cost=0.0,
        ),
        chains,
    )

    assert 0.0 <= efficiency <= 1.0


def test_pattern_recommendations():
    """Pattern recommendations generated for low-efficiency patterns."""
    detector = WorkflowPatternDetector()

    # Create a low-efficiency pattern
    patterns = [
        WorkflowPattern(
            name="tool_hopping",
            description="Frequent tool switching",
            tool_sequence=["claude_code", "cursor", "kiro"],
            frequency=5,
            avg_efficiency=0.3,
            avg_tokens=5000,
            avg_cost=1.0,
        )
    ]

    recommendations = detector.get_pattern_recommendations(patterns)

    assert len(recommendations) == 1
    assert recommendations[0]["pattern"] == "tool_hopping"
    assert "recommendation" in recommendations[0]


# --- WorkflowAnalyzer Tests ---


def test_analyzer_empty_chains():
    """Analyzer handles empty chains gracefully."""
    analyzer = WorkflowAnalyzer()
    result = analyzer.analyze_chains([], [])

    assert "error" in result
    assert result["error"] == "No chains to analyze"


def test_analyze_chains_basic():
    """Basic chain analysis produces expected output."""
    analyzer = WorkflowAnalyzer()
    now = datetime.now()

    sessions = [
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=10),
            now - timedelta(minutes=5),
            total_tokens=2500,
            estimated_cost_usd=0.25,
        ),
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=3),
            now,
            total_tokens=2500,
            estimated_cost_usd=0.25,
        ),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    result = analyzer.analyze_chains(chains, transitions)

    assert "patterns" in result
    assert "metrics" in result
    assert "recommendations" in result
    assert result["chain_count"] == 1
    assert result["transition_count"] == 0


def test_analyze_tool_combinations():
    """Tool combinations analysis groups correctly."""
    analyzer = WorkflowAnalyzer()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=20), now - timedelta(minutes=10)),
        _create_session(ToolName.CURSOR, now - timedelta(minutes=5), now),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)

    combinations = analyzer.analyze_tool_combinations(chains)

    assert len(combinations) == 1
    combo_key = list(combinations.keys())[0]
    assert "claude_code" in combo_key or "cursor" in combo_key
    assert combinations[combo_key]["count"] == 1


def test_measure_switching_costs_empty():
    """Switching costs handles empty transitions."""
    analyzer = WorkflowAnalyzer()
    result = analyzer.measure_switching_costs([])

    assert "error" in result


def test_measure_switching_costs_basic():
    """Switching costs calculated for tool transitions."""
    analyzer = WorkflowAnalyzer()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5), project="/test/project"),
        _create_session(ToolName.CURSOR, now, project="/test/project"),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    costs = analyzer.measure_switching_costs(transitions)

    assert len(costs) == 1
    key = list(costs.keys())[0]
    assert costs[key]["from_tool"] == "claude_code"
    assert costs[key]["to_tool"] == "cursor"
    assert costs[key]["frequency"] == 1


def test_identify_workflow_patterns():
    """Workflow patterns identified and returned as dicts."""
    analyzer = WorkflowAnalyzer()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5)),
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=3), now),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)

    patterns = analyzer.identify_workflow_patterns(chains, [])

    assert len(patterns) == 1
    assert patterns[0]["name"] == "single_tool_deep_dive"
    assert "frequency" in patterns[0]
    assert "avg_efficiency" in patterns[0]


def test_calculate_chain_efficiency():
    """Chain efficiency score calculated with all factors."""
    analyzer = WorkflowAnalyzer()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5)),
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=3), now),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)

    score = analyzer.calculate_chain_efficiency(chains[0], [])

    assert 0.0 <= score <= 1.0


def test_calculate_chain_efficiency_with_context_preservation():
    """Efficiency score factors in context preservation."""
    analyzer = WorkflowAnalyzer()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5), project="/test/project"),
        _create_session(ToolName.CURSOR, now, project="/test/project"),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    # Since ToolTransition is frozen, use replace to create modified transition
    from dataclasses import replace
    transitions = [
        replace(t, context_preservation_score=0.8)
        for t in transitions
    ]

    score = analyzer.calculate_chain_efficiency(chains[0], transitions)

    # Score should be valid
    assert 0.0 <= score <= 1.0


def test_task_based_recommendation():
    """Task-based recommendations returned correctly."""
    analyzer = WorkflowAnalyzer()

    rec = analyzer.get_task_based_recommendation("debugging", ["claude_code", "cursor"])

    assert rec is not None
    assert rec.primary_tool == "claude_code"
    assert rec.task_type == "debugging"


def test_task_based_recommendation_fallback():
    """Task recommendation falls back when primary unavailable."""
    analyzer = WorkflowAnalyzer()

    rec = analyzer.get_task_based_recommendation("debugging", ["cursor", "kiro"])

    # Should still provide recommendation with secondary tool
    assert rec is not None
    assert rec.primary_tool in ["cursor", "kiro"]


def test_task_based_recommendation_no_tools():
    """Task recommendation returns None when no tools available."""
    analyzer = WorkflowAnalyzer()

    rec = analyzer.get_task_based_recommendation("debugging", [])

    assert rec is None


# --- Knowledge Base Tests ---


def test_get_pattern_info():
    """Pattern info retrieved from knowledge base."""
    info = get_pattern_info("single_tool_deep_dive")

    assert info is not None
    assert "description" in info
    assert "efficiency" in info


def test_get_pattern_info_unknown():
    """Unknown pattern returns None."""
    info = get_pattern_info("unknown_pattern")

    assert info is None


def test_get_switching_cost():
    """Switching cost retrieved from knowledge base."""
    cost = get_switching_cost("claude_code", "cursor")

    assert cost is not None
    assert hasattr(cost, "context_loss_score")
    assert hasattr(cost, "mitigation_strategy")


def test_get_switching_cost_unknown():
    """Unknown tool transition returns None."""
    cost = get_switching_cost("unknown_tool1", "unknown_tool2")

    assert cost is None


def test_get_recommendation_for_task():
    """Task recommendation retrieved from knowledge base."""
    rec = get_recommendation_for_task("debugging")

    assert rec is not None
    assert rec.task_type == "debugging"
    assert rec.primary_tool is not None
    assert rec.secondary_tools is not None


def test_get_recommendation_for_task_unknown():
    """Unknown task returns None."""
    rec = get_recommendation_for_task("unknown_task")

    assert rec is None


# --- Edge Cases Tests ---


def test_empty_session_list():
    """All modules handle empty session lists."""
    correlator = SessionCorrelator()
    detector = WorkflowPatternDetector()
    analyzer = WorkflowAnalyzer()

    # Correlator
    chains = correlator.correlate_by_time([])
    assert chains == []

    # Detector
    patterns = detector.detect_patterns([], [])
    assert patterns == []

    # Analyzer
    result = analyzer.analyze_chains([], [])
    assert "error" in result


def test_none_end_time_edge_case():
    """None end_time doesn't crash any component."""
    correlator = SessionCorrelator()
    detector = WorkflowPatternDetector()
    analyzer = WorkflowAnalyzer()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), end_time=None),
        _create_session(ToolName.CURSOR, now, end_time=None),
    ]

    # Should not crash
    chains = correlator.correlate_by_time(sessions)
    transitions = correlator.detect_tool_transitions(chains, sessions)
    patterns = detector.detect_patterns(chains, transitions)
    result = analyzer.analyze_chains(chains, transitions)

    assert len(chains) >= 0
    assert len(transitions) >= 0
    assert len(patterns) >= 0
    assert "patterns" in result or "error" in result


def test_single_tool_usage():
    """Single tool chain handled correctly."""
    correlator = SessionCorrelator()
    detector = WorkflowPatternDetector()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5)),
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=3), now),
    ]

    chains = correlator.correlate_by_time(sessions)
    transitions = correlator.detect_tool_transitions(chains, sessions)
    patterns = detector.detect_patterns(chains, transitions)

    assert len(patterns) == 1
    assert patterns[0].name == "single_tool_deep_dive"


def test_very_long_time_gap():
    """Very long time gaps don't create chains."""
    correlator = SessionCorrelator()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(days=7), now - timedelta(days=7) + timedelta(minutes=10)),
        _create_session(ToolName.CURSOR, now),
    ]

    chains = correlator.correlate_by_time(sessions, max_gap_minutes=30)

    # Should not form a chain due to large gap
    assert len(chains) == 0


def test_sessions_with_no_project():
    """Sessions without project handled correctly."""
    correlator = SessionCorrelator()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), project=None),
        _create_session(ToolName.CURSOR, now, project=None),
    ]

    chains = correlator.correlate_by_time(sessions)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    # Should still create chain, project_match is True (both None projects match)
    assert len(chains) == 1
    if transitions:
        assert transitions[0].project_match is True
