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

import asyncio
import http.client
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, AsyncGenerator, List, Optional

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
        MemoryProvider,
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
    def from_json(cls, raw: str) -> "A2AResponse":
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


def _build_app(facade: Optional[A2AFacade] = None):
    """Build a FastAPI application wrapping the given A2AFacade.

    To integrate into an existing FastAPI app, import this function
    and mount or include the returned app:

        from agentmesh.a2a_server import _build_app
        app.mount("/a2a", _build_app())

    Endpoints:
        GET  /ping          - Health check
        POST /send          - Send a task
        GET  /task/{id}     - Get task status
        POST /cancel/{id}   - Cancel a task
        GET  /agents        - List registered agent cards
        POST /agents        - Register an agent card
    """
    from fastapi import Body, FastAPI
    from starlette.responses import JSONResponse, StreamingResponse

    if facade is None:
        provider = MemoryProvider("a2a-server")
        task_manager = A2ATaskManager()
        facade = A2AFacade(provider=provider, task_manager=task_manager)

    app = FastAPI(title="AgentMesh A2A Server", version="0.4.0")

    # --- Endpoints ---

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
            return _json_response(result, status_code=_error_code(result.error, 400))
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

    @app.get("/task/{task_id}")
    async def get_task(task_id: str):
        result = facade.get_task(task_id)
        if not result.success:
            return _json_response(result, status_code=_error_code(result.error, 404))
        return _json_response(result)

    @app.post("/cancel/{task_id}")
    async def cancel_task(task_id: str):
        result = facade.cancel_task(task_id)
        if not result.success:
            return _json_response(result, status_code=_error_code(result.error, 404))
        return _json_response(result)

    @app.get("/stream/{task_id}")
    async def stream_task(task_id: str):
        """SSE stream: subscribe to task state changes in real time.

        Returns Server-Sent Events as the task progresses through
        its lifecycle (submitted -> working -> completed/canceled/failed).
        Each event has type "state", "completed", or "done".

        Example:
            curl -N http://localhost:8080/stream/task_001
        """
        task = facade.get_task(task_id)
        if not task.success:
            async def _err_stream() -> AsyncGenerator[bytes, None]:
                yield _sse_event("error", task)
                yield _sse_event("done", {"success": False, "data": {"message": "Task not found"}})
            return StreamingResponse(_err_stream(), media_type="text/event-stream")

        async def _stream() -> AsyncGenerator[bytes, None]:
            # 1. Emit current state immediately
            result = facade.get_task(task_id)
            yield _sse_event("state", result)

            # 2. If submitted, simulate step-through progress
            if result.task_state == "submitted":
                stages = [
                    ("working", "Processing task...", 0.5),
                    ("working", "Analyzing data...", 1.0),
                    ("working", "Generating result...", 1.5),
                ]
                for state, msg, delay in stages:
                    await asyncio.sleep(delay)
                    tasks = facade.provider._tasks
                    if task_id in tasks:
                        tasks[task_id].setdefault("status", {})["state"] = state
                        tasks[task_id]["status"]["message"] = msg
                        tasks[task_id]["status"]["timestamp"] = time.time()
                    result = facade.get_task(task_id)
                    yield _sse_event("state", result)

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

    def __init__(self, base_url: str = "http://localhost:8080", name: str = "http"):
        super().__init__(name)
        self.base_url = base_url.rstrip("/")
        self._capabilities = {"http", "network"}

    # ---- A2AProvider interface ----

    def send_message(self, task: dict, auth: Optional[dict] = None) -> A2AResult:
        payload = {"task": task, "auth": auth}
        resp = self._post("/send", payload)
        return self._to_result(resp)

    def get_task(self, task_id: str, auth: Optional[dict] = None) -> A2AResult:
        resp = self._get(f"/task/{task_id}")
        return self._to_result(resp)

    def cancel_task(self, task_id: str, auth: Optional[dict] = None) -> A2AResult:
        resp = self._post(f"/cancel/{task_id}", {})
        return self._to_result(resp)

    def ping(self) -> A2AResult:
        resp = self._get("/ping")
        return self._to_result(resp)

    def register_agent(self, name: str, skills: Optional[List[str]] = None) -> A2AResult:
        resp = self._post("/agents", {"name": name, "skills": skills or []})
        return self._to_result(resp)

    def stream_task(self, task_id: str) -> "SSEStream":
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
        return SSEStream(self.base_url, task_id)

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
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {"success": False, "error": {"code": e.code, "message": body, "recoverable": True}}
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            return {"success": False, "error": {"code": 503, "message": str(e), "recoverable": True}}

    def _to_result(self, resp: dict) -> A2AResult:
        success = resp.get("success", False)
        data = resp.get("data")
        error_raw = resp.get("error")
        task_state = resp.get("task_state")

        error = None
        if error_raw:
            error = A2AError(
                code=error_raw.get("code", 500),
                message=error_raw.get("message", "Unknown error"),
                recoverable=error_raw.get("recoverable", False),
            )

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

    def __init__(self, base_url: str, task_id: str,
                 max_retries: int = 3,
                 backoff_factor: float = 1.0,
                 timeout: int = 30,
                 heartbeat_timeout: float = 15.0):
        """
        Args:
            base_url: Server base URL (e.g. http://localhost:8080)
            task_id: Task ID to stream
            max_retries: Max reconnection attempts on transient failure (0 = no retry)
            backoff_factor: Exponential backoff multiplier in seconds
            timeout: HTTP connection timeout in seconds
            heartbeat_timeout: Seconds without data before yielding timeout event
        """
        self.url = base_url.rstrip("/") + f"/stream/{task_id}"
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.timeout = timeout
        self.heartbeat_timeout = heartbeat_timeout

    def __iter__(self):
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
    def _parse(raw: bytes):
        """Parse a single SSE message into (event_type, data_dict) or None."""
        event_type = "message"
        data_str = None
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
    delay = factor * (2 ** (attempt - 1))
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


def cmd_server(port: int = 8080, daemon: bool = False):
    """Start the A2A test server."""
    import uvicorn

    app = _build_app()
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
          "expected failure for empty id, got success")

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
