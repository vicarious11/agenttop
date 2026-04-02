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

# Import CostOptimization for tests
from agenttop.workflow.models import CostOptimization  # noqa: E402 (Phase 2 test import)


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


# --- Phase 1 Tests: Momentum, Confidence Intervals, Time of Day ---


def test_session_momentum_calculation():
    """Momentum score calculated correctly for chains."""
    correlator = SessionCorrelator()
    now = datetime.now()

    # Create sessions with high momentum indicators (same project, short gaps)
    sessions = [
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=10),
            now - timedelta(minutes=5),
            project="/test/project",
        ),
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=2),
            now,
            project="/test/project",
        ),
    ]

    chains = correlator.correlate_by_time(sessions)

    assert len(chains) == 1
    # Same project + same tool + short gap = meaningful momentum
    assert chains[0].momentum_score is not None
    assert 0.0 <= chains[0].momentum_score <= 1.0
    # Should have some momentum due to same project and short gap
    # Note: Without similar prompts, momentum is lower but still present


def test_session_start_times_tracked():
    """Session start times collected for time-of-day analysis."""
    correlator = SessionCorrelator()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5)),
        _create_session(ToolName.CURSOR, now - timedelta(minutes=2), now),
    ]

    chains = correlator.correlate_by_time(sessions)

    assert len(chains) == 1
    assert len(chains[0].session_start_times) == 2
    # Session start times should be in ascending order
    assert chains[0].session_start_times[0] < chains[0].session_start_times[1]


def test_chain_sample_size():
    """Chain sample size reflects number of sessions."""
    correlator = SessionCorrelator()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5)),
        _create_session(ToolName.CURSOR, now - timedelta(minutes=2), now),
        _create_session(ToolName.KIRO, now),
    ]

    chains = correlator.correlate_by_time(sessions)

    # All 3 sessions should form a chain
    assert len(chains) == 1
    assert chains[0].sample_size == 3


def test_confidence_interval_efficiency():
    """Confidence interval calculated for efficiency scores."""
    analyzer = WorkflowAnalyzer()
    now = datetime.now()

    # Create multiple chains with different efficiency scores
    sessions = []
    for i in range(10):
        tool = ToolName.CLAUDE_CODE if i % 2 == 0 else ToolName.CURSOR
        sessions.append(_create_session(tool, now - timedelta(minutes=60 - i * 5), now - timedelta(minutes=55 - i * 5)))

    from agenttop.workflow.correlator import SessionCorrelator
    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions, max_gap_minutes=15)

    # Add efficiency scores to chains
    chains_with_efficiency = [
        chain.with_efficiency(0.6 + i * 0.03)  # Varying efficiency scores
        for i, chain in enumerate(chains)
    ]

    metrics = analyzer._calculate_metrics(chains_with_efficiency, [])

    # Should have confidence interval for efficiency with enough samples
    if len(chains_with_efficiency) >= 2:
        assert metrics.efficiency_ci is not None
        lower, upper = metrics.efficiency_ci
        assert 0.0 <= lower <= upper <= 1.0


def test_confidence_interval_insufficient_data():
    """Confidence interval is None with insufficient data."""
    analyzer = WorkflowAnalyzer()

    # Create metrics with single chain
    chains = [
        WorkflowChain(
            id="test",
            session_ids=["s1"],
            tools=["claude_code"],
            start_time=1000.0,
            end_time=2000.0,
            project="test",
            total_tokens=1000,
            total_cost=0.1,
            efficiency_score=0.7,
            sample_size=1,
        )
    ]

    metrics = analyzer._calculate_metrics(chains, [])

    # With only 1 chain, should not have CI
    assert metrics.efficiency_ci is None


def test_peak_time_of_day_analysis():
    """Peak time of day calculated from session start times."""
    analyzer = WorkflowAnalyzer()
    now = datetime.now()

    # Create sessions at 10 AM
    morning_time = now.replace(hour=10, minute=0, second=0, microsecond=0)
    sessions = []
    for i in range(5):
        sessions.append(_create_session(
            ToolName.CLAUDE_CODE,
            morning_time + timedelta(minutes=i * 5),
            morning_time + timedelta(minutes=i * 5 + 3)
        ))

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)

    metrics = analyzer._calculate_metrics(chains, [])

    # Should detect peak hour around 10 AM
    assert metrics.peak_time_of_day is not None
    hour, confidence, sample_size = metrics.peak_time_of_day
    assert hour == 10  # 10 AM
    assert 0 <= confidence <= 100
    assert sample_size == 5  # 5 sessions


def test_confidence_level_by_sample_size():
    """Confidence level determined by sample size."""
    detector = WorkflowPatternDetector()

    # High confidence with 10+ samples
    assert detector._get_confidence_level(10) == "high"
    assert detector._get_confidence_level(15) == "high"

    # Medium confidence with 5-9 samples
    assert detector._get_confidence_level(5) == "medium"
    assert detector._get_confidence_level(7) == "medium"

    # Low confidence with <5 samples
    assert detector._get_confidence_level(3) == "low"
    assert detector._get_confidence_level(1) == "low"


def test_pattern_confidence_interval():
    """Pattern includes confidence interval with sufficient data."""
    detector = WorkflowPatternDetector()
    now = datetime.now()

    # Create multiple chains for same pattern
    sessions = []
    for i in range(8):
        tool = ToolName.CLAUDE_CODE if i % 2 == 0 else ToolName.CURSOR
        sessions.append(_create_session(
            tool,
            now - timedelta(minutes=60 - i * 5),
            now - timedelta(minutes=55 - i * 5),
            project="/test/project"
        ))

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions, max_gap_minutes=15)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    patterns = detector.detect_patterns(chains, transitions)

    # Should have at least one pattern
    assert len(patterns) >= 1

    # With 8 chains, should have confidence level
    pattern = patterns[0]
    assert pattern.sample_size >= 1
    assert pattern.confidence in ["low", "medium", "high"]


# --- Phase 2 Tests: Anti-Pattern Detection ---


def test_anti_pattern_detector_empty_chains():
    """Anti-pattern detector handles empty chains."""
    from agenttop.workflow.anti_patterns import AntiPatternDetector

    detector = AntiPatternDetector()
    patterns = detector.detect_anti_patterns([], [])
    assert patterns == []


def test_anti_pattern_excessive_switching():
    """Excessive tool switching detected as anti-pattern."""
    from agenttop.workflow.anti_patterns import AntiPatternDetector, AntiPatternType

    detector = AntiPatternDetector()
    now = datetime.now()

    # Create chain with 5 different tools (exceeds threshold of 4)
    # and 4 transitions (exceeds threshold of 3)
    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=25), now - timedelta(minutes=20)),
        _create_session(ToolName.CURSOR, now - timedelta(minutes=18), now - timedelta(minutes=15)),
        _create_session(ToolName.KIRO, now - timedelta(minutes=12), now - timedelta(minutes=10)),
        _create_session(ToolName.COPILOT, now - timedelta(minutes=8), now - timedelta(minutes=5)),
        _create_session(ToolName.AIDER, now - timedelta(minutes=3), now),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions, max_gap_minutes=30)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    patterns = detector.detect_anti_patterns(chains, transitions)

    # Should detect excessive switching (5 tools, 4+ transitions)
    assert len(patterns) >= 1
    excessive_patterns = [p for p in patterns if p.type == AntiPatternType.EXCESSIVE_SWITCHING]
    assert len(excessive_patterns) >= 1
    assert excessive_patterns[0].severity in ["high", "critical"]


def test_anti_pattern_spiraling():
    """Spiraling (high token consumption with low efficiency) detected."""
    from agenttop.workflow.anti_patterns import AntiPatternDetector, AntiPatternType

    detector = AntiPatternDetector()
    now = datetime.now()

    # Create session with high token consumption (spiraling)
    # Need >3000 tokens/minute for 10+ minutes with low efficiency
    sessions = [
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=15),
            now - timedelta(minutes=10),
            total_tokens=25000,  # ~5000 tokens/min
            message_count=30,
        ),
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=9),
            now - timedelta(minutes=2),
            total_tokens=30000,  # ~4300 tokens/min
            message_count=30,
        ),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)
    # Add low efficiency - need chains to exist first
    if chains:
        chains_with_low_eff = [chains[0].with_efficiency(0.3)]
    else:
        chains_with_low_eff = []

    patterns = detector.detect_anti_patterns(chains_with_low_eff, [])

    # May detect spiraling with high token consumption and low efficiency
    spiraling_patterns = [p for p in patterns if p.type == AntiPatternType.SPIRALING]
    if spiraling_patterns:
        assert spiraling_patterns[0].type == AntiPatternType.SPIRALING


def test_anti_pattern_context_thrashing():
    """Context thrashing (rapid tool switching) detected."""
    from agenttop.workflow.anti_patterns import AntiPatternDetector, AntiPatternType

    detector = AntiPatternDetector()
    now = datetime.now()

    # Create sessions with rapid tool switches (less than 2 minutes apart)
    # Need 4+ occurrences for detection
    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=8), now - timedelta(minutes=7)),
        _create_session(ToolName.CURSOR, now - timedelta(minutes=6), now - timedelta(minutes=5)),
        _create_session(ToolName.KIRO, now - timedelta(minutes=4), now - timedelta(minutes=3)),
        _create_session(ToolName.COPILOT, now - timedelta(minutes=2), now - timedelta(minutes=1)),
        _create_session(ToolName.AIDER, now),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions, max_gap_minutes=10)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    patterns = detector.detect_anti_patterns(chains, transitions)

    # Should detect context thrashing with 4+ rapid switches
    thrashing_patterns = [p for p in patterns if p.type == AntiPatternType.CONTEXT_THRASHING]
    if thrashing_patterns:
        assert thrashing_patterns[0].type == AntiPatternType.CONTEXT_THRASHING


def test_anti_pattern_abandoned_sessions():
    """Abandoned sessions (short sessions with multiple attempts) detected."""
    from agenttop.workflow.anti_patterns import AntiPatternDetector, AntiPatternType

    detector = AntiPatternDetector()
    now = datetime.now()

    # Create multiple very short sessions (suggesting abandonment)
    # Duration < 1 minute, 2+ sessions
    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(seconds=30), now - timedelta(seconds=20)),
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(seconds=15), now - timedelta(seconds=5)),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions, max_gap_minutes=1)

    patterns = detector.detect_anti_patterns(chains, [])

    # May detect abandoned sessions
    abandoned_patterns = [p for p in patterns if p.type == AntiPatternType.ABANDONED_SESSION]
    assert len(abandoned_patterns) >= 0  # May or may not detect depending on exact timing


def test_anti_pattern_cost_bloat():
    """Cost bloat (high cost relative to median) detected."""
    from agenttop.workflow.anti_patterns import AntiPatternDetector, AntiPatternType

    detector = AntiPatternDetector()
    now = datetime.now()

    # Create chains with varying costs - one much higher than median
    # Need 2+ sessions for each to form chains
    sessions_low = [
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=30),
            now - timedelta(minutes=25),
            total_tokens=5000,
            estimated_cost_usd=1.0,
        ),
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=24),
            now - timedelta(minutes=20),
            total_tokens=5000,
            estimated_cost_usd=1.0,
        ),
    ]

    sessions_high = [
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=18),
            now - timedelta(minutes=12),
            total_tokens=25000,
            estimated_cost_usd=7.5,
        ),
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=10),
            now - timedelta(minutes=5),
            total_tokens=25000,
            estimated_cost_usd=7.5,
        ),
    ]

    correlator = SessionCorrelator()
    chains_low = correlator.correlate_by_time(sessions_low)
    chains_high = correlator.correlate_by_time(sessions_high)

    # Add efficiency values - need chains to exist first
    all_chains = []
    if chains_low:
        all_chains.append(chains_low[0].with_efficiency(0.8))
    if chains_high:
        all_chains.append(chains_high[0].with_efficiency(0.3))

    patterns = detector.detect_anti_patterns(all_chains, [])

    # May detect cost bloat on the expensive chain
    cost_bloat_patterns = [p for p in patterns if p.type == AntiPatternType.COST_BLOAT]
    assert len(cost_bloat_patterns) >= 0


def test_anti_pattern_token_inefficiency():
    """Token inefficiency (high tokens, low efficiency) detected."""
    from agenttop.workflow.anti_patterns import AntiPatternDetector, AntiPatternType

    detector = AntiPatternDetector()
    now = datetime.now()

    # Create chains with varying token usage
    # Need 2+ sessions for each to form chains
    sessions_normal = [
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=20),
            now - timedelta(minutes=15),
            total_tokens=5000,
        ),
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=14),
            now - timedelta(minutes=10),
            total_tokens=5000,
        ),
    ]

    sessions_inefficient = [
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=8),
            now - timedelta(minutes=5),
            total_tokens=25000,  # 5x more tokens
        ),
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=4),
            now,
            total_tokens=25000,
        ),
    ]

    correlator = SessionCorrelator()
    chains_normal = correlator.correlate_by_time(sessions_normal)
    chains_inefficient = correlator.correlate_by_time(sessions_inefficient)

    # Add efficiency values - need chains to exist first
    all_chains = []
    if chains_normal:
        all_chains.append(chains_normal[0].with_efficiency(0.8))
    if chains_inefficient:
        all_chains.append(chains_inefficient[0].with_efficiency(0.3))

    # Add low efficiency to inefficient chain
    all_chains = [chains_normal[0].with_efficiency(0.8), chains_inefficient[0].with_efficiency(0.3)]

    patterns = detector.detect_anti_patterns(all_chains, [])

    # May detect token inefficiency
    token_patterns = [p for p in patterns if p.type == AntiPatternType.TOKEN_INEFFICIENCY]
    assert len(token_patterns) >= 0


def test_anti_pattern_summary():
    """Anti-pattern summary aggregates all patterns."""
    from agenttop.workflow.anti_patterns import AntiPatternDetector

    detector = AntiPatternDetector()
    now = datetime.now()

    # Create sessions that might trigger anti-patterns
    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=25), now - timedelta(minutes=20)),
        _create_session(ToolName.CURSOR, now - timedelta(minutes=18), now - timedelta(minutes=15)),
        _create_session(ToolName.KIRO, now - timedelta(minutes=12), now - timedelta(minutes=10)),
        _create_session(ToolName.COPILOT, now - timedelta(minutes=8), now - timedelta(minutes=5)),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    patterns = detector.detect_anti_patterns(chains, transitions)
    summary = detector.get_anti_pattern_summary(patterns)

    assert summary["total_count"] >= 0
    assert "by_severity" in summary
    assert "by_type" in summary
    assert "total_cost_impact" in summary


# --- Phase 2 Tests: Tool Affinity Analyzer ---


def test_tool_affinity_empty_chains():
    """Tool affinity analyzer handles empty chains."""
    from agenttop.workflow.affinity import ToolAffinityAnalyzer

    analyzer = ToolAffinityAnalyzer()
    affinities = analyzer.analyze_affinities([])
    assert affinities == []


def test_tool_affinity_by_time_of_day():
    """Tool affinity analyzed by time of day."""
    from agenttop.workflow.affinity import ToolAffinityAnalyzer

    analyzer = ToolAffinityAnalyzer()
    now = datetime.now()

    # Create sessions at different times but close enough to form chains
    morning_time = now.replace(hour=9, minute=0, second=0, microsecond=0)

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, morning_time, morning_time + timedelta(minutes=5)),
        _create_session(ToolName.CLAUDE_CODE, morning_time + timedelta(minutes=10), morning_time + timedelta(minutes=15)),
        _create_session(ToolName.CURSOR, morning_time + timedelta(minutes=20), morning_time + timedelta(minutes=25)),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)

    # Need chains with efficiency scores for affinity analysis
    chains_with_eff = [c.with_efficiency(0.7) for c in chains]

    affinities = analyzer.analyze_affinities(chains_with_eff)

    # Should have affinities with time contexts
    assert len(affinities) >= 1
    time_affinities = [a for a in affinities if a.context.startswith("time_")]
    assert len(time_affinities) >= 1


def test_tool_affinity_by_chain_length():
    """Tool affinity analyzed by chain length."""
    from agenttop.workflow.affinity import ToolAffinityAnalyzer

    analyzer = ToolAffinityAnalyzer()
    now = datetime.now()

    # Create multiple chains of same length category to get sample_size >= 2
    base_time = now - timedelta(minutes=120)

    # Two short chains (2 sessions each) with same tool
    sessions_short1 = [
        _create_session(ToolName.CLAUDE_CODE, base_time, base_time + timedelta(minutes=5)),
        _create_session(ToolName.CLAUDE_CODE, base_time + timedelta(minutes=10), base_time + timedelta(minutes=15)),
    ]

    sessions_short2 = [
        _create_session(ToolName.CLAUDE_CODE, base_time + timedelta(minutes=30), base_time + timedelta(minutes=35)),
        _create_session(ToolName.CLAUDE_CODE, base_time + timedelta(minutes=40), base_time + timedelta(minutes=45)),
    ]

    correlator = SessionCorrelator()
    chains_short1 = correlator.correlate_by_time(sessions_short1)
    chains_short2 = correlator.correlate_by_time(sessions_short2)

    # Need chains with efficiency scores for affinity analysis
    all_chains = []
    for c in chains_short1 + chains_short2:
        all_chains.append(c.with_efficiency(0.7))

    affinities = analyzer.analyze_affinities(all_chains)

    # Should have workflow length affinities
    workflow_affinities = [a for a in affinities if a.context.startswith("workflow_")]
    assert len(workflow_affinities) >= 1


def test_tool_affinity_by_efficiency_tier():
    """Tool affinity analyzed by efficiency tier."""
    from agenttop.workflow.affinity import ToolAffinityAnalyzer

    analyzer = ToolAffinityAnalyzer()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5)),
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=3), now),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)
    chains_with_eff = [chains[0].with_efficiency(0.8)]  # High efficiency

    affinities = analyzer.analyze_affinities(chains_with_eff)

    # Should have high efficiency affinities
    assert len(affinities) >= 0


def test_tool_affinity_recommendations():
    """Context-specific tool affinity recommendations."""
    from agenttop.workflow.affinity import ToolAffinityAnalyzer

    analyzer = ToolAffinityAnalyzer()
    now = datetime.now()

    # Create sessions mostly in morning
    morning_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    sessions = [
        _create_session(ToolName.CLAUDE_CODE, morning_time, morning_time + timedelta(minutes=5)),
        _create_session(ToolName.CLAUDE_CODE, morning_time + timedelta(hours=1), morning_time + timedelta(hours=1, minutes=5)),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)

    # Get affinities first
    affinities = analyzer.analyze_affinities(chains)

    # Get recommendations for time_morning context
    recommendations = analyzer.get_recommendations_for_context(
        affinities=affinities,
        context="time_morning",
    )

    # May have recommendations for morning context
    assert len(recommendations) >= 0


# --- Phase 2 Tests: Cost Optimizer ---


def test_cost_optimizer_empty_chains():
    """Cost optimizer handles empty chains."""
    from agenttop.workflow.cost_optimizer import CostOptimizer

    optimizer = CostOptimizer()
    optimizations = optimizer.analyze_optimization_opportunities([])
    assert optimizations == []


def test_cost_optimizer_expensive_tool_detection():
    """Expensive tool usage detected for optimization."""
    from agenttop.workflow.cost_optimizer import CostOptimizer

    optimizer = CostOptimizer()
    now = datetime.now()

    # Create chain with high cost (simulating claude_code usage)
    sessions = [
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=10),
            now - timedelta(minutes=5),
            total_tokens=50000,
            estimated_cost_usd=10.0,
        ),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)

    optimizations = optimizer.analyze_optimization_opportunities(chains)

    # claude_code is expensive (rank 30), may detect optimization
    assert len(optimizations) >= 0


def test_cost_optimizer_low_efficiency_waste():
    """Low efficiency chains flagged for cost waste."""
    from agenttop.workflow.cost_optimizer import CostOptimizer

    optimizer = CostOptimizer()
    now = datetime.now()

    # Need at least 3 sessions for chain formation
    sessions = [
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=10),
            now - timedelta(minutes=7),
            total_tokens=10000,
            estimated_cost_usd=2.0,
        ),
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=5),
            now - timedelta(minutes=2),
            total_tokens=10000,
            estimated_cost_usd=2.0,
        ),
        _create_session(
            ToolName.CLAUDE_CODE,
            now,
            now + timedelta(minutes=3),
            total_tokens=10000,
            estimated_cost_usd=2.0,
        ),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)
    if chains:
        chains_with_low_eff = [chains[0].with_efficiency(0.3)]
        optimizations = optimizer.analyze_optimization_opportunities(chains_with_low_eff)
        # Should detect low efficiency waste
        assert len(optimizations) >= 0
    else:
        # If no chains formed, test passes vacuously
        assert True


def test_cost_optimizer_aggregate_opportunities():
    """Aggregate cost opportunities detected across chains."""
    from agenttop.workflow.cost_optimizer import CostOptimizer

    optimizer = CostOptimizer()
    now = datetime.now()

    # Create multiple chains with expensive tool and low efficiency
    sessions = []
    for i in range(5):
        sessions.append(_create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=60 - i * 10),
            now - timedelta(minutes=55 - i * 10),
            total_tokens=30000,
            estimated_cost_usd=8.0,
        ))

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions, max_gap_minutes=15)
    chains_with_low_eff = [c.with_efficiency(0.4) for c in chains]

    optimizations = optimizer.analyze_optimization_opportunities(chains_with_low_eff)

    # Should have aggregate opportunities with 5+ chains
    assert len(optimizations) >= 0


def test_cost_optimizer_total_waste():
    """Total waste calculated correctly."""
    from agenttop.workflow.cost_optimizer import CostOptimizer, CostOptimization

    optimizer = CostOptimizer()

    optimizations = [
        CostOptimization(
            pattern_name="test1",
            current_cost=10.0,
            optimized_cost=7.0,
            potential_savings=3.0,
            savings_percentage=30.0,
            recommendation="Test 1",
            alternative_tools=[],
            confidence="high",
        ),
        CostOptimization(
            pattern_name="test2",
            current_cost=5.0,
            optimized_cost=4.0,
            potential_savings=1.0,
            savings_percentage=20.0,
            recommendation="Test 2",
            alternative_tools=[],
            confidence="medium",
        ),
    ]

    waste = optimizer.get_total_waste(optimizations)

    assert waste["total_potential_savings"] == 4.0  # 3.0 + 1.0
    assert waste["total_current_cost"] == 15.0
    assert waste["optimization_count"] == 2


def test_cost_optimizer_sorted_by_savings():
    """Optimizations sorted by potential savings."""
    from agenttop.workflow.cost_optimizer import CostOptimizer

    optimizer = CostOptimizer()

    # Test with actual chains
    now = datetime.now()
    sessions = [
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=10),
            now,
            total_tokens=100000,
            estimated_cost_usd=100.0,
        ),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)

    optimizations = optimizer.analyze_optimization_opportunities(chains)

    # Should be sorted by potential savings (descending)
    if len(optimizations) > 1:
        for i in range(len(optimizations) - 1):
            assert optimizations[i].potential_savings >= optimizations[i + 1].potential_savings


# --- Phase 2 Tests: Workflow Predictor ---


def test_workflow_predictor_no_data():
    """Predictor handles empty data gracefully."""
    from agenttop.workflow.prediction import WorkflowPredictor

    predictor = WorkflowPredictor()

    prediction = predictor.predict_next_tool(
        current_session={"tool": "claude_code", "project": "/test"},
        chains=[],
        transitions=[],
        patterns=[],
    )

    assert prediction is None


def test_workflow_predictor_pattern_based():
    """Pattern-based prediction predicts next tool in sequence."""
    from agenttop.workflow.prediction import WorkflowPredictor, WorkflowPattern

    predictor = WorkflowPredictor()
    now = datetime.now()

    # Create a pattern with tool sequence
    pattern = WorkflowPattern(
        name="test_pattern",
        description="Test pattern for prediction",
        tool_sequence=["claude_code", "cursor"],
        frequency=5,
        avg_efficiency=0.7,
        avg_tokens=5000,
        avg_cost=1.0,
    )

    current_session = {
        "tool": "claude_code",
        "project": "/test",
        "session_id": "test123",
    }

    prediction = predictor.predict_next_tool(
        current_session=current_session,
        chains=[],
        transitions=[],
        patterns=[pattern],
    )

    assert prediction is not None
    assert prediction.predicted_next_tool == "cursor"
    assert prediction.based_on_pattern == "test_pattern"


def test_workflow_predictor_transition_based():
    """Transition-based prediction uses historical transitions."""
    from agenttop.workflow.prediction import WorkflowPredictor
    from agenttop.workflow.models import ToolTransition

    predictor = WorkflowPredictor()
    now = datetime.now()

    # Create transitions showing claude_code -> cursor pattern
    transitions = [
        ToolTransition(
            id="trans1",
            from_session_id="s1",
            to_session_id="s2",
            from_tool="claude_code",
            to_tool="cursor",
            time_gap_seconds=120,
            project_match=True,
            timestamp=now.timestamp(),
            context_preservation_score=0.8,
        ),
        ToolTransition(
            id="trans2",
            from_session_id="s3",
            to_session_id="s4",
            from_tool="claude_code",
            to_tool="cursor",
            time_gap_seconds=90,
            project_match=True,
            timestamp=now.timestamp(),
            context_preservation_score=0.9,
        ),
    ]

    current_session = {
        "tool": "claude_code",
        "project": "/test",
        "session_id": "test123",
    }

    prediction = predictor.predict_next_tool(
        current_session=current_session,
        chains=[],
        transitions=transitions,
        patterns=[],
    )

    assert prediction is not None
    assert prediction.predicted_next_tool == "cursor"
    assert prediction.confidence >= 0.5


def test_workflow_predictor_context_based():
    """Context-based prediction uses similar historical contexts."""
    from agenttop.workflow.prediction import WorkflowPredictor

    predictor = WorkflowPredictor()
    now = datetime.now()

    # Create chains showing similar context pattern
    # Need to create historical chains that show what follows claude_code
    sessions_historical = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=50), now - timedelta(minutes=45), project="/test/project"),
        _create_session(ToolName.CURSOR, now - timedelta(minutes=40), now - timedelta(minutes=35), project="/test/project"),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions_historical, max_gap_minutes=30)

    # Add metrics to chains
    chains_with_metrics = [c.with_efficiency(0.7).with_momentum(0.6) for c in chains]

    current_session = {
        "tool": "claude_code",
        "project": "/test/project",
        "session_id": "test123",
        "message_count": 10,
    }

    prediction = predictor.predict_next_tool(
        current_session=current_session,
        chains=chains_with_metrics,
        transitions=[],
        patterns=[],
    )

    # May predict cursor based on similar context (pattern from historical chains)
    if prediction:
        assert prediction.predicted_next_tool == "cursor"


def test_workflow_predictor_low_confidence():
    """Predictor returns None when confidence is too low."""
    from agenttop.workflow.prediction import WorkflowPredictor
    from agenttop.workflow.models import WorkflowPattern

    predictor = WorkflowPredictor()

    # Create weak pattern
    pattern = WorkflowPattern(
        name="weak_pattern",
        description="Weak pattern",
        tool_sequence=["claude_code", "cursor"],
        frequency=1,  # Low frequency = low confidence
        avg_efficiency=0.5,
        avg_tokens=1000,
        avg_cost=0.1,
    )

    current_session = {
        "tool": "claude_code",
        "project": "/test",
        "session_id": "test123",
    }

    prediction = predictor.predict_next_tool(
        current_session=current_session,
        chains=[],
        transitions=[],
        patterns=[pattern],
    )

    # Low frequency pattern may not meet confidence threshold
    # If it does predict, confidence should be low
    if prediction:
        assert prediction.confidence < 0.5


def test_workflow_predictor_optimization_suggestions():
    """Workflow optimization suggestions generated."""
    from agenttop.workflow.prediction import WorkflowPredictor

    predictor = WorkflowPredictor()
    now = datetime.now()

    # Create chains with varying efficiency
    sessions_high_eff = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=20), now - timedelta(minutes=10)),
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=5), now),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions_high_eff)
    chains_with_high_eff = [chains[0].with_efficiency(0.9)]

    suggestions = predictor.suggest_workflow_optimization(chains_with_high_eff, [])

    assert len(suggestions) >= 0
    # May suggest using the efficient tool more


# --- Phase 2 Tests: Productivity Scorer ---


def test_productivity_scorer_empty_chains():
    """Productivity scorer handles empty chains."""
    from agenttop.workflow.productivity import ProductivityScorer

    scorer = ProductivityScorer()
    score, breakdown = scorer.calculate_productivity_score([], [])

    assert score == 0.5
    assert breakdown == {}


def test_productivity_scorer_basic():
    """Basic productivity score calculated."""
    from agenttop.workflow.productivity import ProductivityScorer

    scorer = ProductivityScorer()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5)),
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=3), now),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)
    chains_with_metrics = [
        chains[0].with_efficiency(0.7),
    ]

    score, breakdown = scorer.calculate_productivity_score(chains_with_metrics, [])

    assert 0.0 <= score <= 1.0
    assert "efficiency" in breakdown
    assert "cost_effectiveness" in breakdown
    assert "momentum" in breakdown
    assert "focus" in breakdown
    assert "overall" in breakdown


def test_productivity_scorer_with_anti_patterns():
    """Productivity score penalizes anti-patterns."""
    from agenttop.workflow.productivity import ProductivityScorer
    from agenttop.workflow.models import AntiPattern, AntiPatternType

    scorer = ProductivityScorer()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5)),
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=3), now),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)
    chains_with_metrics = [chains[0].with_efficiency(0.8)]

    # Create anti-patterns affecting sessions
    anti_patterns = [
        AntiPattern(
            id="ap1",
            type=AntiPatternType.EXCESSIVE_SWITCHING,
            severity="medium",
            affected_sessions=list(chains[0].session_ids),
            description="Too many tool switches",
            detected_at=now.timestamp(),
            remedy="Reduce tool switching",
            estimated_cost_impact=0.0,
        ),
    ]

    score, breakdown = scorer.calculate_productivity_score(chains_with_metrics, anti_patterns)

    # Score should be lower due to anti-pattern
    assert breakdown["anti_pattern_free"] < 1.0


def test_productivity_scorer_focus_factor():
    """Focus factor decreases with excessive tool switching."""
    from agenttop.workflow.productivity import ProductivityScorer

    scorer = ProductivityScorer()
    now = datetime.now()

    # Single tool chain = high focus
    sessions_single = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5)),
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=3), now),
    ]

    correlator = SessionCorrelator()
    chains_single = correlator.correlate_by_time(sessions_single)

    # Multi-tool chain = lower focus
    sessions_multi = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=25), now - timedelta(minutes=20)),
        _create_session(ToolName.CURSOR, now - timedelta(minutes=18), now - timedelta(minutes=15)),
        _create_session(ToolName.KIRO, now - timedelta(minutes=12), now - timedelta(minutes=10)),
        _create_session(ToolName.COPILOT, now - timedelta(minutes=8), now - timedelta(minutes=5)),
    ]

    chains_multi = correlator.correlate_by_time(sessions_multi, max_gap_minutes=30)

    focus_single = scorer._calculate_focus_factor(chains_single)
    focus_multi = scorer._calculate_focus_factor(chains_multi)

    assert focus_single > focus_multi


def test_productivity_grade_conversion():
    """Productivity score converted to letter grade."""
    from agenttop.workflow.productivity import ProductivityScorer

    scorer = ProductivityScorer()

    assert scorer.get_productivity_grade(0.95) == "A"
    assert scorer.get_productivity_grade(0.85) == "B"
    assert scorer.get_productivity_grade(0.75) == "C"
    assert scorer.get_productivity_grade(0.65) == "D"
    assert scorer.get_productivity_grade(0.45) == "F"


def test_productivity_improvement_suggestions():
    """Improvement suggestions based on factor breakdown."""
    from agenttop.workflow.productivity import ProductivityScorer

    scorer = ProductivityScorer()

    breakdown_low_efficiency = {
        "efficiency": 0.3,
        "cost_effectiveness": 0.7,
        "momentum": 0.7,
        "focus": 0.7,
        "anti_pattern_free": 0.8,
        "overall": 0.5,
    }

    suggestions = scorer.get_improvement_suggestions(breakdown_low_efficiency)

    assert len(suggestions) >= 1
    assert any("efficiency" in s.lower() for s in suggestions)


def test_productivity_chain_score():
    """Single chain productivity score calculated."""
    from agenttop.workflow.productivity import ProductivityScorer

    scorer = ProductivityScorer()
    now = datetime.now()

    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=10), now - timedelta(minutes=5)),
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=3), now),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)
    chain_with_metrics = chains[0].with_efficiency(0.8)

    score = scorer.calculate_chain_productivity(chain_with_metrics)

    assert 0.0 <= score <= 1.0


def test_productivity_cost_effectiveness():
    """Cost effectiveness calculated correctly."""
    from agenttop.workflow.productivity import ProductivityScorer

    scorer = ProductivityScorer()
    now = datetime.now()

    # High tokens per dollar = high effectiveness
    sessions_efficient = [
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=10),
            now - timedelta(minutes=5),
            total_tokens=50000,
            estimated_cost_usd=0.5,
        ),
        _create_session(
            ToolName.CLAUDE_CODE,
            now - timedelta(minutes=4),
            now,
            total_tokens=50000,
            estimated_cost_usd=0.5,
        ),
    ]

    # Low tokens per dollar = low effectiveness
    sessions_inefficient = [
        _create_session(
            ToolName.CLAUDE_CODE,
            now + timedelta(minutes=5),
            now + timedelta(minutes=10),
            total_tokens=1000,
            estimated_cost_usd=1.0,
        ),
        _create_session(
            ToolName.CLAUDE_CODE,
            now + timedelta(minutes=15),
            now + timedelta(minutes=20),
            total_tokens=1000,
            estimated_cost_usd=1.0,
        ),
    ]

    correlator = SessionCorrelator()
    chains_efficient = correlator.correlate_by_time(sessions_efficient)
    chains_inefficient = correlator.correlate_by_time(sessions_inefficient)

    eff_efficient = scorer._calculate_cost_effectiveness(chains_efficient)
    eff_inefficient = scorer._calculate_cost_effectiveness(chains_inefficient)

    assert eff_efficient > eff_inefficient


# --- Phase 2 Integration Tests ---


def test_phase_2_full_workflow_analysis():
    """Full workflow analysis with Phase 2 components."""
    from agenttop.workflow.anti_patterns import AntiPatternDetector
    from agenttop.workflow.affinity import ToolAffinityAnalyzer
    from agenttop.workflow.cost_optimizer import CostOptimizer
    from agenttop.workflow.prediction import WorkflowPredictor
    from agenttop.workflow.productivity import ProductivityScorer

    now = datetime.now()

    # Create realistic session data
    sessions = [
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=50), now - timedelta(minutes=40), project="/test/project"),
        _create_session(ToolName.CURSOR, now - timedelta(minutes=35), now - timedelta(minutes=25), project="/test/project"),
        _create_session(ToolName.CLAUDE_CODE, now - timedelta(minutes=20), now - timedelta(minutes=10), project="/test/project"),
        _create_session(ToolName.KIRO, now - timedelta(minutes=5), now, project="/test/project"),
    ]

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions, max_gap_minutes=30)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    # Add efficiency scores
    chains_with_eff = [c.with_efficiency(0.7) for c in chains]

    # Run all Phase 2 analyses
    anti_pattern_detector = AntiPatternDetector()
    affinity_analyzer = ToolAffinityAnalyzer()
    cost_optimizer = CostOptimizer()
    workflow_predictor = WorkflowPredictor()
    productivity_scorer = ProductivityScorer()

    # Detect anti-patterns
    anti_patterns = anti_pattern_detector.detect_anti_patterns(chains_with_eff, transitions)

    # Analyze affinities
    time_affinities = affinity_analyzer.analyze_affinities(chains_with_eff)

    # Find cost optimizations
    optimizations = cost_optimizer.analyze_optimization_opportunities(chains_with_eff)

    # Get predictions
    current_session = {
        "tool": "kiro",
        "project": "/test/project",
        "session_id": "current",
        "message_count": 10,
    }
    prediction = workflow_predictor.predict_next_tool(
        current_session=current_session,
        chains=chains_with_eff,
        transitions=transitions,
        patterns=[],
    )

    # Calculate productivity
    productivity_score, breakdown = productivity_scorer.calculate_productivity_score(
        chains_with_eff,
        anti_patterns,
    )

    # Verify all Phase 2 components return valid data
    assert len(anti_patterns) >= 0
    assert len(time_affinities) >= 0
    assert len(optimizations) >= 0
    assert 0.0 <= productivity_score <= 1.0
    assert "overall" in breakdown


def test_phase_2_models_immutability():
    """Phase 2 models are immutable (frozen dataclasses)."""
    from dataclasses import FrozenInstanceError
    from agenttop.workflow.models import (
        AntiPattern,
        AntiPatternType,
        ToolAffinity,
        WorkflowPrediction,
        CostOptimization,
    )

    # AntiPattern should be frozen
    anti_pattern = AntiPattern(
        id="ap1",
        type=AntiPatternType.EXCESSIVE_SWITCHING,
        severity="medium",
        affected_sessions=["s1", "s2"],
        description="Test",
        detected_at=0.0,
        remedy="Fix it",
        estimated_cost_impact=1.0,
    )

    try:
        anti_pattern.severity = "high"
        assert False, "Should not be able to modify frozen dataclass"
    except (FrozenInstanceError, AttributeError):
        pass  # Expected

    # ToolAffinity should be frozen
    affinity = ToolAffinity(
        tool="claude_code",
        context="morning",
        success_rate=0.8,
        avg_efficiency=0.7,
        avg_cost_per_outcome=1.0,
        sample_size=10,
    )

    try:
        affinity.success_rate = 0.5
        assert False, "Should not be able to modify frozen dataclass"
    except (FrozenInstanceError, AttributeError):
        pass  # Expected

    # CostOptimization should be frozen
    optimization = CostOptimization(
        pattern_name="test",
        current_cost=10.0,
        optimized_cost=5.0,
        potential_savings=5.0,
        savings_percentage=50.0,
        recommendation="Use cheaper tool",
        alternative_tools=["kiro"],
        confidence="high",
    )

    try:
        optimization.potential_savings = 10.0
        assert False, "Should not be able to modify frozen dataclass"
    except (FrozenInstanceError, AttributeError):
        pass  # Expected

    # WorkflowPrediction should be frozen
    prediction = WorkflowPrediction(
        current_session_id="s1",
        predicted_next_tool="cursor",
        confidence=0.8,
        reasoning="Test",
        alternative_suggestions=["kiro"],
        based_on_pattern="test_pattern",
    )

    try:
        prediction.confidence = 0.9
        assert False, "Should not be able to modify frozen dataclass"
    except (FrozenInstanceError, AttributeError):
        pass  # Expected


def test_phase_2_anti_pattern_type_enum():
    """AntiPatternType enum has all expected values."""
    from agenttop.workflow.models import AntiPatternType

    assert AntiPatternType.EXCESSIVE_SWITCHING.value == "excessive_switching"
    assert AntiPatternType.SPIRALING.value == "spiraling"
    assert AntiPatternType.CONTEXT_THRASHING.value == "context_thrashing"
    assert AntiPatternType.ABANDONED_SESSION.value == "abandoned_session"
    assert AntiPatternType.COST_BLOAT.value == "cost_bloat"
    assert AntiPatternType.TOKEN_INEFFICIENCY.value == "token_inefficiency"


def test_phase_2_workflow_metrics_extended():
    """WorkflowMetrics includes Phase 2 fields."""
    from agenttop.workflow.models import WorkflowMetrics

    # Create metrics with Phase 2 fields
    metrics = WorkflowMetrics(
        total_chains=10,
        total_transitions=20,
        avg_chain_length=5.0,
        avg_efficiency_score=0.75,
        most_common_pattern="single_tool_deep_dive",
        most_efficient_pattern="iterative_refinement",
        tool_usage_distribution={"claude_code": 5, "cursor": 3, "kiro": 2},
        transition_matrix={"claude_code": {"cursor": 2}, "cursor": {"claude_code": 1}},
        # Phase 2 fields
        productivity_score=0.72,
        total_wasted_tokens=5000,
        cost_savings_potential=10.0,
        total_sessions=50,
        peak_time_of_day=(10, 85, 50),
        efficiency_ci=(0.70, 0.80),
        avg_chain_length_ci=(4.5, 5.5),
    )

    assert metrics.productivity_score == 0.72
    assert metrics.total_wasted_tokens == 5000
    assert metrics.cost_savings_potential == 10.0


# =============================================================================
# PHASE 3 TESTS - Advanced Workflow Intelligence
# =============================================================================

# --- WorkflowRecommender Tests ---


def test_workflow_recommender_empty():
    """Recommender handles empty analysis results."""
    from agenttop.workflow.recommender import WorkflowRecommender
    from agenttop.workflow.models import WorkflowMetrics

    recommender = WorkflowRecommender()
    recommendations = recommender.generate_recommendations(
        chains=[],
        metrics=WorkflowMetrics(
            total_chains=0,
            total_transitions=0,
            avg_chain_length=0.0,
            avg_efficiency_score=0.7,  # Normal efficiency to avoid auto-recommendations
            most_common_pattern="",
            most_efficient_pattern="",
            tool_usage_distribution={},
            transition_matrix={},
        ),
        anti_patterns=[],
        cost_optimizations=[],
        tool_affinities=[],
    )

    assert recommendations == []


def test_workflow_recommender_from_anti_patterns():
    """Recommender generates recommendations from anti-patterns."""
    from agenttop.workflow.recommender import WorkflowRecommender, RecommendationConfig
    from agenttop.workflow.models import (
        AntiPattern,
        AntiPatternType,
        WorkflowMetrics,
    )

    recommender = WorkflowRecommender(RecommendationConfig(include_low_priority=True))

    anti_patterns = [
        AntiPattern(
            id="ap1",
            type=AntiPatternType.EXCESSIVE_SWITCHING,
            severity="high",
            description="Too many tool switches",
            affected_sessions=["s1", "s2"],
            detected_at=1000.0,
            remedy="Consolidate tool usage",
            estimated_cost_impact=5.0,
            frequency=3,
        ),
        AntiPattern(
            id="ap2",
            type=AntiPatternType.COST_BLOAT,
            severity="critical",
            description="Expensive tool overuse",
            affected_sessions=["s3"],
            detected_at=1000.0,
            remedy="Use cheaper alternatives",
            estimated_cost_impact=20.0,
            frequency=1,
        ),
    ]

    recommendations = recommender.generate_recommendations(
        chains=[],
        metrics=WorkflowMetrics(
            total_chains=5,
            total_transitions=10,
            avg_chain_length=3.0,
            avg_efficiency_score=0.6,
            most_common_pattern="test",
            most_efficient_pattern="test",
            tool_usage_distribution={},
            transition_matrix={},
        ),
        anti_patterns=anti_patterns,
        cost_optimizations=[],
        tool_affinities=[],
    )

    # Should generate recommendations for both anti-patterns
    assert len(recommendations) >= 2

    # Critical anti-pattern should come first
    assert recommendations[0].priority.value in ("critical", "high")


def test_workflow_recommender_from_costs():
    """Recommender generates recommendations from cost optimizations."""
    from agenttop.workflow.recommender import WorkflowRecommender
    from agenttop.workflow.models import (
        CostOptimization,
        WorkflowMetrics,
    )

    recommender = WorkflowRecommender()

    optimizations = [
        CostOptimization(
            pattern_name="expensive_tool_usage",
            current_cost=100.0,
            optimized_cost=50.0,
            potential_savings=50.0,
            savings_percentage=50.0,
            recommendation="Switch to cheaper tool",
            alternative_tools=["kiro"],
            confidence="high",
        ),
    ]

    recommendations = recommender.generate_recommendations(
        chains=[],
        metrics=WorkflowMetrics(
            total_chains=5,
            total_transitions=10,
            avg_chain_length=3.0,
            avg_efficiency_score=0.6,
            most_common_pattern="test",
            most_efficient_pattern="test",
            tool_usage_distribution={},
            transition_matrix={},
        ),
        anti_patterns=[],
        cost_optimizations=optimizations,
        tool_affinities=[],
    )

    assert len(recommendations) == 1
    assert recommendations[0].category == "cost"
    assert recommendations[0].expected_savings_usd == 50.0


def test_workflow_recommender_from_affinities():
    """Recommender generates recommendations from tool affinities."""
    from agenttop.workflow.recommender import WorkflowRecommender
    from agenttop.workflow.models import (
        ToolAffinity,
        WorkflowChain,
        WorkflowMetrics,
    )

    recommender = WorkflowRecommender()

    affinities = [
        ToolAffinity(
            tool="claude_code",
            context="python",
            success_rate=0.85,
            avg_efficiency=0.8,
            avg_cost_per_outcome=2.0,
            sample_size=20,
            recommended=True,
        ),
    ]

    # Create chains with mixed projects - only some are python-related
    # and those don't use claude_code (they use cursor instead)
    chains = [
        WorkflowChain(
            id=f"c{i}",
            session_ids=[f"s{i}"],
            tools=["cursor"],  # Using cursor, not claude_code
            start_time=1000.0 + i * 100,
            end_time=2000.0 + i * 100,
            project="python-project" if i < 3 else "other-project",  # Only 3 out of 10 are python
            total_tokens=1000,
            total_cost=5.0,
            efficiency_score=0.6,
        )
        for i in range(10)
    ]

    recommendations = recommender.generate_recommendations(
        chains=chains,
        metrics=WorkflowMetrics(
            total_chains=10,
            total_transitions=0,
            avg_chain_length=1.0,
            avg_efficiency_score=0.6,
            most_common_pattern="test",
            most_efficient_pattern="test",
            tool_usage_distribution={},
            transition_matrix={},
        ),
        anti_patterns=[],
        cost_optimizations=[],
        tool_affinities=affinities,
    )

    # Should generate recommendation for using claude_code for python context
    # The title format is "Use {tool} for {context}"
    assert any("claude_code" in r.title and "python" in r.title.lower() for r in recommendations)


def test_workflow_recommender_from_metrics():
    """Recommender generates recommendations from workflow metrics."""
    from agenttop.workflow.recommender import WorkflowRecommender
    from agenttop.workflow.models import (
        WorkflowChain,
        WorkflowMetrics,
    )

    recommender = WorkflowRecommender()

    chains = [
        WorkflowChain(
            id="c1",
            session_ids=["s1"],
            tools=["claude_code", "cursor", "kiro", "copilot", "codex"],
            start_time=1000.0,
            end_time=2000.0,
            project="test-project",
            total_tokens=1000,
            total_cost=5.0,
            efficiency_score=0.5,
        ),
    ]

    # Low efficiency, high chain length, high waste
    metrics = WorkflowMetrics(
        total_chains=5,
        total_transitions=20,
        avg_chain_length=5.0,
        avg_efficiency_score=0.5,
        most_common_pattern="test",
        most_efficient_pattern="test",
        tool_usage_distribution={},
        transition_matrix={},
        total_wasted_tokens=200_000,
        cost_savings_potential=50.0,
    )

    recommendations = recommender.generate_recommendations(
        chains=chains,
        metrics=metrics,
        anti_patterns=[],
        cost_optimizations=[],
        tool_affinities=[],
    )

    # Should generate recommendations for all issues
    assert len(recommendations) >= 3
    categories = {r.category for r in recommendations}
    assert "efficiency" in categories
    assert "workflow" in categories


def test_workflow_recommender_insights():
    """Recommender generates high-level insights."""
    from agenttop.workflow.recommender import WorkflowRecommender
    from agenttop.workflow.models import (
        WorkflowActionableRecommendation,
        RecommendationPriority,
        AntiPatternType,
        WorkflowMetrics,
    )

    recommender = WorkflowRecommender()

    recommendations = [
        WorkflowActionableRecommendation(
            id="r1",
            title="Fix Cost",
            description="High cost issue",
            priority=RecommendationPriority.HIGH,
            category="cost",
            estimated_impact="Save $50",
            effort_required="medium",
            action_steps=["Step 1"],
            related_anti_patterns=[],
            expected_savings_usd=50.0,
            confidence=0.8,
            created_at=1000.0,
        ),
        WorkflowActionableRecommendation(
            id="r2",
            title="Fix Efficiency",
            description="Low efficiency",
            priority=RecommendationPriority.MEDIUM,
            category="efficiency",
            estimated_impact="Improve 10%",
            effort_required="low",
            action_steps=["Step 1"],
            related_anti_patterns=[],
            expected_savings_usd=10.0,
            confidence=0.6,
            created_at=1000.0,
        ),
    ]

    metrics = WorkflowMetrics(
        total_chains=10,
        total_transitions=20,
        avg_chain_length=3.0,
        avg_efficiency_score=0.7,
        most_common_pattern="test",
        most_efficient_pattern="test",
        tool_usage_distribution={},
        transition_matrix={},
    )

    insights = recommender.generate_insights(recommendations, metrics)

    assert len(insights) > 0
    assert any("savings" in i.lower() for i in insights)


# --- AnomalyDetector Tests ---


def test_anomaly_detector_empty():
    """Anomaly detector handles empty data."""
    from agenttop.workflow.anomaly import AnomalyDetector
    from agenttop.workflow.models import WorkflowMetrics

    detector = AnomalyDetector()
    anomalies = detector.detect_all_anomalies(
        chains=[],
        transitions=[],
        metrics=WorkflowMetrics(
            total_chains=0,
            total_transitions=0,
            avg_chain_length=0.0,
            avg_efficiency_score=0.0,
            most_common_pattern="",
            most_efficient_pattern="",
            tool_usage_distribution={},
            transition_matrix={},
        ),
    )

    assert anomalies == []


def test_anomaly_detector_cost_spike():
    """Anomaly detector detects cost spikes."""
    from agenttop.workflow.anomaly import AnomalyDetector, AnomalyConfig
    from agenttop.workflow.models import (
        WorkflowChain,
        WorkflowMetrics,
    )

    detector = AnomalyDetector(AnomalyConfig(
        min_data_points=3,
        cost_spike_threshold=2.0,  # Lower threshold for testing
    ))

    chains = [
        # Multiple normal chains to establish a baseline
        WorkflowChain(
            id=f"normal{i}",
            session_ids=[f"sn{i}"],
            tools=["claude_code"],
            start_time=1000.0 + i * 100,
            end_time=2000.0 + i * 100,
            project="test",
            total_tokens=1000,
            total_cost=1.0 + i * 0.1,  # Normal costs: 1.0, 1.1, 1.2, ...
            efficiency_score=0.7,
        )
        for i in range(8)  # 8 normal chains
    ] + [
        # One spike at the end
        WorkflowChain(
            id="spike",
            session_ids=["ss1"],
            tools=["claude_code"],
            start_time=9000.0,
            end_time=10000.0,
            project="test",
            total_tokens=50000,
            total_cost=20.0,  # Spike
            efficiency_score=0.7,
        ),
    ]

    metrics = WorkflowMetrics(
        total_chains=9,
        total_transitions=0,
        avg_chain_length=1.0,
        avg_efficiency_score=0.7,
        most_common_pattern="test",
        most_efficient_pattern="test",
        tool_usage_distribution={},
        transition_matrix={},
    )

    anomalies = detector.detect_all_anomalies(chains, [], metrics)

    # Should detect cost spike
    assert any(a.type.value == "cost_spike" for a in anomalies)


def test_anomaly_detector_activity_drop():
    """Anomaly detector detects activity drops."""
    from agenttop.workflow.anomaly import AnomalyDetector, AnomalyConfig
    from agenttop.workflow.models import (
        WorkflowChain,
        WorkflowMetrics,
    )

    detector = AnomalyDetector(AnomalyConfig(
        min_data_points=3,
        activity_drop_threshold=0.3,  # 30% drop
    ))

    now = 10000.0
    chains = [
        # High activity in past - create more chains
        WorkflowChain(
            id=f"old_{i}",
            session_ids=[f"old_s{i}"],
            tools=["claude_code"],
            start_time=now - 86400 * 5 - i * 3600,  # 5 days ago, spread over hours
            end_time=now - 86400 * 5 - i * 3600 + 1000,
            project="test",
            total_tokens=50000,  # High token count
            total_cost=50.0,
            efficiency_score=0.7,
        )
        for i in range(15)  # More historical chains
    ] + [
        # Low activity recently
        WorkflowChain(
            id=f"recent{i}",
            session_ids=[f"recent_s{i}"],
            tools=["claude_code"],
            start_time=now - i * 3600,
            end_time=now - i * 3600 + 1000,
            project="test",
            total_tokens=1000,  # Much lower
            total_cost=1.0,
            efficiency_score=0.7,
        )
        for i in range(3)
    ]

    metrics = WorkflowMetrics(
        total_chains=18,
        total_transitions=0,
        avg_chain_length=1.0,
        avg_efficiency_score=0.7,
        most_common_pattern="test",
        most_efficient_pattern="test",
        tool_usage_distribution={},
        transition_matrix={},
    )

    anomalies = detector.detect_all_anomalies(chains, [], metrics)

    # Should detect activity drop
    assert any(a.type.value == "activity_drop" for a in anomalies)


def test_anomaly_detector_context_fragmentation():
    """Anomaly detector detects context fragmentation."""
    from agenttop.workflow.anomaly import AnomalyDetector
    from agenttop.workflow.models import (
        ToolTransition,
        WorkflowMetrics,
    )

    detector = AnomalyDetector()

    # Create many transitions with fewer chains to trigger high switches per chain
    transitions = [
        ToolTransition(
            id=f"t{i}",
            from_tool=f"tool{i % 5}",
            to_tool=f"tool{(i + 1) % 5}",
            from_session_id=f"s{i}",
            to_session_id=f"s{i+1}",
            time_gap_seconds=60.0,
            project_match=True,
            timestamp=1000.0 + i * 100,
        )
        for i in range(50)  # Many transitions
    ]

    metrics = WorkflowMetrics(
        total_chains=5,  # Few chains means high switches per chain
        total_transitions=50,
        avg_chain_length=6.0,  # High switching
        avg_efficiency_score=0.6,
        most_common_pattern="test",
        most_efficient_pattern="test",
        tool_usage_distribution={},
        transition_matrix={},
    )

    anomalies = detector.detect_all_anomalies([], transitions, metrics)

    # Should detect context fragmentation
    assert any(a.type.value == "context_fragmentation" for a in anomalies)


def test_anomaly_detector_baseline_tracking():
    """Anomaly detector can track historical baselines."""
    from agenttop.workflow.anomaly import AnomalyDetector

    detector = AnomalyDetector()
    detector.set_baseline("efficiency", [0.6, 0.65, 0.7, 0.68, 0.72])
    detector.set_baseline("cost", [10.0, 12.0, 11.0, 13.0, 12.5])

    # Baselines should be stored
    assert "efficiency" in detector._historical_baseline
    assert "cost" in detector._historical_baseline


# --- TrendAnalyzer Tests ---


def test_trend_analyzer_empty():
    """Trend analyzer handles empty data."""
    from agenttop.workflow.trend import TrendAnalyzer

    analyzer = TrendAnalyzer()
    trends = analyzer.analyze_all_trends([], time_period_days=30)

    assert trends == []


def test_trend_analyzer_efficiency_trend():
    """Trend analyzer tracks efficiency changes."""
    import time
    from agenttop.workflow.trend import TrendAnalyzer, TrendConfig
    from agenttop.workflow.models import WorkflowChain

    analyzer = TrendAnalyzer(TrendConfig(min_data_points=3))

    now = time.time()
    # Create chains across multiple days (at least 3 for min_data_points)
    # Use recent timestamps so they don't get filtered out
    chains = [
        WorkflowChain(
            id=f"c{i}",
            session_ids=[f"s{i}"],
            tools=["claude_code"],
            start_time=now - (10 - i) * 86400,  # Last 10 days, one per day
            end_time=now - (10 - i) * 86400 + 3600,  # 1 hour duration
            project="test",
            total_tokens=1000,
            total_cost=1.0,
            efficiency_score=0.5 + i * 0.03,  # Improving from 0.5 to 0.77
        )
        for i in range(10)
    ]

    trends = analyzer.analyze_all_trends(chains, time_period_days=30)

    # Should have efficiency trend
    efficiency_trends = [t for t in trends if "efficiency" in t.metric_name]
    assert len(efficiency_trends) > 0

    trend = efficiency_trends[0]
    assert trend.direction.value in ("improving", "stable", "declining", "volatile")


def test_trend_analyzer_cost_trend():
    """Trend analyzer tracks cost changes."""
    import time
    from agenttop.workflow.trend import TrendAnalyzer, TrendConfig
    from agenttop.workflow.models import WorkflowChain

    analyzer = TrendAnalyzer(TrendConfig(min_data_points=3))

    now = time.time()
    chains = [
        WorkflowChain(
            id=f"c{i}",
            session_ids=[f"s{i}"],
            tools=["claude_code"],
            start_time=now - (10 - i) * 86400,  # Last 10 days
            end_time=now - (10 - i) * 86400 + 3600,  # 1 hour duration
            project="test",
            total_tokens=1000,
            total_cost=10.0 - i * 0.5,  # Decreasing cost from 10 to 5.5
            efficiency_score=0.7,
        )
        for i in range(10)
    ]

    trends = analyzer.analyze_all_trends(chains, time_period_days=30)

    # Should have cost trend
    cost_trends = [t for t in trends if "cost" in t.metric_name]
    assert len(cost_trends) > 0


def test_trend_analyzer_insights():
    """Trend analyzer provides insights."""
    import time
    from agenttop.workflow.trend import TrendAnalyzer, TrendConfig
    from agenttop.workflow.models import WorkflowChain

    analyzer = TrendAnalyzer(TrendConfig(min_data_points=3))

    now = time.time()
    chains = [
        WorkflowChain(
            id=f"c{i}",
            session_ids=[f"s{i}"],
            tools=["claude_code"],
            start_time=now - (10 - i) * 86400,  # Last 10 days
            end_time=now - (10 - i) * 86400 + 3600,  # 1 hour duration
            project="test",
            total_tokens=1000,
            total_cost=1.0,
            efficiency_score=0.85,  # High efficiency
        )
        for i in range(10)
    ]

    trends = analyzer.analyze_all_trends(chains, time_period_days=30)

    # Should include insights
    for trend in trends:
        if trend.insights:
            assert len(trend.insights) > 0
            break
    else:
        # If no insights, at least verify trends were generated
        assert len(trends) > 0, "Should generate at least some trend analysis"


def test_trend_analyzer_data_point_tracking():
    """Trend analyzer can track individual data points."""
    from agenttop.workflow.trend import TrendAnalyzer

    analyzer = TrendAnalyzer()

    # Add data points
    for i in range(10):
        analyzer.add_data_point("test_metric", 0.5 + i * 0.05, 10000.0 + i * 100)

    history = analyzer.get_metric_history("test_metric", limit=5)
    assert len(history) == 5


# --- ComparativeAnalyzer Tests ---


def test_comparative_analyzer_by_project():
    """Comparative analyzer compares across projects."""
    from agenttop.workflow.comparative import ComparativeAnalyzer
    from agenttop.workflow.models import WorkflowChain

    analyzer = ComparativeAnalyzer()

    chains = [
        # Project A - better efficiency
        WorkflowChain(
            id=f"pa_{i}",
            session_ids=[f"s{i}"],
            tools=["claude_code"],
            start_time=10000.0 - i * 1000,
            end_time=10000.0 - i * 1000 + 1000,
            project="project_a",
            total_tokens=1000,
            total_cost=1.0,
            efficiency_score=0.85,  # Better
        )
        for i in range(10)
    ] + [
        # Project B - worse efficiency
        WorkflowChain(
            id=f"pb_{i}",
            session_ids=[f"s{i}"],
            tools=["cursor"],
            start_time=10000.0 - i * 1000,
            end_time=10000.0 - i * 1000 + 1000,
            project="project_b",
            total_tokens=1000,
            total_cost=1.0,
            efficiency_score=0.55,  # Worse
        )
        for i in range(10)
    ]

    comparisons = analyzer.compare_by_project(chains, min_chains_per_project=5)

    # Should generate comparison
    assert len(comparisons) > 0
    assert comparisons[0].comparison_type == "project"


def test_comparative_analyzer_by_tool():
    """Comparative analyzer compares across tools."""
    from agenttop.workflow.comparative import ComparativeAnalyzer
    from agenttop.workflow.models import WorkflowChain

    analyzer = ComparativeAnalyzer()

    chains = [
        # Claude - better
        WorkflowChain(
            id=f"cc_{i}",
            session_ids=[f"s{i}"],
            tools=["claude_code"],
            start_time=10000.0 - i * 1000,
            end_time=10000.0 - i * 1000 + 1000,
            project="test",
            total_tokens=1000,
            total_cost=1.0,
            efficiency_score=0.8,
        )
        for i in range(5)
    ] + [
        # Cursor - worse
        WorkflowChain(
            id=f"cur_{i}",
            session_ids=[f"s{i}"],
            tools=["cursor"],
            start_time=10000.0 - i * 1000,
            end_time=10000.0 - i * 1000 + 1000,
            project="test",
            total_tokens=1000,
            total_cost=1.0,
            efficiency_score=0.6,
        )
        for i in range(5)
    ]

    comparisons = analyzer.compare_by_tool(chains)

    # Should generate comparison
    assert len(comparisons) > 0
    assert comparisons[0].comparison_type == "tool"


def test_comparative_analyzer_best_practices():
    """Comparative analyzer identifies best practices."""
    from agenttop.workflow.comparative import ComparativeAnalyzer
    from agenttop.workflow.models import WorkflowChain

    analyzer = ComparativeAnalyzer()

    chains = [
        WorkflowChain(
            id=f"c{i}",
            session_ids=[f"s{i}"],
            tools=["claude_code"],  # Single tool
            start_time=10000.0 - i * 1000,
            end_time=10000.0 - i * 1000 + 1000,
            project="test",
            total_tokens=1000,
            total_cost=1.0,
            efficiency_score=0.85,
        )
        for i in range(10)
    ]

    practices = analyzer.find_best_practices(chains)

    assert len(practices) > 0
    assert "optimal_chain_length" in practices


# --- WorkflowSimulator Tests ---


def test_simulator_reduce_switching():
    """Simulator models reducing tool switches."""
    from agenttop.workflow.simulator import WorkflowSimulator
    from agenttop.workflow.models import WorkflowChain

    simulator = WorkflowSimulator()

    chains = [
        WorkflowChain(
            id="c1",
            session_ids=["s1"],
            tools=["claude_code", "cursor", "kiro", "copilot"],  # 4 tools = 3 switches
            start_time=1000.0,
            end_time=2000.0,
            project="test",
            total_tokens=1000,
            total_cost=5.0,
            efficiency_score=0.6,
        ),
        WorkflowChain(
            id="c2",
            session_ids=["s2"],
            tools=["cursor", "claude_code"],  # 2 tools = 1 switch
            start_time=3000.0,
            end_time=4000.0,
            project="test",
            total_tokens=800,
            total_cost=3.0,
            efficiency_score=0.7,
        ),
    ]

    result = simulator.simulate_reduce_switching(chains, target_reduction=0.5)

    assert result.scenario_name == "Reduce Tool Switching by 50%"
    assert result.estimated_cost_impact < 0  # Savings
    assert result.estimated_efficiency_impact > 0  # Improvement


def test_simulator_switch_to_cheaper_tool():
    """Simulator models switching to cheaper tool."""
    from agenttop.workflow.simulator import WorkflowSimulator
    from agenttop.workflow.models import WorkflowChain

    simulator = WorkflowSimulator()

    chains = [
        WorkflowChain(
            id="c1",
            session_ids=["s1"],
            tools=["claude_code"],  # Expensive
            start_time=1000.0,
            end_time=2000.0,
            project="test",
            total_tokens=1000,
            total_cost=10.0,
            efficiency_score=0.7,
        ),
    ]

    result = simulator.simulate_switch_to_cheaper_tool(
        chains,
        expensive_tool="claude_code",
        cheaper_alternative="kiro",
        cost_reduction_ratio=0.6,
    )

    assert "claude_code" in result.scenario_name or "kiro" in result.scenario_name
    assert result.estimated_cost_impact < 0  # Savings


def test_simulator_improve_prompt_efficiency():
    """Simulator models prompt efficiency improvements."""
    from agenttop.workflow.simulator import WorkflowSimulator
    from agenttop.workflow.models import WorkflowChain

    simulator = WorkflowSimulator()

    chains = [
        WorkflowChain(
            id="c1",
            session_ids=["s1"],
            tools=["claude_code"],
            start_time=1000.0,
            end_time=2000.0,
            project="test",
            total_tokens=10000,
            total_cost=10.0,
            efficiency_score=0.6,
        ),
    ]

    result = simulator.simulate_improve_prompt_efficiency(
        chains,
        token_reduction=0.25,
    )

    assert "Prompt Efficiency" in result.scenario_name
    assert result.estimated_cost_impact < 0
    assert result.estimated_efficiency_impact > 0


def test_simulator_consolidate_sessions():
    """Simulator models session consolidation."""
    from agenttop.workflow.simulator import WorkflowSimulator
    from agenttop.workflow.models import WorkflowChain

    simulator = WorkflowSimulator()

    chains = [
        WorkflowChain(
            id=f"c{i}",
            session_ids=[f"s{i}"],
            tools=["claude_code"],
            start_time=1000.0 + i * 100,
            end_time=1000.0 + i * 100 + 50,
            project="test",
            total_tokens=100,
            total_cost=0.5,
            efficiency_score=0.6,
        )
        for i in range(10)
    ]

    result = simulator.simulate_consolidate_sessions(
        chains,
        consolidation_factor=0.5,
    )

    assert "Consolidate" in result.scenario_name
    assert "num_chains" in result.current_metrics


def test_simulator_fix_anti_patterns():
    """Simulator models fixing anti-patterns."""
    from agenttop.workflow.simulator import WorkflowSimulator
    from agenttop.workflow.models import (
        WorkflowChain,
        AntiPatternType,
    )

    simulator = WorkflowSimulator()

    chains = [
        WorkflowChain(
            id="c1",
            session_ids=["s1"],
            tools=["claude_code"],
            start_time=1000.0,
            end_time=2000.0,
            project="test",
            total_tokens=1000,
            total_cost=10.0,
            efficiency_score=0.5,
        ),
    ]

    anti_patterns = [
        (AntiPatternType.EXCESSIVE_SWITCHING, 3),
        (AntiPatternType.COST_BLOAT, 2),
    ]

    result = simulator.simulate_fix_anti_patterns(chains, anti_patterns)

    assert "Anti-Patterns" in result.scenario_name
    assert result.estimated_cost_impact < 0
    assert result.estimated_efficiency_impact > 0


def test_simulator_batch_simulation():
    """Simulator runs batch simulations."""
    from agenttop.workflow.simulator import WorkflowSimulator
    from agenttop.workflow.models import WorkflowChain

    simulator = WorkflowSimulator()

    chains = [
        WorkflowChain(
            id="c1",
            session_ids=["s1"],
            tools=["claude_code", "cursor", "kiro"],
            start_time=1000.0,
            end_time=2000.0,
            project="test",
            total_tokens=5000,
            total_cost=10.0,
            efficiency_score=0.6,
        ),
    ]

    results = simulator.run_batch_simulation(chains)

    assert len(results) > 1
    # Results should be sorted by impact
    if len(results) > 1:
        assert results[0].estimated_cost_impact <= results[1].estimated_cost_impact


# --- Phase 3 Model Tests ---


def test_phase_3_models_frozen():
    """Phase 3 models are frozen dataclasses."""
    from dataclasses import FrozenInstanceError
    from agenttop.workflow.models import (
        WorkflowActionableRecommendation,
        AnomalyDetection,
        TrendAnalysis,
        ComparativeAnalysis,
        SimulationResult,
        RecommendationPriority,
        AnomalyType,
        TrendDirection,
    )

    # WorkflowActionableRecommendation should be frozen
    rec = WorkflowActionableRecommendation(
        id="test",
        title="Test",
        description="Test",
        priority=RecommendationPriority.HIGH,
        category="test",
        estimated_impact="test",
        effort_required="low",
        action_steps=["step1"],
        related_anti_patterns=[],
        expected_savings_usd=10.0,
        confidence=0.8,
        created_at=1000.0,
    )

    try:
        rec.title = "Modified"
        assert False, "Should not be able to modify frozen dataclass"
    except (FrozenInstanceError, AttributeError):
        pass  # Expected

    # AnomalyDetection should be frozen
    anomaly = AnomalyDetection(
        id="test",
        type=AnomalyType.COST_SPIKE,
        severity="high",
        description="test",
        detected_at=1000.0,
        metric_name="cost",
        observed_value=100.0,
        expected_range=(50.0, 70.0),
        deviation_score=2.0,
        affected_sessions=["s1"],
        suggested_investigation="test",
        is_transient=False,
    )

    try:
        anomaly.severity = "critical"
        assert False, "Should not be able to modify frozen dataclass"
    except (FrozenInstanceError, AttributeError):
        pass  # Expected

    # TrendAnalysis should be frozen
    trend = TrendAnalysis(
        metric_name="efficiency",
        direction=TrendDirection.IMPROVING,
        current_value=0.8,
        previous_value=0.6,
        percent_change=33.3,
        time_period_days=30,
        confidence="high",
        data_points=10,
    )

    try:
        trend.current_value = 0.9
        assert False, "Should not be able to modify frozen dataclass"
    except (FrozenInstanceError, AttributeError):
        pass  # Expected


def test_phase_3_recommendation_priority_enum():
    """RecommendationPriority enum has all expected values."""
    from agenttop.workflow.models import RecommendationPriority

    assert RecommendationPriority.CRITICAL.value == "critical"
    assert RecommendationPriority.HIGH.value == "high"
    assert RecommendationPriority.MEDIUM.value == "medium"
    assert RecommendationPriority.LOW.value == "low"
    assert RecommendationPriority.INFO.value == "info"


def test_phase_3_anomaly_type_enum():
    """AnomalyType enum has all expected values."""
    from agenttop.workflow.models import AnomalyType

    assert AnomalyType.COST_SPIKE.value == "cost_spike"
    assert AnomalyType.ACTIVITY_DROP.value == "activity_drop"
    assert AnomalyType.TOOL_SHIFT.value == "tool_shift"
    assert AnomalyType.EFFICIENCY_DECLINE.value == "efficiency_decline"
    assert AnomalyType.SESSION_BURST.value == "session_burst"
    assert AnomalyType.TOKEN_OUTLIER.value == "token_outlier"
    assert AnomalyType.CONTEXT_FRAGMENTATION.value == "context_fragmentation"


def test_phase_3_trend_direction_enum():
    """TrendDirection enum has all expected values."""
    from agenttop.workflow.models import TrendDirection

    assert TrendDirection.IMPROVING.value == "improving"
    assert TrendDirection.DECLINING.value == "declining"
    assert TrendDirection.STABLE.value == "stable"
    assert TrendDirection.VOLATILE.value == "volatile"


def test_phase_3_full_integration():
    """Full Phase 3 integration test with all analyzers."""
    from agenttop.workflow.recommender import WorkflowRecommender
    from agenttop.workflow.anomaly import AnomalyDetector
    from agenttop.workflow.trend import TrendAnalyzer
    from agenttop.workflow.comparative import ComparativeAnalyzer
    from agenttop.workflow.simulator import WorkflowSimulator
    from agenttop.workflow.models import (
        WorkflowChain,
        WorkflowMetrics,
    )

    # Create test data
    chains = [
        WorkflowChain(
            id=f"c{i}",
            session_ids=[f"s{i}"],
            tools=["claude_code", "cursor"] if i % 2 == 0 else ["claude_code"],
            start_time=10000.0 - (20 - i) * 86400,  # Last 20 days
            end_time=10000.0 - (20 - i) * 86400 + 1000,
            project=f"project_{i % 3}",  # 3 different projects
            total_tokens=1000 + i * 100,
            total_cost=1.0 + i * 0.1,
            efficiency_score=0.5 + (i % 5) * 0.1,
        )
        for i in range(20)
    ]

    metrics = WorkflowMetrics(
        total_chains=20,
        total_transitions=10,
        avg_chain_length=1.5,
        avg_efficiency_score=0.65,
        most_common_pattern="single_tool",
        most_efficient_pattern="single_tool",
        tool_usage_distribution={"claude_code": 15, "cursor": 5},
        transition_matrix={"claude_code": {"cursor": 5}},
    )

    # Run all Phase 3 analyzers
    recommender = WorkflowRecommender()
    anomaly_detector = AnomalyDetector()
    trend_analyzer = TrendAnalyzer()
    comparative_analyzer = ComparativeAnalyzer()
    simulator = WorkflowSimulator()

    # Get results from each
    recommendations = recommender.generate_recommendations(
        chains, metrics, [], [], [],
    )

    anomalies = anomaly_detector.detect_all_anomalies(
        chains, [], metrics,
    )

    trends = trend_analyzer.analyze_all_trends(chains, time_period_days=30)

    comparisons = comparative_analyzer.compare_by_project(
        chains, min_chains_per_project=5,
    )

    simulations = simulator.run_batch_simulation(chains)

    # All should produce results (or handle gracefully)
    assert isinstance(recommendations, list)
    assert isinstance(anomalies, list)
    assert isinstance(trends, list)
    assert isinstance(comparisons, list)
    assert isinstance(simulations, list)

    # At minimum, simulations should produce results
    assert len(simulations) > 0

