"""Trend analysis for workflow metrics over time.

This module tracks how workflow metrics change over time, identifying
improvements, declines, and seasonal patterns.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from agenttop.workflow.models import (
    TrendAnalysis,
    TrendDirection,
    WorkflowChain,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class TrendConfig:
    """Configuration for trend analysis."""
    min_data_points: int = 3  # Minimum data points for trend analysis
    significant_change_threshold: float = 0.10  # 10% change is significant
    confidence_threshold: float = 0.05  # P-value threshold for statistical significance
    min_confidence: str = "medium"  # Minimum confidence to report trend


class TrendAnalyzer:
    """Analyzes trends in workflow metrics over time.

    Provides:
    - Trend direction (improving, declining, stable, volatile)
    - Percent change calculations
    - Forecasting based on historical trends
    - Seasonal pattern detection
    """

    def __init__(self, config: TrendConfig | None = None) -> None:
        """Initialize the trend analyzer.

        Args:
            config: Configuration for trend analysis
        """
        self._config = config or TrendConfig()
        self._historical_data: dict[str, list[tuple[float, float]]] = defaultdict(list)

    def add_data_point(self, metric_name: str, value: float, timestamp: float) -> None:
        """Add a data point for trend tracking.

        Args:
            metric_name: Name of the metric
            value: Value at this timestamp
            timestamp: Unix timestamp
        """
        self._historical_data[metric_name].append((timestamp, value))
        # Keep last 1000 points per metric
        if len(self._historical_data[metric_name]) > 1000:
            self._historical_data[metric_name] = self._historical_data[metric_name][-1000:]

    def analyze_all_trends(
        self,
        chains: Sequence[WorkflowChain],
        time_period_days: int = 30,
    ) -> list[TrendAnalysis]:
        """Analyze trends for all key workflow metrics.

        Args:
            chains: Workflow chains to analyze
            time_period_days: Time period to analyze in days

        Returns:
            List of trend analyses for each metric
        """
        if not chains:
            return []

        # Organize chains by time periods
        time_series = self._create_time_series(chains, time_period_days)

        analyses: list[TrendAnalysis] = []

        # Analyze each metric
        analyses.append(self._analyze_efficiency_trend(time_series, time_period_days))
        analyses.append(self._analyze_cost_trend(time_series, time_period_days))
        analyses.append(self._analyze_token_trend(time_series, time_period_days))
        analyses.append(self._analyze_chain_length_trend(time_series, time_period_days))
        analyses.append(self._analyze_activity_trend(time_series, time_period_days))

        return [a for a in analyses if a is not None]

    def _create_time_series(
        self,
        chains: Sequence[WorkflowChain],
        time_period_days: int,
    ) -> dict[str, list[tuple[float, dict[str, float]]]]:
        """Create time series data from chains.

        Returns:
            Dict mapping period key to (timestamp, metrics) tuples
        """
        # Group chains by day
        daily_data: defaultdict[str, list[WorkflowChain]] = defaultdict(list)

        now = time.time()
        cutoff_time = now - (time_period_days * 86400)

        for chain in chains:
            if chain.start_time >= cutoff_time:
                day_key = datetime.fromtimestamp(chain.start_time).strftime("%Y-%m-%d")
                daily_data[day_key].append(chain)

        # Calculate metrics per day
        time_series: dict[str, list[tuple[float, dict[str, float]]]] = {}

        for day, day_chains in sorted(daily_data.items()):
            day_timestamp = datetime.strptime(day, "%Y-%m-%d").timestamp()

            metrics = self._calculate_period_metrics(day_chains)
            time_series[day] = [(day_timestamp, metrics)]

        return time_series

    def _calculate_period_metrics(
        self, chains: Sequence[WorkflowChain],
    ) -> dict[str, float]:
        """Calculate aggregate metrics for a time period."""
        if not chains:
            return {}

        total_cost = sum(c.total_cost for c in chains)
        total_tokens = sum(c.total_tokens for c in chains)
        avg_chain_length = sum(len(c.tools) for c in chains) / len(chains)

        eff_scores = [c.efficiency_score for c in chains if c.efficiency_score is not None]
        avg_efficiency = sum(eff_scores) / len(eff_scores) if eff_scores else 0.5

        return {
            "avg_efficiency": avg_efficiency,
            "total_cost": total_cost,
            "total_tokens": float(total_tokens),
            "avg_chain_length": avg_chain_length,
            "num_chains": float(len(chains)),
        }

    def _analyze_efficiency_trend(
        self,
        time_series: dict[str, list[tuple[float, dict[str, float]]]],
        time_period_days: int,
    ) -> TrendAnalysis | None:
        """Analyze efficiency trend over time."""
        if len(time_series) < self._config.min_data_points:
            return None

        points = []
        for day_data in time_series.values():
            for ts, metrics in day_data:
                if "avg_efficiency" in metrics:
                    points.append((ts, metrics["avg_efficiency"]))

        if not points:
            return None

        return self._build_trend_analysis(
            metric_name="efficiency_score",
            points=sorted(points),
            time_period_days=time_period_days,
            direction_map=TrendDirection.IMPROVING,  # Higher is better
        )

    def _analyze_cost_trend(
        self,
        time_series: dict[str, list[tuple[float, dict[str, float]]]],
        time_period_days: int,
    ) -> TrendAnalysis | None:
        """Analyze cost trend over time."""
        if len(time_series) < self._config.min_data_points:
            return None

        points = []
        for day_data in time_series.values():
            for ts, metrics in day_data:
                if "total_cost" in metrics:
                    points.append((ts, metrics["total_cost"]))

        if not points:
            return None

        return self._build_trend_analysis(
            metric_name="daily_cost",
            points=sorted(points),
            time_period_days=time_period_days,
            direction_map=TrendDirection.DECLINING,  # Lower is better for cost
        )

    def _analyze_token_trend(
        self,
        time_series: dict[str, list[tuple[float, dict[str, float]]]],
        time_period_days: int,
    ) -> TrendAnalysis | None:
        """Analyze token consumption trend."""
        if len(time_series) < self._config.min_data_points:
            return None

        points = []
        for day_data in time_series.values():
            for ts, metrics in day_data:
                if "total_tokens" in metrics:
                    points.append((ts, metrics["total_tokens"]))

        if not points:
            return None

        return self._build_trend_analysis(
            metric_name="daily_tokens",
            points=sorted(points),
            time_period_days=time_period_days,
            direction_map=TrendDirection.DECLINING,  # Lower is better
        )

    def _analyze_chain_length_trend(
        self,
        time_series: dict[str, list[tuple[float, dict[str, float]]]],
        time_period_days: int,
    ) -> TrendAnalysis | None:
        """Analyze chain length trend."""
        if len(time_series) < self._config.min_data_points:
            return None

        points = []
        for day_data in time_series.values():
            for ts, metrics in day_data:
                if "avg_chain_length" in metrics:
                    points.append((ts, metrics["avg_chain_length"]))

        if not points:
            return None

        return self._build_trend_analysis(
            metric_name="avg_chain_length",
            points=sorted(points),
            time_period_days=time_period_days,
            direction_map=TrendDirection.DECLINING,  # Lower is better (less switching)
        )

    def _analyze_activity_trend(
        self,
        time_series: dict[str, list[tuple[float, dict[str, float]]]],
        time_period_days: int,
    ) -> TrendAnalysis | None:
        """Analyze activity level trend."""
        if len(time_series) < self._config.min_data_points:
            return None

        points = []
        for day_data in time_series.values():
            for ts, metrics in day_data:
                if "num_chains" in metrics:
                    points.append((ts, metrics["num_chains"]))

        if not points:
            return None

        return self._build_trend_analysis(
            metric_name="daily_chains",
            points=sorted(points),
            time_period_days=time_period_days,
            direction_map=TrendDirection.STABLE,  # Stable is best for activity
        )

    def _build_trend_analysis(
        self,
        metric_name: str,
        points: list[tuple[float, float]],
        time_period_days: int,
        direction_map: TrendDirection,
    ) -> TrendAnalysis | None:
        """Build a trend analysis from data points."""
        if len(points) < 2:
            return None

        # Calculate values
        current_value = points[-1][1]
        previous_value = points[0][1]

        # Avoid division by zero
        if previous_value == 0:
            percent_change = 0.0
        else:
            percent_change = ((current_value - previous_value) / previous_value) * 100

        # Determine direction
        direction = self._determine_direction(
            percent_change,
            points,
            direction_map,
        )

        # Determine confidence based on data points
        confidence = self._determine_confidence(len(points))

        # Simple linear forecast
        forecast = self._simple_forecast(points)

        # Detect seasonality
        seasonal = self._detect_seasonality(points)

        # Generate insights
        insights = self._generate_insights(
            metric_name,
            direction,
            percent_change,
            current_value,
        )

        return TrendAnalysis(
            metric_name=metric_name,
            direction=direction,
            current_value=current_value,
            previous_value=previous_value,
            percent_change=percent_change,
            time_period_days=time_period_days,
            confidence=confidence,
            data_points=len(points),
            trend_line=points,
            seasonal_pattern=seasonal,
            forecast=forecast,
            insights=insights,
        )

    def _determine_direction(
        self,
        percent_change: float,
        points: list[tuple[float, float]],
        preferred_direction: TrendDirection,
    ) -> TrendDirection:
        """Determine trend direction."""
        threshold = self._config.significant_change_threshold * 100

        # Check for volatility
        if len(points) > 3:
            values = [v for _, v in points[-5:]]
            if max(values) - min(values) > (sum(values) / len(values) * 0.5):
                return TrendDirection.VOLATILE

        # Determine based on change
        if abs(percent_change) < threshold:
            return TrendDirection.STABLE

        if preferred_direction == TrendDirection.IMPROVING:
            # Higher is better
            return TrendDirection.IMPROVING if percent_change > 0 else TrendDirection.DECLINING
        elif preferred_direction == TrendDirection.DECLINING:
            # Lower is better
            return TrendDirection.IMPROVING if percent_change < 0 else TrendDirection.DECLINING
        else:
            # Stable is preferred
            return TrendDirection.STABLE

    def _determine_confidence(self, data_points: int) -> str:
        """Determine confidence level based on data points."""
        if data_points >= 20:
            return "high"
        if data_points >= 10:
            return "medium"
        return "low"

    def _simple_forecast(
        self, points: list[tuple[float, float]],
    ) -> tuple[float, float] | None:
        """Generate a simple linear forecast.

        Returns:
            (predicted_value, confidence) or None
        """
        if len(points) < 3:
            return None

        # Simple linear regression
        n = len(points)
        sum_x = sum(ts for ts, _ in points)
        sum_y = sum(v for _, v in points)
        sum_xy = sum(ts * v for ts, v in points)
        sum_x2 = sum(ts * ts for ts, _ in points)

        denominator = (n * sum_x2) - (sum_x * sum_x)
        if denominator == 0:
            return None

        slope = ((n * sum_xy) - (sum_x * sum_y)) / denominator
        intercept = (sum_y - (slope * sum_x)) / n

        # Forecast next period
        last_ts = points[-1][0]
        period_delta = (points[-1][0] - points[0][0]) / (n - 1) if n > 1 else 86400
        next_ts = last_ts + period_delta

        predicted = slope * next_ts + intercept

        # Simple confidence based on R² approximation
        y_mean = sum_y / n
        ss_tot = sum((v - y_mean) ** 2 for _, v in points)
        ss_res = sum((v - (slope * ts + intercept)) ** 2 for ts, v in points)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        confidence = min(0.95, max(0.1, r_squared))

        return (predicted, confidence)

    def _detect_seasonality(
        self, points: list[tuple[float, float]],
    ) -> str | None:
        """Detect seasonal patterns in the data.

        Returns description of pattern or None
        """
        if len(points) < 7:  # Need at least a week
            return None

        # Check for day-of-week patterns
        weekday_values: defaultdict[int, list[float]] = defaultdict(list)

        for ts, value in points:
            weekday = datetime.fromtimestamp(ts).weekday()
            weekday_values[weekday].append(value)

        # Calculate averages per weekday
        weekday_avgs = {
            wd: sum(vals) / len(vals)
            for wd, vals in weekday_values.items()
            if vals
        }

        if len(weekday_avgs) < 5:
            return None

        # Check if there's significant variation
        avg_values = list(weekday_avgs.values())
        variation = (max(avg_values) - min(avg_values)) / (sum(avg_values) / len(avg_values))

        if variation > 0.3:
            # Find best and worst days
            best_day = max(weekday_avgs, key=weekday_avgs.get)
            worst_day = min(weekday_avgs, key=weekday_avgs.get)
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            return (
                f"Weekly pattern: {day_names[best_day]} highest, "
                f"{day_names[worst_day]} lowest"
            )

        return None

    def _generate_insights(
        self,
        metric_name: str,
        direction: TrendDirection,
        percent_change: float,
        current_value: float,
    ) -> list[str]:
        """Generate insights about the trend."""
        insights: list[str] = []

        if direction == TrendDirection.IMPROVING:
            insights.append(f"{metric_name} improved by {abs(percent_change):.1f}%")
        elif direction == TrendDirection.DECLINING:
            insights.append(f"{metric_name} declined by {abs(percent_change):.1f}%")
        elif direction == TrendDirection.VOLATILE:
            insights.append(f"{metric_name} shows high volatility")
        else:
            insights.append(f"{metric_name} remained stable")

        # Add specific insights based on metric
        if "efficiency" in metric_name:
            if current_value > 0.8:
                insights.append("Strong efficiency performance")
            elif current_value < 0.5:
                insights.append("Efficiency below 50% - needs attention")
        elif "cost" in metric_name:
            if direction == TrendDirection.DECLINING:
                insights.append("Cost reduction trend positive")
        elif "chain_length" in metric_name:
            if current_value < 2:
                insights.append("Good focus - minimal tool switching")
            elif current_value > 5:
                insights.append("High switching may hurt productivity")

        return insights

    def get_metric_history(
        self, metric_name: str, limit: int = 30,
    ) -> list[tuple[float, float]]:
        """Get historical data for a metric.

        Args:
            metric_name: Name of the metric
            limit: Maximum number of points to return

        Returns:
            List of (timestamp, value) tuples
        """
        if metric_name not in self._historical_data:
            return []

        return self._historical_data[metric_name][-limit:]
