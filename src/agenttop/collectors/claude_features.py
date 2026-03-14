"""Claude Code feature detection.

Pure functions that scan ~/.claude/ configuration directories to detect
which features the user has configured. Used by the optimizer for
ground-truth feature recommendations.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def detect_agents(claude_dir: Path) -> dict[str, Any]:
    """Detect custom agent definitions in agents/*.md."""
    agents_dir = claude_dir / "agents"
    if not agents_dir.is_dir():
        return {"count": 0, "names": [], "configured": False}
    agents = [f.stem for f in agents_dir.glob("*.md") if f.is_file()]
    return {"count": len(agents), "names": sorted(agents), "configured": len(agents) > 0}


def detect_commands(claude_dir: Path) -> dict[str, Any]:
    """Detect custom slash commands."""
    commands_dir = claude_dir / "commands"
    if not commands_dir.is_dir():
        return {"count": 0, "names": [], "configured": False}
    commands = [f.stem for f in commands_dir.rglob("*.md") if f.is_file()]
    return {"count": len(commands), "names": sorted(commands), "configured": len(commands) > 0}


def detect_rules(claude_dir: Path) -> dict[str, Any]:
    """Detect custom rules files (global and per-project)."""
    rules_dir = claude_dir / "rules"
    if not rules_dir.is_dir():
        return {"count": 0, "has_global": False, "has_project": False, "configured": False}

    all_rules = list(rules_dir.rglob("*.md"))
    # Check for common/ (global rules) vs project-specific dirs
    has_global = (rules_dir / "common").is_dir()
    has_project = any(
        d.is_dir() and d.name != "common"
        for d in rules_dir.iterdir()
        if d.is_dir()
    )
    return {
        "count": len(all_rules),
        "has_global": has_global,
        "has_project": has_project,
        "configured": len(all_rules) > 0,
    }


def detect_skills(claude_dir: Path) -> dict[str, Any]:
    """Detect installed skills."""
    skills_dir = claude_dir / "skills"
    if not skills_dir.is_dir():
        return {"count": 0, "names": [], "configured": False}
    # Skills can be .md files or directories with skill content
    skills = []
    for item in skills_dir.iterdir():
        if item.is_file() and item.suffix == ".md":
            skills.append(item.stem)
        elif item.is_dir():
            skills.append(item.name)
    return {"count": len(skills), "names": sorted(skills), "configured": len(skills) > 0}


def detect_plans(claude_dir: Path) -> dict[str, Any]:
    """Detect saved plan files (indicates planning activity)."""
    plans_dir = claude_dir / "plans"
    if not plans_dir.is_dir():
        return {"count": 0}
    plans = [f for f in plans_dir.glob("*.md") if f.is_file()]
    return {"count": len(plans)}


def detect_tasks(claude_dir: Path) -> dict[str, Any]:
    """Detect task directories (one per session that used tasks)."""
    tasks_dir = claude_dir / "tasks"
    if not tasks_dir.is_dir():
        return {"count": 0}
    task_dirs = [d for d in tasks_dir.iterdir() if d.is_dir()]
    return {"count": len(task_dirs)}


def detect_hooks(claude_dir: Path) -> dict[str, Any]:
    """Detect hooks configuration from settings.json."""
    settings_path = claude_dir / "settings.json"
    if not settings_path.is_file():
        return {"configured": False, "hook_count": 0}
    try:
        data = json.loads(settings_path.read_text())
        hooks = data.get("hooks", {})
        hook_count = sum(len(v) if isinstance(v, list) else 1 for v in hooks.values())
        return {"configured": hook_count > 0, "hook_count": hook_count}
    except (json.JSONDecodeError, OSError):
        return {"configured": False, "hook_count": 0}


def detect_project_memory(claude_dir: Path) -> dict[str, Any]:
    """Detect CLAUDE.md files across projects."""
    projects_dir = claude_dir / "projects"
    if not projects_dir.is_dir():
        return {"claude_md_count": 0, "memory_md_count": 0}
    claude_mds = list(projects_dir.rglob("CLAUDE.md"))
    memory_mds = list(projects_dir.rglob("MEMORY.md"))
    return {
        "claude_md_count": len(claude_mds),
        "memory_md_count": len(memory_mds),
    }


def detect_mcp_servers(claude_dir: Path) -> dict[str, Any]:
    """Detect MCP server configuration."""
    # Check both claude dir and home-level .claude.json
    mcp_path = claude_dir / "mcp.json"
    if not mcp_path.is_file():
        # Try .claude.json at home level (parent of .claude/)
        home_config = claude_dir.parent / ".claude.json"
        if home_config.is_file():
            try:
                data = json.loads(home_config.read_text())
                servers = data.get("mcpServers", {})
                return {
                    "configured": len(servers) > 0,
                    "server_count": len(servers),
                    "server_names": sorted(servers.keys()),
                }
            except (json.JSONDecodeError, OSError):
                pass
        return {"configured": False, "server_count": 0, "server_names": []}
    try:
        data = json.loads(mcp_path.read_text())
        servers = data.get("mcpServers", {})
        return {
            "configured": len(servers) > 0,
            "server_count": len(servers),
            "server_names": sorted(servers.keys()),
        }
    except (json.JSONDecodeError, OSError):
        return {"configured": False, "server_count": 0, "server_names": []}


def detect_all_features(claude_dir: Path) -> dict[str, Any]:
    """Detect all Claude Code features. Returns combined dict."""
    return {
        "agents": detect_agents(claude_dir),
        "commands": detect_commands(claude_dir),
        "rules": detect_rules(claude_dir),
        "skills": detect_skills(claude_dir),
        "plans": detect_plans(claude_dir),
        "tasks": detect_tasks(claude_dir),
        "hooks": detect_hooks(claude_dir),
        "project_memory": detect_project_memory(claude_dir),
        "mcp_servers": detect_mcp_servers(claude_dir),
    }
