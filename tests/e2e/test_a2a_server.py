#!/usr/bin/env python3
"""End-to-end tests for the A2A HTTP Server (a2a_server.py).

These tests start a real FastAPI server, exercise the A2A protocol
over HTTP, and verify correctness of the HttpProvider client.

Usage:
    pytest tests/e2e/test_a2a_server.py -v                  # auto-start server
    pytest tests/e2e/test_a2a_server.py -v --server-port 8080  # existing server

Design:
    Tests use HttpProvider as client and expect a server at the
    configured port. A fixture manages server lifecycle when no
    existing server is detected (via /ping).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest

# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

try:
    from agentmesh.a2a_server import HttpProvider
    from agentmesh.a2a_provider import A2AError
except ImportError:
    # Not installed; insert repo root
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from agentmesh.a2a_server import HttpProvider
    from agentmesh.a2a_provider import A2AError


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVER_PORT = int(os.environ.get("A2A_SERVER_PORT", "8089"))
SERVER_URL = f"http://localhost:{SERVER_PORT}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _server_proc():
    """Start server, yield (proc, url), terminate on cleanup."""
    import urllib.request
    import urllib.error

    # Check if already running
    try:
        req = urllib.request.Request(f"{SERVER_URL}/ping", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return None  # Already running
    except Exception:
        pass

    script = os.path.join(os.path.dirname(__file__), "..", "..", "agentmesh", "a2a_server.py")
    proc = subprocess.Popen(
        [sys.executable, script, "server", "--port", str(SERVER_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    return proc


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestA2AServerProtocol(unittest.TestCase):
    """Verify the A2A HTTP protocol implementation."""

    @classmethod
    def setUpClass(cls):
        cls._proc = _server_proc()
        cls.client = HttpProvider(SERVER_URL, "test-client")

    @classmethod
    def tearDownClass(cls):
        if cls._proc:
            cls._proc.terminate()
            try:
                cls._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls._proc.kill()

    # --- Protocol correctness ---

    def test_ping(self):
        """Server responds to health check."""
        r = self.client.ping()
        self.assertTrue(r.success)
        self.assertEqual(r.data.get("status"), "ok")
        self.assertEqual(r.data.get("provider"), "a2a-server")

    def test_send_task(self):
        """Sending a task returns submitted state."""
        task = {"id": "ut_send_01", "status": {"state": "submitted"}, "payload": {"text": "hello"}}
        r = self.client.send_message(task)
        self.assertTrue(r.success)
        self.assertEqual(r.task_state, "submitted")

    def test_get_task(self):
        """Get a previously sent task."""
        task = {"id": "ut_get_01", "status": {"state": "submitted"}, "payload": {}}
        self.client.send_message(task)
        r = self.client.get_task("ut_get_01")
        self.assertTrue(r.success)
        self.assertEqual(r.data["id"], "ut_get_01")

    def test_cancel_task(self):
        """Cancel a task transitions it to canceled."""
        task = {"id": "ut_cancel_01", "status": {"state": "submitted"}, "payload": {}}
        self.client.send_message(task)
        r = self.client.cancel_task("ut_cancel_01")
        self.assertTrue(r.success)
        self.assertEqual(r.task_state, "canceled")

    def test_get_nonexistent_task(self):
        """Getting a nonexistent task returns a 404 error."""
        r = self.client.get_task("ut_nonexistent")
        self.assertFalse(r.success)
        self.assertIsNotNone(r.error)
        self.assertEqual(r.error.code, 404)

    def test_cancel_nonexistent_task(self):
        """Cancelling a nonexistent task returns a 404 error."""
        r = self.client.cancel_task("ut_nonexistent_cancel")
        self.assertFalse(r.success)
        self.assertIsNotNone(r.error)
        self.assertEqual(r.error.code, 404)

    def test_empty_task_id(self):
        """Sending a task with empty id returns an error."""
        task = {"id": "", "status": {"state": "submitted"}, "payload": {}}
        r = self.client.send_message(task)
        self.assertFalse(r.success)

    def test_register_agent(self):
        """Register an agent card via HttpProvider."""
        r = self.client.register_agent("test-bot", ["coding", "debug"])
        self.assertTrue(r.success)

    def test_send_get_cancel_lifecycle(self):
        """Complete task lifecycle: send → get → cancel → verify."""
        task = {"id": "ut_lifecycle_01", "status": {"state": "submitted"}, "payload": {"text": "lifecycle"}}
        
        r1 = self.client.send_message(task)
        self.assertTrue(r1.success)
        self.assertEqual(r1.task_state, "submitted")

        r2 = self.client.get_task("ut_lifecycle_01")
        self.assertTrue(r2.success)
        self.assertEqual(r2.data["id"], "ut_lifecycle_01")

        r3 = self.client.cancel_task("ut_lifecycle_01")
        self.assertTrue(r3.success)
        self.assertEqual(r3.task_state, "canceled")

        r4 = self.client.get_task("ut_lifecycle_01")
        self.assertTrue(r4.success)
        self.assertEqual(r4.data["status"]["state"], "canceled")

    def test_multiple_tasks(self):
        """Server handles multiple concurrent tasks."""
        ids = [f"ut_multi_{i:03d}" for i in range(10)]
        for tid in ids:
            task = {"id": tid, "status": {"state": "submitted"}, "payload": {"n": tid}}
            r = self.client.send_message(task)
            self.assertTrue(r.success)

        for tid in ids:
            r = self.client.get_task(tid)
            self.assertTrue(r.success)
            self.assertEqual(r.data["id"], tid)

    def test_hup_via_facade(self):
        """HttpProvider works when wrapped in A2AFacade."""
        from agentmesh.a2a_provider import A2AFacade

        facade = A2AFacade(provider=self.client)
        task = {"id": "ut_facade_01", "status": {"state": "submitted"}, "payload": {}}
        r = facade.send_task(task)
        self.assertTrue(r.success)

        r2 = facade.get_task("ut_facade_01")
        self.assertTrue(r2.success)


# ---------------------------------------------------------------------------
# Run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
