"""Base collector interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agenttop.models import Event, Session, ToolName, ToolStats


class BaseCollector(ABC):
    """Abstract base class for AI tool data collectors.

    To add support for a new tool, subclass BaseCollector and implement
    the three abstract methods. Register the collector in collectors/__init__.py.
    """

    @property
    @abstractmethod
    def tool_name(self) -> ToolName:
        """Which tool this collector handles."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this tool's data directory exists on this machine."""

    @abstractmethod
    def collect_events(self) -> list[Event]:
        """Collect new events since last run. Called periodically."""

    @abstractmethod
    def collect_sessions(self) -> list[Session]:
        """Collect/update session summaries."""

    @abstractmethod
    def get_stats(self, days: int = 0) -> ToolStats:
        """Return aggregated stats for the dashboard.

        Args:
            days: Number of days to aggregate. 0 = all available data.
        """
