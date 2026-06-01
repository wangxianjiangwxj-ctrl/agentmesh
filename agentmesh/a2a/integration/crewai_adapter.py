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


# ---------------------------------------------------------------------------
# Imports for concrete implementation (stdlib only)
# ---------------------------------------------------------------------------

import json
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request


# ---------------------------------------------------------------------------
# Proxy classes (fallback when crewai package is not installed)
# ---------------------------------------------------------------------------

class _CrewAIProxyAgent:
    """Fallback proxy when the crewai package is not installed.

    Implements the CrewAIAgentProtocol interface with basic attribute
    storage so that create_agent() never fails due to missing crewai.
    """

    def __init__(
        self,
        config: CrewAIAgentConfig,
        agent_id: str,
        tools: List[Any],
    ) -> None:
        self.role = config.role
        self.goal = config.goal
        self.backstory = config.backstory
        self.allow_delegation = config.allow_delegation
        self.tools = list(tools)
        self.id = agent_id
        self._config = config

    def __repr__(self) -> str:
        return f"_CrewAIProxyAgent(role='{self.role}', id='{self.id}')"


class _A2AToolProxy:
    """CrewAI BaseTool-compatible proxy for A2A card operations.

    This is a callable object that CrewAI agents can invoke to send
    cards through the AgentMesh server. When CrewAI is not installed,
    this serves as a drop-in replacement for a BaseTool instance.
    """

    def __init__(self, tool_def: A2AToolDef, adapter: CrewAIAdapter) -> None:
        self.name = tool_def.name
        self.description = tool_def.description
        self._tool_def = tool_def
        self._adapter = adapter
        self._sender_id: Optional[str] = None

    def set_sender(self, agent_id: str) -> None:
        """Set the sending agent ID for this tool instance."""
        self._sender_id = agent_id

    def _run(self, recipient_id: str, message: str, **kwargs: Any) -> str:
        """Execute the tool: send a card and return the result.

        This is the primary invocation method expected by CrewAI's
        BaseTool interface.

        Args:
            recipient_id: Target agent ID.
            message: Text payload to send.
            **kwargs: Additional arguments forwarded to send_card().

        Returns:
            JSON-encoded response string.
        """
        if self._sender_id is None:
            return json.dumps({"error": "sender not set on tool"})

        payload: CardPayload = {"text": message}
        metadata: Optional[CardMetadata] = None
        if "metadata" in kwargs:
            metadata = kwargs["metadata"]
        if "payload" in kwargs and isinstance(kwargs["payload"], dict):
            payload.update(kwargs["payload"])

        result = self._adapter.send_card(
            sender_id=self._sender_id,
            recipient_id=recipient_id,
            payload=payload,
            card_type=self._tool_def.card_type,
            metadata=metadata,
            timeout_seconds=self._tool_def.timeout_seconds,
        )

        return json.dumps({
            "card_id": result.card_id,
            "status": result.status.value,
            "recipient_agent": result.recipient_agent,
            "error_message": result.error_message,
        })

    def __call__(self, recipient_id: str, message: str, **kwargs: Any) -> str:
        """Make the proxy directly callable."""
        return self._run(recipient_id, message, **kwargs)


# ---------------------------------------------------------------------------
# Concrete CrewAI adapter implementation
# ---------------------------------------------------------------------------

class CrewAIAdapter(CrewAIAdapterBase):
    """Concrete CrewAI adapter using HTTP transport to AgentMesh A2A Server.

    All communication with the AgentMesh server uses the REST API with
    JSON body encoding.  Only stdlib modules are used: ``urllib.request``
    for HTTP, ``threading`` for thread safety, ``uuid`` for card IDs, and
    ``time``/``json`` for serialisation.

    Every HTTP endpoint is prefixed with ``/api/v1/``.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self._server_url: str = ""
        self._host: str = "127.0.0.1"
        self._port: int = 8080
        self._connected: bool = False
        self._default_timeout: float = 30.0
        self._lock: threading.Lock = threading.Lock()
        self._agents: Dict[str, Any] = {}  # agent_id -> agent instance
        self._tools: Dict[str, _A2AToolProxy] = {}  # tool_name -> tool proxy

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api_url(self, path: str) -> str:
        """Build a full API URL for the given path.

        Args:
            path: Path relative to the API root (e.g. ``/send``).

        Returns:
            Full URL like ``http://host:port/api/v1/send``.
        """
        # Strip leading slash so we don't double it
        clean_path = path.lstrip("/")
        return f"http://{self._host}:{self._port}/api/v1/{clean_path}"

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Unified HTTP request helper.

        Args:
            method: HTTP method (``GET``, ``POST``, etc.).
            path: API path (e.g. ``/send``).  ``/api/v1/`` is prepended.
            body: JSON-serialisable dict sent as request body.
            timeout: Request timeout in seconds.  Falls back to
                     ``self._default_timeout`` if ``None``.

        Returns:
            Parsed JSON response dict.

        Raises:
            ConnectionError: If the server is unreachable.
            ValueError: If the server returns a non-2xx status.
        """
        url = self._api_url(path)
        effective_timeout = timeout if timeout is not None else self._default_timeout

        data_bytes: Optional[bytes] = None
        if body is not None:
            data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data_bytes,
            method=method,
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
                raw = resp.read()
                if raw:
                    return dict(json.loads(raw.decode("utf-8")))
                return {}
        except urllib.error.HTTPError as exc:
            # Try to extract a meaningful error message from the response body
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = str(exc)
            raise ValueError(
                f"HTTP {exc.code} from {method} {url}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ConnectionError(
                f"Cannot reach {url}: {exc.reason}"
            ) from exc
        except OSError as exc:
            raise ConnectionError(
                f"Connection error to {url}: {exc}"
            ) from exc

    def _ensure_connected(self) -> None:
        """Raise RuntimeError if the adapter is not connected."""
        if not self._connected:
            raise RuntimeError(
                "CrewAIAdapter is not connected. Call connect() first."
            )

    def _parse_card_type(self, value: str) -> CardType:
        """Safely parse a string into a CardType enum member."""
        try:
            return CardType(value)
        except ValueError:
            return CardType.CUSTOM

    # ------------------------------------------------------------------
    # connect / disconnect / is_connected
    # ------------------------------------------------------------------

    def connect(self, server_url: str, timeout_seconds: float = 30.0) -> None:
        """Establish a connection to the AgentMesh A2A server.

        Validates the URL format, pings the health endpoint, and marks
        the adapter as connected.

        Args:
            server_url: Base URL (e.g. ``"http://localhost:8080"``).
            timeout_seconds: Connection timeout.

        Raises:
            ValueError: If the URL is malformed.
            ConnectionError: If the server is unreachable.
        """
        # Validate and parse the server URL
        parsed = urllib.parse.urlparse(server_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(
                f"Invalid server_url: '{server_url}'. "
                f"Expected format: http://host:port"
            )

        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8080

        with self._lock:
            self._server_url = server_url
            self._host = host
            self._port = port
            self._default_timeout = timeout_seconds

        # Verify connectivity by hitting the health endpoint
        start = time.monotonic()
        try:
            self._request("GET", "/health", timeout=min(timeout_seconds, 10.0))
        except (ConnectionError, ValueError, OSError) as exc:
            raise ConnectionError(
                f"AgentMesh server at {server_url} is not reachable: {exc}"
            ) from exc

        latency = (time.monotonic() - start) * 1000.0

        # Notify server of our connection
        try:
            self._request(
                "POST",
                "/connect",
                body={"client": "crewai_adapter", "latency_ms": round(latency, 2)},
                timeout=min(timeout_seconds, 10.0),
            )
        except (ConnectionError, ValueError):
            # Non-fatal: we already verified the server is up
            pass

        with self._lock:
            self._connected = True

    def disconnect(self) -> None:
        """Gracefully close the connection to the AgentMesh server.

        Best-effort: notifies the server and clears local state.
        """
        with self._lock:
            was_connected = self._connected
            self._connected = False
            agents = dict(self._agents)
            self._agents.clear()
            tools = dict(self._tools)
            self._tools.clear()

        # Best-effort server notification
        if was_connected:
            try:
                self._request(
                    "POST",
                    "/disconnect",
                    body={"agent_ids": list(agents.keys())},
                    timeout=5.0,
                )
            except (ConnectionError, ValueError, OSError):
                pass

    @property
    def is_connected(self) -> bool:
        """Check whether the adapter is currently connected to the server."""
        return self._connected

    # ------------------------------------------------------------------
    # Agent creation
    # ------------------------------------------------------------------

    def create_agent(
        self,
        config: CrewAIAgentConfig,
        agent_id: Optional[str] = None,
    ) -> Any:
        """Create a CrewAI Agent configured with AgentMesh A2ATool.

        Attempts to import ``crewai.Agent``.  If the package is not
        available a ``_CrewAIProxyAgent`` is returned instead.

        The created agent has an A2ATool automatically added to its
        tool list, and is registered with the server.

        Args:
            config: Agent configuration.
            agent_id: Optional unique identifier; auto-generated if omitted.

        Returns:
            A CrewAI Agent (or proxy) wired with A2ATool.

        Raises:
            RuntimeError: If not connected.
        """
        self._ensure_connected()

        resolved_id = agent_id or f"crewai_agent_{uuid.uuid4().hex[:12]}"

        # Create or retrieve the A2ATool
        tool_def = A2AToolDef(
            name=config.agentmesh_tool_name,
            description=f"Send a card through AgentMesh to another agent",
            card_type=CardType.TEXT,
        )
        tool = self.create_a2a_tool(tool_def)

        # Build the full tool list (user-supplied tools + A2ATool)
        user_tools: list = list(config.tools) if config.tools else []
        all_tools = user_tools + [tool]

        # Try to import CrewAI; fall back to proxy on failure
        agent = self._try_create_crewai_agent(config, resolved_id, all_tools)
        self.register_agent(resolved_id, agent)

        return agent

    def _try_create_crewai_agent(
        self,
        config: CrewAIAgentConfig,
        agent_id: str,
        tools: List[Any],
    ) -> Any:
        """Attempt to create a real CrewAI Agent; return a proxy on failure."""
        try:
            from crewai import Agent as CrewAIAgent  # type: ignore[import-untyped]

            return CrewAIAgent(
                role=config.role,
                goal=config.goal,
                backstory=config.backstory,
                allow_delegation=config.allow_delegation,
                tools=tools,
            )
        except ImportError:
            return _CrewAIProxyAgent(config, agent_id, tools)

    # ------------------------------------------------------------------
    # Agent registration
    # ------------------------------------------------------------------

    def register_agent(self, agent_id: str, agent: Any) -> None:
        """Register a CrewAI agent with the AgentMesh server.

        Args:
            agent_id: Unique identifier for the agent.
            agent: The agent instance to register.

        Raises:
            ValueError: If the agent is already registered locally.
            ConnectionError: If the server is unreachable.
        """
        self._ensure_connected()

        with self._lock:
            if agent_id in self._agents:
                raise ValueError(f"Agent '{agent_id}' is already registered.")
            self._agents[agent_id] = agent

        try:
            self._request(
                "POST",
                "/register_agent",
                body={
                    "agent_id": agent_id,
                    "role": getattr(agent, "role", "unknown"),
                },
            )
        except (ConnectionError, ValueError) as exc:
            # Roll back local registration on server failure
            with self._lock:
                self._agents.pop(agent_id, None)
            raise ConnectionError(
                f"Failed to register agent '{agent_id}' with server: {exc}"
            ) from exc

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from the AgentMesh server and local state.

        Args:
            agent_id: Identifier of the agent to unregister.
        """
        with self._lock:
            self._agents.pop(agent_id, None)

        try:
            self._request(
                "POST",
                "/unregister_agent",
                body={"agent_id": agent_id},
                timeout=5.0,
            )
        except (ConnectionError, ValueError, OSError):
            pass  # Best-effort

    # ------------------------------------------------------------------
    # Card operations
    # ------------------------------------------------------------------

    def send_card(
        self,
        sender_id: str,
        recipient_id: str,
        payload: CardPayload,
        card_type: CardType = CardType.TEXT,
        metadata: Optional[CardMetadata] = None,
        timeout_seconds: Optional[float] = None,
    ) -> CardSendResult:
        """Send an A2A Card from one agent to another via the server.

        Args:
            sender_id: Sending agent ID.
            recipient_id: Target agent ID.
            payload: Arbitrary JSON-serializable dict.
            card_type: Card type classification.
            metadata: Optional routing metadata.
            timeout_seconds: Override default timeout.

        Returns:
            CardSendResult with delivery status.

        Raises:
            ConnectionError: If the server is unreachable.
        """
        self._ensure_connected()

        card_id: str = uuid.uuid4().hex

        request_body: Dict[str, Any] = {
            "card_id": card_id,
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "payload": payload,
            "card_type": card_type.value,
        }
        if metadata is not None:
            request_body["metadata"] = metadata

        eff_timeout = (
            timeout_seconds if timeout_seconds is not None
            else self._default_timeout
        )

        try:
            response = self._request(
                "POST",
                "/send",
                body=request_body,
                timeout=eff_timeout,
            )
        except (ConnectionError, ValueError) as exc:
            return CardSendResult(
                card_id=card_id,
                status=CardStatus.FAILED,
                recipient_agent=recipient_id,
                error_message=str(exc),
            )

        server_status = response.get("status", CardStatus.DELIVERED.value)
        parsed_status = CardStatus.PENDING
        try:
            parsed_status = CardStatus(server_status)
        except ValueError:
            parsed_status = CardStatus.DELIVERED

        return CardSendResult(
            card_id=response.get("card_id", card_id),
            status=parsed_status,
            recipient_agent=recipient_id,
            error_message=response.get("error_message"),
        )

    def receive_card(
        self,
        agent_id: str,
        timeout_seconds: Optional[float] = None,
    ) -> Optional[CardReceiveResult]:
        """Receive the next pending Card for an agent (blocking).

        Args:
            agent_id: Receiving agent ID.
            timeout_seconds: Maximum wait time. ``None`` uses default.

        Returns:
            CardReceiveResult if a card is available, ``None`` on timeout.

        Raises:
            ConnectionError: If the server is unreachable.
        """
        self._ensure_connected()

        query_params = urllib.parse.urlencode({"agent_id": agent_id})
        eff_timeout = (
            timeout_seconds if timeout_seconds is not None
            else self._default_timeout
        )

        try:
            response = self._request(
                "POST",
                f"/receive?{query_params}",
                body=None,
                timeout=eff_timeout,
            )
        except ConnectionError:
            raise
        except ValueError as exc:
            # Non-2xx status from a well-formed server
            error_str = str(exc)
            if "404" in error_str or "408" in error_str:
                return None
            raise ConnectionError(error_str) from exc

        if not response:
            return None

        return self._response_to_card_receive(response)

    def poll_cards(
        self,
        agent_id: str,
        max_count: int = 10,
        timeout_seconds: float = 1.0,
    ) -> List[CardReceiveResult]:
        """Poll for multiple pending Cards (non-blocking).

        Args:
            agent_id: Receiving agent ID.
            max_count: Maximum number of cards to retrieve.
            timeout_seconds: Per-poll timeout.

        Returns:
            List of received cards (may be empty).
        """
        self._ensure_connected()

        query_params = urllib.parse.urlencode({
            "agent_id": agent_id,
            "max_count": max_count,
        })

        try:
            response = self._request(
                "POST",
                f"/poll?{query_params}",
                body=None,
                timeout=timeout_seconds,
            )
        except (ConnectionError, ValueError, OSError):
            return []

        cards_raw = response.get("cards", []) if isinstance(response, dict) else []
        if not isinstance(cards_raw, list):
            return []

        results: List[CardReceiveResult] = []
        for raw in cards_raw[:max_count]:
            if isinstance(raw, dict):
                parsed = self._response_to_card_receive(raw)
                if parsed is not None:
                    results.append(parsed)
        return results

    def _response_to_card_receive(
        self,
        response: Dict[str, Any],
    ) -> Optional[CardReceiveResult]:
        """Convert a server response dict into a CardReceiveResult."""
        if not response:
            return None

        card_type_str = response.get("card_type", CardType.TEXT.value)
        if not isinstance(card_type_str, str):
            card_type_str = CardType.TEXT.value

        return CardReceiveResult(
            card_id=str(response.get("card_id", "")),
            sender_agent=str(response.get("sender_id", response.get("sender_agent", ""))),
            card_type=self._parse_card_type(card_type_str),
            payload=dict(response.get("payload", {})),
            metadata=(
                dict(response["metadata"])
                if response.get("metadata") is not None
                else None
            ),
        )

    # ------------------------------------------------------------------
    # Tool management
    # ------------------------------------------------------------------

    def create_a2a_tool(
        self,
        tool_def: A2AToolDef,
    ) -> Any:
        """Create a CrewAI BaseTool-compatible object for AgentMesh.

        Returns a ``_A2AToolProxy`` that is callable and compatible with
        CrewAI's tool interface.

        Args:
            tool_def: Tool definition.

        Returns:
            A callable tool proxy.
        """
        tool = _A2AToolProxy(tool_def, self)
        with self._lock:
            self._tools[tool_def.name] = tool
        return tool

    def list_registered_tools(self) -> List[A2AToolDef]:
        """List all A2ATools currently registered on the server.

        Returns:
            List of tool definitions from the server.
        """
        self._ensure_connected()

        try:
            response = self._request("GET", "/tools")
        except (ConnectionError, ValueError, OSError):
            with self._lock:
                return [self._tools[n]._tool_def for n in self._tools]

        tools_raw = response.get("tools", []) if isinstance(response, dict) else []
        if not isinstance(tools_raw, list):
            with self._lock:
                return [self._tools[n]._tool_def for n in self._tools]

        result: List[A2AToolDef] = []
        for raw in tools_raw:
            if not isinstance(raw, dict):
                continue
            try:
                result.append(A2AToolDef(
                    name=str(raw.get("name", "")),
                    description=str(raw.get("description", "")),
                    card_type=self._parse_card_type(
                        raw.get("card_type", CardType.TEXT.value)
                    ),
                    timeout_seconds=float(raw.get("timeout_seconds", 30.0)),
                ))
            except (ValueError, TypeError):
                continue
        return result

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    def start_agent_task(
        self,
        agent_id: str,
        task_description: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Start a new task for an agent via the server.

        Args:
            agent_id: Executing agent ID.
            task_description: Task description.
            context: Optional context data.

        Returns:
            Task identifier string.

        Raises:
            ConnectionError: If the server is unreachable.
        """
        self._ensure_connected()

        body: Dict[str, Any] = {
            "agent_id": agent_id,
            "task_description": task_description,
        }
        if context is not None:
            body["context"] = context

        try:
            response = self._request("POST", "/tasks/start", body=body)
        except (ConnectionError, ValueError) as exc:
            raise ConnectionError(
                f"Failed to start task for agent '{agent_id}': {exc}"
            ) from exc

        return str(response.get("task_id", uuid.uuid4().hex))

    def get_task_result(
        self,
        agent_id: str,
        task_id: str,
        timeout_seconds: float = 30.0,
    ) -> Optional[CardReceiveResult]:
        """Retrieve the result of a previously started task.

        Args:
            agent_id: Executing agent ID.
            task_id: Task identifier.
            timeout_seconds: Maximum wait time.

        Returns:
            CardReceiveResult or ``None`` if not yet completed.

        Raises:
            ConnectionError: If the server is unreachable.
        """
        self._ensure_connected()

        body: Dict[str, Any] = {
            "agent_id": agent_id,
            "task_id": task_id,
        }

        try:
            response = self._request(
                "POST",
                "/tasks/result",
                body=body,
                timeout=timeout_seconds,
            )
        except ConnectionError:
            raise
        except ValueError as exc:
            error_str = str(exc)
            if "404" in error_str or "408" in error_str:
                return None
            raise ConnectionError(error_str) from exc

        if not response:
            return None

        return self._response_to_card_receive(response)

    # ------------------------------------------------------------------
    # Health & status
    # ------------------------------------------------------------------

    def health_check(self) -> Dict[str, Any]:
        """Check the health of the AgentMesh connection and server.

        Returns:
            Dict with status, server URL, latency, and agent count.
        """
        start = time.monotonic()
        try:
            response = self._request("GET", "/health", timeout=10.0)
            latency_ms = (time.monotonic() - start) * 1000.0
            registered = 0
            registered_raw = response.get("registered_agents", 0)
            if isinstance(registered_raw, (int, float)):
                registered = int(registered_raw)
            return {
                "status": response.get("status", "ok"),
                "server_url": self._server_url,
                "latency_ms": round(latency_ms, 2),
                "registered_agents": registered,
            }
        except (ConnectionError, ValueError, OSError) as exc:
            with self._lock:
                local_count = len(self._agents)
            return {
                "status": "down",
                "server_url": self._server_url,
                "latency_ms": -1.0,
                "registered_agents": local_count,
                "error": str(exc),
            }
