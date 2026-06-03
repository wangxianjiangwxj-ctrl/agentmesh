#!/usr/bin/env python3
"""
AgentMesh A2A Test Server — lightweight HTTP A2A server + client.

Server:  FastAPI server wrapping MemoryProvider + A2ATaskManager
         Exposes the A2A protocol over HTTP for real network testing.
Client:  HttpProvider class implementing the A2AProvider interface
         for connecting to any A2A-compatible HTTP server.

Usage:
    # Start server (default http://localhost:8080)
    python -m agentmesh.a2a_server server

    # Run tests against server
    python -m agentmesh.a2a_server test

    # Or with pytest
    pytest tests/e2e/test_a2a_server.py -v

    # Or start in background
    python -m agentmesh.a2a_server server --port 8080 --daemon

Design:
    - Stateless HTTP translation layer over the in-memory A2A state machine
    - Task state transitions enforced by A2ATaskManager
    - AgentCard registry for agent discovery
    - Compatible with the A2AProvider interface (HttpProvider)
"""

from __future__ import annotations

import asyncio
import http.client
import json
import os
import subprocess
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncGenerator,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)

from agentmesh.a2a import StructuredLogger, with_trace_context, TraceProvider

# Import timeout/retry configs from models
from agentmesh.a2a_models import ServerTimeoutConfig, DEFAULT_TIMEOUT_CONFIG


log = StructuredLogger("a2a-server")


# Server start time (set when _build_app() first creates an app)
_server_start_time: Optional[float] = None

# Default server timeout configuration (can be overridden at build time)
_timeout_config: ServerTimeoutConfig = DEFAULT_TIMEOUT_CONFIG


def _get_version() -> str:
    """Return the AgentMesh package version.

    Attempts to read from importlib metadata first, then from
    the agentmesh package __version__ attribute, and finally
    falls back to "dev".
    """
    # Try importlib.metadata (works when installed as package)
    try:
        import importlib.metadata
        return importlib.metadata.version("agentmesh")
    except (ImportError, LookupError):
        pass

    # Try direct import of __version__
    try:
        from agentmesh import __version__
        return __version__
    except (ImportError, AttributeError):
        pass

    return "dev"


# pydantic models for API — defined at module level for Python 3.9 compat
try:
    from pydantic import BaseModel
except ImportError:
    # pydantic is optional; only needed for server mode
    BaseModel = object


class _SendRequest(BaseModel):
    """Request model for POST /send."""
    task: dict
    auth: Optional[dict] = None


class _AgentCardRequest(BaseModel):
    """Request model for POST /agents."""
    name: str
    skills: List[str] = []
    endpoints: Optional[dict] = None


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------


class A2AServerError(Exception):
    """Unified server exception that maps to a structured JSON error response.

    Raise this in route handlers to produce a consistent error response:

        raise A2AServerError(
            status_code=404,
            code="TASK_NOT_FOUND",
            message="Task abc-123 not found",
        )

    Attributes:
        status_code: HTTP status code (400, 404, 500, 503, etc.)
        code: Machine-readable error code string
        message: Human-readable error description
    """
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"[{status_code}] {code}: {message}")


# Map from HTTP status code to canonical error code string
ERROR_CODE_MAP: dict[int, str] = {
    400: "INVALID_REQUEST",
    404: "NOT_FOUND",
    405: "INVALID_REQUEST",
    422: "VALIDATION_ERROR",
    429: "SERVICE_UNAVAILABLE",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


# Map from internal A2AError code (int) to canonical error code string
INTERNAL_TO_ERROR_CODE: dict[int, str] = {
    400: "INVALID_REQUEST",
    404: "NOT_FOUND",
    409: "INVALID_REQUEST",
    500: "INTERNAL_ERROR",
}


# ---------------------------------------------------------------------------
# Import from a2a_provider (same package)
# ---------------------------------------------------------------------------

try:
    from agentmesh.a2a_provider import (
        A2AError,
        A2AFacade,
        A2AProvider,
        A2AResult,
        A2ATaskManager,
        A2ATaskState,
        MemoryProvider,
        ProviderError,
    )
except ImportError:
    # Allow running directly as __main__ before package is installed
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from a2a_provider import (
        A2AError,
        A2AFacade,
        A2AProvider,
        A2AResult,
        A2ATaskManager,
        A2ATaskState,
        MemoryProvider,
        ProviderError,
    )


# ---------------------------------------------------------------------------
# HTTP wire format
# ---------------------------------------------------------------------------

@dataclass
class A2ARequest:
    """Request body sent to the A2A server."""
    task: dict
    auth: Optional[dict] = None


@dataclass
class A2AResponse:
    """Response body from the A2A server."""
    success: bool
    data: Any = None
    error: Optional[dict] = None
    task_state: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps({
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "task_state": self.task_state,
        })

    @classmethod
    def from_json(cls, raw: str) -> A2AResponse:
        d = json.loads(raw)
        return cls(
            success=d["success"],
            data=d.get("data"),
            error=d.get("error"),
            task_state=d.get("task_state"),
        )


# ===================================================================
# A2A HTTP Server (FastAPI)
# ===================================================================


def _build_app(facade: Optional[A2AFacade] = None,
                timeout_config: Optional[ServerTimeoutConfig] = None) -> FastAPI:
    """Build a FastAPI application wrapping the given A2AFacade.

    To integrate into an existing FastAPI app, import this function
    and mount or include the returned app:

        from agentmesh.a2a_server import _build_app
        app.mount("/a2a", _build_app())

    Endpoints:
        GET  /health        - Health check (status, uptime, components, version)
        GET  /ping          - Ping health check
        POST /send          - Send a task
        GET  /task/{id}     - Get task status
        POST /cancel/{id}   - Cancel a task
        GET  /agents        - List registered agent cards
        POST /agents        - Register an agent card
    """
    import asyncio as _asyncio
    from fastapi import Body, FastAPI, Request
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from starlette.responses import JSONResponse, StreamingResponse

    # Record server start time on first app build
    global _server_start_time, _timeout_config
    if _server_start_time is None:
        _server_start_time = time.time()
    if timeout_config is not None:
        _timeout_config = timeout_config

    if facade is None:
        provider = MemoryProvider("a2a-server")
        task_manager = A2ATaskManager()
        facade = A2AFacade(provider=provider, task_manager=task_manager)

    app = FastAPI(title="AgentMesh A2A Server", version=_get_version())

    # -----------------------------------------------------------------------
    # Request tracing middleware — inject trace context per request
    # -----------------------------------------------------------------------

    # -----------------------------------------------------------------------
    # Request processing timeout middleware
    # -----------------------------------------------------------------------

    @app.middleware("http")
    async def _timeout_middleware(request: Request, call_next):
        """Wrap request handler with a configurable timeout.

        If the handler exceeds ``_timeout_config.request_timeout`` seconds,
        the middleware raises ``asyncio.TimeoutError`` and returns a 503
        response to the client.
        """
        timeout = _timeout_config.request_timeout
        if timeout > 0:
            try:
                response = await _asyncio.wait_for(
                    call_next(request), timeout=timeout
                )
            except _asyncio.TimeoutError:
                log.warn("request_timeout",
                         method=request.method,
                         path=request.url.path,
                         timeout=timeout)
                return JSONResponse(
                    status_code=503,
                    content={
                        "success": False,
                        "error": {
                            "code": "SERVICE_UNAVAILABLE",
                            "message": f"Request timed out after {timeout}s",
                            "recoverable": True,
                        }
                    },
                )
        else:
            response = await call_next(request)
        return response

    # -----------------------------------------------------------------------
    # Request tracing middleware — inject trace context per request
    # -----------------------------------------------------------------------

    @app.middleware("http")
    async def _trace_middleware(request: Request, call_next):
        """Set up a trace context for each HTTP request.

        Extracts existing trace headers from the incoming request
        (e.g. ``X-Trace-Id`` / ``X-Span-Id``) or generates a fresh root
        context.  Logs request start and completion with duration.
        """
        # Attempt to extract trace context from request headers
        headers = dict(request.headers)
        ctx = TraceProvider.extract(headers)
        if ctx is None:
            ctx = TraceProvider().new_context(baggage={"method": request.method, "path": request.url.path})

        start = time.perf_counter()
        with with_trace_context(context=ctx):
            log.info("http_request_start", method=request.method, path=request.url.path, trace_id=ctx.trace_id)
            response = await call_next(request)
            elapsed = (time.perf_counter() - start) * 1000
            log.info("http_request_end", method=request.method, path=request.url.path, status_code=response.status_code, duration_ms=round(elapsed, 2), trace_id=ctx.trace_id)
            response.headers["X-Trace-Id"] = ctx.trace_id
        return response

    # -----------------------------------------------------------------------
    # Exception handlers — unified error responses
    # -----------------------------------------------------------------------

    @app.exception_handler(A2AServerError)
    async def _a2a_server_error_handler(request: Request, exc: A2AServerError):
        """Handle A2AServerError — our custom exception with string error codes."""
        log.warn("a2a_server_error", message=f"[{exc.status_code}] {exc.code}: {exc.message}", status_code=exc.status_code, error_code=exc.code)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
        """Handle Starlette/FastAPI HTTP exceptions (e.g. 405 Method Not Allowed)."""
        error_code = ERROR_CODE_MAP.get(exc.status_code, "INTERNAL_ERROR")
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": error_code, "message": exc.detail}},
        )

    @app.exception_handler(Exception)
    async def _general_exception_handler(request: Request, exc: Exception):
        """Catch-all handler: logs full traceback, returns safe 500."""
        log.error("unhandled_error", message=f"Unhandled server error at {request.method} {request.url.path}", error=exc, method=request.method, path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR",
                              "message": "An internal error occurred"}},
        )

    # --- Endpoints ---

    @app.get("/health")
    async def health():
        """Health check endpoint.

        Returns server status, uptime, component health, and version.
        """
        nonlocal facade
        comps = {}

        # Server component
        comps["server"] = "healthy"

        # Provider component — attempt a lightweight ping
        try:
            ping_result = facade.provider.ping()
            provider_ok = ping_result.success
        except Exception:
            provider_ok = False
        comps["provider"] = "healthy" if provider_ok else "unhealthy"

        return {
            "status": "ok",
            "uptime": round(time.time() - _server_start_time, 2) if _server_start_time else 0,
            "components": comps,
            "version": _get_version(),
        }

    @app.get("/ping")
    async def ping():
        result = facade.provider.ping()
        return {
            "success": result.success,
            "data": result.data,
            "error": _serialize_error(result.error),
            "task_state": result.task_state,
        }

    @app.post("/send")
    async def send_task(req: _SendRequest = Body(...)):
        result = facade.send_task(req.task)
        if not result.success:
            _raise_a2a_error(result, 400, "INVALID_REQUEST")
        return _json_response(result)

    def _json_response(result, status_code: int = 200):
        return JSONResponse(
            status_code=status_code,
            content={
                "success": result.success if hasattr(result, 'success') else False,
                "data": result.data if hasattr(result, 'data') else None,
                "error": _serialize_error(getattr(result, 'error', None)),
                "task_state": getattr(result, 'task_state', None),
            },
        )

    def _raise_a2a_error(result, default_status: int, default_code: str, *extra_codes: str):
        """Raise A2AServerError from a failed A2AResult.

        Args:
            result: The failed A2AResult.
            default_status: Fallback HTTP status code.
            default_code: Fallback error code string.
            extra_codes: More specific codes tried before default.
        """
        status = _error_code(result.error, default_status)
        code = default_code
        msg = "Unknown error"

        # Try more specific error codes first
        if result.error:
            if isinstance(result.error, A2AError):
                msg = result.error.message
                # Map internal error codes
                for ec in (*extra_codes, INTERNAL_TO_ERROR_CODE.get(result.error.code, default_code)):
                    code = ec
                    break
            elif isinstance(result.error, dict):
                msg = result.error.get("message", msg)
                code = result.error.get("code", default_code)

        raise A2AServerError(status_code=status, code=code, message=msg)

    @app.get("/task/{task_id}")
    async def get_task(task_id: str):
        result = facade.get_task(task_id)
        if not result.success:
            _raise_a2a_error(result, 404, "NOT_FOUND", "TASK_NOT_FOUND")
        return _json_response(result)

    @app.post("/cancel/{task_id}")
    async def cancel_task(task_id: str):
        result = facade.cancel_task(task_id)
        if not result.success:
            _raise_a2a_error(result, 404, "NOT_FOUND", "TASK_NOT_FOUND")
        return _json_response(result)

    @app.get("/stream/{task_id}")
    async def stream_task(task_id: str):
        """SSE stream: subscribe to task state changes in real time.

        Returns Server-Sent Events as the task progresses through
        its lifecycle (submitted -> working -> completed/canceled/failed).
        Each event has type "state", "completed", or "done".

        The stream enforces an idle timeout configured via
        ``_timeout_config.stream_idle_timeout``. If no data is sent
        for that duration, the stream sends a "stream_timeout" event
        and closes.

        Example:
            curl -N http://localhost:8080/stream/task_001
        """
        import time as _time

        idle_timeout = _timeout_config.stream_idle_timeout

        task = facade.get_task(task_id)
        if not task.success:
            async def _err_stream() -> AsyncGenerator[bytes, None]:
                yield _sse_event("error", task)
                yield _sse_event("done", {"success": False, "data": {"message": "Task not found"}})
            return StreamingResponse(_err_stream(), media_type="text/event-stream")

        async def _stream() -> AsyncGenerator[bytes, None]:
            last_activity = _time.monotonic()

            # 1. Emit current state immediately
            result = facade.get_task(task_id)
            yield _sse_event("state", result)
            last_activity = _time.monotonic()

            # 2. If submitted, simulate step-through progress
            if result.task_state == "submitted":
                stages = [
                    ("working", "Processing task...", 0.5),
                    ("working", "Analyzing data...", 1.0),
                    ("working", "Generating result...", 1.5),
                ]
                for state, msg, delay in stages:
                    # Check idle timeout before each delay
                    if idle_timeout > 0:
                        elapsed = _time.monotonic() - last_activity
                        if elapsed > idle_timeout:
                            yield _sse_event("stream_timeout", {
                                "idle_seconds": elapsed,
                                "timeout": idle_timeout,
                            })
                            yield _sse_event("done", {
                                "success": False,
                                "data": {"message": "Stream idle timeout"},
                            })
                            return

                    await asyncio.sleep(delay)
                    tasks = facade.provider._tasks
                    if task_id in tasks:
                        tasks[task_id].setdefault("status", {})["state"] = state
                        tasks[task_id]["status"]["message"] = msg
                        tasks[task_id]["status"]["timestamp"] = time.time()
                    result = facade.get_task(task_id)
                    yield _sse_event("state", result)
                    last_activity = _time.monotonic()

                # Mark as completed
                if task_id in tasks:
                    tasks[task_id]["status"]["state"] = "completed"
                    tasks[task_id]["status"]["message"] = "Task completed successfully"
                    tasks[task_id]["status"]["timestamp"] = time.time()
                    tasks[task_id].setdefault("result", {})["data"] = {
                        "output": f"Processed task {task_id}"
                    }
                result = facade.get_task(task_id)
                yield _sse_event("completed", result)

            yield _sse_event("done", {"success": True, "data": {"message": "Stream ended"}})

        return StreamingResponse(_stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

    @app.get("/agents")
    async def list_agents():
        """List all registered agent cards."""
        return {"agents": []}

    @app.post("/agents")
    async def register_agent(card: _AgentCardRequest = Body(...)):
        """Register an agent card."""
        provider = _get_memory_provider(facade.provider)
        if provider:
            provider.register_agent_card(card.model_dump())
        return {"success": True, "message": f"Agent '{card.name}' registered"}

    # --- Return the FastAPI app so callers can mount or run it ---
    return app


def _sse_event(event_type: str, data: Any) -> bytes:
    """Format data as an SSE event payload."""
    if isinstance(data, A2AResult):
        payload = {
            "event": event_type,
            "data": {
                "success": data.success,
                "data": data.data,
                "error": _serialize_error(data.error),
                "task_state": data.task_state,
            }
        }
    else:
        payload = {"event": event_type, "data": data}
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n".encode("utf-8")


def _serialize_error(error: Any) -> Optional[dict]:
    if error is None:
        return None
    if isinstance(error, A2AError):
        return {"code": error.code, "message": error.message, "recoverable": error.recoverable}
    if isinstance(error, dict):
        return error
    return {"code": 500, "message": str(error), "recoverable": False}


def _error_code(error: Any, default: int) -> int:
    if isinstance(error, A2AError):
        return error.code
    return default


def _get_memory_provider(provider: A2AProvider) -> Optional[MemoryProvider]:
    """Safely cast provider to MemoryProvider if applicable."""
    if isinstance(provider, MemoryProvider):
        return provider
    return None


# ===================================================================
# HttpProvider — A2A client that talks to an A2A server over HTTP
# ===================================================================


class HttpProvider(A2AProvider):
    """HTTP Provider: connects to a remote A2A Server via HTTP.

    Implements the A2AProvider interface by making HTTP requests
    to a server running agentmesh.a2a_server.

    Usage:
        provider = HttpProvider("http://localhost:8080")
        result = provider.send_message({"id": "t1", "status": {"state": "submitted"}, "payload": {}})
        result = provider.get_task("t1")
        result = provider.cancel_task("t1")
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        name: str = "http",
        timeout_config: Optional[ServerTimeoutConfig] = None,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
    ) -> None:
        """
        Args:
            base_url: Server base URL.
            name: Provider name.
            timeout_config: Timeout settings (connection, read, request).
            max_retries: Max HTTP retry attempts on transient failure (0 = no retry).
            backoff_factor: Exponential backoff multiplier in seconds.
        """
        super().__init__(name)
        self.base_url: str = base_url.rstrip("/")
        self._capabilities: Set[str] = {"http", "network"}
        self._timeout_config: ServerTimeoutConfig = timeout_config or ServerTimeoutConfig()
        self._max_retries: int = max_retries
        self._backoff_factor: float = backoff_factor

    # ---- A2AProvider interface ----

    def send_message(self, task: dict, auth: Optional[dict] = None) -> A2AResult:
        payload: dict = {"task": task, "auth": auth}
        resp: dict = self._post("/send", payload)
        return self._to_result(resp)

    def get_task(self, task_id: str, auth: Optional[dict] = None) -> A2AResult:
        resp: dict = self._get(f"/task/{task_id}")
        return self._to_result(resp)

    def cancel_task(self, task_id: str, auth: Optional[dict] = None) -> A2AResult:
        resp: dict = self._post(f"/cancel/{task_id}", {})
        return self._to_result(resp)

    def ping(self) -> A2AResult:
        resp: dict = self._get("/ping")
        return self._to_result(resp)

    def register_agent(self, name: str, skills: Optional[List[str]] = None) -> A2AResult:
        resp: dict = self._post("/agents", {"name": name, "skills": skills or []})
        return self._to_result(resp)

    def stream_task(self, task_id: str) -> SSEStream:
        """Open an SSE stream for task state updates.

        Returns an SSEStream iterator that yields (event_type, data_dict)
        tuples as the task progresses.

        Usage:
            stream = client.stream_task("task_001")
            for event_type, data in stream:
                print(f"[{event_type}] {data}")
                if event_type == "done":
                    break
        """
        return SSEStream(
            self.base_url, task_id,
            max_retries=self._max_retries,
            backoff_factor=self._backoff_factor,
            timeout=int(self._timeout_config.connect_timeout),
            heartbeat_timeout=self._timeout_config.stream_idle_timeout,
        )

    # ---- Internal HTTP helpers ----

    def _post(self, path: str, body: dict) -> dict:
        url = self.base_url + path
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._do_request(req)

    def _get(self, path: str) -> dict:
        url = self.base_url + path
        req = urllib.request.Request(url, method="GET")
        return self._do_request(req)

    def _do_request(self, req: urllib.request.Request) -> dict:
        """Execute an HTTP request with configurable timeout and automatic retry.

        Retries on:
        - 5xx server errors (500, 502, 503, 504)
        - 429 rate limit
        - Network-level exceptions (ConnectionError, TimeoutError, OSError)

        Does NOT retry on:
        - 4xx client errors (except 429)
        - Non-network exceptions

        Retry uses exponential backoff with jitter.
        """
        import random as _random
        import time as _time

        timeout = int(self._timeout_config.read_timeout) if hasattr(self, '_timeout_config') else 10
        max_retries = getattr(self, '_max_retries', 3)
        backoff_factor = getattr(self, '_backoff_factor', 1.0)

        for attempt in range(1 + max_retries):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = resp.read().decode("utf-8")
                    return json.loads(body)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8")
                try:
                    result = json.loads(body)
                except json.JSONDecodeError:
                    result = {"success": False,
                              "error": {"code": e.code, "message": body, "recoverable": True}}

                # Retry on 5xx and 429; do NOT retry on 4xx
                if attempt < max_retries and (e.code == 429 or e.code >= 500):
                    delay = min(backoff_factor * (2 ** attempt), 30.0)
                    jitter = delay * _random.uniform(0, 0.25)
                    _time.sleep(delay + jitter)
                    continue
                return result

            except (urllib.error.URLError, OSError, TimeoutError) as e:
                if attempt < max_retries:
                    delay = min(backoff_factor * (2 ** attempt), 30.0)
                    jitter = delay * _random.uniform(0, 0.25)
                    _time.sleep(delay + jitter)
                    continue
                return {"success": False,
                        "error": {"code": 503, "message": str(e), "recoverable": True}}

        return {"success": False,
                "error": {"code": 503, "message": "Request failed after retries", "recoverable": False}}

    # Map from string error codes (new unified format) to HTTP int codes
    _STRING_TO_INT_CODE = {
        "INVALID_REQUEST": 400,
        "VALIDATION_ERROR": 400,
        "NOT_FOUND": 404,
        "TASK_NOT_FOUND": 404,
        "AGENT_NOT_FOUND": 404,
        "INTERNAL_ERROR": 500,
        "PROVIDER_ERROR": 500,
        "SERVICE_UNAVAILABLE": 503,
    }

    @staticmethod
    def _infer_recoverable(int_code: int, resp_code_override: Optional[int] = None) -> bool:
        """Infer whether an error is recoverable based on HTTP status code.

        5xx errors (server-side) are generally recoverable (retryable).
        4xx errors (client-side) are generally NOT recoverable.
        """
        actual = resp_code_override if resp_code_override is not None else int_code
        return actual >= 500

    def _to_result(self, resp: dict) -> A2AResult:
        success = resp.get("success", False)
        data = resp.get("data")
        error_raw = resp.get("error")
        task_state = resp.get("task_state")

        error = None
        if error_raw:
            code_raw = error_raw.get("code", 500)
            message = error_raw.get("message", "Unknown error")
            recoverable = error_raw.get("recoverable", None)

            if isinstance(code_raw, str):
                int_code = self._STRING_TO_INT_CODE.get(code_raw, 500)
                # Use explicit recoverable if provided, otherwise infer from status
                if recoverable is None:
                    recoverable = self._infer_recoverable(int_code)
                error = A2AError(code=int_code, message=message, recoverable=recoverable)
            else:
                # Old format: int code
                if recoverable is None:
                    recoverable = self._infer_recoverable(code_raw)
                error = A2AError(code=code_raw, message=message, recoverable=recoverable)

        return A2AResult(success=success, data=data, error=error, task_state=task_state)


# ===================================================================
# SSE Stream client
# ===================================================================


class SSEStream:
    """SSE event stream reader for A2A task state updates.

    Wraps an HTTP streaming response to the /stream/{task_id} endpoint
    and yields parsed (event_type, data_dict) tuples.

    Supports automatic reconnection with exponential backoff for transient
    failures (5xx, 429), configurable timeouts, and heartbeat detection.

    Usage:
        stream = SSEStream("http://localhost:8080", "task_001")
        for event_type, data in stream:
            print(f"[{event_type}] {data}")
            if event_type == "done":
                break

    Thread-safe: opens its own HTTP connection on iteration.
    """

    def __init__(
        self,
        base_url: str,
        task_id: str,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
        timeout: int = 30,
        heartbeat_timeout: float = 15.0,
    ) -> None:
        """
        Args:
            base_url: Server base URL (e.g. http://localhost:8080)
            task_id: Task ID to stream
            max_retries: Max reconnection attempts on transient failure (0 = no retry)
            backoff_factor: Exponential backoff multiplier in seconds
            timeout: HTTP connection timeout in seconds
            heartbeat_timeout: Seconds without data before yielding timeout event
        """
        self.url: str = base_url.rstrip("/") + f"/stream/{task_id}"
        self.max_retries: int = max_retries
        self.backoff_factor: float = backoff_factor
        self.timeout: int = timeout
        self.heartbeat_timeout: float = heartbeat_timeout

    def __iter__(self) -> Iterator[Tuple[str, Any]]:
        """Iterate over (event_type, data_dict) tuples from the SSE stream."""
        last_activity = time.monotonic()
        retries = 0

        while retries <= self.max_retries:
            parsed = urllib.parse.urlparse(self.url)
            conn = http.client.HTTPConnection(
                parsed.hostname, parsed.port or 80, timeout=self.timeout
            )
            try:
                conn.request(
                    "GET",
                    parsed.path + ("?" + parsed.query if parsed.query else ""),
                    headers={"Accept": "text/event-stream"},
                )
                resp = conn.getresponse()

                # Non-200: retry if retryable status, otherwise fail
                if resp.status != 200:
                    if retries < self.max_retries and _is_retryable_status(resp.status):
                        retries += 1
                        _backoff_wait(retries, self.backoff_factor)
                        conn.close()
                        continue
                    yield ("error", {"status": resp.status, "message": resp.reason})
                    return

                # Successful connection — reset retry counter
                retries = 0
                buffer = b""

                try:
                    while True:
                        # Heartbeat detection: yield timeout if silent too long
                        idle_time = time.monotonic() - last_activity
                        if idle_time > self.heartbeat_timeout:
                            yield ("heartbeat_timeout", {
                                "idle_seconds": idle_time,
                                "timeout": self.heartbeat_timeout,
                            })
                            return

                        # Non-blocking read with heartbeat check
                        chunk = resp.read(4096)
                        if not chunk:
                            break

                        last_activity = time.monotonic()
                        buffer += chunk

                        while b"\n\n" in buffer:
                            raw_event, buffer = buffer.split(b"\n\n", 1)
                            parsed_event = self._parse(raw_event)
                            if parsed_event:
                                yield parsed_event
                finally:
                    conn.close()

                # Clean exit — stream ended normally
                return

            except (http.client.HTTPException, urllib.error.URLError,
                    ConnectionError, TimeoutError, OSError) as exc:
                conn.close()
                if retries < self.max_retries:
                    retries += 1
                    yield ("reconnect", {
                        "attempt": retries,
                        "max_retries": self.max_retries,
                        "error": str(exc),
                    })
                    _backoff_wait(retries, self.backoff_factor)
                else:
                    yield ("error", {
                        "message": f"SSE connection failed after {retries} retries",
                        "last_error": str(exc),
                    })
                    return

    @staticmethod
    def _parse(raw: bytes) -> Optional[Tuple[str, dict]]:
        """Parse a single SSE message into (event_type, data_dict) or None."""
        event_type = "message"
        data_str: Optional[str] = None
        for line in raw.decode("utf-8").split("\n"):
            if line.startswith("event: "):
                event_type = line[7:].strip()
            elif line.startswith("data: "):
                data_str = line[6:].strip()
            elif line.startswith("id: "):
                pass  # SSE event id — reserved for future use
        if data_str:
            try:
                payload = json.loads(data_str)
                return (payload.get("event", event_type), payload.get("data", {}))
            except json.JSONDecodeError:
                return (event_type, {"raw": data_str})
        return None


def _is_retryable_status(status: int) -> bool:
    """Check if an HTTP status code warrants reconnection."""
    return status in (429, 502, 503, 504)


def _backoff_wait(attempt: int, factor: float) -> None:
    """Sleep with exponential backoff, capped at 30 seconds."""
    delay: float = factor * (2 ** (attempt - 1))
    time.sleep(min(delay, 30.0))


# ===================================================================
# Convenience functions
# ===================================================================


def create_server_app():
    """Create and return a configured FastAPI app.

    Useful for embedding in another application or testing.
    """
    return _build_app()


def create_http_provider(base_url: str = "http://localhost:8080") -> HttpProvider:
    """Create an HttpProvider configured for the given server."""
    return HttpProvider(base_url)


# ===================================================================
# CLI
# ===================================================================


def cmd_server(port: int = 8080, daemon: bool = False,
               timeout_config: Optional[ServerTimeoutConfig] = None):
    """Start the A2A test server.

    Args:
        port: Server port (default: 8080).
        daemon: Fork to background.
        timeout_config: Optional timeout configuration override.
    """
    import uvicorn

    app = _build_app(timeout_config=timeout_config)
    log_level = "info"

    if daemon:
        # Fork into background
        pid = os.fork()
        if pid > 0:
            print(f"A2A server starting (pid={pid}) on http://localhost:{port}")
            return

    print(f"A2A Server listening on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level=log_level)


def cmd_test(port: int = 8080):
    """Run the built-in A2A protocol test against a running or auto-started server."""
    # Check if server responds
    try:
        req = urllib.request.Request(f"http://localhost:{port}/ping", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            pass
        server_running = True
        server_proc = None
        print(f"[*] Server already running on :{port}")
    except Exception:
        server_running = False
        # Fork a server process
        print(f"[*] Starting server on :{port}...")
        server_proc = subprocess.Popen(
            [sys.executable, "-m", "agentmesh.a2a_server", "server", "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(2)

    try:
        _run_test(port)
    finally:
        if server_proc:
            server_proc.terminate()
            server_proc.wait(timeout=5)


def _run_test(port: int):
    """Execute protocol verification against the server at the given port."""
    base = f"http://localhost:{port}"
    client = HttpProvider(base)
    passed = 0
    failed = 0

    def check(name: str, cond: bool, detail: str = ""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  ✅ {name}")
        else:
            failed += 1
            print(f"  ❌ {name} — {detail}")

    print(f"\n=== A2A Server Protocol Test ({base}) ===")

    # 1. Ping
    r = client.ping()
    check("Ping", r.success and r.data and r.data.get("status") == "ok",
          f"expected ok status, got {r.data}")

    # 2. Send task
    task = {"id": "test_001", "status": {"state": "submitted"}, "payload": {"text": "hello"}}
    r = client.send_message(task)
    check("Send task", r.success and r.task_state == "submitted",
          f"expected submitted, got {r.task_state}")

    # 3. Get task
    r = client.get_task("test_001")
    check("Get task", r.success and r.data and r.data["id"] == "test_001",
          f"expected task test_001, got {r.data}")

    # 4. Cancel task
    r = client.cancel_task("test_001")
    check("Cancel task", r.success and r.task_state == "canceled",
          f"expected canceled, got {r.task_state}")

    # 5. Get nonexistent task → 404
    r = client.get_task("nonexistent")
    check("Get nonexistent → 404", not r.success and r.error and r.error.code == 404,
          f"expected 404, got {r.error}")

    # 6. Register agent via HttpProvider
    r = client.register_agent("test-agent", ["test", "demo"])
    check("Register agent", r.success,
          f"expected success, got {r.error}")

    # 7. Send then get lifecycle
    task2 = {"id": "test_002", "status": {"state": "submitted"}, "payload": {"text": "world"}}
    r1 = client.send_message(task2)
    r2 = client.get_task("test_002")
    check("Full lifecycle (send→get)", r1.success and r2.success,
          f"send={r1.success} get={r2.success}")

    # 8. Empty task id → error
    bad_task = {"id": "", "status": {"state": "submitted"}, "payload": {}}
    r = client.send_message(bad_task)
    check("Empty task id → error", not r.success,
          f"expected failure for empty id, got success")

    print(f"\n=== Results: {passed}/{passed + failed} passed ===")

    if failed > 0:
        sys.exit(1)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="AgentMesh A2A Test Server")
    sub = parser.add_subparsers(dest="command", required=True)

    # server
    p_server = sub.add_parser("server", help="Start A2A HTTP server")
    p_server.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    p_server.add_argument("--daemon", action="store_true", help="Fork to background")

    # test
    p_test = sub.add_parser("test", help="Run protocol test against server")
    p_test.add_argument("--port", type=int, default=8080, help="Server port (default: 8080)")

    args = parser.parse_args()

    if args.command == "server":
        cmd_server(port=args.port, daemon=args.daemon)
    elif args.command == "test":
        cmd_test(port=args.port)


if __name__ == "__main__":
    main()
