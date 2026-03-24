"""JSON extraction and validation for LLM responses."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

# Valid values for session analysis fields
_VALID_INTENTS = frozenset({
    "debugging", "greenfield", "refactoring", "exploration",
    "devops", "documentation", "code_review", "other",
})
_VALID_OUTCOMES = frozenset({"resolved", "abandoned", "pivoted"})

# Required fields in a session analysis object
_SESSION_ANALYSIS_FIELDS = {
    "intent": str,
    "had_spiral": bool,
    "spiral_detail": str,
    "prompt_quality": str,
    "outcome": str,
    "wasted_effort": str,
    "actionable_fix": str,
}


def extract_json_object(raw: str) -> dict[str, Any]:
    """Extract a JSON object from potentially noisy LLM output.

    Handles markdown fences, thinking tags, and extra text around JSON.
    Raises json.JSONDecodeError if no valid JSON object is found.
    """
    cleaned = _strip_llm_wrapping(raw)

    # Try direct parse first
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Fallback: find the outermost { ... } in the response
    brace_start = cleaned.find("{")
    brace_end = cleaned.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        result = json.loads(cleaned[brace_start : brace_end + 1])
        if isinstance(result, dict):
            return result

    raise json.JSONDecodeError("No JSON object found", cleaned, 0)


def extract_json_array(raw: str) -> list[dict[str, Any]]:
    """Extract a JSON array from LLM output.

    Raises json.JSONDecodeError if no valid JSON array is found.
    """
    cleaned = _strip_llm_wrapping(raw)

    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Fallback: find [ ... ]
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end > start:
        result = json.loads(cleaned[start : end + 1])
        if isinstance(result, list):
            return result

    raise json.JSONDecodeError("No JSON array found", cleaned, 0)


def validate_session_analysis(item: Any) -> dict[str, Any] | None:
    """Validate and normalize a single session analysis object.

    Returns a cleaned dict with correct types, or None if the item
    is not a valid session analysis.
    """
    if not isinstance(item, dict):
        logging.debug("Session analysis item is not a dict: %s", type(item))
        return None

    result: dict[str, Any] = {}
    for field, expected_type in _SESSION_ANALYSIS_FIELDS.items():
        value = item.get(field)
        if expected_type is bool:
            result[field] = bool(value) if value is not None else False
        elif expected_type is str:
            result[field] = str(value) if value is not None else ""
        else:
            result[field] = value

    # Clamp to valid enum values
    if result["intent"] not in _VALID_INTENTS:
        logging.debug("Unknown intent %r, defaulting to 'other'", result["intent"])
        result["intent"] = "other"
    if result["outcome"] not in _VALID_OUTCOMES:
        logging.debug("Unknown outcome %r, defaulting to 'resolved'", result["outcome"])
        result["outcome"] = "resolved"

    return result


def _strip_llm_wrapping(raw: str) -> str:
    """Remove thinking tags, markdown fences, and whitespace from LLM output."""
    cleaned = raw.strip()
    cleaned = re.sub(
        r"<think>.*?</think>", "", cleaned, flags=re.DOTALL,
    ).strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    return cleaned.strip()
