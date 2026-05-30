"""Tests for the AgentMesh-CrewAI integration adapter.

Phase 13, Direction 5: Real Agent Framework Integration.

This module contains skeleton test cases for the CrewAIAdapterBase class.
Tests are structured to be discoverable by pytest but marked as skipped
when the concrete implementation or external dependencies are unavailable.

Usage:
    # Run all CrewAI adapter tests (will skip if not implemented)
    pytest tests/integration/test_crewai_adapter.py -v

    # Run tests with stdout
    pytest tests/integration/test_crewai_adapter.py -v -s

Reference: research/phase13-integration-plan.md — Task 1
"""

import unittest
from typing import Optional
from unittest import mock


# ---------------------------------------------------------------------------
# Import guard: the integration package should always be importable
# (stdlib only).  The concrete CrewAI package is NOT required at import
# time — only at test execution time for the integration scenarios.
# ---------------------------------------------------------------------------

try:
    from agentmesh.a2a.integration import (
        CrewAIAdapterBase,
        A2AToolDef,
        CrewAIAgentConfig,
        CardType,
        CardStatus,
        CardSendResult,
        CardReceiveResult,
    )
    HAS_ADAPTER = True
except ImportError:
    HAS_ADAPTER = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MOCK_SERVER_URL = "http://localhost:8080"
TEST_AGENT_ID = "test_crewai_agent"
TEST_RECIPIENT_ID = "test_crewai_recipient"


# ---------------------------------------------------------------------------
# Concrete stub for testing
# ---------------------------------------------------------------------------

class StubCrewAIAdapter(CrewAIAdapterBase):
    """Minimal concrete stub for unit-testing the abstract interface.

    Provides no-op implementations of all abstract methods. Used to verify
    that the interface is correct and testable, not for real integration.
    """

    def __init__(self) -> None:
        self._connected = False
        self._server_url = ""
        self._agents: dict = {}

    # Lifecycle
    def connect(self, server_url: str, timeout_seconds: float = 30.0) -> None:
        if not server_url:
            raise ValueError("server_url must not be empty")
        self._server_url = server_url
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False
        self._agents.clear()

    @property
    def is_connected(self) -> bool:
        return self._connected

    # Agent creation
    def create_agent(
        self,
        config: CrewAIAgentConfig,
        agent_id: Optional[str] = None,
    ) -> object:
        actual_id = agent_id or config.role
        self._agents[actual_id] = config
        return mock.MagicMock()

    def register_agent(self, agent_id: str, agent: object) -> None:
        self._agents[agent_id] = agent

    def unregister_agent(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)

    # Card operations
    def send_card(
        self,
        sender_id: str,
        recipient_id: str,
        payload: dict,
        card_type: CardType = CardType.TEXT,
        metadata: Optional[dict] = None,
        timeout_seconds: Optional[float] = None,
    ) -> CardSendResult:
        return CardSendResult(
            card_id="stub-card-001",
            status=CardStatus.DELIVERED,
            recipient_agent=recipient_id,
        )

    def receive_card(
        self,
        agent_id: str,
        timeout_seconds: Optional[float] = None,
    ) -> Optional[CardReceiveResult]:
        return CardReceiveResult(
            card_id="stub-card-001",
            sender_agent="stub-sender",
            card_type=CardType.TEXT,
            payload={"text": "stub message"},
        )

    def poll_cards(
        self,
        agent_id: str,
        max_count: int = 10,
        timeout_seconds: float = 1.0,
    ) -> list[CardReceiveResult]:
        return [
            CardReceiveResult(
                card_id="stub-card-001",
                sender_agent="stub-sender",
                card_type=CardType.TEXT,
                payload={"text": "stub message"},
            )
        ]

    # Tool management
    def create_a2a_tool(self, tool_def: A2AToolDef) -> object:
        return mock.MagicMock()

    def list_registered_tools(self) -> list[A2AToolDef]:
        return []

    # Task lifecycle
    def start_agent_task(
        self,
        agent_id: str,
        task_description: str,
        context: Optional[dict] = None,
    ) -> str:
        return "stub-task-001"

    def get_task_result(
        self,
        agent_id: str,
        task_id: str,
        timeout_seconds: float = 30.0,
    ) -> Optional[CardReceiveResult]:
        return CardReceiveResult(
            card_id="stub-task-result",
            sender_agent=agent_id,
            card_type=CardType.TEXT,
            payload={"result": "task completed"},
        )

    # Health
    def health_check(self) -> dict:
        return {
            "status": "ok",
            "server_url": self._server_url,
            "latency_ms": 0.0,
            "registered_agents": len(self._agents),
        }

    # Internal
    def _check_prerequisite(self, package_name: str) -> bool:
        return True


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_ADAPTER, "agentmesh.a2a.integration not importable")
class TestCrewAIAdapterInterface(unittest.TestCase):
    """Verify the CrewAIAdapterBase abstract interface."""

    def setUp(self) -> None:
        self.adapter = StubCrewAIAdapter()

    # ------------------------------------------------------------------
    # Lifecycle tests
    # ------------------------------------------------------------------

    def test_connect_disconnect_cycle(self) -> None:
        """Adapter should connect to a server URL and disconnect cleanly."""
        self.assertFalse(self.adapter.is_connected)
        self.adapter.connect(MOCK_SERVER_URL)
        self.assertTrue(self.adapter.is_connected)
        self.adapter.disconnect()
        self.assertFalse(self.adapter.is_connected)

    def test_connect_reject_empty_url(self) -> None:
        """Connecting with an empty URL should raise ValueError."""
        with self.assertRaises(ValueError):
            self.adapter.connect("")

    # ------------------------------------------------------------------
    # Agent creation tests
    # ------------------------------------------------------------------

    def test_create_agent_with_default_id(self) -> None:
        """Creating an agent without explicit ID should use the role name."""
        config = CrewAIAgentConfig(role="researcher", goal="find answers")
        agent = self.adapter.create_agent(config)
        self.assertIsNotNone(agent)

    def test_create_agent_with_explicit_id(self) -> None:
        """Creating an agent with an explicit ID should work."""
        config = CrewAIAgentConfig(role="writer", goal="write content")
        agent = self.adapter.create_agent(config, agent_id="my-writer")
        self.assertIsNotNone(agent)

    def test_create_agent_minimal_config(self) -> None:
        """Creating an agent with only required fields should work."""
        config = CrewAIAgentConfig(role="minimal", goal="test minimal")
        agent = self.adapter.create_agent(config)
        self.assertIsNotNone(agent)

    # ------------------------------------------------------------------
    # Card operations tests
    # ------------------------------------------------------------------

    def test_send_card_returns_result(self) -> None:
        """Sending a card should return a CardSendResult with status."""
        result = self.adapter.send_card(
            sender_id="sender",
            recipient_id="receiver",
            payload={"text": "hello"},
        )
        self.assertIsInstance(result, CardSendResult)
        self.assertEqual(result.status, CardStatus.DELIVERED)
        self.assertEqual(result.recipient_agent, "receiver")
        self.assertIsNotNone(result.card_id)

    def test_receive_card_returns_result(self) -> None:
        """Receiving a card should return a CardReceiveResult."""
        result = self.adapter.receive_card(agent_id="agent-1")
        self.assertIsInstance(result, CardReceiveResult)
        self.assertIsNotNone(result.card_id)
        self.assertIsNotNone(result.payload)

    def test_poll_cards_returns_list(self) -> None:
        """Polling for cards should return a list of CardReceiveResult."""
        results = self.adapter.poll_cards(agent_id="agent-1", max_count=5)
        self.assertIsInstance(results, list)
        if results:
            self.assertIsInstance(results[0], CardReceiveResult)

    def test_send_card_empty_payload(self) -> None:
        """Sending a card with an empty payload should still succeed."""
        result = self.adapter.send_card(
            sender_id="sender",
            recipient_id="receiver",
            payload={},
        )
        self.assertEqual(result.status, CardStatus.DELIVERED)

    # ------------------------------------------------------------------
    # Tool management tests
    # ------------------------------------------------------------------

    def test_create_a2a_tool_returns_object(self) -> None:
        """Creating an A2A tool should return a tool-like object."""
        tool_def = A2AToolDef(
            name="agentmesh_send",
            description="Send cards via AgentMesh",
        )
        tool = self.adapter.create_a2a_tool(tool_def)
        self.assertIsNotNone(tool)

    def test_list_registered_tools_initially_empty(self) -> None:
        """Listing tools should return an empty list initially."""
        tools = self.adapter.list_registered_tools()
        self.assertEqual(tools, [])

    # ------------------------------------------------------------------
    # Task lifecycle tests
    # ------------------------------------------------------------------

    def test_start_agent_task_returns_task_id(self) -> None:
        """Starting a task should return a task identifier."""
        task_id = self.adapter.start_agent_task(
            agent_id="agent-1",
            task_description="research topic X",
        )
        self.assertIsInstance(task_id, str)
        self.assertTrue(len(task_id) > 0)

    def test_get_task_result_returns_result(self) -> None:
        """Retrieving a task result should return a CardReceiveResult."""
        result = self.adapter.get_task_result(
            agent_id="agent-1",
            task_id="task-001",
        )
        self.assertIsInstance(result, CardReceiveResult)

    # ------------------------------------------------------------------
    # Health check test
    # ------------------------------------------------------------------

    def test_health_check_returns_status(self) -> None:
        """Health check should return a dict with expected keys."""
        self.adapter.connect(MOCK_SERVER_URL)
        health = self.adapter.health_check()
        self.assertIn("status", health)
        self.assertIn("server_url", health)
        self.assertIn("latency_ms", health)
        self.assertIn("registered_agents", health)
        self.assertEqual(health["status"], "ok")

    # ------------------------------------------------------------------
    # Edge case: double connect / double disconnect
    # ------------------------------------------------------------------

    def test_double_connect(self) -> None:
        """Connecting twice should not raise an error."""
        self.adapter.connect(MOCK_SERVER_URL)
        self.adapter.connect(MOCK_SERVER_URL)  # Should be idempotent
        self.assertTrue(self.adapter.is_connected)

    def test_double_disconnect(self) -> None:
        """Disconnecting twice should not raise an error."""
        self.adapter.connect(MOCK_SERVER_URL)
        self.adapter.disconnect()
        self.adapter.disconnect()  # Should be idempotent
        self.assertFalse(self.adapter.is_connected)

    # ------------------------------------------------------------------
    # Register/unregister agent
    # ------------------------------------------------------------------

    def test_register_and_unregister_agent(self) -> None:
        """Register then unregister an agent."""
        self.adapter.connect(MOCK_SERVER_URL)
        config = CrewAIAgentConfig(role="test", goal="test")
        agent = self.adapter.create_agent(config, agent_id="test-id")
        self.adapter.register_agent("test-id", agent)
        self.adapter.unregister_agent("test-id")

    def test_unregister_nonexistent_agent(self) -> None:
        """Unregistering a non-existent agent should not raise."""
        try:
            self.adapter.unregister_agent("nonexistent")
        except Exception as exc:
            self.fail(f"unregister_agent raised {exc}")


# ---------------------------------------------------------------------------
# Integration scenario tests (skeleton — require external dependencies)
# ---------------------------------------------------------------------------

@unittest.skip("CrewAI integration scenarios not yet implemented")
class TestCrewAIIntegrationScenarios(unittest.TestCase):
    """End-to-end integration scenarios with a real CrewAI setup.

    These tests require:
      - CrewAI package installed (pip install crewai)
      - An AgentMesh A2A server running
      - The concrete CrewAIAdapter implementation
    """

    def test_crewai_agent_sends_text_card(self) -> None:
        """CrewAI agent sends a text Card to another CrewAI agent."""
        raise NotImplementedError("Implement with real CrewAI adapter")

    def test_crewai_agent_receives_text_card(self) -> None:
        """CrewAI agent receives a text Card from another CrewAI agent."""
        raise NotImplementedError("Implement with real CrewAI adapter")

    def test_crewai_agent_with_tool_injection(self) -> None:
        """CrewAI agent gets A2ATool injected into its tools list."""
        raise NotImplementedError("Implement with real CrewAI adapter")

    def test_crewai_to_autogen_bridge(self) -> None:
        """CrewAI agent sends a card to an AutoGen agent via bridge."""
        raise NotImplementedError("Implement with real CrewAI adapter")

    def test_crewai_task_with_agentmesh_context(self) -> None:
        """CrewAI task execution with AgentMesh context data."""
        raise NotImplementedError("Implement with real CrewAI adapter")


# ---------------------------------------------------------------------------
# Run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
