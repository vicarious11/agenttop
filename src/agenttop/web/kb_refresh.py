# ruff: noqa: E501
"""Background knowledge base refresh — hardcoded-first, daily internet update.

The KNOWLEDGE_BASE in optimizer.py is always the source of truth.
This module AUGMENTS it with fresh data fetched from official GitHub repos
when internet is available. If no internet, hardcoded KB works perfectly.

Schedule: once on startup + every 24 hours (non-blocking background task).
Storage: ~/.agenttop/knowledge_base.json (cached updates with timestamp).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KB_CACHE_PATH = Path.home() / ".agenttop" / "knowledge_base.json"
REFRESH_INTERVAL = 86400  # 24 hours
_last_refresh: float = 0.0

# GitHub raw URLs for each tool's documentation
_SOURCES: dict[str, list[str]] = {
    "claude_code": [
        "https://raw.githubusercontent.com/anthropics/claude-code/main/README.md",
    ],
    "cursor": [
        "https://raw.githubusercontent.com/getcursor/cursor/main/README.md",
    ],
    "copilot": [
        "https://raw.githubusercontent.com/github/copilot-docs/main/README.md",
    ],
}


def _fetch(url: str, timeout: int = 10) -> str | None:
    """Fetch URL content. Returns None if offline or error."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "agenttop/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def _extract_features(content: str) -> list[dict[str, str]]:
    """Extract feature names + descriptions from README markdown.

    Looks for ### headings under feature-related ## sections.
    """
    features: list[dict[str, str]] = []
    lines = content.split("\n")
    in_feature_section = False
    keywords = {"feature", "usage", "getting started", "capabilities", "commands"}

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## "):
            in_feature_section = any(kw in stripped.lower() for kw in keywords)
        elif stripped.startswith("### ") and in_feature_section:
            name = stripped[4:].strip()
            desc_parts: list[str] = []
            for j in range(i + 1, min(i + 5, len(lines))):
                nxt = lines[j].strip()
                if nxt.startswith("#") or not nxt:
                    break
                desc_parts.append(nxt)
            if desc_parts:
                features.append({
                    "name": name,
                    "description": " ".join(desc_parts)[:300],
                    "source": "auto-refresh",
                })
    return features


def _fetch_all_updates() -> dict[str, list[dict[str, str]]]:
    """Fetch from all sources. Returns tool_id -> new features. Graceful on failure."""
    updates: dict[str, list[dict[str, str]]] = {}
    for tool_id, urls in _SOURCES.items():
        for url in urls:
            content = _fetch(url)
            if content:
                extracted = _extract_features(content)
                if extracted:
                    updates[tool_id] = extracted
                    logger.info("Fetched %d features for %s", len(extracted), tool_id)
    return updates


def _load_cache() -> dict[str, Any] | None:
    """Load cached KB updates. Returns None if stale or missing."""
    if not KB_CACHE_PATH.exists():
        return None
    try:
        data = json.loads(KB_CACHE_PATH.read_text())
        if (time.time() - data.get("timestamp", 0)) > REFRESH_INTERVAL:
            return None
        return data.get("updates")
    except (json.JSONDecodeError, OSError):
        return None


def _save_cache(updates: dict[str, Any]) -> None:
    """Save KB updates to ~/.agenttop/knowledge_base.json."""
    try:
        KB_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        KB_CACHE_PATH.write_text(json.dumps({
            "timestamp": time.time(),
            "updates": updates,
        }, indent=2, default=str))
    except OSError as exc:
        logger.warning("Failed to save KB cache: %s", exc)


def merge_updates(
    knowledge_base: dict[str, Any],
    updates: dict[str, list[dict[str, str]]],
) -> dict[str, Any]:
    """Merge fetched features into KNOWLEDGE_BASE. Only ADDS new features.

    Returns a new dict (immutable). Never removes hardcoded features.
    """
    merged = {}
    for tool_id, tool_data in knowledge_base.items():
        new_tool = {**tool_data}
        if tool_id in updates:
            existing = {f["name"] for f in new_tool.get("features", [])}
            new_features = [f for f in updates[tool_id] if f["name"] not in existing]
            if new_features:
                new_tool["features"] = [*new_tool.get("features", []), *new_features]
                logger.info("Added %d features to %s", len(new_features), tool_id)
        merged[tool_id] = new_tool
    return merged


async def refresh_kb(knowledge_base: dict[str, Any]) -> dict[str, Any]:
    """Refresh KB: try cache first, then internet. Returns updated KB.

    Non-blocking (runs fetch in executor). If everything fails,
    returns the original hardcoded KB unchanged.
    """
    global _last_refresh

    # Try cache
    cached = _load_cache()
    if cached:
        _last_refresh = time.time()
        return merge_updates(knowledge_base, cached)

    # Try internet (in executor so we don't block)
    loop = asyncio.get_event_loop()
    try:
        updates = await loop.run_in_executor(None, _fetch_all_updates)
    except Exception:
        updates = {}

    if updates:
        _save_cache(updates)
        _last_refresh = time.time()
        return merge_updates(knowledge_base, updates)

    # No internet, no cache — hardcoded KB is fine
    logger.info("KB refresh: offline, using hardcoded knowledge base")
    _last_refresh = time.time()
    return knowledge_base


def needs_refresh() -> bool:
    """Check if KB refresh is due (every 24h)."""
    return (time.time() - _last_refresh) > REFRESH_INTERVAL
