# ruff: noqa: E501
"""Deterministic scoring, prompt analysis, anti-patterns, cost forensics, and strengths.

All functions in this module are pure Python — no LLM calls. They compute
exact metrics from real collector data and (optionally) LLM session
classifications from the MAP phase.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from agenttop.models import Session


# ---------------------------------------------------------------------------
# Prompt analysis (NLP-lite)
# ---------------------------------------------------------------------------


def analyze_prompts(sessions: list[Session]) -> dict[str, Any]:
    """NLP-lite analysis on all session prompts."""
    all_prompts: list[str] = []
    for s in sessions:
        all_prompts.extend(s.prompts)

    if not all_prompts:
        return {
            "prompt_length_distribution": {
                "commands_under_20": 0, "short_20_100": 0,
                "detailed_100_500": 0, "very_detailed_500_plus": 0,
                "avg_length": 0,
            },
            "correction_spirals": [],
            "repeated_prompts": [],
            "slash_commands": {},
            "uses_compact": 0,
            "uses_clear": 0,
            "specificity_score": 0,
        }

    lengths = [len(p) for p in all_prompts]
    result: dict[str, Any] = {}
    result["prompt_length_distribution"] = {
        "commands_under_20": sum(1 for ln in lengths if ln < 20),
        "short_20_100": sum(1 for ln in lengths if 20 <= ln < 100),
        "detailed_100_500": sum(1 for ln in lengths if 100 <= ln < 500),
        "very_detailed_500_plus": sum(1 for ln in lengths if ln >= 500),
        "avg_length": round(sum(lengths) / len(lengths)),
    }

    # Correction spirals — populated by LLM-based conversation analysis
    result["correction_spirals"] = []

    # Repeated prompts (skill candidates)
    prompt_counter = Counter(p for p in all_prompts if len(p) > 15)
    result["repeated_prompts"] = [
        {"prompt": t[:150], "count": c}
        for t, c in prompt_counter.most_common(10) if c > 2
    ]

    # Slash commands
    slash_counts = Counter(
        p.split()[0] for p in all_prompts if p.startswith("/")
    )
    result["slash_commands"] = dict(slash_counts.most_common(10))
    result["uses_compact"] = slash_counts.get("/compact", 0)
    result["uses_clear"] = slash_counts.get("/clear", 0)

    # Specificity score
    result["specificity_score"] = round(
        sum(1 for ln in lengths if ln >= 100) / len(lengths) * 100, 1,
    )
    return result


# ---------------------------------------------------------------------------
# Anti-pattern detection
# ---------------------------------------------------------------------------


def analyze_anti_patterns(
    sessions: list[Session],
    prompt_analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    """Detect anti-patterns with severity, count, detail, fix, and examples."""
    patterns: list[dict[str, Any]] = []

    # 1. Correction spirals
    spirals = prompt_analysis.get("correction_spirals", [])
    if spirals:
        total_wasted = sum(sp["tokens_wasted"] for sp in spirals)
        patterns.append({
            "pattern": "Correction Spirals",
            "icon": "\U0001f300",
            "severity": "high",
            "count": len(spirals),
            "detail": (
                f"{len(spirals)} sessions with 3+ corrections wasting "
                f"{total_wasted:,} tokens. You're fighting the AI instead of guiding it."
            ),
            "fix": (
                "Be specific upfront: include file paths, expected behavior, and constraints "
                "in your first prompt. If the AI goes wrong, start a new session with a "
                "clearer prompt instead of correcting repeatedly."
            ),
            "examples": [
                f"{sp['project']}: {sp['corrections']} corrections in {sp['messages']} msgs "
                f"({sp['correction_rate']}% rate, {sp['tokens_wasted']:,} tokens)"
                + (f" — {sp['what_went_wrong']}" if sp.get("what_went_wrong") else "")
                for sp in spirals[:3]
            ],
        })

    # 2. Marathon sessions
    marathon_sessions = [s for s in sessions if s.message_count >= 100]
    if marathon_sessions:
        marathon_tokens = sum(s.total_tokens for s in marathon_sessions)
        patterns.append({
            "pattern": "Marathon Sessions",
            "icon": "\U0001f3c3",
            "severity": "high" if len(marathon_sessions) > 5 else "medium",
            "count": len(marathon_sessions),
            "detail": (
                f"{len(marathon_sessions)} sessions with 100+ messages "
                f"({marathon_tokens:,} tokens). After ~50 messages, context degrades "
                f"and the AI starts forgetting earlier instructions."
            ),
            "fix": (
                "Break work into focused sessions of <30 messages. Use /compact to "
                "compress context mid-session. Start new sessions for new subtasks. "
                "Use CLAUDE.md for persistent context."
            ),
            "examples": [
                f"{s.project.split('/')[-1] if s.project else 'unknown'}: "
                f"{s.message_count} msgs, {s.total_tokens:,} tokens"
                for s in sorted(marathon_sessions, key=lambda x: x.message_count, reverse=True)[:3]
            ],
        })

    # 3. Vague prompts
    specificity = prompt_analysis.get("specificity_score", 0)
    if specificity < 30:
        patterns.append({
            "pattern": "Vague Prompts",
            "icon": "\U0001f32b\ufe0f",
            "severity": "medium",
            "count": round((100 - specificity) / 100 * sum(
                len(s.prompts) for s in sessions
            )),
            "detail": (
                f"Only {specificity}% of prompts are detailed (100+ chars). "
                f"Short, vague prompts lead to more back-and-forth corrections."
            ),
            "fix": (
                "Include context in prompts: file paths, expected behavior, constraints, "
                "and examples. A detailed first prompt saves 3-5 correction messages."
            ),
            "examples": [],
        })

    # 4. No context management
    uses_compact = prompt_analysis.get("uses_compact", 0)
    uses_clear = prompt_analysis.get("uses_clear", 0)
    bloated = sum(1 for s in sessions if s.message_count > 50)
    if bloated > 3 and uses_compact == 0 and uses_clear == 0:
        patterns.append({
            "pattern": "No Context Management",
            "icon": "\U0001f5c4\ufe0f",
            "severity": "medium",
            "count": bloated,
            "detail": (
                f"{bloated} bloated sessions (>50 msgs) but never used /compact or "
                f"/clear. Context grows unbounded, degrading response quality."
            ),
            "fix": (
                "Use /compact when context feels heavy (~30-40 messages). "
                "Use /clear between distinct subtasks. Both are free and instant."
            ),
            "examples": [],
        })

    # 5. Repeated prompts (skill candidates)
    repeated = prompt_analysis.get("repeated_prompts", [])
    if repeated:
        patterns.append({
            "pattern": "Repeated Prompts",
            "icon": "\U0001f501",
            "severity": "low",
            "count": sum(r["count"] for r in repeated),
            "detail": (
                f"{len(repeated)} prompts repeated 3+ times — these are skill candidates. "
                f"Automating them would save time and tokens."
            ),
            "fix": (
                "Create custom slash commands or CLAUDE.md snippets for repeated prompts. "
                "Consider building a skill file for frequently used workflows."
            ),
            "examples": [
                f'"{r["prompt"][:80]}..." ({r["count"]}x)'
                for r in repeated[:3]
            ],
        })

    return patterns


# ---------------------------------------------------------------------------
# Cost forensics
# ---------------------------------------------------------------------------


def build_cost_forensics(
    profile: dict[str, Any],
    sessions: list[Session],
    model_usage: dict[str, Any],
) -> dict[str, Any]:
    """Deep cost analysis with waste estimation."""
    from agenttop.collectors.claude import _match_model_pricing

    ce = profile.get("context_engineering", {})
    total_cost = ce.get("total_cost", 0.0)

    # Cost by project
    project_costs: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"cost": 0.0, "tokens": 0},
    )
    for s in sessions:
        pname = s.project.split("/")[-1] if s.project else "unknown"
        project_costs[pname]["cost"] += s.estimated_cost_usd
        project_costs[pname]["tokens"] += s.total_tokens
    cost_by_project = [
        {"project": name, "cost": round(d["cost"], 2), "tokens": d["tokens"]}
        for name, d in sorted(
            project_costs.items(), key=lambda x: x[1]["cost"], reverse=True,
        )[:10]
    ]

    # Cost by model
    model_costs: dict[str, dict[str, float]] = defaultdict(
        lambda: {"cost": 0.0, "tokens": 0},
    )

    # Claude: precise per-model breakdown
    for model_id, usage in model_usage.items():
        pricing = _match_model_pricing(model_id)
        model_cost = (
            usage.get("inputTokens", 0) / 1_000_000 * pricing["input"]
            + usage.get("outputTokens", 0) / 1_000_000 * pricing["output"]
            + usage.get("cacheReadInputTokens", 0) / 1_000_000 * pricing["cache_read"]
            + usage.get("cacheCreationInputTokens", 0) / 1_000_000 * pricing["cache_create"]
        )
        billed_tokens = (
            usage.get("inputTokens", 0)
            + usage.get("outputTokens", 0)
        )
        model_costs[model_id]["cost"] += model_cost
        model_costs[model_id]["tokens"] += billed_tokens

    # Non-Claude tools
    claude_session_ids = {
        s.id for s in sessions if s.tool.value == "claude_code"
    }
    for s in sessions:
        if s.id in claude_session_ids:
            continue
        label = s.tool.value
        model_costs[label]["cost"] += s.estimated_cost_usd
        model_costs[label]["tokens"] += s.total_tokens

    cost_by_model = [
        {"model": model_id, "cost": round(d["cost"], 2), "tokens": int(d["tokens"])}
        for model_id, d in model_costs.items()
        if d["cost"] > 0 or d["tokens"] > 0
    ]
    cost_by_model.sort(key=lambda x: x["cost"], reverse=True)

    # Estimated waste from marathon sessions
    marathon_threshold = 50
    waste_discount = 0.5
    estimated_waste = 0.0
    for s in sessions:
        if s.message_count > marathon_threshold:
            tail_fraction = (s.message_count - marathon_threshold) / s.message_count
            estimated_waste += s.estimated_cost_usd * tail_fraction * waste_discount

    waste_pct = round(estimated_waste / total_cost * 100, 1) if total_cost > 0 else 0

    return {
        "total_cost": round(total_cost, 2),
        "estimated_waste": round(estimated_waste, 2),
        "waste_pct": waste_pct,
        "cost_by_project": cost_by_project,
        "cost_by_model": cost_by_model,
    }


# ---------------------------------------------------------------------------
# Deterministic score
# ---------------------------------------------------------------------------


def compute_deterministic_score(
    profile: dict[str, Any],
    session_analyses: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """Compute a 0-100 optimization score from LLM-classified sessions + metrics.

    Five dimensions, each scored 0-20:
      1. Session Hygiene = sessions without spirals / total analyzed
      2. Prompt Quality  = sessions without wasted effort / total analyzed
      3. Cost Efficiency  = (1 - waste_pct / 100) * 20
      4. Cache Efficiency  = cache_hit_rate / 100 * 20
      5. Tool Utilization  = features_configured / features_available * 20
    """
    grades: dict[str, dict[str, Any]] = {}
    breakdown: dict[str, float] = {}

    sessions = profile.get("all_sessions", [])
    sessions_count = len(sessions) or profile.get("session_count", 0) or 1
    prompt_analysis = profile.get("prompt_analysis", {})
    cost_forensics = profile.get("cost_forensics", {})
    model_usage = profile.get("model_usage", {})
    feature_detection = profile.get("feature_detection", {})

    analyzed = list((session_analyses or {}).values())
    total_analyzed = max(len(analyzed), 1)
    confidence = "full" if total_analyzed >= 25 else "partial"

    # --- 1. Session Hygiene (0-20) ---
    if analyzed:
        no_spiral = sum(1 for a in analyzed if not a.get("had_spiral"))
        hygiene_score = round(no_spiral / total_analyzed * 20, 1)
        confidence_note = f" ({confidence}, {total_analyzed} analyzed)" if confidence == "partial" else ""
        detail = (
            f"{no_spiral}/{total_analyzed} analyzed sessions spiral-free{confidence_note}"
        )
    else:
        healthy_count = sum(1 for s in sessions if s.message_count < 50) if sessions else 0
        hygiene_score = round(healthy_count / max(len(sessions), 1) * 20, 1) if sessions else 0.0
        detail = f"{healthy_count}/{len(sessions) if sessions else 0} sessions under 50 messages"

    breakdown["session_hygiene"] = hygiene_score
    grades["session_hygiene"] = _grade_dimension(hygiene_score, 20, detail)

    # --- 2. Prompt Quality (0-20) ---
    if analyzed:
        good_prompts = sum(
            1 for a in analyzed if not a.get("wasted_effort")
        )
        prompt_score = round(good_prompts / total_analyzed * 20, 1)
        confidence_note = f" ({confidence})" if confidence == "partial" else ""
        detail = (
            f"{good_prompts}/{total_analyzed} sessions had no wasted effort{confidence_note}"
        )
    else:
        specificity = prompt_analysis.get("specificity_score", 0)
        spiral_count = len(prompt_analysis.get("correction_spirals", []))
        spiral_free_ratio = 1 - (spiral_count / max(sessions_count, 1))
        prompt_score = round(
            (specificity / 100 * 0.6 + spiral_free_ratio * 0.4) * 20, 1,
        )
        detail = f"{specificity}% prompt specificity, {spiral_count} spirals"

    breakdown["prompt_quality"] = prompt_score
    grades["prompt_quality"] = _grade_dimension(prompt_score, 20, detail)

    # --- 3. Cost Efficiency (0-20) ---
    waste_pct = cost_forensics.get("waste_pct", 0)
    cost_score = round((1 - waste_pct / 100) * 20, 1)
    total_cost = cost_forensics.get("total_cost", 0)
    estimated_waste = cost_forensics.get("estimated_waste", 0)
    breakdown["cost_efficiency"] = cost_score
    grades["cost_efficiency"] = _grade_dimension(
        cost_score, 20,
        f"${estimated_waste:.2f} wasted of ${total_cost:.2f} total ({waste_pct}% waste rate)",
    )

    # --- 4. Cache Efficiency (0-20) ---
    cache_hit_rate = model_usage.get("overall_cache_hit_rate", 0) if isinstance(model_usage, dict) else 0
    cache_score = round(cache_hit_rate / 100 * 20, 1)
    breakdown["cache_efficiency"] = cache_score
    grades["cache_efficiency"] = _grade_dimension(
        cache_score, 20,
        f"{cache_hit_rate:.1f}% cache hit rate across all sessions",
    )

    # --- 5. Tool Utilization (0-20) ---
    features_available = 9
    features_used = 0

    claude_features = feature_detection.get("claude_code", {})
    if claude_features:
        feature_checks = [
            bool(claude_features.get("agents", {}).get("count", 0)),
            bool(claude_features.get("commands", {}).get("count", 0)),
            bool(claude_features.get("rules", {}).get("total_count", 0)),
            bool(claude_features.get("skills", {}).get("count", 0)),
            bool(claude_features.get("hooks", {}).get("configured", False)),
            bool(claude_features.get("mcp_servers", {}).get("count", 0)),
            bool(claude_features.get("project_memory", {}).get("has_memory", False)),
        ]
        features_used += sum(feature_checks)

    uses_compact = prompt_analysis.get("uses_compact", 0)
    uses_clear = prompt_analysis.get("uses_clear", 0)
    if uses_compact > 0:
        features_used += 1
    if uses_clear > 0:
        features_used += 1

    utilization_ratio = min(features_used, features_available) / features_available
    tool_score = round(utilization_ratio * 20, 1)
    breakdown["tool_utilization"] = tool_score
    grades["tool_utilization"] = _grade_dimension(
        tool_score, 20,
        f"{features_used}/{features_available} features active "
        f"(/compact {uses_compact}x, /clear {uses_clear}x)",
    )

    total_score = round(sum(breakdown.values()))
    return {
        "score": total_score,
        "grades": grades,
        "breakdown": breakdown,
        "sessions_analyzed": total_analyzed,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Strengths
# ---------------------------------------------------------------------------


def compute_strengths(
    profile: dict[str, Any],
    session_analyses: dict[str, dict] | None = None,
) -> list[dict[str, str]]:
    """Extract diverse positive signals — what the user is doing right."""
    strengths: list[dict[str, str]] = []
    analyzed = list((session_analyses or {}).values())
    sessions = profile.get("all_sessions", [])
    prompt_analysis = profile.get("prompt_analysis", {})
    cost_forensics = profile.get("cost_forensics", {})
    model_usage = profile.get("model_usage", {})
    feature_detection = profile.get("feature_detection", {})

    # 1. Resolution rate from MAP
    if analyzed:
        resolved = sum(1 for a in analyzed if a.get("outcome") == "resolved")
        total = len(analyzed)
        rate = round(resolved / total * 100) if total else 0
        if rate >= 70:
            strengths.append({
                "title": "High resolution rate",
                "detail": f"{resolved}/{total} sessions resolved successfully ({rate}%)",
                "icon": "\u2705",
            })

    # 2. Intent diversity from MAP
    if analyzed:
        intents = set(a.get("intent", "other") for a in analyzed)
        if len(intents) >= 4:
            strengths.append({
                "title": "Versatile AI usage",
                "detail": f"Using AI across {len(intents)} task types: {', '.join(sorted(intents))}",
                "icon": "\U0001f3af",
            })

    # 3. Low spiral rate
    if analyzed:
        no_spiral = sum(1 for a in analyzed if not a.get("had_spiral"))
        rate = round(no_spiral / len(analyzed) * 100) if analyzed else 0
        if rate >= 80:
            strengths.append({
                "title": "Clean session flow",
                "detail": f"{rate}% of analyzed sessions had no correction spirals",
                "icon": "\U0001f9f9",
            })

    # 4. Good prompt specificity
    specificity = prompt_analysis.get("specificity_score", 0)
    if specificity >= 50:
        strengths.append({
            "title": "Detailed prompts",
            "detail": f"{specificity}% of prompts include specific context (100+ chars)",
            "icon": "\U0001f4dd",
        })

    # 5. Context management habits
    uses_compact = prompt_analysis.get("uses_compact", 0)
    uses_clear = prompt_analysis.get("uses_clear", 0)
    if uses_compact > 0 or uses_clear > 0:
        parts = []
        if uses_clear > 0:
            parts.append(f"/clear {uses_clear}x")
        if uses_compact > 0:
            parts.append(f"/compact {uses_compact}x")
        strengths.append({
            "title": "Active context management",
            "detail": f"Using {', '.join(parts)} to keep sessions focused",
            "icon": "\U0001f5c2\ufe0f",
        })

    # 6. Cache efficiency
    cache_hit_rate = model_usage.get("overall_cache_hit_rate", 0) if isinstance(model_usage, dict) else 0
    if cache_hit_rate >= 60:
        strengths.append({
            "title": "Strong cache utilization",
            "detail": f"{cache_hit_rate:.1f}% cache hit rate — saving significantly on input tokens",
            "icon": "\u26a1",
        })

    # 7. Low waste rate
    waste_pct = cost_forensics.get("waste_pct", 0)
    if waste_pct <= 10:
        strengths.append({
            "title": "Cost-efficient workflow",
            "detail": f"Only {waste_pct}% estimated waste — well below the typical 15-25% range",
            "icon": "\U0001f4b0",
        })

    # 8. Multi-tool usage
    active_tools = profile.get("active_tools", [])
    if len(active_tools) >= 2:
        tool_names = [t.get("display_name", t.get("tool", "?")) for t in active_tools]
        strengths.append({
            "title": "Multi-tool workflow",
            "detail": f"Using {len(active_tools)} AI tools: {', '.join(tool_names)}",
            "icon": "\U0001f6e0\ufe0f",
        })

    # 9. Feature adoption
    claude_features = feature_detection.get("claude_code", {})
    adopted = []
    if claude_features.get("agents", {}).get("count", 0):
        adopted.append(f"{claude_features['agents']['count']} agents")
    if claude_features.get("commands", {}).get("count", 0):
        adopted.append(f"{claude_features['commands']['count']} commands")
    if claude_features.get("hooks", {}).get("configured"):
        adopted.append("hooks")
    if claude_features.get("skills", {}).get("count", 0):
        adopted.append(f"{claude_features['skills']['count']} skills")
    if claude_features.get("rules", {}).get("total_count", 0):
        adopted.append(f"{claude_features['rules']['total_count']} rules")
    if len(adopted) >= 3:
        strengths.append({
            "title": "Power user features",
            "detail": f"Leveraging {', '.join(adopted)}",
            "icon": "\U0001f680",
        })

    # 10. Model diversity
    if isinstance(model_usage, dict):
        model_count = model_usage.get("model_count", 0)
        if model_count >= 2:
            strengths.append({
                "title": "Strategic model selection",
                "detail": f"Using {model_count} different models — matching model to task complexity",
                "icon": "\U0001f9e0",
            })

    # 11. Good prompt quality from MAP
    if analyzed:
        good_prompts = sum(1 for a in analyzed if not a.get("wasted_effort"))
        rate = round(good_prompts / len(analyzed) * 100) if analyzed else 0
        if rate >= 70:
            strengths.append({
                "title": "Efficient communication",
                "detail": f"{rate}% of sessions had no wasted effort — clear instructions from the start",
                "icon": "\U0001f4ac",
            })

    # 12. Multi-project breadth
    project_count = profile.get("project_count", 0)
    if project_count >= 5:
        strengths.append({
            "title": "Broad project coverage",
            "detail": f"AI assistance across {project_count} projects",
            "icon": "\U0001f4c2",
        })

    return strengths[:8]


def _grade_dimension(score: float, max_score: float, detail: str) -> dict[str, str]:
    """Convert a numeric score to a letter grade with detail."""
    pct = score / max_score * 100 if max_score > 0 else 0
    if pct >= 85:
        grade = "A"
    elif pct >= 65:
        grade = "B"
    elif pct >= 45:
        grade = "C"
    else:
        grade = "D"
    return {"grade": grade, "detail": detail}
