"""Tests for the Claude Code feature detection module.

Covers: detect_agents, detect_commands, detect_rules, detect_skills,
detect_plans, detect_tasks, detect_hooks, detect_project_memory,
detect_mcp_servers, detect_all_features.
"""

import json
import tempfile
from pathlib import Path

import pytest

from agenttop.collectors.claude_features import (
    detect_agents,
    detect_all_features,
    detect_commands,
    detect_hooks,
    detect_mcp_servers,
    detect_plans,
    detect_project_memory,
    detect_rules,
    detect_skills,
    detect_tasks,
)


@pytest.fixture()
def claude_dir():
    """Create a temporary directory simulating ~/.claude/.

    Uses a nested structure (home/.claude/) so that fallback logic
    in detect_mcp_servers can write to the parent without leaking
    between tests.
    """
    with tempfile.TemporaryDirectory() as tmp:
        claude = Path(tmp) / ".claude"
        claude.mkdir()
        yield claude


# ── detect_agents ────────────────────────────────────────────


class TestDetectAgents:
    def test_missing_directory(self, claude_dir: Path):
        result = detect_agents(claude_dir)
        assert result == {"count": 0, "names": [], "configured": False}

    def test_empty_directory(self, claude_dir: Path):
        (claude_dir / "agents").mkdir()
        result = detect_agents(claude_dir)
        assert result == {"count": 0, "names": [], "configured": False}

    def test_with_agent_files(self, claude_dir: Path):
        agents_dir = claude_dir / "agents"
        agents_dir.mkdir()
        (agents_dir / "planner.md").write_text("# Planner")
        (agents_dir / "reviewer.md").write_text("# Reviewer")
        # Non-md file should be ignored
        (agents_dir / "notes.txt").write_text("not an agent")

        result = detect_agents(claude_dir)
        assert result["count"] == 2
        assert result["names"] == ["planner", "reviewer"]
        assert result["configured"] is True


# ── detect_commands ──────────────────────────────────────────


class TestDetectCommands:
    def test_missing_directory(self, claude_dir: Path):
        result = detect_commands(claude_dir)
        assert result == {"count": 0, "names": [], "configured": False}

    def test_empty_directory(self, claude_dir: Path):
        (claude_dir / "commands").mkdir()
        result = detect_commands(claude_dir)
        assert result == {"count": 0, "names": [], "configured": False}

    def test_with_command_files(self, claude_dir: Path):
        commands_dir = claude_dir / "commands"
        commands_dir.mkdir()
        (commands_dir / "deploy.md").write_text("# Deploy")
        (commands_dir / "test.md").write_text("# Test")

        result = detect_commands(claude_dir)
        assert result["count"] == 2
        assert result["names"] == ["deploy", "test"]
        assert result["configured"] is True

    def test_nested_commands(self, claude_dir: Path):
        """Commands uses rglob, so nested .md files should be found."""
        commands_dir = claude_dir / "commands"
        sub_dir = commands_dir / "sub"
        sub_dir.mkdir(parents=True)
        (commands_dir / "top.md").write_text("# Top")
        (sub_dir / "nested.md").write_text("# Nested")

        result = detect_commands(claude_dir)
        assert result["count"] == 2
        assert sorted(result["names"]) == ["nested", "top"]


# ── detect_rules ─────────────────────────────────────────────


class TestDetectRules:
    def test_missing_directory(self, claude_dir: Path):
        result = detect_rules(claude_dir)
        assert result == {
            "count": 0,
            "has_global": False,
            "has_project": False,
            "configured": False,
        }

    def test_empty_directory(self, claude_dir: Path):
        (claude_dir / "rules").mkdir()
        result = detect_rules(claude_dir)
        assert result["count"] == 0
        assert result["has_global"] is False
        assert result["has_project"] is False
        assert result["configured"] is False

    def test_with_global_rules(self, claude_dir: Path):
        common_dir = claude_dir / "rules" / "common"
        common_dir.mkdir(parents=True)
        (common_dir / "style.md").write_text("# Style")

        result = detect_rules(claude_dir)
        assert result["count"] == 1
        assert result["has_global"] is True
        assert result["has_project"] is False
        assert result["configured"] is True

    def test_with_project_rules(self, claude_dir: Path):
        project_dir = claude_dir / "rules" / "myproject"
        project_dir.mkdir(parents=True)
        (project_dir / "lint.md").write_text("# Lint")

        result = detect_rules(claude_dir)
        assert result["count"] == 1
        assert result["has_global"] is False
        assert result["has_project"] is True
        assert result["configured"] is True

    def test_with_both_global_and_project_rules(self, claude_dir: Path):
        common_dir = claude_dir / "rules" / "common"
        project_dir = claude_dir / "rules" / "myproject"
        common_dir.mkdir(parents=True)
        project_dir.mkdir(parents=True)
        (common_dir / "style.md").write_text("# Style")
        (project_dir / "lint.md").write_text("# Lint")

        result = detect_rules(claude_dir)
        assert result["count"] == 2
        assert result["has_global"] is True
        assert result["has_project"] is True


# ── detect_skills ────────────────────────────────────────────


class TestDetectSkills:
    def test_missing_directory(self, claude_dir: Path):
        result = detect_skills(claude_dir)
        assert result == {"count": 0, "names": [], "configured": False}

    def test_empty_directory(self, claude_dir: Path):
        (claude_dir / "skills").mkdir()
        result = detect_skills(claude_dir)
        assert result == {"count": 0, "names": [], "configured": False}

    def test_with_md_skills(self, claude_dir: Path):
        skills_dir = claude_dir / "skills"
        skills_dir.mkdir()
        (skills_dir / "deploy.md").write_text("# Deploy skill")

        result = detect_skills(claude_dir)
        assert result["count"] == 1
        assert result["names"] == ["deploy"]
        assert result["configured"] is True

    def test_with_directory_skills(self, claude_dir: Path):
        skills_dir = claude_dir / "skills"
        skills_dir.mkdir()
        (skills_dir / "complex-skill").mkdir()

        result = detect_skills(claude_dir)
        assert result["count"] == 1
        assert result["names"] == ["complex-skill"]
        assert result["configured"] is True

    def test_mixed_skills(self, claude_dir: Path):
        skills_dir = claude_dir / "skills"
        skills_dir.mkdir()
        (skills_dir / "alpha.md").write_text("# Alpha")
        (skills_dir / "beta").mkdir()

        result = detect_skills(claude_dir)
        assert result["count"] == 2
        assert result["names"] == ["alpha", "beta"]


# ── detect_plans ─────────────────────────────────────────────


class TestDetectPlans:
    def test_missing_directory(self, claude_dir: Path):
        result = detect_plans(claude_dir)
        assert result == {"count": 0}

    def test_empty_directory(self, claude_dir: Path):
        (claude_dir / "plans").mkdir()
        result = detect_plans(claude_dir)
        assert result == {"count": 0}

    def test_with_plan_files(self, claude_dir: Path):
        plans_dir = claude_dir / "plans"
        plans_dir.mkdir()
        (plans_dir / "plan-001.md").write_text("# Plan 1")
        (plans_dir / "plan-002.md").write_text("# Plan 2")
        # Non-md file should be ignored
        (plans_dir / "draft.txt").write_text("not a plan")

        result = detect_plans(claude_dir)
        assert result["count"] == 2


# ── detect_tasks ─────────────────────────────────────────────


class TestDetectTasks:
    def test_missing_directory(self, claude_dir: Path):
        result = detect_tasks(claude_dir)
        assert result == {"count": 0}

    def test_empty_directory(self, claude_dir: Path):
        (claude_dir / "tasks").mkdir()
        result = detect_tasks(claude_dir)
        assert result == {"count": 0}

    def test_with_task_directories(self, claude_dir: Path):
        tasks_dir = claude_dir / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "session-abc123").mkdir()
        (tasks_dir / "session-def456").mkdir()
        # Regular file should be ignored (only dirs count)
        (tasks_dir / "stray-file.txt").write_text("not a task")

        result = detect_tasks(claude_dir)
        assert result["count"] == 2


# ── detect_hooks ─────────────────────────────────────────────


class TestDetectHooks:
    def test_missing_settings_file(self, claude_dir: Path):
        result = detect_hooks(claude_dir)
        assert result == {"configured": False, "hook_count": 0}

    def test_settings_with_no_hooks(self, claude_dir: Path):
        (claude_dir / "settings.json").write_text(json.dumps({"theme": "dark"}))
        result = detect_hooks(claude_dir)
        assert result == {"configured": False, "hook_count": 0}

    def test_settings_with_empty_hooks(self, claude_dir: Path):
        (claude_dir / "settings.json").write_text(json.dumps({"hooks": {}}))
        result = detect_hooks(claude_dir)
        assert result == {"configured": False, "hook_count": 0}

    def test_settings_with_hooks_list(self, claude_dir: Path):
        settings = {
            "hooks": {
                "PreToolUse": [
                    {"command": "lint"},
                    {"command": "format"},
                ],
                "PostToolUse": [
                    {"command": "check"},
                ],
            }
        }
        (claude_dir / "settings.json").write_text(json.dumps(settings))
        result = detect_hooks(claude_dir)
        assert result["configured"] is True
        assert result["hook_count"] == 3

    def test_settings_with_hooks_non_list_value(self, claude_dir: Path):
        settings = {
            "hooks": {
                "Stop": "cleanup",
            }
        }
        (claude_dir / "settings.json").write_text(json.dumps(settings))
        result = detect_hooks(claude_dir)
        assert result["configured"] is True
        assert result["hook_count"] == 1

    def test_invalid_json(self, claude_dir: Path):
        (claude_dir / "settings.json").write_text("{broken json")
        result = detect_hooks(claude_dir)
        assert result == {"configured": False, "hook_count": 0}


# ── detect_project_memory ────────────────────────────────────


class TestDetectProjectMemory:
    def test_missing_projects_directory(self, claude_dir: Path):
        result = detect_project_memory(claude_dir)
        assert result == {"claude_md_count": 0, "memory_md_count": 0}

    def test_empty_projects_directory(self, claude_dir: Path):
        (claude_dir / "projects").mkdir()
        result = detect_project_memory(claude_dir)
        assert result == {"claude_md_count": 0, "memory_md_count": 0}

    def test_with_claude_md_files(self, claude_dir: Path):
        proj = claude_dir / "projects" / "myapp"
        proj.mkdir(parents=True)
        (proj / "CLAUDE.md").write_text("# Project memory")

        result = detect_project_memory(claude_dir)
        assert result["claude_md_count"] == 1
        assert result["memory_md_count"] == 0

    def test_with_memory_md_files(self, claude_dir: Path):
        proj = claude_dir / "projects" / "myapp"
        proj.mkdir(parents=True)
        (proj / "MEMORY.md").write_text("# Memory")

        result = detect_project_memory(claude_dir)
        assert result["claude_md_count"] == 0
        assert result["memory_md_count"] == 1

    def test_with_both_file_types(self, claude_dir: Path):
        proj_a = claude_dir / "projects" / "app-a"
        proj_b = claude_dir / "projects" / "app-b"
        proj_a.mkdir(parents=True)
        proj_b.mkdir(parents=True)
        (proj_a / "CLAUDE.md").write_text("# A")
        (proj_b / "CLAUDE.md").write_text("# B")
        (proj_b / "MEMORY.md").write_text("# Memory B")

        result = detect_project_memory(claude_dir)
        assert result["claude_md_count"] == 2
        assert result["memory_md_count"] == 1


# ── detect_mcp_servers ───────────────────────────────────────


class TestDetectMcpServers:
    def test_no_config_files(self, claude_dir: Path):
        result = detect_mcp_servers(claude_dir)
        assert result == {"configured": False, "server_count": 0, "server_names": []}

    def test_mcp_json_with_servers(self, claude_dir: Path):
        mcp_config = {
            "mcpServers": {
                "github": {"command": "gh-mcp"},
                "slack": {"command": "slack-mcp"},
            }
        }
        (claude_dir / "mcp.json").write_text(json.dumps(mcp_config))

        result = detect_mcp_servers(claude_dir)
        assert result["configured"] is True
        assert result["server_count"] == 2
        assert result["server_names"] == ["github", "slack"]

    def test_mcp_json_empty_servers(self, claude_dir: Path):
        (claude_dir / "mcp.json").write_text(json.dumps({"mcpServers": {}}))

        result = detect_mcp_servers(claude_dir)
        assert result["configured"] is False
        assert result["server_count"] == 0

    def test_mcp_json_invalid_json(self, claude_dir: Path):
        (claude_dir / "mcp.json").write_text("not valid json{{{")

        result = detect_mcp_servers(claude_dir)
        assert result == {"configured": False, "server_count": 0, "server_names": []}

    def test_fallback_to_claude_json(self, claude_dir: Path):
        """When mcp.json is absent, fall back to ../.claude.json."""
        home_config = {
            "mcpServers": {
                "filesystem": {"command": "fs-mcp"},
            }
        }
        # .claude.json lives at the parent of the claude_dir
        (claude_dir.parent / ".claude.json").write_text(json.dumps(home_config))

        result = detect_mcp_servers(claude_dir)
        assert result["configured"] is True
        assert result["server_count"] == 1
        assert result["server_names"] == ["filesystem"]

    def test_fallback_invalid_json(self, claude_dir: Path):
        (claude_dir.parent / ".claude.json").write_text("bad json")

        result = detect_mcp_servers(claude_dir)
        assert result == {"configured": False, "server_count": 0, "server_names": []}

    def test_mcp_json_takes_precedence_over_fallback(self, claude_dir: Path):
        """When mcp.json exists, .claude.json is not consulted."""
        (claude_dir / "mcp.json").write_text(
            json.dumps({"mcpServers": {"primary": {}}})
        )
        (claude_dir.parent / ".claude.json").write_text(
            json.dumps({"mcpServers": {"fallback": {}}})
        )

        result = detect_mcp_servers(claude_dir)
        assert result["server_names"] == ["primary"]


# ── detect_all_features ──────────────────────────────────────


class TestDetectAllFeatures:
    def test_empty_claude_dir(self, claude_dir: Path):
        """All sub-detectors return zero/empty state for a bare directory."""
        result = detect_all_features(claude_dir)

        assert set(result.keys()) == {
            "agents",
            "commands",
            "rules",
            "skills",
            "plans",
            "tasks",
            "hooks",
            "project_memory",
            "mcp_servers",
        }
        assert result["agents"]["count"] == 0
        assert result["commands"]["count"] == 0
        assert result["rules"]["count"] == 0
        assert result["skills"]["count"] == 0
        assert result["plans"]["count"] == 0
        assert result["tasks"]["count"] == 0
        assert result["hooks"]["configured"] is False
        assert result["project_memory"]["claude_md_count"] == 0
        assert result["mcp_servers"]["configured"] is False

    def test_populated_claude_dir(self, claude_dir: Path):
        """Integration: populate several features and verify combined output."""
        # Agents
        (claude_dir / "agents").mkdir()
        (claude_dir / "agents" / "coder.md").write_text("# Coder")

        # Commands (nested)
        cmd_dir = claude_dir / "commands" / "ops"
        cmd_dir.mkdir(parents=True)
        (cmd_dir / "deploy.md").write_text("# Deploy")

        # Plans
        (claude_dir / "plans").mkdir()
        (claude_dir / "plans" / "plan-1.md").write_text("# Plan")

        # Hooks
        (claude_dir / "settings.json").write_text(
            json.dumps({"hooks": {"PreToolUse": [{"command": "lint"}]}})
        )

        # MCP
        (claude_dir / "mcp.json").write_text(
            json.dumps({"mcpServers": {"github": {}}})
        )

        result = detect_all_features(claude_dir)

        assert result["agents"]["count"] == 1
        assert result["agents"]["names"] == ["coder"]
        assert result["commands"]["count"] == 1
        assert result["plans"]["count"] == 1
        assert result["hooks"]["configured"] is True
        assert result["hooks"]["hook_count"] == 1
        assert result["mcp_servers"]["server_names"] == ["github"]
