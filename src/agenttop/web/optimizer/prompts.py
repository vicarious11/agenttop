# ruff: noqa: E501
"""LLM prompt templates for the optimizer's Map-Reduce-Generate pipeline."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Per-session analysis (individual fallback)
# ---------------------------------------------------------------------------

SESSION_ANALYSIS_PROMPT = """\
Analyze this AI coding session. You see ALL the user's prompts in order.

Session metadata:
- Tool: {tool}
- Project: {project}
- Messages: {message_count}
- Tokens: {total_tokens}

User prompts (in order):
{prompts}

Answer these questions about this session as JSON:
{{
  "intent": "<debugging|greenfield|refactoring|exploration|devops|documentation|code_review|other>",
  "had_spiral": <true|false>,
  "spiral_detail": "<if spiral: 1 sentence what went wrong. if no spiral: empty string>",
  "prompt_quality": "<1 sentence: was the first prompt clear enough? what was missing?>",
  "outcome": "<resolved|abandoned|pivoted>",
  "wasted_effort": "<1 sentence: what caused unnecessary back-and-forth, or empty string if efficient>",
  "actionable_fix": "<1 sentence: what would have saved time in this session>"
}}

Rules:
- "had_spiral" means user repeatedly corrected, redirected, or fought the AI (3+ times)
- "wasted_effort" should be empty string if the session was efficient
- Return ONLY the JSON object, no markdown fences, no explanation
"""

# ---------------------------------------------------------------------------
# Batched MAP: analyze multiple sessions in a single LLM call
# ---------------------------------------------------------------------------

_MAX_PROMPTS_HEAD = 5         # first N prompts kept per session
_MAX_PROMPTS_TAIL = 2         # last N prompts kept per session
_MAX_PROMPT_CHARS = 200       # truncate each prompt to this length

SESSION_BATCH_ANALYSIS_PROMPT = """\
Analyze these {count} AI coding sessions. For each, classify intent and quality.

{sessions_block}

Return a JSON array with one object per session (SAME ORDER as above):
[
  {{
    "session_id": "<exact session ID from above>",
    "intent": "<debugging|greenfield|refactoring|exploration|devops|documentation|code_review|other>",
    "had_spiral": <true|false>,
    "spiral_detail": "<if spiral: 1 sentence. if no spiral: empty string>",
    "prompt_quality": "<1 sentence>",
    "outcome": "<resolved|abandoned|pivoted>",
    "wasted_effort": "<empty string if efficient, else 1 sentence>",
    "actionable_fix": "<1 sentence: what would have saved time>"
  }}
]

Rules:
- "had_spiral" = user corrected/redirected the AI 3+ times
- Return ONLY the JSON array, no markdown, no explanation
"""

# ---------------------------------------------------------------------------
# Synthesis (GENERATE phase)
# ---------------------------------------------------------------------------

SYNTHESIS_PROMPT = """\
You are an AI coding workflow consultant. Based on the analysis below, \
write actionable recommendations.

## Pre-computed Analysis (do NOT recompute — these are exact)

Score: {score}/100
Grades: {grades}
Anti-patterns found: {anti_patterns_summary}
Cost forensics: {cost_summary}
Session patterns: {session_patterns}
Features configured: {features}

## Real Projects (ONLY use these exact names in project_insights)
{real_projects}

## Per-Session Observations (from detailed analysis)
{session_observations}

## Tool Knowledge
{tool_knowledge}

## Generate (JSON):
Return ONLY valid JSON with this exact structure:
{{
  "developer_profile": {{
    "title": "<short identity, e.g. 'Full-Stack AI Power User'>",
    "bio": "<2-3 sentence profile based on the data>",
    "traits": ["<trait1>", "<trait2>", "<trait3>"],
    "ai_personality": "<one of: power_user, methodical_builder, debug_warrior, explorer, cautious_adopter, efficiency_optimizer>"
  }},
  "recommendations": [
    {{"title": "<actionable title>", "description": "<specific advice referencing their data>", "priority": "<high/medium/low>", "savings": "<estimated impact>", "source": "<reference>"}}
  ],
  "missing_features": [
    {{"tool": "<tool name>", "feature": "<feature name>", "evidence": "<data evidence>", "benefit": "<what they'd gain>"}}
  ],
  "project_insights": [
    {{"project": "<name>", "type": "<greenfield/maintenance/debugging/refactoring/exploration>", "insight": "<observation>", "recommendation": "<advice>", "underutilized": "<features>", "recommended_model": {{"model": "<name>", "reason": "<why>"}}, "recommended_tool": {{"tool": "<IDE/tool name>", "reason": "<why this tool fits this project type>"}}}}
  ],
  "workflow": {{
    "current": "<2-3 sentence current workflow assessment>",
    "future": "<2-3 sentence optimized workflow vision>"
  }}
}}

Rules:
- Score and grades are PRE-COMPUTED facts — do NOT invent different numbers
- Reference REAL numbers from the data (tokens, costs, session counts)
- 3-7 recommendations, ranked by impact
- Be specific and actionable, not generic
- Return ONLY the JSON object, no markdown fences, no explanation
- project_insights MUST use ONLY the exact project names from "Real Projects" above — NEVER invent or rename projects
- ONLY recommend models that actually exist for the tool being used:
  Claude Code: claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5
  Cursor: gpt-4o, claude-sonnet-4-6, claude-haiku-4-5, gemini-2.5-pro
  Copilot: gpt-4o, claude-sonnet-4-6, o3-mini
  Codex: codex-mini, o4-mini, o3
  Kiro: claude-sonnet-4-6
"""
