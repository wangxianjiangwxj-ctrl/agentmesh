"""Tests for the AgentMesh-AutoGen integration adapter.

Phase 13, Direction 5: Real Agent Framework Integration.

This module contains skeleton test cases for the AutoGenAdapterBase class.
Tests are structured to be discoverable by pytest but marked as skipped
when the concrete implementation or external dependencies are unavailable.

Usage:
    # Run all AutoGen adapter tests (will skip if not implemented)
    pytest tests/integration/test_autogen_adapter.py -v

    # Run tests with stdout
    pytest tests/integration/test_autogen_adapter.py -v -s

Reference: research/phase13-integration-plan.md — Task 2
"""

import unittest
from typing import Optional
from unittest import mock


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------

try:
    from agentmesh.a2a.integration import (
        AutoGenAdapterBase,
        A2AAgentDef,
        AutoGenAgentConfig,
        GroupChatConfig,
        MessageType,
        CardStatus,
        MessageSendResult,
        MessageReceiveResult,
        ConversationPhase,
    )
    HAS_ADAPTER = True
except ImportError:
    HAS_ADAPTER = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MOCK_SERVER_URL = "http://localhost:8080"
TEST_AGENT_ID = "test_autogen_agent"
TEST_RECIPIENT_ID = "test_autogen_recipient"
TEST_CONVERSATION_ID = "conv-001"


# ---------------------------------------------------------------------------
# Concrete stub for testing
# ---------------------------------------------------------------------------

class StubAutoGenAdapter(AutoGenAdapterBase):
    """Minimal concrete stub for unit-testing the abstract interface.

    Provides no-op implementations of all abstract methods. Used to verify
    that the interface is correct and testable, not for real integration.
    """

    def __init__(self) -> None:
        self._connected = False
        self._server_url = ""
        self._agents: dict = {}
        self._conversations: dict = {}

    # Lifecycle
    def connect(self, server_url: str, timeout_seconds: float = 30.0) -> None:
        if not server_url:
            raise ValueError("server_url must not be empty")
        self._server_url = server_url
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False
        self._agents.clear()
        self._conversations.clear()

    @property
    def is_connected(self) -> bool:
        return self._connected

    # Agent creation
    def create_agent(self, config: AutoGenAgentConfig) -> object:
        agent_id = config.agent_def.name
        self._agents[agent_id] = config
        return mock.MagicMock()

    def register_agent(self, agent_id: str, agent: object) -> None:
        self._agents[agent_id] = agent

    def unregister_agent(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)

    # Message operations
    def send_message(
        self,
        sender_id: str,
        recipient_id: str,
        content: dict,
        message_type: MessageType = MessageType.TEXT,
        conversation_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> MessageSendResult:
        cid = conversation_id or TEST_CONVERSATION_ID
        return MessageSendResult(
            message_id="stub-msg-001",
            conversation_id=cid,
            status=CardStatus.DELIVERED,
            recipient_agent=recipient_id,
        )

    def receive_message(
        self,
        agent_id: str,
        timeout_seconds: Optional[float] = None,
    ) -> Optional[MessageReceiveResult]:
        return MessageReceiveResult(
            message_id="stub-msg-001",
            conversation_id=TEST_CONVERSATION_ID,
            sender_agent="stub-sender",
            message_type=MessageType.TEXT,
            content={"text": "stub message"},
        )

    def poll_messages(
        self,
        agent_id: str,
        max_count: int = 10,
        conversation_id: Optional[str] = None,
    ) -> list[MessageReceiveResult]:
        return [
            MessageReceiveResult(
                message_id="stub-msg-002",
                conversation_id=conversation_id or TEST_CONVERSATION_ID,
                sender_agent="stub-sender",
                message_type=MessageType.TEXT,
                content={"text": "polled message"},
            )
        ]

    # GroupChat
    def create_group_chat(self, config: GroupChatConfig) -> object:
        self._conversations[config.name] = config
        return mock.MagicMock()

    def start_conversation(
        self,
        group_chat_id: str,
        initiator_id: str,
        message: str,
    ) -> str:
        cid = f"conv-{group_chat_id}-{hash(message) % 10000}"
        self._conversations[cid] = ConversationPhase.ACTIVE
        return cid

    def get_conversation_status(self, conversation_id: str) -> ConversationPhase:
        return self._conversations.get(conversation_id, ConversationPhase.TERMINATED)

    def get_conversation_history(
        self,
        conversation_id: str,
        since_message_id: Optional[str] = None,
        max_messages: int = 50,
    ) -> list[MessageReceiveResult]:
        return [
            MessageReceiveResult(
                message_id="stub-hist-001",
                conversation_id=conversation_id,
                sender_agent="stub-sender",
                message_type=MessageType.TEXT,
                content={"text": "historical message"},
            )
        ]

    # Bridging
    def bridge_to_crewai(
        self,
        autogen_agent_id: str,
        crewai_agent_id: str,
    ) -> None:
        pass

    def bridge_to_custom(
        self,
        autogen_agent_id: str,
        custom_agent_id: str,
        format_adapter: Optional[object] = None,
    ) -> None:
        pass

    # Health
    def health_check(self) -> dict:
        return {
            "status": "ok",
            "server_url": self._server_url,
            "latency_ms": 0.0,
            "registered_agents": len(self._agents),
            "active_conversations": sum(
                1 for v in self._conversations.values() if v == ConversationPhase.ACTIVE
            ),
        }

    def _check_prerequisite(self, package_name: str) -> bool:
        return True


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_ADAPTER, "agentmesh.a2a.integration not importable")
class TestAutoGenAdapterInterface(unittest.TestCase):
    """Verify the AutoGenAdapterBase abstract interface."""

    def setUp(self) -> None:
        self.adapter = StubAutoGenAdapter()

    # ------------------------------------------------------------------
    # Lifecycle tests
    # ------------------------------------------------------------------

    def test_connect_disconnect_cycle(self) -> None:
        """Adapter should connect and disconnect cleanly."""
        self.assertFalse(self.adapter.is_connected)
        self.adapter.connect(MOCK_SERVER_URL)
        self.assertTrue(self.adapter.is_connected)
        self.adapter.disconnect()
        self.assertFalse(self.adapter.is_connected)

    def test_connect_reject_empty_url(self) -> None:
        """Connecting with an empty URL should raise ValueError."""
        with self.assertRaises(ValueError):
            self.adapter.connect("")

    def test_double_connect(self) -> None:
        """Connecting twice should be idempotent."""
        self.adapter.connect(MOCK_SERVER_URL)
        self.adapter.connect(MOCK_SERVER_URL)
        self.assertTrue(self.adapter.is_connected)

    # ------------------------------------------------------------------
    # Agent creation tests
    # ------------------------------------------------------------------

    def test_create_agent_with_minimal_config(self) -> None:
        """Creating an agent with only required fields should work."""
        agent_def = A2AAgentDef(name="assistant")
        config = AutoGenAgentConfig(agent_def=agent_def)
        agent = self.adapter.create_agent(config)
        self.assertIsNotNone(agent)

    def test_create_agent_with_full_config(self) -> None:
        """Creating an agent with full configuration should work."""
        agent_def = A2AAgentDef(
            name="researcher",
            system_message="You are a research assistant.",
            description="Helps with research tasks",
            max_consecutive_auto_reply=5,
            human_input_mode="TERMINATE",
        )
        config = AutoGenAgentConfig(
            agent_def=agent_def,
            llm_config={"model": "gpt-4", "temperature": 0.7},
            agentmesh_routing=True,
        )
        agent = self.adapter.create_agent(config)
        self.assertIsNotNone(agent)

    # ------------------------------------------------------------------
    # Message operations tests
    # ------------------------------------------------------------------

    def test_send_message_returns_result(self) -> None:
        """Sending a message should return MessageSendResult."""
        result = self.adapter.send_message(
            sender_id="sender",
            recipient_id="receiver",
            content={"text": "hello"},
        )
        self.assertIsInstance(result, MessageSendResult)
        self.assertEqual(result.status, CardStatus.DELIVERED)
        self.assertIsNotNone(result.message_id)
        self.assertIsNotNone(result.conversation_id)

    def test_send_message_with_conversation_id(self) -> None:
        """Sending a message with explicit conversation ID should work."""
        result = self.adapter.send_message(
            sender_id="sender",
            recipient_id="receiver",
            content={"text": "hello"},
            conversation_id="custom-conv-001",
        )
        self.assertEqual(result.conversation_id, "custom-conv-001")

    def test_receive_message_returns_result(self) -> None:
        """Receiving a message should return MessageReceiveResult."""
        result = self.adapter.receive_message(agent_id="agent-1")
        self.assertIsInstance(result, MessageReceiveResult)
        self.assertIsNotNone(result.message_id)
        self.assertIsNotNone(result.content)

    def test_poll_messages_returns_list(self) -> None:
        """Polling messages should return a list."""
        results = self.adapter.poll_messages(agent_id="agent-1", max_count=5)
        self.assertIsInstance(results, list)
        if results:
            self.assertIsInstance(results[0], MessageReceiveResult)

    def test_send_message_empty_content(self) -> None:
        """Sending with empty content should still succeed."""
        result = self.adapter.send_message(
            sender_id="sender",
            recipient_id="receiver",
            content={},
        )
        self.assertEqual(result.status, CardStatus.DELIVERED)

    # ------------------------------------------------------------------
    # GroupChat tests
    # ------------------------------------------------------------------

    def test_create_group_chat(self) -> None:
        """Creating a GroupChat should work with valid config."""
        config = GroupChatConfig(
            name="test-group",
            agent_ids=["agent-a", "agent-b"],
            max_round=30,
            speaker_selection_method="round_robin",
        )
        chat = self.adapter.create_group_chat(config)
        self.assertIsNotNone(chat)

    def test_create_group_chat_single_agent(self) -> None:
        """Creating a GroupChat with a single agent should still work."""
        config = GroupChatConfig(
            name="solo-group",
            agent_ids=["agent-alone"],
            max_round=10,
        )
        chat = self.adapter.create_group_chat(config)
        self.assertIsNotNone(chat)

    def test_start_conversation_returns_id(self) -> None:
        """Starting a conversation should return a conversation ID."""
        self.adapter.create_group_chat(GroupChatConfig(name="g1", agent_ids=["a1", "a2"]))
        conv_id = self.adapter.start_conversation(
            group_chat_id="g1",
            initiator_id="a1",
            message="Let's discuss",
        )
        self.assertIsInstance(conv_id, str)
        self.assertTrue(len(conv_id) > 0)

    def test_get_conversation_status(self) -> None:
        """Getting conversation status should return a ConversationPhase."""
        self.adapter.create_group_chat(GroupChatConfig(name="g2", agent_ids=["a1", "a2"]))
        conv_id = self.adapter.start_conversation("g2", "a1", "Hello")
        status = self.adapter.get_conversation_status(conv_id)
        self.assertIsInstance(status, ConversationPhase)

    def test_get_conversation_history(self) -> None:
        """Getting conversation history should return a list of messages."""
        self.adapter.create_group_chat(GroupChatConfig(name="g3", agent_ids=["a1", "a2"]))
        conv_id = self.adapter.start_conversation("g3", "a1", "Hello")
        history = self.adapter.get_conversation_history(conv_id)
        self.assertIsInstance(history, list)

    # ------------------------------------------------------------------
    # Bridging tests
    # ------------------------------------------------------------------

    def test_bridge_to_crewai(self) -> None:
        """Bridging to CrewAI should not raise."""
        try:
            self.adapter.bridge_to_crewai("autogen-agent", "crewai-agent")
        except Exception as exc:
            self.fail(f"bridge_to_crewai raised {exc}")

    def test_bridge_to_custom(self) -> None:
        """Bridging to a custom agent should not raise."""
        try:
            self.adapter.bridge_to_custom("autogen-agent", "custom-agent")
        except Exception as exc:
            self.fail(f"bridge_to_custom raised {exc}")

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def test_health_check_returns_expected_keys(self) -> None:
        """Health check should return a dict with expected keys."""
        self.adapter.connect(MOCK_SERVER_URL)
        health = self.adapter.health_check()
        self.assertIn("status", health)
        self.assertIn("server_url", health)
        self.assertIn("latency_ms", health)
        self.assertIn("registered_agents", health)
        self.assertIn("active_conversations", health)
        self.assertEqual(health["status"], "ok")

    # ------------------------------------------------------------------
    # Register / unregister
    # ------------------------------------------------------------------

    def test_register_and_unregister_agent(self) -> None:
        """Register then unregister an agent."""
        self.adapter.connect(MOCK_SERVER_URL)
        agent_def = A2AAgentDef(name="test-agent")
        config = AutoGenAgentConfig(agent_def=agent_def)
        agent = self.adapter.create_agent(config)
        self.adapter.register_agent("test-agent", agent)
        self.adapter.unregister_agent("test-agent")

    def test_unregister_nonexistent_agent(self) -> None:
        """Unregistering a non-existent agent should not raise."""
        try:
            self.adapter.unregister_agent("nonexistent")
        except Exception as exc:
            self.fail(f"unregister_agent raised {exc}")


# ---------------------------------------------------------------------------
# Integration scenario tests (skeleton — require external dependencies)
# ---------------------------------------------------------------------------

@unittest.skip("AutoGen integration scenarios not yet implemented")
class TestAutoGenIntegrationScenarios(unittest.TestCase):
    """End-to-end integration scenarios with a real AutoGen setup.

    These tests require:
      - pyautogen package installed (pip install pyautogen)
      - An AgentMesh A2A server running
      - The concrete AutoGenAdapter implementation
      - LLM API key for agent conversations
    """

    def test_autogen_agent_sends_message(self) -> None:
        """AutoGen agent sends a message to another AutoGen agent."""
        raise NotImplementedError("Implement with real AutoGen adapter")

    def test_autogen_agent_receives_message(self) -> None:
        """AutoGen agent receives a message from another AutoGen agent."""
        raise NotImplementedError("Implement with real AutoGen adapter")

    def test_autogen_group_chat_via_agentmesh(self) -> None:
        """Multi-agent GroupChat with AgentMesh routing."""
        raise NotImplementedError("Implement with real AutoGen adapter")

    def test_autogen_to_crewai_bridge(self) -> None:
        """AutoGen agent sends a message to a CrewAI agent via bridge."""
        raise NotImplementedError("Implement with real AutoGen adapter")

    def test_autogen_conversation_history(self) -> None:
        """Retrieve full conversation history after a multi-turn discussion."""
        raise NotImplementedError("Implement with real AutoGen adapter")


# ---------------------------------------------------------------------------
# Run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
