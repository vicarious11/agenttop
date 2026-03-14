"""Human-readable number formatting utilities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BudgetStatus(str, Enum):
    """Budget status levels."""
    OK = "ok"
    WARNING = "warning"
    ALERT = "alert"


@dataclass
class BudgetInfo:
    """Budget status information."""
    status: BudgetStatus
    total_cost: float
    budget: float
    ratio: float
    remaining: float


def human_number(n: int | float) -> str:
    """Format large numbers for display: 85605600 → '85.6M', 1234 → '1.2K', 500 → '500'."""
    if abs(n) >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if abs(n) >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def human_cost(n: float) -> str:
    """Format cost values: 513.63 → '$513.63', 1234.5 → '$1.2K'."""
    if abs(n) >= 1000:
        return f"${human_number(n)}"
    return f"${n:.2f}"


def human_tokens(n: int) -> str:
    """Format token counts: 85605600 → '85.6M', 0 → '0'."""
    return human_number(n) if n else "0"


def human_duration_ms(ms: int | float) -> str:
    """Format milliseconds to human-readable duration: 668922566 → '7.7 days'."""
    seconds = ms / 1000
    if seconds >= 86400:
        return f"{seconds / 86400:.1f} days"
    if seconds >= 3600:
        return f"{seconds / 3600:.1f} hours"
    if seconds >= 60:
        return f"{seconds / 60:.0f} min"
    return f"{seconds:.0f}s"


def check_budget(total_cost: float, budget: float) -> BudgetInfo:
    """Check budget status and return budget information.

    Args:
        total_cost: Total cost for the current period.
        budget: Budget threshold for the period.

    Returns:
        BudgetInfo with status, ratio, and remaining amount.
    """
    if budget <= 0:
        # Budgeting disabled or invalid
        return BudgetInfo(
            status=BudgetStatus.OK,
            total_cost=total_cost,
            budget=budget,
            ratio=0.0,
            remaining=0.0,
        )

    ratio = total_cost / budget
    remaining = budget - total_cost

    if ratio >= 1.0:
        status = BudgetStatus.ALERT
    elif ratio >= 0.8:
        status = BudgetStatus.WARNING
    else:
        status = BudgetStatus.OK

    return BudgetInfo(
        status=status,
        total_cost=total_cost,
        budget=budget,
        ratio=ratio,
        remaining=remaining,
    )


def format_budget_message(budget_info: BudgetInfo) -> str:
    """Format budget status message for CLI display.

    Args:
        budget_info: Budget information from check_budget().

    Returns:
        Formatted message with appropriate styling.
    """
    if budget_info.status == BudgetStatus.ALERT:
        return (
            f"[red]⚠️  OVER BUDGET: ${budget_info.total_cost:.2f} "
            f"(${budget_info.ratio:.0%} of ${budget_info.budget:.2f} limit)[/red]"
        )
    elif budget_info.status == BudgetStatus.WARNING:
        return (
            f"[yellow]⚠️  ${budget_info.total_cost:.2f} "
            f"(${budget_info.ratio:.0%} of ${budget_info.budget:.2f} daily budget)[/yellow]"
        )
    else:
        return f"${budget_info.total_cost:.2f} of ${budget_info.budget:.2f} daily budget"
