"""Session correlation across AI coding tools."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from agenttop.models import Session
from agenttop.workflow.models import ToolTransition, WorkflowChain

log = logging.getLogger(__name__)

# Configuration constants
_MAX_TIME_GAP_MINUTES = 60  # Max gap between sessions to consider them correlated
_MAX_CHAIN_DURATION_HOURS = 8  # Max duration of a workflow chain
_MIN_SESSION_OVERLAP_SECONDS = 0  # Sessions must not overlap


class SessionCorrelator:
    """Correlates sessions across AI coding tools by time and project proximity."""

    def correlate_by_time(
        self,
        sessions: list[Session],
        max_gap_minutes: float = _MAX_TIME_GAP_MINUTES,
    ) -> list[WorkflowChain]:
        """Group sessions that are close in time (within max_gap_minutes).

        Sessions are sorted by start time, Sessions that are within
        max_gap_minutes of each other are grouped into chains.

        Args:
            sessions: List of sessions from all tools
            max_gap_minutes: Maximum time gap between sessions to consider them correlated

        Returns:
            List of WorkflowChain objects representing correlated session groups
        """
        if not sessions:
            return []

        # Sort sessions by start time
        sorted_sessions = sorted(sessions, key=lambda s: s.start_time)
        chains: list[WorkflowChain] = []
        current_chain_sessions: list[Session] = [sorted_sessions[0]]

        for i in range(1, len(sorted_sessions)):
            current_session = sorted_sessions[i]
            prev_session = current_chain_sessions[-1]

            # Calculate time gap (use start_time as fallback if end_time is None)
            prev_end = prev_session.end_time or prev_session.start_time
            time_gap = (current_session.start_time - prev_end).total_seconds() / 60

            if time_gap <= max_gap_minutes:
                # Add to current chain
                current_chain_sessions.append(current_session)
            else:
                # Finalize current chain and start new one
                if len(current_chain_sessions) > 1:
                    chains.append(self._build_chain(current_chain_sessions))
                current_chain_sessions = [current_session]

        # Don't forget the last chain
        if len(current_chain_sessions) > 1:
            chains.append(self._build_chain(current_chain_sessions))

        log.info("Correlated %d sessions into %d time-based chains", len(sessions), len(chains))
        return chains

    def correlate_by_project(
        self,
        sessions: list[Session],
        max_gap_hours: float = _MAX_CHAIN_DURATION_HOURS,
    ) -> list[WorkflowChain]:
        """Group sessions working on the same project.

        Sessions are grouped by project, then further refined by time proximity.

        Args:
            sessions: List of sessions from all tools
            max_gap_hours: Maximum time gap in hours for project-based correlation

        Returns:
            List of WorkflowChain objects grouped by project
        """
        if not sessions:
            return []

        # Group by project
        project_sessions: dict[str, list[Session]] = {}
        no_project_sessions: list[Session] = []

        for session in sessions:
            if session.project:
                project_name = session.project.split("/")[-1]  # Get project name from path
                if project_name not in project_sessions:
                    project_sessions[project_name] = []
                project_sessions[project_name].append(session)
            else:
                no_project_sessions.append(session)

        chains: list[WorkflowChain] = []

        # Create chains per project
        for project_name, proj_sessions in project_sessions.items():
            # Sort by time within project
            proj_sessions.sort(key=lambda s: s.start_time)

            # Split into time-based sub-chains
            current_chain: list[Session] = [proj_sessions[0]]

            for i in range(1, len(proj_sessions)):
                current_session = proj_sessions[i]
                prev_session = current_chain[-1]

                # Use start_time as fallback if end_time is None
                prev_end = prev_session.end_time or prev_session.start_time
                time_gap_hours = (
                    (current_session.start_time - prev_end).total_seconds() / 3600
                )

                if time_gap_hours <= max_gap_hours:
                    current_chain.append(current_session)
                else:
                    if len(current_chain) > 1:
                        chains.append(self._build_chain(current_chain, project_name))
                    current_chain = [current_session]

            if len(current_chain) > 1:
                chains.append(self._build_chain(current_chain, project_name))

        log.info(
            "Correlated %d sessions into %d project-based chains from %d projects",
            len(sessions), len(chains), len(project_sessions)
        )
        return chains

    def detect_tool_transitions(
        self,
        chains: list[WorkflowChain],
        sessions: list[Session],
    ) -> list[ToolTransition]:
        """Identify when user switched between tools within chains.

        Args:
            chains: List of workflow chains
            sessions: Original sessions for detailed transition analysis

        Returns:
            List of ToolTransition objects
        """
        transitions: list[ToolTransition] = []
        session_map = {s.id: s for s in sessions}

        for chain in chains:
            # Get sessions in order
            chain_sessions = [session_map[sid] for sid in chain.session_ids if sid in session_map]

            for i in range(1, len(chain_sessions)):
                prev_session = chain_sessions[i - 1]
                curr_session = chain_sessions[i]

                # Only create transition if tools are different
                if prev_session.tool != curr_session.tool:
                    # Use start_time as fallback if end_time is None
                    prev_end = prev_session.end_time or prev_session.start_time
                    transition = ToolTransition(
                        id=str(uuid.uuid4()),
                        from_tool=prev_session.tool.value if hasattr(prev_session.tool, "value") else str(prev_session.tool),
                        to_tool=curr_session.tool.value if hasattr(curr_session.tool, "value") else str(curr_session.tool),
                        from_session_id=prev_session.id,
                        to_session_id=curr_session.id,
                        time_gap_seconds=(
                            (curr_session.start_time - prev_end).total_seconds()
                        ),
                        project_match=(prev_session.project == curr_session.project),
                        context_preservation_score=self._estimate_context_preservation(prev_session, curr_session),
                        timestamp=curr_session.start_time.timestamp(),
                    )
                    transitions.append(transition)

        log.info("Detected %d tool transitions across %d chains", len(transitions), len(chains))
        return transitions

    def _build_chain(
        self,
        sessions: list[Session],
        project_name: str | None = None,
    ) -> WorkflowChain:
        """Build a WorkflowChain from a list of sessions."""
        tools = list(set(
            s.tool.value if hasattr(s.tool, "value") else str(s.tool)
            for s in sessions
        ))
        total_tokens = sum(s.total_tokens for s in sessions)
        total_cost = sum(s.estimated_cost_usd for s in sessions)

        return WorkflowChain(
            id=str(uuid.uuid4()),
            session_ids=[s.id for s in sessions],
            tools=tools,
            start_time=sessions[0].start_time.timestamp(),
            end_time=(sessions[-1].end_time or sessions[-1].start_time).timestamp(),
            project=project_name or sessions[0].project,
            total_tokens=total_tokens,
            total_cost=total_cost,
            efficiency_score=None,  # Computed later by analyzer
            pattern_type=None,  # Classified later by pattern detector
        )

    def _estimate_context_preservation(
        self,
        from_session: Session,
        to_session: Session,
    ) -> float:
        """Estimate how much context was preserved between sessions.

        Higher score = better context preservation.
        Factors:
        - Same project = +0.4
        - Short time gap = +0.3
        - Same tool = +0.3 (but transitions are only created when tools differ)

        Returns:
            Float between 0.0 and 1.0
        """
        score = 0.0

        # Same project bonus
        if from_session.project and to_session.project:
            if from_session.project == to_session.project:
                score += 0.4

        # Time gap bonus (shorter = better)
        time_gap = (to_session.start_time - from_session.end_time).total_seconds()
        if time_gap <= 300:  # 5 minutes
            score += 0.3
        elif time_gap <= 900:  # 15 minutes
            score += 0.2
        elif time_gap <= 1800:  # 30 minutes
            score += 0.1

        # Message count similarity (similar session sizes = better context transfer)
        if from_session.message_count > 0 and to_session.message_count > 0:
            ratio = min(from_session.message_count, to_session.message_count) / max(
                from_session.message_count, to_session.message_count
            )
            if ratio > 0.7:
                score += 0.3
            elif ratio > 0.4:
                score += 0.2
            elif ratio > 0.2:
                score += 0.1

        return min(1.0, score)

    def get_tool_usage_distribution(
        self,
        sessions: list[Session],
    ) -> dict[str, int]:
        """Get distribution of sessions per tool.

        Args:
            sessions: List of sessions

        Returns:
            Dict mapping tool name to session count
        """
        distribution: dict[str, int] = {}
        for session in sessions:
            tool_name = session.tool.value if hasattr(session.tool, "value") else str(session.tool)
            distribution[tool_name] = distribution.get(tool_name, 0) + 1
        return distribution

    def get_transition_matrix(
        self,
        transitions: list[ToolTransition],
    ) -> dict[str, dict[str, int]]:
        """Build a transition frequency matrix.

        Args:
            transitions: List of tool transitions

        Returns:
            Dict of dicts: from_tool -> to_tool -> count
        """
        matrix: dict[str, dict[str, int]] = {}
        for transition in transitions:
            from_tool = transition.from_tool
            to_tool = transition.to_tool

            if from_tool not in matrix:
                matrix[from_tool] = {}
            matrix[from_tool][to_tool] = matrix[from_tool].get(to_tool, 0) + 1

        return matrix
