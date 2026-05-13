"""Lightweight observability for the Calendar Agent backend.

Provides:
- Request logging middleware (method, path, status, duration, request id)
- In-memory metrics counters (total requests, by path, latencies, errors)

State lives in module-level dicts. This is intentionally simple for demo use,
not a production-grade metrics pipeline.
"""
import logging
import sys
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# ---- Logging setup ----

logger = logging.getLogger("calendar_agent")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


# ---- In-memory metrics state ----

_metrics = {
    "total_requests": 0,
    "errors": 0,
    "by_path_count": {},   # path -> int
    "by_path_total_ms": {},  # path -> float (sum of durations)
}

# Tool call metrics (populated by chat_service.execute_tool)
_tool_metrics = {
    "total_tool_calls": 0,
    "by_tool_count": {},   # tool_name -> int
    "by_tool_total_ms": {},  # tool_name -> float
}


def record_tool_call(tool_name: str, duration_ms: float) -> None:
    """Called by chat_service after each tool execution."""
    _tool_metrics["total_tool_calls"] += 1
    _tool_metrics["by_tool_count"][tool_name] = (
        _tool_metrics["by_tool_count"].get(tool_name, 0) + 1
    )
    _tool_metrics["by_tool_total_ms"][tool_name] = (
        _tool_metrics["by_tool_total_ms"].get(tool_name, 0.0) + duration_ms
    )


def get_metrics_snapshot() -> dict:
    """Build a JSON-serializable snapshot of current metrics."""
    avg_latency_by_path = {}
    for path, count in _metrics["by_path_count"].items():
        total_ms = _metrics["by_path_total_ms"].get(path, 0.0)
        avg_latency_by_path[path] = round(total_ms / count, 2) if count else 0.0

    avg_latency_by_tool = {}
    for tool, count in _tool_metrics["by_tool_count"].items():
        total_ms = _tool_metrics["by_tool_total_ms"].get(tool, 0.0)
        avg_latency_by_tool[tool] = round(total_ms / count, 2) if count else 0.0

    return {
        "requests": {
            "total": _metrics["total_requests"],
            "errors": _metrics["errors"],
            "by_path_count": dict(_metrics["by_path_count"]),
            "avg_latency_ms_by_path": avg_latency_by_path,
        },
        "tools": {
            "total_calls": _tool_metrics["total_tool_calls"],
            "by_tool_count": dict(_tool_metrics["by_tool_count"]),
            "avg_latency_ms_by_tool": avg_latency_by_tool,
        },
    }


# ---- Middleware ----

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs each request, records counters, attaches X-Request-Id header."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        req_id = uuid.uuid4().hex[:8]
        start = time.perf_counter()
        path = request.url.path
        method = request.method

        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            # Log the failure then re-raise so FastAPI's normal handlers run
            duration_ms = (time.perf_counter() - start) * 1000
            _metrics["total_requests"] += 1
            _metrics["errors"] += 1
            _metrics["by_path_count"][path] = _metrics["by_path_count"].get(path, 0) + 1
            _metrics["by_path_total_ms"][path] = (
                _metrics["by_path_total_ms"].get(path, 0.0) + duration_ms
            )
            logger.info(
                "[req=%s] %s %s 500 %dms (exception)",
                req_id, method, path, int(duration_ms),
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000

        _metrics["total_requests"] += 1
        if status_code >= 500:
            _metrics["errors"] += 1
        _metrics["by_path_count"][path] = _metrics["by_path_count"].get(path, 0) + 1
        _metrics["by_path_total_ms"][path] = (
            _metrics["by_path_total_ms"].get(path, 0.0) + duration_ms
        )

        response.headers["X-Request-Id"] = req_id
        logger.info(
            "[req=%s] %s %s %d %dms",
            req_id, method, path, status_code, int(duration_ms),
        )
        return response
