# ruff: noqa: E501
"""Demo collector — Apple Store mode. Realistic fake data for screenshots."""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta
from typing import Any

from agenttop.collectors.base import BaseCollector
from agenttop.models import Event, Session, ToolName, ToolStats

# Projects that tell a story — a startup eng team building real things
PROJECTS = [
    {"name": "apex-trading-engine", "weight": 25, "avg_cost": 8.0},
    {"name": "vaultkeeper", "weight": 18, "avg_cost": 5.5},
    {"name": "phantom-search", "weight": 15, "avg_cost": 4.2},
    {"name": "neon-ui", "weight": 12, "avg_cost": 2.8},
    {"name": "dataweave", "weight": 10, "avg_cost": 6.0},
    {"name": "ironclad-auth", "weight": 8, "avg_cost": 3.5},
    {"name": "skybridge-api", "weight": 5, "avg_cost": 1.8},
    {"name": "ghostwriter", "weight": 4, "avg_cost": 2.0},
    {"name": "pulsecheck", "weight": 2, "avg_cost": 0.9},
    {"name": "dotfiles", "weight": 1, "avg_cost": 0.3},
]

# Prompts that feel like a real engineer's day — specific, contextual, varied
PROMPTS_BY_PROJECT: dict[str, list[str]] = {
    "apex-trading-engine": [
        "the order matching engine is dropping limit orders when the book depth exceeds 10k entries. trace the hot path in matching.rs",
        "implement circuit breaker — halt trading if price moves >5% in 100ms window. needs to propagate to all connected gateways",
        "why is the FIX protocol handler leaking file descriptors under load? we're hitting ulimit after 6 hours",
        "add TWAP execution algorithm. split parent order into child slices across configurable time window",
        "the latency p99 spiked from 12us to 340us after the last deploy. bisect the commits and find the regression",
        "write property-based tests for the order book — fuzz with random insert/cancel/modify sequences",
    ],
    "vaultkeeper": [
        "migrate from AES-256-CBC to AES-256-GCM for all at-rest encryption. need zero-downtime key rotation",
        "the HSM integration is returning PKCS#11 CKR_DEVICE_ERROR intermittently. add retry with exponential backoff",
        "implement shamir secret sharing for the master key — 3-of-5 threshold scheme",
        "audit log shows a gap between 02:14 and 02:17 UTC. find what happened to those 180 seconds of events",
        "add mTLS between all vault nodes. generate certs with 90-day rotation via the internal CA",
    ],
    "phantom-search": [
        "the vector similarity search returns garbage above 100M docs. the HNSW index params need tuning — try ef_construction=400 M=48",
        "implement hybrid search: combine BM25 lexical + cosine similarity with reciprocal rank fusion",
        "why does reindexing take 14 hours? profile the embedding pipeline — suspect it's the tokenizer batch size",
        "add query understanding: detect when the user means exact match vs semantic. 'error code 4012' should be exact",
        "the relevance A/B test shows our reranker is worse than baseline on short queries. debug the cross-encoder",
    ],
    "neon-ui": [
        "the DataGrid component re-renders 847 times on scroll. fix with virtualization — only render visible rows ± 5 buffer",
        "implement the command palette (Cmd+K). needs fuzzy search across all routes, recent files, and actions",
        "dark mode has contrast issues on the chart tooltips. the rgba overlay math is wrong for the glass effect",
        "add skeleton loading states to all dashboard cards. use CSS containment for paint performance",
        "the bundle is 2.3MB. code-split the chart library — it's 800KB and only used on the analytics page",
    ],
    "dataweave": [
        "the Spark job OOMs at the join stage. partition key is skewed — user_id has a 40:1 hotspot ratio",
        "implement incremental CDC pipeline from Postgres to the lakehouse. use debezium with exactly-once semantics",
        "write a data quality check: assert no nulls in required columns, referential integrity on foreign keys, freshness < 2hr",
        "the cost anomaly detector flagged a 3x spike in BigQuery slot usage. trace it to the query and optimize",
    ],
    "ironclad-auth": [
        "add WebAuthn/passkey support as a second factor. need the registration ceremony and assertion flow",
        "the session token rotation has a race condition — two concurrent requests can both get 401 during refresh",
        "implement SCIM provisioning endpoint for enterprise SSO. Okta sends user create/update/deactivate",
    ],
    "skybridge-api": [
        "add request coalescing for the /users/:id endpoint — 50 concurrent identical GETs should collapse to 1 DB query",
        "implement API versioning via Accept header. v2 changes the pagination format from offset to cursor",
    ],
    "ghostwriter": [
        "the markdown-to-PDF renderer strips code blocks inside blockquotes. fix the AST walker",
        "add real-time collaborative editing. use CRDTs (Yjs) for conflict-free merging across clients",
    ],
    "pulsecheck": [
        "the health check endpoint returns 200 even when the database connection pool is exhausted. add deep health checks",
    ],
    "dotfiles": [
        "update my neovim config to use lazy.nvim instead of packer. migrate all 34 plugins",
    ],
}

# Generic fallback prompts
GENERIC_PROMPTS = [
    "fix the failing CI pipeline — the e2e tests timeout after the Node upgrade",
    "refactor this function into smaller pieces, it's 280 lines and impossible to test",
    "review this PR for security issues before we merge to main",
    "write integration tests that hit the real database, not mocks",
    "the memory usage grows linearly over 24 hours. find the leak",
    "add structured logging with correlation IDs across all microservices",
    "optimize this SQL query — it does a sequential scan on a 50M row table",
    "set up Grafana dashboards for the new service. alert on p99 > 500ms and error rate > 1%",
    "implement graceful shutdown — drain in-flight requests before stopping",
    "the webhook delivery has 12% failure rate. add dead letter queue with retry",
]

DEMO_MODELS = {
    "claude-opus-4-6-20260301": {
        "inputTokens": 1_847_293,
        "outputTokens": 9_421_087,
        "cacheReadInputTokens": 12_384_012,
        "cacheCreationInputTokens": 487_291,
    },
    "claude-sonnet-4-6-20260301": {
        "inputTokens": 892_104,
        "outputTokens": 3_291_847,
        "cacheReadInputTokens": 5_102_893,
        "cacheCreationInputTokens": 201_847,
    },
    "claude-haiku-4-5-20251001": {
        "inputTokens": 241_029,
        "outputTokens": 847_192,
        "cacheReadInputTokens": 1_928_471,
        "cacheCreationInputTokens": 89_120,
    },
}


def _seed(salt: str) -> None:
    random.seed(hashlib.md5(f"agenttop-{salt}".encode()).hexdigest())


def _pick_project() -> dict:
    weights = [p["weight"] for p in PROJECTS]
    return random.choices(PROJECTS, weights=weights, k=1)[0]


def _pick_prompts(project_name: str, count: int) -> list[str]:
    pool = PROMPTS_BY_PROJECT.get(project_name, GENERIC_PROMPTS)
    return random.sample(pool, min(count, len(pool)))


def _make_sessions(
    tool: ToolName, count: int, days_back: int = 30,
) -> list[Session]:
    _seed(f"sessions-{tool.value}")
    sessions = []
    now = datetime.now()

    for i in range(count):
        proj = _pick_project()
        name = proj["name"]

        # Cluster sessions in realistic work hours (9-23) with some late nights
        hour = random.choices(
            range(24),
            weights=[0, 0, 0, 0, 0, 0, 1, 2, 5, 10, 12, 10, 8, 10, 12, 10,
                     8, 6, 5, 4, 3, 3, 2, 1],
            k=1,
        )[0]
        day_offset = random.uniform(0, days_back)
        start = (now - timedelta(days=day_offset)).replace(
            hour=hour,
            minute=random.randint(0, 59),
            second=random.randint(0, 59),
        )

        # Session length varies: quick fixes (5m) to deep work (2h)
        duration_min = random.choices(
            [5, 12, 25, 45, 75, 120, 180],
            weights=[15, 20, 25, 20, 10, 7, 3],
            k=1,
        )[0]
        end = start + timedelta(minutes=duration_min)

        msg_count = max(3, int(duration_min * random.uniform(0.3, 0.8)))
        tokens = msg_count * random.randint(1200, 5000)
        tool_calls = int(msg_count * random.uniform(0.5, 2.5))

        # Cost scales with project complexity
        base_rate = proj["avg_cost"] / 40  # per message
        cost = msg_count * base_rate * random.uniform(0.6, 1.4)

        num_prompts = random.randint(1, min(4, msg_count))
        prompts = _pick_prompts(name, num_prompts)

        sid = hashlib.sha256(
            f"d-{tool.value}-{i}-{name}-{start.isoformat()}".encode(),
        ).hexdigest()[:16]

        # Generate realistic tool breakdown
        tb: dict[str, int] = {}
        if tool_calls > 0:
            tb["Read"] = random.randint(1, max(2, tool_calls // 3))
            tb["Edit"] = random.randint(1, max(2, tool_calls // 4))
            tb["Bash"] = random.randint(0, max(1, tool_calls // 4))
            tb["Grep"] = random.randint(0, max(1, tool_calls // 5))
            tb["Glob"] = random.randint(0, max(1, tool_calls // 6))
            tb["Write"] = random.randint(0, 2)
            tb["Agent"] = random.randint(0, 1)
            tb = {k: v for k, v in tb.items() if v > 0}

        # Model used for this session
        model_choices = [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
        ]
        model_weights = [30, 50, 20]
        mu: dict[str, int] = {}
        if tool == ToolName.CLAUDE_CODE:
            m = random.choices(model_choices, model_weights, k=1)[0]
            mu[m] = msg_count

        sessions.append(Session(
            id=sid,
            tool=tool,
            project=f"/Users/dev/{name}",
            start_time=start,
            end_time=end,
            message_count=msg_count,
            tool_call_count=tool_calls,
            total_tokens=tokens,
            estimated_cost_usd=round(cost, 3),
            prompts=prompts,
            tool_breakdown=tb,
            models_used=mu,
        ))

    sessions.sort(key=lambda s: s.start_time, reverse=True)
    return sessions


def _make_stats(tool: ToolName, sessions: list[Session]) -> ToolStats:
    hourly = [0] * 24
    for s in sessions:
        hourly[s.start_time.hour] += s.total_tokens

    return ToolStats(
        tool=tool,
        sessions_today=len(sessions),
        messages_today=sum(s.message_count for s in sessions),
        tool_calls_today=sum(s.tool_call_count for s in sessions),
        tokens_today=sum(s.total_tokens for s in sessions),
        estimated_cost_today=round(
            sum(s.estimated_cost_usd for s in sessions), 2,
        ),
        status="active" if sessions else "idle",
        hourly_tokens=hourly,
    )


class DemoCollector(BaseCollector):
    """Generates realistic fake data for demos."""

    def __init__(self, tool: ToolName, session_count: int = 80) -> None:
        self._tool = tool
        self._sessions = _make_sessions(tool, session_count)
        self._stats = _make_stats(tool, self._sessions)

    @property
    def tool_name(self) -> ToolName:
        return self._tool

    def is_available(self) -> bool:
        return True

    def collect_events(self) -> list[Event]:
        return []

    def collect_sessions(self) -> list[Session]:
        return self._sessions

    def get_stats(self, days: int = 0) -> ToolStats:
        if days > 0:
            cutoff = datetime.now() - timedelta(days=days)
            filtered = [s for s in self._sessions if s.start_time >= cutoff]
            return _make_stats(self._tool, filtered)
        return self._stats

    def get_model_usage(self) -> dict[str, Any]:
        if self._tool != ToolName.CLAUDE_CODE:
            return {}
        return {k: dict(v) for k, v in DEMO_MODELS.items()}

    def get_daily_history(self, days: int = 30) -> list[dict[str, Any]]:
        _seed("daily-history")
        result = []
        now = datetime.now()
        for d in range(days):
            date = now - timedelta(days=d)
            # Weekdays busier than weekends
            base = 140 if date.weekday() < 5 else 40
            result.append({
                "date": date.strftime("%Y-%m-%d"),
                "messageCount": base + random.randint(-30, 60),
            })
        result.reverse()
        return result

    def get_daily_model_tokens(self) -> list[dict[str, Any]]:
        _seed("daily-model-tokens")
        result = []
        now = datetime.now()
        for d in range(30):
            date = now - timedelta(days=d)
            scale = 1.0 if date.weekday() < 5 else 0.3
            by_model = {
                "claude-opus-4-6-20260301": int(
                    random.randint(150_000, 400_000) * scale,
                ),
                "claude-sonnet-4-6-20260301": int(
                    random.randint(80_000, 250_000) * scale,
                ),
                "claude-haiku-4-5-20251001": int(
                    random.randint(20_000, 80_000) * scale,
                ),
            }
            result.append({
                "date": date.strftime("%Y-%m-%d"),
                "tokensByModel": by_model,
            })
        result.reverse()
        return result

    def get_session_summary(self) -> dict[str, Any]:
        return {
            "totalSessions": len(self._sessions),
            "totalMessages": sum(s.message_count for s in self._sessions),
            "firstSessionDate": (
                self._sessions[-1].start_time.isoformat()
                if self._sessions else None
            ),
            "longestSession": {"messageCount": 312, "duration": 10800000},
        }

    def get_hour_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self._sessions:
            h = str(s.start_time.hour)
            counts[h] = counts.get(h, 0) + 1
        return counts

    def get_feature_config(self) -> dict[str, Any]:
        if self._tool != ToolName.CLAUDE_CODE:
            return {}
        return {
            "agents": 12,
            "commands": 38,
            "rules": 16,
            "skills": 52,
            "plans": 7,
            "hooks": {"preToolUse": 3, "postToolUse": 2},
            "project_memory": True,
            "mcp_servers": 6,
        }


def create_demo_collectors() -> list[tuple[str, DemoCollector]]:
    """Create a full set of demo collectors with realistic distribution."""
    return [
        ("Claude Code", DemoCollector(ToolName.CLAUDE_CODE, session_count=180)),
        ("Cursor", DemoCollector(ToolName.CURSOR, session_count=45)),
        ("Kiro", DemoCollector(ToolName.KIRO, session_count=20)),
        ("Codex", DemoCollector(ToolName.CODEX, session_count=12)),
        ("Copilot", DemoCollector(ToolName.COPILOT, session_count=8)),
    ]
