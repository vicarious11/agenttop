"""Session analysis cache with schema versioning.

Sessions are immutable — once analyzed by the LLM, cached forever.
Cache is persisted to ~/.agenttop/session_cache.json with a version
field so format changes can be detected and migrated.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_SESSION_CACHE_PATH = Path.home() / ".agenttop" / "session_cache.json"

# Bump this when the cache schema changes. Old caches with a different
# version are discarded gracefully (sessions will be re-analyzed).
_CACHE_VERSION = 1


def _load_session_cache() -> dict[str, dict[str, Any]]:
    """Load cached per-session LLM analyses from disk.

    Returns an empty dict if the file is missing, corrupt, or has an
    incompatible schema version.
    """
    if not _SESSION_CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(_SESSION_CACHE_PATH.read_text())
        if not isinstance(data, dict):
            return {}
        version = data.get("_version")
        if version != _CACHE_VERSION:
            logging.info(
                "Session cache version mismatch (got %s, want %d) — discarding",
                version,
                _CACHE_VERSION,
            )
            return {}
        # Return sessions only (exclude meta keys)
        return {
            k: v for k, v in data.items()
            if not k.startswith("_") and isinstance(v, dict)
        }
    except (json.JSONDecodeError, OSError) as e:
        logging.debug("Failed to load session cache: %s", e)
    return {}


def _save_session_cache(cache: dict[str, dict[str, Any]]) -> None:
    """Persist session cache to disk with version metadata."""
    try:
        _SESSION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        envelope = {"_version": _CACHE_VERSION, **cache}
        _SESSION_CACHE_PATH.write_text(
            json.dumps(envelope, default=str),
        )
    except OSError as e:
        logging.warning("Failed to save session cache: %s", e)
