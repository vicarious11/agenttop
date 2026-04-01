"""Workflow pattern detection and classification."""

from __future__ import annotations

import logging
from collections import Counter

from agenttop.workflow.correlator import SessionCorrelator
from agenttop.workflow.knowledge_base import WORKFLOW_PATTERNS, get_pattern_info
from agenttop.workflow.models import ToolTransition, WorkflowChain, WorkflowPattern

log = logging.getLogger(__name__)


class WorkflowPatternDetector:
    """Detects and classifies workflow patterns from tool usage sequences."""

    def __init__(self) -> None:
        self._correlator = SessionCorrelator()

    def detect_patterns(
        self,
        chains: list[WorkflowChain],
        transitions: list[ToolTransition],
    ) -> list[WorkflowPattern]:
        """Detect and classify workflow patterns in chains.

        Args:
            chains: List of workflow chains
            transitions: List of tool transitions

        Returns:
            List of detected WorkflowPattern objects
        """
        patterns: list[WorkflowPattern] = []
        pattern_counts: Counter = Counter()

        for chain in chains:
            pattern_type = self._classify_chain_pattern(chain, transitions)
            if pattern_type:
                pattern_counts[pattern_type] += 1
                chain.pattern_type = pattern_type

        # Aggregate patterns
        for pattern_name, count in pattern_counts.items():
            pattern_chains = [c for c in chains if c.pattern_type == pattern_name]
            if pattern_chains:
                avg_efficiency = sum(
                    c.efficiency_score for c in pattern_chains if c.efficiency_score is not None
                ) / len([c for c in pattern_chains if c.efficiency_score is not None]) if any(
                    c.efficiency_score is not None for c in pattern_chains
                ) else 0.5

                avg_tokens = sum(c.total_tokens for c in pattern_chains) / len(pattern_chains)
                avg_cost = sum(c.total_cost for c in pattern_chains) / len(pattern_chains)

                durations = [
                    (c.end_time - c.start_time) / 60  # minutes
                    for c in pattern_chains
                ]
                avg_duration = sum(durations) / len(durations) if durations else 0

                # Get tool sequence (most common for this pattern)
                tool_sequences = [tuple(c.tools) for c in pattern_chains]
                most_common_sequence = Counter(tool_sequences).most_common(1)[0][0] if tool_sequences else []

                pattern_info = get_pattern_info(pattern_name)
                patterns.append(WorkflowPattern(
                    name=pattern_name,
                    description=pattern_info.get("description", "") if pattern_info else "",
                    tool_sequence=list(most_common_sequence),
                    frequency=count,
                    avg_efficiency=avg_efficiency,
                    avg_tokens=int(avg_tokens),
                    avg_cost=avg_cost,
                    typical_duration_minutes=avg_duration,
                    last_seen=max(c.end_time for c in pattern_chains),
                ))

        log.info("Detected %d unique patterns from %d chains", len(patterns), len(chains))
        return patterns

    def _classify_chain_pattern(
        self,
        chain: WorkflowChain,
        transitions: list[ToolTransition],
    ) -> str | None:
        """Classify a chain into a workflow pattern.

        Args:
            chain: Workflow chain to classify
            transitions: All transitions for reference

        Returns:
            Pattern name or None if unclassifiable
        """
        if len(chain.tools) == 1:
            return "single_tool_deep_dive"

        # Get transitions for this chain
        chain_transitions = [
            t for t in transitions
            if t.from_session_id in chain.session_ids or t.to_session_id in chain.session_ids
        ]

        if not chain_transitions:
            return "single_tool_deep_dive"

        # Count unique tools
        unique_tools = set(chain.tools)
        num_tools = len(unique_tools)

        # Calculate chain duration in minutes
        duration_minutes = (chain.end_time - chain.start_time) / 60

        # Pattern detection rules

        # Tool hopping: Many switches in short time
        if num_tools >= 3 and len(chain_transitions) >= 3 and duration_minutes < 30:
            return "tool_hopping"

        # Quick iteration: Rapid back-and-forth between 2 tools
        if num_tools == 2 and len(chain_transitions) >= 2:
            avg_gap = sum(t.time_gap_seconds for t in chain_transitions) / len(chain_transitions)
            if avg_gap < 300:  # Less than 5 minutes average
                return "quick_iteration"

        # Iterative refinement: Structured progression through tools
        if self._is_iterative_refinement(chain, chain_transitions):
            return "iterative_refinement"

        # Parallel exploration: Multiple tools used for different aspects
        if num_tools >= 2 and len(chain_transitions) >= 2:
            # Check if sessions overlap (parallel usage)
            return "parallel_exploration"

        return "single_tool_deep_dive"

    def _is_iterative_refinement(
        self,
        chain: WorkflowChain,
        transitions: list[ToolTransition],
    ) -> bool:
        """Check if chain represents iterative refinement pattern.

        Iterative refinement typically shows:
        1. Quick suggestion tool first (copilot)
        2. IDE refinement (cursor)
        3. Deep implementation (claude_code)
        """
        if len(transitions) < 2:
            return False

        # Check for progressive tool sophistication
        tool_order = [t.from_tool for t in transitions] + [transitions[-1].to_tool]

        # Look for progression from simple to sophisticated
        sophistication_order = {
            "copilot": 1,
            "kiro": 2,
            "cursor": 2,
            "claude_code": 3,
            "codex": 2,
            "aider": 2,
            "continue": 2,
        }

        # Check if tools progress in sophistication
        sophistication_scores = [
            sophistication_order.get(t.lower(), 2) for t in tool_order
        ]

        # Monotonic increase indicates iterative refinement
        is_progressive = all(
            sophistication_scores[i] <= sophistication_scores[i + 1]
            for i in range(len(sophistication_scores) - 1)
        )

        return is_progressive and len(set(tool_order)) >= 2

    def calculate_pattern_efficiency(
        self,
        pattern: WorkflowPattern,
        chains: list[WorkflowChain],
    ) -> float:
        """Calculate efficiency score for a pattern.

        Efficiency factors:
        - Context preservation (high = better)
        - Token efficiency (output/input ratio)
        - Cost efficiency (value per dollar)
        - Duration efficiency (quick completion)

        Args:
            pattern: Pattern to score
            chains: Chains matching this pattern

        Returns:
            Efficiency score 0.0 - 1.0
        """
        if not chains:
            return 0.5

        scores = []

        for chain in chains:
            score = 0.5  # Start neutral

            # Token efficiency: lower tokens for same task = better
            if chain.total_tokens < 5000:
                score += 0.2
            elif chain.total_tokens < 15000:
                score += 0.1
            elif chain.total_tokens > 50000:
                score -= 0.1

            # Duration efficiency: quick completion = better
            duration_minutes = (chain.end_time - chain.start_time) / 60
            if duration_minutes < 15:
                score += 0.2
            elif duration_minutes < 30:
                score += 0.1
            elif duration_minutes > 120:
                score -= 0.1

            # Tool count: optimal = 1-2 tools, too many = inefficient
            num_tools = len(set(chain.tools))
            if num_tools == 1:
                score += 0.1  # Single tool focus is often efficient
            elif num_tools == 2:
                score += 0.05  # Two tools can be efficient
            elif num_tools >= 4:
                score -= 0.1  # Too many tools = context switching

            scores.append(max(0.0, min(1.0, score)))

        return sum(scores) / len(scores) if scores else 0.5

    def get_pattern_recommendations(
        self,
        patterns: list[WorkflowPattern],
    ) -> list[dict]:
        """Get recommendations based on detected patterns.

        Args:
            patterns: Detected patterns

        Returns:
            List of recommendation dicts
        """
        recommendations = []

        for pattern in patterns:
            pattern_info = get_pattern_info(pattern.name)
            if not pattern_info:
                continue

            efficiency = pattern_info.get("efficiency", "medium")

            if efficiency == "low":
                recommendations.append({
                    "pattern": pattern.name,
                    "issue": f"Pattern '{pattern.name}' has low efficiency",
                    "frequency": pattern.frequency,
                    "recommendation": self._get_improvement_recommendation(pattern.name),
                    "potential_savings": f"${pattern.avg_cost * 0.3:.2f}/session",
                })

        return recommendations

    def _get_improvement_recommendation(self, pattern_name: str) -> str:
        """Get specific improvement recommendation for a pattern."""
        recommendations = {
            "tool_hopping": "Consider committing to one tool for the session. Frequent switching loses context.",
            "quick_iteration": "This back-and-forth may indicate unclear requirements. Try planning more upfront.",
            "parallel_exploration": "Parallel tool usage can be efficient, but ensure you're not duplicating effort.",
            "single_tool_deep_dive": "Consider whether a simpler tool could handle subtasks more efficiently.",
            "iterative_refinement": "This is an efficient pattern. Consider documenting your workflow for reuse.",
        }
        return recommendations.get(pattern_name, "Review this pattern for optimization opportunities.")
