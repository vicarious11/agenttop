"""Tests for budget functionality."""

from fastapi.testclient import TestClient

from agenttop.formatting import BudgetInfo, BudgetStatus, check_budget, format_budget_message
from agenttop.web.server import app


class TestBudgetCheck:
    """Tests for check_budget function."""

    def test_budget_disabled_zero_returns_ok(self) -> None:
        """Zero budget returns OK status."""
        result = check_budget(5.0, 0.0)

        assert result.status == BudgetStatus.OK
        assert result.total_cost == 5.0
        assert result.budget == 0.0
        assert result.ratio == 0.0

    def test_budget_ok_below_warning_threshold(self) -> None:
        """Cost below 80% threshold returns OK."""
        result = check_budget(7.0, 10.0)

        assert result.status == BudgetStatus.OK
        assert result.ratio == 0.7
        assert result.remaining == 3.0

    def test_budget_at_warning_threshold(self) -> None:
        """Cost at exactly 80% returns WARNING."""
        result = check_budget(8.0, 10.0)

        assert result.status == BudgetStatus.WARNING
        assert result.ratio == 0.8
        assert result.remaining == 2.0

    def test_budget_above_warning_threshold(self) -> None:
        """Cost above 80% but below 100% returns WARNING."""
        result = check_budget(9.5, 10.0)

        assert result.status == BudgetStatus.WARNING
        assert result.ratio == 0.95
        assert result.remaining == 0.5

    def test_budget_exactly_limit_returns_alert(self) -> None:
        """Cost at exactly budget returns ALERT."""
        result = check_budget(10.0, 10.0)

        assert result.status == BudgetStatus.ALERT
        assert result.ratio == 1.0
        assert result.remaining == 0.0

    def test_budget_over_limit_returns_alert(self) -> None:
        """Cost over budget returns ALERT."""
        result = check_budget(12.0, 10.0)

        assert result.status == BudgetStatus.ALERT
        assert result.ratio == 1.2
        assert result.remaining == -2.0

    def test_zero_cost_returns_ok(self) -> None:
        """Zero cost returns OK status."""
        result = check_budget(0.0, 10.0)

        assert result.status == BudgetStatus.OK
        assert result.ratio == 0.0
        assert result.remaining == 10.0


class TestBudgetMessageFormat:
    """Tests for format_budget_message function."""

    def test_ok_status_message(self) -> None:
        """OK status returns plain message."""
        budget_info = BudgetInfo(
            status=BudgetStatus.OK,
            total_cost=5.0,
            budget=10.0,
            ratio=0.5,
            remaining=5.0,
        )
        message, color = format_budget_message(budget_info)

        assert "OVER BUDGET" not in message
        assert "WARNING" not in message
        assert "$5.00 of $10.00 daily budget" in message
        assert color == "green"

    def test_warning_status_message(self) -> None:
        """WARNING status includes yellow warning."""
        budget_info = BudgetInfo(
            status=BudgetStatus.WARNING,
            total_cost=8.5,
            budget=10.0,
            ratio=0.85,
            remaining=1.5,
        )
        message, color = format_budget_message(budget_info)

        assert "⚠️" in message
        assert "85%" in message
        assert "$8.50" in message
        assert "$10.00" in message
        assert color == "yellow"

    def test_alert_status_message(self) -> None:
        """ALERT status includes red warning."""
        budget_info = BudgetInfo(
            status=BudgetStatus.ALERT,
            total_cost=12.0,
            budget=10.0,
            ratio=1.2,
            remaining=-2.0,
        )
        message, color = format_budget_message(budget_info)

        assert "⚠️" in message
        assert "OVER BUDGET" in message
        assert "120%" in message
        assert "$12.00" in message
        assert color == "red"


class TestBudgetDataclass:
    """Tests for BudgetInfo dataclass."""

    def test_budget_info_creation(self) -> None:
        """BudgetInfo creates with all fields."""
        budget_info = BudgetInfo(
            status=BudgetStatus.WARNING,
            total_cost=8.0,
            budget=10.0,
            ratio=0.8,
            remaining=2.0,
        )

        assert budget_info.status == BudgetStatus.WARNING
        assert budget_info.total_cost == 8.0
        assert budget_info.budget == 10.0
        assert budget_info.ratio == 0.8
        assert budget_info.remaining == 2.0

    def test_budget_status_enum_values(self) -> None:
        """BudgetStatus enum has correct string values."""
        assert BudgetStatus.OK == "ok"
        assert BudgetStatus.WARNING == "warning"
        assert BudgetStatus.ALERT == "alert"


class TestBudgetAPI:
    """Tests for /api/budget endpoint."""

    def test_api_budget_endpoint_today_enabled(self) -> None:
        """Test /api/budget endpoint with budget enabled for today."""
        client = TestClient(app)
        response = client.get("/api/budget?days=1")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "enabled" in data
        assert "budget" in data
        assert "total_cost" in data
        assert "ratio" in data
        assert "remaining" in data
        assert "status" in data

        # Verify status is a string, not enum
        assert data["status"] in ["ok", "warning", "alert"]

    def test_api_budget_endpoint_other_timeframe(self) -> None:
        """Test /api/budget endpoint returns disabled for non-today timeframes."""
        client = TestClient(app)
        response = client.get("/api/budget?days=7")

        assert response.status_code == 200
        data = response.json()

        assert data["enabled"] is False
        assert data["status"] == "ok"
        assert data["budget"] == 0.0

    def test_api_budget_endpoint_all_time(self) -> None:
        """Test /api/budget endpoint returns disabled for all-time (days=0)."""
        client = TestClient(app)
        response = client.get("/api/budget?days=0")

        assert response.status_code == 200
        data = response.json()

        # Budget is disabled for all-time view
        assert data["enabled"] is False
        assert data["status"] == "ok"
        assert data["budget"] == 0.0
