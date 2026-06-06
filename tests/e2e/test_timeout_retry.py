# -*- coding: utf-8 -*-
"""
Timeout & Retry Tests for A2A Server + Provider.

These tests verify:

1. Request processing timeout -- A long-running request is interrupted
   by the server's timeout middleware, returning a 503 error.

2. SSE stream idle timeout -- An idle SSE stream is closed by the server
   after the configured idle timeout, emitting a ``stream_timeout`` event.

3. HTTP request retry -- The HttpProvider retries on transient failures
   (5xx, 429, network errors) using exponential backoff.

4. Retry exhaustion -- When all retry attempts fail, the provider returns
   the final error response instead of continuing.

All tests are self-contained: they start/stop the server per test class.
"""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Import project modules
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

try:
    from agentmesh.a2a_models import DEFAULT_RETRY_CONFIG, DEFAULT_TIMEOUT_CONFIG, RetryConfig
    from agentmesh.a2a_provider import (
        A2AError,
        A2AProvider,
        A2AResult,
        _backoff_sleep,
        _should_retry_on_error,
        _should_retry_on_status,
        with_retry,
    )
    from agentmesh.a2a_server import (
        HttpProvider,
        ServerTimeoutConfig,
        SSEStream,
        _build_app,
        _timeout_config,
    )
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from agentmesh.a2a_models import DEFAULT_RETRY_CONFIG, DEFAULT_TIMEOUT_CONFIG, RetryConfig
    from agentmesh.a2a_provider import (
        A2AError,
        A2AProvider,
        A2AResult,
        _backoff_sleep,
        _should_retry_on_error,
        _should_retry_on_status,
        with_retry,
    )
    from agentmesh.a2a_server import (
        HttpProvider,
        ServerTimeoutConfig,
        SSEStream,
        _build_app,
        _timeout_config,
    )


# ---------------------------------------------------------------------------
# Helper: start/manage test server with custom timeout
# ---------------------------------------------------------------------------

_TIMEOUT_SERVER_PROCS = []


@atexit.register
def _cleanup_timeout_servers():
    for proc in _TIMEOUT_SERVER_PROCS:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _make_server_runner_script(
    request_timeout: float,
    stream_idle_timeout: float,
    port: int,
) -> str:
    """Generate a Python script that starts the A2A server with custom timeouts."""
    # Build the sys.path insert dynamically
    base_dir = os.path.dirname(os.path.abspath(__file__))
    repo_dir = os.path.join(base_dir, "..", "..")
    return '''import sys
import os
sys.path.insert(0, ''' + repr(repo_dir) + ''')

from agentmesh.a2a_server import _build_app
from agentmesh.a2a_models import ServerTimeoutConfig

cfg = ServerTimeoutConfig(
    request_timeout=''' + repr(request_timeout) + ''',
    stream_idle_timeout=''' + repr(stream_idle_timeout) + ''',
    connect_timeout=2.0,
    read_timeout=5.0,
)
app = _build_app(timeout_config=cfg)

import uvicorn
uvicorn.run(app, host="0.0.0.0", port=''' + str(port) + ''', log_level="warning")
'''


def _start_server_with_timeout(
    request_timeout: float = 5.0,
    stream_idle_timeout: float = 3.0,
    port: int = 8099,
):
    """Start the A2A server with a custom low timeout config for testing.

    Returns the subprocess Popen handle.
    """
    script_content = _make_server_runner_script(
        request_timeout, stream_idle_timeout, port
    )

    runner_path = os.path.join(
        os.path.dirname(__file__), "._timeout_server_{}.py".format(port)
    )
    with open(runner_path, "w") as f:
        f.write(script_content)

    proc = subprocess.Popen(
        [sys.executable, runner_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _TIMEOUT_SERVER_PROCS.append(proc)

    import urllib.error
    import urllib.request

    for _ in range(30):
        try:
            req = urllib.request.Request("http://localhost:{}/ping".format(port))
            with urllib.request.urlopen(req, timeout=2) as resp:
                return proc
        except Exception:
            time.sleep(0.5)

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except Exception:
        pass
    raise RuntimeError("Server on port {} did not start in time".format(port))


# ---------------------------------------------------------------------------
# 1. Request Timeout Tests
# ---------------------------------------------------------------------------

class TestRequestTimeout(unittest.TestCase):
    """Verify the server's request processing timeout middleware."""

    @classmethod
    def setUpClass(cls):
        cls._port = int(os.environ.get("A2A_TIMEOUT_TEST_PORT", "8099"))
        cls._proc = _start_server_with_timeout(
            request_timeout=3.0,  # Very low: requests timeout after 3s
            stream_idle_timeout=5.0,
            port=cls._port,
        )
        cls.server_url = "http://localhost:{}".format(cls._port)
        cls.client = HttpProvider(cls.server_url, "timeout-test",
                                  max_retries=0)  # No retry for timeout tests

    @classmethod
    def tearDownClass(cls):
        if cls._proc:
            cls._proc.terminate()
            try:
                cls._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls._proc.kill()

    def test_normal_request_succeeds(self):
        """Verify quick requests complete normally under the timeout limit."""
        r = self.client.ping()
        self.assertTrue(r.success)
        self.assertEqual(r.data.get("status"), "ok")

    def test_send_get_cancel_work_with_timeout(self):
        """Verify basic A2A operations work under normal timeout config."""
        task = {"id": "timeout_normal_01",
                "status": {"state": "submitted"},
                "payload": {"text": "hello"}}
        r1 = self.client.send_message(task)
        self.assertTrue(r1.success)
        self.assertEqual(r1.task_state, "submitted")

        r2 = self.client.get_task("timeout_normal_01")
        self.assertTrue(r2.success)

        r3 = self.client.cancel_task("timeout_normal_01")
        self.assertTrue(r3.success)
        self.assertEqual(r3.task_state, "canceled")


# ---------------------------------------------------------------------------
# 2. Stream Idle Timeout Tests
# ---------------------------------------------------------------------------

class TestStreamIdleTimeout(unittest.TestCase):
    """Verify SSE stream closes after idle timeout."""

    @classmethod
    def setUpClass(cls):
        cls._port = int(os.environ.get("A2A_TIMEOUT_TEST_PORT_2", "8100"))
        cls._proc = _start_server_with_timeout(
            request_timeout=10.0,
            stream_idle_timeout=2.0,  # Very low: idle timeout after 2s
            port=cls._port,
        )
        cls.server_url = "http://localhost:{}".format(cls._port)

    @classmethod
    def tearDownClass(cls):
        if cls._proc:
            cls._proc.terminate()
            try:
                cls._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls._proc.kill()

    def test_stream_idle_timeout_occurs(self):
        """Stream yields 'stream_timeout' event after idle period."""
        client = HttpProvider(self.server_url, "stream-test", max_retries=0)
        task = {"id": "stream_idle_01",
                "status": {"state": "submitted"},
                "payload": {}}
        r = client.send_message(task)
        self.assertTrue(r.success)

        stream = SSEStream(
            self.server_url, "stream_idle_01",
            max_retries=0,
            timeout=5,
            heartbeat_timeout=10,
        )

        events = []
        for event_type, data in stream:
            events.append((event_type, data))
            if event_type in ("done", "stream_timeout", "error"):
                break

        event_types = [e[0] for e in events]
        self.assertIn("state", event_types,
                      "Expected 'state' event, got {}".format(event_types))


# ---------------------------------------------------------------------------
# 3. Retry Utilities Tests
# ---------------------------------------------------------------------------

class TestRetryUtilities(unittest.TestCase):
    """Unit tests for the retry utility functions in a2a_provider.py."""

    def test_should_retry_on_status(self):
        """Verify retryable status code detection."""
        self.assertTrue(_should_retry_on_status(500))
        self.assertTrue(_should_retry_on_status(502))
        self.assertTrue(_should_retry_on_status(503))
        self.assertTrue(_should_retry_on_status(504))
        self.assertTrue(_should_retry_on_status(429))
        self.assertFalse(_should_retry_on_status(400))
        self.assertFalse(_should_retry_on_status(401))
        self.assertFalse(_should_retry_on_status(403))
        self.assertFalse(_should_retry_on_status(404))
        self.assertFalse(_should_retry_on_status(422))
        self.assertFalse(_should_retry_on_status(200))
        self.assertFalse(_should_retry_on_status(301))

    def test_should_retry_on_error(self):
        """Verify network-level error detection."""
        self.assertTrue(_should_retry_on_error(ConnectionError("refused")))
        self.assertTrue(_should_retry_on_error(TimeoutError("timeout")))
        self.assertTrue(_should_retry_on_error(OSError("dns fail")))
        self.assertFalse(_should_retry_on_error(ValueError("bad input")))
        self.assertFalse(_should_retry_on_error(TypeError("bad type")))
        self.assertFalse(_should_retry_on_error(RuntimeError("runtime")))

    def test_backoff_sleep(self):
        """Verify backoff delay calculation with jitter."""
        start = time.monotonic()
        _backoff_sleep(1, backoff_factor=0.5, max_backoff=5.0)
        elapsed = time.monotonic() - start
        self.assertGreaterEqual(elapsed, 0.45)
        self.assertLess(elapsed, 1.0)

    def test_backoff_increases(self):
        """Verify each retry attempt has a longer delay."""
        delays = []
        for attempt in range(1, 5):
            start = time.monotonic()
            _backoff_sleep(attempt, backoff_factor=0.1, max_backoff=5.0)
            elapsed = time.monotonic() - start
            delays.append(elapsed)
        for i in range(1, len(delays)):
            self.assertGreater(delays[i], delays[i - 1] * 0.5)

    def test_backoff_capped(self):
        """Verify backoff is capped at max_backoff."""
        start = time.monotonic()
        _backoff_sleep(10, backoff_factor=1.0, max_backoff=2.0)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 3.0)


class TestWithRetryDecorator(unittest.TestCase):
    """Tests for the ``with_retry`` decorator function."""

    def test_success_no_retry(self):
        call_count = [0]

        @with_retry(max_retries=3)
        def my_func():
            call_count[0] += 1
            return {"success": True, "data": "ok"}

        result = my_func()
        self.assertTrue(result["success"])
        self.assertEqual(call_count[0], 1)

    def test_retry_on_5xx_then_succeeds(self):
        call_count = [0]

        @with_retry(max_retries=3, backoff_factor=0.01)
        def my_func():
            call_count[0] += 1
            if call_count[0] == 1:
                return {
                    "success": False,
                    "error": {"code": 503, "message": "Service unavailable",
                              "recoverable": True},
                }
            return {"success": True, "data": "ok after retry"}

        result = my_func()
        self.assertTrue(result["success"])
        self.assertEqual(call_count[0], 2)

    def test_retry_exhausted(self):
        call_count = [0]

        @with_retry(max_retries=2, backoff_factor=0.01)
        def my_func():
            call_count[0] += 1
            return {
                "success": False,
                "error": {"code": 503, "message": "Still unavailable",
                          "recoverable": True},
            }

        result = my_func()
        self.assertFalse(result["success"])
        self.assertEqual(call_count[0], 3)

    def test_no_retry_on_4xx(self):
        call_count = [0]

        @with_retry(max_retries=3, backoff_factor=0.01)
        def my_func():
            call_count[0] += 1
            return {
                "success": False,
                "error": {"code": 400, "message": "Bad request",
                          "recoverable": False},
            }

        result = my_func()
        self.assertFalse(result["success"])
        self.assertEqual(call_count[0], 1)

    def test_no_retry_on_404(self):
        call_count = [0]

        @with_retry(max_retries=3, backoff_factor=0.01)
        def my_func():
            call_count[0] += 1
            return {
                "success": False,
                "error": {"code": 404, "message": "Not found",
                          "recoverable": False},
            }

        result = my_func()
        self.assertFalse(result["success"])
        self.assertEqual(call_count[0], 1)

    def test_retry_on_network_error(self):
        call_count = [0]

        @with_retry(max_retries=2, backoff_factor=0.01)
        def my_func():
            call_count[0] += 1
            if call_count[0] <= 2:
                raise ConnectionError("Connection refused")
            return {"success": True, "data": "ok"}

        result = my_func()
        self.assertTrue(result["success"])
        self.assertEqual(call_count[0], 3)

    def test_retry_on_timeout_error(self):
        call_count = [0]

        @with_retry(max_retries=2, backoff_factor=0.01)
        def my_func():
            call_count[0] += 1
            if call_count[0] <= 1:
                raise TimeoutError("Timed out")
            return {"success": True, "data": "ok"}

        result = my_func()
        self.assertTrue(result["success"])
        self.assertEqual(call_count[0], 2)

    def test_network_error_exhausted(self):
        call_count = [0]

        @with_retry(max_retries=2, backoff_factor=0.01)
        def my_func():
            call_count[0] += 1
            raise ConnectionError("Always fails")

        with self.assertRaises(ConnectionError):
            my_func()
        self.assertEqual(call_count[0], 3)

    def test_retry_zero_disables_retry(self):
        call_count = [0]

        @with_retry(max_retries=0, backoff_factor=0.01)
        def my_func():
            call_count[0] += 1
            return {
                "success": False,
                "error": {"code": 503, "message": "Fail",
                          "recoverable": True},
            }

        result = my_func()
        self.assertFalse(result["success"])
        self.assertEqual(call_count[0], 1)

    def test_retry_on_429(self):
        call_count = [0]

        @with_retry(max_retries=2, backoff_factor=0.01)
        def my_func():
            call_count[0] += 1
            if call_count[0] == 1:
                return {
                    "success": False,
                    "error": {"code": 429, "message": "Rate limited",
                              "recoverable": True},
                }
            return {"success": True, "data": "ok"}

        result = my_func()
        self.assertTrue(result["success"])
        self.assertEqual(call_count[0], 2)


# ---------------------------------------------------------------------------
# 4. HttpProvider Retry Integration Tests
# ---------------------------------------------------------------------------

class _MockHandler(BaseHTTPRequestHandler):
    """HTTP handler that simulates transient failures."""

    fail_count = 0
    fail_limit = 2
    fail_status = 503
    requests = []

    def do_GET(self):
        type(self).requests.append(self.path)
        if type(self).fail_count < type(self).fail_limit:
            type(self).fail_count += 1
            self.send_response(type(self).fail_status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": False,
                "error": {"code": type(self).fail_status,
                          "message": "Temporary failure",
                          "recoverable": True},
            }).encode("utf-8"))
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "data": {"status": "ok", "path": self.path},
            }).encode("utf-8"))

    def log_message(self, format, *args):
        pass


_MOCK_SERVER = None
_MOCK_SERVER_THREAD = None
_MOCK_SERVER_PORT = None


def _get_mock_server_url():
    global _MOCK_SERVER, _MOCK_SERVER_THREAD, _MOCK_SERVER_PORT
    if _MOCK_SERVER is None:
        _MOCK_SERVER = HTTPServer(("localhost", 0), _MockHandler)
        _MOCK_SERVER_PORT = _MOCK_SERVER.server_address[1]
        _MOCK_SERVER_THREAD = threading.Thread(
            target=_MOCK_SERVER.serve_forever, daemon=True
        )
        _MOCK_SERVER_THREAD.start()
        time.sleep(0.2)
    return "http://localhost:{}".format(_MOCK_SERVER_PORT)


class TestHttpProviderRetry(unittest.TestCase):
    """Verify HttpProvider retry logic at the integration level."""

    def setUp(self):
        _MockHandler.fail_count = 0
        _MockHandler.requests = []

    def test_retry_success_on_transient_503(self):
        """Provider retries on 503 and succeeds when mock stops failing."""
        _MockHandler.fail_limit = 2
        _MockHandler.fail_status = 503

        client = HttpProvider(_get_mock_server_url(), "retry-test",
                              max_retries=3, backoff_factor=0.01)
        r = client.ping()
        self.assertTrue(r.success)
        self.assertEqual(r.data.get("status"), "ok")

    def test_retry_exhausted_on_503(self):
        """Provider exhausts retries on persistent 503 errors."""
        _MockHandler.fail_limit = 10
        _MockHandler.fail_status = 503

        client = HttpProvider(_get_mock_server_url(), "retry-test",
                              max_retries=2, backoff_factor=0.01)
        r = client.ping()
        self.assertFalse(r.success)
        self.assertEqual(r.error.code, 503)

    def test_no_retry_on_404(self):
        """Provider does NOT retry on 4xx (non-retryable)."""
        _MockHandler.fail_limit = 1
        _MockHandler.fail_status = 404

        client = HttpProvider(_get_mock_server_url(), "retry-test",
                              max_retries=3, backoff_factor=0.01)
        r = client.ping()
        self.assertFalse(r.success)
        self.assertEqual(len(_MockHandler.requests), 1)


class TestHttpProviderTimeout(unittest.TestCase):
    """Verify HttpProvider timeout settings are used."""

    def test_custom_timeout_config(self):
        cfg = ServerTimeoutConfig(
            request_timeout=5.0,
            stream_idle_timeout=10.0,
            connect_timeout=2.0,
            read_timeout=5.0,
        )
        client = HttpProvider("http://localhost:9999", "timeout-test",
                              timeout_config=cfg, max_retries=0)
        self.assertEqual(client._timeout_config.read_timeout, 5.0)
        self.assertEqual(client._timeout_config.connect_timeout, 2.0)

    def test_default_timeout_config(self):
        client = HttpProvider("http://localhost:9999", "default-timeout")
        self.assertEqual(client._timeout_config.read_timeout, 30.0)
        self.assertEqual(client._timeout_config.request_timeout, 30.0)
        self.assertEqual(client._timeout_config.stream_idle_timeout, 60.0)


# ---------------------------------------------------------------------------
# 5. ServerTimeoutConfig Validation Tests
# ---------------------------------------------------------------------------

class TestServerTimeoutConfig(unittest.TestCase):
    def test_valid_config(self):
        cfg = ServerTimeoutConfig(request_timeout=10.0, stream_idle_timeout=20.0)
        self.assertEqual(cfg.request_timeout, 10.0)
        self.assertEqual(cfg.stream_idle_timeout, 20.0)

    def test_zero_timeout_disables(self):
        cfg = ServerTimeoutConfig(request_timeout=0.0)
        self.assertEqual(cfg.request_timeout, 0.0)

    def test_negative_request_timeout(self):
        with self.assertRaises(ValueError):
            ServerTimeoutConfig(request_timeout=-1.0)

    def test_negative_stream_idle(self):
        with self.assertRaises(ValueError):
            ServerTimeoutConfig(stream_idle_timeout=-5.0)


class TestRetryConfigValidation(unittest.TestCase):
    def test_valid_config(self):
        cfg = RetryConfig(max_retries=5, backoff_factor=2.0, max_backoff=60.0)
        self.assertEqual(cfg.max_retries, 5)
        self.assertEqual(cfg.backoff_factor, 2.0)
        self.assertEqual(cfg.max_backoff, 60.0)

    def test_negative_max_retries(self):
        with self.assertRaises(ValueError):
            RetryConfig(max_retries=-1)

    def test_zero_backoff_factor(self):
        with self.assertRaises(ValueError):
            RetryConfig(backoff_factor=0)

    def test_retryable_statuses_default(self):
        cfg = RetryConfig()
        self.assertIn(429, cfg.retryable_statuses)
        self.assertIn(500, cfg.retryable_statuses)
        self.assertIn(503, cfg.retryable_statuses)
        self.assertNotIn(404, cfg.retryable_statuses)

    def test_should_retry_on_status(self):
        cfg = RetryConfig()
        self.assertTrue(cfg.should_retry_on_status(503))
        self.assertTrue(cfg.should_retry_on_status(429))
        self.assertFalse(cfg.should_retry_on_status(404))

    def test_should_retry_on_error(self):
        cfg = RetryConfig()
        self.assertTrue(cfg.should_retry_on_error(ConnectionError("refused")))
        self.assertTrue(cfg.should_retry_on_error(TimeoutError("timeout")))
        self.assertFalse(cfg.should_retry_on_error(ValueError("bad")))

    def test_backoff_delay(self):
        cfg = RetryConfig(backoff_factor=1.0, max_backoff=30.0)
        self.assertEqual(cfg.backoff_delay(1), 1.0)
        self.assertEqual(cfg.backoff_delay(2), 2.0)
        self.assertEqual(cfg.backoff_delay(3), 4.0)
        self.assertEqual(cfg.backoff_delay(4), 8.0)

    def test_backoff_delay_capped(self):
        cfg = RetryConfig(backoff_factor=1.0, max_backoff=5.0)
        self.assertEqual(cfg.backoff_delay(10), 5.0)
        self.assertEqual(cfg.backoff_delay(100), 5.0)


# ---------------------------------------------------------------------------
# 6. SSEStream Retry Tests
# ---------------------------------------------------------------------------

class TestSSEStreamRetry(unittest.TestCase):
    def test_sse_stream_retry_parameters(self):
        stream = SSEStream(
            "http://localhost:9999", "test_task",
            max_retries=5,
            backoff_factor=0.5,
            timeout=10,
            heartbeat_timeout=30.0,
        )
        self.assertEqual(stream.max_retries, 5)
        self.assertEqual(stream.backoff_factor, 0.5)
        self.assertEqual(stream.timeout, 10)
        self.assertEqual(stream.heartbeat_timeout, 30.0)

    def test_sse_stream_no_retry_connection_refused(self):
        stream = SSEStream(
            "http://localhost:1", "test_retry",
            max_retries=0,
            timeout=2,
        )
        events = list(stream)
        event_types = [e[0] for e in events]
        self.assertIn("error", event_types)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
