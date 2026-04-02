"""Tool affinity analysis - which tools work best for which contexts."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from agenttop.workflow.models import ToolAffinity, WorkflowChain

log = logging.getLogger(__name__)


class ToolAffinityAnalyzer:
    """Analyzes which tools work best in different contexts."""

    def __init__(self) -> None:
        self._context_categories = [
            "time_of_day",  # morning, afternoon, evening, night
            "project_type",  # derived from project path
            "task_complexity",  # based on session count and tokens
            "chain_length",  # short, medium, long
        ]

    def analyze_affinities(
        self,
        chains: list[WorkflowChain],
    ) -> list[ToolAffinity]:
        """Analyze tool success rates across different contexts.

        Args:
            chains: List of workflow chains

        Returns:
            List of ToolAffinity objects
        """
        affinities: list[ToolAffinity] = []

        # Analyze by time of day
        affinities.extend(self._analyze_by_time_of_day(chains))

        # Analyze by chain length (workflow complexity)
        affinities.extend(self._analyze_by_chain_length(chains))

        # Analyze by efficiency tier
        affinities.extend(self._analyze_by_efficiency_tier(chains))

        log.info("Generated %d tool affinity recommendations", len(affinities))
        return affinities

    def _analyze_by_time_of_day(
        self,
        chains: list[WorkflowChain],
    ) -> list[ToolAffinity]:
        """Analyze which tools work best at different times of day."""
        # Group by tool and time period
        time_periods = {
            "morning": (6, 12),    # 6 AM - 12 PM
            "afternoon": (12, 18),  # 12 PM - 6 PM
            "evening": (18, 24),    # 6 PM - 12 AM
            "night": (0, 6),        # 12 AM - 6 AM
        }

        # Build stats: tool -> period -> (efficiencies, costs)
        stats: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {
            "efficiencies": [],
            "costs": [],
            "sample_size": 0,
        }))

        for chain in chains:
            for session_ts in chain.session_start_times:
                hour = datetime.fromtimestamp(session_ts).hour

                # Determine time period
                period = "unknown"
                for period_name, (start, end) in time_periods.items():
                    if start <= hour < end:
                        period = period_name
                        break

                # Add data for each tool in chain
                for tool in chain.tools:
                    if chain.efficiency_score is not None:
                        stats[tool][period]["efficiencies"].append(chain.efficiency_score)
                    stats[tool][period]["costs"].append(chain.total_cost)
                    stats[tool][period]["sample_size"] += 1

        # Generate affinities
        affinities: list[ToolAffinity] = []

        for tool, periods in stats.items():
            # Find best period for this tool
            best_period = None
            best_success_rate = 0.0

            for period, data in periods.items():
                if data["sample_size"] < 2:
                    continue

                efficiencies = data["efficiencies"]
                if not efficiencies:
                    continue

                success_rate = sum(efficiencies) / len(efficiencies)
                avg_cost = sum(data["costs"]) / len(data["costs"])

                affinities.append(ToolAffinity(
                    tool=tool,
                    context=f"time_{period}",
                    success_rate=round(success_rate, 2),
                    avg_efficiency=round(success_rate, 2),
                    avg_cost_per_outcome=round(avg_cost / max(1, data["sample_size"]), 2),
                    sample_size=data["sample_size"],
                    recommended=False,  # Will be set after comparison
                ))

                if success_rate > best_success_rate:
                    best_success_rate = success_rate
                    best_period = period

            # Mark best period as recommended
            if best_period:
                for affinity in affinities:
                    if affinity.tool == tool and affinity.context == f"time_{best_period}":
                        affinities.append(affinity.__class__(
                            **{**affinity.__dict__, "recommended": True}
                        ))
                        affinities.pop()  # Remove the non-recommended version
                        break

        return affinities

    def _analyze_by_chain_length(
        self,
        chains: list[WorkflowChain],
    ) -> list[ToolAffinity]:
        """Analyze which tools work best for different workflow lengths."""
        # Group by tool and chain length category
        length_categories = {
            "short": (1, 2),      # 1-2 sessions
            "medium": (3, 5),     # 3-5 sessions
            "long": (6, 100),     # 6+ sessions
        }

        stats: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {
            "efficiencies": [],
            "costs": [],
            "sample_size": 0,
        }))

        for chain in chains:
            session_count = chain.sample_size

            # Determine length category
            category = "unknown"
            for cat_name, (min_sessions, max_sessions) in length_categories.items():
                if min_sessions <= session_count <= max_sessions:
                    category = cat_name
                    break

            # Add data for each tool in chain
            for tool in chain.tools:
                if chain.efficiency_score is not None:
                    stats[tool][category]["efficiencies"].append(chain.efficiency_score)
                stats[tool][category]["costs"].append(chain.total_cost)
                stats[tool][category]["sample_size"] += 1

        # Generate affinities
        affinities: list[ToolAffinity] = []

        for tool, categories in stats.items():
            for category, data in categories.items():
                if data["sample_size"] < 2:
                    continue

                efficiencies = data["efficiencies"]
                if not efficiencies:
                    continue

                success_rate = sum(efficiencies) / len(efficiencies)
                avg_cost = sum(data["costs"]) / len(data["costs"])

                affinities.append(ToolAffinity(
                    tool=tool,
                    context=f"workflow_{category}",
                    success_rate=round(success_rate, 2),
                    avg_efficiency=round(success_rate, 2),
                    avg_cost_per_outcome=round(avg_cost / max(1, data["sample_size"]), 2),
                    sample_size=data["sample_size"],
                    recommended=success_rate > 0.6,
                ))

        return affinities

    def _analyze_by_efficiency_tier(
        self,
        chains: list[WorkflowChain],
    ) -> list[ToolAffinity]:
        """Analyze which tools most frequently achieve high efficiency."""
        # Group by efficiency tier
        tiers = {
            "high": (0.7, 1.0),
            "medium": (0.4, 0.7),
            "low": (0.0, 0.4),
        }

        # Count tool appearances in each tier
        tier_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        for chain in chains:
            if chain.efficiency_score is None:
                continue

            # Determine tier
            tier = "unknown"
            for tier_name, (min_eff, max_eff) in tiers.items():
                if min_eff <= chain.efficiency_score < max_eff:
                    tier = tier_name
                    break

            # Count each tool
            for tool in chain.tools:
                tier_counts[tool][tier] += 1

        # Generate affinities (tools that are most often in high tier)
        affinities: list[ToolAffinity] = []

        for tool, tiers_dict in tier_counts.items():
            total = sum(tiers_dict.values())
            high_count = tiers_dict.get("high", 0)

            if total == 0:
                continue

            high_percentage = high_count / total

            affinities.append(ToolAffinity(
                tool=tool,
                context="high_efficiency",
                success_rate=round(high_percentage, 2),
                avg_efficiency=round(high_percentage, 2),
                avg_cost_per_outcome=0.0,  # Not applicable for this context
                sample_size=total,
                recommended=high_percentage > 0.5,
            ))

        return affinities

    def get_recommendations_for_context(
        self,
        affinities: list[ToolAffinity],
        context: str,
    ) -> list[ToolAffinity]:
        """Get tool recommendations for a specific context.

        Args:
            affinities: List of all tool affinities
            context: Context string to filter by

        Returns:
            List of ToolAffinity objects matching the context, sorted by success rate
        """
        matching = [a for a in affinities if a.context == context]

        return sorted(matching, key=lambda x: x.success_rate, reverse=True)
