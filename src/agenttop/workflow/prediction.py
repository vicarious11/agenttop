"""Workflow prediction engine - predict next tool/action based on patterns."""

from __future__ import annotations

import logging
import uuid
from collections import Counter, defaultdict
from datetime import datetime

from agenttop.workflow.models import (
    ToolTransition,
    WorkflowChain,
    WorkflowPattern,
    WorkflowPrediction,
)

log = logging.getLogger(__name__)


class WorkflowPredictor:
    """Predicts next likely tool/action based on workflow patterns."""

    def __init__(self) -> None:
        self._min_confidence = 0.3  # Minimum confidence to make a prediction

    def predict_next_tool(
        self,
        current_session: dict,
        chains: list[WorkflowChain],
        transitions: list[ToolTransition],
        patterns: list[WorkflowPattern],
    ) -> WorkflowPrediction | None:
        """Predict the next tool the user is likely to use.

        Args:
            current_session: Dict with current session info (tool, project, message_count, etc.)
            chains: Historical workflow chains
            transitions: Historical tool transitions
            patterns: Detected workflow patterns

        Returns:
            WorkflowPrediction if confident enough, None otherwise
        """
        current_tool = current_session.get("tool", "")
        current_project = current_session.get("project", "")

        # Get predictions from multiple strategies
        predictions = []

        # Strategy 1: Pattern-based prediction
        pattern_pred = self._predict_from_pattern(current_session, patterns)
        if pattern_pred:
            predictions.append(pattern_pred)

        # Strategy 2: Transition-based prediction (what usually follows this tool)
        transition_pred = self._predict_from_transitions(
            current_tool,
            current_project,
            transitions,
        )
        if transition_pred:
            predictions.append(transition_pred)

        # Strategy 3: Context-based prediction (similar historical contexts)
        context_pred = self._predict_from_context(
            current_session,
            chains,
        )
        if context_pred:
            predictions.append(context_pred)

        if not predictions:
            return None

        # Combine predictions (weighted by confidence)
        return self._combine_predictions(predictions, current_session.get("session_id", ""))

    def _predict_from_pattern(
        self,
        current_session: dict,
        patterns: list[WorkflowPattern],
    ) -> dict | None:
        """Predict next tool based on detected workflow pattern."""
        current_tool = current_session.get("tool", "")

        for pattern in patterns:
            # Check if current tool is in this pattern
            if current_tool in pattern.tool_sequence:
                tool_idx = pattern.tool_sequence.index(current_tool)

                # Predict next tool in sequence
                if tool_idx + 1 < len(pattern.tool_sequence):
                    next_tool = pattern.tool_sequence[tool_idx + 1]

                    return {
                        "next_tool": next_tool,
                        "confidence": min(0.8, pattern.frequency * 0.1),
                        "reasoning": f"Following detected '{pattern.name}' pattern (frequency: {pattern.frequency})",
                        "pattern": pattern.name,
                    }

        return None

    def _predict_from_transitions(
        self,
        current_tool: str,
        current_project: str | None,
        transitions: list[ToolTransition],
    ) -> dict | None:
        """Predict next tool based on historical transitions."""
        # Find transitions from current tool
        from_transitions = [
            t for t in transitions
            if t.from_tool == current_tool
        ]

        if not from_transitions:
            return None

        # Count most common next tools
        next_tool_counts: dict[str, int] = defaultdict(int)
        total = 0

        for t in from_transitions:
            # Weight by project match
            weight = 2 if (current_project and t.project_match) else 1
            next_tool_counts[t.to_tool] += weight
            total += weight

        if total == 0:
            return None

        # Get most common next tool
        most_common = max(next_tool_counts.items(), key=lambda x: x[1])
        next_tool, count = most_common
        confidence = count / total

        if confidence < self._min_confidence:
            return None

        return {
            "next_tool": next_tool,
            "confidence": confidence,
            "reasoning": f"After {current_tool}, users typically switch to {next_tool} ({count}/{total} times, {confidence*100:.0f}%)",
            "pattern": "transition_history",
        }

    def _predict_from_context(
        self,
        current_session: dict,
        chains: list[WorkflowChain],
    ) -> dict | None:
        """Predict next tool based on similar historical contexts."""
        current_tool = current_session.get("tool", "")
        current_project = current_session.get("project", "")
        message_count = current_session.get("message_count", 0)

        # Find similar chains (same project, similar progress)
        similar_chains = [
            c for c in chains
            if c.project == current_project
            and current_tool in c.tools
            and c.sample_size >= 2
        ]

        if not similar_chains:
            return None

        # What typically follows the current tool in these contexts?
        next_tools: list[str] = []

        for chain in similar_chains:
            tools = chain.tools
            if current_tool in tools:
                idx = tools.index(current_tool)
                if idx + 1 < len(tools):
                    next_tools.append(tools[idx + 1])

        if not next_tools:
            return None

        # Most common next tool
        counter = Counter(next_tools)
        most_common, count = counter.most_common(1)[0]
        confidence = count / len(next_tools)

        if confidence < self._min_confidence:
            return None

        return {
            "next_tool": most_common,
            "confidence": confidence,
            "reasoning": f"In similar {current_project} sessions, {current_tool} is typically followed by {most_common}",
            "pattern": "context_similarity",
        }

    def _combine_predictions(
        self,
        predictions: list[dict],
        session_id: str,
    ) -> WorkflowPrediction:
        """Combine multiple predictions into a single recommendation.

        Uses weighted averaging based on prediction source confidence.
        """
        # Extract predictions
        next_tools: list[tuple[str, float]] = [
            (p["next_tool"], p["confidence"])
            for p in predictions
        ]

        # If all predictions agree, high confidence
        unique_tools = set(t for t, _ in next_tools)

        if len(unique_tools) == 1:
            # All agree - high confidence
            predicted_tool = unique_tools.pop()
            confidence = min(0.95, max(c for _, c in next_tools) + 0.2)
            reasoning = "All prediction strategies agree: " + predictions[0]["reasoning"]
            pattern = predictions[0]["pattern"]
        else:
            # Disagreement - pick highest confidence
            predicted_tool, conf = max(next_tools, key=lambda x: x[1])
            confidence = conf * 0.7  # Reduce confidence due to disagreement
            reasoning = f"Most likely next tool is {predicted_tool} (based on {predictions[0]['pattern']})"
            pattern = predictions[0]["pattern"]

        # Alternative suggestions
        alternatives = list(unique_tools - {predicted_tool})[:2]

        return WorkflowPrediction(
            current_session_id=session_id,
            predicted_next_tool=predicted_tool if confidence >= self._min_confidence else None,
            confidence=round(confidence, 2),
            reasoning=reasoning,
            alternative_suggestions=alternatives,
            based_on_pattern=pattern,
        )

    def suggest_workflow_optimization(
        self,
        chains: list[WorkflowChain],
        transitions: list[ToolTransition],
    ) -> list[dict]:
        """Suggest workflow optimizations based on patterns.

        Args:
            chains: Historical workflow chains
            transitions: Historical tool transitions

        Returns:
            List of optimization suggestions
        """
        suggestions: list[dict] = []

        # Find most efficient patterns
        efficient_chains = [c for c in chains if c.efficiency_score and c.efficiency_score > 0.7]

        if efficient_chains:
            # What makes these efficient?
            efficient_tools: dict[str, int] = Counter()
            for chain in efficient_chains:
                for tool in chain.tools:
                    efficient_tools[tool] += 1

            if efficient_tools:
                top_tool = max(efficient_tools.items(), key=lambda x: x[1])
                suggestions.append({
                    "type": "tool_usage",
                    "suggestion": f"Your most efficient workflows use {top_tool[0]}. Consider using it more often.",
                    "confidence": "high" if efficient_tools[top_tool[0]] > 5 else "medium",
                })

        # Check for high-cost transitions
        if transitions:
            # Group by tool pair
            transition_costs: dict[tuple[str, str], list[float]] = defaultdict(list)

            for chain in chains:
                for t in transitions:
                    if t.from_session_id in chain.session_ids or t.to_session_id in chain.session_ids:
                        transition_costs[(t.from_tool, t.to_tool)].append(chain.total_cost)

            # Find expensive transitions
            for (from_t, to_t), costs in transition_costs.items():
                avg_cost = sum(costs) / len(costs)
                if avg_cost > 5.0:  # More than $5 per transition
                    suggestions.append({
                        "type": "transition_cost",
                        "suggestion": f"The {from_t} → {to_t} transition is expensive (${avg_cost:.2f} avg). Minimize this switch.",
                        "confidence": "medium",
                    })

        return suggestions
