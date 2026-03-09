"""Pydantic models for agenttop events, sessions, and analysis."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ToolName(str, Enum):
    CLAUDE_CODE = "claude_code"
    CURSOR = "cursor"
    KIRO = "kiro"
    COPILOT = "copilot"
    CODEX = "codex"
    WINDSURF = "windsurf"
    CONTINUE = "continue"
    AIDER = "aider"
    GENERIC = "generic"


class Event(BaseModel):
    """A single event captured from any AI tool."""

    id: int | None = None
    tool: ToolName
    event_type: str  # e.g. "message", "tool_call", "session_start", "session_end"
    timestamp: datetime
    session_id: str | None = None
    project: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    token_count: int | None = None
    cost_usd: float | None = None


class Session(BaseModel):
    """An aggregated AI tool session."""

    id: str
    tool: ToolName
    project: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    message_count: int = 0
    tool_call_count: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    prompts: list[str] = Field(default_factory=list)


class ToolStats(BaseModel):
    """Aggregated stats for a single tool (shown in dashboard rows)."""

    tool: ToolName
    sessions_today: int = 0
    messages_today: int = 0
    tool_calls_today: int = 0
    tokens_today: int = 0
    estimated_cost_today: float = 0.0
    status: str = "idle"  # idle, active, error
    hourly_tokens: list[int] = Field(default_factory=lambda: [0] * 24)


class IntentCategory(str, Enum):
    DEBUGGING = "debugging"
    REFACTORING = "refactoring"
    GREENFIELD = "greenfield"
    EXPLORATION = "exploration"
    CODE_REVIEW = "code_review"
    DEVOPS = "devops"
    DOCUMENTATION = "documentation"
    UNKNOWN = "unknown"


class SessionIntent(BaseModel):
    """Classified intent for a session."""

    session_id: str
    intent: IntentCategory
    confidence: float = 0.0
    summary: str = ""


class Suggestion(BaseModel):
    """An actionable recommendation from the analysis engine."""

    id: int | None = None
    tool: ToolName | None = None
    category: str  # e.g. "config", "workflow", "cost", "memory"
    title: str
    description: str
    estimated_savings: str | None = None  # e.g. "~2000 tokens/session"
    priority: int = 0  # 0=low, 1=medium, 2=high
    created_at: datetime = Field(default_factory=datetime.now)
    dismissed: bool = False


class DailySummary(BaseModel):
    """Daily aggregated metrics across all tools."""

    date: str  # YYYY-MM-DD
    total_sessions: int = 0
    total_messages: int = 0
    total_tool_calls: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    tools: dict[str, ToolStats] = Field(default_factory=dict)
    intents: dict[str, int] = Field(default_factory=dict)
