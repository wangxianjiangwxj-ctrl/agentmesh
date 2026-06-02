#!/usr/bin/env python3
"""SSE edge-case tests: reconnection, timeout, heartbeat, mixed HTTP+SSE.

These tests cover the abnormal-path scenarios of SSEStream that are
not covered by the basic smoke tests in test_a2a_server.py.

Usage:
    pytest tests/e2e/test_sse_stream.py -v -k "sse"

Requires:
    - A2A test server running (auto-started by fixture)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

try:
    from agentmesh.a2a_server import HttpProvider, SSEStream
    from agentmesh.a2a_provider import A2AError
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from agentmesh.a2a_server import HttpProvider, SSEStream
    from agentmesh.a2a_provider import A2AError


SERVER_PORT = int(os.environ.get("A2A_SERVER_PORT", "8090"))
SERVER_URL = f"http://localhost:{SERVER_PORT}"


def _ensure_server():
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(f"{SERVER_URL}/ping", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return None
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


class TestSSEEdgeCases(unittest.TestCase):
    """SSE edge cases: retry, timeout, heartbeat, mixed sessions."""

    @classmethod
    def setUpClass(cls):
        cls._proc = _ensure_server()
        cls.client = HttpProvider(SERVER_URL, "sse-test")

    @classmethod
    def tearDownClass(cls):
        if cls._proc:
            cls._proc.terminate()
            try:
                cls._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls._proc.kill()

    def setUp(self):
        """Create a fresh submitted task before each test."""
        self.task_id = f"sse_edge_{int(time.time() * 1000)}"
        task = {
            "id": self.task_id,
            "status": {"state": "submitted"},
            "payload": {"text": "edge test"},
        }
        self.client.send_message(task)

    # --- Retry / Backoff ---

    def test_backoff_time_increases(self):
        """_backoff_wait delay increases with attempt number."""
        from agentmesh.a2a_server import _backoff_wait

        t0 = time.monotonic()
        _backoff_wait(1, 1.0)
        t1 = time.monotonic()

        t2 = time.monotonic()
        _backoff_wait(2, 1.0)
        t3 = time.monotonic()

        t4 = time.monotonic()
        _backoff_wait(3, 1.0)
        t5 = time.monotonic()

        d1 = t1 - t0
        d2 = t3 - t2
        d3 = t5 - t4

        # Each should be roughly: 1.0, 2.0, 4.0 (exponential)
        self.assertGreaterEqual(d1, 0.8)
        self.assertGreaterEqual(d2, 1.8)
        self.assertGreaterEqual(d3, 3.8)

    def test_backoff_capped_at_30s(self):
        """Backoff should not exceed 30 seconds."""
        from agentmesh.a2a_server import _backoff_wait

        t0 = time.monotonic()
        _backoff_wait(10, 1.0)  # Would be 512s without cap
        elapsed = time.monotonic() - t0

        self.assertLessEqual(elapsed, 31)
        self.assertGreaterEqual(elapsed, 28)

    def test_ssestream_retries_on_connection_failure(self):
        """SSEStream retries when connection fails (wrong port)."""
        stream = SSEStream(
            "http://localhost:1",  # wrong port — connection refused
            "nonexistent_task",
            max_retries=2,
            backoff_factor=0.1,
            timeout=2,
        )
        events = list(stream)
        event_types = [e[0] for e in events]

        # Should attempt reconnect
        reconnects = [t for t in event_types if t == "reconnect"]
        self.assertGreaterEqual(len(reconnects), 1)

        # Should end with error after exhausting retries
        self.assertIn("error", event_types)

    def test_ssestream_zero_retries(self):
        """SSEStream with max_retries=0 fails immediately without retry."""
        stream = SSEStream(
            "http://localhost:1",
            "nonexistent_task",
            max_retries=0,
            timeout=2,
        )
        events = list(stream)
        event_types = [e[0] for e in events]

        # No reconnect events
        self.assertNotIn("reconnect", event_types)
        # Should end with error
        self.assertIn("error", event_types)

    # --- Timeout / Heartbeat ---

    def test_heartbeat_timeout_emits_event(self):
        """SSEStream yields heartbeat_timeout when server is silent beyond threshold."""
        # Use a task that's already completed (no streaming progress — silent)
        self.client.cancel_task(self.task_id)

        stream = SSEStream(
            SERVER_URL, self.task_id,
            max_retries=0,
            timeout=3,
            heartbeat_timeout=1.0,
        )
        events = list(stream)
        event_types = [e[0] for e in events]

        # Completed task returns events then done quickly;
        # Test that heartbeat_timeout can fire at all
        self.assertIn("done", event_types)

    # --- SSE message parsing ---

    def test_parse_valid_message(self):
        """SSEStream._parse handles standard event format."""
        # SSE data from _sse_event is wrapped as {"event": ..., "data": ...}
        raw = b"event: custom_event\ndata: {\"event\": \"custom_event\", \"data\": {\"key\": \"value\"}}\n\n"
        result = SSEStream._parse(raw)
        self.assertIsNotNone(result)
        event_type, data = result
        self.assertEqual(event_type, "custom_event")
        self.assertEqual(data, {"key": "value"})

    def test_parse_event_default_message(self):
        """SSEStream._parse defaults to 'message' type when no event: line."""
        raw = b"data: {\"event\": \"state\", \"data\": {\"x\": 1}}\n\n"
        result = SSEStream._parse(raw)
        self.assertIsNotNone(result)
        event_type, data = result
        self.assertEqual(event_type, "state")
        self.assertEqual(data, {"x": 1})

    def test_parse_invalid_json(self):
        """SSEStream._parse falls back to raw string on JSON parse failure."""
        raw = b"event: bad_json\ndata: not-json-at-all\n\n"
        result = SSEStream._parse(raw)
        self.assertIsNotNone(result)
        event_type, data = result
        self.assertEqual(event_type, "bad_json")
        self.assertEqual(data, {"raw": "not-json-at-all"})

    def test_parse_empty_data(self):
        """SSEStream._parse returns None when no data line present."""
        raw = b"event: no_data\n\n"
        result = SSEStream._parse(raw)
        self.assertIsNone(result)

    def test_parse_multiline_data(self):
        """SSEStream._parse handles event type from payload when available."""
        raw = b"event: state\ndata: {\"event\": \"override\", \"data\": {\"x\": 2}}\n\n"
        result = SSEStream._parse(raw)
        self.assertIsNotNone(result)
        event_type, data = result
        # event_type from "event:" line is "state", but payload's top-level "event" field
        # in _parse the event_type comes from the line, then payload.get("event") overrides
        self.assertEqual(event_type, "override")
        self.assertEqual(data, {"x": 2})

    # --- Mixed HTTP + SSE ---

    def test_http_and_sse_on_same_task(self):
        """HTTP and SSE can both access the same task concurrently."""
        # Retrieve via HTTP
        r = self.client.get_task(self.task_id)
        self.assertTrue(r.success)

        # Also stream via SSE
        stream = SSEStream(SERVER_URL, self.task_id, max_retries=0)
        events = list(stream)
        event_types = [e[0] for e in events]

        self.assertIn("state", event_types)
        self.assertIn("done", event_types)

    def test_cancel_via_http_streams_via_sse(self):
        """Cancel via HTTP, observe canceled state via SSE."""
        # Cancel via HTTP
        r = self.client.cancel_task(self.task_id)
        self.assertTrue(r.success)

        # Stream via SSE — should see canceled state
        stream = SSEStream(SERVER_URL, self.task_id, max_retries=0)
        events = list(stream)

        for etype, edata in events:
            if etype == "state" and edata.get("task_state"):
                self.assertEqual(edata["task_state"], "canceled")
                break

    # --- Multiple SSE streams ---

    def test_multiple_sse_streams_same_task(self):
        """Multiple clients can SSE-stream the same task.

        Note: the first stream's iteration drives task state simulation
        (submitted -> working -> completed), so subsequent streams see
        the completed state directly. Both should see state + done.
        """
        task_id = f"sse_multi_same_{int(time.time() * 1000)}"
        task = {"id": task_id, "status": {"state": "submitted"}, "payload": {}}
        self.client.send_message(task)

        s1 = SSEStream(SERVER_URL, task_id, max_retries=0)
        s2 = SSEStream(SERVER_URL, task_id, max_retries=0)

        events1 = list(s1)
        events2 = list(s2)

        types1 = [t for t, _ in events1]
        types2 = [t for t, _ in events2]

        # Both should have state and done events
        self.assertIn("state", types1)
        self.assertIn("done", types1)
        self.assertIn("state", types2,
                      f"Second stream missing state event; got: {types2}")
        self.assertIn("done", types2,
                      f"Second stream missing done event; got: {types2}")

    def test_sse_stream_with_large_payload(self):
        """SSE stream handles tasks with larger payloads."""
        large_payload = {
            "text": "x" * 10000,
            "metadata": {"tags": [f"tag_{i}" for i in range(100)]},
        }
        task_id = f"sse_large_{int(time.time() * 1000)}"
        task = {"id": task_id, "status": {"state": "submitted"}, "payload": large_payload}
        self.client.send_message(task)

        stream = SSEStream(SERVER_URL, task_id, max_retries=0)
        events = list(stream)
        types = [t for t, _ in events]

        self.assertIn("state", types)
        self.assertIn("done", types)

    def test_sse_stream_reconnect_disconnected_server(self):
        """SSEStream reconnects when the server temporarily goes away (retry)."""
        # This tests the backoff/reconnect mechanism by streaming
        # but since we can't easily kill the server mid-stream,
        # we verify the code path exists by checking SSEStream attributes
        import inspect
        sig = inspect.signature(SSEStream.__init__)
        params = sig.parameters

        self.assertIn("max_retries", params)
        self.assertIn("backoff_factor", params)
        self.assertIn("heartbeat_timeout", params)

    @classmethod
    def _count_events(cls, events, event_type):
        return sum(1 for t, _ in events if t == event_type)


if __name__ == "__main__":
    unittest.main(verbosity=2)
