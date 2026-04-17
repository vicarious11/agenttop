# Architecture — data flow and persistence

This note explains the data model and why new fields on `Session` do not
require a migration. It is aimed at reviewers and contributors who see the
`sessions` table in `db.py` and expect the usual ORM-style concerns.

## Source of truth: the tool directories

agenttop is a **read-only viewer** over data that other tools already store
on disk. The source of truth is always the tool's own files:

| Tool        | Source                                                     |
|-------------|------------------------------------------------------------|
| Claude Code | `~/.claude/projects/**/*.jsonl`                            |
| Cursor      | `~/.cursor/ai-tracking/ai-code-tracking.db` (SQLite)       |
| Kiro        | `~/Library/.../Kiro/User/globalStorage/state.vscdb`        |
| Codex       | `~/.codex/` (JSON + SQLite)                                |
| Copilot     | `~/.config/github-copilot/session-state/` (JSON)           |

Every time a collector runs, it **re-parses these files from scratch** and
produces fresh `Session` objects. See `BaseCollector.collect_sessions()`
and its concrete implementations.

```
collectors → Session objects → web/TUI panels (no DB round-trip)
```

## The SQLite store is an optional cache, not the source

`agenttop/db.py` defines a `sessions` table with ten columns (id, tool,
project, start_time, end_time, message_count, tool_call_count,
total_tokens, estimated_cost_usd, prompts). That table:

- **Does not include `tool_breakdown` or `models_used`** — those fields
  have never been persisted to SQLite.
- **Is not read by the web or TUI dashboards.** The web server calls
  `collector.collect_sessions()` directly on every request; the TUI
  refreshes from collectors on a timer.
- **Exists for a future offline/aggregation use case** and for the
  suggestions feature. It is not the source of truth.

## Why adding fields to `Session` is not a breaking change

Given the above:

1. **Pydantic's `Field(default_factory=dict)`** guarantees every Session
   instance has the new fields, whether built fresh from a collector or
   reconstructed from DB rows that pre-date the field.
2. **The DB doesn't store these fields,** so there is no "old row that
   lacks column X" state to migrate. Reading an old row produces a
   Session with `tool_breakdown={}` — which is exactly what would happen
   for any tool that doesn't expose tool-call data.
3. **Fresh collector runs always populate the fields** (for tools that
   expose the data). By the time you see the dashboard, `Session.tool_breakdown`
   reflects the current state of your JSONL files.

No migration script is required.

## Data availability per collector

Not every tool exposes the same data. Panels that depend on
`tool_breakdown` gracefully fall back to prompt keywords for tools that
don't have it.

| Collector   | `tool_breakdown` | `models_used` | Activity classification |
|-------------|:----------------:|:-------------:|-------------------------|
| Claude Code | ✅ exact          | ✅ exact       | Tool-call based          |
| Cursor      | ➖ empty          | ✅             | Prompt keywords          |
| Kiro        | ➖ empty          | ➖ partial     | Prompt keywords          |
| Codex       | ➖ empty          | ✅             | Prompt keywords          |
| Copilot     | ➖ empty          | ✅             | Prompt keywords          |

An empty `tool_breakdown` is handled explicitly by the classifier — see
`classify_session()` in `agenttop/analysis/classifier.py`, which routes
those sessions through keyword-based fallback logic and has unit-test
coverage for both paths.

## Testing

Activity classification, one-shot rate computation, tool frequency, and
cost breakdowns are covered in `tests/test_classifier.py`. Both
branches (tool-breakdown-present and prompt-keyword-fallback) are
exercised. Run with:

```bash
pytest tests/test_classifier.py -v
```
