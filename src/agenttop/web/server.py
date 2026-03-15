"""FastAPI web server for the agenttop dashboard."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agenttop.collectors.base import BaseCollector
from agenttop.collectors.claude import ClaudeCodeCollector
from agenttop.collectors.codex import CodexCollector
from agenttop.collectors.copilot import CopilotCollector
from agenttop.collectors.cursor import CursorCollector
from agenttop.collectors.kiro import KiroCollector
from agenttop.config import Config, load_config
from agenttop.web.graph_builder import GraphBuilder

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="agenttop", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
_config: Config | None = None
_collectors: list[tuple[str, BaseCollector]] = []
_claude: ClaudeCodeCollector | None = None
_cached_optimize: dict[str, Any] | None = None
_cached_optimize_time: float = 0.0
_optimize_running = False
_CACHE_TTL_SECONDS = 300  # 5-minute cache TTL


def _init() -> None:
    """Initialize config and collectors (lazy, once)."""
    global _config, _collectors, _claude
    if _config is not None:
        return
    _config = load_config()
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


@app.get("/api/sessions")
def api_sessions(days: int = 7) -> JSONResponse:
    _init()
    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(days=days) if days > 0 else datetime(2000, 1, 1)
    sessions = []
    for _, collector in _collectors:
        if not collector.is_available():
            continue
        for s in collector.collect_sessions():
            if s.start_time >= cutoff:
                sessions.append(s.model_dump(mode="json"))
    sessions.sort(key=lambda x: x["start_time"], reverse=True)
    return JSONResponse(sessions[:200])


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


class OptimizeRequest(BaseModel):
    days: int = 0


def _run_optimize(days: int = 0) -> dict[str, Any]:
    """Run optimizer analysis (blocking). Used by both startup and endpoint."""
    _init()
    from agenttop.web.optimizer import AIUsageOptimizer

    stats = _get_all_stats(days)
    sessions = []
    feature_configs: dict[str, Any] = {}
    for _, collector in _collectors:
        if collector.is_available():
            sessions.extend(collector.collect_sessions())
            fc = collector.get_feature_config()
            if fc:
                tool_id = collector.tool_name.value
                feature_configs[tool_id] = fc
    model_usage = {}
    if _claude and _claude.is_available():
        model_usage = _claude.get_model_usage()

    optimizer = AIUsageOptimizer(_config, claude_collector=_claude)
    return optimizer.analyze(stats, sessions, model_usage, feature_configs)


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
            result = await asyncio.get_event_loop().run_in_executor(
                None, _run_optimize,
            )
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

    # If startup precompute is still running, wait for it (up to 90s)
    if req.days == 0 and _optimize_running:
        for _ in range(180):
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
            timeout=90.0,
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
        _cached_optimize = result
        _cached_optimize_time = time.time()
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


# --- Static files and SPA fallback ---

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> FileResponse:
    """Serve index.html for all non-API routes (SPA fallback)."""
    return FileResponse(str(STATIC_DIR / "index.html"))
