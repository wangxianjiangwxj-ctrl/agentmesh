# AgentMesh A2A — CrewAI Integration Adapter (Skeleton)
#
# Phase 13, Direction 5: Real Agent Framework Integration.
# This module defines the abstract interface for integrating AgentMesh A2A
# with CrewAI. The adapter wraps AgentMesh operations as CrewAI BaseTool
# instances, enabling seamless agent-to-agent communication via AgentMesh.
#
# CrewAI Integration Approach (Provider Layer):
#   - A2ATool: A CrewAI BaseTool subclass that sends/receives Cards through
#     the AgentMesh A2A server. Agents use this tool to exchange messages.
#   - CrewAIAdapterBase: High-level orchestrator that creates agents,
#     registers tools, and manages the AgentMesh connection.
#
# Workflow:
#   1. User instantiates CrewAIAdapterBase with an AgentMesh server URL
#   2. Calls create_agent() to get a CrewAI Agent wired with A2ATool
#   3. Agents communicate by invoking the tool, which relays Cards
#      through AgentMesh to other agents
#
# Reference: research/phase13-integration-plan.md — Task 1

from __future__ import annotations

import abc
import dataclasses
import enum
from typing import Any, Dict, List, Optional, Protocol, TypeVar


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

T = TypeVar("T")

CardPayload = Dict[str, Any]
CardMetadata = Dict[str, Any]


# ---------------------------------------------------------------------------
# Enums & constants
# ---------------------------------------------------------------------------

class CardType(str, enum.Enum):
    """Standard A2A Card types exchanged between agents."""

    TEXT = "text"
    DATA = "data"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    CUSTOM = "custom"


class CardStatus(str, enum.Enum):
    """Delivery status of a Card."""

    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    TIMEOUT = "timeout"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class A2AToolDef:
    """Definition metadata for an A2ATool that CrewAI agents will use.

    Attributes:
        name: Unique tool name (e.g. "agentmesh_send").
        description: Human-readable description shown to CrewAI agent.
        card_type: Type of Card this tool sends.
        timeout_seconds: Maximum wait time for a response.
    """

    name: str
    description: str
    card_type: CardType = CardType.TEXT
    timeout_seconds: float = 30.0


@dataclasses.dataclass(frozen=True)
class CrewAIAgentConfig:
    """Configuration for creating a CrewAI Agent wired with AgentMesh.

    Attributes:
        role: Agent role (e.g., "researcher", "writer").
        goal: Agent goal description.
        backstory: Agent backstory for CrewAI context.
        allow_delegation: Whether this agent can delegate tasks to others.
        tools: Additional CrewAI tools beyond A2ATool.
        agentmesh_tool_name: Name of the A2ATool to attach.
    """

    role: str
    goal: str
    backstory: str = ""
    allow_delegation: bool = True
    tools: Optional[List[Any]] = None
    agentmesh_tool_name: str = "agentmesh_send"


@dataclasses.dataclass(frozen=True)
class CardSendResult:
    """Result of sending a Card through AgentMesh.

    Attributes:
        card_id: Unique identifier for the sent Card.
        status: Delivery status of the Card.
        recipient_agent: Name/ID of the target agent.
        error_message: Error details if status is FAILED.
    """

    card_id: str
    status: CardStatus
    recipient_agent: str
    error_message: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class CardReceiveResult:
    """Result of receiving a Card from AgentMesh.

    Attributes:
        card_id: Unique identifier of the received Card.
        sender_agent: Name/ID of the sending agent.
        card_type: Type of the Card payload.
        payload: The Card content.
        metadata: Additional routing/metadata information.
    """

    card_id: str
    sender_agent: str
    card_type: CardType
    payload: CardPayload
    metadata: Optional[CardMetadata] = None


# ---------------------------------------------------------------------------
# Protocols (structural typing)
# ---------------------------------------------------------------------------

class CrewAIAgentProtocol(Protocol):
    """Protocol describing a CrewAI Agent-compatible object.

    This allows the adapter to work with any object that follows the
    CrewAI Agent interface without depending on the crewai package.
    """

    role: str
    goal: str
    backstory: str
    allow_delegation: bool
    tools: List[Any]


# ---------------------------------------------------------------------------
# Abstract adapter base
# ---------------------------------------------------------------------------

class CrewAIAdapterBase(abc.ABC):
    """Abstract base class for integrating AgentMesh A2A with CrewAI.

    This adapter orchestrates:
      - Connection management to the AgentMesh A2A server
      - Creation of CrewAI agents pre-wired with A2ATool
      - Sending and receiving Cards on behalf of CrewAI agents
      - Tool lifecycle (registration, invocation, cleanup)

    Subclasses implement the concrete transport and tool-wiring logic.
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

        This should flush any pending messages and release resources.
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
        config: CrewAIAgentConfig,
        agent_id: Optional[str] = None,
    ) -> Any:
        """Create a CrewAI Agent configured with AgentMesh A2ATool.

        The returned object should be compatible with CrewAI's Agent class
        and have the A2ATool automatically injected into its tools list.

        Args:
            config: Agent configuration (role, goal, backstory, etc.).
            agent_id: Optional unique identifier; auto-generated if omitted.

        Returns:
            A CrewAI Agent instance (or compatible proxy) wired with A2ATool.

        Raises:
            RuntimeError: If not connected to the server.
        """
        ...

    @abc.abstractmethod
    def register_agent(self, agent_id: str, agent: Any) -> None:
        """Register a CrewAI agent with the AgentMesh server.

        After registration, the agent can send and receive Cards through
        AgentMesh. This is typically called automatically by create_agent(),
        but can be used for externally created agents.

        Args:
            agent_id: Unique identifier for the agent.
            agent: The CrewAI Agent instance to register.
        """
        ...

    @abc.abstractmethod
    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from the AgentMesh server.

        Args:
            agent_id: Identifier of the agent to unregister.
        """
        ...

    # ------------------------------------------------------------------
    # Card operations
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def send_card(
        self,
        sender_id: str,
        recipient_id: str,
        payload: CardPayload,
        card_type: CardType = CardType.TEXT,
        metadata: Optional[CardMetadata] = None,
        timeout_seconds: Optional[float] = None,
    ) -> CardSendResult:
        """Send an A2A Card from one CrewAI agent to another.

        Args:
            sender_id: Identifier of the sending agent.
            recipient_id: Identifier of the target agent.
            payload: The Card content (arbitrary JSON-serializable dict).
            card_type: Type of Card (text, data, tool_call, etc.).
            metadata: Optional routing metadata.
            timeout_seconds: Override default timeout for this send.

        Returns:
            CardSendResult with delivery status and card_id.

        Raises:
            ValueError: If sender_id or recipient_id is not registered.
            ConnectionError: If the server is unreachable.
        """
        ...

    @abc.abstractmethod
    def receive_card(
        self,
        agent_id: str,
        timeout_seconds: Optional[float] = None,
    ) -> Optional[CardReceiveResult]:
        """Receive the next pending Card for a CrewAI agent.

        Blocks until a Card is available or the timeout expires.

        Args:
            agent_id: Identifier of the receiving agent.
            timeout_seconds: Maximum wait time. None means use default.

        Returns:
            CardReceiveResult if a Card is available, None on timeout.

        Raises:
            ValueError: If agent_id is not registered.
            ConnectionError: If the server is unreachable.
        """
        ...

    @abc.abstractmethod
    def poll_cards(
        self,
        agent_id: str,
        max_count: int = 10,
        timeout_seconds: float = 1.0,
    ) -> List[CardReceiveResult]:
        """Poll for multiple pending Cards for a CrewAI agent.

        Non-blocking: returns immediately if no cards are available.

        Args:
            agent_id: Identifier of the receiving agent.
            max_count: Maximum number of Cards to retrieve.
            timeout_seconds: Per-poll timeout.

        Returns:
            List of received CardReceiveResult objects (may be empty).
        """
        ...

    # ------------------------------------------------------------------
    # Tool management
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def create_a2a_tool(
        self,
        tool_def: A2AToolDef,
    ) -> Any:
        """Create a CrewAI BaseTool-compatible object for AgentMesh.

        The returned tool should be usable as a CrewAI Tool, callable
        by the agent's LLM to send Cards through AgentMesh.

        Args:
            tool_def: Definition including name, description, card type.

        Returns:
            A CrewAI BaseTool-like object for AgentMesh operations.
        """
        ...

    @abc.abstractmethod
    def list_registered_tools(self) -> List[A2AToolDef]:
        """List all A2ATools currently registered on the server.

        Returns:
            List of tool definitions known to the AgentMesh server.
        """
        ...

    # ------------------------------------------------------------------
    # Task lifecycle (CrewAI-specific)
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def start_agent_task(
        self,
        agent_id: str,
        task_description: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Start a new task for a CrewAI agent via AgentMesh.

        The agent will execute the task and send results back as Cards.

        Args:
            agent_id: Identifier of the executing agent.
            task_description: Natural language task description.
            context: Optional contextual data for the task.

        Returns:
            Task identifier that can be used to query results.
        """
        ...

    @abc.abstractmethod
    def get_task_result(
        self,
        agent_id: str,
        task_id: str,
        timeout_seconds: float = 30.0,
    ) -> Optional[CardReceiveResult]:
        """Retrieve the result of a previously started task.

        Args:
            agent_id: Identifier of the executing agent.
            task_id: Task identifier returned by start_agent_task().
            timeout_seconds: Maximum wait time.

        Returns:
            CardReceiveResult containing the task result, or None if
            the task has not completed within the timeout.
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
        """
        ...
