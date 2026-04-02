"""Workflow analysis constants."""

from __future__ import annotations

from datetime import timedelta

# Workflow analysis intervals
WORKFLOW_INTERVALS = {
    "very_short": timedelta(minutes=5),
    "short": timedelta(minutes=15),
    "medium": timedelta(minutes=30),
    "long": timedelta(hours=1),
    "very_long": timedelta(hours=2),
}


def all_timezones() -> list[str]:
    """Return list of common timezones for workflow analysis.

    This is a simplified list for the workflow module. For a complete
    list, use pytz or zoneinfo in your application code.
    """
    return [
        "US/Pacific",
        "US/Eastern",
        "US/Central",
        "US/Mountain",
        "Europe/London",
        "Europe/Paris",
        "Europe/Berlin",
        "Asia/Tokyo",
        "Asia/Shanghai",
        "Asia/Kolkata",
        "Australia/Sydney",
        "UTC",
    ]
