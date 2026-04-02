"""Anti-pattern detection for workflow analysis."""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import datetime

from agenttop.workflow.models import (
    AntiPattern,
    AntiPatternType,
    ToolTransition,
    WorkflowChain,
)

log = logging.getLogger(__name__)


class AntiPatternDetector:
    """Detects harmful workflow patterns."""

    def __init__(self) -> None:
        self._thresholds = {
            "excessive_switching_min_tools": 4,
            "excessive_switching_min_transitions": 3,
            "spiraling_max_tokens_per_minute": 3000,
            "spiraling_min_duration": 10,
            "context_thrash_gap_minutes": 2,
            "context_thrash_occurrences": 4,
            "abandoned_max_gap_minutes": 5,
            "abandoned_min_message_ratio": 0.3,
            "cost_bloat_multiplier": 3.0,
            "token_inefficiency_ratio": 5.0,
        }

    def detect_anti_patterns(
        self,
        chains: list[WorkflowChain],
        transitions: list[ToolTransition],
    ) -> list[AntiPattern]:
        """Detect all anti-patterns in the workflow data.

        Args:
            chains: List of workflow chains
            transitions: List of tool transitions

        Returns:
            List of detected AntiPattern objects
        """
        anti_patterns: list[AntiPattern] = []

        # Detect each type of anti-pattern
        anti_patterns.extend(self._detect_excessive_switching(chains, transitions))
        anti_patterns.extend(self._detect_spiraling(chains))
        anti_patterns.extend(self._detect_context_thrashing(chains, transitions))
        anti_patterns.extend(self._detect_abandoned_sessions(chains))
        anti_patterns.extend(self._detect_cost_bloat(chains))
        anti_patterns.extend(self._detect_token_inefficiency(chains))

        log.info("Detected %d anti-patterns across %d chains", len(anti_patterns), len(chains))
        return anti_patterns

    def _detect_excessive_switching(
        self,
        chains: list[WorkflowChain],
        transitions: list[ToolTransition],
    ) -> list[AntiPattern]:
        """Detect chains with excessive tool switching.

        Excessive switching indicates context thrashing and lack of focus.
        """
        anti_patterns: list[AntiPattern] = []

        for chain in chains:
            # Count unique tools
            unique_tools = len(set(chain.tools))

            # Count transitions for this chain
            chain_transitions = [
                t for t in transitions
                if t.from_session_id in chain.session_ids or t.to_session_id in chain.session_ids
            ]

            if unique_tools >= self._thresholds["excessive_switching_min_tools"] and len(chain_transitions) >= self._thresholds["excessive_switching_min_transitions"]:
                severity = "critical" if unique_tools >= 5 else "high"

                anti_patterns.append(AntiPattern(
                    id=str(uuid.uuid4()),
                    type=AntiPatternType.EXCESSIVE_SWITCHING,
                    severity=severity,
                    description=f"Chain used {unique_tools} different tools with {len(chain_transitions)} transitions in {((chain.end_time - chain.start_time) / 60):.0f} minutes",
                    affected_sessions=list(chain.session_ids),
                    detected_at=datetime.now().timestamp(),
                    remedy=f"Reduce tool switching. Pick one primary tool for the task and use others only for specific needs. Consider using a tool that can handle multiple aspects of your workflow.",
                    estimated_cost_impact=chain.total_cost * 0.2,  # 20% waste estimate
                    frequency=1,
                ))

        return anti_patterns

    def _detect_spiraling(self, chains: list[WorkflowChain]) -> list[AntiPattern]:
        """Detect sessions that are spiraling (high token consumption with low progress).

        Spiraling is characterized by very high token consumption relative to time,
        suggesting the AI is going in circles or the user is stuck.
        """
        anti_patterns: list[AntiPattern] = []

        for chain in chains:
            duration_minutes = (chain.end_time - chain.start_time) / 60

            if duration_minutes >= self._thresholds["spiraling_min_duration"]:
                tokens_per_minute = chain.total_tokens / duration_minutes

                if tokens_per_minute > self._thresholds["spiraling_max_tokens_per_minute"]:
                    # Check if efficiency is also low (confirming spiral)
                    efficiency = chain.efficiency_score or 0.5

                    if efficiency < 0.4:
                        severity = "critical" if tokens_per_minute > 5000 else "high"

                        anti_patterns.append(AntiPattern(
                            id=str(uuid.uuid4()),
                            type=AntiPatternType.SPIRALING,
                            severity=severity,
                            description=f"Chain consumed {tokens_per_minute:.0f} tokens/minute for {duration_minutes:.0f} minutes with low efficiency ({efficiency:.2f})",
                            affected_sessions=list(chain.session_ids),
                            detected_at=datetime.now().timestamp(),
                            remedy="Break down the task into smaller, more focused requests. Take a step back and reconsider the approach. High token consumption with low efficiency suggests going in circles.",
                            estimated_cost_impact=chain.total_cost * 0.4,  # 40% waste
                            frequency=1,
                        ))

        return anti_patterns

    def _detect_context_thrashing(
        self,
        chains: list[WorkflowChain],
        transitions: list[ToolTransition],
    ) -> list[AntiPattern]:
        """Detect rapid back-and-forth switching between tools (context thrashing).

        Context thrashing is when user switches tools very frequently,
            losing context each time.
        """
        anti_patterns: list[AntiPattern] = []

        for chain in chains:
            chain_transitions = [
                t for t in transitions
                if t.from_session_id in chain.session_ids or t.to_session_id in chain.session_ids
            ]

            if len(chain_transitions) < self._thresholds["context_thrash_occurrences"]:
                continue

            # Count rapid switches (less than threshold gap)
            rapid_switch_count = sum(
                1 for t in chain_transitions
                if t.time_gap_seconds < self._thresholds["context_thrash_gap_minutes"] * 60
            )

            if rapid_switch_count >= self._thresholds["context_thrash_occurrences"]:
                severity = "high" if rapid_switch_count >= 6 else "medium"

                anti_patterns.append(AntiPattern(
                    id=str(uuid.uuid4()),
                    type=AntiPatternType.CONTEXT_THRASHING,
                    severity=severity,
                    description=f"Chain has {rapid_switch_count} rapid tool switches (less than {self._thresholds['context_thrash_gap_minutes']} minutes apart)",
                    affected_sessions=list(chain.session_ids),
                    detected_at=datetime.now().timestamp(),
                    remedy="Slow down and plan your approach. Each tool switch loses context. Try to complete a meaningful unit of work in one tool before switching.",
                    estimated_cost_impact=chain.total_cost * 0.15,  # 15% waste
                    frequency=1,
                ))

        return anti_patterns

    def _detect_abandoned_sessions(self, chains: list[WorkflowChain]) -> list[AntiPattern]:
        """Detect sessions that were abandoned mid-task.

        Abandoned sessions show very low message count relative to duration,
            or sudden stops without completion.
        """
        anti_patterns: list[AntiPattern] = []

        for chain in chains:
            # Use sample_size as proxy for session count
            num_sessions = chain.sample_size

            # Check for very short sessions with low activity
            duration_minutes = (chain.end_time - chain.start_time) / 60

            if duration_minutes < 1 and num_sessions >= 2:
                # Multiple very short sessions suggest abandonment
                avg_messages_per_session = 2  # Minimal assumption

                if avg_messages_per_session < self._thresholds["abandoned_min_message_ratio"] * 10:
                    anti_patterns.append(AntiPattern(
                        id=str(uuid.uuid4()),
                        type=AntiPatternType.ABANDONED_SESSION,
                        severity="medium",
                        description=f"Chain has {num_sessions} very short sessions (total {duration_minutes:.1f} minutes), suggesting abandoned attempts",
                        affected_sessions=list(chain.session_ids),
                        detected_at=datetime.now().timestamp(),
                        remedy="Sessions appear to be abandoned. Consider planning your approach before starting. If stuck, try rephrasing your request or breaking down the task.",
                        estimated_cost_impact=chain.total_cost * 0.3,  # 30% waste
                        frequency=1,
                    ))

        return anti_patterns

    def _detect_cost_bloat(self, chains: list[WorkflowChain]) -> list[AntiPattern]:
        """Detect chains with unusually high cost relative to peers.

        Cost bloat indicates spending more than necessary for the outcome.
        """
        if not chains:
            return []

        anti_patterns: list[AntiPattern] = []

        # Calculate median cost per chain
        costs_per_session = [
            c.total_cost / c.sample_size
            for c in chains
            if c.sample_size > 0
        ]

        if not costs_per_session:
            return []

        median_cost = sorted(costs_per_session)[len(costs_per_session) // 2]

        for chain in chains:
            avg_cost_per_session = chain.total_cost / chain.sample_size if chain.sample_size > 0 else 0

            if avg_cost_per_session > median_cost * self._thresholds["cost_bloat_multiplier"]:
                # Check efficiency to confirm it's not justified
                if (chain.efficiency_score or 0.5) < 0.6:
                    severity = "critical" if avg_cost_per_session > median_cost * 5 else "high"

                    anti_patterns.append(AntiPattern(
                        id=str(uuid.uuid4()),
                        type=AntiPatternType.COST_BLOAT,
                        severity=severity,
                        description=f"Chain cost ${avg_cost_per_session:.2f} per session is {avg_cost_per_session/median_cost:.1f}x higher than median (${median_cost:.2f})",
                        affected_sessions=list(chain.session_ids),
                        detected_at=datetime.now().timestamp(),
                        remedy=f"Your spending is {avg_cost_per_session/median_cost:.1f}x higher than typical. Consider using more efficient prompts, switching to a cheaper tool, or breaking down complex requests.",
                        estimated_cost_impact=chain.total_cost - (median_cost * chain.sample_size),
                        frequency=1,
                    ))

        return anti_patterns

    def _detect_token_inefficiency(self, chains: list[WorkflowChain]) -> list[AntiPattern]:
        """Detect chains with poor token efficiency (high tokens, low outcomes).

        Token inefficiency is consuming many tokens without proportionate results.
        """
        if not chains:
            return []

        anti_patterns: list[AntiPattern] = []

        # Calculate median tokens per session
        tokens_per_session = [
            c.total_tokens / c.sample_size
            for c in chains
            if c.sample_size > 0
        ]

        if not tokens_per_session:
            return []

        median_tokens = sorted(tokens_per_session)[len(tokens_per_session) // 2]

        for chain in chains:
            avg_tokens_per_session = chain.total_tokens / chain.sample_size if chain.sample_size > 0 else 0
            efficiency = chain.efficiency_score or 0.5

            # High token consumption with low efficiency
            if avg_tokens_per_session > median_tokens * self._thresholds["token_inefficiency_ratio"] and efficiency < 0.5:
                severity = "high" if avg_tokens_per_session > median_tokens * 10 else "medium"

                anti_patterns.append(AntiPattern(
                    id=str(uuid.uuid4()),
                    type=AntiPatternType.TOKEN_INEFFICIENCY,
                    severity=severity,
                    description=f"Chain uses {avg_tokens_per_session:.0f} tokens per session ({avg_tokens_per_session/median_tokens:.1f}x median) with low efficiency ({efficiency:.2f})",
                    affected_sessions=list(chain.session_ids),
                    detected_at=datetime.now().timestamp(),
                    remedy="High token consumption with low efficiency suggests poor prompt engineering. Be more specific, provide better context, or use code files instead of pasting code.",
                    estimated_cost_impact=chain.total_cost * 0.25,  # 25% waste estimate
                    frequency=1,
                ))

        return anti_patterns

    def get_anti_pattern_summary(
        self,
        anti_patterns: list[AntiPattern],
    ) -> dict:
        """Get summary statistics of detected anti-patterns.

        Args:
            anti_patterns: List of detected anti-patterns

        Returns:
            Dict with summary statistics
        """
        if not anti_patterns:
            return {
                "total_count": 0,
                "by_severity": {},
                "by_type": {},
                "total_cost_impact": 0.0,
            }

        # Count by severity
        by_severity: dict[str, int] = {}
        for ap in anti_patterns:
            by_severity[ap.severity] = by_severity.get(ap.severity, 0) + 1

        # Count by type
        by_type: dict[str, int] = {}
        for ap in anti_patterns:
            by_type[ap.type.value] = by_type.get(ap.type.value, 0) + 1

        # Total cost impact
        total_cost_impact = sum(ap.estimated_cost_impact for ap in anti_patterns)

        return {
            "total_count": len(anti_patterns),
            "by_severity": by_severity,
            "by_type": by_type,
            "total_cost_impact": round(total_cost_impact, 2),
        }
