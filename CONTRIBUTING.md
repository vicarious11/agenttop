# Contributing to agenttop

## Adding a New Collector

The easiest way to contribute is adding support for a new AI tool.

1. Create `src/agenttop/collectors/your_tool.py`
2. Subclass `BaseCollector`:

```python
from agenttop.collectors.base import BaseCollector
from agenttop.models import Event, Session, ToolName, ToolStats

class YourToolCollector(BaseCollector):
    @property
    def tool_name(self) -> ToolName:
        return ToolName.YOUR_TOOL  # Add to the enum first

    def is_available(self) -> bool:
        # Check if the tool's data directory exists
        return Path("~/.your-tool").expanduser().exists()

    def collect_events(self) -> list[Event]:
        # Parse local data files into Event objects
        ...

    def collect_sessions(self) -> list[Session]:
        # Aggregate events into sessions
        ...

    def get_stats(self) -> ToolStats:
        # Return today's aggregated stats for the dashboard
        ...
```

3. Add the tool to `ToolName` enum in `models.py`
4. Register in `tui/app.py` `_init_collectors()`
5. Add tests in `tests/test_collectors.py`

## Development Setup

```bash
git clone https://github.com/vicarious11/agenttop
cd agenttop
pip install -e ".[dev]"
pytest
ruff check src/ tests/
```

## Guidelines

- Keep collectors read-only — never modify the tool's data files
- All data stays local — never send raw prompts to external services
- Estimate tokens conservatively when exact counts aren't available
- Add tests for your collector with mock data
