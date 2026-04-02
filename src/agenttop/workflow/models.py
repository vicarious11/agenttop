"""Workflow intelligence models for cross-tool analysis."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum


class ToolType(str, Enum):
    """Supported AI coding tools."""
    CLAUDE_CODE = "claude_code"
    CURSOR = "cursor"
    KIRO = "kiro"
    COPILOT = "copilot"
    CODEX = "codex"
    AIDER = "aider"
    CONTINUE = "continue"
    GENERIC = "generic"


class AntiPatternType(str, Enum):
    """Types of workflow anti-patterns."""
    EXCESSIVE_SWITCHING = "excessive_switching"
    SPIRALING = "spiraling"
    CONTEXT_THRASHING = "context_thrashing"
    ABANDONED_SESSION = "abandoned_session"
    COST_BLOAT = "cost_bloat"
    TOKEN_INEFFICIENCY = "token_inefficiency"


@dataclass(frozen=True)
class WorkflowChain:
    """A sequence of correlated sessions across tools."""
    id: str
    session_ids: list[str]
    tools: list[str]
    start_time: float
    end_time: float
    project: str | None
    total_tokens: int
    total_cost: float
    efficiency_score: float | None = None  # 0.0 - 1.0
    pattern_type: str | None = None
    # Phase 1 additions
    session_start_times: list[float] = ()  # Individual session start times (hour of day analysis)
    momentum_score: float | None = None  # 0.0 - 1.0, how much sessions build on each other
    sample_size: int = 1  # Number of sessions in this chain

    def with_efficiency(self, score: float) -> "WorkflowChain":
        """Return a new chain with updated efficiency score."""
        return replace(self, efficiency_score=score)

    def with_pattern(self, pattern: str) -> "WorkflowChain":
        """Return a new chain with updated pattern type."""
        return replace(self, pattern_type=pattern)

    def with_momentum(self, score: float) -> "WorkflowChain":
        """Return a new chain with updated momentum score."""
        return replace(self, momentum_score=score)


@dataclass(frozen=True)
class ToolTransition:
    """A transition from one tool to another."""
    id: str
    from_tool: str
    to_tool: str
    from_session_id: str
    to_session_id: str
    time_gap_seconds: float
    project_match: bool
    timestamp: float
    context_preservation_score: float | None = None  # 0.0 - 1.0


@dataclass(frozen=True)
class WorkflowPattern:
    """A detected workflow pattern."""
    name: str
    description: str
    tool_sequence: list[str]
    frequency: int
    avg_efficiency: float
    avg_tokens: int
    avg_cost: float
    typical_duration_minutes: float = 0.0
    last_seen: float = 0.0
    # Phase 1 additions - confidence intervals and sample awareness
    efficiency_ci: tuple[float, float] | None = None  # 95% CI
    duration_ci: tuple[float, float] | None = None  # 95% CI
    sample_size: int = 1  # Number of chains detected with this pattern
    confidence: str = "low"  # "low", "medium", "high" based on sample size


@dataclass(frozen=True)
class WorkflowRecommendation:
    """A recommendation for workflow improvement."""
    task_type: str
    primary_tool: str
    secondary_tools: list[str]
    avoid_tools: list[str]
    rationale: str
    estimated_efficiency_gain: float


@dataclass(frozen=True)
class SwitchingCost:
    """Cost of switching between tools."""
    from_tool: str
    to_tool: str
    context_loss_score: float  # 0.0 - 1.0
    ramp_up_time_minutes: float
    mitigation_strategy: str


@dataclass(frozen=True)
class AntiPattern:
    """A detected workflow anti-pattern with severity and remedy."""
    id: str
    type: AntiPatternType
    severity: str  # "low", "medium", "high", "critical"
    description: str
    affected_sessions: list[str]  # Session IDs exhibiting this pattern
    detected_at: float  # Timestamp
    remedy: str
    estimated_cost_impact: float = 0.0  # USD cost of this anti-pattern
    frequency: int = 1  # How many times this pattern was detected


@dataclass(frozen=True)
class ToolAffinity:
    """Affinity/success rate of a tool for specific contexts."""
    tool: str
    context: str  # e.g., project type, time of day, task category
    success_rate: float  # 0.0 - 1.0
    avg_efficiency: float  # 0.0 - 1.0
    avg_cost_per_outcome: float
    sample_size: int
    recommended: bool = False  # Whether this tool is recommended for this context


@dataclass(frozen=True)
class WorkflowPrediction:
    """Prediction for next likely action/tool in workflow."""
    current_session_id: str
    predicted_next_tool: str | None
    confidence: float  # 0.0 - 1.0
    reasoning: str
    alternative_suggestions: list[str]
    based_on_pattern: str  # Name of pattern this prediction is based on


@dataclass(frozen=True)
class CostOptimization:
    """Cost optimization opportunity."""
    pattern_name: str
    current_cost: float
    optimized_cost: float
    potential_savings: float
    savings_percentage: float
    recommendation: str
    alternative_tools: list[str]
    confidence: str  # "low", "medium", "high" based on sample size


@dataclass(frozen=True)
class WorkflowMetrics:
    """Aggregated workflow metrics."""
    total_chains: int
    total_transitions: int
    avg_chain_length: float
    avg_efficiency_score: float
    most_common_pattern: str
    most_efficient_pattern: str
    tool_usage_distribution: dict[str, int]
    transition_matrix: dict[str, dict[str, int]]
    # Phase 1 additions - confidence intervals and sample sizes
    efficiency_ci: tuple[float, float] | None = None  # (lower, upper) 95% confidence interval
    avg_chain_length_ci: tuple[float, float] | None = None
    total_sessions: int = 0  # Total number of sessions analyzed
    peak_time_of_day: tuple[int, int, int] | None = None  # (hour, confidence, sample_size)
    # Phase 2 additions
    productivity_score: float = 0.5  # 0.0 - 1.0, composite productivity metric
    total_wasted_tokens: int = 0  # Tokens spent on inefficient patterns
    cost_savings_potential: float = 0.0  # Potential USD savings from optimization


# =============================================================================
# PHASE 3 MODELS - Advanced Workflow Intelligence
# =============================================================================


class RecommendationPriority(str, Enum):
    """Priority level for workflow recommendations."""
    CRITICAL = "critical"  # Immediate action required
    HIGH = "high"  # Significant impact
    MEDIUM = "medium"  # Moderate impact
    LOW = "low"  # Nice to have
    INFO = "info"  # Informational only


class AnomalyType(str, Enum):
    """Types of workflow anomalies."""
    COST_SPIKE = "cost_spike"  # Unusual cost increase
    ACTIVITY_DROP = "activity_drop"  # Sudden decrease in usage
    TOOL_SHIFT = "tool_shift"  # Unexpected change in tool preferences
    EFFICIENCY_DECLINE = "efficiency_decline"  # Decreasing efficiency over time
    SESSION_BURST = "session_burst"  # Unusually high session count
    TOKEN_OUTLIER = "token_outlier"  # Unusual token consumption
    CONTEXT_FRAGMENTATION = "context_fragmentation"  # Excessive tool switching


class TrendDirection(str, Enum):
    """Direction of a trend."""
    IMPROVING = "improving"  # Metrics getting better
    DECLINING = "declining"  # Metrics getting worse
    STABLE = "stable"  # No significant change
    VOLATILE = "volatile"  # Significant fluctuations


@dataclass(frozen=True)
class WorkflowActionableRecommendation:
    """An actionable recommendation for workflow improvement (Phase 3)."""
    id: str
    title: str
    description: str
    priority: RecommendationPriority
    category: str  # "cost", "efficiency", "workflow", "quality", "learning"
    estimated_impact: str  # Description of expected improvement
    effort_required: str  # "low", "medium", "high"
    action_steps: list[str]  # Concrete steps to implement
    related_anti_patterns: list[AntiPatternType]  # Connected anti-patterns
    expected_savings_usd: float = 0.0  # Estimated cost savings
    confidence: float = 0.5  # 0.0 - 1.0, confidence in recommendation
    created_at: float = 0.0  # Timestamp


@dataclass(frozen=True)
class AnomalyDetection:
    """A detected workflow anomaly (Phase 3)."""
    id: str
    type: AnomalyType
    severity: str  # "low", "medium", "high", "critical"
    description: str
    detected_at: float  # Timestamp
    metric_name: str  # Name of the metric that flagged this
    observed_value: float  # The actual value observed
    expected_range: tuple[float, float]  # Expected (min, max) range
    deviation_score: float  # How far from expected (0.0 - 1.0+)
    affected_sessions: list[str]  # Related session IDs
    suggested_investigation: str  # What to look into
    is_transient: bool = False  # True if likely temporary fluctuation


@dataclass(frozen=True)
class TrendAnalysis:
    """Analysis of metric trends over time (Phase 3)."""
    metric_name: str
    direction: TrendDirection
    current_value: float
    previous_value: float
    percent_change: float
    time_period_days: int
    confidence: str  # "low", "medium", "high" based on data sufficiency
    data_points: int  # Number of data points analyzed
    trend_line: list[tuple[float, float]] | None = None  # (timestamp, value) points
    seasonal_pattern: str | None = None  # Description of any seasonal pattern
    forecast: tuple[float, float] | None = None  # (predicted_value, confidence)
    insights: list[str] = ()  # Key insights about this trend


@dataclass(frozen=True)
class ComparativeAnalysis:
    """Comparison across different dimensions (Phase 3)."""
    comparison_type: str  # "project", "time_period", "tool", "user"
    baseline_name: str  # Name of baseline (e.g., "main project")
    comparison_name: str  # Name being compared (e.g., "side project")
    metric_comparisons: dict[str, tuple[float, float, str]]  # metric -> (baseline, comparison, status)
    # Status: "better", "worse", "similar"
    overall_assessment: str  # Summary of comparison
    key_differences: list[str]  # Notable differences
    recommendations: list[str]  # What to apply from one to the other
    confidence: str = "medium"  # Based on data quality and sample size
    created_at: float = 0.0


@dataclass(frozen=True)
class SimulationResult:
    """Result of a what-if simulation (Phase 3)."""
    scenario_name: str
    description: str
    current_metrics: dict[str, float]  # Current state metrics
    simulated_metrics: dict[str, float]  # Simulated state metrics
    changes: list[tuple[str, float, str]]  # (metric, change, direction)
    # Direction: "improvement", "decline", "no_change"
    estimated_cost_impact: float
    estimated_efficiency_impact: float
    assumptions: list[str]  # What the simulation assumes
    confidence: float  # 0.0 - 1.0
    risk_factors: list[str]  # Potential downsides


@dataclass(frozen=True)
class WorkflowInsight:
    """A high-level insight about workflow patterns (Phase 3)."""
    id: str
    category: str  # "strength", "weakness", "opportunity", "trend"
    title: str
    description: str
    supporting_metrics: dict[str, float]  # Metrics backing this insight
    confidence: float  # 0.0 - 1.0
    created_at: float
    related_recommendations: list[str]  # IDs of related recommendations
    time_sensitive: bool = False  # True if this insight changes frequently
