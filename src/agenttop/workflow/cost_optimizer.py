"""Cost optimization analysis for workflow spending."""

from __future__ import annotations

import logging
from collections import defaultdict

from agenttop.workflow.knowledge_base import get_tool_pricing
from agenttop.workflow.models import CostOptimization, WorkflowChain

log = logging.getLogger(__name__)


class CostOptimizer:
    """Analyzes spending patterns and suggests cost optimizations."""

    def __init__(self) -> None:
        self._tool_rankings = {
            # Approximate cost per 1M tokens (input) - lower is cheaper
            "generic": 0.5,      # Free/very cheap
            "kiro": 1.0,
            "copilot": 2.0,     # Per seat, but low marginal cost
            "continue": 5.0,
            "aider": 10.0,
            "cursor": 15.0,
            "claude_code": 30.0,
            "codex": 25.0,
        }

    def analyze_optimization_opportunities(
        self,
        chains: list[WorkflowChain],
    ) -> list[CostOptimization]:
        """Identify cost optimization opportunities.

        Args:
            chains: List of workflow chains

        Returns:
            List of CostOptimization objects
        """
        optimizations: list[CostOptimization] = []

        # Analyze each chain for optimization opportunities
        for chain in chains:
            # Get optimization suggestions for this chain
            chain_optimizations = self._analyze_chain(chain)
            optimizations.extend(chain_optimizations)

        # Find aggregate patterns
        optimizations.extend(self._find_aggregate_opportunities(chains))

        # Sort by potential savings
        optimizations.sort(key=lambda x: x.potential_savings, reverse=True)

        log.info("Found %d cost optimization opportunities", len(optimizations))
        return optimizations

    def _analyze_chain(
        self,
        chain: WorkflowChain,
    ) -> list[CostOptimization]:
        """Analyze a single chain for optimization opportunities."""
        optimizations: list[CostOptimization] = []

        # Check for expensive tool usage
        for tool in chain.tools:
            tool_rank = self._tool_rankings.get(tool.lower(), 20.0)

            if tool_rank > 15:  # Expensive tool
                # Find cheaper alternatives
                alternatives = [
                    t for t, rank in self._tool_rankings.items()
                    if rank < tool_rank * 0.5  # At least 50% cheaper
                ]

                if alternatives:
                    potential_cost = chain.total_cost * 0.5  # Estimate 50% savings
                    savings = chain.total_cost - potential_cost

                    optimizations.append(CostOptimization(
                        pattern_name=f"expensive_tool_{tool}",
                        current_cost=chain.total_cost,
                        optimized_cost=potential_cost,
                        potential_savings=savings,
                        savings_percentage=round((savings / chain.total_cost) * 100, 1),
                        recommendation=f"Consider using {' or '.join(alternatives[:3])} instead of {tool} for similar tasks",
                        alternative_tools=alternatives[:3],
                        confidence="medium" if chain.sample_size >= 3 else "low",
                    ))

        # Check for low efficiency chains (wasted spending)
        if chain.efficiency_score is not None and chain.efficiency_score < 0.4:
            # Potential savings from improving efficiency
            waste_percentage = (1.0 - chain.efficiency_score) * 0.5  # Assume 50% of inefficiency is recoverable
            potential_savings = chain.total_cost * waste_percentage

            optimizations.append(CostOptimization(
                pattern_name="low_efficiency_waste",
                current_cost=chain.total_cost,
                optimized_cost=chain.total_cost - potential_savings,
                potential_savings=potential_savings,
                savings_percentage=round(waste_percentage * 100, 1),
                recommendation="Improve prompt quality and session focus. Low efficiency suggests scattered approach or unclear requirements.",
                alternative_tools=[],
                confidence="high" if chain.sample_size >= 5 else "medium",
            ))

        return optimizations

    def _find_aggregate_opportunities(
        self,
        chains: list[WorkflowChain],
    ) -> list[CostOptimization]:
        """Find optimization opportunities across all chains."""
        optimizations: list[CostOptimization] = []

        # Group by primary tool
        tool_costs: dict[str, list[float]] = defaultdict(list)
        tool_efficiencies: dict[str, list[float]] = defaultdict(list)

        for chain in chains:
            if not chain.tools:
                continue

            primary_tool = chain.tools[0]
            tool_costs[primary_tool].append(chain.total_cost)
            if chain.efficiency_score is not None:
                tool_efficiencies[primary_tool].append(chain.efficiency_score)

        # Find expensive tools with low efficiency
        for tool, costs in tool_costs.items():
            if len(costs) < 3:
                continue

            avg_cost = sum(costs) / len(costs)
            avg_efficiency = (
                sum(tool_efficiencies[tool]) / len(tool_efficiencies[tool])
                if tool in tool_efficiencies else 0.5
            )

            tool_rank = self._tool_rankings.get(tool.lower(), 20.0)

            # Expensive tool with low efficiency
            if tool_rank > 15 and avg_efficiency < 0.5:
                total_cost = sum(costs)
                potential_savings = total_cost * 0.3  # Estimate 30% savings

                # Find alternatives
                alternatives = [
                    t for t, rank in self._tool_rankings.items()
                    if rank < tool_rank * 0.4  # At least 60% cheaper
                ]

                optimizations.append(CostOptimization(
                    pattern_name=f"aggregate_expensive_tool_{tool}",
                    current_cost=total_cost,
                    optimized_cost=total_cost - potential_savings,
                    potential_savings=potential_savings,
                    savings_percentage=30.0,
                    recommendation=f"{tool} is expensive (${avg_cost:.2f}/chain avg) with low efficiency ({avg_efficiency:.2f}). Consider switching to {' or '.join(alternatives[:2])} for similar tasks.",
                    alternative_tools=alternatives[:2],
                    confidence="high" if len(costs) >= 5 else "medium",
                ))

        return optimizations

    def get_total_waste(
        self,
        optimizations: list[CostOptimization],
    ) -> dict:
        """Calculate total waste and potential savings.

        Args:
            optimizations: List of cost optimization opportunities

        Returns:
            Dict with total waste statistics
        """
        if not optimizations:
            return {
                "total_potential_savings": 0.0,
                "total_current_cost": 0.0,
                "optimization_count": 0,
                "by_confidence": {},
            }

        total_savings = sum(o.potential_savings for o in optimizations)
        total_cost = sum(o.current_cost for o in optimizations)

        by_confidence: dict[str, dict] = {}
        for opt in optimizations:
            if opt.confidence not in by_confidence:
                by_confidence[opt.confidence] = {
                    "count": 0,
                    "savings": 0.0,
                }
            by_confidence[opt.confidence]["count"] += 1
            by_confidence[opt.confidence]["savings"] += opt.potential_savings

        return {
            "total_potential_savings": round(total_savings, 2),
            "total_current_cost": round(total_cost, 2),
            "optimization_count": len(optimizations),
            "by_confidence": by_confidence,
        }
