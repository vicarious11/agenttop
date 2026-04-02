"""Workflow analysis: efficiency scoring and insights."""

from __future__ import annotations

import logging
import math
from collections import Counter
from datetime import datetime

from agenttop.models import Session
from agenttop.workflow.anti_patterns import AntiPatternDetector
from agenttop.workflow.affinity import ToolAffinityAnalyzer
from agenttop.workflow.correlator import SessionCorrelator
from agenttop.workflow.cost_optimizer import CostOptimizer
from agenttop.workflow.knowledge_base import (
    TASK_TYPE_RECOMMENDATIONS,
    get_recommendation_for_task,
    get_switching_cost,
)
from agenttop.workflow.models import (
    ToolTransition,
    WorkflowChain,
    WorkflowMetrics,
    WorkflowRecommendation,
)
from agenttop.workflow.patterns import WorkflowPatternDetector
from agenttop.workflow.prediction import WorkflowPredictor
from agenttop.workflow.productivity import ProductivityScorer

log = logging.getLogger(__name__)


class WorkflowAnalyzer:
    """Analyzes workflow patterns and efficiency."""

    def __init__(self) -> None:
        self._correlator = SessionCorrelator()
        self._pattern_detector = WorkflowPatternDetector()
        # Phase 2 modules
        self._anti_pattern_detector = AntiPatternDetector()
        self._affinity_analyzer = ToolAffinityAnalyzer()
        self._cost_optimizer = CostOptimizer()
        self._predictor = WorkflowPredictor()
        self._productivity_scorer = ProductivityScorer()

    def analyze_chains(
        self,
        chains: list[WorkflowChain],
        transitions: list[ToolTransition],
    ) -> dict:
        """Analyze workflow chains and calculate metrics.

        Args:
            chains: List of workflow chains
            transitions: List of tool transitions

        Returns:
            Dict with analysis results including Phase 2 enhancements
        """
        if not chains:
            return {"error": "No chains to analyze"}

        # Detect patterns
        patterns = self._pattern_detector.detect_patterns(chains, transitions)

        # Calculate efficiency scores for each chain (immutable: create new list)
        chains_with_efficiency = [
            chain.with_efficiency(self.calculate_chain_efficiency(chain, transitions))
            for chain in chains
        ]

        # Phase 2: Detect anti-patterns
        anti_patterns = self._anti_pattern_detector.detect_anti_patterns(chains_with_efficiency, transitions)

        # Phase 2: Calculate productivity score
        productivity_score, productivity_breakdown = self._productivity_scorer.calculate_productivity_score(
            chains_with_efficiency,
            anti_patterns,
        )

        # Calculate aggregate metrics (with productivity)
        metrics = self._calculate_metrics(chains_with_efficiency, transitions, productivity_score)

        # Phase 2: Analyze tool affinities
        affinities = self._affinity_analyzer.analyze_affinities(chains_with_efficiency)

        # Phase 2: Find cost optimization opportunities
        cost_optimizations = self._cost_optimizer.analyze_optimization_opportunities(chains_with_efficiency)

        # Get recommendations
        recommendations = self._generate_recommendations(chains_with_efficiency, patterns)

        # Add Phase 2 recommendations
        recommendations.extend(self._generate_phase_2_recommendations(
            anti_patterns,
            cost_optimizations,
            productivity_breakdown,
        ))

        return {
            "patterns": patterns,
            "metrics": metrics,
            "recommendations": recommendations,
            "chain_count": len(chains),
            "transition_count": len(transitions),
            # Phase 2 additions
            "anti_patterns": anti_patterns,
            "anti_pattern_summary": self._anti_pattern_detector.get_anti_pattern_summary(anti_patterns),
            "affinities": affinities,
            "cost_optimizations": cost_optimizations[:10],  # Top 10
            "cost_optimization_summary": self._cost_optimizer.get_total_waste(cost_optimizations),
            "productivity_score": productivity_score,
            "productivity_breakdown": productivity_breakdown,
            "productivity_grade": self._productivity_scorer.get_productivity_grade(productivity_score),
        }

    def analyze_tool_combinations(
        self,
        chains: list[WorkflowChain],
    ) -> dict[str, dict]:
        """Identify which tool combinations are most effective.

        Args:
            chains: List of workflow chains

        Returns:
            Dict mapping tool combination string to effectiveness metrics
        """
        combinations: dict[str, dict] = {}

        for chain in chains:
            # Create a sorted tuple of tools for the key
            tool_combo = tuple(sorted(set(chain.tools)))
            combo_key = " → ".join(tool_combo)

            if combo_key not in combinations:
                combinations[combo_key] = {
                    "tools": tool_combo,
                    "count": 0,
                    "total_tokens": 0,
                    "total_cost": 0.0,
                    "efficiency_scores": [],
                    "avg_duration_minutes": [],
                }

            combinations[combo_key]["count"] += 1
            combinations[combo_key]["total_tokens"] += chain.total_tokens
            combinations[combo_key]["total_cost"] += chain.total_cost
            if chain.efficiency_score is not None:
                combinations[combo_key]["efficiency_scores"].append(chain.efficiency_score)
            combinations[combo_key]["avg_duration_minutes"].append(
                (chain.end_time - chain.start_time) / 60
            )

        # Calculate averages and rank
        for combo_key, data in combinations.items():
            count = data["count"]
            data["avg_tokens"] = data["total_tokens"] / count if count > 0 else 0
            data["avg_cost"] = data["total_cost"] / count if count > 0 else 0
            data["avg_efficiency"] = (
                sum(data["efficiency_scores"]) / len(data["efficiency_scores"])
                if data["efficiency_scores"] else 0.5
            )
            data["avg_duration"] = (
                sum(data["avg_duration_minutes"]) / len(data["avg_duration_minutes"])
                if data["avg_duration_minutes"] else 0
            )
            # Clean up raw lists
            del data["efficiency_scores"]
            del data["avg_duration_minutes"]

        return dict(sorted(
            combinations.items(),
            key=lambda x: x[1]["avg_efficiency"],
            reverse=True,
        ))

    def measure_switching_costs(
        self,
        transitions: list[ToolTransition],
    ) -> dict:
        """Calculate context loss and ramp-up time when switching tools.

        Args:
            transitions: List of tool transitions

        Returns:
            Dict with switching cost analysis
        """
        if not transitions:
            return {"error": "No transitions to analyze"}

        # Group transitions by from->to pair
        transition_costs: dict[tuple[str, str], list[ToolTransition]] = {}
        for transition in transitions:
            key = (transition.from_tool, transition.to_tool)
            if key not in transition_costs:
                transition_costs[key] = []
            transition_costs[key].append(transition)

        results = {}
        for (from_tool, to_tool), trans_list in transition_costs.items():
            # Get known switching cost from knowledge base
            known_cost = get_switching_cost(from_tool, to_tool)

            # Calculate actual metrics from transitions
            avg_time_gap = sum(t.time_gap_seconds for t in trans_list) / len(trans_list)
            avg_preservation = sum(
                t.context_preservation_score for t in trans_list
                if t.context_preservation_score is not None
            ) / len([t for t in trans_list if t.context_preservation_score is not None]) if any(
                t.context_preservation_score is not None for t in trans_list
            ) else 0.5

            project_match_rate = sum(1 for t in trans_list if t.project_match) / len(trans_list)

            results[f"{from_tool} → {to_tool}"] = {
                "from_tool": from_tool,
                "to_tool": to_tool,
                "frequency": len(trans_list),
                "avg_time_gap_seconds": round(avg_time_gap, 1),
                "avg_context_preservation": round(avg_preservation, 2),
                "project_match_rate": round(project_match_rate, 2),
                "known_context_loss": known_cost.context_loss_score if known_cost else None,
                "mitigation_strategy": known_cost.mitigation_strategy if known_cost else None,
            }

        return results

    def identify_workflow_patterns(
        self,
        chains: list[WorkflowChain],
        transitions: list[ToolTransition],
    ) -> list[dict]:
        """Detect common workflow patterns in the chains.

        Args:
            chains: List of workflow chains
            transitions: List of tool transitions

        Returns:
            List of pattern descriptions with recommendations
        """
        patterns = self._pattern_detector.detect_patterns(chains, transitions)
        return [
            {
                "name": p.name,
                "description": p.description,
                "tool_sequence": p.tool_sequence,
                "frequency": p.frequency,
                "avg_efficiency": round(p.avg_efficiency, 2),
                "avg_cost": round(p.avg_cost, 2),
                "typical_duration_minutes": round(p.typical_duration_minutes, 1),
            }
            for p in patterns
        ]

    def calculate_chain_efficiency(
        self,
        chain: WorkflowChain,
        transitions: list[ToolTransition],
    ) -> float:
        """Calculate efficiency score for a chain (0.0 - 1.0).

        Factors:
        - Tool selection appropriateness
        - Context preservation
        - Token efficiency
        - Duration efficiency
        """
        score = 0.5  # Start neutral

        # Get transitions for this chain
        chain_transitions = [
            t for t in transitions
            if t.from_session_id in chain.session_ids or t.to_session_id in chain.session_ids
        ]

        # Factor 1: Number of tools (optimal = 1-2)
        num_tools = len(set(chain.tools))
        if num_tools == 1:
            score += 0.15  # Single tool can be very efficient
        elif num_tools == 2:
            score += 0.10  # Two tools often optimal
        elif num_tools == 3:
            score += 0.0  # Neutral
        else:
            score -= 0.10  # Too many tools

        # Factor 2: Context preservation
        if chain_transitions:
            avg_preservation = sum(
                t.context_preservation_score for t in chain_transitions
                if t.context_preservation_score is not None
            ) / len(chain_transitions)
            if avg_preservation >= 0.7:
                score += 0.15
            elif avg_preservation >= 0.5:
                score += 0.05
            elif avg_preservation < 0.3:
                score -= 0.10

        # Factor 3: Token efficiency (tokens per minute)
        duration_minutes = (chain.end_time - chain.start_time) / 60
        if duration_minutes > 0:
            tokens_per_minute = chain.total_tokens / duration_minutes
            if tokens_per_minute < 500:
                score += 0.10  # Thoughtful usage
            elif tokens_per_minute > 2000:
                score -= 0.05  # Rapid token consumption

        # Factor 4: Project consistency
        if chain_transitions:
            project_match_rate = sum(1 for t in chain_transitions if t.project_match) / len(chain_transitions)
            if project_match_rate >= 0.8:
                score += 0.10

        return max(0.0, min(1.0, score))

    def _calculate_confidence_interval(
        self,
        values: list[float],
        confidence: float = 0.95,
    ) -> tuple[float, float] | None:
        """Calculate confidence interval for a list of values.

        Uses t-distribution for small samples (n < 30).

        Args:
            values: List of numeric values
            confidence: Confidence level (default 0.95 for 95% CI)

        Returns:
            Tuple of (lower, upper) bounds or None if insufficient data
        """
        n = len(values)
        if n < 2:
            return None

        mean = sum(values) / n

        # Calculate sample standard deviation
        variance = sum((x - mean) ** 2 for x in values) / (n - 1) if n > 1 else 0
        std_dev = math.sqrt(variance)

        if std_dev == 0:
            return (mean, mean)

        # Standard error
        std_error = std_dev / math.sqrt(n)

        # T-score for 95% confidence (approximate, use 2.0 for n >= 30)
        if n >= 30:
            t_score = 1.96  # Normal distribution approximation
        else:
            # Approximate t-scores for common sample sizes
            t_table = {
                2: 12.71, 3: 4.30, 4: 3.18, 5: 2.78, 6: 2.57,
                7: 2.45, 8: 2.36, 9: 2.31, 10: 2.26, 11: 2.23,
                12: 2.20, 13: 2.18, 14: 2.16, 15: 2.14, 16: 2.13,
                17: 2.12, 18: 2.11, 19: 2.10, 20: 2.09, 25: 2.06,
            }
            t_score = t_table.get(n, 2.0)  # Default to 2.0 for larger small samples

        margin_of_error = t_score * std_error

        return (
            round(max(0.0, mean - margin_of_error), 3),
            round(min(1.0, mean + margin_of_error), 3),
        )

    def _calculate_peak_time_of_day(
        self,
        chains: list[WorkflowChain],
    ) -> tuple[int, int, int] | None:
        """Find the peak hour of day for workflow activity.

        Args:
            chains: List of workflow chains with session_start_times

        Returns:
            Tuple of (hour, confidence, sample_size) or None if no data
        """
        all_hours: list[int] = []

        for chain in chains:
            for ts in chain.session_start_times:
                dt = datetime.fromtimestamp(ts)
                all_hours.append(dt.hour)

        if not all_hours:
            return None

        # Count occurrences per hour
        hour_counts: dict[int, int] = {}
        for hour in all_hours:
            hour_counts[hour] = hour_counts.get(hour, 0) + 1

        # Find peak hour
        peak_hour = max(hour_counts, key=hour_counts.get)  # type: ignore[arg-type]

        # Calculate confidence based on concentration
        total = len(all_hours)
        peak_count = hour_counts[peak_hour]
        concentration = peak_count / total

        # Confidence: high if >40% concentration, medium if >25%, low otherwise
        if concentration > 0.4:
            confidence_pct = 85
        elif concentration > 0.25:
            confidence_pct = 60
        else:
            confidence_pct = 40

        return (peak_hour, confidence_pct, total)

    def _calculate_metrics(
        self,
        chains: list[WorkflowChain],
        transitions: list[ToolTransition],
        productivity_score: float = 0.5,
    ) -> WorkflowMetrics:
        """Calculate aggregate workflow metrics with confidence intervals and Phase 2 enhancements."""
        # Tool usage distribution from chains (convert Counter to dict for JSON serialization)
        tool_dist: dict[str, int] = dict(Counter(tool for chain in chains for tool in chain.tools))

        # Transition matrix
        transition_matrix = self._correlator.get_transition_matrix(transitions)

        # Average chain length (number of sessions per chain)
        chain_lengths = [len(c.session_ids) for c in chains]
        avg_chain_length = sum(chain_lengths) / len(chains) if chains else 0

        # Phase 1: Chain length confidence interval
        chain_length_ci = self._calculate_confidence_interval(chain_lengths) if len(chain_lengths) >= 2 else None

        # Average efficiency
        efficiencies = [c.efficiency_score for c in chains if c.efficiency_score is not None]
        avg_efficiency = sum(efficiencies) / len(efficiencies) if efficiencies else 0.5

        # Phase 1: Efficiency confidence interval
        efficiency_ci = self._calculate_confidence_interval(efficiencies) if len(efficiencies) >= 2 else None

        # Most common pattern
        pattern_counts = Counter(c.pattern_type for c in chains if c.pattern_type)
        most_common_pattern = pattern_counts.most_common(1)[0][0] if pattern_counts else "unknown"

        # Most efficient pattern
        pattern_efficiencies: dict[str, list[float]] = {}
        for chain in chains:
            if chain.pattern_type and chain.efficiency_score is not None:
                if chain.pattern_type not in pattern_efficiencies:
                    pattern_efficiencies[chain.pattern_type] = []
                pattern_efficiencies[chain.pattern_type].append(chain.efficiency_score)

        most_efficient_pattern = "unknown"
        best_avg = 0.0
        for pattern, scores in pattern_efficiencies.items():
            avg = sum(scores) / len(scores)
            if avg > best_avg:
                best_avg = avg
                most_efficient_pattern = pattern

        # Phase 1: Total sessions across all chains
        total_sessions = sum(c.sample_size for c in chains) if chains else 0

        # Phase 1: Peak time of day analysis
        peak_time_of_day = self._calculate_peak_time_of_day(chains)

        # Phase 2: Calculate wasted tokens and cost savings potential
        wasted_tokens = sum(
            c.total_tokens for c in chains
            if c.efficiency_score is not None and c.efficiency_score < 0.5
        )
        cost_savings = sum(
            c.total_cost * 0.3 for c in chains
            if c.efficiency_score is not None and c.efficiency_score < 0.5
        )

        return WorkflowMetrics(
            total_chains=len(chains),
            total_transitions=len(transitions),
            avg_chain_length=round(avg_chain_length, 2),
            avg_efficiency_score=round(avg_efficiency, 2),
            most_common_pattern=most_common_pattern,
            most_efficient_pattern=most_efficient_pattern,
            tool_usage_distribution=tool_dist,
            transition_matrix=transition_matrix,
            efficiency_ci=efficiency_ci,  # Phase 1
            avg_chain_length_ci=chain_length_ci,  # Phase 1
            total_sessions=total_sessions,  # Phase 1
            peak_time_of_day=peak_time_of_day,  # Phase 1
            productivity_score=round(productivity_score, 2),  # Phase 2
            total_wasted_tokens=wasted_tokens,  # Phase 2
            cost_savings_potential=round(cost_savings, 2),  # Phase 2
        )

    def _generate_recommendations(
        self,
        chains: list[WorkflowChain],
        patterns: list,
    ) -> list[dict]:
        """Generate workflow improvement recommendations."""
        recommendations = []

        # Get pattern recommendations
        pattern_recs = self._pattern_detector.get_pattern_recommendations(patterns)
        recommendations.extend(pattern_recs)

        # Analyze tool selection
        tool_usage = Counter(tool for chain in chains for tool in chain.tools)

        # Check for over-reliance on one tool
        if tool_usage:
            most_used = tool_usage.most_common(1)[0]
            total_usage = sum(tool_usage.values())
            if most_used[1] / total_usage > 0.8:
                recommendations.append({
                    "type": "tool_diversity",
                    "issue": f"Over-reliance on {most_used[0]} ({most_used[1]/total_usage*100:.0f}% of usage)",
                    "recommendation": f"Consider using complementary tools for different task types",
                    "potential_benefit": "May improve efficiency by 20-30%",
                })

        return recommendations

    def get_task_based_recommendation(
        self,
        task_type: str,
        current_tools: list[str],
    ) -> WorkflowRecommendation | None:
        """Get recommendation for a specific task type.

        Args:
            task_type: Type of task (debugging, greenfield, etc.)
            current_tools: Tools currently available/being used

        Returns:
            WorkflowRecommendation if found, None otherwise
        """
        base_recommendation = get_recommendation_for_task(task_type)
        if not base_recommendation:
            return None

        # Check if current tools match recommendation
        if base_recommendation.primary_tool in current_tools:
            return base_recommendation

        # Suggest alternative if primary not available
        for secondary in base_recommendation.secondary_tools:
            if secondary in current_tools:
                return WorkflowRecommendation(
                    task_type=task_type,
                    primary_tool=secondary,
                    secondary_tools=[t for t in current_tools if t != secondary],
                    avoid_tools=base_recommendation.avoid_tools,
                    rationale=f"Primary recommendation ({base_recommendation.primary_tool}) not available. {base_recommendation.rationale}",
                    estimated_efficiency_gain=base_recommendation.estimated_efficiency_gain * 0.7,
                )

        return None

    def _generate_phase_2_recommendations(
        self,
        anti_patterns: list,
        cost_optimizations: list,
        productivity_breakdown: dict,
    ) -> list[dict]:
        """Generate Phase 2 recommendations based on anti-patterns and cost optimization.

        Args:
            anti_patterns: List of detected anti-patterns
            cost_optimizations: List of cost optimization opportunities
            productivity_breakdown: Productivity factor breakdown

        Returns:
            List of recommendation dicts
        """
        recommendations: list[dict] = []

        # Anti-pattern based recommendations
        critical_anti_patterns = [ap for ap in anti_patterns if ap.severity in ("critical", "high")]
        if critical_anti_patterns:
            recommendations.append({
                "type": "anti_pattern",
                "priority": "urgent",
                "issue": f"{len(critical_anti_patterns)} critical/high severity anti-patterns detected",
                "recommendation": "Address these anti-patterns immediately. They are significantly impacting your productivity and costs.",
                "affected_sessions": sum(len(ap.affected_sessions) for ap in critical_anti_patterns),
                "estimated_cost_impact": sum(ap.estimated_cost_impact for ap in critical_anti_patterns),
            })

        # Cost optimization recommendations
        if cost_optimizations:
            top_saving = cost_optimizations[0]  # Already sorted by savings
            if top_saving.potential_savings > 1.0:
                recommendations.append({
                    "type": "cost_optimization",
                    "priority": "high" if top_saving.potential_savings > 5.0 else "medium",
                    "issue": f"Significant cost savings opportunity: ${top_saving.potential_savings:.2f}",
                    "recommendation": top_saving.recommendation,
                    "current_cost": round(top_saving.current_cost, 2),
                    "optimized_cost": round(top_saving.optimized_cost, 2),
                    "savings_percentage": top_saving.savings_percentage,
                })

        # Productivity improvement recommendations
        if productivity_breakdown.get("overall", 1.0) < 0.6:
            # Find weakest factor
            factors = ["efficiency", "cost_effectiveness", "momentum", "focus", "anti_pattern_free"]
            weakest = min(factors, key=lambda f: productivity_breakdown.get(f, 0.5))

            recommendations.append({
                "type": "productivity",
                "priority": "medium",
                "issue": f"Low productivity score ({productivity_breakdown.get('overall', 0):.2f})",
                "recommendation": f"Focus on improving {weakest}. " + self._get_factor_improvement_tip(weakest),
                "breakdown": productivity_breakdown,
            })

        return recommendations

    def _get_factor_improvement_tip(self, factor: str) -> str:
        """Get specific improvement tip for a productivity factor."""
        tips = {
            "efficiency": "Plan your requests more carefully and provide clearer context.",
            "cost_effectiveness": "Use more concise prompts and consider cheaper tool alternatives for simple tasks.",
            "momentum": "Build on previous work by staying in focused sessions and reusing context.",
            "focus": "Reduce tool switching. Pick one tool and complete your workflow in it.",
            "anti_pattern_free": "Break out of spiraling loops and abandon sessions that aren't progressing.",
        }
        return tips.get(factor, "Review your workflow patterns for optimization opportunities.")
