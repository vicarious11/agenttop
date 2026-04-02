"""Workflow simulation for what-if scenario modeling.

This module allows simulating the impact of potential workflow changes
before implementing them, helping make data-driven decisions.
"""

from __future__ import annotations

import copy
import time
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from agenttop.workflow.models import (
    AntiPatternType,
    SimulationResult,
    WorkflowChain,
    WorkflowMetrics,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class SimulationConfig:
    """Configuration for workflow simulation."""
    default_cost_per_token: float = 0.00001  # $10 per million tokens
    switching_cost_seconds: float = 120  # Time cost per tool switch
    switching_cost_dollars: float = 0.50  # Dollar cost per switch
    efficiency_improvement_factor: float = 0.15  # Expected improvement from fixing anti-patterns


class WorkflowSimulator:
    """Simulates what-if scenarios for workflow optimization.

    Supports scenarios like:
    - Reducing tool switches
    - Using cheaper alternatives
    - Improving prompt efficiency
    - Consolidating sessions
    - Adopting recommended tools
    """

    def __init__(self, config: SimulationConfig | None = None) -> None:
        """Initialize the workflow simulator.

        Args:
            config: Configuration for simulation parameters
        """
        self._config = config or SimulationConfig()

    def simulate_reduce_switching(
        self,
        chains: Sequence[WorkflowChain],
        target_reduction: float = 0.25,
    ) -> SimulationResult:
        """Simulate the impact of reducing tool switches.

        Args:
            chains: Current workflow chains
            target_reduction: Target reduction in switches (0.0 - 1.0)

        Returns:
            Simulation result with estimated impacts
        """
        current_switches = sum(len(c.tools) - 1 for c in chains if len(c.tools) > 1)
        target_switches = int(current_switches * (1 - target_reduction))

        # Calculate current metrics
        current_cost = sum(c.total_cost for c in chains)
        current_eff = sum(
            c.efficiency_score for c in chains
            if c.efficiency_score is not None
        ) / len(chains) if chains else 0.5

        # Simulate reduced switching
        simulated_chains = []
        for chain in chains:
            # Calculate reduction for this chain
            chain_switches = max(0, len(chain.tools) - 1)
            reduction = int(chain_switches * target_reduction)
            new_switches = max(1, chain_switches - reduction)

            # Create simulated chain with reduced switches
            new_tools = chain.tools[:new_switches + 1] if chain.tools else []

            # Estimate efficiency improvement
            efficiency_gain = min(
                0.2,
                reduction * 0.05,  # 5% improvement per eliminated switch
            )
            new_efficiency = (
                chain.efficiency_score + efficiency_gain
                if chain.efficiency_score is not None
                else 0.5
            )

            simulated_chains.append(replace(
                chain,
                tools=new_tools,
                efficiency_score=min(1.0, new_efficiency),
            ))

        # Calculate simulated metrics
        simulated_eff = sum(
            c.efficiency_score for c in simulated_chains
            if c.efficiency_score is not None
        ) / len(simulated_chains) if simulated_chains else 0.5

        # Cost impact from reduced switching
        switching_savings = (
            (current_switches - target_switches) * self._config.switching_cost_dollars
        )
        simulated_cost = current_cost - switching_savings

        changes = [
            ("tool_switches", current_switches - target_switches, "improvement"),
            ("efficiency_score", simulated_eff - current_eff, "improvement"),
            ("total_cost", switching_savings, "improvement"),
        ]

        return SimulationResult(
            scenario_name=f"Reduce Tool Switching by {target_reduction:.0%}",
            description=f"Reduce tool switches from {current_switches} to {target_switches}",
            current_metrics={
                "total_switches": float(current_switches),
                "efficiency_score": current_eff,
                "total_cost": current_cost,
            },
            simulated_metrics={
                "total_switches": float(target_switches),
                "efficiency_score": simulated_eff,
                "total_cost": simulated_cost,
            },
            changes=changes,
            estimated_cost_impact=-switching_savings,  # Negative = savings
            estimated_efficiency_impact=simulated_eff - current_eff,
            assumptions=[
                f"Each eliminated switch saves {self._config.switching_cost_dollars:.2f}",
                "Efficiency improves 5% per eliminated switch (max 20%)",
                "No loss of functionality from fewer switches",
            ],
            confidence=0.7,
            risk_factors=[
                "May limit access to specialized tool features",
                "Could reduce flexibility for certain task types",
                "Requires better upfront planning",
            ],
        )

    def simulate_switch_to_cheaper_tool(
        self,
        chains: Sequence[WorkflowChain],
        expensive_tool: str,
        cheaper_alternative: str,
        cost_reduction_ratio: float = 0.5,
    ) -> SimulationResult:
        """Simulate switching from an expensive to cheaper tool.

        Args:
            chains: Current workflow chains
            expensive_tool: Tool to replace
            cheaper_alternative: Cheaper alternative
            cost_reduction_ratio: Expected cost reduction (0.0 - 1.0)

        Returns:
            Simulation result with estimated impacts
        """
        # Find chains using the expensive tool
        affected_chains = [
            c for c in chains
            if expensive_tool in c.tools
        ]

        if not affected_chains:
            return SimulationResult(
                scenario_name=f"Switch to {cheaper_alternative}",
                description=f"No chains use {expensive_tool}",
                current_metrics={},
                simulated_metrics={},
                changes=[],
                estimated_cost_impact=0.0,
                estimated_efficiency_impact=0.0,
                assumptions=["No affected chains found"],
                confidence=0.0,
                risk_factors=[],
            )

        # Calculate current costs
        current_cost = sum(c.total_cost for c in affected_chains)

        # Simulate switching
        simulated_savings = current_cost * cost_reduction_ratio
        simulated_cost = current_cost - simulated_savings

        # Efficiency might slightly decrease with new tool
        current_eff = sum(
            c.efficiency_score for c in affected_chains
            if c.efficiency_score is not None
        ) / len(affected_chains) if affected_chains else 0.5

        # Assume slight efficiency dip during learning curve
        efficiency_impact = -0.05  # 5% temporary decrease

        changes = [
            ("total_cost", simulated_savings, "improvement"),
            ("efficiency_score", efficiency_impact, "decline"),
        ]

        return SimulationResult(
            scenario_name=f"Switch {expensive_tool} → {cheaper_alternative}",
            description=(
                f"Replace {expensive_tool} with {cheaper_alternative} for "
                f"{len(affected_chains)} affected chains"
            ),
            current_metrics={
                "affected_chains": float(len(affected_chains)),
                "current_cost": current_cost,
                "efficiency_score": current_eff,
            },
            simulated_metrics={
                "affected_chains": float(len(affected_chains)),
                "simulated_cost": simulated_cost,
                "efficiency_score": current_eff + efficiency_impact,
            },
            changes=changes,
            estimated_cost_impact=-simulated_savings,
            estimated_efficiency_impact=efficiency_impact,
            assumptions=[
                f"{cheaper_alternative} provides {cost_reduction_ratio:.0%} cost savings",
                "Temporary 5% efficiency dip during learning period",
                "Full recovery of efficiency after 2-3 weeks",
            ],
            confidence=0.6,
            risk_factors=[
                f"{cheaper_alternative} may lack some features of {expensive_tool}",
                "Team learning curve may affect short-term productivity",
                "Quality of output may vary during transition",
            ],
        )

    def simulate_improve_prompt_efficiency(
        self,
        chains: Sequence[WorkflowChain],
        token_reduction: float = 0.20,
    ) -> SimulationResult:
        """Simulate the impact of improving prompt efficiency.

        Args:
            chains: Current workflow chains
            token_reduction: Target reduction in token usage (0.0 - 1.0)

        Returns:
            Simulation result with estimated impacts
        """
        # Calculate current metrics
        current_tokens = sum(c.total_tokens for c in chains)
        current_cost = sum(c.total_cost for c in chains)

        # Simulate improved efficiency
        simulated_tokens = current_tokens * (1 - token_reduction)
        simulated_cost = current_cost * (1 - token_reduction)

        # Better prompts typically improve efficiency too
        current_eff = sum(
            c.efficiency_score for c in chains
            if c.efficiency_score is not None
        ) / len(chains) if chains else 0.5

        efficiency_gain = token_reduction * 0.3  # 30% of token reduction as efficiency gain
        simulated_eff = min(1.0, current_eff + efficiency_gain)

        changes = [
            ("total_tokens", current_tokens - simulated_tokens, "improvement"),
            ("total_cost", current_cost - simulated_cost, "improvement"),
            ("efficiency_score", efficiency_gain, "improvement"),
        ]

        return SimulationResult(
            scenario_name=f"Improve Prompt Efficiency ({token_reduction:.0%} reduction)",
            description=f"Reduce token usage through better prompt engineering",
            current_metrics={
                "total_tokens": float(current_tokens),
                "total_cost": current_cost,
                "efficiency_score": current_eff,
            },
            simulated_metrics={
                "total_tokens": simulated_tokens,
                "total_cost": simulated_cost,
                "efficiency_score": simulated_eff,
            },
            changes=changes,
            estimated_cost_impact=-(current_cost - simulated_cost),
            estimated_efficiency_impact=efficiency_gain,
            assumptions=[
                f"Can achieve {token_reduction:.0%} reduction through prompt optimization",
                "No loss of output quality from more focused prompts",
                "Efficiency improves due to better context understanding",
            ],
            confidence=0.65,
            risk_factors=[
                "Requires investment in prompt engineering training",
                "May take time to refine prompts for each use case",
                "Some tasks may require more verbose prompts",
            ],
        )

    def simulate_consolidate_sessions(
        self,
        chains: Sequence[WorkflowChain],
        consolidation_factor: float = 0.3,
    ) -> SimulationResult:
        """Simulate the impact of consolidating fragmented sessions.

        Args:
            chains: Current workflow chains
            consolidation_factor: Target reduction in chain count (0.0 - 1.0)

        Returns:
            Simulation result with estimated impacts
        """
        current_chains = len(chains)

        # Calculate current metrics
        current_cost = sum(c.total_cost for c in chains)
        current_eff = sum(
            c.efficiency_score for c in chains
            if c.efficiency_score is not None
        ) / len(chains) if chains else 0.5

        # Simulate consolidation
        target_chains = int(current_chains * (1 - consolidation_factor))

        # Consolidated sessions have less overhead
        overhead_savings = (current_chains - target_chains) * 0.1  # $0.10 per session overhead
        simulated_cost = current_cost - overhead_savings

        # Better focus in consolidated sessions
        efficiency_gain = consolidation_factor * 0.2  # Up to 20% improvement
        simulated_eff = min(1.0, current_eff + efficiency_gain)

        changes = [
            ("num_chains", current_chains - target_chains, "improvement"),
            ("session_overhead", overhead_savings, "improvement"),
            ("efficiency_score", efficiency_gain, "improvement"),
        ]

        return SimulationResult(
            scenario_name=f"Consolidate Sessions ({consolidation_factor:.0%} reduction)",
            description=f"Merge fragmented sessions into longer, focused workflows",
            current_metrics={
                "num_chains": float(current_chains),
                "total_cost": current_cost,
                "efficiency_score": current_eff,
            },
            simulated_metrics={
                "num_chains": float(target_chains),
                "total_cost": simulated_cost,
                "efficiency_score": simulated_eff,
            },
            changes=changes,
            estimated_cost_impact=-overhead_savings,
            estimated_efficiency_impact=efficiency_gain,
            assumptions=[
                f"Can merge {consolidation_factor:.0%} of sessions without losing context",
                "Consolidated sessions maintain or improve quality",
                "Better focus leads to efficiency gains",
            ],
            confidence=0.6,
            risk_factors=[
                "May require better task planning upfront",
                "Longer sessions could lead to fatigue",
                "Harder to track progress across consolidated sessions",
            ],
        )

    def simulate_fix_anti_patterns(
        self,
        chains: Sequence[WorkflowChain],
        anti_patterns: list[tuple[str, float]],  # (pattern_type, frequency)
    ) -> SimulationResult:
        """Simulate the impact of fixing detected anti-patterns.

        Args:
            chains: Current workflow chains
            anti_patterns: List of (pattern_type, frequency) tuples

        Returns:
            Simulation result with estimated impacts
        """
        current_cost = sum(c.total_cost for c in chains)
        current_eff = sum(
            c.efficiency_score for c in chains
            if c.efficiency_score is not None
        ) / len(chains) if chains else 0.5

        # Calculate impact based on anti-pattern types
        total_impact = 0.0
        fixes_descriptions = []

        for pattern_type, frequency in anti_patterns:
            match pattern_type:
                case AntiPatternType.EXCESSIVE_SWITCHING:
                    impact = frequency * 2.0  # $2 per switch
                    fixes_descriptions.append(f"Fix {frequency} excessive switching cases")
                case AntiPatternType.SPIRALING:
                    impact = frequency * 5.0  # $5 per spiral
                    fixes_descriptions.append(f"Fix {frequency} spiraling patterns")
                case AntiPatternType.ABANDONED_SESSION:
                    impact = frequency * 3.0  # $3 per abandoned session
                    fixes_descriptions.append(f"Fix {frequency} abandoned sessions")
                case AntiPatternType.TOKEN_INEFFICIENCY:
                    impact = frequency * 1.5  # $1.5 per inefficient session
                    fixes_descriptions.append(f"Fix {frequency} token inefficiencies")
                case AntiPatternType.COST_BLOAT:
                    impact = frequency * 4.0  # $4 per cost bloat
                    fixes_descriptions.append(f"Fix {frequency} cost bloat cases")
                case AntiPatternType.CONTEXT_THRASHING:
                    impact = frequency * 2.5  # $2.5 per thrash
                    fixes_descriptions.append(f"Fix {frequency} context thrashing cases")
                case _:
                    impact = frequency * 1.0

            total_impact += impact

        # Efficiency improvement from fixing anti-patterns
        efficiency_gain = min(0.25, len(anti_patterns) * 0.05)
        simulated_eff = min(1.0, current_eff + efficiency_gain)

        changes = [
            ("anti_patterns_fixed", float(len(anti_patterns)), "improvement"),
            ("cost_savings", total_impact, "improvement"),
            ("efficiency_score", efficiency_gain, "improvement"),
        ]

        return SimulationResult(
            scenario_name="Fix Detected Anti-Patterns",
            description=f"Address {len(anti_patterns)} types of workflow anti-patterns",
            current_metrics={
                "anti_pattern_count": float(len(anti_patterns)),
                "total_cost": current_cost,
                "efficiency_score": current_eff,
            },
            simulated_metrics={
                "anti_pattern_count": 0.0,
                "total_cost": current_cost - total_impact,
                "efficiency_score": simulated_eff,
            },
            changes=changes,
            estimated_cost_impact=-total_impact,
            estimated_efficiency_impact=efficiency_gain,
            assumptions=[
                "All anti-patterns can be fixed with recommended actions",
                "Efficiency gains compound from fixing multiple patterns",
                "Cost savings are conservative estimates",
            ],
            confidence=0.7,
            risk_factors=[
                "Fixing anti-patterns may require behavior changes",
                "Some patterns may be deeply ingrained in workflows",
                "Initial productivity dip during adjustment period",
            ],
        )

    def run_batch_simulation(
        self,
        chains: Sequence[WorkflowChain],
        scenarios: list[dict] | None = None,
    ) -> list[SimulationResult]:
        """Run multiple simulations and return results.

        Args:
            chains: Current workflow chains
            scenarios: List of scenario configs. If None, runs default scenarios.

        Returns:
            List of simulation results
        """
        if scenarios is None:
            scenarios = [
                {"type": "reduce_switching", "params": {"target_reduction": 0.25}},
                {"type": "reduce_switching", "params": {"target_reduction": 0.5}},
                {"type": "improve_prompts", "params": {"token_reduction": 0.2}},
                {"type": "consolidate", "params": {"consolidation_factor": 0.3}},
            ]

        results: list[SimulationResult] = []

        for scenario in scenarios:
            match scenario["type"]:
                case "reduce_switching":
                    result = self.simulate_reduce_switching(
                        chains,
                        **scenario.get("params", {}),
                    )
                case "improve_prompts":
                    result = self.simulate_improve_prompt_efficiency(
                        chains,
                        **scenario.get("params", {}),
                    )
                case "consolidate":
                    result = self.simulate_consolidate_sessions(
                        chains,
                        **scenario.get("params", {}),
                    )
                case "switch_tool":
                    result = self.simulate_switch_to_cheaper_tool(
                        chains,
                        **scenario.get("params", {}),
                    )
                case _:
                    continue

            results.append(result)

        # Sort by total impact (cost + efficiency)
        results.sort(
            key=lambda r: abs(r.estimated_cost_impact) + r.estimated_efficiency_impact * 100,
            reverse=True,
        )

        return results
