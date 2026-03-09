"""Intent classification using LLM or local heuristics."""

from __future__ import annotations

from agenttop.analysis.engine import get_completion
from agenttop.config import LLMConfig
from agenttop.models import IntentCategory, SessionIntent

INTENT_PROMPT = """Classify the following AI coding assistant prompt into exactly one category.

Categories:
- debugging: fixing bugs, errors, crashes
- refactoring: cleaning up, restructuring, renaming code
- greenfield: creating new features, implementing from scratch
- exploration: understanding code, asking questions, searching
- code_review: reviewing, auditing, evaluating code quality
- devops: deployment, CI/CD, infrastructure, Docker, K8s
- documentation: writing docs, READMEs, comments

Prompt: "{prompt}"

Respond with ONLY the category name (one word, lowercase)."""


def classify_with_llm(prompt: str, config: LLMConfig) -> IntentCategory:
    """Classify a prompt's intent using the configured LLM."""
    result = get_completion(
        INTENT_PROMPT.format(prompt=prompt[:500]),
        config,
        system="You classify developer prompts into categories. Respond with a single word.",
        max_tokens=20,
    )
    result = result.strip().lower()
    try:
        return IntentCategory(result)
    except ValueError:
        return IntentCategory.UNKNOWN


def classify_batch(
    prompts: list[str],
    config: LLMConfig,
    use_llm: bool = True,
) -> list[SessionIntent]:
    """Classify a batch of prompts."""
    from agenttop.tui.analysis import classify_intent_local

    results = []
    for i, prompt in enumerate(prompts):
        from agenttop.analysis.engine import is_llm_configured

        if use_llm and is_llm_configured(config):
            intent = classify_with_llm(prompt, config)
        else:
            intent = classify_intent_local(prompt)

        results.append(
            SessionIntent(
                session_id=str(i),
                intent=intent,
                summary=prompt[:100],
            )
        )
    return results
