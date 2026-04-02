"""Cross-tool workflow intelligence module.

This module provides analysis of how developers use multiple AI coding tools
throughout their workday, identifying optimal tool combinations for different
task types and suggesting workflow improvements.

Key components:
- SessionCorrelator: Groups sessions across tools by time and project proximity
- WorkflowAnalyzer: Analyzes workflow patterns and calculates efficiency
- WorkflowPatternDetector: Detects and classifies common workflow patterns
- AntiPatternDetector: Detects harmful workflow patterns (Phase 2)
- ToolAffinityAnalyzer: Analyzes which tools work best for which contexts (Phase 2)
- CostOptimizer: Identifies cost optimization opportunities (Phase 2)
- WorkflowPredictor: Predicts next likely tool/action (Phase 2)
- ProductivityScorer: Calculates composite productivity scores (Phase 2)
- WorkflowRecommender: Generates actionable recommendations (Phase 3)
- AnomalyDetector: Detects unusual patterns and outliers (Phase 3)
- TrendAnalyzer: Tracks metric changes over time (Phase 3)
- ComparativeAnalyzer: Compares workflows across dimensions (Phase 3)
- WorkflowSimulator: What-if scenario modeling (Phase 3)
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

from agenttop.workflow.affinity import ToolAffinityAnalyzer
from agenttop.workflow.anti_patterns import AntiPatternDetector
from agenttop.workflow.analyzer import WorkflowAnalyzer
from agenttop.workflow.anomaly import AnomalyDetector
from agenttop.workflow.comparative import ComparativeAnalyzer
from agenttop.workflow.constants import WORKFLOW_INTERVALS, all_timezones
from agenttop.workflow.correlator import SessionCorrelator
from agenttop.workflow.cost_optimizer import CostOptimizer
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
    AnomalyDetection,
    AnomalyType,
    AntiPattern,
    AntiPatternType,
    ComparativeAnalysis,
    CostOptimization,
    RecommendationPriority,
    SimulationResult,
    SwitchingCost,
    TrendAnalysis,
    TrendDirection,
    ToolAffinity,
    ToolTransition,
    ToolType,
    WorkflowActionableRecommendation,
    WorkflowChain,
    WorkflowInsight,
    WorkflowMetrics,
    WorkflowPattern,
    WorkflowPrediction,
    WorkflowRecommendation,
)
from agenttop.workflow.patterns import WorkflowPatternDetector
from agenttop.workflow.prediction import WorkflowPredictor
from agenttop.workflow.productivity import ProductivityScorer, ProductivityFactors
from agenttop.workflow.recommender import WorkflowRecommender
from agenttop.workflow.simulator import WorkflowSimulator
from agenttop.workflow.trend import TrendAnalyzer

__all__ = [
    # Main classes
    "SessionCorrelator",
    "WorkflowAnalyzer",
    "WorkflowPatternDetector",
    # Phase 2 classes
    "AntiPatternDetector",
    "ToolAffinityAnalyzer",
    "CostOptimizer",
    "WorkflowPredictor",
    "ProductivityScorer",
    "ProductivityFactors",
    # Phase 3 classes
    "WorkflowRecommender",
    "AnomalyDetector",
    "TrendAnalyzer",
    "ComparativeAnalyzer",
    "WorkflowSimulator",
    # Models
    "ToolType",
    "WorkflowChain",
    "ToolTransition",
    "WorkflowPattern",
    "WorkflowRecommendation",
    "SwitchingCost",
    "WorkflowMetrics",
    # Phase 2 models
    "AntiPattern",
    "AntiPatternType",
    "ToolAffinity",
    "CostOptimization",
    "WorkflowPrediction",
    # Phase 3 models
    "RecommendationPriority",
    "AnomalyType",
    "TrendDirection",
    "WorkflowActionableRecommendation",
    "AnomalyDetection",
    "TrendAnalysis",
    "ComparativeAnalysis",
    "SimulationResult",
    "WorkflowInsight",
    # Knowledge base
    "TASK_TYPE_RECOMMENDATIONS",
    "SWITCHING_COSTS",
    "WORKFLOW_PATTERNS",
    "get_recommendation_for_task",
    "get_switching_cost",
    "get_pattern_info",
    "get_all_tool_names",
    "calculate_optimal_workflow",
    "WORKFLOW_INTERVALS",
    "all_timezones",
]
