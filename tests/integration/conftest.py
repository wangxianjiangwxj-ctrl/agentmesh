"""
conftest.py — AgentMesh A2A Layer 2 Integration Test Fixtures

Provides pytest fixtures for spinning up a real A2A HTTP Server (JSON-RPC 2.0)
and connecting an HTTP client to it. All URLs/ports/timeouts are configurable
via pytest.mark or environment variables.

Usage:
    def test_foo(a2a_server, a2a_client):
        resp = a2a_client.send_task(...)
        assert resp ...
"""

import os
import sys
import json
import time
import uuid
import threading
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

import pytest

from agentmesh.a2a.provider import (
    A2AProvider,
    MemoryProvider,
    A2AResult,
    A2AError,
    A2ATaskManager,
    A2ATaskState,
    A2AFacade,
)

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


DEFAULT_HOST = os.environ.get("A2A_TEST_HOST", "127.0.0.1")
DEFAULT_TIMEOUT = float(os.environ.get("A2A_TEST_TIMEOUT", "10.0"))


def make_id(prefix: str = "task") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# A2A HTTP Server (in-process, background thread)
# ---------------------------------------------------------------------------

class IntegrationA2AServer:
    """
    Lightweight A2A JSON-RPC 2.0 HTTP server that runs in a background thread.

    Supports JSON-RPC 2.0 methods:
      - tasks.send
      - tasks.get
      - tasks.cancel
      - tasks.notify  (SSE push stub)
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = 0,
                 name: str = "a2a-integration-server"):
        self.host = host
        self.port = port
        self.name = name
        self._provider = MemoryProvider(f"integration-{name}")
        self._task_manager = A2ATaskManager()
        self._httpd = None
        self._thread = None
        self._started = threading.Event()

        # Register agent card
        self._provider.register_agent_card({
            "name": name,
            "description": "A2A Integration Test Server",
            "url": f"http://{host}:{port}/a2a",
            "capabilities": ["task-processing", "json-rpc"],
            "authentication": {"schemes": [{"type": "none"}]},
        })

    @property
    def url(self) -> str:
        if hasattr(self, '_httpd') and self._httpd is not None:
            actual_port = self._httpd.server_address[1]
            return f"http://{self.host}:{actual_port}/a2a"
        return f"http://{self.host}:{self.port}/a2a"

    @property
    def provider(self) -> MemoryProvider:
        return self._provider

    @property
    def task_manager(self) -> A2ATaskManager:
        return self._task_manager

    # -- JSON-RPC Handlers ------------------------------------------------

    def handle_request(self, body: dict) -> dict:
        method = body.get("method", "")
        req_id = body.get("id", None)
        params = body.get("params", {})

        handlers = {
            "tasks.send": self._handle_send,
            "tasks.get": self._handle_get,
            "tasks.cancel": self._handle_cancel,
            "tasks.notify": self._handle_notify,
        }

        handler = handlers.get(method)
        if handler is None:
            return self._jsonrpc_error(req_id, -32601, f"Method not found: {method}")
        try:
            return handler(req_id, params)
        except Exception as exc:
            return self._jsonrpc_error(req_id, -32603, str(exc))

    def _jsonrpc_error(self, req_id, code: int, message: str):
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

    def _jsonrpc_result(self, req_id, result: dict):
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _handle_send(self, req_id, params: dict) -> dict:
        task_id = params.get("id", make_id())
        state = params.get("status", {}).get("state", A2ATaskState.SUBMITTED)

        # Track in task manager
        if not self._task_manager.get_task(task_id):
            self._task_manager.track(task_id, state)
        else:
            self._task_manager.update_state(task_id, state)

        # Simulate processing
        self._task_manager.update_state(task_id, A2ATaskState.WORKING)
        time.sleep(0.02)
        self._task_manager.update_state(task_id, A2ATaskState.COMPLETED)

        # Build result
        result = {
            "id": task_id,
            "status": {"state": A2ATaskState.COMPLETED},
            "messages": params.get("messages", []),
            "artifacts": [
                {
                    "artifactId": f"art_{uuid.uuid4().hex[:8]}",
                    "parts": [{"type": "text", "text": f"Processed task {task_id}"}],
                }
            ],
        }

        # Store in provider
        self._provider._tasks[task_id] = result
        return self._jsonrpc_result(req_id, result)

    def _handle_get(self, req_id, params: dict) -> dict:
        task_id = params.get("id", "")
        task = self._provider.get_task(task_id)
        if isinstance(task, A2AResult):
            if not task.success:
                return self._jsonrpc_error(req_id, -32000, f"Task not found: {task_id}")
            return self._jsonrpc_result(req_id, task.data)

        if task is None:
            return self._jsonrpc_error(req_id, -32000, f"Task not found: {task_id}")
        state = self._task_manager.get_task(task_id)
        state_str = state["state"] if state else "unknown"
        return self._jsonrpc_result(req_id, {"id": task_id, "status": {"state": state_str}})

    def _handle_cancel(self, req_id, params: dict) -> dict:
        task_id = params.get("id", "")
        result = self._provider.cancel_task(task_id)
        if not result.success:
            return self._jsonrpc_error(req_id, -32000, f"Task not found: {task_id}")
        # Attempt state machine transition; ignore if task is already terminal
        try:
            self._task_manager.update_state(task_id, A2ATaskState.CANCELED)
        except A2AError:
            # Task is in a terminal state (completed/failed/canceled);
            # override stored state to CANCELED regardless
            tracked = self._task_manager.get_task(task_id)
            if tracked:
                tracked["state"] = A2ATaskState.CANCELED
        return self._jsonrpc_result(req_id, {"id": task_id, "status": {"state": A2ATaskState.CANCELED}})

    def _handle_notify(self, req_id, params: dict) -> dict:
        """Placeholder for SSE push notification stub."""
        task_id = params.get("id", "")
        event = params.get("event", "state_change")
        return self._jsonrpc_result(req_id, {
            "id": task_id,
            "event": event,
            "ack": True,
        })

    # -- Lifecycle ---------------------------------------------------------

    def start(self):
        """Start the HTTP server in a background thread."""

        server_self = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                content_length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(content_length).decode("utf-8"))
                response = server_self.handle_request(body)
                resp_body = json.dumps(response, ensure_ascii=False)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(resp_body.encode("utf-8"))

            def do_GET(self):
                """GET /health — health check"""
                if self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
                elif self.path == "/a2a":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"service": "A2A Integration Server", "name": server_self.name}).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, fmt, *args):
                pass  # suppress server logs in tests

        self._httpd = HTTPServer((self.host, self.port), Handler)
        self.port = self._httpd.server_address[1]
        # Update agent card with actual port
        old_card = self._provider._agent_cards.get(self.name, {})
        if old_card:
            old_card["url"] = self.url
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        self._started.set()
        return self.port

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def wait_ready(self, timeout: float = 5.0):
        """Block until the server is accepting connections."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                import urllib.request
                resp = urllib.request.urlopen(f"http://{self.host}:{self.port}/health", timeout=1)
                if resp.status == 200:
                    return True
            except (ConnectionRefusedError, urllib.error.URLError, OSError):
                time.sleep(0.05)
        raise RuntimeError(f"A2A server did not become ready within {timeout}s")


# ---------------------------------------------------------------------------
# A2A HTTP Client
# ---------------------------------------------------------------------------

class IntegrationA2AClient:
    """HTTP client for the A2A JSON-RPC 2.0 server."""

    def __init__(self, server_url: str, timeout: float = DEFAULT_TIMEOUT):
        self.server_url = server_url
        self.timeout = timeout
        self._counter = 0

    def _post(self, body: dict) -> dict:
        import urllib.request
        self._counter += 1
        body["id"] = body.get("id", self._counter)
        req_data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.server_url,
            data=req_data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def send_task(self, task_id: str = None, messages: list = None,
                  state: str = "submitted") -> dict:
        tid = task_id or make_id()
        return self._post({
            "jsonrpc": "2.0",
            "method": "tasks.send",
            "params": {
                "id": tid,
                "status": {"state": state},
                "messages": messages or [{"role": "user", "parts": [{"text": "test query"}]}],
            },
        })

    def get_task(self, task_id: str) -> dict:
        return self._post({
            "jsonrpc": "2.0",
            "method": "tasks.get",
            "params": {"id": task_id},
        })

    def cancel_task(self, task_id: str) -> dict:
        return self._post({
            "jsonrpc": "2.0",
            "method": "tasks.cancel",
            "params": {"id": task_id},
        })

    def notify(self, task_id: str, event: str = "state_change") -> dict:
        return self._post({
            "jsonrpc": "2.0",
            "method": "tasks.notify",
            "params": {"id": task_id, "event": event},
        })

    def health_check(self) -> bool:
        import urllib.request
        import urllib.error
        try:
            base = self.server_url.rsplit("/", 1)[0]  # strip /a2a path
            resp = urllib.request.urlopen(f"{base}/health", timeout=self.timeout)
            return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False


# ---------------------------------------------------------------------------
# pytest Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def a2a_server_port():
    """Provide a consistent port across the test session."""
    return _find_free_port()


@pytest.fixture(scope="session")
def a2a_server_host():
    """Server hostname, configurable via A2A_TEST_HOST env var."""
    return DEFAULT_HOST


@pytest.fixture(scope="function")
def a2a_server(a2a_server_host):
    """
    Spins up an A2A HTTP server in a background thread.

    Yields the server object. The server is torn down after each test function.
    """
    server = IntegrationA2AServer(host=a2a_server_host, port=0)
    server.start()
    server.wait_ready(timeout=5)
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="function")
def a2a_client(a2a_server):
    """
    Creates an A2A HTTP client connected to the fixture server.

    Requires the ``a2a_server`` fixture to be active.
    """
    client = IntegrationA2AClient(server_url=a2a_server.url, timeout=DEFAULT_TIMEOUT)
    return client


@pytest.fixture(scope="function")
def sample_task_id():
    """Generate a unique task ID for each test."""
    return make_id("test")


@pytest.fixture
def a2a_facade():
    """Creates an A2AFacade with a fresh MemoryProvider for in-memory reference testing."""
    return A2AFacade(provider=MemoryProvider("ref"), task_manager=A2ATaskManager())
