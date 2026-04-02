"""Workflow recommendation engine - synthesizes analysis into actionable recommendations.

This module combines insights from all other analyzers to generate
prioritized, actionable recommendations for workflow improvement.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from agenttop.workflow.models import (
    AntiPattern,
    AntiPatternType,
    CostOptimization,
    RecommendationPriority,
    ToolAffinity,
    WorkflowActionableRecommendation,
    WorkflowChain,
    WorkflowMetrics,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class RecommendationConfig:
    """Configuration for recommendation generation."""
    min_cost_impact: float = 1.0  # Minimum USD impact to flag
    min_efficiency_gain: float = 0.05  # Minimum 5% efficiency gain to flag
    max_recommendations: int = 10  # Maximum recommendations to generate
    include_low_priority: bool = False  # Whether to include low priority items


class WorkflowRecommender:
    """Generates actionable workflow recommendations from analysis results.

    The recommender synthesizes outputs from:
    - AntiPatternDetector: Harmful patterns to address
    - CostOptimizer: Wasteful spending to fix
    - ToolAffinityAnalyzer: Better tool choices for contexts
    - ProductivityScorer: Areas for productivity improvement
    """

    def __init__(self, config: RecommendationConfig | None = None) -> None:
        """Initialize the recommender with optional configuration.

        Args:
            config: Configuration for recommendation generation
        """
        self._config = config or RecommendationConfig()

    def generate_recommendations(
        self,
        chains: Sequence[WorkflowChain],
        metrics: WorkflowMetrics,
        anti_patterns: Sequence[AntiPattern],
        cost_optimizations: Sequence[CostOptimization],
        tool_affinities: Sequence[ToolAffinity],
    ) -> list[WorkflowActionableRecommendation]:
        """Generate actionable recommendations from all analysis results.

        Args:
            chains: All analyzed workflow chains
            metrics: Aggregated workflow metrics
            anti_patterns: Detected anti-patterns
            cost_optimizations: Cost optimization opportunities
            tool_affinities: Tool affinity analysis results

        Returns:
            Prioritized list of actionable recommendations
        """
        recommendations: list[WorkflowActionableRecommendation] = []

        # Generate recommendations from different sources
        recommendations.extend(
            self._recommend_from_anti_patterns(anti_patterns)
        )
        recommendations.extend(
            self._recommend_from_costs(cost_optimizations)
        )
        recommendations.extend(
            self._recommend_from_affinities(tool_affinities, chains)
        )
        recommendations.extend(
            self._recommend_from_metrics(metrics, chains)
        )

        # Sort by priority and impact
        prioritized = self._prioritize_recommendations(recommendations)

        # Limit to max recommendations
        return prioritized[: self._config.max_recommendations]

    def _recommend_from_anti_patterns(
        self, anti_patterns: Sequence[AntiPattern],
    ) -> list[WorkflowActionableRecommendation]:
        """Generate recommendations from detected anti-patterns."""
        recommendations = []

        for pattern in anti_patterns:
            # Skip low severity if not including low priority
            if pattern.severity == "low" and not self._config.include_low_priority:
                continue

            priority = self._severity_to_priority(pattern.severity)

            # Generate specific action steps based on pattern type
            action_steps = self._get_action_steps_for_pattern(pattern)

            rec = WorkflowActionableRecommendation(
                id=f"ap_{pattern.id}",
                title=f"Fix {pattern.type.value.replace('_', ' ').title()} Pattern",
                description=pattern.description,
                priority=priority,
                category="workflow",
                estimated_impact=f"Save ${pattern.estimated_cost_impact:.2f} per occurrence",
                effort_required=self._estimate_effort(pattern.type),
                action_steps=action_steps,
                related_anti_patterns=[pattern.type],
                expected_savings_usd=pattern.estimated_cost_impact,
                confidence=0.8,
                created_at=time.time(),
            )
            recommendations.append(rec)

        return recommendations

    def _recommend_from_costs(
        self, optimizations: Sequence[CostOptimization],
    ) -> list[WorkflowActionableRecommendation]:
        """Generate recommendations from cost optimization opportunities."""
        recommendations = []

        for opt in optimizations:
            if opt.potential_savings < self._config.min_cost_impact:
                continue

            priority = self._savings_to_priority(opt.potential_savings)

            rec = WorkflowActionableRecommendation(
                id=f"cost_{opt.pattern_name}",
                title=f"Reduce Costs: {opt.pattern_name}",
                description=opt.recommendation,
                priority=priority,
                category="cost",
                estimated_impact=f"Save ${opt.potential_savings:.2f} ({opt.savings_percentage:.1f}%)",
                effort_required="low",
                action_steps=self._get_cost_action_steps(opt),
                related_anti_patterns=[],
                expected_savings_usd=opt.potential_savings,
                confidence=self._confidence_to_float(opt.confidence),
                created_at=time.time(),
            )
            recommendations.append(rec)

        return recommendations

    def _recommend_from_affinities(
        self,
        affinities: Sequence[ToolAffinity],
        chains: Sequence[WorkflowChain],
    ) -> list[WorkflowActionableRecommendation]:
        """Generate recommendations from tool affinity analysis."""
        recommendations = []

        # Find high-affinity tools that aren't being used optimally
        recommended_tools = [a for a in affinities if a.recommended]
        recommended_by_context: dict[str, list[ToolAffinity]] = {}

        for affinity in recommended_tools:
            context = affinity.context
            if context not in recommended_by_context:
                recommended_by_context[context] = []
            recommended_by_context[context].append(affinity)

        # Generate recommendation for each context with good alternatives
        for context, ctx_affinities in recommended_by_context.items():
            # Find best tool for this context
            best = max(ctx_affinities, key=lambda a: a.success_rate * a.avg_efficiency)

            # Check if this tool is being underutilized
            current_usage = sum(
                1 for c in chains
                if c.project and context.lower() in c.project.lower()
            )
            total_chains = len(chains)
            usage_rate = current_usage / total_chains if total_chains > 0 else 0

            # Only recommend if not already widely used
            if usage_rate < 0.5 and best.success_rate > 0.7:
                potential_savings = self._estimate_affinity_savings(best, chains)

                rec = WorkflowActionableRecommendation(
                    id=f"aff_{context}_{best.tool}",
                    title=f"Use {best.tool} for {context}",
                    description=(
                        f"{best.tool} shows {best.success_rate:.1%} success rate "
                        f"and {best.avg_efficiency:.1%} efficiency for {context} tasks"
                    ),
                    priority=RecommendationPriority.MEDIUM,
                    category="efficiency",
                    estimated_impact=f"Improve efficiency by {potential_savings:.1%}",
                    effort_required="medium",
                    action_steps=[
                        f"Identify {context} tasks in your workflow",
                        f"Try using {best.tool} for these tasks",
                        f"Monitor efficiency for 1-2 weeks",
                        f"Compare results with current tool choices",
                    ],
                    related_anti_patterns=[],
                    expected_savings_usd=potential_savings * 100,  # Rough estimate
                    confidence=0.6,
                    created_at=time.time(),
                )
                recommendations.append(rec)

        return recommendations

    def _recommend_from_metrics(
        self,
        metrics: WorkflowMetrics,
        chains: Sequence[WorkflowChain],
    ) -> list[WorkflowActionableRecommendation]:
        """Generate recommendations from overall workflow metrics."""
        recommendations = []

        # Low overall efficiency
        if metrics.avg_efficiency_score < 0.6:
            recommendations.append(WorkflowActionableRecommendation(
                id="eff_overall",
                title="Improve Overall Workflow Efficiency",
                description=(
                    f"Current efficiency score is {metrics.avg_efficiency_score:.1%}, "
                    f"below the 60% threshold"
                ),
                priority=RecommendationPriority.HIGH,
                category="efficiency",
                estimated_impact="Improve to 70%+ efficiency",
                effort_required="high",
                action_steps=[
                    "Review session patterns for bottlenecks",
                    "Reduce unnecessary tool switches",
                    "Focus on longer, more focused sessions",
                    "Use tool recommendations based on task type",
                ],
                related_anti_patterns=[AntiPatternType.EXCESSIVE_SWITCHING],
                expected_savings_usd=metrics.cost_savings_potential * 0.5,
                confidence=0.7,
                created_at=time.time(),
            ))

        # High wasted tokens
        if metrics.total_wasted_tokens > 100_000:
            waste_cost = metrics.total_wasted_tokens * 0.00001  # Rough $ per token
            recommendations.append(WorkflowActionableRecommendation(
                id="token_waste",
                title="Reduce Token Waste",
                description=(
                    f"Over {metrics.total_wasted_tokens:,} tokens wasted on inefficient patterns, "
                    f"costing approximately ${waste_cost:.2f}"
                ),
                priority=RecommendationPriority.HIGH,
                category="cost",
                estimated_impact=f"Save ${waste_cost:.2f} monthly",
                effort_required="medium",
                action_steps=[
                    "Review abandoned sessions",
                    "Use smaller, more focused prompts",
                    "Leverage context caching where available",
                    "Avoid re-prompting similar requests",
                ],
                related_anti_patterns=[
                    AntiPatternType.ABANDONED_SESSION,
                    AntiPatternType.TOKEN_INEFFICIENCY,
                ],
                expected_savings_usd=waste_cost,
                confidence=0.75,
                created_at=time.time(),
            ))

        # Excessive tool switching
        if metrics.avg_chain_length > 4:
            switch_cost = (metrics.avg_chain_length - 3) * 0.5  # Rough cost per switch
            recommendations.append(WorkflowActionableRecommendation(
                id="tool_switching",
                title="Reduce Excessive Tool Switching",
                description=(
                    f"Average chain length is {metrics.avg_chain_length:.1f} tools, "
                    f"indicating frequent switching that may hurt productivity"
                ),
                priority=RecommendationPriority.MEDIUM,
                category="workflow",
                estimated_impact=f"Save ${switch_cost:.2f} in context loss",
                effort_required="medium",
                action_steps=[
                    "Plan your tool usage before starting work",
                    "Complete related tasks in the same tool",
                    "Use tool-specific features before switching",
                    "Batch similar tasks together",
                ],
                related_anti_patterns=[AntiPatternType.EXCESSIVE_SWITCHING],
                expected_savings_usd=switch_cost,
                confidence=0.65,
                created_at=time.time(),
            ))

        return recommendations

    def _prioritize_recommendations(
        self, recommendations: list[WorkflowActionableRecommendation],
    ) -> list[WorkflowActionableRecommendation]:
        """Sort recommendations by priority and expected impact."""
        priority_order = {
            RecommendationPriority.CRITICAL: 0,
            RecommendationPriority.HIGH: 1,
            RecommendationPriority.MEDIUM: 2,
            RecommendationPriority.LOW: 3,
            RecommendationPriority.INFO: 4,
        }

        def sort_key(rec: WorkflowActionableRecommendation) -> tuple[int, float]:
            priority_score = priority_order.get(rec.priority, 5)
            # Higher confidence and savings come first within priority
            impact_score = rec.expected_savings_usd * rec.confidence
            return (priority_score, -impact_score)

        return sorted(recommendations, key=sort_key)

    def _severity_to_priority(self, severity: str) -> RecommendationPriority:
        """Convert anti-pattern severity to recommendation priority."""
        mapping = {
            "critical": RecommendationPriority.CRITICAL,
            "high": RecommendationPriority.HIGH,
            "medium": RecommendationPriority.MEDIUM,
            "low": RecommendationPriority.LOW,
        }
        return mapping.get(severity, RecommendationPriority.INFO)

    def _savings_to_priority(self, savings: float) -> RecommendationPriority:
        """Convert potential savings to priority."""
        if savings > 50:
            return RecommendationPriority.CRITICAL
        if savings > 20:
            return RecommendationPriority.HIGH
        if savings > 5:
            return RecommendationPriority.MEDIUM
        return RecommendationPriority.LOW

    def _estimate_effort(self, pattern_type: AntiPatternType) -> str:
        """Estimate effort required to fix an anti-pattern."""
        high_effort = {
            AntiPatternType.CONTEXT_THRASHING,
            AntiPatternType.SPIRALING,
        }
        medium_effort = {
            AntiPatternType.EXCESSIVE_SWITCHING,
            AntiPatternType.TOKEN_INEFFICIENCY,
        }
        low_effort = {
            AntiPatternType.ABANDONED_SESSION,
            AntiPatternType.COST_BLOAT,
        }

        if pattern_type in high_effort:
            return "high"
        if pattern_type in medium_effort:
            return "medium"
        return "low"

    def _get_action_steps_for_pattern(
        self, pattern: AntiPattern,
    ) -> list[str]:
        """Generate action steps for addressing an anti-pattern."""
        steps_map: dict[AntiPatternType, list[str]] = {
            AntiPatternType.EXCESSIVE_SWITCHING: [
                "Identify your primary tool for each task type",
                "Complete related tasks in batches within the same tool",
                "Use tool recommendations to minimize switches",
                "Track switches for one week to identify patterns",
            ],
            AntiPatternType.SPIRALING: [
                "Take a break when stuck in a loop",
                "Document the problem before returning to AI tools",
                "Try a different approach or tool when spiraling",
                "Consider human collaboration for complex problems",
            ],
            AntiPatternType.CONTEXT_THRASHING: [
                "Group related tasks to stay in one context",
                "Use tool-specific features instead of switching",
                "Document requirements before tool use",
                "Leverage session history features",
            ],
            AntiPatternType.ABANDONED_SESSION: [
                "Review abandoned sessions to understand why",
                "Break large tasks into smaller, completable ones",
                "Set clear success criteria before starting",
                "Use progress tracking to maintain momentum",
            ],
            AntiPatternType.COST_BLOAT: [
                "Review usage of expensive tools",
                "Consider cheaper alternatives for routine tasks",
                "Use smaller models for simple requests",
                "Implement caching for repeated queries",
            ],
            AntiPatternType.TOKEN_INEFFICIENCY: [
                "Use more focused, specific prompts",
                "Leverage context caching features",
                "Break complex requests into smaller steps",
                "Review and refine prompt engineering",
            ],
        }
        return steps_map.get(pattern.type, ["Investigate and address this pattern"])

    def _get_cost_action_steps(self, opt: CostOptimization) -> list[str]:
        """Generate action steps for cost optimization."""
        return [
            f"Review current usage of {opt.pattern_name}",
            f"Evaluate alternative tools: {', '.join(opt.alternative_tools)}",
            "Run a trial with alternative for one week",
            "Compare results and cost savings",
            "Adopt if quality is maintained",
        ]

    def _estimate_affinity_savings(
        self, affinity: ToolAffinity, chains: Sequence[WorkflowChain],
    ) -> float:
        """Estimate potential efficiency gain from using recommended tool."""
        # Rough estimate based on efficiency difference
        current_avg_eff = sum(
            c.efficiency_score for c in chains
            if c.efficiency_score is not None
        ) / len(chains) if chains else 0.5

        efficiency_gain = affinity.avg_efficiency - current_avg_eff
        return max(0.0, efficiency_gain)

    def _confidence_to_float(self, confidence: str) -> float:
        """Convert confidence string to float."""
        mapping = {"low": 0.4, "medium": 0.6, "high": 0.8}
        return mapping.get(confidence, 0.5)

    def generate_insights(
        self,
        recommendations: Sequence[WorkflowActionableRecommendation],
        metrics: WorkflowMetrics,
    ) -> list[str]:
        """Generate high-level insights from recommendations and metrics.

        Args:
            recommendations: Generated recommendations
            metrics: Workflow metrics

        Returns:
            List of insight strings
        """
        insights = []

        # Categorize recommendations
        by_category: dict[str, list[WorkflowActionableRecommendation]] = {}
        for rec in recommendations:
            if rec.category not in by_category:
                by_category[rec.category] = []
            by_category[rec.category].append(rec)

        # Generate insights per category
        if "cost" in by_category:
            cost_savings = sum(r.expected_savings_usd for r in by_category["cost"])
            insights.append(
                f"Potential monthly savings: ${cost_savings:.2f} from "
                f"{len(by_category['cost'])} cost optimizations"
            )

        if "workflow" in by_category:
            insights.append(
                f"{len(by_category['workflow'])} workflow patterns could be "
                f"improved for better productivity"
            )

        if "efficiency" in by_category:
            insights.append(
                f"{len(by_category['efficiency'])} efficiency opportunities "
                f"identified based on tool usage patterns"
            )

        # Overall assessment
        total_savings = sum(r.expected_savings_usd for r in recommendations)
        if total_savings > 50:
            insights.append(
                f"High-impact optimization opportunity: ${total_savings:.2f} "
                f"total potential savings"
            )

        # Productivity insight
        if metrics.productivity_score < 0.5:
            insights.append(
                "Productivity score below 50% indicates significant room "
                "for workflow improvement"
            )
        elif metrics.productivity_score > 0.8:
            insights.append(
                "Strong workflow efficiency with minor optimization opportunities"
            )

        return insights
