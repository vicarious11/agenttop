"""Workflow analysis: efficiency scoring and insights."""

from __future__ import annotations

import logging
from collections import Counter

from agenttop.models import Session
from agenttop.workflow.correlator import SessionCorrelator
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

log = logging.getLogger(__name__)


class WorkflowAnalyzer:
    """Analyzes workflow patterns and efficiency."""

    def __init__(self) -> None:
        self._correlator = SessionCorrelator()
        self._pattern_detector = WorkflowPatternDetector()

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
            Dict with analysis results
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

        # Calculate aggregate metrics
        metrics = self._calculate_metrics(chains_with_efficiency, transitions)

        # Get recommendations
        recommendations = self._generate_recommendations(chains_with_efficiency, patterns)

        return {
            "patterns": patterns,
            "metrics": metrics,
            "recommendations": recommendations,
            "chain_count": len(chains),
            "transition_count": len(transitions),
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

    def _calculate_metrics(
        self,
        chains: list[WorkflowChain],
        transitions: list[ToolTransition],
    ) -> WorkflowMetrics:
        """Calculate aggregate workflow metrics."""
        # Tool usage distribution from chains (convert Counter to dict for JSON serialization)
        tool_dist: dict[str, int] = dict(Counter(tool for chain in chains for tool in chain.tools))

        # Transition matrix
        transition_matrix = self._correlator.get_transition_matrix(transitions)

        # Average chain length (number of sessions per chain)
        avg_chain_length = sum(len(c.session_ids) for c in chains) / len(chains) if chains else 0

        # Average efficiency
        efficiencies = [c.efficiency_score for c in chains if c.efficiency_score is not None]
        avg_efficiency = sum(efficiencies) / len(efficiencies) if efficiencies else 0.5

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

        return WorkflowMetrics(
            total_chains=len(chains),
            total_transitions=len(transitions),
            avg_chain_length=round(avg_chain_length, 2),
            avg_efficiency_score=round(avg_efficiency, 2),
            most_common_pattern=most_common_pattern,
            most_efficient_pattern=most_efficient_pattern,
            tool_usage_distribution=tool_dist,
            transition_matrix=transition_matrix,
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
