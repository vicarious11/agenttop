"""Workflow knowledge base: task recommendations and switching costs."""

from __future__ import annotations

from dataclasses import dataclass

from agenttop.workflow.models import SwitchingCost, WorkflowRecommendation


@dataclass
class TaskTypeConfig:
    """Configuration for a task type."""
    primary_tool: str
    secondary_tools: list[str]
    avoid_tools: list[str]
    rationale: str
    estimated_efficiency_gain: float


# Task type recommendations based on workflow analysis
TASK_TYPE_RECOMMENDATIONS: dict[str, TaskTypeConfig] = {
    "debugging": TaskTypeConfig(
        primary_tool="claude_code",
        secondary_tools=["cursor"],
        avoid_tools=["copilot"],
        rationale="Debugging needs deep context understanding and multi-file analysis. Claude Code excels at tracing issues across files.",
        estimated_efficiency_gain=0.35,
    ),
    "greenfield": TaskTypeConfig(
        primary_tool="claude_code",
        secondary_tools=["cursor", "kiro"],
        avoid_tools=[],
        rationale="New features benefit from full conversation context and architectural reasoning.",
        estimated_efficiency_gain=0.30,
    ),
    "quick_fix": TaskTypeConfig(
        primary_tool="copilot",
        secondary_tools=["cursor"],
        avoid_tools=["claude_code"],
        rationale="Simple changes like typos or single-line fixes don't need full agent session overhead.",
        estimated_efficiency_gain=0.50,
    ),
    "refactoring": TaskTypeConfig(
        primary_tool="claude_code",
        secondary_tools=["cursor"],
        avoid_tools=["copilot"],
        rationale="Refactoring needs architectural understanding and safe transformation patterns.",
        estimated_efficiency_gain=0.40,
    ),
    "exploration": TaskTypeConfig(
        primary_tool="cursor",
        secondary_tools=["claude_code"],
        avoid_tools=["copilot"],
        rationale="Codebase exploration benefits from IDE integration and semantic search.",
        estimated_efficiency_gain=0.25,
    ),
    "code_review": TaskTypeConfig(
        primary_tool="claude_code",
        secondary_tools=["cursor"],
        avoid_tools=[],
        rationale="Code review needs deep analysis and understanding of patterns across the codebase.",
        estimated_efficiency_gain=0.30,
    ),
    "documentation": TaskTypeConfig(
        primary_tool="claude_code",
        secondary_tools=["copilot"],
        avoid_tools=[],
        rationale="Documentation benefits from context understanding but can start with suggestions.",
        estimated_efficiency_gain=0.20,
    ),
    "testing": TaskTypeConfig(
        primary_tool="claude_code",
        secondary_tools=["cursor"],
        avoid_tools=["copilot"],
        rationale="Test writing needs understanding of code behavior and edge cases.",
        estimated_efficiency_gain=0.35,
    ),
    "devops": TaskTypeConfig(
        primary_tool="claude_code",
        secondary_tools=["cursor"],
        avoid_tools=["copilot"],
        rationale="DevOps tasks need understanding of system architecture and configuration.",
        estimated_efficiency_gain=0.25,
    ),
}


# Tool switching costs - how much context is lost when switching between tools
SWITCHING_COSTS: dict[tuple[str, str], SwitchingCost] = {
    # From Copilot
    ("copilot", "claude_code"): SwitchingCost(
        from_tool="copilot",
        to_tool="claude_code",
        context_loss_score=0.7,
        ramp_up_time_minutes=5.0,
        mitigation_strategy="Copy relevant code context or describe the issue fresh in Claude Code",
    ),
    ("copilot", "cursor"): SwitchingCost(
        from_tool="copilot",
        to_tool="cursor",
        context_loss_score=0.4,
        ramp_up_time_minutes=2.0,
        mitigation_strategy="Copilot suggestions often transfer to Cursor's context via editor state",
    ),
    ("copilot", "kiro"): SwitchingCost(
        from_tool="copilot",
        to_tool="kiro",
        context_loss_score=0.6,
        ramp_up_time_minutes=3.0,
        mitigation_strategy="Start fresh with clear requirements",
    ),

    # From Cursor
    ("cursor", "claude_code"): SwitchingCost(
        from_tool="cursor",
        to_tool="claude_code",
        context_loss_score=0.5,
        ramp_up_time_minutes=3.0,
        mitigation_strategy="Projects often overlap. Reference files cursor was working on",
    ),
    ("cursor", "copilot"): SwitchingCost(
        from_tool="cursor",
        to_tool="copilot",
        context_loss_score=0.3,
        ramp_up_time_minutes=1.0,
        mitigation_strategy="Low cost - Copilot picks up from editor state",
    ),
    ("cursor", "kiro"): SwitchingCost(
        from_tool="cursor",
        to_tool="kiro",
        context_loss_score=0.4,
        ramp_up_time_minutes=2.0,
        mitigation_strategy="Similar IDE context, easy transfer",
    ),

    # From Claude Code
    ("claude_code", "cursor"): SwitchingCost(
        from_tool="claude_code",
        to_tool="cursor",
        context_loss_score=0.5,
        ramp_up_time_minutes=3.0,
        mitigation_strategy="Reference Claude's analysis in Cursor prompt for continuation",
    ),
    ("claude_code", "copilot"): SwitchingCost(
        from_tool="claude_code",
        to_tool="copilot",
        context_loss_score=0.6,
        ramp_up_time_minutes=2.0,
        mitigation_strategy="Copilot won't have Claude's context - use for simple completions only",
    ),
    ("claude_code", "kiro"): SwitchingCost(
        from_tool="claude_code",
        to_tool="kiro",
        context_loss_score=0.5,
        ramp_up_time_minutes=3.0,
        mitigation_strategy="Start fresh with clear requirements based on Claude's work",
    ),

    # From Kiro
    ("kiro", "claude_code"): SwitchingCost(
        from_tool="kiro",
        to_tool="claude_code",
        context_loss_score=0.5,
        ramp_up_time_minutes=3.0,
        mitigation_strategy="Describe Kiro's spec or current state in Claude",
    ),
    ("kiro", "cursor"): SwitchingCost(
        from_tool="kiro",
        to_tool="cursor",
        context_loss_score=0.4,
        ramp_up_time_minutes=2.0,
        mitigation_strategy="Similar IDE context transfer",
    ),
    ("kiro", "copilot"): SwitchingCost(
        from_tool="kiro",
        to_tool="copilot",
        context_loss_score=0.6,
        ramp_up_time_minutes=2.0,
        mitigation_strategy="Copilot won't have Kiro's context",
    ),
}


# Known workflow patterns with their characteristics
WORKFLOW_PATTERNS = {
    "iterative_refinement": {
        "description": "Quick suggestion → IDE refinement → Deep implementation",
        "tools": ["copilot", "cursor", "claude_code"],
        "typical_sequence": ["copilot", "cursor", "claude_code"],
        "efficiency": "high",
        "best_for": ["greenfield", "refactoring"],
        "avg_duration_minutes": 45,
    },
    "parallel_exploration": {
        "description": "Multiple tools used simultaneously for different aspects",
        "tools": [],  # Any combination
        "efficiency": "medium",
        "best_for": ["exploration", "code_review"],
        "avg_duration_minutes": 60,
    },
    "single_tool_deep_dive": {
        "description": "Extended session with single tool",
        "tools": ["claude_code"],
        "typical_sequence": ["claude_code"],
        "efficiency": "varies",
        "best_for": ["debugging", "refactoring", "greenfield"],
        "avg_duration_minutes": 30,
    },
    "quick_iteration": {
        "description": "Rapid back-and-forth between two tools",
        "tools": [],  # Any pair
        "efficiency": "low",
        "best_for": [],  # Usually indicates inefficiency
        "avg_duration_minutes": 20,
    },
    "tool_hopping": {
        "description": "Frequent switching between multiple tools",
        "tools": [],  # Many tools
        "efficiency": "low",
        "best_for": [],  # Indicates lack of clear strategy
        "avg_duration_minutes": 40,
    },
}


def get_recommendation_for_task(task_type: str) -> WorkflowRecommendation | None:
    """Get workflow recommendation for a task type.

    Args:
        task_type: Type of task (debugging, greenfield, etc.)

    Returns:
        WorkflowRecommendation if found, None otherwise
    """
    config = TASK_TYPE_RECOMMENDATIONS.get(task_type.lower())
    if not config:
        return None

    return WorkflowRecommendation(
        task_type=task_type,
        primary_tool=config.primary_tool,
        secondary_tools=config.secondary_tools,
        avoid_tools=config.avoid_tools,
        rationale=config.rationale,
        estimated_efficiency_gain=config.estimated_efficiency_gain,
    )


def get_switching_cost(from_tool: str, to_tool: str) -> SwitchingCost | None:
    """Get switching cost between two tools.

    Args:
        from_tool: Source tool name
        to_tool: Target tool name

    Returns:
        SwitchingCost if found, None otherwise
    """
    return SWITCHING_COSTS.get((from_tool.lower(), to_tool.lower()))


def get_pattern_info(pattern_name: str) -> dict | None:
    """Get information about a workflow pattern.

    Args:
        pattern_name: Name of the pattern

    Returns:
        Pattern info dict if found, None otherwise
    """
    return WORKFLOW_PATTERNS.get(pattern_name.lower())


def get_all_tool_names() -> list[str]:
    """Get list of all known tool names."""
    return list(set(
        [t[0] for t in SWITCHING_COSTS.keys()] +
        [t[1] for t in SWITCHING_COSTS.keys()]
    ))


def calculate_optimal_workflow(task_type: str, available_tools: list[str]) -> list[str]:
    """Calculate optimal workflow for a task given available tools.

    Args:
        task_type: Type of task
        available_tools: List of tools available to the user

    Returns:
        List of tool names in optimal sequence
    """
    recommendation = get_recommendation_for_task(task_type)
    if not recommendation:
        return available_tools[:1] if available_tools else []

    # Filter to available tools
    workflow = []
    if recommendation.primary_tool in available_tools:
        workflow.append(recommendation.primary_tool)

    for tool in recommendation.secondary_tools:
        if tool in available_tools and tool not in workflow:
            workflow.append(tool)

    # If no recommended tools available, use first available
    if not workflow and available_tools:
        return available_tools[:1]

    return workflow
