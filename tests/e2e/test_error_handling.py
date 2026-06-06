#!/usr/bin/env python3
"""End-to-end tests for unified A2A error handling.

Verifies that all exceptions from the A2A server return a consistent
JSON error format, and that sensitive information (tracebacks) is not
leaked in error responses.

Usage:
    pytest tests/e2e/test_error_handling.py -v
    pytest tests/e2e/test_error_handling.py -v --server-port 8091

Design:
    Tests use HttpProvider as client and a self-started server.
    The error handling middleware in a2a_server.py converts all
    exceptions to the unified format:
        {"error": {"code": "ERROR_CODE", "message": "Human-readable message"}}
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

try:
    from agentmesh.a2a_provider import A2AError, ProviderError
    from agentmesh.a2a_server import ERROR_CODE_MAP, A2AServerError, HttpProvider
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from agentmesh.a2a_provider import A2AError, ProviderError
    from agentmesh.a2a_server import ERROR_CODE_MAP, A2AServerError, HttpProvider

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVER_PORT = int(os.environ.get("A2A_SERVER_PORT", "8091"))
SERVER_URL = f"http://localhost:{SERVER_PORT}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _ensure_server():
    """Start server, return (proc, url) or (None, url) if already running."""
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


# ---------------------------------------------------------------------------
# Helper: raw HTTP request (bypasses HttpProvider to inspect raw JSON)
# ---------------------------------------------------------------------------

def _raw_get(path: str) -> tuple[int, dict]:
    """Perform a raw GET and return (status_code, parsed_json)."""
    url = SERVER_URL + path
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return (resp.status, json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return (e.code, json.loads(body))
        except (json.JSONDecodeError, ValueError):
            return (e.code, {"raw": body})


def _raw_post(path: str, body: dict) -> tuple[int, dict]:
    """Perform a raw POST and return (status_code, parsed_json)."""
    url = SERVER_URL + path
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return (resp.status, json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return (e.code, json.loads(body))
        except (json.JSONDecodeError, ValueError):
            return (e.code, {"raw": body})


# ---------------------------------------------------------------------------
# Test: A2AServerError and ProviderError class behavior
# ---------------------------------------------------------------------------

class TestErrorClasses(unittest.TestCase):
    """Verify A2AServerError and ProviderError constructors."""

    def test_a2a_server_error_holds_fields(self):
        exc = A2AServerError(status_code=404, code="TASK_NOT_FOUND",
                             message="Task abc not found")
        self.assertEqual(exc.status_code, 404)
        self.assertEqual(exc.code, "TASK_NOT_FOUND")
        self.assertEqual(exc.message, "Task abc not found")

    def test_a2a_server_error_defaults(self):
        exc = A2AServerError(status_code=500, code="INTERNAL_ERROR",
                             message="Oops")
        self.assertEqual(exc.status_code, 500)
        self.assertEqual(exc.code, "INTERNAL_ERROR")

    def test_provider_error_is_a2a_error(self):
        exc = ProviderError(code=503, message="Upstream unavailable")
        self.assertIsInstance(exc, A2AError)
        self.assertEqual(exc.code, 503)
        self.assertTrue(exc.recoverable)

    def test_provider_error_defaults(self):
        exc = ProviderError()
        self.assertEqual(exc.code, 500)
        self.assertEqual(exc.message, "Provider error")
        self.assertTrue(exc.recoverable)


# ---------------------------------------------------------------------------
# Test: Unified error response format via HTTP
# ---------------------------------------------------------------------------

class TestUnifiedErrorResponse(unittest.TestCase):
    """Verify that server errors return the unified JSON format."""

    @classmethod
    def setUpClass(cls):
        cls._proc = _ensure_server()
        cls.client = HttpProvider(SERVER_URL, "error-test-client")

    @classmethod
    def tearDownClass(cls):
        if cls._proc:
            cls._proc.terminate()
            try:
                cls._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls._proc.kill()

    # --- Unified format structure ---

    def test_error_response_has_error_key(self):
        """Every error response should have an 'error' key at the top level."""
        status, body = _raw_get("/nonexistent_route_xyz")
        self.assertIn("error", body,
                      f"Expected 'error' key in response: {body}")
        self.assertIsInstance(body["error"], dict)

    def test_error_response_has_code_and_message(self):
        """Error object should have 'code' (str) and 'message' (str)."""
        status, body = _raw_get("/task/nonexistent_404_test")
        self.assertIn("error", body)
        err = body["error"]
        self.assertIn("code", err, f"Missing 'code' in error: {err}")
        self.assertIn("message", err, f"Missing 'message' in error: {err}")
        self.assertIsInstance(err["code"], str,
                              f"Expected string code, got {type(err['code']).__name__}: {err}")

    def test_error_response_contains_no_traceback(self):
        """Sensitive details should not leak into error responses."""
        status, body = _raw_get("/task/nonexistent_no_traceback")
        body_str = json.dumps(body)
        self.assertNotIn("Traceback", body_str)
        self.assertNotIn("File \"", body_str)
        self.assertNotIn("line ", body_str)

    # --- Error code correctness ---

    def test_nonexistent_route_returns_404_not_found(self):
        """An undefined route should return 404 with NOT_FOUND code."""
        status, body = _raw_get("/this_route_does_not_exist")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "NOT_FOUND")

    def test_nonexistent_task_returns_404_task_not_found(self):
        """Getting a nonexistent task should return 404 TASK_NOT_FOUND."""
        status, body = _raw_get("/task/ut_eh_nonexistent")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "TASK_NOT_FOUND")

    def test_cancel_nonexistent_task_returns_404(self):
        """Canceling a nonexistent task should return 404 TASK_NOT_FOUND."""
        status, body = _raw_post("/cancel/ut_eh_no_such_cancel", {})
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "TASK_NOT_FOUND")

    def test_empty_task_id_returns_400_invalid_request(self):
        """Sending a task with empty id should return 400 INVALID_REQUEST."""
        status, body = _raw_post("/send", {"task": {"id": "", "status": {"state": "submitted"}, "payload": {}}})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "INVALID_REQUEST")

    # --- HttpProvider compatibility ---

    def test_http_provider_404_maps_correctly(self):
        """HttpProvider should correctly parse unified error format."""
        r = self.client.get_task("ut_eh_hp_nonexistent")
        self.assertFalse(r.success)
        self.assertIsNotNone(r.error)
        self.assertIsInstance(r.error, A2AError)
        self.assertEqual(r.error.code, 404)
        # Message should be descriptive
        self.assertIn("ut_eh_hp_nonexistent", r.error.message)

    def test_http_provider_cancel_404_maps_correctly(self):
        """HttpProvider cancel on nonexistent task returns 404 A2AError."""
        r = self.client.cancel_task("ut_eh_hp_cancel_nonexist")
        self.assertFalse(r.success)
        self.assertIsNotNone(r.error)
        self.assertEqual(r.error.code, 404)

    def test_http_provider_empty_id_400(self):
        """HttpProvider send with empty id returns 400 A2AError."""
        task = {"id": "", "status": {"state": "submitted"}, "payload": {}}
        r = self.client.send_message(task)
        self.assertFalse(r.success)
        self.assertIsNotNone(r.error)
        self.assertEqual(r.error.code, 400)

    # --- Error code map consistency ---

    def test_error_code_map_all_codes_present(self):
        """ERROR_CODE_MAP should have entries for all required statuses."""
        required = [400, 404, 405, 422, 429, 500, 503]
        for code in required:
            self.assertIn(code, ERROR_CODE_MAP,
                          f"Missing ERROR_CODE_MAP entry for {code}")
        # Verify string codes
        self.assertEqual(ERROR_CODE_MAP[400], "INVALID_REQUEST")
        self.assertEqual(ERROR_CODE_MAP[404], "NOT_FOUND")
        self.assertEqual(ERROR_CODE_MAP[500], "INTERNAL_ERROR")
        self.assertEqual(ERROR_CODE_MAP[503], "SERVICE_UNAVAILABLE")


# ---------------------------------------------------------------------------
# Test: Success responses should still work (no regression)
# ---------------------------------------------------------------------------

class TestSuccessResponseFormat(unittest.TestCase):
    """Verify successful responses still have their original format."""

    @classmethod
    def setUpClass(cls):
        cls._proc = _ensure_server()
        cls.client = HttpProvider(SERVER_URL, "success-test-client")

    @classmethod
    def tearDownClass(cls):
        if cls._proc:
            cls._proc.terminate()
            try:
                cls._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls._proc.kill()

    def test_ping_returns_expected_format(self):
        """Ping should still return the original success format."""
        r = self.client.ping()
        self.assertTrue(r.success)
        self.assertEqual(r.data.get("status"), "ok")

    def test_send_task_still_works(self):
        """Sending a valid task should still succeed."""
        task = {"id": "ut_success_01", "status": {"state": "submitted"}, "payload": {"text": "hello"}}
        r = self.client.send_message(task)
        self.assertTrue(r.success)
        self.assertEqual(r.task_state, "submitted")

    def test_get_task_still_works(self):
        """Getting an existing task should still work."""
        task = {"id": "ut_success_02", "status": {"state": "submitted"}, "payload": {}}
        self.client.send_message(task)
        r = self.client.get_task("ut_success_02")
        self.assertTrue(r.success)
        self.assertEqual(r.data["id"], "ut_success_02")

    def test_cancel_task_still_works(self):
        """Cancelling an existing task should still work."""
        task = {"id": "ut_success_03", "status": {"state": "submitted"}, "payload": {}}
        self.client.send_message(task)
        r = self.client.cancel_task("ut_success_03")
        self.assertTrue(r.success)
        self.assertEqual(r.task_state, "canceled")


# ---------------------------------------------------------------------------
# Run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
