"""Tests for enriched collectors' get_feature_config() methods.

Covers: CursorCollector, CodexCollector, CopilotCollector, KiroCollector.
"""

import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from agenttop.collectors.codex import CodexCollector
from agenttop.collectors.copilot import CopilotCollector
from agenttop.collectors.cursor import CursorCollector
from agenttop.collectors.kiro import KiroCollector


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, data: Any) -> None:
    """Write JSON data to a file, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _create_sqlite_db(path: Path, schema_statements: list[str]) -> None:
    """Create a SQLite DB with the given CREATE TABLE statements."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    for stmt in schema_statements:
        conn.execute(stmt)
    conn.commit()
    conn.close()


# ===========================================================================
# CursorCollector.get_feature_config()
# ===========================================================================

class TestCursorFeatureConfig:
    """Tests for CursorCollector.get_feature_config()."""

    @pytest.fixture()
    def cursor_dir(self) -> Path:
        return Path(tempfile.mkdtemp())

    def _make_cursor_db(self, cursor_dir: Path) -> Path:
        """Create a Cursor DB with all required tables including tracking_state."""
        db_path = cursor_dir / "ai-tracking" / "ai-code-tracking.db"
        _create_sqlite_db(db_path, [
            "CREATE TABLE ai_code_hashes ("
            "  hash TEXT, model TEXT, source TEXT, fileName TEXT,"
            "  conversationId TEXT, createdAt INTEGER"
            ")",
            "CREATE TABLE conversation_summaries ("
            "  conversationId TEXT, title TEXT, tldr TEXT,"
            "  model TEXT, mode TEXT, updatedAt INTEGER"
            ")",
            "CREATE TABLE scored_commits ("
            "  scoredAt INTEGER, tabLinesAdded INTEGER,"
            "  composerLinesAdded INTEGER, humanLinesAdded INTEGER"
            ")",
            "CREATE TABLE tracking_state (key TEXT PRIMARY KEY, value TEXT)",
        ])
        return db_path

    def test_tracking_state_returned(self, cursor_dir: Path) -> None:
        """tracking_state with valid trackingStartTime is parsed correctly."""
        db_path = self._make_cursor_db(cursor_dir)
        start_ms = int(datetime(2025, 1, 1).timestamp() * 1000)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO tracking_state VALUES (?, ?)",
            ("trackingStartTime", json.dumps({"timestamp": start_ms})),
        )
        conn.commit()
        conn.close()

        collector = CursorCollector(cursor_dir=cursor_dir)
        config = collector.get_feature_config()

        assert "tracking_state" in config
        assert config["tracking_state"]["start_time_ms"] == start_ms
        assert config["tracking_state"]["tracking_days"] >= 0

    def test_tracking_state_missing_key(self, cursor_dir: Path) -> None:
        """No trackingStartTime row => no tracking_state in result."""
        self._make_cursor_db(cursor_dir)

        collector = CursorCollector(cursor_dir=cursor_dir)
        config = collector.get_feature_config()

        assert "tracking_state" not in config

    def test_table_row_counts(self, cursor_dir: Path) -> None:
        """Row counts are returned for each table with data."""
        db_path = self._make_cursor_db(cursor_dir)
        now_ms = int(datetime.now().timestamp() * 1000)

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO ai_code_hashes VALUES (?, ?, ?, ?, ?, ?)",
            ("h1", "gpt-4o", "composer", "/f.py", "c1", now_ms),
        )
        conn.execute(
            "INSERT INTO ai_code_hashes VALUES (?, ?, ?, ?, ?, ?)",
            ("h2", "gpt-4o", "tab", "/g.py", "c1", now_ms),
        )
        conn.execute(
            "INSERT INTO conversation_summaries VALUES (?, ?, ?, ?, ?, ?)",
            ("c1", "Title", "TLDR", "gpt-4o", "chat", now_ms),
        )
        conn.execute(
            "INSERT INTO scored_commits VALUES (?, ?, ?, ?)",
            (now_ms, 10, 20, 50),
        )
        conn.commit()
        conn.close()

        collector = CursorCollector(cursor_dir=cursor_dir)
        config = collector.get_feature_config()

        assert "table_row_counts" in config
        counts = config["table_row_counts"]
        assert counts["ai_code_hashes"] == 2
        assert counts["conversation_summaries"] == 1
        assert counts["scored_commits"] == 1

    def test_db_size_bytes_present(self, cursor_dir: Path) -> None:
        """db_size_bytes is a positive integer when DB exists."""
        self._make_cursor_db(cursor_dir)

        collector = CursorCollector(cursor_dir=cursor_dir)
        config = collector.get_feature_config()

        assert "db_size_bytes" in config
        assert config["db_size_bytes"] > 0

    def test_ai_vs_human_included(self, cursor_dir: Path) -> None:
        """ai_vs_human ratio is included in feature config."""
        db_path = self._make_cursor_db(cursor_dir)
        now_ms = int(datetime.now().timestamp() * 1000)

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO scored_commits VALUES (?, ?, ?, ?)",
            (now_ms, 5, 15, 30),
        )
        conn.commit()
        conn.close()

        collector = CursorCollector(cursor_dir=cursor_dir)
        config = collector.get_feature_config()

        assert "ai_vs_human" in config
        assert config["ai_vs_human"]["ai_lines"] == 20
        assert config["ai_vs_human"]["human_lines"] == 30

    def test_missing_db_returns_defaults(self) -> None:
        """Missing DB returns empty dicts / zero values, no crash."""
        collector = CursorCollector(cursor_dir=Path("/nonexistent/cursor"))
        config = collector.get_feature_config()

        assert "tracking_state" not in config
        # ai_vs_human returns zeroed dict even when DB is missing (no rows to count)
        ai_vs_human = config.get("ai_vs_human", {})
        assert ai_vs_human.get("ai_lines", 0) == 0
        assert ai_vs_human.get("human_lines", 0) == 0
        assert config.get("db_size_bytes") == 0


# ===========================================================================
# CodexCollector.get_feature_config()
# ===========================================================================

class TestCodexFeatureConfig:
    """Tests for CodexCollector.get_feature_config()."""

    @pytest.fixture()
    def codex_dir(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp

    def test_global_state_prompt_history(self, codex_dir: Path) -> None:
        """Prompt history from .codex-global-state.json is included."""
        state = {
            "prompt-history": ["fix the bug", "add tests", "refactor auth"],
            "agent-mode": True,
        }
        _write_json(codex_dir / ".codex-global-state.json", state)

        collector = CodexCollector(codex_dir=codex_dir)
        config = collector.get_feature_config()

        assert "global_state" in config
        gs = config["global_state"]
        assert gs["prompt_history"] == ["fix the bug", "add tests", "refactor auth"]
        assert gs["agent_mode"] is True

    def test_global_state_electron_extra_keys(self, codex_dir: Path) -> None:
        """Extra keys beyond prompt-history and agent-mode go to electron_state."""
        state = {
            "prompt-history": [],
            "window-size": {"width": 1200, "height": 800},
        }
        _write_json(codex_dir / ".codex-global-state.json", state)

        collector = CodexCollector(codex_dir=codex_dir)
        config = collector.get_feature_config()

        gs = config["global_state"]
        assert "electron_state" in gs
        assert gs["electron_state"]["window-size"] == {"width": 1200, "height": 800}

    def test_codex_db_automations(self, codex_dir: Path) -> None:
        """Automations from codex-dev.db are parsed."""
        db_path = codex_dir / "sqlite" / "codex-dev.db"
        _create_sqlite_db(db_path, [
            "CREATE TABLE automations (name TEXT, status TEXT)",
        ])
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO automations VALUES (?, ?)", ("lint-on-save", "active"))
        conn.execute("INSERT INTO automations VALUES (?, ?)", ("format-code", "paused"))
        conn.commit()
        conn.close()

        collector = CodexCollector(codex_dir=codex_dir)
        config = collector.get_feature_config()

        assert "database" in config
        auto = config["database"]["automations"]
        assert auto["count"] == 2
        assert "lint-on-save" in auto["names"]
        assert "format-code" in auto["names"]
        assert set(auto["statuses"]) == {"active", "paused"}

    def test_codex_db_automation_runs(self, codex_dir: Path) -> None:
        """Automation runs table is counted with last_run timestamp."""
        db_path = codex_dir / "sqlite" / "codex-dev.db"
        _create_sqlite_db(db_path, [
            "CREATE TABLE automation_runs (created_at TEXT)",
        ])
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO automation_runs VALUES (?)", ("2025-06-01 10:00:00",))
        conn.execute("INSERT INTO automation_runs VALUES (?)", ("2025-06-02 14:30:00",))
        conn.commit()
        conn.close()

        collector = CodexCollector(codex_dir=codex_dir)
        config = collector.get_feature_config()

        runs = config["database"]["automation_runs"]
        assert runs["count"] == 2
        assert runs["last_run"] == "2025-06-02 14:30:00"

    def test_codex_db_inbox_items(self, codex_dir: Path) -> None:
        """Inbox items are counted."""
        db_path = codex_dir / "sqlite" / "codex-dev.db"
        _create_sqlite_db(db_path, [
            "CREATE TABLE inbox_items (id TEXT)",
        ])
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO inbox_items VALUES (?)", ("item-1",))
        conn.commit()
        conn.close()

        collector = CodexCollector(codex_dir=codex_dir)
        config = collector.get_feature_config()

        assert config["database"]["inbox_items"]["count"] == 1

    def test_config_toml_parsed(self, codex_dir: Path) -> None:
        """config.toml model and reasoning_effort are extracted."""
        toml_content = b'model = "o3-mini"\nreasoning_effort = "high"\napproval_mode = "auto"\n'
        config_path = codex_dir / "config.toml"
        config_path.write_bytes(toml_content)

        collector = CodexCollector(codex_dir=codex_dir)
        config = collector.get_feature_config()

        assert "config" in config
        assert config["config"]["model"] == "o3-mini"
        assert config["config"]["reasoning_effort"] == "high"
        assert config["config"]["approval_mode"] == "auto"

    def test_models_cache(self, codex_dir: Path) -> None:
        """models_cache.json list of model strings is returned."""
        _write_json(codex_dir / "models_cache.json", ["gpt-4o", "o3-mini", "codex-mini-latest"])

        collector = CodexCollector(codex_dir=codex_dir)
        config = collector.get_feature_config()

        assert config["models_cache"] == ["gpt-4o", "o3-mini", "codex-mini-latest"]

    def test_missing_all_files(self) -> None:
        """Missing codex dir returns empty config, no crash."""
        collector = CodexCollector(codex_dir=Path("/nonexistent/codex"))
        config = collector.get_feature_config()

        assert config == {}

    def test_missing_global_state(self, codex_dir: Path) -> None:
        """Missing .codex-global-state.json is handled gracefully."""
        collector = CodexCollector(codex_dir=codex_dir)
        config = collector.get_feature_config()

        assert "global_state" not in config

    def test_missing_db(self, codex_dir: Path) -> None:
        """Missing codex-dev.db is handled gracefully."""
        collector = CodexCollector(codex_dir=codex_dir)
        config = collector.get_feature_config()

        assert "database" not in config

    def test_missing_config_toml(self, codex_dir: Path) -> None:
        """Missing config.toml is handled gracefully."""
        collector = CodexCollector(codex_dir=codex_dir)
        config = collector.get_feature_config()

        assert "config" not in config


# ===========================================================================
# CopilotCollector.get_feature_config()
# ===========================================================================

class TestCopilotFeatureConfig:
    """Tests for CopilotCollector.get_feature_config()."""

    @pytest.fixture()
    def copilot_dir(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp

    def test_config_file_parsed(self, copilot_dir: Path) -> None:
        """Config file with JSON settings is parsed."""
        config_data = {
            "github.com": {"user": "testuser", "oauth_token": "secret"},
            "editor": "vscode",
            "telemetry": False,
        }
        _write_json(copilot_dir / "config", config_data)

        collector = CopilotCollector(copilot_dir=copilot_dir)
        config = collector.get_feature_config()

        assert config["config"]["exists"] is True
        # Only scalar values are included in settings
        settings = config["config"]["settings"]
        assert settings["editor"] == "vscode"
        assert settings["telemetry"] is False
        # Dict values (like "github.com") are excluded from scalar-only filter
        assert "github.com" not in settings

    def test_config_file_missing(self, copilot_dir: Path) -> None:
        """Missing config file reports exists=False."""
        collector = CopilotCollector(copilot_dir=copilot_dir)
        config = collector.get_feature_config()

        assert config["config"]["exists"] is False

    def test_agents_detected(self, copilot_dir: Path) -> None:
        """Agent definition files in agents/ are detected."""
        agents_dir = copilot_dir / "agents"
        agents_dir.mkdir()
        (agents_dir / "code-review.agent.md").write_text("# Code Review Agent")
        (agents_dir / "test-writer.agent.md").write_text("# Test Writer Agent")

        collector = CopilotCollector(copilot_dir=copilot_dir)
        config = collector.get_feature_config()

        assert config["agents"]["count"] == 2
        assert set(config["agents"]["names"]) == {"code-review", "test-writer"}

    def test_agents_dir_missing(self, copilot_dir: Path) -> None:
        """Missing agents dir returns count=0."""
        collector = CopilotCollector(copilot_dir=copilot_dir)
        config = collector.get_feature_config()

        assert config["agents"]["count"] == 0
        assert config["agents"]["names"] == []

    def test_agents_dir_empty(self, copilot_dir: Path) -> None:
        """Empty agents dir returns count=0."""
        (copilot_dir / "agents").mkdir()

        collector = CopilotCollector(copilot_dir=copilot_dir)
        config = collector.get_feature_config()

        assert config["agents"]["count"] == 0

    def test_missing_dir_entirely(self) -> None:
        """Nonexistent copilot dir still returns a config (no crash)."""
        collector = CopilotCollector(copilot_dir=Path("/nonexistent/copilot"))
        config = collector.get_feature_config()

        assert config["config"]["exists"] is False
        assert config["agents"]["count"] == 0

    def test_invalid_config_json(self, copilot_dir: Path) -> None:
        """Malformed JSON in config file is handled gracefully."""
        (copilot_dir / "config").write_text("{invalid json")

        collector = CopilotCollector(copilot_dir=copilot_dir)
        config = collector.get_feature_config()

        assert config["config"]["exists"] is True
        assert config["config"]["parse_error"] is True


# ===========================================================================
# KiroCollector.get_feature_config()
# ===========================================================================

class TestKiroFeatureConfig:
    """Tests for KiroCollector.get_feature_config()."""

    @pytest.fixture()
    def kiro_dir(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp

    def _make_state_db(self, kiro_dir: Path) -> Path:
        """Create a state.vscdb with an ItemTable containing kiro keys."""
        db_path = kiro_dir / "state.vscdb"
        _create_sqlite_db(db_path, [
            "CREATE TABLE ItemTable (key TEXT, value TEXT)",
        ])
        return db_path

    def test_kiro_state_keys_counted(self, kiro_dir: Path) -> None:
        """Keys matching kiro patterns are counted."""
        db_path = self._make_state_db(kiro_dir)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("kiro.sessions", json.dumps([{"id": "s1"}])),
        )
        conn.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("kiro.chat.history", json.dumps({"messages": []})),
        )
        conn.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("unrelated.setting", "some-value"),
        )
        conn.commit()
        conn.close()

        collector = KiroCollector(kiro_dir=kiro_dir)
        config = collector.get_feature_config()

        # "kiro.sessions" and "kiro.chat.history" both match "kiro" pattern,
        # and "kiro.chat.history" also matches "chat". Deduplication by (table, key).
        assert config["kiro_state_keys"] == 2

    def test_agent_extension_exists(self, kiro_dir: Path) -> None:
        """Agent extension dir with files is detected."""
        self._make_state_db(kiro_dir)
        agent_dir = kiro_dir / "globalStorage" / "kiro.kiroagent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "extension.js").write_text("// agent code")
        (agent_dir / "package.json").write_text("{}")

        collector = KiroCollector(kiro_dir=kiro_dir)
        config = collector.get_feature_config()

        assert config["agent_extension"]["exists"] is True
        assert config["agent_extension"]["file_count"] == 2

    def test_agent_extension_missing(self, kiro_dir: Path) -> None:
        """Missing agent extension dir returns exists=False."""
        self._make_state_db(kiro_dir)

        collector = KiroCollector(kiro_dir=kiro_dir)
        config = collector.get_feature_config()

        assert config["agent_extension"]["exists"] is False
        assert config["agent_extension"]["file_count"] == 0

    def test_missing_state_db(self) -> None:
        """Missing kiro dir returns zero keys and no agent extension."""
        collector = KiroCollector(kiro_dir=Path("/nonexistent/kiro"))
        config = collector.get_feature_config()

        assert config["kiro_state_keys"] == 0
        assert config["agent_extension"]["exists"] is False

    def test_empty_state_db(self, kiro_dir: Path) -> None:
        """State DB with ItemTable but no kiro keys returns 0."""
        db_path = self._make_state_db(kiro_dir)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("editor.theme", "dark"),
        )
        conn.commit()
        conn.close()

        collector = KiroCollector(kiro_dir=kiro_dir)
        config = collector.get_feature_config()

        assert config["kiro_state_keys"] == 0

    def test_conversation_keys_counted(self, kiro_dir: Path) -> None:
        """Keys matching 'conversation' or 'session' patterns are also counted."""
        db_path = self._make_state_db(kiro_dir)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("active.conversation.id", json.dumps("conv-123")),
        )
        conn.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("last.session.timestamp", json.dumps(1700000000000)),
        )
        conn.commit()
        conn.close()

        collector = KiroCollector(kiro_dir=kiro_dir)
        config = collector.get_feature_config()

        assert config["kiro_state_keys"] == 2
