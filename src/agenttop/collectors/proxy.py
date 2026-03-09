"""Local HTTP proxy collector for generic AI tool token capture.

Sits between the AI tool and the real API. Captures request/response
metadata (token counts, latency, model) without modifying the data.

Usage:
  Set ANTHROPIC_BASE_URL=http://localhost:9120/v1 etc. in your tool config.
  The proxy forwards all requests to the real API transparently.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

import httpx

from agenttop.collectors.base import BaseCollector
from agenttop.config import ProxyConfig
from agenttop.models import Event, Session, ToolName, ToolStats

# Known API base URLs
DEFAULT_FORWARD_URLS = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com",
}


class ProxyCollector(BaseCollector):
    """Collects data by acting as a local API proxy."""

    def __init__(self, config: ProxyConfig | None = None) -> None:
        self._config = config or ProxyConfig()
        self._events: list[Event] = []
        self._forward_urls = {**DEFAULT_FORWARD_URLS, **(self._config.forward_urls or {})}

    @property
    def tool_name(self) -> ToolName:
        return ToolName.GENERIC

    def is_available(self) -> bool:
        return self._config.enabled

    def collect_events(self) -> list[Event]:
        events = list(self._events)
        self._events.clear()
        return events

    def collect_sessions(self) -> list[Session]:
        return []

    def get_stats(self, days: int = 0) -> ToolStats:
        stats = ToolStats(tool=ToolName.GENERIC)
        if self._config.enabled:
            stats.status = "active"
        return stats

    def record_event(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
    ) -> None:
        """Record a proxied API call."""
        total_tokens = input_tokens + output_tokens
        # Rough cost estimation
        cost = total_tokens * 0.000003  # ~$3/M tokens average
        self._events.append(
            Event(
                tool=ToolName.GENERIC,
                event_type="api_call",
                timestamp=datetime.now(),
                data={
                    "provider": provider,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "latency_ms": latency_ms,
                },
                token_count=total_tokens,
                cost_usd=cost,
            )
        )


async def run_proxy(config: ProxyConfig, collector: ProxyCollector) -> None:
    """Run the HTTP proxy server using raw asyncio (no external framework needed)."""
    forward_urls = {**DEFAULT_FORWARD_URLS, **(config.forward_urls or {})}

    async def handle_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            # Read the HTTP request
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return

            request_str = request_line.decode("utf-8", errors="replace").strip()
            method, path, _ = request_str.split(" ", 2)

            # Read headers
            headers: dict[str, str] = {}
            while True:
                line = await reader.readline()
                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    break
                key, _, value = line_str.partition(":")
                headers[key.strip().lower()] = value.strip()

            # Read body if present
            body = b""
            content_length = int(headers.get("content-length", "0"))
            if content_length > 0:
                body = await reader.readexactly(content_length)

            # Determine provider from path
            provider = "unknown"
            target_base = ""
            for p, url in forward_urls.items():
                if f"/{p}" in path or p in headers.get("host", ""):
                    provider = p
                    target_base = url
                    path = path.replace(f"/{p}", "")
                    break

            if not target_base:
                # Default to first configured forward URL
                if forward_urls:
                    provider = next(iter(forward_urls))
                    target_base = forward_urls[provider]

            # Forward request
            start = time.monotonic()
            async with httpx.AsyncClient() as client:
                forward_headers = {
                    k: v
                    for k, v in headers.items()
                    if k not in ("host", "content-length", "transfer-encoding")
                }
                resp = await client.request(
                    method=method,
                    url=f"{target_base}{path}",
                    headers=forward_headers,
                    content=body,
                    timeout=120.0,
                )
            latency_ms = (time.monotonic() - start) * 1000

            # Extract token usage from response
            input_tokens = 0
            output_tokens = 0
            model = "unknown"
            try:
                resp_json = resp.json()
                usage = resp_json.get("usage", {})
                input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
                output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0))
                model = resp_json.get("model", "unknown")
            except Exception:
                pass

            collector.record_event(provider, model, input_tokens, output_tokens, latency_ms)

            # Send response back
            status_line = f"HTTP/1.1 {resp.status_code} OK\r\n"
            writer.write(status_line.encode())
            for k, v in resp.headers.items():
                if k.lower() not in ("transfer-encoding",):
                    writer.write(f"{k}: {v}\r\n".encode())
            writer.write(b"\r\n")
            writer.write(resp.content)
            await writer.drain()
        except Exception:
            try:
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle_request, "127.0.0.1", config.port)
    async with server:
        await server.serve_forever()
