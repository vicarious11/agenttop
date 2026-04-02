"""Productivity scoring - composite metric combining multiple factors."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from agenttop.workflow.anti_patterns import AntiPattern
from agenttop.workflow.models import WorkflowChain

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductivityFactors:
    """Individual factors that contribute to productivity score."""
    efficiency: float = 0.5  # 0.0 - 1.0
    cost_effectiveness: float = 0.5  # 0.0 - 1.0
    momentum: float = 0.5  # 0.0 - 1.0
    focus: float = 0.5  # 0.0 - 1.0 (inverse of tool switching)
    anti_pattern_free: float = 1.0  # 0.0 - 1.0 (1.0 = no anti-patterns)


class ProductivityScorer:
    """Calculates composite productivity scores."""

    def __init__(self) -> None:
        # Weights for each factor (sum = 1.0)
        self._weights = {
            "efficiency": 0.25,
            "cost_effectiveness": 0.20,
            "momentum": 0.20,
            "focus": 0.15,
            "anti_pattern_free": 0.20,
        }

    def calculate_productivity_score(
        self,
        chains: list[WorkflowChain],
        anti_patterns: list[AntiPattern],
    ) -> tuple[float, dict]:
        """Calculate overall productivity score for a set of chains.

        Args:
            chains: List of workflow chains
            anti_patterns: List of detected anti-patterns

        Returns:
            Tuple of (overall_score, breakdown_by_factor)
        """
        if not chains:
            return 0.5, {}

        # Calculate individual factors
        efficiency = self._calculate_efficiency_factor(chains)
        cost_effectiveness = self._calculate_cost_effectiveness(chains)
        momentum = self._calculate_momentum_factor(chains)
        focus = self._calculate_focus_factor(chains)
        anti_pattern_free = self._calculate_anti_pattern_factor(chains, anti_patterns)

        # Calculate weighted score
        overall = (
            efficiency * self._weights["efficiency"] +
            cost_effectiveness * self._weights["cost_effectiveness"] +
            momentum * self._weights["momentum"] +
            focus * self._weights["focus"] +
            anti_pattern_free * self._weights["anti_pattern_free"]
        )

        breakdown = {
            "efficiency": round(efficiency, 2),
            "cost_effectiveness": round(cost_effectiveness, 2),
            "momentum": round(momentum, 2),
            "focus": round(focus, 2),
            "anti_pattern_free": round(anti_pattern_free, 2),
            "overall": round(overall, 2),
        }

        return round(overall, 2), breakdown

    def _calculate_efficiency_factor(self, chains: list[WorkflowChain]) -> float:
        """Calculate efficiency factor (0.0 - 1.0)."""
        efficiencies = [c.efficiency_score for c in chains if c.efficiency_score is not None]

        if not efficiencies:
            return 0.5

        return sum(efficiencies) / len(efficiencies)

    def _calculate_cost_effectiveness(self, chains: list[WorkflowChain]) -> float:
        """Calculate cost effectiveness (value per dollar).

        Higher is better - getting more value for less cost.
        """
        if not chains:
            return 0.5

        # Calculate tokens per dollar for each chain
        tokens_per_dollar = []
        for chain in chains:
            if chain.total_cost > 0:
                tokens_per_dollar.append(chain.total_tokens / chain.total_cost)

        if not tokens_per_dollar:
            return 0.5

        avg_tokens_per_dollar = sum(tokens_per_dollar) / len(tokens_per_dollar)

        # Normalize: 100k tokens/$1 = 1.0, 10k tokens/$1 = 0.0
        # This is a simplified model
        normalized = min(1.0, max(0.0, (avg_tokens_per_dollar - 10000) / 90000))

        return normalized

    def _calculate_momentum_factor(self, chains: list[WorkflowChain]) -> float:
        """Calculate momentum factor (sessions build on each other)."""
        momenta = [c.momentum_score for c in chains if c.momentum_score is not None]

        if not momenta:
            return 0.5

        return sum(momenta) / len(momenta)

    def _calculate_focus_factor(self, chains: list[WorkflowChain]) -> float:
        """Calculate focus factor (inverse of excessive tool switching)."""
        if not chains:
            return 0.5

        focus_scores = []

        for chain in chains:
            num_tools = len(set(chain.tools))

            # Fewer tools = more focused
            if num_tools == 1:
                focus = 1.0
            elif num_tools == 2:
                focus = 0.9
            elif num_tools == 3:
                focus = 0.7
            else:
                focus = max(0.0, 1.0 - (num_tools - 3) * 0.15)

            focus_scores.append(focus)

        return sum(focus_scores) / len(focus_scores)

    def _calculate_anti_pattern_factor(
        self,
        chains: list[WorkflowChain],
        anti_patterns: list[AntiPattern],
    ) -> float:
        """Calculate anti-pattern penalty (1.0 = clean, 0.0 = many anti-patterns)."""
        if not chains:
            return 1.0

        # Count anti-patterns affecting sessions
        affected_sessions: set[str] = set()

        for ap in anti_patterns:
            affected_sessions.update(ap.affected_sessions)

        if not affected_sessions:
            return 1.0

        # Calculate what fraction of sessions are affected
        total_sessions = sum(c.sample_size for c in chains)
        affected_count = len(affected_sessions)

        affected_ratio = affected_count / total_sessions if total_sessions > 0 else 0

        # Penalty: more affected = lower score
        # 0% affected = 1.0, 50% affected = 0.5, 100% affected = 0.0
        return max(0.0, 1.0 - affected_ratio)

    def get_productivity_grade(self, score: float) -> str:
        """Convert productivity score to letter grade.

        Args:
            score: Productivity score (0.0 - 1.0)

        Returns:
            Letter grade (A, B, C, D, F)
        """
        if score >= 0.9:
            return "A"
        elif score >= 0.8:
            return "B"
        elif score >= 0.7:
            return "C"
        elif score >= 0.6:
            return "D"
        else:
            return "F"

    def get_improvement_suggestions(
        self,
        breakdown: dict,
    ) -> list[str]:
        """Get specific improvement suggestions based on factor breakdown.

        Args:
            breakdown: Dict of factor scores from calculate_productivity_score

        Returns:
            List of improvement suggestions
        """
        suggestions: list[str] = []

        # Check each factor
        if breakdown["efficiency"] < 0.5:
            suggestions.append("Improve efficiency by planning your requests better and providing clearer context.")

        if breakdown["cost_effectiveness"] < 0.5:
            suggestions.append("Improve cost effectiveness by using more concise prompts and considering cheaper alternatives for simple tasks.")

        if breakdown["momentum"] < 0.5:
            suggestions.append("Build momentum by staying focused on related tasks and reusing session context.")

        if breakdown["focus"] < 0.5:
            suggestions.append("Improve focus by reducing tool switching. Pick one tool and stick with it for the task.")

        if breakdown["anti_pattern_free"] < 0.7:
            suggestions.append("Address detected anti-patterns (spiraling, excessive switching, etc.) to improve productivity.")

        # Add positive reinforcement if doing well
        if breakdown["overall"] >= 0.8:
            suggestions.append("Great productivity! Your workflow is efficient and effective.")

        return suggestions

    def calculate_chain_productivity(
        self,
        chain: WorkflowChain,
    ) -> float:
        """Calculate productivity score for a single chain.

        Args:
            chain: WorkflowChain to score

        Returns:
            Productivity score (0.0 - 1.0)
        """
        factors = ProductivityFactors(
            efficiency=chain.efficiency_score or 0.5,
            cost_effectiveness=self._calculate_chain_cost_effectiveness(chain),
            momentum=chain.momentum_score or 0.5,
            focus=self._calculate_chain_focus(chain),
            anti_pattern_free=1.0,  # Would need anti-pattern data for this
        )

        score = (
            factors.efficiency * self._weights["efficiency"] +
            factors.cost_effectiveness * self._weights["cost_effectiveness"] +
            factors.momentum * self._weights["momentum"] +
            factors.focus * self._weights["focus"] +
            factors.anti_pattern_free * self._weights["anti_pattern_free"]
        )

        return round(score, 2)

    def _calculate_chain_cost_effectiveness(self, chain: WorkflowChain) -> float:
        """Calculate cost effectiveness for a single chain."""
        if chain.total_cost <= 0:
            return 0.5

        tokens_per_dollar = chain.total_tokens / chain.total_cost
        return min(1.0, max(0.0, (tokens_per_dollar - 10000) / 90000))

    def _calculate_chain_focus(self, chain: WorkflowChain) -> float:
        """Calculate focus score for a single chain."""
        num_tools = len(set(chain.tools))

        if num_tools == 1:
            return 1.0
        elif num_tools == 2:
            return 0.9
        elif num_tools == 3:
            return 0.7
        else:
            return max(0.0, 1.0 - (num_tools - 3) * 0.15)
