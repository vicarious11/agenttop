"""FastAPI web server for the agenttop dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agenttop.collectors.base import BaseCollector
from agenttop.collectors.claude import ClaudeCodeCollector
from agenttop.collectors.codex import CodexCollector
from agenttop.collectors.copilot import CopilotCollector
from agenttop.collectors.cursor import CursorCollector
from agenttop.collectors.kiro import KiroCollector
from agenttop.config import Config, load_config
from agenttop.formatting import check_budget
from agenttop.web.graph_builder import GraphBuilder
from agenttop.workflow import (
    SessionCorrelator,
    WorkflowAnalyzer,
    get_all_tool_names,
)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="agenttop", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8420", "http://localhost:8420"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# Global state
_config: Config | None = None
_collectors: list[tuple[str, BaseCollector]] = []
_claude: ClaudeCodeCollector | None = None
_cached_optimize: dict[str, Any] | None = None
_cached_optimize_time: float = 0.0
_optimize_running = False
_CACHE_TTL_SECONDS = 300  # 5-minute cache TTL


_demo_mode = False


def enable_demo_mode() -> None:
    """Switch to demo collectors with fake data."""
    global _demo_mode
    _demo_mode = True


def _init() -> None:
    """Initialize config and collectors (lazy, once)."""
    global _config, _collectors, _claude
    if _config is not None:
        return
    _config = load_config()

    if _demo_mode:
        from agenttop.collectors.demo import create_demo_collectors

        _collectors = create_demo_collectors()
        _claude = _collectors[0][1]  # type: ignore[assignment]
        return

    _claude = ClaudeCodeCollector(_config.claude_dir)
    _collectors = [
        ("Claude Code", _claude),
        ("Cursor", CursorCollector(_config.cursor_dir)),
        ("Kiro", KiroCollector(_config.kiro_dir)),
        ("Codex", CodexCollector()),
        ("Copilot", CopilotCollector()),
    ]


def _get_all_stats(days: int = 0) -> list[dict[str, Any]]:
    """Collect stats from all available collectors."""
    _init()
    results = []
    for name, collector in _collectors:
        if not collector.is_available():
            continue
        s = collector.get_stats(days=days)
        d = s.model_dump()
        d["display_name"] = name
        results.append(d)
    return results


# --- API endpoints ---


@app.get("/api/graph")
def api_graph(days: int = 0) -> JSONResponse:
    _init()
    builder = GraphBuilder(_collectors, _claude, days=days)
    return JSONResponse(builder.build())


@app.get("/api/stats")
def api_stats(days: int = 0) -> JSONResponse:
    return JSONResponse(_get_all_stats(days))


def _collect_all_sessions(days: int = 7) -> list:
    """Collect sessions from all available collectors within time window."""
    _init()
    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(days=days) if days > 0 else datetime(2000, 1, 1)
    sessions = []
    for _, collector in _collectors:
        if not collector.is_available():
            continue
        for s in collector.collect_sessions():
            if s.start_time >= cutoff:
                sessions.append(s)
    return sessions


def _build_session_index() -> dict[str, Any]:
    """Build a session ID -> Session mapping for O(1) lookups."""
    index: dict[str, Any] = {}
    for _, collector in _collectors:
        if not collector.is_available():
            continue
        for s in collector.collect_sessions():
            index[s.id] = s
    return index


@app.get("/api/sessions")
def api_sessions(days: int = 7) -> JSONResponse:
    sessions = _collect_all_sessions(days)
    result = [s.model_dump(mode="json") for s in sessions]
    result.sort(key=lambda x: x["start_time"], reverse=True)
    return JSONResponse(result)


@app.get("/api/sessions/{session_id}")
def api_session_detail(session_id: str) -> JSONResponse:
    """Get full session detail including prompts."""
    _init()
    # Validate session_id format
    if not session_id or len(session_id) > 128 or not re.match(r"^[\w\-]+$", session_id):
        return JSONResponse({"error": "Invalid session ID"}, status_code=400)
    index = _build_session_index()
    session = index.get(session_id)
    if session:
        return JSONResponse(session.model_dump(mode="json"))
    return JSONResponse({"error": "Session not found"}, status_code=404)



@app.get("/api/models")
def api_models() -> JSONResponse:
    _init()
    if _claude and _claude.is_available():
        return JSONResponse(_claude.get_model_usage())
    return JSONResponse({})


@app.get("/api/hours")
def api_hours(days: int = 0) -> JSONResponse:
    """Aggregate hourly token counts from ALL available tools."""
    _init()
    merged: dict[str, int] = {}
    for _, collector in _collectors:
        if not collector.is_available():
            continue
        stats = collector.get_stats(days=days)
        for hour, tokens in enumerate(stats.hourly_tokens):
            if tokens > 0:
                merged[str(hour)] = merged.get(str(hour), 0) + tokens
    return JSONResponse(merged)


@app.get("/api/budget")
def api_budget(days: int = 0) -> JSONResponse:
    """Get budget status for the current period."""
    _init()
    stats = _get_all_stats(days)
    total_cost = sum(s.get("estimated_cost_today", 0.0) for s in stats)

    # Budget only applies to today (days=1)
    if days == 1:
        budget = _config.llm.max_budget_per_day
        budget_info = check_budget(total_cost, budget)

        return JSONResponse({
            "enabled": budget > 0,
            "budget": budget,
            "total_cost": total_cost,
            "ratio": budget_info.ratio,
            "remaining": budget_info.remaining,
            "status": budget_info.status.value,  # Use .value to get string instead of enum
        })

    return JSONResponse({
        "enabled": False,
        "budget": 0.0,
        "total_cost": total_cost,
        "ratio": 0.0,
        "remaining": 0.0,
        "status": "ok",
    })


# --- Workflow Intelligence API ---


@app.get("/api/workflow/chains")
def api_workflow_chains(days: int = 7, gap_minutes: int = 30) -> JSONResponse:
    """Get workflow chains - correlated sessions across tools."""
    sessions = _collect_all_sessions(days)

    if not sessions:
        return JSONResponse({"chains": [], "total": 0})

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions, max_gap_minutes=gap_minutes)

    # Convert to JSON-serializable format
    chains_data = []
    for chain in chains:
        chains_data.append({
            "id": chain.id,
            "session_ids": chain.session_ids,
            "tools": chain.tools,
            "start_time": chain.start_time,
            "end_time": chain.end_time,
            "project": chain.project,
            "total_tokens": chain.total_tokens,
            "total_cost": chain.total_cost,
            "efficiency_score": chain.efficiency_score,
            "pattern_type": chain.pattern_type,
        })

    return JSONResponse({"chains": chains_data, "total": len(chains_data)})


@app.get("/api/workflow/patterns")
def api_workflow_patterns(days: int = 7, offset: int = 0) -> JSONResponse:
    """Detect workflow patterns from recent sessions.

    Args:
        days: Number of days to look back
        offset: Day offset (0 for current period, 7 for previous week, etc.)
    """
    _init()
    from datetime import datetime, timedelta

    # Calculate cutoff with offset for historical comparison
    end_date = datetime.now() - timedelta(days=offset)
    cutoff = end_date - timedelta(days=days) if days > 0 else datetime(2000, 1, 1)
    sessions = []
    for _, collector in _collectors:
        if not collector.is_available():
            continue
        for s in collector.collect_sessions():
            # Filter sessions within the time range [cutoff, end_date]
            if s.start_time >= cutoff and s.start_time < end_date:
                sessions.append(s)

    if not sessions:
        return JSONResponse({"patterns": [], "total": 0})

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    analyzer = WorkflowAnalyzer()
    analysis = analyzer.analyze_chains(chains, transitions)

    patterns_data = []
    for pattern in analysis.get("patterns", []):
        patterns_data.append({
            "name": pattern.name,
            "description": pattern.description,
            "tool_sequence": pattern.tool_sequence,
            "frequency": pattern.frequency,
            "avg_efficiency": round(pattern.avg_efficiency, 2),
            "avg_tokens": pattern.avg_tokens,
            "avg_cost": round(pattern.avg_cost, 2),
            "typical_duration_minutes": round(pattern.typical_duration_minutes, 1),
        })

    # Convert metrics dataclass to dict using dataclasses.asdict
    import dataclasses as _dc
    metrics_data = _dc.asdict(analysis.get("metrics")) if analysis.get("metrics") else None

    return JSONResponse({
        "patterns": patterns_data,
        "total": len(patterns_data),
        "metrics": metrics_data,
    })


@app.get("/api/workflow/recommendations")
def api_workflow_recommendations(days: int = 7, task_type: str | None = None) -> JSONResponse:
    """Get workflow recommendations based on usage patterns."""
    _init()
    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(days=days) if days > 0 else datetime(2000, 1, 1)
    sessions = []
    available_tools = set()
    for name, collector in _collectors:
        if not collector.is_available():
            continue
        available_tools.add(name.lower().replace(" ", "_"))
        for s in collector.collect_sessions():
            if s.start_time >= cutoff:
                sessions.append(s)

    if not sessions:
        return JSONResponse({"recommendations": [], "available_tools": list(available_tools)})

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    analyzer = WorkflowAnalyzer()
    analysis = analyzer.analyze_chains(chains, transitions)

    recommendations = analysis.get("recommendations", [])

    # If task_type specified, add specific recommendation
    if task_type:
        task_rec = analyzer.get_task_based_recommendation(task_type, list(available_tools))
        if task_rec:
            recommendations.insert(0, {
                "type": "task_specific",
                "task_type": task_type,
                "primary_tool": task_rec.primary_tool,
                "secondary_tools": task_rec.secondary_tools,
                "avoid_tools": task_rec.avoid_tools,
                "rationale": task_rec.rationale,
                "estimated_efficiency_gain": task_rec.estimated_efficiency_gain,
            })

    return JSONResponse({
        "recommendations": recommendations,
        "available_tools": list(available_tools),
    })


@app.get("/api/workflow/switching-costs")
def api_workflow_switching_costs(days: int = 7) -> JSONResponse:
    """Analyze tool switching costs and context loss."""
    _init()
    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(days=days) if days > 0 else datetime(2000, 1, 1)
    sessions = []
    for _, collector in _collectors:
        if not collector.is_available():
            continue
        for s in collector.collect_sessions():
            if s.start_time >= cutoff:
                sessions.append(s)

    if not sessions:
        return JSONResponse({
            "switching_costs": {},
            "transition_analysis": {},
            "known_tools": get_all_tool_names(),
        })

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    analyzer = WorkflowAnalyzer()
    switching_analysis = analyzer.measure_switching_costs(transitions)

    return JSONResponse({
        "switching_costs": switching_analysis,
        "transition_count": len(transitions),
        "known_tools": get_all_tool_names(),
    })


@app.get("/api/workflow/tool-combinations")
def api_workflow_tool_combinations(days: int = 7) -> JSONResponse:
    """Analyze effectiveness of different tool combinations."""
    _init()
    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(days=days) if days > 0 else datetime(2000, 1, 1)
    sessions = []
    for _, collector in _collectors:
        if not collector.is_available():
            continue
        for s in collector.collect_sessions():
            if s.start_time >= cutoff:
                sessions.append(s)

    if not sessions:
        return JSONResponse({"combinations": {}, "total_chains": 0})

    correlator = SessionCorrelator()
    chains = correlator.correlate_by_time(sessions)
    transitions = correlator.detect_tool_transitions(chains, sessions)

    analyzer = WorkflowAnalyzer()
    # Calculate efficiency scores for each chain
    for chain in chains:
        chain.efficiency_score = analyzer._calculate_chain_efficiency(chain, transitions)

    combinations = analyzer.analyze_tool_combinations(chains)

    return JSONResponse({
        "combinations": combinations,
        "total_chains": len(chains),
    })


class OptimizeRequest(BaseModel):
    days: int = 0

class AnalyzeSessionsRequest(BaseModel):
    session_ids: list[str] = Field(..., max_length=100)



def _run_optimize(
    days: int = 0,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """Run optimizer analysis (blocking).

    Collects sessions FIRST to prime the collector cache, then calls
    stats/model_usage which hit cached data (no redundant JSONL parsing).
    """
    _init()
    from agenttop.web.optimizer import AIUsageOptimizer

    # 1. Collect sessions first (primes Claude's internal cache)
    sessions: list = []
    feature_configs: dict[str, Any] = {}
    for _, collector in _collectors:
        if collector.is_available():
            sessions.extend(collector.collect_sessions())
            fc = collector.get_feature_config()
            if fc:
                feature_configs[collector.tool_name.value] = fc

    # 2. Now stats and model_usage hit cached data (no re-parse)
    stats = _get_all_stats(days)
    model_usage = _claude.get_model_usage() if _claude and _claude.is_available() else {}

    optimizer = AIUsageOptimizer(_config, claude_collector=_claude)
    return optimizer.analyze(
        stats, sessions, model_usage, feature_configs,
        on_progress=on_progress,
    )


@app.on_event("startup")
async def _startup_tasks() -> None:
    """Run LLM analysis + KB refresh at boot (non-blocking)."""
    global _cached_optimize, _cached_optimize_time, _optimize_running

    # Background: refresh knowledge base (daily, graceful if offline)
    async def _kb_refresh_loop() -> None:
        from agenttop.web import kb_refresh
        from agenttop.web.optimizer import KNOWLEDGE_BASE

        while True:
            try:
                updated = await kb_refresh.refresh_kb(KNOWLEDGE_BASE)
                if updated is not KNOWLEDGE_BASE:
                    KNOWLEDGE_BASE.update(updated)
                    logging.info("Knowledge base refreshed with %d tools", len(updated))
            except Exception as e:
                logging.debug("KB refresh failed (will retry): %s", e)
            await asyncio.sleep(kb_refresh.REFRESH_INTERVAL)

    asyncio.create_task(_kb_refresh_loop())

    # Background: precompute optimizer result
    async def _bg() -> None:
        global _cached_optimize, _cached_optimize_time, _optimize_running
        _optimize_running = True
        try:
            import time
            result = await asyncio.get_event_loop().run_in_executor(
                None, _run_optimize,
            )
            _cached_optimize_time = time.time()
            _cached_optimize = result
        except Exception as e:
            logging.error("Optimizer precompute failed: %s", e, exc_info=True)
            _cached_optimize = {
                "error": f"Precompute failed: {e}",
                "source": "error",
            }
        finally:
            _optimize_running = False

    asyncio.create_task(_bg())


@app.post("/api/optimize")
async def api_optimize(req: OptimizeRequest) -> JSONResponse:
    global _cached_optimize, _cached_optimize_time
    import time

    # Return cached result if fresh (within TTL) and not an error
    cache_age = time.time() - _cached_optimize_time
    if (
        req.days == 0
        and _cached_optimize is not None
        and "error" not in _cached_optimize
        and cache_age < _CACHE_TTL_SECONDS
    ):
        return JSONResponse(_cached_optimize)

    # If startup precompute is still running, wait for it (up to 180s)
    if req.days == 0 and _optimize_running:
        for _ in range(360):
            await asyncio.sleep(0.5)
            if not _optimize_running:
                break
        if (
            _cached_optimize is not None
            and "error" not in _cached_optimize
        ):
            return JSONResponse(_cached_optimize)
        # Precompute failed — fall through to fresh analysis

    # Run fresh analysis (retries if previous result was an error)
    try:
        result = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None, _run_optimize, req.days,
            ),
            timeout=180.0,
        )
    except asyncio.TimeoutError:
        return JSONResponse({
            "error": "Analysis timed out. Check your LLM provider.",
            "source": "error",
        })
    except Exception as e:
        return JSONResponse({
            "error": f"Optimizer crashed: {e}",
            "source": "error",
        })
    if req.days == 0 and "error" not in result:
        _cached_optimize_time = time.time()
        _cached_optimize = result
    return JSONResponse(result)


@app.get("/api/optimize-stream")
async def api_optimize_stream(days: int = 0) -> StreamingResponse:
    """SSE endpoint — streams progress during MAP phase, then final JSON result."""
    import queue
    import threading
    import time

    # Return cached result immediately if fresh (skip full pipeline)
    if days == 0 and _cached_optimize and "error" not in _cached_optimize:
        cache_age = time.time() - _cached_optimize_time
        if cache_age < _CACHE_TTL_SECONDS:

            async def _cached_stream():  # noqa: ANN202
                yield f"event: result\ndata: {json.dumps(_cached_optimize, default=str)}\n\n"

            return StreamingResponse(
                _cached_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

    progress_q: queue.Queue[str | None] = queue.Queue()

    def _on_progress(phase: str, current: int, total: int) -> None:
        """Called from the optimizer thread with progress updates."""
        msg = json.dumps({"phase": phase, "current": current, "total": total})
        progress_q.put(f"event: progress\ndata: {msg}\n\n")

    async def _event_stream():  # noqa: ANN202
        """Yield SSE events: progress updates, then final result."""
        result_holder: list[dict[str, Any]] = []
        error_holder: list[str] = []

        def _thread_target() -> None:
            try:
                result_holder.append(_run_optimize(days, on_progress=_on_progress))
            except Exception as e:
                error_holder.append(str(e))
            finally:
                progress_q.put(None)  # sentinel

        thread = threading.Thread(target=_thread_target, daemon=True)
        thread.start()

        # Stream progress events until optimizer finishes
        while True:
            try:
                msg = await asyncio.get_event_loop().run_in_executor(
                    None, progress_q.get, True, 1.0,
                )
            except Exception:
                # queue.get timeout — keep waiting
                if not thread.is_alive():
                    break
                continue
            if msg is None:
                break
            yield msg

        # Send final result
        if error_holder:
            data = json.dumps({"error": error_holder[0], "source": "error"})
        elif result_holder:
            data = json.dumps(result_holder[0], default=str)
            # Cache the result (runs on event loop thread — safe)
            global _cached_optimize, _cached_optimize_time
            if days == 0 and "error" not in result_holder[0]:
                # Assign time first so readers never see new result with old timestamp
                _cached_optimize_time = time.time()
                _cached_optimize = result_holder[0]
        else:
            data = json.dumps({"error": "No result", "source": "error"})

        yield f"event: result\ndata: {data}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )




@app.post("/api/analyze-sessions")
async def api_analyze_sessions(req: AnalyzeSessionsRequest) -> JSONResponse:
    """Analyze user-selected sessions via the optimizer pipeline."""
    if not req.session_ids:
        return JSONResponse({"error": "No session IDs provided"}, status_code=400)

    _init()
    from agenttop.web.optimizer import AIUsageOptimizer

    # Collect all sessions, filter to requested IDs
    requested = set(req.session_ids)
    selected_sessions: list = []
    feature_configs: dict[str, Any] = {}
    for _, collector in _collectors:
        if collector.is_available():
            for s in collector.collect_sessions():
                if s.id in requested:
                    selected_sessions.append(s)
            fc = collector.get_feature_config()
            if fc:
                feature_configs[collector.tool_name.value] = fc

    if not selected_sessions:
        return JSONResponse({"error": "No matching sessions found"}, status_code=404)

    stats = _get_all_stats(0)
    model_usage = _claude.get_model_usage() if _claude and _claude.is_available() else {}

    optimizer = AIUsageOptimizer(_config, claude_collector=_claude)
    try:
        result = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None, optimizer.analyze, stats, selected_sessions,
                model_usage, feature_configs,
            ),
            timeout=300.0,
        )
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Analysis timed out"}, status_code=504)
    except Exception as e:
        return JSONResponse({"error": f"Analysis failed: {e}"}, status_code=500)

    return JSONResponse(result)

# --- KB refresh manual trigger ---


@app.post("/api/kb-refresh")
async def api_kb_refresh() -> JSONResponse:
    """Manually trigger knowledge base refresh."""
    from agenttop.web import kb_refresh
    from agenttop.web.optimizer import KNOWLEDGE_BASE

    try:
        updated = await kb_refresh.refresh_kb(KNOWLEDGE_BASE)
        new_count = sum(len(t.get("features", [])) for t in updated.values())
        return JSONResponse({
            "status": "ok",
            "tools": len(updated),
            "total_features": new_count,
        })
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})


# --- WebSocket for real-time updates ---

_ws_clients: set[WebSocket] = set()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    _ws_clients.add(ws)
    client_days = 0  # Default to all-time; client can update via message
    try:
        while True:
            # Check if client sent a days preference (non-blocking)
            import asyncio as _aio

            try:
                msg = await _aio.wait_for(ws.receive_text(), timeout=5.0)
                try:
                    client_days = int(msg)
                except ValueError:
                    pass
            except _aio.TimeoutError:
                pass

            stats = _get_all_stats(days=client_days)
            totals = {
                "tokens": sum(s.get("tokens_today", 0) for s in stats),
                "cost": sum(s.get("estimated_cost_today", 0.0) for s in stats),
                "sessions": sum(s.get("sessions_today", 0) for s in stats),
                "messages": sum(s.get("messages_today", 0) for s in stats),
                "tools": stats,
            }
            await ws.send_json(totals)
    except WebSocketDisconnect:
        _ws_clients.discard(ws)
    except Exception as e:
        logging.error("WebSocket error: %s", e, exc_info=True)
        _ws_clients.discard(ws)


# --- Selective Session Analysis ---


# --- Static files and SPA fallback ---

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> FileResponse:
    """Serve index.html for all non-API routes (SPA fallback)."""
    return FileResponse(str(STATIC_DIR / "index.html"))
