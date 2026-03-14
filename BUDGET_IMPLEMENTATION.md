# Budget Alerting System - Implementation Summary

## Overview
This implementation adds budget alerting functionality to agenttop, showing users when their daily AI spending approaches or exceeds their configured budget threshold.

## Changes Made

### 1. Core Budget Logic (`src/agenttop/formatting.py`)
- Added `BudgetStatus` enum: `ok`, `warning`, `alert`
- Added `BudgetInfo` dataclass with status, total_cost, budget, ratio, remaining
- Added `check_budget()` function to calculate budget status
- Added `format_budget_message()` function for CLI display

**Key thresholds:**
- `OK`: Cost < 80% of budget
- `WARNING`: 80% ≤ Cost < 100% of budget
- `ALERT`: Cost ≥ 100% of budget

### 2. CLI Integration (`src/agenttop/cli.py`)
- Added budget checking to `stats` command
- Displays colored warnings when approaching or over budget
- Only shows budget status for "today" (days=0)

### 3. TUI Dashboard (`src/agenttop/tui/dashboard.py`)
- Updated `StatsBar.__init__()` to accept `budget` parameter
- Updated `StatsBar.update_stats()` to display budget indicator
- Color-coded: green (OK), yellow (WARNING), red (ALERT)
- Added budget percentage and status message to header

### 4. TUI App (`src/agenttop/tui/app.py`)
- Updated `_refresh_data()` to pass budget from config
- Only applies budget for "today" view (days=0)

### 5. Web Server (`src/agenttop/web/server.py`)
- Added `/api/budget` endpoint
- Returns budget status: enabled, budget, total_cost, ratio, remaining, status
- Budget only enabled for "all time" (days=0) to match daily budget concept

### 6. Web JavaScript (`src/agenttop/web/static/js/app.js`)
- Updated `refresh()` to fetch budget data
- Pass budget to `Stats.render()`

### 7. Web Stats Display (`src/agenttop/web/static/js/stats.js`)
- Updated `render()` to accept budget parameter
- Added budget card with:
  - Status icon and percentage
  - Color-coded border (green/yellow/red)
  - Progress bar showing usage
  - Dollar amount display
- Added data attribute for CSS targeting: `data-status`

### 8. Web CSS (`src/agenttop/web/static/css/neon.css`)
- Added `.budget-card` styles
- Added `.budget-bar` and `.budget-bar-fill` for progress visualization
- Added status-specific styles:
  - `[data-status="alert"]` - Red border, pulsing animation
  - `[data-status="warning"]` - Yellow border, glow effect
  - `[data-status="ok"]` - Green border (default)
- Added `budget-pulse` animation for alert state

### 9. Tests (`tests/test_budget.py`)
- Added comprehensive test coverage:
  - `TestBudgetCheck`: Tests `check_budget()` with all threshold scenarios
  - `TestBudgetMessageFormat`: Tests `format_budget_message()` for each status
  - `TestBudgetDataclass`: Tests `BudgetInfo` creation and enum values

## Usage

### CLI
```bash
# View stats with budget warning (if applicable)
agenttop stats

# Configure budget
# Edit ~/.agenttop/config.toml
[llm]
max_budget_per_day = 10.0
```

### TUI
- Run `agenttop` (default: today view)
- Budget indicator appears in header bar
- Color-coded based on status

### Web Dashboard
- Run `agenttop web`
- Budget card appears in stats ribbon (all time view only)
- Click for budget details via `/api/budget`

## API Endpoint

### GET `/api/budget?days=<int>`
Returns budget status for the specified time range.

**Response:**
```json
{
  "enabled": true,
  "budget": 10.0,
  "total_cost": 8.50,
  "ratio": 0.85,
  "remaining": 1.50,
  "status": "warning"
}
```

**Parameters:**
- `days`: Time range (default: 0 = all time, budget only enabled for days=0)

**Response Fields:**
- `enabled`: Whether budget is configured (> 0)
- `budget`: Configured daily budget
- `total_cost`: Total cost for the period
- `ratio`: Cost as percentage of budget (0.0 to 1.0+)
- `remaining`: Budget minus total_cost (negative if over)
- `status`: "ok" | "warning" | "alert"

## Testing

Run tests with:
```bash
cd /tmp/agenttop
python3 -m pytest tests/test_budget.py -v
```

Test coverage includes:
- All threshold scenarios (below warning, at warning, above warning, at limit, over limit)
- Message formatting for each status level
- BudgetInfo dataclass creation
- BudgetStatus enum values

## Configuration

Add to `~/.agenttop/config.toml`:

```toml
[llm]
max_budget_per_day = 10.0  # USD, set to 0 to disable
```

Or set via environment variable:
```bash
export AGENTTOP_LLM_MAX_BUDGET_PER_DAY=10.0
```

## Design Decisions

1. **Budget only applies to "today" view** - Daily budget concept doesn't translate well to 7-day or 30-day views
2. **Graceful degradation** - System works normally if budget is 0 or not configured
3. **Consistent thresholds** - Same 80%/100% thresholds across CLI, TUI, and Web
4. **Visual hierarchy** - Alert > Warning > OK in all interfaces
5. **No breaking changes** - All new features are additive

## Files Modified

| File | Lines Added | Lines Modified | Description |
|------|---------------|-----------------|-------------|
| `src/agenttop/formatting.py` | ~70 | ~0 | Core budget logic |
| `src/agenttop/cli.py` | ~8 | ~2 | CLI budget display |
| `src/agenttop/tui/dashboard.py` | ~25 | ~5 | TUI budget indicator |
| `src/agenttop/tui/app.py` | ~5 | ~1 | TUI budget passing |
| `src/agenttop/web/server.py` | ~30 | ~2 | API endpoint |
| `src/agenttop/web/static/js/app.js` | ~5 | ~2 | Budget fetching |
| `src/agenttop/web/static/js/stats.js` | ~50 | ~10 | Budget display |
| `src/agenttop/web/static/css/neon.css` | ~60 | ~0 | Budget styles |
| `tests/test_budget.py` | ~160 | ~0 | Test coverage |

**Total:** ~413 lines added/modified

## Backward Compatibility

- All changes are additive
- Existing functionality unchanged
- Budget feature is opt-in (0 budget = disabled)
- No API breaking changes

## Future Enhancements

Possible future improvements:
1. Per-tool budget limits
2. Budget history/over time tracking
3. Alert notifications (email, browser notifications)
4. Budget forecasting based on trends
5. Custom threshold configuration
6. Export budget reports

## Screenshots

### CLI (Alert)
```
agenttop — AI Tool Usage Summary (today)
======================================================
⚠️  OVER BUDGET: $12.50 (125% of $10.00 limit)
======================================================
```

### CLI (Warning)
```
⚠️  $8.50 (85% of $10.00 daily budget)
```

### Web Dashboard
- Budget card appears in stats ribbon (all time view)
- Green bar: OK (< 80%)
- Yellow bar: WARNING (80-99%)
- Red pulsing bar: ALERT (≥ 100%)
