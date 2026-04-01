# ruff: noqa: E501
"""AI Usage Optimizer — LLM-powered workflow recommendations.

Architecture:
  1. Python computes deterministic metrics (anti-patterns, cost forensics,
     prompt analysis, context engineering, session details)
  2. These go BOTH to the LLM (as structured JSON) AND directly into the response
  3. LLM adds intelligence: grades, recommendations, developer_profile,
     project_insights, workflow, missing_features
  4. Final response merges Python metrics + LLM analysis

Module layout:
  - knowledge_base.py — per-tool best practices
  - cache.py — session analysis cache with versioning
  - prompts.py — LLM prompt templates
  - analyzer.py — deterministic scoring, anti-patterns, cost forensics
  - profile.py — user profile builder
  - llm_parser.py — JSON extraction + validation
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from agenttop.analysis.engine import get_completion
from agenttop.config import Config
from agenttop.models import Session

from agenttop.web.optimizer.analyzer import (
    analyze_anti_patterns,
    build_cost_forensics,
    compute_deterministic_score,
    compute_strengths,
)
from agenttop.web.optimizer.cache import (
    _load_session_cache,
    _save_session_cache,
)
from agenttop.web.optimizer.knowledge_base import KNOWLEDGE_BASE, UNIVERSAL_PRACTICES
from agenttop.web.optimizer.llm_parser import (
    extract_json_array,
    extract_json_object,
    validate_session_analysis,
)
from agenttop.web.optimizer.profile import build_tool_knowledge, build_user_profile
from agenttop.web.optimizer.prompts import (
    SESSION_ANALYSIS_PROMPT,
    SESSION_BATCH_ANALYSIS_PROMPT,
    SYNTHESIS_PROMPT,
    _MAX_PROMPT_CHARS,
    _MAX_PROMPTS_HEAD,
    _MAX_PROMPTS_TAIL,
)

# Re-export for backward compatibility (server.py, tests, kb_refresh)
_compute_deterministic_score = compute_deterministic_score
_build_cost_forensics = build_cost_forensics

# Maximum new (uncached) sessions to analyze per MAP run.
_MAX_NEW_PER_MAP_RUN = 50

__all__ = [
    "AIUsageOptimizer",
    "KNOWLEDGE_BASE",
    "UNIVERSAL_PRACTICES",
    "build_user_profile",
    "_load_session_cache",
    "_save_session_cache",
    "_compute_deterministic_score",
    "_build_cost_forensics",
]


class AIUsageOptimizer:
    """Analyzes usage patterns and generates optimization recommendations.

    Architecture:
      Phase 1 — MAP: Per-session LLM calls with FULL prompts, cached by
        session ID. Each call classifies intent, spirals, prompt quality.
      Phase 2 — REDUCE: Pure Python aggregation of per-session results
        into deterministic score and metrics.
      Phase 3 — GENERATE: Single LLM call with small pre-computed metrics
        input, producing prose recommendations.
    """

    def __init__(
        self,
        config: Config | None = None,
        claude_collector: Any | None = None,
    ) -> None:
        from agenttop.config import load_config

        self._config = config or load_config()
        self._claude = claude_collector

    def analyze(
        self,
        stats: list[dict[str, Any]],
        sessions: list[Session],
        model_usage: dict[str, Any],
        feature_configs: dict[str, dict[str, Any]] | None = None,
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, Any]:
        """Run MAP -> REDUCE -> GENERATE optimization analysis."""
        _progress = on_progress or (lambda *_: None)

        # Build the user profile from real data
        _progress("profile", 0, 0)
        profile = build_user_profile(
            stats, sessions, model_usage, self._claude, feature_configs,
        )
        profile["all_sessions"] = sessions

        # --- Phase 1: MAP — per-session LLM analysis (cached) ---
        cache = _load_session_cache()
        session_analyses = self._analyze_sessions_map(
            sessions, cache, on_progress=_progress,
        )

        # Build correction spirals from MAP results
        spirals = self._spirals_from_analyses(sessions, session_analyses)
        profile["prompt_analysis"]["correction_spirals"] = spirals
        profile["anti_patterns"] = analyze_anti_patterns(
            sessions, profile["prompt_analysis"],
        )

        # --- Phase 2: REDUCE — deterministic score + strengths ---
        _progress("reduce", 0, 0)
        det_score = compute_deterministic_score(profile, session_analyses)
        profile["deterministic_score"] = det_score
        profile["strengths"] = compute_strengths(profile, session_analyses)

        # --- Phase 3: GENERATE — prose from pre-computed metrics ---
        _progress("generate", 0, 0)
        llm_result = self._get_llm_analysis(
            profile, session_analyses,
        )

        # Merge everything
        return self._merge_results(profile, llm_result)

    # ------------------------------------------------------------------
    # Phase 1: MAP — per-session LLM analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _truncate_prompts(prompts: list[str]) -> str:
        """Keep first N + last M prompts, truncate each to max chars."""
        if not prompts:
            return "(no prompts)"
        head = prompts[:_MAX_PROMPTS_HEAD]
        tail = prompts[-_MAX_PROMPTS_TAIL:] if len(prompts) > _MAX_PROMPTS_HEAD + _MAX_PROMPTS_TAIL else prompts[_MAX_PROMPTS_HEAD:]
        selected = head + ([f"... ({len(prompts) - _MAX_PROMPTS_HEAD - len(tail)} skipped)"] if tail and len(prompts) > _MAX_PROMPTS_HEAD + _MAX_PROMPTS_TAIL else []) + tail
        return "\n".join(
            f"{i + 1}. {p[:_MAX_PROMPT_CHARS]}{'...' if len(p) > _MAX_PROMPT_CHARS else ''}"
            for i, p in enumerate(selected)
        )

    def _format_session_block(self, session: Session) -> str:
        """Format a single session for the batch prompt."""
        project = session.project.split("/")[-1] if session.project else "unknown"
        tool = session.tool.value if hasattr(session.tool, "value") else str(session.tool)
        return (
            f"### Session ID: {session.id}\n"
            f"Tool: {tool} | Project: {project} | "
            f"Messages: {session.message_count} | Tokens: {session.total_tokens}\n"
            f"Prompts:\n{self._truncate_prompts(session.prompts)}\n"
        )

    def _analyze_sessions_map(
        self,
        sessions: list[Session],
        cache: dict[str, dict[str, Any]],
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """MAP phase: 1 batched LLM call for all uncached sessions."""
        _progress = on_progress or (lambda *_: None)

        top_sessions = sorted(
            sessions,
            key=lambda s: s.estimated_cost_usd,
            reverse=True,
        )[:100]

        to_analyze = [s for s in top_sessions if s.id not in cache and s.prompts]
        to_analyze = to_analyze[:_MAX_NEW_PER_MAP_RUN]

        if to_analyze:
            logging.info("MAP phase: %d sessions in 1 batch call", len(to_analyze))

        results: dict[str, dict[str, Any]] = {}

        if to_analyze:
            _progress("map", 0, len(to_analyze))
            batch_results = self._analyze_batch(to_analyze)

            if batch_results:
                results = batch_results
            else:
                # Fallback: individual calls if batch failed
                logging.info("Batch MAP failed, falling back to individual calls")
                for idx, s in enumerate(to_analyze):
                    _progress("map", idx + 1, len(to_analyze))
                    result = self._analyze_single_session(s)
                    if result:
                        results[s.id] = result

            _progress("map", len(to_analyze), len(to_analyze))

        updated_cache = {**cache, **results}
        if results:
            _save_session_cache(updated_cache)

        top_ids = {s.id for s in top_sessions}
        return {sid: analysis for sid, analysis in updated_cache.items() if sid in top_ids}

    def _analyze_batch(
        self,
        sessions: list[Session],
    ) -> dict[str, dict[str, Any]] | None:
        """Analyze all sessions in a single LLM call."""
        sessions_block = "\n".join(
            self._format_session_block(s) for s in sessions
        )
        prompt = SESSION_BATCH_ANALYSIS_PROMPT.format(
            count=len(sessions),
            sessions_block=sessions_block,
        )
        system_msg = (
            "You are a coding session analyst. Classify each session. "
            "Return ONLY a valid JSON array."
        )

        for attempt in range(2):
            raw = get_completion(
                prompt,
                self._config.llm,
                system=system_msg,
                max_tokens=500 * len(sessions),
                timeout=60,
            )
            if raw.startswith("[error]"):
                logging.warning("Batch MAP LLM error: %s", raw)
                return None
            try:
                parsed = extract_json_array(raw)
                return self._parse_batch_response(parsed, sessions)
            except (json.JSONDecodeError, ValueError):
                logging.debug("Batch MAP parse failed (attempt %d/2)", attempt + 1)
        return None

    @staticmethod
    def _parse_batch_response(
        parsed: list[dict[str, Any]],
        sessions: list[Session],
    ) -> dict[str, dict[str, Any]]:
        """Map batch response array back to session IDs with validation."""
        session_ids = {s.id for s in sessions}
        results: dict[str, dict[str, Any]] = {}

        for item in parsed:
            sid = item.get("session_id", "")
            if sid not in session_ids:
                continue
            validated = validate_session_analysis(item)
            if validated:
                results[sid] = validated

        # If LLM didn't return session_ids but order matches, map by index
        if not results and len(parsed) == len(sessions):
            for session, item in zip(sessions, parsed):
                validated = validate_session_analysis(item)
                if validated:
                    results[session.id] = validated

        return results

    def _analyze_single_session(
        self,
        session: Session,
    ) -> dict[str, Any] | None:
        """Fallback: analyze one session individually if batch fails."""
        if not session.prompts:
            return None

        prompts_text = self._truncate_prompts(session.prompts)
        project = session.project.split("/")[-1] if session.project else "unknown"

        prompt = SESSION_ANALYSIS_PROMPT.format(
            tool=session.tool.value if hasattr(session.tool, "value") else str(session.tool),
            project=project,
            message_count=session.message_count,
            total_tokens=session.total_tokens,
            prompts=prompts_text,
        )

        system_msg = (
            "You are a coding session analyst. Analyze the prompt sequence "
            "and classify this session. Return ONLY valid JSON."
        )

        for attempt in range(2):
            raw = get_completion(
                prompt,
                self._config.llm,
                system=system_msg,
                max_tokens=500,
                timeout=30,
            )
            if raw.startswith("[error]"):
                logging.warning("Session analysis failed for %s: %s", session.id[:12], raw)
                return None
            try:
                parsed = extract_json_object(raw)
                return validate_session_analysis(parsed)
            except json.JSONDecodeError:
                logging.debug("Session analysis JSON parse failed (attempt %d/2) for %s", attempt + 1, session.id[:12])

        return None

    def _spirals_from_analyses(
        self,
        sessions: list[Session],
        session_analyses: dict[str, dict],
    ) -> list[dict[str, Any]]:
        """Extract correction spiral data from MAP results."""
        session_map = {s.id: s for s in sessions}
        spirals: list[dict[str, Any]] = []

        for sid, analysis in session_analyses.items():
            if not analysis.get("had_spiral"):
                continue
            session = session_map.get(sid)
            if not session:
                continue

            project = (
                session.project.split("/")[-1]
                if session.project else "unknown"
            )
            prompt_count = len(session.prompts) if session.prompts else 0
            est_corrections = max(3, round(prompt_count * 0.3))
            est_rate = round(est_corrections / max(prompt_count, 1) * 100)
            spirals.append({
                "project": project,
                "messages": session.message_count,
                "corrections": est_corrections,
                "correction_rate": est_rate,
                "what_went_wrong": analysis.get("spiral_detail", ""),
                "first_prompt": (
                    session.prompts[0][:120] if session.prompts else ""
                ),
                "tokens_wasted": session.total_tokens,
            })

        return sorted(
            spirals, key=lambda x: x["tokens_wasted"], reverse=True,
        )[:10]

    # ------------------------------------------------------------------
    # Phase 3: GENERATE — prose from pre-computed metrics
    # ------------------------------------------------------------------

    def _get_llm_analysis(
        self,
        profile: dict[str, Any],
        session_analyses: dict[str, dict],
    ) -> dict[str, Any]:
        """GENERATE phase: single LLM call with small pre-computed input."""
        det_score = profile.get("deterministic_score", {})
        active_tool_ids = {
            t["tool"] for t in profile.get("active_tools", [])
        }

        # Build session observations summary from MAP results
        observations: list[str] = []
        for sid, analysis in list(session_analyses.items())[:15]:
            parts = [f"Session {sid[:12]}:"]
            parts.append(f"intent={analysis.get('intent', '?')}")
            if analysis.get("had_spiral"):
                parts.append(f"SPIRAL: {analysis.get('spiral_detail', '')}")
            if analysis.get("wasted_effort"):
                parts.append(f"waste: {analysis['wasted_effort']}")
            if analysis.get("actionable_fix"):
                parts.append(f"fix: {analysis['actionable_fix']}")
            observations.append(" | ".join(parts))

        # Build compact summaries for the prompt
        anti_patterns = profile.get("anti_patterns", [])
        anti_summary = "; ".join(
            f"{ap['pattern']} ({ap.get('severity', '?')}, {ap.get('count', 0)}x)"
            for ap in anti_patterns
        ) or "None detected"

        cost_f = profile.get("cost_forensics", {})
        cost_summary = (
            f"Total: ${cost_f.get('total_cost', 0):.2f}, "
            f"Waste: ${cost_f.get('estimated_waste', 0):.2f} "
            f"({cost_f.get('waste_pct', 0)}%)"
        )

        # Extract real project details (strip sample_prompts for brevity)
        project_details = {
            k: {kk: vv for kk, vv in v.items() if kk != "sample_prompts"}
            for k, v in profile.get("project_details", {}).items()
        }

        session_patterns = json.dumps({
            "count": profile.get("session_count", 0),
            "distribution": profile.get("session_distribution", {}),
            "intent_distribution": profile.get("intent_distribution", {}),
            "project_details": project_details,
        }, default=str)

        # Build explicit project list
        real_projects_section = "\n".join(
            f"- {name}: {details.get('sessions', 0)} sessions, "
            f"{details.get('tokens', 0)} tokens, "
            f"${details.get('cost', 0):.2f}, "
            f"intents={dict(details.get('intents', {}))}"
            for name, details in project_details.items()
        ) or "No projects found"

        tool_knowledge = build_tool_knowledge(active_tool_ids)

        prompt = SYNTHESIS_PROMPT.format(
            score=det_score.get("score", 0),
            grades=json.dumps(det_score.get("grades", {}), default=str),
            anti_patterns_summary=anti_summary,
            cost_summary=cost_summary,
            session_patterns=session_patterns,
            features=json.dumps(
                profile.get("feature_detection", {}), default=str,
            ),
            real_projects=real_projects_section,
            session_observations="\n".join(observations) or "No sessions analyzed",
            tool_knowledge=json.dumps(tool_knowledge, default=str),
        )

        system_msg = (
            "You are an AI coding workflow consultant. "
            "Return ONLY valid JSON. No markdown fences, no explanation."
        )

        for attempt in range(3):
            raw = get_completion(
                prompt,
                self._config.llm,
                system=system_msg,
                max_tokens=4000,
                timeout=60,
            )

            if raw.startswith("[error]"):
                return {"error": raw, "source": "error"}

            try:
                parsed = extract_json_object(raw)
                parsed["source"] = "llm"
                return parsed
            except (json.JSONDecodeError, IndexError, KeyError):
                logging.debug(
                    "Synthesis JSON parse failed (attempt %d/3): %s",
                    attempt + 1,
                    raw[:200] if raw else "empty",
                )

        return {
            "error": "LLM returned invalid JSON after 3 attempts. Try a different model.",
            "source": "error",
        }

    # ------------------------------------------------------------------
    # Merge: deterministic score + Python metrics + LLM prose
    # ------------------------------------------------------------------

    def _merge_results(
        self,
        profile: dict[str, Any],
        llm_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge Python-computed metrics with LLM prose."""
        det_score = profile.get("deterministic_score", {})

        # Python-computed fields (always accurate)
        result: dict[str, Any] = {
            "anti_patterns": profile.get("anti_patterns", []),
            "cost_forensics": profile.get("cost_forensics", {}),
            "prompt_analysis": profile.get("prompt_analysis", {}),
            "context_engineering": profile.get("context_engineering", {}),
            "session_details": profile.get("session_details", []),
            "profile_summary": {
                "total_tokens": profile.get("total_tokens", 0),
                "total_cost": profile.get("total_cost", 0),
                "session_count": profile.get("session_count", 0),
                "avg_messages": profile.get(
                    "avg_messages_per_session", 0,
                ),
                "cache_hit_rate": (
                    profile.get("model_usage", {})
                    .get("overall_cache_hit_rate", 0)
                ),
                "active_tools": len(profile.get("active_tools", [])),
            },
            "feature_detection": profile.get("feature_detection", {}),
            "strengths": profile.get("strengths", []),
            "score": det_score.get("score", 0),
            "grades": det_score.get("grades", {}),
        }

        # Handle LLM errors
        if llm_result.get("source") == "error":
            result["error"] = llm_result.get("error", "LLM analysis failed")
            result["source"] = "partial"
            result["setup_hint"] = (
                "The optimizer requires an LLM. Quickest setup:\n\n"
                "  brew install ollama\n"
                "  ollama pull gemma3:4b\n"
                "  ollama serve\n\n"
                "Then refresh and try again."
            )
            result["recommendations"] = []
            result["missing_features"] = []
            result["project_insights"] = []
            result["workflow"] = {}
            result["developer_profile"] = {}
            return result

        # LLM-provided prose
        result["developer_profile"] = llm_result.get("developer_profile", {})
        result["recommendations"] = llm_result.get("recommendations", [])
        result["missing_features"] = llm_result.get("missing_features", [])
        result["workflow"] = llm_result.get("workflow", {})
        result["source"] = "llm"

        # Validate project_insights — drop any hallucinated project names
        real_projects = set(profile.get("project_details", {}).keys())
        result["project_insights"] = [
            pi for pi in llm_result.get("project_insights", [])
            if pi.get("project") in real_projects
        ]

        return result
