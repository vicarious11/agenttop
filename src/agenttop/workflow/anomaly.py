"""Anomaly detection for workflow patterns.

This module identifies unusual patterns, outliers, and unexpected changes
in workflow metrics that may indicate problems or opportunities.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, replace
from statistics import median, stdev
from typing import TYPE_CHECKING

from agenttop.workflow.models import (
    AnomalyDetection,
    AnomalyType,
    ToolTransition,
    WorkflowChain,
    WorkflowMetrics,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class AnomalyConfig:
    """Configuration for anomaly detection."""
    z_threshold: float = 2.5  # Standard deviations for anomaly
    min_data_points: int = 5  # Minimum data points for statistical analysis
    cost_spike_threshold: float = 3.0  # Multiplier for cost spikes
    activity_drop_threshold: float = 0.3  # 30% drop in activity
    token_outlier_threshold: float = 2.0  # Multiplier for token outliers
    enable_context_fragmentation: bool = True  # Detect excessive switching


class AnomalyDetector:
    """Detects anomalies and unusual patterns in workflow data.

    Uses statistical methods including:
    - Z-score analysis for outliers
    - Moving average comparisons for trends
    - Distribution analysis for unusual patterns
    """

    def __init__(self, config: AnomalyConfig | None = None) -> None:
        """Initialize the anomaly detector.

        Args:
            config: Configuration for detection thresholds
        """
        self._config = config or AnomalyConfig()
        self._historical_baseline: dict[str, list[float]] = defaultdict(list)

    def set_baseline(self, metric_name: str, values: list[float]) -> None:
        """Set historical baseline for a metric.

        Args:
            metric_name: Name of the metric
            values: Historical values for this metric
        """
        self._historical_baseline[metric_name] = values[-100:]  # Keep last 100

    def detect_all_anomalies(
        self,
        chains: Sequence[WorkflowChain],
        transitions: Sequence[ToolTransition],
        metrics: WorkflowMetrics,
    ) -> list[AnomalyDetection]:
        """Detect all types of anomalies in workflow data.

        Args:
            chains: Workflow chains to analyze
            transitions: Tool transitions to analyze
            metrics: Aggregate metrics

        Returns:
            List of detected anomalies
        """
        anomalies: list[AnomalyDetection] = []

        anomalies.extend(self._detect_cost_spikes(chains))
        anomalies.extend(self._detect_activity_drops(chains))
        anomalies.extend(self._detect_tool_shifts(chains))
        anomalies.extend(self._detect_efficiency_decline(chains))
        anomalies.extend(self._detect_session_bursts(chains))
        anomalies.extend(self._detect_token_outliers(chains))

        if self._config.enable_context_fragmentation:
            anomalies.extend(self._detect_context_fragmentation(transitions, metrics))

        return anomalies

    def _detect_cost_spikes(
        self, chains: Sequence[WorkflowChain],
    ) -> list[AnomalyDetection]:
        """Detect unusual cost increases."""
        if not chains:
            return []

        costs = [c.total_cost for c in chains]
        if len(costs) < self._config.min_data_points:
            return []

        mean_cost = sum(costs) / len(costs)
        if len(costs) < 2:
            return []

        try:
            cost_std = stdev(costs) if len(costs) > 1 else mean_cost * 0.2
        except statisticsError:
            cost_std = mean_cost * 0.2

        threshold = mean_cost + (self._config.cost_spike_threshold * cost_std)
        anomalies: list[AnomalyDetection] = []

        for chain in chains:
            if chain.total_cost > threshold:
                severity = self._calculate_severity(
                    chain.total_cost, mean_cost, threshold,
                )
                anomalies.append(AnomalyDetection(
                    id=f"cost_spike_{chain.id}",
                    type=AnomalyType.COST_SPIKE,
                    severity=severity,
                    description=f"Unusual cost spike of ${chain.total_cost:.2f} in workflow chain",
                    detected_at=time.time(),
                    metric_name="total_cost",
                    observed_value=chain.total_cost,
                    expected_range=(mean_cost * 0.5, mean_cost * 1.5),
                    deviation_score=(chain.total_cost - mean_cost) / cost_std if cost_std > 0 else 0,
                    affected_sessions=chain.session_ids,
                    suggested_investigation=(
                        f"Review session {chain.session_ids[0] if chain.session_ids else 'unknown'} "
                        f"for unusual token consumption or expensive tool usage"
                    ),
                    is_transient=False,
                ))

        return anomalies

    def _detect_activity_drops(
        self, chains: Sequence[WorkflowChain],
    ) -> list[AnomalyDetection]:
        """Detect sudden drops in activity."""
        if len(chains) < self._config.min_data_points:
            return []

        # Sort chains by start time
        sorted_chains = sorted(chains, key=lambda c: c.start_time)

        # Split into recent and historical
        mid_point = len(sorted_chains) // 2
        historical = sorted_chains[:mid_point]
        recent = sorted_chains[mid_point:]

        # Calculate activity metrics
        historical_activity = sum(c.total_tokens for c in historical)
        recent_activity = sum(c.total_tokens for c in recent)

        if historical_activity == 0:
            return []

        activity_ratio = recent_activity / historical_activity

        if activity_ratio < (1 - self._config.activity_drop_threshold):
            drop_percent = (1 - activity_ratio) * 100
            return [AnomalyDetection(
                id="activity_drop",
                type=AnomalyType.ACTIVITY_DROP,
                severity="medium" if drop_percent < 50 else "high",
                description=f"Activity dropped by {drop_percent:.1f}% in recent sessions",
                detected_at=time.time(),
                metric_name="activity_level",
                observed_value=recent_activity,
                expected_range=(
                    historical_activity * 0.8,
                    historical_activity * 1.2,
                ),
                deviation_score=1 - activity_ratio,
                affected_sessions=[c.id for c in recent],
                suggested_investigation=(
                    "Check for changes in work patterns, tool availability, "
                    "or project status"
                ),
                is_transient=True,
            )]

        return []

    def _detect_tool_shifts(
        self, chains: Sequence[WorkflowChain],
    ) -> list[AnomalyDetection]:
        """Detect unexpected changes in tool preferences."""
        if len(chains) < self._config.min_data_points * 2:
            return []

        sorted_chains = sorted(chains, key=lambda c: c.start_time)
        mid_point = len(sorted_chains) // 2

        historical_tools: list[str] = []
        for c in sorted_chains[:mid_point]:
            historical_tools.extend(c.tools)

        recent_tools: list[str] = []
        for c in sorted_chains[mid_point:]:
            recent_tools.extend(c.tools)

        # Calculate distribution
        from collections import Counter

        hist_dist = Counter(historical_tools)
        recent_dist = Counter(recent_tools)

        # Find significant shifts
        anomalies: list[AnomalyDetection] = []

        for tool in set(hist_dist.keys()) | set(recent_dist.keys()):
            hist_pct = hist_dist[tool] / len(historical_tools) if historical_tools else 0
            recent_pct = recent_dist[tool] / len(recent_tools) if recent_tools else 0
            change = recent_pct - hist_pct

            # Flag significant changes (>30% shift)
            if abs(change) > 0.3:
                direction = "increased" if change > 0 else "decreased"
                anomalies.append(AnomalyDetection(
                    id=f"tool_shift_{tool}",
                    type=AnomalyType.TOOL_SHIFT,
                    severity="low",
                    description=f"Usage of {tool} {direction} by {abs(change):.1%}",
                    detected_at=time.time(),
                    metric_name=f"tool_usage_{tool}",
                    observed_value=recent_pct,
                    expected_range=(hist_pct * 0.8, hist_pct * 1.2),
                    deviation_score=abs(change),
                    affected_sessions=[c.id for c in sorted_chains[mid_point:] if tool in c.tools],
                    suggested_investigation=(
                        f"Consider why {tool} usage has changed - "
                        f"new project requirements or tool capabilities?"
                    ),
                    is_transient=False,
                ))

        return anomalies

    def _detect_efficiency_decline(
        self, chains: Sequence[WorkflowChain],
    ) -> list[AnomalyDetection]:
        """Detect declining efficiency over time."""
        chains_with_eff = [c for c in chains if c.efficiency_score is not None]

        if len(chains_with_eff) < self._config.min_data_points:
            return []

        sorted_chains = sorted(chains_with_eff, key=lambda c: c.start_time)

        # Calculate moving average
        window = max(3, len(sorted_chains) // 4)
        recent_eff = [
            c.efficiency_score for c in sorted_chains[-window:]
            if c.efficiency_score is not None
        ]
        older_eff = [
            c.efficiency_score for c in sorted_chains[:-window]
            if c.efficiency_score is not None
        ]

        if not recent_eff or not older_eff:
            return []

        recent_avg = sum(recent_eff) / len(recent_eff)
        older_avg = sum(older_eff) / len(older_eff)

        decline = older_avg - recent_avg

        # Flag if decline is more than 15%
        if decline > 0.15:
            return [AnomalyDetection(
                id="efficiency_decline",
                type=AnomalyType.EFFICIENCY_DECLINE,
                severity="high" if decline > 0.3 else "medium",
                description=f"Efficiency declined by {decline:.1%} over time",
                detected_at=time.time(),
                metric_name="efficiency_score",
                observed_value=recent_avg,
                expected_range=(older_avg * 0.9, older_avg * 1.1),
                deviation_score=decline,
                affected_sessions=[c.id for c in sorted_chains[-window:]],
                suggested_investigation=(
                    "Review recent sessions for context loss, tool switching, "
                    "or task complexity changes"
                ),
                is_transient=False,
            )]

        return []

    def _detect_session_bursts(
        self, chains: Sequence[WorkflowChain],
    ) -> list[AnomalyDetection]:
        """Detect unusually high session activity in short time periods."""
        if len(chains) < self._config.min_data_points:
            return []

        # Group chains by time windows (1 hour)
        time_windows: defaultdict[float, list[WorkflowChain]] = defaultdict(list)

        for chain in chains:
            hour_window = math.floor(chain.start_time / 3600) * 3600
            time_windows[hour_window].append(chain)

        # Calculate statistics
        session_counts = [len(chains_list) for chains_list in time_windows.values()]

        if len(session_counts) < 3:
            return []

        mean_count = sum(session_counts) / len(session_counts)
        try:
            count_std = stdev(session_counts) if len(session_counts) > 1 else 1
        except Exception:
            count_std = 1

        threshold = mean_count + (2 * count_std)

        anomalies: list[AnomalyDetection] = []

        for window, window_chains in time_windows.items():
            if len(window_chains) > threshold:
                anomalies.append(AnomalyDetection(
                    id=f"session_burst_{int(window)}",
                    type=AnomalyType.SESSION_BURST,
                    severity="low",
                    description=f"Unusual burst of {len(window_chains)} sessions in one hour",
                    detected_at=time.time(),
                    metric_name="sessions_per_hour",
                    observed_value=float(len(window_chains)),
                    expected_range=(mean_count * 0.5, mean_count * 1.5),
                    deviation_score=(len(window_chains) - mean_count) / count_std if count_std > 0 else 0,
                    affected_sessions=[c.id for c in window_chains],
                    suggested_investigation=(
                        "May indicate fragmented work or trial-and-error approach. "
                        "Consider consolidating into longer, focused sessions."
                    ),
                    is_transient=True,
                ))

        return anomalies

    def _detect_token_outliers(
        self, chains: Sequence[WorkflowChain],
    ) -> list[AnomalyDetection]:
        """Detect unusual token consumption patterns."""
        if not chains:
            return []

        token_counts = [c.total_tokens for c in chains]

        if len(token_counts) < self._config.min_data_points:
            return []

        median_tokens = median(token_counts)
        # Use IQR method for outlier detection
        sorted_tokens = sorted(token_counts)
        q1_idx = len(sorted_tokens) // 4
        q3_idx = 3 * len(sorted_tokens) // 4
        q1 = sorted_tokens[q1_idx]
        q3 = sorted_tokens[q3_idx]
        iqr = q3 - q1

        if iqr == 0:
            return []

        upper_bound = q3 + (self._config.token_outlier_threshold * iqr)

        anomalies: list[AnomalyDetection] = []

        for chain in chains:
            if chain.total_tokens > upper_bound:
                anomalies.append(AnomalyDetection(
                    id=f"token_outlier_{chain.id}",
                    type=AnomalyType.TOKEN_OUTLIER,
                    severity="medium",
                    description=f"Unusually high token consumption: {chain.total_tokens:,} tokens",
                    detected_at=time.time(),
                    metric_name="total_tokens",
                    observed_value=float(chain.total_tokens),
                    expected_range=(float(q1), float(upper_bound)),
                    deviation_score=(chain.total_tokens - median_tokens) / iqr if iqr > 0 else 0,
                    affected_sessions=chain.session_ids,
                    suggested_investigation=(
                        "Review for: very large prompts, extensive context, "
                        "or repeated requests that could be consolidated"
                    ),
                    is_transient=False,
                ))

        return anomalies

    def _detect_context_fragmentation(
        self,
        transitions: Sequence[ToolTransition],
        metrics: WorkflowMetrics,
    ) -> list[AnomalyDetection]:
        """Detect excessive tool switching that fragments context."""
        if not transitions:
            return []

        # Calculate switching frequency
        total_switches = len(transitions)
        avg_switches_per_chain = (
            total_switches / metrics.total_chains
            if metrics.total_chains > 0 else 0
        )

        # Threshold: more than 5 switches per chain is excessive
        if avg_switches_per_chain > 5:
            severity = "high" if avg_switches_per_chain > 8 else "medium"

            return [AnomalyDetection(
                id="context_fragmentation",
                type=AnomalyType.CONTEXT_FRAGMENTATION,
                severity=severity,
                description=(
                    f"High context fragmentation: {avg_switches_per_chain:.1f} "
                    f"tool switches per workflow chain"
                ),
                detected_at=time.time(),
                metric_name="avg_switches_per_chain",
                observed_value=avg_switches_per_chain,
                expected_range=(1.0, 4.0),
                deviation_score=(avg_switches_per_chain - 4) / 4,
                affected_sessions=[
                    t.to_session_id for t in transitions
                ][:20],  # Limit to 20 sessions
                suggested_investigation=(
                    "Consider: batching related tasks, staying in one tool longer, "
                    "or using tool-specific features before switching"
                ),
                is_transient=False,
            )]

        return []

    def _calculate_severity(
        self, value: float, mean: float, threshold: float,
    ) -> str:
        """Calculate severity based on how far value is from threshold."""
        excess = (value - threshold) / (threshold - mean) if threshold > mean else 0

        if excess > 2:
            return "critical"
        if excess > 1:
            return "high"
        if excess > 0.5:
            return "medium"
        return "low"


# Need to import stdev
import statistics
