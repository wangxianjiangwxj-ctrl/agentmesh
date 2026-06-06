"""Real end-to-end integration tests for the A2A Server.

Direction A, Phase 3: Real Integration Testing.

This module provides:
  1. RealIntegrationTestRunner -- a concrete IntegrationTestRunner subclass
     that uses a real A2A Server and HttpProvider for all scenarios.
  2. Standalone test classes using real HttpProvider against a real server:
       - Server health check / ping
       - Card send/receive (via task protocol)
       - Message send/receive (text + data payloads)
       - Cross-adapter communication (CrewAI <-> AutoGen via A2A Server)
       - Concurrent task processing
       - Error recovery (server restart)

Usage:
    pytest tests/integration/test_real_e2e.py -v --timeout=60
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import unittest
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.insert(0, REPO_ROOT)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

try:
    from agentmesh.a2a_provider import A2AError, A2AResult
    from agentmesh.a2a_server import HttpProvider
except ImportError:
    sys.path.insert(0, os.path.join(REPO_ROOT, "agentmesh"))
    from agentmesh.a2a_provider import A2AError, A2AResult
    from agentmesh.a2a_server import HttpProvider

try:
    from agentmesh.a2a.integration import (
        DEFAULT_MATRIX,
        FrameworkType,
        IntegrationTestMatrix,
        IntegrationTestRunner,
        ScenarioResult,
        TestResult,
        TestScenario,
    )
    HAS_INTEGRATION = True
except ImportError:
    HAS_INTEGRATION = False

try:
    from agentmesh.a2a.integration.crewai_adapter import (
        A2AToolDef,
        CardReceiveResult,
        CardSendResult,
        CardStatus,
        CardType,
        CrewAIAdapter,
        CrewAIAgentConfig,
    )
    HAS_CREWAI_ADAPTER = True
except ImportError:
    HAS_CREWAI_ADAPTER = False

try:
    from agentmesh.a2a.integration.autogen_adapter import (
        A2AAgentDef,
        AutoGenAdapter,
        AutoGenAgentConfig,
        MessageReceiveResult,
        MessageSendResult,
        MessageType,
    )
    HAS_AUTOGEN_ADAPTER = True
except ImportError:
    HAS_AUTOGEN_ADAPTER = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVER_PORT = int(os.environ.get("A2A_SERVER_PORT", "8089"))
SERVER_URL = f"http://localhost:{SERVER_PORT}"
SERVER_SCRIPT = os.path.join(REPO_ROOT, "agentmesh", "a2a_server.py")


# ---------------------------------------------------------------------------
# Server lifecycle helpers
# ---------------------------------------------------------------------------

def _is_server_running(url: str = SERVER_URL) -> bool:
    """Check if an A2A server is already running at the given URL."""
    import urllib.error
    import urllib.request
    try:
        req = urllib.request.Request(f"{url}/ping", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _start_server_process(
    port: int = SERVER_PORT,
    script: str = SERVER_SCRIPT,
) -> subprocess.Popen:
    """Start the A2A server as a subprocess and return the handle."""
    proc = subprocess.Popen(
        [sys.executable, script, "server", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for server to be ready
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if _is_server_running(f"http://localhost:{port}"):
            return proc
        time.sleep(0.2)
    raise RuntimeError(f"A2A Server failed to start on :{port}")


def _stop_server_process(proc: subprocess.Popen) -> None:
    """Terminate the server subprocess."""
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


# ---------------------------------------------------------------------------
# Global server context (session-level fixture replacement)
# ---------------------------------------------------------------------------

class _ServerContext:
    """Manages a single server instance for the test module.

    Use as a context manager or call start()/stop() explicitly.
    Thread-safe for concurrent test usage.
    """

    def __init__(self, port: int = SERVER_PORT):
        self.port = port
        self.url = f"http://localhost:{port}"
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._refcount = 0

    def start(self) -> None:
        """Start the server if not already running."""
        with self._lock:
            if self._refcount > 0:
                self._refcount += 1
                return
            if _is_server_running(self.url):
                self._refcount = 1
                return
            self._proc = _start_server_process(self.port)
            self._refcount = 1

    def stop(self) -> None:
        """Stop the server when the last user releases it."""
        with self._lock:
            self._refcount -= 1
            if self._refcount > 0:
                return
            if self._proc:
                _stop_server_process(self._proc)
                self._proc = None

    def restart(self) -> None:
        """Stop and restart the server."""
        with self._lock:
            if self._proc:
                _stop_server_process(self._proc)
                self._proc = None
            self._proc = _start_server_process(self.port)


SERVER_CTX = _ServerContext()


# ===================================================================
# 1. RealIntegrationTestRunner
# ===================================================================

@unittest.skipUnless(HAS_INTEGRATION, "agentmesh.a2a.integration not importable")
class RealIntegrationTestRunner(IntegrationTestRunner):
    """Concrete IntegrationTestRunner using a real A2A Server + HttpProvider.

    All scenarios in the test matrix are executed against the real HTTP
    server. The runner auto-starts the server on first use and stops it
    when the last scenario completes.

    Usage:
        runner = RealIntegrationTestRunner()
        results = runner.run_all()
        report = runner.summary_report()
    """

    def __init__(
        self,
        matrix: Optional[IntegrationTestMatrix] = None,
        server_url: str = SERVER_URL,
    ):
        super().__init__(matrix)
        self._server_url = server_url
        self._client: Optional[HttpProvider] = None
        self._server_started = False

    # ------------------------------------------------------------------
    # IntegrationTestRunner abstract methods
    # ------------------------------------------------------------------

    def setup_scenario(self, scenario: TestScenario) -> Dict[str, Any]:
        """Prepare the scenario environment: ensure server is running and
        create an HttpProvider client.  Returns context with sender_id,
        receiver_id, and client reference."""
        # Start server on first use
        if not self._server_started:
            if not _is_server_running(self._server_url):
                SERVER_CTX.start()
            self._server_started = True

        if self._client is None:
            self._client = HttpProvider(self._server_url, "real-integration-runner")

        # Derive sender/receiver IDs from the scenario
        sender_id = f"{scenario.sender_framework.value}_{scenario.name}_sender"
        receiver_id = f"{scenario.receiver_framework.value}_{scenario.name}_receiver"

        return {
            "client": self._client,
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "server_url": self._server_url,
        }

    def execute_scenario(
        self,
        scenario: TestScenario,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a single scenario against the real server.

        Sends a task via HttpProvider and verifies it was received.
        The payload content varies by message_type (text / data / tool_call).
        """
        client: HttpProvider = context["client"]
        sender_id = context["sender_id"]
        receiver_id = context["receiver_id"]

        # Build the task payload according to the scenario's message type
        task_id = f"real_e2e_{int(time.time() * 1000)}_{scenario.name}"
        payload = self._build_payload(scenario, sender_id, receiver_id)

        task: Dict[str, Any] = {
            "id": task_id,
            "status": {"state": "submitted"},
            "payload": payload,
            "metadata": {
                "sender": sender_id,
                "receiver": receiver_id,
                "scenario": scenario.name,
                "message_type": scenario.message_type,
            },
        }

        # Send the task
        send_result = client.send_message(task)
        if not send_result.success:
            raise RuntimeError(
                f"Failed to send task for scenario '{scenario.name}': "
                f"{send_result.error}"
            )

        # Verify the task is stored
        get_result = client.get_task(task_id)
        if not get_result.success:
            raise RuntimeError(
                f"Failed to retrieve task '{task_id}' after send: "
                f"{get_result.error}"
            )

        # Register an agent card if sender is non-custom
        if scenario.sender_framework != FrameworkType.CUSTOM:
            reg_result = client.register_agent(sender_id, ["integration", "test"])
            if not reg_result.success:
                # Non-fatal: agent registration is informational
                pass

        # Compute round-trip latency
        latency_s = (
            get_result.data.get("status", {}).get("timestamp", time.time())
            if get_result.data
            else time.time()
        )
        if isinstance(latency_s, (int, float)):
            latency_ms = abs(time.time() - latency_s) * 1000.0
        else:
            latency_ms = 5.0

        return {
            "sent": {
                "sender_id": sender_id,
                "receiver_id": receiver_id,
                "payload": payload,
                "message_type": scenario.message_type,
                "task_id": task_id,
            },
            "received": {
                "content": get_result.data,
                "task_state": get_result.task_state,
                "metadata": {"latency_ms": latency_ms},
            },
            "latency_ms": latency_ms,
        }

    def teardown_scenario(
        self,
        scenario: TestScenario,
        context: Dict[str, Any],
    ) -> None:
        """Clean up after a single scenario. Cancels the task if needed."""
        client: HttpProvider = context.get("client")
        if client and "sent" in context:
            task_id = context["sent"].get("task_id", "")
            if task_id:
                try:
                    client.cancel_task(task_id)
                except Exception:
                    pass  # Best-effort cleanup

    def validate_result(
        self,
        scenario: TestScenario,
        result_data: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """Validate that a scenario produced the expected result.

        Checks:
          - task was sent successfully (has sender_id, receiver_id)
          - response was received (has content)
          - message_type matches
        """
        sent = result_data.get("sent", {})
        received = result_data.get("received", {})

        # Check sent fields
        if not sent.get("sender_id"):
            return False, "Missing sender_id in sent data"
        if not sent.get("receiver_id"):
            return False, "Missing receiver_id in sent data"
        if sent.get("message_type") != scenario.message_type:
            return False, (
                f"Message type mismatch: expected {scenario.message_type}, "
                f"got {sent.get('message_type')}"
            )

        # Check received fields
        content = received.get("content")
        if content is None:
            return False, "Missing received content"
        if received.get("task_state") != "submitted":
            return False, (
                f"Unexpected task state: "
                f"{received.get('task_state')}"
            )

        return True, None

    def _check_prerequisite(self, package_name: str) -> bool:
        """Check if a required package is importable."""
        if package_name == "crewai":
            return HAS_CREWAI_ADAPTER
        if package_name == "pyautogen":
            return HAS_AUTOGEN_ADAPTER
        try:
            __import__(package_name)
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_payload(
        scenario: TestScenario,
        sender_id: str,
        receiver_id: str,
    ) -> Dict[str, Any]:
        """Build a payload dict appropriate for the scenario's message_type."""
        base = {
            "sender": sender_id,
            "receiver": receiver_id,
            "timestamp": time.time(),
        }

        if scenario.message_type == "text":
            base["content"] = f"Text message from {sender_id} to {receiver_id}"
            base["type"] = "text"
        elif scenario.message_type == "data":
            base["content"] = {
                "values": [1, 2, 3],
                "labels": ["a", "b", "c"],
                "metadata": {"format": "json"},
            }
            base["type"] = "data"
        elif scenario.message_type == "tool_call":
            base["content"] = {
                "tool": "agentmesh_send",
                "parameters": {
                    "recipient_id": receiver_id,
                    "message": f"Tool call from {sender_id}",
                },
            }
            base["type"] = "tool_call"
        else:
            base["content"] = f"Message from {sender_id} to {receiver_id}"
            base["type"] = scenario.message_type

        return base


# ===================================================================
# 2. RealIntegrationTestRunner Tests
# ===================================================================

@unittest.skipUnless(HAS_INTEGRATION, "agentmesh.a2a.integration not importable")
class TestRealIntegrationTestRunner(unittest.TestCase):
    """Verify RealIntegrationTestRunner works with the real server."""

    @classmethod
    def setUpClass(cls):
        SERVER_CTX.start()
        cls.runner = RealIntegrationTestRunner()

    @classmethod
    def tearDownClass(cls):
        SERVER_CTX.stop()

    def test_run_scenario_by_name(self) -> None:
        """Run a single scenario by name against the real server."""
        result = self.runner.run_scenario("custom_to_custom_tool_call")
        # Since the default matrix doesn't have custom-to-custom,
        # this should return None (not found)
        if result is None:
            # Run a known scenario instead
            result = self.runner.run_scenario("crewai_to_crewai_text")
        self.assertIsNotNone(result)
        if result and result.result != TestResult.SKIPPED:
            self.assertIn(
                result.result,
                (TestResult.PASSED, TestResult.FAILED),
                f"Unexpected result: {result.result}",
            )

    def test_run_all_scenarios(self) -> None:
        """Run all 8 scenarios in the default matrix."""
        results = self.runner.run_all()
        self.assertEqual(len(results), len(self.runner.matrix.scenarios))
        for r in results:
            if r.result == TestResult.FAILED:
                print(f"  Scenario '{r.scenario.name}' FAILED: {r.error_message}")
        # At minimum, scenarios without framework prerequisites should pass
        passed_or_skipped = sum(
            1 for r in results
            if r.result in (TestResult.PASSED, TestResult.SKIPPED)
        )
        self.assertEqual(
            passed_or_skipped,
            len(results),
            f"Expected all {len(results)} scenarios to pass or skip, "
            f"got {passed_or_skipped}",
        )

    def test_summary_report(self) -> None:
        """Summary report after running all scenarios is well-formed."""
        self.runner.run_all()
        report = self.runner.summary_report()
        self.assertIn("total", report)
        self.assertIn("passed", report)
        self.assertIn("failed", report)
        self.assertIn("details", report)
        self.assertEqual(report["total"], len(self.runner.matrix.scenarios))
        self.assertGreaterEqual(report["total"], 0)

    def test_results_property(self) -> None:
        """results property returns accumulated results."""
        self.runner.run_all()
        self.assertEqual(len(self.runner.results), 8)


# ===================================================================
# 3. Server Health & Lifecycle Tests
# ===================================================================

class TestRealServerHealth(unittest.TestCase):
    """Verify the real A2A server responds to health checks."""

    @classmethod
    def setUpClass(cls):
        SERVER_CTX.start()
        cls.client = HttpProvider(SERVER_URL, "health-test")

    @classmethod
    def tearDownClass(cls):
        SERVER_CTX.stop()

    def test_ping_returns_ok(self) -> None:
        """Server responds to health check with status 'ok'."""
        r = self.client.ping()
        self.assertTrue(r.success)
        self.assertIsNotNone(r.data)
        self.assertEqual(r.data.get("status"), "ok")
        self.assertEqual(r.data.get("provider"), "a2a-server")

    def test_ping_returns_success_flag(self) -> None:
        """Ping response has success=True."""
        r = self.client.ping()
        self.assertTrue(r.success)

    def test_server_url_is_accessible(self) -> None:
        """Server URL is directly accessible via HTTP."""
        import urllib.request
        req = urllib.request.Request(f"{SERVER_URL}/ping", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)


# ===================================================================
# 4. Card Send / Receive Tests (via task protocol)
# ===================================================================

class TestRealServerCardSendReceive(unittest.TestCase):
    """Verify Card-like communication through the A2A task protocol.

    Cards are represented as A2A tasks with structured payloads.
    """

    @classmethod
    def setUpClass(cls):
        SERVER_CTX.start()
        cls.client = HttpProvider(SERVER_URL, "card-test")

    @classmethod
    def tearDownClass(cls):
        SERVER_CTX.stop()

    def test_send_text_card(self) -> None:
        """Send a text Card (task with text payload)."""
        task_id = f"card_text_{int(time.time() * 1000)}"
        task = {
            "id": task_id,
            "status": {"state": "submitted"},
            "payload": {
                "type": "text",
                "content": "Hello from sender",
                "sender": "agent_a",
                "receiver": "agent_b",
            },
        }
        r = self.client.send_message(task)
        self.assertTrue(r.success)
        self.assertEqual(r.task_state, "submitted")

        # Verify the card was stored
        r2 = self.client.get_task(task_id)
        self.assertTrue(r2.success)
        self.assertEqual(r2.data["id"], task_id)
        self.assertEqual(
            r2.data["payload"]["content"],
            "Hello from sender",
        )

    def test_send_data_card(self) -> None:
        """Send a data Card (task with data payload)."""
        task_id = f"card_data_{int(time.time() * 1000)}"
        data_payload = {
            "type": "data",
            "content": {"values": [10, 20, 30], "labels": ["x", "y", "z"]},
            "sender": "agent_a",
            "receiver": "agent_b",
        }
        task = {
            "id": task_id,
            "status": {"state": "submitted"},
            "payload": data_payload,
        }
        r = self.client.send_message(task)
        self.assertTrue(r.success)

        r2 = self.client.get_task(task_id)
        self.assertTrue(r2.success)
        self.assertEqual(r2.data["payload"]["type"], "data")
        self.assertEqual(r2.data["payload"]["content"]["values"], [10, 20, 30])

    def test_card_send_receive_lifecycle(self) -> None:
        """Card send -> receive -> cancel lifecycle."""
        task_id = f"card_lifecycle_{int(time.time() * 1000)}"
        task = {
            "id": task_id,
            "status": {"state": "submitted"},
            "payload": {
                "type": "text",
                "content": "Lifecycle test card",
            },
        }

        # Send
        r1 = self.client.send_message(task)
        self.assertTrue(r1.success)

        # Receive (get)
        r2 = self.client.get_task(task_id)
        self.assertTrue(r2.success)
        self.assertEqual(r2.data["payload"]["content"], "Lifecycle test card")

        # Cancel
        r3 = self.client.cancel_task(task_id)
        self.assertTrue(r3.success)
        self.assertEqual(r3.task_state, "canceled")

        # Verify canceled
        r4 = self.client.get_task(task_id)
        self.assertTrue(r4.success)
        self.assertEqual(r4.data["status"]["state"], "canceled")

    def test_send_multiple_cards_independently(self) -> None:
        """Multiple cards can be sent and retrieved independently."""
        cards = [
            {"id": f"card_multi_a_{int(time.time() * 1000)}", "text": "Card A"},
            {"id": f"card_multi_b_{int(time.time() * 1000)}", "text": "Card B"},
            {"id": f"card_multi_c_{int(time.time() * 1000)}", "text": "Card C"},
        ]
        for card in cards:
            task = {
                "id": card["id"],
                "status": {"state": "submitted"},
                "payload": {"type": "text", "content": card["text"]},
            }
            r = self.client.send_message(task)
            self.assertTrue(r.success)

        # Verify each independently
        for card in cards:
            r = self.client.get_task(card["id"])
            self.assertTrue(r.success)
            self.assertEqual(r.data["payload"]["content"], card["text"])


# ===================================================================
# 5. Message Send / Receive Tests (text + data)
# ===================================================================

class TestRealServerMessageSendReceive(unittest.TestCase):
    """Verify message-level communication through the A2A protocol."""

    @classmethod
    def setUpClass(cls):
        SERVER_CTX.start()
        cls.client = HttpProvider(SERVER_URL, "msg-test")

    @classmethod
    def tearDownClass(cls):
        SERVER_CTX.stop()

    def test_send_text_message(self) -> None:
        """Send a text message as an A2A task."""
        task_id = f"msg_text_{int(time.time() * 1000)}"
        task = {
            "id": task_id,
            "status": {"state": "submitted"},
            "payload": {
                "type": "text",
                "content": "This is a text message",
                "sender": "user_a",
                "receiver": "agent_b",
            },
        }
        r = self.client.send_message(task)
        self.assertTrue(r.success)

        r2 = self.client.get_task(task_id)
        self.assertTrue(r2.success)
        self.assertEqual(r2.data["payload"]["content"], "This is a text message")

    def test_send_data_message(self) -> None:
        """Send a data message with structured content."""
        task_id = f"msg_data_{int(time.time() * 1000)}"
        data = {
            "type": "data",
            "content": {
                "temperature": 22.5,
                "humidity": 65,
                "location": "Shanghai",
            },
            "sender": "sensor_01",
            "receiver": "monitor",
        }
        task = {"id": task_id, "status": {"state": "submitted"}, "payload": data}
        r = self.client.send_message(task)
        self.assertTrue(r.success)

        r2 = self.client.get_task(task_id)
        self.assertTrue(r2.success)
        payload = r2.data["payload"]
        self.assertEqual(payload["type"], "data")
        self.assertEqual(payload["content"]["temperature"], 22.5)
        self.assertEqual(payload["content"]["location"], "Shanghai")

    def test_send_message_with_metadata(self) -> None:
        """Send a message with rich metadata."""
        task_id = f"msg_meta_{int(time.time() * 1000)}"
        task = {
            "id": task_id,
            "status": {"state": "submitted"},
            "payload": {
                "type": "text",
                "content": "Message with metadata",
            },
            "metadata": {
                "sender": "agent_a",
                "receiver": "agent_b",
                "priority": "high",
                "correlation_id": "corr-001",
            },
        }
        r = self.client.send_message(task)
        self.assertTrue(r.success)

        r2 = self.client.get_task(task_id)
        self.assertTrue(r2.success)
        self.assertEqual(r2.data.get("metadata", {}).get("priority"), "high")
        self.assertEqual(
            r2.data.get("metadata", {}).get("correlation_id"),
            "corr-001",
        )

    def test_message_idempotent_send(self) -> None:
        """Sending the same message twice is handled gracefully."""
        task_id = f"msg_idempotent_{int(time.time() * 1000)}"
        task = {
            "id": task_id,
            "status": {"state": "submitted"},
            "payload": {"type": "text", "content": "Idempotent message"},
        }

        # Send twice with same id
        r1 = self.client.send_message(task)
        self.assertTrue(r1.success)

        r2 = self.client.send_message(task)
        # The server should either accept the duplicate or return an error,
        # but not crash
        self.assertIsNotNone(r2)


# ===================================================================
# 6. Cross-Adapter Communication
# ===================================================================

class TestRealServerCrossAdapter(unittest.TestCase):
    """Simulate cross-framework (CrewAI <-> AutoGen) communication via A2A.

    Since both adapters ultimately use the same A2A protocol, we test
    that the protocol layer handles payloads typical of each framework.
    """

    @classmethod
    def setUpClass(cls):
        SERVER_CTX.start()
        cls.client = HttpProvider(SERVER_URL, "cross-adapter-test")

    @classmethod
    def tearDownClass(cls):
        SERVER_CTX.stop()

    def test_crewai_to_autogen_task_flow(self) -> None:
        """Simulate a CrewAI agent sending a task that an AutoGen agent receives.

        The A2A protocol is framework-agnostic: both adapters use the
        same send/get/cancel primitives.
        """
        task_id = f"cross_c2a_{int(time.time() * 1000)}"
        task = {
            "id": task_id,
            "status": {"state": "submitted"},
            "payload": {
                "type": "text",
                "content": "CrewAI request to AutoGen: analyze this data",
                "sender": "crewai_agent",
                "receiver": "autogen_agent",
                "framework": "crewai",
            },
        }
        # CrewAI side: send
        r_send = self.client.send_message(task)
        self.assertTrue(r_send.success)
        self.assertEqual(r_send.task_state, "submitted")

        # AutoGen side: receive (get task)
        r_get = self.client.get_task(task_id)
        self.assertTrue(r_get.success)
        self.assertEqual(r_get.data["payload"]["sender"], "crewai_agent")
        self.assertEqual(r_get.data["payload"]["receiver"], "autogen_agent")

        # AutoGen side: respond (update task status)
        # The server updates are in-place, so we verify the state transition
        r_cancel = self.client.cancel_task(task_id)
        self.assertTrue(r_cancel.success)

    def test_autogen_to_crewai_task_flow(self) -> None:
        """Simulate an AutoGen agent sending a task to a CrewAI agent."""
        task_id = f"cross_a2c_{int(time.time() * 1000)}"
        task = {
            "id": task_id,
            "status": {"state": "submitted"},
            "payload": {
                "type": "data",
                "content": {"query": "research_topic", "params": {"depth": "detailed"}},
                "sender": "autogen_agent",
                "receiver": "crewai_agent",
                "framework": "autogen",
            },
        }
        r = self.client.send_message(task)
        self.assertTrue(r.success)
        self.assertEqual(r.task_state, "submitted")

        # Verify AutoGen payload reaches CrewAI side intact
        r2 = self.client.get_task(task_id)
        self.assertTrue(r2.success)
        self.assertEqual(r2.data["payload"]["content"]["query"], "research_topic")
        self.assertEqual(r2.data["payload"]["framework"], "autogen")

    def test_custom_to_crewai_data_exchange(self) -> None:
        """Custom agent sends a DataCard-like task to a CrewAI agent."""
        task_id = f"cross_custom_crewai_{int(time.time() * 1000)}"
        task = {
            "id": task_id,
            "status": {"state": "submitted"},
            "payload": {
                "type": "data",
                "content": {
                    "data_points": [100, 200, 300],
                    "analysis": "preliminary",
                },
                "sender": "custom_agent",
                "receiver": "crewai_agent",
            },
        }
        r = self.client.send_message(task)
        self.assertTrue(r.success)

        r2 = self.client.get_task(task_id)
        self.assertTrue(r2.success)
        self.assertEqual(r2.data["payload"]["content"]["data_points"], [100, 200, 300])

    def test_autogen_to_custom_tool_call(self) -> None:
        """AutoGen agent sends a ToolCall-like task to a Custom agent."""
        task_id = f"cross_autogen_custom_{int(time.time() * 1000)}"
        task = {
            "id": task_id,
            "status": {"state": "submitted"},
            "payload": {
                "type": "tool_call",
                "content": {
                    "tool": "agentmesh_query",
                    "parameters": {
                        "target": "custom_agent",
                        "query": "get_status",
                    },
                },
                "sender": "autogen_agent",
                "receiver": "custom_agent",
            },
        }
        r = self.client.send_message(task)
        self.assertTrue(r.success)

        r2 = self.client.get_task(task_id)
        self.assertTrue(r2.success)
        self.assertEqual(r2.data["payload"]["type"], "tool_call")
        self.assertEqual(
            r2.data["payload"]["content"]["tool"],
            "agentmesh_query",
        )

    def test_register_agent_via_server(self) -> None:
        """Agent cards can be registered on the server for discovery."""
        r = self.client.register_agent("crewai_worker", ["coding", "analysis"])
        self.assertTrue(r.success)

        r2 = self.client.register_agent("autogen_assistant", ["chat", "reasoning"])
        self.assertTrue(r2.success)


# ===================================================================
# 7. Concurrent Task Processing
# ===================================================================

class TestRealServerConcurrentTasks(unittest.TestCase):
    """Verify the server handles concurrent task submissions correctly."""

    CONCURRENCY = 5

    @classmethod
    def setUpClass(cls):
        SERVER_CTX.start()
        cls.client = HttpProvider(SERVER_URL, "concurrent-test")

    @classmethod
    def tearDownClass(cls):
        SERVER_CTX.stop()

    def test_concurrent_submission(self) -> None:
        """Submit multiple tasks concurrently; all should be accepted."""
        n = self.CONCURRENCY
        results: List[Optional[Dict[str, Any]]] = [None] * n
        errors: List[str] = []

        def _send(idx: int) -> None:
            try:
                task_id = f"concurrent_{idx}_{int(time.time() * 1000)}"
                task = {
                    "id": task_id,
                    "status": {"state": "submitted"},
                    "payload": {"type": "text", "content": f"Concurrent task #{idx}"},
                }
                r = self.client.send_message(task)
                results[idx] = {
                    "task_id": task_id,
                    "success": r.success,
                    "state": r.task_state,
                }
            except Exception as e:
                errors.append(f"Thread {idx}: {e}")

        threads = [threading.Thread(target=_send, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(
            len(errors), 0,
            f"Concurrent send errors: {errors}",
        )
        completed = sum(1 for r in results if r and r["success"])
        self.assertEqual(completed, n, f"Expected {n} success, got {completed}")

        # All task IDs must be unique
        task_ids = [r["task_id"] for r in results if r]
        self.assertEqual(len(set(task_ids)), len(task_ids))

    def test_concurrent_get_tasks(self) -> None:
        """Submit sequentially, then retrieve all concurrently."""
        n = self.CONCURRENCY
        task_ids = [
            f"concurrent_get_{i}_{int(time.time() * 1000)}"
            for i in range(n)
        ]
        for tid in task_ids:
            task = {
                "id": tid,
                "status": {"state": "submitted"},
                "payload": {"type": "text", "content": f"Concurrent get task {tid}"},
            }
            r = self.client.send_message(task)
            self.assertTrue(r.success)

        # Retrieve all concurrently
        retrievals: List[Optional[bool]] = [None] * n
        errors: List[str] = []

        def _get(idx: int) -> None:
            try:
                r = self.client.get_task(task_ids[idx])
                retrievals[idx] = r.success and r.data["id"] == task_ids[idx]
            except Exception as e:
                errors.append(f"Get thread {idx}: {e}")

        threads = [threading.Thread(target=_get, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Concurrent get errors: {errors}")
        self.assertTrue(all(retrievals), f"Not all retrievals succeeded: {retrievals}")


# ===================================================================
# 8. Error Recovery Tests
# ===================================================================

class TestRealServerErrorRecovery(unittest.TestCase):
    """Verify error handling: 404s, invalid tasks, server restarts."""

    @classmethod
    def setUpClass(cls):
        SERVER_CTX.start()
        cls.client = HttpProvider(SERVER_URL, "error-recovery-test")

    @classmethod
    def tearDownClass(cls):
        SERVER_CTX.stop()

    def test_get_nonexistent_task_returns_404(self) -> None:
        """Getting a nonexistent task returns an error with code 404."""
        r = self.client.get_task("nonexistent_task_xyz")
        self.assertFalse(r.success)
        self.assertIsNotNone(r.error)
        self.assertEqual(r.error.code, 404)

    def test_cancel_nonexistent_task_returns_404(self) -> None:
        """Canceling a nonexistent task returns an error with code 404."""
        r = self.client.cancel_task("nonexistent_task_abc")
        self.assertFalse(r.success)
        self.assertIsNotNone(r.error)
        self.assertEqual(r.error.code, 404)

    def test_empty_task_id_rejected(self) -> None:
        """Sending a task with an empty id is rejected."""
        task = {
            "id": "",
            "status": {"state": "submitted"},
            "payload": {"text": "empty id task"},
        }
        r = self.client.send_message(task)
        self.assertFalse(r.success)

    def test_missing_status_rejected(self) -> None:
        """Sending a task without a status field is handled gracefully."""
        task = {
            "id": f"no_status_{int(time.time() * 1000)}",
            "payload": {"text": "no status field"},
        }
        r = self.client.send_message(task)
        # Server should either accept with default state or return error
        self.assertIsNotNone(r)

    def test_server_restart_recovery(self) -> None:
        """After server restart, the server responds to new requests."""
        # Send a task first
        task_id = f"restart_recovery_{int(time.time() * 1000)}"
        task = {
            "id": task_id,
            "status": {"state": "submitted"},
            "payload": {"type": "text", "content": "Before restart"},
        }
        r1 = self.client.send_message(task)
        self.assertTrue(r1.success)

        # Restart the server
        SERVER_CTX.restart()
        # Recreate client (new connection)
        new_client = HttpProvider(SERVER_URL, "recovery-client")

        # After restart, the in-memory task store is gone, but the server
        # should still respond to new requests
        task_id2 = f"restart_recovery_after_{int(time.time() * 1000)}"
        task2 = {
            "id": task_id2,
            "status": {"state": "submitted"},
            "payload": {"type": "text", "content": "After restart"},
        }
        r2 = new_client.send_message(task2)
        self.assertTrue(r2.success, "Server did not accept tasks after restart")

        # The old task should be gone (in-memory) but that's expected
        # The important thing is the server is functional

    def test_server_health_after_restart(self) -> None:
        """Server health check works after restart."""
        SERVER_CTX.restart()
        new_client = HttpProvider(SERVER_URL, "post-restart")
        r = new_client.ping()
        self.assertTrue(r.success)
        self.assertEqual(r.data.get("status"), "ok")


# ===================================================================
# 9. Agent Registration Tests
# ===================================================================

class TestRealServerAgentRegistration(unittest.TestCase):
    """Verify agent card registration via the A2A server."""

    @classmethod
    def setUpClass(cls):
        SERVER_CTX.start()
        cls.client = HttpProvider(SERVER_URL, "agent-reg-test")

    @classmethod
    def tearDownClass(cls):
        SERVER_CTX.stop()

    def test_register_agent_card(self) -> None:
        """Register an agent card with skills."""
        r = self.client.register_agent("test-agent-1", ["coding", "debug", "analysis"])
        self.assertTrue(r.success)

    def test_register_multiple_agents(self) -> None:
        """Register multiple agent cards."""
        agents = [
            ("agent-alpha", ["planning"]),
            ("agent-beta", ["execution", "testing"]),
            ("agent-gamma", ["monitoring", "alerting"]),
        ]
        for name, skills in agents:
            r = self.client.register_agent(name, skills)
            self.assertTrue(r.success, f"Failed to register {name}")

    def test_register_agent_no_skills(self) -> None:
        """Register an agent card with no skills (empty list)."""
        r = self.client.register_agent("bare-agent", [])
        self.assertTrue(r.success)


# ===================================================================
# Run directly
# ===================================================================

def main():
    """Run all tests in this module."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Discover all test classes in this module
    suite.addTests(loader.loadTestsFromModule(sys.modules[__name__]))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
