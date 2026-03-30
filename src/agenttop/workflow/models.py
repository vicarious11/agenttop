"""Workflow intelligence models for cross-tool analysis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ToolType(str, Enum):
    """Supported AI coding tools."""
    CLAUDE_CODE = "claude_code"
    CURSOR = "cursor"
    KIRO = "kiro"
    COPILOT = "copilot"
    CODEX = "codex"
    AIDER = "aider"
    CONTINUE = "continue"
    GENERIC = "generic"


@dataclass
class WorkflowChain:
    """A sequence of correlated sessions across tools."""
    id: str
    session_ids: list[str]
    tools: list[str]
    start_time: float
    end_time: float
    project: str | None
    total_tokens: int
    total_cost: float
    efficiency_score: float | None = None  # 0.0 - 1.0
    pattern_type: str | None = None


@dataclass
class ToolTransition:
    """A transition from one tool to another."""
    id: str
    from_tool: str
    to_tool: str
    from_session_id: str
    to_session_id: str
    time_gap_seconds: float
    project_match: bool
    timestamp: float
    context_preservation_score: float | None = None  # 0.0 - 1.0


@dataclass
class WorkflowPattern:
    """A detected workflow pattern."""
    name: str
    description: str
    tool_sequence: list[str]
    frequency: int
    avg_efficiency: float
    avg_tokens: int
    avg_cost: float
    typical_duration_minutes: float = 0.0
    last_seen: float = 0.0


@dataclass
class WorkflowRecommendation:
    """A recommendation for workflow improvement."""
    task_type: str
    primary_tool: str
    secondary_tools: list[str]
    avoid_tools: list[str]
    rationale: str
    estimated_efficiency_gain: float


@dataclass
class SwitchingCost:
    """Cost of switching between tools."""
    from_tool: str
    to_tool: str
    context_loss_score: float  # 0.0 - 1.0
    ramp_up_time_minutes: float
    mitigation_strategy: str


@dataclass
class WorkflowMetrics:
    """Aggregated workflow metrics."""
    total_chains: int
    total_transitions: int
    avg_chain_length: float
    avg_efficiency_score: float
    most_common_pattern: str
    most_efficient_pattern: str
    tool_usage_distribution: dict[str, int]
    transition_matrix: dict[str, dict[str, int]]
