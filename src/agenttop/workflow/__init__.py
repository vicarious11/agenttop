"""Cross-tool workflow intelligence module.

This module provides analysis of how developers use multiple AI coding tools
throughout their workday, identifying optimal tool combinations for different
task types and suggesting workflow improvements.

Key components:
- SessionCorrelator: Groups sessions across tools by time and project proximity
- WorkflowAnalyzer: Analyzes workflow patterns and calculates efficiency
- WorkflowPatternDetector: Detects and classifies common workflow patterns
- Knowledge base: Task recommendations and switching costs

Usage:
    from agenttop.workflow import SessionCorrelator, WorkflowAnalyzer

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    analyzer = WorkflowAnalyzer()
    analysis = analyzer.analyze_chains(chains, transitions)
"""

from __future__ import annotations

from agenttop.workflow.analyzer import WorkflowAnalyzer
from agenttop.workflow.correlator import SessionCorrelator
from agenttop.workflow.knowledge_base import (
    SWITCHING_COSTS,
    TASK_TYPE_RECOMMENDATIONS,
    WORKFLOW_PATTERNS,
    calculate_optimal_workflow,
    get_all_tool_names,
    get_pattern_info,
    get_recommendation_for_task,
    get_switching_cost,
)
from agenttop.workflow.models import (
    SwitchingCost,
    ToolTransition,
    ToolType,
    WorkflowChain,
    WorkflowMetrics,
    WorkflowPattern,
    WorkflowRecommendation,
)
from agenttop.workflow.patterns import WorkflowPatternDetector

__all__ = [
    # Main classes
    "SessionCorrelator",
    "WorkflowAnalyzer",
    "WorkflowPatternDetector",
    # Models
    "ToolType",
    "WorkflowChain",
    "ToolTransition",
    "WorkflowPattern",
    "WorkflowRecommendation",
    "SwitchingCost",
    "WorkflowMetrics",
    # Knowledge base
    "TASK_TYPE_RECOMMENDATIONS",
    "SWITCHING_COSTS",
    "WORKFLOW_PATTERNS",
    "get_recommendation_for_task",
    "get_switching_cost",
    "get_pattern_info",
    "get_all_tool_names",
    "calculate_optimal_workflow",
]
