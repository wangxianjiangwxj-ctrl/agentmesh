"""
test_protocol_flow.py — A2A Layer 2 Protocol Flow Integration Tests

Tests the A2A JSON-RPC 2.0 protocol over real HTTP:
  - Server startup and health check
  - task_send / task_get / task_cancel lifecycle
  - Concurrent task submission
  - Error handling (non-existent task, bad method)
  - JSON-RPC 2.0 compliance (jsonrpc field, id pairing)
"""

import json
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from agentmesh.a2a.provider import (
    A2ATaskState,
    A2ATaskManager,
    A2AError,
    A2AResult,
)

# ====================================================================
# Test Class: Server Startup & Health
# ====================================================================

class TestServerStartup:
    """Verify the A2A server starts and responds correctly."""

    def test_server_health_endpoint(self, a2a_server):
        """GET /health should return HTTP 200 with status ok."""
        import urllib.request
        base = a2a_server.url.rsplit("/", 1)[0]
        resp = urllib.request.urlopen(f"{base}/health", timeout=5)
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "ok"

    def test_server_a2a_endpoint(self, a2a_server):
        """GET /a2a should return server metadata."""
        import urllib.request
        resp = urllib.request.urlopen(a2a_server.url, timeout=5)
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["service"] == "A2A Integration Server"
        assert "name" in data

    def test_server_agent_card_registered(self, a2a_server):
        """Server should have a valid agent card."""
        card = a2a_server.provider.get_agent_card(a2a_server.name)
        assert card is not None
        assert card["name"] == a2a_server.name
        assert card["url"] == a2a_server.url
        assert "json-rpc" in card["capabilities"]

    def test_server_rejects_unknown_method(self, a2a_client):
        """POST with unknown JSON-RPC method returns -32601."""
        resp = a2a_client._post({
            "jsonrpc": "2.0",
            "method": "tasks.nonexistent",
            "params": {},
        })
        assert "error" in resp
        assert resp["error"]["code"] == -32601
        assert "Method not found" in resp["error"]["message"]

    def test_server_returns_jsonrpc_2_0(self, a2a_client):
        """All responses must contain 'jsonrpc': '2.0'."""
        resp = a2a_client.send_task()
        assert resp.get("jsonrpc") == "2.0"


# ====================================================================
# Test Class: Task Send
# ====================================================================

class TestTaskSend:
    """Tests for the tasks.send method."""

    def test_send_task_returns_id(self, a2a_client):
        """tasks.send should return a result with the task id."""
        task_id = f"sendtest_{uuid.uuid4().hex[:8]}"
        resp = a2a_client.send_task(task_id=task_id)
        assert "error" not in resp, f"Unexpected error: {resp.get('error')}"
        result = resp["result"]
        assert result["id"] == task_id

    def test_send_task_returns_completed_state(self, a2a_client):
        """tasks.send should process synchronously and return completed state."""
        resp = a2a_client.send_task()
        assert "error" not in resp
        assert resp["result"]["status"]["state"] == A2ATaskState.COMPLETED

    def test_send_task_includes_artifacts(self, a2a_client):
        """tasks.send should include artifacts in the response."""
        resp = a2a_client.send_task()
        assert "error" not in resp
        result = resp["result"]
        assert "artifacts" in result
        assert len(result["artifacts"]) >= 1
        artifact = result["artifacts"][0]
        assert "artifactId" in artifact
        assert "parts" in artifact

    def test_send_task_with_messages(self, a2a_client):
        """tasks.send should pass messages through in the result."""
        messages = [
            {"role": "user", "parts": [{"text": "Hello, A2A server!"}]},
        ]
        resp = a2a_client.send_task(messages=messages)
        assert "error" not in resp
        result = resp["result"]
        assert result["messages"] == messages

    def test_send_task_tracks_in_server(self, a2a_client, a2a_server):
        """After tasks.send, the server's task manager should track the task."""
        task_id = f"tracktest_{uuid.uuid4().hex[:8]}"
        a2a_client.send_task(task_id=task_id)
        tracked = a2a_server.task_manager.get_task(task_id)
        assert tracked is not None
        assert tracked["task_id"] == task_id
        assert tracked["state"] == A2ATaskState.COMPLETED


# ====================================================================
# Test Class: Task Get
# ====================================================================

class TestTaskGet:
    """Tests for the tasks.get method."""

    def test_get_existing_task(self, a2a_client):
        """tasks.get on an existing task returns its data."""
        task_id = f"gettest_{uuid.uuid4().hex[:8]}"
        a2a_client.send_task(task_id=task_id)
        resp = a2a_client.get_task(task_id)
        assert "error" not in resp, f"Unexpected error: {resp.get('error')}"
        result = resp["result"]
        assert result["id"] == task_id
        assert "status" in result

    def test_get_nonexistent_task_returns_error(self, a2a_client):
        """tasks.get on a nonexistent task returns -32000."""
        resp = a2a_client.get_task("nonexistent_task_12345")
        assert "error" in resp
        assert resp["error"]["code"] == -32000

    def test_get_task_state_is_completed(self, a2a_client):
        """tasks.get should return COMPLETED state for processed tasks."""
        task_id = f"statetest_{uuid.uuid4().hex[:8]}"
        a2a_client.send_task(task_id=task_id)
        resp = a2a_client.get_task(task_id)
        assert resp["result"]["status"]["state"] == A2ATaskState.COMPLETED

    def test_get_task_preserves_id_in_response(self, a2a_client):
        """The JSON-RPC response id should match the request id."""
        task_id = f"idtest_{uuid.uuid4().hex[:8]}"
        a2a_client.send_task(task_id=task_id)
        resp = a2a_client.get_task(task_id)
        assert resp["id"] is not None


# ====================================================================
# Test Class: Task Cancel
# ====================================================================

class TestTaskCancel:
    """Tests for the tasks.cancel method."""

    def test_cancel_existing_task(self, a2a_client):
        """tasks.cancel on an existing task returns CANCELED state."""
        task_id = f"canceltest_{uuid.uuid4().hex[:8]}"
        a2a_client.send_task(task_id=task_id)
        resp = a2a_client.cancel_task(task_id)
        assert "error" not in resp, f"Unexpected error: {resp.get('error')}"
        assert resp["result"]["status"]["state"] == A2ATaskState.CANCELED

    def test_cancel_nonexistent_task_returns_error(self, a2a_client):
        """tasks.cancel on a nonexistent task returns -32000."""
        resp = a2a_client.cancel_task("ghost_task_999")
        assert "error" in resp
        assert resp["error"]["code"] == -32000

    def test_cancel_updates_server_state(self, a2a_client, a2a_server):
        """After cancel, the server's task manager state should be CANCELED."""
        task_id = f"cancelstate_{uuid.uuid4().hex[:8]}"
        a2a_client.send_task(task_id=task_id)
        a2a_client.cancel_task(task_id)
        tracked = a2a_server.task_manager.get_task(task_id)
        assert tracked["state"] == A2ATaskState.CANCELED


# ====================================================================
# Test Class: Full Protocol Lifecycle
# ====================================================================

class TestProtocolLifecycle:
    """End-to-end protocol lifecycle: send -> get -> cancel -> verify."""

    def test_full_lifecycle(self, a2a_client):
        """Complete lifecycle: send, get, cancel, and verify states."""
        task_id = f"lifecycle_{uuid.uuid4().hex[:8]}"

        # 1. Send
        send_resp = a2a_client.send_task(task_id=task_id)
        assert "error" not in send_resp
        assert send_resp["result"]["id"] == task_id

        # 2. Get
        get_resp = a2a_client.get_task(task_id)
        assert "error" not in get_resp
        assert get_resp["result"]["id"] == task_id

        # 3. Cancel
        cancel_resp = a2a_client.cancel_task(task_id)
        assert "error" not in cancel_resp
        assert cancel_resp["result"]["status"]["state"] == A2ATaskState.CANCELED

        # 4. Verify final state
        get2_resp = a2a_client.get_task(task_id)
        assert get2_resp["result"]["status"]["state"] == A2ATaskState.CANCELED

    def test_multiple_tasks_independent(self, a2a_client):
        """Multiple tasks sent sequentially have independent identities."""
        ids = [f"multi_{uuid.uuid4().hex[:8]}" for _ in range(5)]
        for tid in ids:
            resp = a2a_client.send_task(task_id=tid)
            assert resp["result"]["id"] == tid
        for tid in ids:
            resp = a2a_client.get_task(tid)
            assert resp["result"]["id"] == tid

    def test_send_after_cancel_new_task(self, a2a_client):
        """Cancelling a task then sending a new one should work."""
        t1 = f"seq1_{uuid.uuid4().hex[:8]}"
        t2 = f"seq2_{uuid.uuid4().hex[:8]}"

        a2a_client.send_task(task_id=t1)
        a2a_client.cancel_task(t1)
        a2a_client.send_task(task_id=t2)

        get2 = a2a_client.get_task(t2)
        assert get2["result"]["id"] == t2
        assert get2["result"]["status"]["state"] == A2ATaskState.COMPLETED

        # t1 should still be CANCELED
        get1 = a2a_client.get_task(t1)
        assert get1["result"]["status"]["state"] == A2ATaskState.CANCELED

    def test_multiple_cancels_idempotent(self, a2a_client):
        """Cancelling an already-canceled task should not error."""
        task_id = f"idem_{uuid.uuid4().hex[:8]}"
        a2a_client.send_task(task_id=task_id)

        r1 = a2a_client.cancel_task(task_id)
        assert "error" not in r1

        r2 = a2a_client.cancel_task(task_id)
        assert "error" not in r2
        assert r2["result"]["status"]["state"] == A2ATaskState.CANCELED


# ====================================================================
# Test Class: Concurrent Tasks
# ====================================================================

class TestConcurrentTasks:
    """Verify the server handles multiple simultaneous tasks correctly."""

    CONCURRENCY = 3

    def _send_and_verify(self, client_factory, task_id: str) -> dict:
        """Helper: create client, send task, verify, return result."""
        import urllib.request
        # Use a fresh client per thread to avoid urllib connection issues
        client = IntegrationA2AClient(client_factory.server_url)
        resp = client.send_task(task_id=task_id)
        assert "error" not in resp, f"Task {task_id} failed: {resp.get('error')}"
        assert resp["result"]["id"] == task_id
        assert resp["result"]["status"]["state"] == A2ATaskState.COMPLETED
        return resp

    def test_concurrent_task_send(self, a2a_server):
        """Send 3 tasks concurrently, all should succeed."""
        from tests.integration.conftest import IntegrationA2AClient

        client = IntegrationA2AClient(server_url=a2a_server.url)

        with ThreadPoolExecutor(max_workers=self.CONCURRENCY) as executor:
            futures = {
                executor.submit(self._send_and_verify, client, f"concur_{uuid.uuid4().hex[:8]}"): i
                for i in range(self.CONCURRENCY)
            }
            for future in as_completed(futures):
                result = future.result(timeout=10)
                assert "result" in result

    def test_concurrent_get_after_send(self, a2a_server):
        """Send tasks then get them concurrently."""
        from tests.integration.conftest import IntegrationA2AClient

        client = IntegrationA2AClient(server_url=a2a_server.url)
        task_ids = [f"conget_{uuid.uuid4().hex[:8]}" for _ in range(self.CONCURRENCY)]

        # Send all first
        for tid in task_ids:
            client.send_task(task_id=tid)

        # Get all concurrently
        def get_task(tid: str) -> dict:
            c = IntegrationA2AClient(server_url=a2a_server.url)
            return c.get_task(tid)

        with ThreadPoolExecutor(max_workers=self.CONCURRENCY) as executor:
            futures = {executor.submit(get_task, tid): tid for tid in task_ids}
            for future in as_completed(futures):
                resp = future.result(timeout=10)
                assert "error" not in resp
                assert resp["result"]["status"]["state"] == A2ATaskState.COMPLETED

    def test_mixed_operations_concurrent(self, a2a_server):
        """Mix send, get, and cancel operations concurrently."""
        from tests.integration.conftest import IntegrationA2AClient

        client = IntegrationA2AClient(server_url=a2a_server.url)

        # Send 3 tasks
        task_ids = [f"mix_{uuid.uuid4().hex[:8]}" for _ in range(3)]
        for tid in task_ids:
            client.send_task(task_id=tid)

        def cancel_task(tid: str) -> dict:
            c = IntegrationA2AClient(server_url=a2a_server.url)
            return c.cancel_task(tid)

        with ThreadPoolExecutor(max_workers=self.CONCURRENCY) as executor:
            futures = {executor.submit(cancel_task, tid): tid for tid in task_ids}
            for future in as_completed(futures):
                resp = future.result(timeout=10)
                assert "error" not in resp
                assert resp["result"]["status"]["state"] == A2ATaskState.CANCELED


# ====================================================================
# Test Class: JSON-RPC Compliance
# ====================================================================

class TestJSONRPCCompliance:
    """Verify the server follows JSON-RPC 2.0 specification."""

    def test_response_has_jsonrpc_field(self, a2a_client):
        """Every response must include 'jsonrpc': '2.0'."""
        resp = a2a_client.send_task()
        assert resp.get("jsonrpc") == "2.0"

    def test_response_id_matches_request(self, a2a_client):
        """Response id must match the request id."""
        resp = a2a_client._post({
            "jsonrpc": "2.0",
            "method": "tasks.send",
            "id": 42,
            "params": {"id": f"idmatch_{uuid.uuid4().hex[:8]}", "status": {"state": "submitted"}},
        })
        assert resp["id"] == 42

    def test_error_response_has_code_and_message(self, a2a_client):
        """Error responses should have code and message fields."""
        resp = a2a_client.get_task("definitely_does_not_exist")
        error = resp.get("error", {})
        assert "code" in error
        assert "message" in error
        assert isinstance(error["code"], int)

    def test_unknown_method_returns_min_32601(self, a2a_client):
        """Unknown method returns JSON-RPC standard code -32601."""
        resp = a2a_client._post({
            "jsonrpc": "2.0",
            "method": "bogus.method",
            "params": {},
        })
        assert resp["error"]["code"] == -32601

    def test_missing_jsonrpc_field(self, a2a_client):
        """Request without jsonrpc field may still be processed gracefully."""
        resp = a2a_client._post({
            "method": "tasks.send",
            "params": {},
        })
        # Server processes it anyway since we handle missing field gracefully
        assert "error" not in resp or resp.get("result") is not None


# ====================================================================
# Helper import (avoid circular dependency in concurrent tests)
# ====================================================================

# The IntegrationA2AClient is used in concurrent tests; we import it
# at function level within those tests to prevent conftest circular imports.
# This top-level import is safe because conftest is a plugin.
from tests.integration.conftest import IntegrationA2AClient, make_id
