#!/usr/bin/env python3
"""End-to-end tests for the /health endpoint.

These tests start a real FastAPI server and verify the
health check response format, content, and stability.

Usage:
    pytest tests/e2e/test_health.py -v

Design:
    Tests use urllib to make raw HTTP requests against the
    /health endpoint. A fixture manages server lifecycle when
    no existing server is detected (via /ping).
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

# We import _get_version and _server_start_time for verification
try:
    from agentmesh.a2a_server import _get_version
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from agentmesh.a2a_server import _get_version


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVER_PORT = int(os.environ.get("A2A_SERVER_PORT", "8089"))
SERVER_URL = f"http://localhost:{SERVER_PORT}"
HEALTH_URL = f"{SERVER_URL}/health"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _server_proc():
    """Start server, yield (proc, url), terminate on cleanup."""
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

class TestHealthEndpoint(unittest.TestCase):
    """Verify the /health endpoint."""

    @classmethod
    def setUpClass(cls):
        cls._proc = _server_proc()

    @classmethod
    def tearDownClass(cls):
        if cls._proc:
            cls._proc.terminate()
            try:
                cls._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls._proc.kill()

    def _get_health(self) -> dict:
        """Make a GET request to /health and return parsed JSON."""
        req = urllib.request.Request(HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
            return json.loads(body)

    # --- Basic structure ---

    def test_status_code_200(self):
        """Health endpoint returns HTTP 200."""
        req = urllib.request.Request(HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.status, 200)

    def test_content_type_json(self):
        """Health endpoint returns JSON content type."""
        req = urllib.request.Request(HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get("Content-Type", "")
            self.assertIn("json", content_type.lower())

    # --- JSON fields ---

    def test_has_status_field(self):
        """Health response contains 'status' field set to 'ok'."""
        data = self._get_health()
        self.assertIn("status", data)
        self.assertEqual(data["status"], "ok")

    def test_has_uptime_field(self):
        """Health response contains 'uptime' field (positive number)."""
        data = self._get_health()
        self.assertIn("uptime", data)
        self.assertIsInstance(data["uptime"], (int, float))
        self.assertGreater(data["uptime"], 0)

    def test_has_components_field(self):
        """Health response contains 'components' field."""
        data = self._get_health()
        self.assertIn("components", data)
        self.assertIsInstance(data["components"], dict)

    def test_components_has_server(self):
        """Components dict contains 'server' key."""
        data = self._get_health()
        self.assertIn("server", data["components"])
        self.assertIn(data["components"]["server"], ("healthy", "unhealthy"))

    def test_components_has_provider(self):
        """Components dict contains 'provider' key."""
        data = self._get_health()
        self.assertIn("provider", data["components"])
        self.assertIn(data["components"]["provider"], ("healthy", "unhealthy"))

    def test_has_version_field(self):
        """Health response contains 'version' field."""
        data = self._get_health()
        self.assertIn("version", data)
        self.assertIsInstance(data["version"], str)
        self.assertGreater(len(data["version"]), 0)

    def test_version_from_get_version(self):
        """Version matches _get_version() result."""
        data = self._get_health()
        expected = _get_version()
        self.assertEqual(data["version"], expected)

    # --- Stability ---

    def test_uptime_increases(self):
        """Uptime increases between two successive requests."""
        d1 = self._get_health()
        time.sleep(0.5)
        d2 = self._get_health()
        self.assertGreater(d2["uptime"], d1["uptime"])

    def test_consistent_response(self):
        """Repeated requests return consistent fields."""
        for _ in range(5):
            data = self._get_health()
            self.assertEqual(data["status"], "ok")
            self.assertIn("server", data["components"])
            self.assertIn("provider", data["components"])

    # --- HTTP method handling ---

    def test_post_returns_405_or_ok(self):
        """POST to /health may succeed or return 405 (framework-dependent)."""
        data = json.dumps({"dummy": True}).encode("utf-8")
        req = urllib.request.Request(HEALTH_URL, data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                # Some frameworks accept POST on /health — that's fine
                pass
        except urllib.error.HTTPError as e:
            # 405 Method Not Allowed is also acceptable
            self.assertIn(e.code, (405, 200))

    # --- Provider health ---

    def test_components_provider_healthy(self):
        """Provider component should be healthy when server is running."""
        data = self._get_health()
        self.assertEqual(data["components"]["provider"], "healthy")

    def test_components_server_healthy(self):
        """Server component should be healthy."""
        data = self._get_health()
        self.assertEqual(data["components"]["server"], "healthy")

    # --- Edge cases ---

    def test_no_trailing_slash_required(self):
        """/health works without trailing slash."""
        url_no_slash = f"{SERVER_URL}/health"
        req = urllib.request.Request(url_no_slash, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.status, 200)

    def test_response_size_reasonable(self):
        """Health response is small (well under 1KB)."""
        data = self._get_health()
        body = json.dumps(data)
        self.assertLess(len(body), 1024, "Health response should be under 1KB")


# ---------------------------------------------------------------------------
# Run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
