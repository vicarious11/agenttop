"""Comparative analysis for workflow metrics across dimensions.

This module compares workflow patterns across projects, time periods,
tools, and users to identify best practices and areas for improvement.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agenttop.workflow.models import ComparativeAnalysis, WorkflowChain, WorkflowMetrics

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class ComparisonConfig:
    """Configuration for comparative analysis."""
    min_sample_size: int = 3  # Minimum samples for meaningful comparison
    similarity_threshold: float = 0.15  # 15% difference is "similar"
    significant_difference: float = 0.30  # 30% difference is significant


class ComparativeAnalyzer:
    """Analyzes workflow patterns across different dimensions.

    Supports comparisons across:
    - Projects: Different codebases or repositories
    - Time periods: Week over week, month over month
    - Tools: Performance metrics across different tools
    - Users: Different team members (if data available)
    """

    def __init__(self, config: ComparisonConfig | None = None) -> None:
        """Initialize the comparative analyzer.

        Args:
            config: Configuration for comparison thresholds
        """
        self._config = config or ComparisonConfig()

    def compare_by_project(
        self,
        chains: Sequence[WorkflowChain],
        min_chains_per_project: int = 5,
    ) -> list[ComparativeAnalysis]:
        """Compare workflow metrics across different projects.

        Args:
            chains: Workflow chains to analyze
            min_chains_per_project: Minimum chains required to include a project

        Returns:
            List of comparative analyses
        """
        # Group chains by project
        by_project: defaultdict[str, list[WorkflowChain]] = defaultdict(list)

        for chain in chains:
            project = chain.project or "unknown"
            by_project[project].append(chain)

        # Filter by minimum size
        valid_projects = {
            p: chains_list
            for p, chains_list in by_project.items()
            if len(chains_list) >= min_chains_per_project
        }

        if len(valid_projects) < 2:
            return []

        # Calculate metrics for each project
        project_metrics: dict[str, WorkflowMetrics] = {}

        for project, proj_chains in valid_projects.items():
            project_metrics[project] = self._calculate_metrics_for_chains(proj_chains)

        # Find the best project to use as baseline
        baseline_project = max(
            project_metrics.keys(),
            key=lambda p: project_metrics[p].avg_efficiency_score,
        )

        # Compare each project to baseline
        analyses: list[ComparativeAnalysis] = []

        for project in project_metrics:
            if project == baseline_project:
                continue

            analysis = self._build_comparison(
                comparison_type="project",
                baseline_name=baseline_project,
                comparison_name=project,
                baseline_metrics=project_metrics[baseline_project],
                comparison_metrics=project_metrics[project],
            )

            if analysis:
                analyses.append(analysis)

        return analyses

    def compare_by_time_period(
        self,
        chains: Sequence[WorkflowChain],
        period_days: int = 7,
    ) -> list[ComparativeAnalysis]:
        """Compare workflow metrics across different time periods.

        Args:
            chains: Workflow chains to analyze
            period_days: Length of each period in days

        Returns:
            List of comparative analyses
        """
        # Group chains by time period
        period_chains: defaultdict[str, list[WorkflowChain]] = defaultdict(list)

        now = time.time()
        period_seconds = period_days * 86400

        for chain in chains:
            period_num = int((now - chain.start_time) // period_seconds)
            period_label = f"Period {period_num}"
            period_chains[period_label].append(chain)

        # Need at least 2 periods with sufficient data
        valid_periods = {
            p: c
            for p, c in period_chains.items()
            if len(c) >= self._config.min_sample_size
        }

        if len(valid_periods) < 2:
            return []

        # Calculate metrics for each period
        period_metrics: dict[str, WorkflowMetrics] = {}

        for period, period_chain_list in valid_periods.items():
            period_metrics[period] = self._calculate_metrics_for_chains(period_chain_list)

        # Sort periods and compare consecutive ones
        sorted_periods = sorted(period_metrics.keys())

        analyses: list[ComparativeAnalysis] = []

        for i in range(len(sorted_periods) - 1):
            current = sorted_periods[i]
            previous = sorted_periods[i + 1]

            analysis = self._build_comparison(
                comparison_type="time_period",
                baseline_name=previous,
                comparison_name=current,
                baseline_metrics=period_metrics[previous],
                comparison_metrics=period_metrics[current],
            )

            if analysis:
                analyses.append(analysis)

        return analyses

    def compare_by_tool(
        self,
        chains: Sequence[WorkflowChain],
    ) -> list[ComparativeAnalysis]:
        """Compare performance metrics across different tools.

        Args:
            chains: Workflow chains to analyze

        Returns:
            List of comparative analyses
        """
        # Group chains by primary tool
        tool_chains: defaultdict[str, list[WorkflowChain]] = defaultdict(list)

        for chain in chains:
            # Use first tool as primary
            if chain.tools:
                primary_tool = chain.tools[0]
                tool_chains[primary_tool].append(chain)

        # Filter by minimum size
        valid_tools = {
            t: c
            for t, c in tool_chains.items()
            if len(c) >= self._config.min_sample_size
        }

        if len(valid_tools) < 2:
            return []

        # Calculate metrics for each tool
        tool_metrics: dict[str, WorkflowMetrics] = {}

        for tool, tool_chain_list in valid_tools.items():
            tool_metrics[tool] = self._calculate_metrics_for_chains(tool_chain_list)

        # Find best tool by efficiency
        baseline_tool = max(
            tool_metrics.keys(),
            key=lambda t: tool_metrics[t].avg_efficiency_score,
        )

        # Compare each tool to the best
        analyses: list[ComparativeAnalysis] = []

        for tool in tool_metrics:
            if tool == baseline_tool:
                continue

            analysis = self._build_comparison(
                comparison_type="tool",
                baseline_name=baseline_tool,
                comparison_name=tool,
                baseline_metrics=tool_metrics[baseline_tool],
                comparison_metrics=tool_metrics[tool],
            )

            if analysis:
                analyses.append(analysis)

        return analyses

    def _calculate_metrics_for_chains(
        self, chains: Sequence[WorkflowChain],
    ) -> WorkflowMetrics:
        """Calculate workflow metrics for a subset of chains."""
        if not chains:
            return WorkflowMetrics(
                total_chains=0,
                total_transitions=0,
                avg_chain_length=0.0,
                avg_efficiency_score=0.0,
                most_common_pattern="",
                most_efficient_pattern="",
                tool_usage_distribution={},
                transition_matrix={},
            )

        total_chains = len(chains)
        total_transitions = sum(len(c.tools) - 1 for c in chains if len(c.tools) > 1)
        avg_chain_length = sum(len(c.tools) for c in chains) / total_chains

        eff_scores = [c.efficiency_score for c in chains if c.efficiency_score is not None]
        avg_efficiency = sum(eff_scores) / len(eff_scores) if eff_scores else 0.5

        # Tool distribution
        tool_dist: defaultdict[str, int] = defaultdict(int)
        for chain in chains:
            for tool in chain.tools:
                tool_dist[tool] += 1

        return WorkflowMetrics(
            total_chains=total_chains,
            total_transitions=total_transitions,
            avg_chain_length=avg_chain_length,
            avg_efficiency_score=avg_efficiency,
            most_common_pattern="",  # Not calculating for subsets
            most_efficient_pattern="",
            tool_usage_distribution=dict(tool_dist),
            transition_matrix={},  # Not calculating for subsets
        )

    def _build_comparison(
        self,
        comparison_type: str,
        baseline_name: str,
        comparison_name: str,
        baseline_metrics: WorkflowMetrics,
        comparison_metrics: WorkflowMetrics,
    ) -> ComparativeAnalysis | None:
        """Build a comparative analysis between two metric sets."""
        # Compare key metrics
        metric_comparisons: dict[str, tuple[float, float, str]] = {}

        # Efficiency comparison
        metric_comparisons["efficiency_score"] = self._compare_values(
            baseline_metrics.avg_efficiency_score,
            comparison_metrics.avg_efficiency_score,
            higher_is_better=True,
        )

        # Chain length comparison (lower is generally better)
        metric_comparisons["avg_chain_length"] = self._compare_values(
            baseline_metrics.avg_chain_length,
            comparison_metrics.avg_chain_length,
            higher_is_better=False,
        )

        # Total activity comparison
        metric_comparisons["activity_level"] = self._compare_values(
            float(baseline_metrics.total_chains),
            float(comparison_metrics.total_chains),
            higher_is_better=True,
        )

        # Generate overall assessment
        better_count = sum(
            1 for _, _, status in metric_comparisons.values() if status == "better"
        )
        worse_count = sum(
            1 for _, _, status in metric_comparisons.values() if status == "worse"
        )

        if better_count > worse_count:
            overall = f"{baseline_name} shows better overall performance"
        elif worse_count > better_count:
            overall = f"{comparison_name} shows better overall performance"
        else:
            overall = "Performance is similar across both"

        # Generate key differences and recommendations
        key_differences = self._generate_key_differences(
            metric_comparisons,
            baseline_name,
            comparison_name,
        )

        recommendations = self._generate_recommendations(
            metric_comparisons,
            baseline_name,
            comparison_name,
        )

        return ComparativeAnalysis(
            comparison_type=comparison_type,
            baseline_name=baseline_name,
            comparison_name=comparison_name,
            metric_comparisons=metric_comparisons,
            overall_assessment=overall,
            key_differences=key_differences,
            recommendations=recommendations,
            confidence="medium",
            created_at=time.time(),
        )

    def _compare_values(
        self,
        baseline: float,
        comparison: float,
        higher_is_better: bool,
    ) -> tuple[float, float, str]:
        """Compare two values and return status.

        Returns:
            (baseline_value, comparison_value, status)
            Status is "better", "worse", or "similar"
        """
        if baseline == 0 and comparison == 0:
            return (baseline, comparison, "similar")

        if baseline == 0:
            diff = comparison
        else:
            diff = abs(comparison - baseline) / baseline

        if diff < self._config.similarity_threshold:
            return (baseline, comparison, "similar")

        if higher_is_better:
            status = "worse" if comparison > baseline else "better"
        else:
            status = "better" if comparison < baseline else "worse"

        return (baseline, comparison, status)

    def _generate_key_differences(
        self,
        metric_comparisons: dict[str, tuple[float, float, str]],
        baseline_name: str,
        comparison_name: str,
    ) -> list[str]:
        """Generate key differences from metric comparisons."""
        differences: list[str] = []

        for metric, (base_val, comp_val, status) in metric_comparisons.items():
            if status == "similar":
                continue

            direction = "higher" if comp_val > base_val else "lower"
            pct_diff = (
                abs(comp_val - base_val) / base_val * 100
                if base_val > 0 else 0
            )

            if status == "better":
                winner = comparison_name if comp_val > base_val else baseline_name
                differences.append(
                    f"{winner} has {pct_diff:.0f}% {direction} {metric} ({direction} is better)"
                )
            else:
                loser = comparison_name if comp_val > base_val else baseline_name
                differences.append(
                    f"{loser} has {pct_diff:.0f}% {direction} {metric} "
                    f"({'worse' if direction == 'higher' and metric == 'avg_chain_length' else 'suboptimal'})"
                )

        return differences

    def _generate_recommendations(
        self,
        metric_comparisons: dict[str, tuple[float, float, str]],
        baseline_name: str,
        comparison_name: str,
    ) -> list[str]:
        """Generate recommendations based on comparison."""
        recommendations: list[str] = []

        # Check efficiency
        if "efficiency_score" in metric_comparisons:
            _, comp_val, status = metric_comparisons["efficiency_score"]
            if status == "worse" and comp_val < 0.6:
                recommendations.append(
                    f"Improve prompt quality and reduce tool switching to boost efficiency"
                )

        # Check chain length
        if "avg_chain_length" in metric_comparisons:
            _, comp_val, status = metric_comparisons["avg_chain_length"]
            if status == "worse" and comp_val > 4:
                recommendations.append(
                    f"Consolidate related tasks to reduce excessive tool switching"
                )

        # Check activity
        if "activity_level" in metric_comparisons:
            _, comp_val, status = metric_comparisons["activity_level"]
            if status == "worse" and comp_val < 5:
                recommendations.append(
                    f"Consider increasing usage or check for data collection issues"
                )

        if not recommendations:
            recommendations.append("Continue current practices - performance is comparable")

        return recommendations

    def find_best_practices(
        self,
        chains: Sequence[WorkflowChain],
    ) -> dict[str, str]:
        """Find best practices across all workflow data.

        Args:
            chains: All workflow chains to analyze

        Returns:
            Dict mapping practice name to description
        """
        practices: dict[str, str] = {}

        if not chains:
            return practices

        # Find most efficient chains
        eff_chains = [c for c in chains if c.efficiency_score is not None]
        if eff_chains:
            top_chains = sorted(eff_chains, key=lambda c: c.efficiency_score, reverse=True)[:5]

            # Analyze characteristics
            avg_chain_length = sum(len(c.tools) for c in top_chains) / len(top_chains)
            avg_cost = sum(c.total_cost for c in top_chains) / len(top_chains)

            practices["optimal_chain_length"] = (
                f"Average {avg_chain_length:.1f} tools per workflow"
            )
            practices["cost_efficiency"] = (
                f"Top performers average ${avg_cost:.2f} per chain"
            )

            # Check for common patterns
            if avg_chain_length < 2.5:
                practices["focus_pattern"] = "Stay in one tool when possible"
            elif avg_chain_length < 4:
                practices["focus_pattern"] = "Limit tool switches to 2-3 per workflow"

        return practices
