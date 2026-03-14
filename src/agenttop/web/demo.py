# ruff: noqa: E501
"""Demo mode — anonymizes sensitive data for video recording / screenshots.

Activate via:
  - CLI: agenttop web --demo
  - Env: AGENTTOP_DEMO=1
  - URL: http://localhost:8420?demo=true (frontend sends to API)

Uses deterministic hashing so the same real name always maps to the same
fake name within a session, keeping relationships visible.
"""

from __future__ import annotations

import hashlib
from typing import Any

# Fake project names — tech-sounding but obviously fictional
_FAKE_PROJECTS = [
    "quantum-engine", "nebula-api", "horizon-ui", "atlas-core",
    "phoenix-ml", "vortex-cli", "prism-sdk", "titan-infra",
    "aurora-web", "nexus-data", "orbit-sync", "cipher-auth",
    "pulse-stream", "helix-ops", "zenith-app", "forge-tools",
    "spark-compute", "drift-proxy", "echo-search", "lumen-dash",
]

_FAKE_PROMPTS = [
    "refactor the authentication module to use JWT tokens",
    "add pagination to the API endpoints",
    "fix the race condition in the cache layer",
    "implement real-time notifications with WebSocket",
    "write unit tests for the payment service",
    "optimize database queries for the dashboard",
    "add dark mode toggle to the settings page",
    "migrate from REST to GraphQL for the mobile API",
    "set up CI/CD pipeline with GitHub Actions",
    "implement rate limiting middleware",
    "add OpenTelemetry tracing to all services",
    "refactor the monolith into microservices",
    "create a CLI tool for database migrations",
    "implement RBAC for the admin panel",
    "add SSR support for the landing page",
]

# Cache: real name → fake name (consistent within process lifetime)
_project_map: dict[str, str] = {}


def _fake_project(real_name: str) -> str:
    """Map a real project name to a consistent fake name."""
    if not real_name or real_name in ("unknown", "other", ""):
        return real_name
    if real_name not in _project_map:
        h = int(hashlib.sha256(real_name.encode()).hexdigest(), 16)
        idx = h % len(_FAKE_PROJECTS)
        # Handle collisions by incrementing
        candidate = _FAKE_PROJECTS[idx]
        used = set(_project_map.values())
        while candidate in used:
            idx = (idx + 1) % len(_FAKE_PROJECTS)
            candidate = _FAKE_PROJECTS[idx]
        _project_map[real_name] = candidate
    return _project_map[real_name]


def _fake_prompt(real_prompt: str) -> str:
    """Replace a real prompt with a fake one."""
    if not real_prompt:
        return real_prompt
    h = int(hashlib.sha256(real_prompt.encode()).hexdigest(), 16)
    return _FAKE_PROMPTS[h % len(_FAKE_PROMPTS)]


def _sanitize_string(value: str) -> str:
    """Sanitize a string that might contain project names or paths."""
    result = value
    for real, fake in _project_map.items():
        result = result.replace(real, fake)
    return result


def sanitize_response(data: Any) -> Any:
    """Recursively sanitize API response data for demo mode.

    Replaces project names, prompts, file paths, and session IDs
    while keeping numeric metrics (tokens, costs, counts) intact.
    """
    if isinstance(data, dict):
        return _sanitize_dict(data)
    if isinstance(data, list):
        return [sanitize_response(item) for item in data]
    if isinstance(data, str):
        return _sanitize_string(data)
    return data


def _sanitize_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a dictionary, applying field-specific rules."""
    result: dict[str, Any] = {}
    for key, value in d.items():
        if key in ("project", "project_name", "name") and isinstance(value, str):
            result[key] = _fake_project(value)
        elif key in ("prompts", "sample_prompts") and isinstance(value, list):
            result[key] = [_fake_prompt(p) if isinstance(p, str) else p for p in value]
        elif key in ("prompt", "command", "bio", "insight", "recommendation", "detail") and isinstance(value, str):
            result[key] = _sanitize_string(value)
        elif key == "project_details" and isinstance(value, dict):
            result[key] = {
                _fake_project(proj): sanitize_response(details)
                for proj, details in value.items()
            }
        elif key == "top_projects" and isinstance(value, dict):
            result[key] = {
                _fake_project(proj): count
                for proj, count in value.items()
            }
        elif key == "project_insights" and isinstance(value, list):
            result[key] = [sanitize_response(pi) for pi in value]
        elif key == "session_details" and isinstance(value, list):
            result[key] = [sanitize_response(sd) for sd in value]
        elif key in ("id", "session_id") and isinstance(value, str):
            # Hash session IDs
            h = hashlib.sha256(value.encode()).hexdigest()[:12]
            result[key] = f"demo-{h}"
        elif key == "cost_forensics" and isinstance(value, dict):
            result[key] = _sanitize_cost_forensics(value)
        else:
            result[key] = sanitize_response(value)
    return result


def _sanitize_cost_forensics(cf: dict[str, Any]) -> dict[str, Any]:
    """Sanitize cost forensics which has project names as keys."""
    result: dict[str, Any] = {}
    for key, value in cf.items():
        if key in ("by_project", "waste_by_project") and isinstance(value, dict):
            result[key] = {
                _fake_project(proj): v for proj, v in value.items()
            }
        else:
            result[key] = sanitize_response(value)
    return result
