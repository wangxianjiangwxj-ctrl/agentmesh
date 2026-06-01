# AgentMesh A2A — AutoGen Integration Adapter (Skeleton)
#
# Phase 13, Direction 5: Real Agent Framework Integration.
# This module defines the abstract interface for integrating AgentMesh A2A
# with AutoGen (pyautogen). The adapter wraps AgentMesh as a communication
# layer for AutoGen ConversableAgent instances, enabling cross-framework
# agent messaging via AgentMesh.
#
# AutoGen Integration Approach (Provider Layer):
#   - A2AAgent: A ConversableAgent subclass that routes send()/receive()
#     through the AgentMesh A2A server instead of direct in-process calls.
#   - AutoGenAdapterBase: High-level orchestrator that creates agents,
#     manages groups, and bridges AutoGen GroupChat with AgentMesh.
#
# Workflow:
#   1. User instantiates AutoGenAdapterBase with an AgentMesh server URL
#   2. Calls create_agent() to get an AutoGen agent wired via AgentMesh
#   3. Optionally calls create_group_chat() for multi-agent discussions
#   4. Messages flow through AgentMesh, enabling cross-framework routing
#
# Reference: research/phase13-integration-plan.md — Task 2

from __future__ import annotations

import abc
import dataclasses
import enum
from typing import Any, Dict, List, Optional, Protocol, TypeVar

# CardStatus is imported from the CrewAI adapter for shared enum usage
from .crewai_adapter import CardStatus


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

T = TypeVar("T")

MessagePayload = Dict[str, Any]
MessageMetadata = Dict[str, Any]


# ---------------------------------------------------------------------------
# Enums & constants
# ---------------------------------------------------------------------------

class MessageType(str, enum.Enum):
    """Standard message types in AutoGen conversations."""

    TEXT = "text"
    FUNCTION_CALL = "function_call"
    FUNCTION_RESULT = "function_result"
    CODE = "code"
    ERROR = "error"
    CUSTOM = "custom"


class ConversationPhase(str, enum.Enum):
    """Phases of an AutoGen conversation or GroupChat."""

    INITIATION = "initiation"
    ACTIVE = "active"
    WAITING_RESPONSE = "waiting_response"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class A2AAgentDef:
    """Definition metadata for an A2A-wired AutoGen agent.

    Attributes:
        name: Agent name (used as identifier in AgentMesh and AutoGen).
        system_message: System prompt for the agent LLM.
        description: Human-readable description for routing.
        max_consecutive_auto_reply: Limit on auto-reply chain length.
        human_input_mode: AutoGen human input mode ("NEVER", "TERMINATE", etc.).
    """

    name: str
    system_message: str = ""
    description: str = ""
    max_consecutive_auto_reply: int = 10
    human_input_mode: str = "NEVER"


@dataclasses.dataclass(frozen=True)
class AutoGenAgentConfig:
    """Full configuration for creating an AutoGen Agent with AgentMesh.

    Attributes:
        agent_def: Core agent definition (name, system_message, etc.).
        llm_config: LLM configuration dict for AutoGen (model, api_key, etc.).
        code_execution_config: Optional code execution configuration.
        agentmesh_routing: If True, route all messages through AgentMesh.
    """

    agent_def: A2AAgentDef
    llm_config: Optional[Dict[str, Any]] = None
    code_execution_config: Optional[Dict[str, Any]] = None
    agentmesh_routing: bool = True


@dataclasses.dataclass(frozen=True)
class MessageSendResult:
    """Result of sending a message through AgentMesh from AutoGen.

    Attributes:
        message_id: Unique identifier for the sent message.
        conversation_id: Conversation thread this message belongs to.
        status: Delivery status.
        recipient_agent: Name/ID of the target agent.
        error_message: Error details if status is FAILED.
    """

    message_id: str
    conversation_id: str
    status: CardStatus
    recipient_agent: str
    error_message: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class MessageReceiveResult:
    """Result of receiving a message from AgentMesh in AutoGen.

    Attributes:
        message_id: Unique identifier of the received message.
        conversation_id: Conversation thread identifier.
        sender_agent: Name/ID of the sending agent.
        message_type: Type of message content.
        content: The message payload.
        metadata: Additional routing/metadata information.
    """

    message_id: str
    conversation_id: str
    sender_agent: str
    message_type: MessageType
    content: MessagePayload
    metadata: Optional[MessageMetadata] = None


@dataclasses.dataclass(frozen=True)
class GroupChatConfig:
    """Configuration for an AutoGen GroupChat bridged through AgentMesh.

    Attributes:
        name: Group chat name for routing.
        agent_ids: List of agent identifiers in this group.
        max_round: Maximum conversation rounds.
        admin_name: Name of the admin agent (for summarization).
        speaker_selection_method: AutoGen speaker selection strategy.
    """

    name: str
    agent_ids: List[str]
    max_round: int = 50
    admin_name: Optional[str] = None
    speaker_selection_method: str = "auto"


# ---------------------------------------------------------------------------
# Protocols (structural typing)
# ---------------------------------------------------------------------------

class ConversableAgentProtocol(Protocol):
    """Protocol describing an AutoGen ConversableAgent-compatible object.

    Allows the adapter to work with any object following the AutoGen
    agent interface without depending on the pyautogen package.
    """

    name: str


# ---------------------------------------------------------------------------
# Abstract adapter base
# ---------------------------------------------------------------------------

class AutoGenAdapterBase(abc.ABC):
    """Abstract base class for integrating AgentMesh A2A with AutoGen.

    This adapter orchestrates:
      - Connection management to the AgentMesh A2A server
      - Creation of AutoGen agents that route through AgentMesh
      - GroupChat management with AgentMesh-backed routing
      - Message send/receive bridging between frameworks
      - Conversation lifecycle tracking

    Subclasses implement the concrete AutoGen agent wrapping and
    message routing logic.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def connect(self, server_url: str, timeout_seconds: float = 30.0) -> None:
        """Establish a connection to the AgentMesh A2A server.

        Args:
            server_url: Base URL of the AgentMesh server (e.g. "http://localhost:8080").
            timeout_seconds: Connection timeout.

        Raises:
            ConnectionError: If the server is unreachable.
            ValueError: If server_url is malformed.
        """
        ...

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Gracefully close the connection to the AgentMesh server.

        Flush pending messages and release resources.
        """
        ...

    @property
    @abc.abstractmethod
    def is_connected(self) -> bool:
        """Check whether the adapter is currently connected to the server."""
        ...

    # ------------------------------------------------------------------
    # Agent creation
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def create_agent(
        self,
        config: AutoGenAgentConfig,
    ) -> Any:
        """Create an AutoGen ConversableAgent wired with AgentMesh routing.

        The returned agent overrides send() and receive() to route messages
        through AgentMesh instead of direct in-process calls. This enables
        cross-framework and cross-process agent communication.

        Args:
            config: Full agent configuration (name, LLM, routing, etc.).

        Returns:
            An AutoGen ConversableAgent-compatible instance with
            AgentMesh message routing.

        Raises:
            RuntimeError: If not connected to the server.
        """
        ...

    @abc.abstractmethod
    def register_agent(self, agent_id: str, agent: Any) -> None:
        """Register an AutoGen agent with the AgentMesh server.

        After registration, the agent can send and receive messages
        through AgentMesh to any other registered agent (including
        CrewAI agents or custom agents).

        Args:
            agent_id: Unique identifier for the agent.
            agent: The AutoGen agent instance to register.
        """
        ...

    @abc.abstractmethod
    def unregister_agent(self, agent_id: str) -> None:
        """Remove an AutoGen agent from the AgentMesh server.

        Args:
            agent_id: Identifier of the agent to unregister.
        """
        ...

    # ------------------------------------------------------------------
    # Message operations
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def send_message(
        self,
        sender_id: str,
        recipient_id: str,
        content: MessagePayload,
        message_type: MessageType = MessageType.TEXT,
        conversation_id: Optional[str] = None,
        metadata: Optional[MessageMetadata] = None,
    ) -> MessageSendResult:
        """Send a message from one AutoGen agent to another via AgentMesh.

        This is the primitive operation that underlies AutoGen's send().
        It packs the message as an A2A Card and relays it through the
        AgentMesh server.

        Args:
            sender_id: Identifier of the sending agent.
            recipient_id: Identifier of the target agent.
            content: The message payload.
            message_type: Type of message (text, function_call, etc.).
            conversation_id: Optional conversation thread identifier.
            metadata: Optional routing metadata.

        Returns:
            MessageSendResult with delivery status and message_id.

        Raises:
            ValueError: If sender_id or recipient_id is not registered.
            ConnectionError: If the server is unreachable.
        """
        ...

    @abc.abstractmethod
    def receive_message(
        self,
        agent_id: str,
        timeout_seconds: Optional[float] = None,
    ) -> Optional[MessageReceiveResult]:
        """Receive the next pending message for an AutoGen agent.

        Blocks until a message is available or the timeout expires.
        This is the primitive operation that underlies AutoGen's receive().

        Args:
            agent_id: Identifier of the receiving agent.
            timeout_seconds: Maximum wait time. None means use default.

        Returns:
            MessageReceiveResult if a message is available, None on timeout.

        Raises:
            ValueError: If agent_id is not registered.
            ConnectionError: If the server is unreachable.
        """
        ...

    @abc.abstractmethod
    def poll_messages(
        self,
        agent_id: str,
        max_count: int = 10,
        conversation_id: Optional[str] = None,
    ) -> List[MessageReceiveResult]:
        """Poll for pending messages for an AutoGen agent.

        Non-blocking; returns immediately if no messages are available.

        Args:
            agent_id: Identifier of the receiving agent.
            max_count: Maximum number of messages to retrieve.
            conversation_id: Optional filter to a specific conversation.

        Returns:
            List of received MessageReceiveResult objects (may be empty).
        """
        ...

    # ------------------------------------------------------------------
    # GroupChat management
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def create_group_chat(
        self,
        config: GroupChatConfig,
    ) -> Any:
        """Create an AutoGen GroupChat managed through AgentMesh.

        The GroupChat uses AgentMesh for message routing, enabling
        cross-framework agents to participate in the same discussion.

        Args:
            config: GroupChat configuration (name, agents, rounds, etc.).

        Returns:
            An AutoGen GroupChat-compatible object using AgentMesh routing.

        Raises:
            RuntimeError: If not connected to the server.
        """
        ...

    @abc.abstractmethod
    def start_conversation(
        self,
        group_chat_id: str,
        initiator_id: str,
        message: str,
    ) -> str:
        """Start a new conversation in a GroupChat.

        Args:
            group_chat_id: Identifier of the GroupChat.
            initiator_id: Agent that initiates the conversation.
            message: The initial message to start the discussion.

        Returns:
            Conversation identifier for tracking.
        """
        ...

    @abc.abstractmethod
    def get_conversation_status(
        self,
        conversation_id: str,
    ) -> ConversationPhase:
        """Get the current phase of a conversation.

        Args:
            conversation_id: Conversation identifier.

        Returns:
            Current ConversationPhase.
        """
        ...

    @abc.abstractmethod
    def get_conversation_history(
        self,
        conversation_id: str,
        since_message_id: Optional[str] = None,
        max_messages: int = 50,
    ) -> List[MessageReceiveResult]:
        """Retrieve the message history of a conversation.

        Args:
            conversation_id: Conversation identifier.
            since_message_id: Optional starting point (exclusive).
            max_messages: Maximum number of messages to return.

        Returns:
            Chronological list of messages in the conversation.
        """
        ...

    # ------------------------------------------------------------------
    # Framework bridging
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def bridge_to_crewai(
        self,
        autogen_agent_id: str,
        crewai_agent_id: str,
    ) -> None:
        """Create a direct communication bridge between an AutoGen and
        a CrewAI agent.

        After bridging, messages sent from the AutoGen agent to the
        CrewAI agent are automatically translated between message
        formats (AutoGen message <-> A2A Card).

        Args:
            autogen_agent_id: Identifier of the AutoGen agent.
            crewai_agent_id: Identifier of the CrewAI agent.
        """
        ...

    @abc.abstractmethod
    def bridge_to_custom(
        self,
        autogen_agent_id: str,
        custom_agent_id: str,
        format_adapter: Optional[Any] = None,
    ) -> None:
        """Create a bridge to a custom (non-CrewAI, non-AutoGen) agent.

        Args:
            autogen_agent_id: Identifier of the AutoGen agent.
            custom_agent_id: Identifier of the custom agent.
            format_adapter: Optional adapter for message format translation.
        """
        ...

    # ------------------------------------------------------------------
    # Health & status
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Check the health of the AgentMesh connection and server.

        Returns:
            Dict with keys:
              - "status": "ok" | "degraded" | "down"
              - "server_url": str
              - "latency_ms": float
              - "registered_agents": int
              - "active_conversations": int
        """
        ...
