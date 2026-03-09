"""Human-readable number formatting utilities."""

from __future__ import annotations


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
