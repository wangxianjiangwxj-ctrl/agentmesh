"""AgentMesh A2A -- AutoGen Integration Adapter.

Phase 13, Direction 5: Real Agent Framework Integration.
This module defines the abstract interface for integrating AgentMesh A2A
with AutoGen (pyautogen). The adapter wraps AgentMesh as a communication
layer for AutoGen ConversableAgent instances, enabling cross-framework
agent messaging via AgentMesh.

AutoGen Integration Approach (Provider Layer):
  - A2AAgent: A ConversableAgent subclass that routes send()/receive()
    through the AgentMesh A2A server instead of direct in-process calls.
  - AutoGenAdapterBase: High-level orchestrator that creates agents,
    manages groups, and bridges AutoGen GroupChat with AgentMesh.

Workflow:
  1. User instantiates AutoGenAdapterBase with an AgentMesh server URL
  2. Calls create_agent() to get an AutoGen agent wired via AgentMesh
  3. Optionally calls create_group_chat() for multi-agent discussions
  4. Messages flow through AgentMesh, enabling cross-framework routing

Reference: research/phase13-integration-plan.md -- Task 2
"""


from __future__ import annotations

import abc
import dataclasses
import enum
from typing import Any, Dict, List, Optional, Protocol, TypeVar


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
# CardStatus is needed at runtime for MessageSendResult construction.
# It is re-exported from ``__init__.py`` via ``crewai_adapter``.
# ---------------------------------------------------------------------------

from .crewai_adapter import CardStatus


# ---------------------------------------------------------------------------
# Proxy class (fallback when pyautogen is not installed)
# ---------------------------------------------------------------------------

class _ConversableAgentProxy:
    """AutoGen ConversableAgent-compatible proxy that routes via AgentMesh.

    Implements the ConversableAgentProtocol interface.  All ``send()`` calls
    are forwarded to the ``AutoGenAdapter.send_message()``, and ``receive()``
    calls store messages in an internal inbox.  ``generate_reply()`` returns
    a pre-configured reply through an optional ``_generate_reply_fn``, or a
    simple echo fallback.

    This proxy allows the adapter to function without the ``pyautogen``
    package installed, making it suitable for environments where only
    the A2A communication layer is needed.
    """

    def __init__(
        self,
        name: str,
        adapter: AutoGenAdapter,
        system_message: str = "",
        description: str = "",
        max_consecutive_auto_reply: int = 10,
        human_input_mode: str = "NEVER",
        llm_config: Optional[Dict[str, Any]] = None,
        code_execution_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.name = name
        self._adapter = adapter
        self._system_message = system_message
        self._description = description
        self._max_consecutive_auto_reply = max_consecutive_auto_reply
        self._human_input_mode = human_input_mode
        self._llm_config = dict(llm_config) if llm_config else {}
        self._code_execution_config = code_execution_config
        self._reply_count: int = 0
        self._inbox: List[Dict[str, Any]] = []
        self._generate_reply_fn: Optional[Any] = None

    # ------------------------------------------------------------------
    # ConversableAgent core interface
    # ------------------------------------------------------------------

    def send(
        self,
        message: Any,
        recipient: Any = None,
        request_reply: Optional[bool] = None,
        silent: Optional[bool] = None,
    ) -> bool:
        """Send a message to another agent via AgentMesh.

        Args:
            message: Message content (string or dict).
            recipient: Target agent (must have a ``name`` attribute).
            request_reply: If True, wait for a reply after sending.
            silent: If True, suppress logging.

        Returns:
            ``True`` if the message was sent successfully.
        """
        if recipient is None:
            return False

        recipient_name = getattr(recipient, "name", str(recipient))

        payload: MessagePayload
        if isinstance(message, str):
            payload = {"text": message}
        elif isinstance(message, dict):
            payload = message
        else:
            payload = {"content": str(message)}

        result = self._adapter.send_message(
            sender_id=self.name,
            recipient_id=recipient_name,
            content=payload,
        )

        return result.status == CardStatus.DELIVERED

    def receive(
        self,
        message: Any,
        sender: Any = None,
        request_reply: Optional[bool] = None,
        silent: Optional[bool] = None,
    ) -> None:
        """Receive a message from another agent.

        Stores the message in the internal inbox for later processing.
        If ``request_reply`` is True, automatically generates and sends
        a reply back to the sender.

        Args:
            message: The received message content.
            sender: The sending agent.
            request_reply: If True, auto-reply after receiving.
            silent: If True, suppress logging.
        """
        sender_name = (
            getattr(sender, "name", "unknown")
            if sender is not None
            else "unknown"
        )
        self._inbox.append({
            "sender": sender_name,
            "message": message,
            "timestamp": time.monotonic(),
        })

        if request_reply:
            msg_list = [message] if not isinstance(message, list) else message
            reply = self.generate_reply(messages=msg_list)
            if reply is not None:
                self.send(reply, recipient=sender)

    def generate_reply(
        self,
        messages: Optional[List[Any]] = None,
        sender: Any = None,
        exclude: Optional[Any] = None,
    ) -> Optional[str]:
        """Generate a reply based on the configured strategy.

        Priority:
          1. ``_generate_reply_fn`` (custom callable, set externally)
          2. LLM config placeholder (``_try_llm_reply``)
          3. Default echo fallback

        Returns:
            A string reply, or ``None`` if ``max_consecutive_auto_reply``
            has been reached.
        """
        if self._reply_count >= self._max_consecutive_auto_reply:
            return None

        self._reply_count += 1

        # Custom reply function takes precedence
        if self._generate_reply_fn is not None:
            try:
                reply = self._generate_reply_fn(messages, sender, exclude)
                if reply is not None:
                    return str(reply)
            except Exception:
                pass

        # LLM config placeholder (overridden when pyautogen is available)
        if self._llm_config:
            reply = self._try_llm_reply(messages)
            if reply:
                return reply

        # Default echo fallback
        if messages and len(messages) > 0:
            last = messages[-1]
            if isinstance(last, dict):
                content = last.get("content", last.get("text", str(last)))
            else:
                content = str(last)
            return f"[{self.name} acknowledges: {content[:200]}]"

        return f"[{self.name}]: I acknowledge your message."

    def _try_llm_reply(self, messages: Optional[List[Any]]) -> Optional[str]:
        """Placeholder for LLM-based reply generation.

        Can be overridden by subclasses or patched at runtime when
        pyautogen and an LLM backend are available.
        """
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def reset_reply_count(self) -> None:
        """Reset the auto-reply counter for a new conversation."""
        self._reply_count = 0

    def __repr__(self) -> str:
        return f"_ConversableAgentProxy(name='{self.name}')"


# ---------------------------------------------------------------------------
# Concrete AutoGen adapter implementation
# ---------------------------------------------------------------------------

class AutoGenAdapter(AutoGenAdapterBase):
    """Concrete AutoGen adapter using HTTP transport to AgentMesh A2A Server.

    All communication with the AgentMesh server uses the REST API with
    JSON body encoding.  Only stdlib modules are used: ``urllib.request``
    for HTTP, ``threading`` for thread safety, ``uuid`` for message IDs,
    and ``time`` / ``json`` for serialisation.

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
        self._conversations: Dict[str, Any] = {}  # conversation_id -> metadata

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

        req = urllib.request.Request(url, data=data_bytes, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
                raw = resp.read()
                if raw:
                    return dict(json.loads(raw.decode("utf-8")))
                return {}
        except urllib.error.HTTPError as exc:
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
                "AutoGenAdapter is not connected. Call connect() first."
            )

    def _parse_message_type(self, value: str) -> MessageType:
        """Safely parse a string into a MessageType enum member."""
        try:
            return MessageType(value)
        except ValueError:
            return MessageType.CUSTOM

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

        start = time.monotonic()
        try:
            self._request("GET", "/health", timeout=min(timeout_seconds, 10.0))
        except (ConnectionError, ValueError, OSError) as exc:
            raise ConnectionError(
                f"AgentMesh server at {server_url} is not reachable: {exc}"
            ) from exc

        latency = (time.monotonic() - start) * 1000.0

        try:
            self._request(
                "POST",
                "/connect",
                body={"client": "autogen_adapter", "latency_ms": round(latency, 2)},
                timeout=min(timeout_seconds, 10.0),
            )
        except (ConnectionError, ValueError):
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
            conversations = dict(self._conversations)
            self._conversations.clear()

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
        config: AutoGenAgentConfig,
    ) -> Any:
        """Create an AutoGen ConversableAgent wired with AgentMesh routing.

        The returned agent overrides ``send()`` and ``receive()`` to route
        messages through AgentMesh instead of direct in-process calls.

        Attempts to import ``autogen.ConversableAgent``.  If the package is
        not available a ``_ConversableAgentProxy`` is returned instead.

        Args:
            config: Full agent configuration.

        Returns:
            An AutoGen agent-compatible instance with AgentMesh routing.

        Raises:
            RuntimeError: If not connected.
        """
        self._ensure_connected()

        agent_def = config.agent_def

        agent = self._try_create_autogen_agent(
            name=agent_def.name,
            system_message=agent_def.system_message,
            description=agent_def.description,
            max_consecutive_auto_reply=agent_def.max_consecutive_auto_reply,
            human_input_mode=agent_def.human_input_mode,
            llm_config=config.llm_config,
            code_execution_config=config.code_execution_config,
        )

        self.register_agent(agent_def.name, agent)
        return agent

    def _try_create_autogen_agent(
        self,
        name: str,
        system_message: str,
        description: str,
        max_consecutive_auto_reply: int,
        human_input_mode: str,
        llm_config: Optional[Dict[str, Any]],
        code_execution_config: Optional[Dict[str, Any]],
    ) -> Any:
        """Attempt to create a real pyautogen agent; return a proxy otherwise."""
        try:
            from autogen import ConversableAgent  # type: ignore[import-untyped]

            return ConversableAgent(
                name=name,
                system_message=system_message,
                human_input_mode=human_input_mode,
                max_consecutive_auto_reply=max_consecutive_auto_reply,
                llm_config=llm_config,
                code_execution_config=code_execution_config,
                description=description,
            )
        except ImportError:
            return _ConversableAgentProxy(
                name=name,
                adapter=self,
                system_message=system_message,
                description=description,
                max_consecutive_auto_reply=max_consecutive_auto_reply,
                human_input_mode=human_input_mode,
                llm_config=llm_config,
                code_execution_config=code_execution_config,
            )

    # ------------------------------------------------------------------
    # Agent registration
    # ------------------------------------------------------------------

    def register_agent(self, agent_id: str, agent: Any) -> None:
        """Register an AutoGen agent with the AgentMesh server.

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
                    "name": getattr(agent, "name", agent_id),
                },
            )
        except (ConnectionError, ValueError) as exc:
            with self._lock:
                self._agents.pop(agent_id, None)
            raise ConnectionError(
                f"Failed to register agent '{agent_id}' with server: {exc}"
            ) from exc

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an AutoGen agent from the AgentMesh server.

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
            pass

    # ------------------------------------------------------------------
    # Message operations
    # ------------------------------------------------------------------

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

        Args:
            sender_id: Sending agent ID.
            recipient_id: Target agent ID.
            content: Message payload.
            message_type: Type of message.
            conversation_id: Optional conversation thread identifier.
            metadata: Optional routing metadata.

        Returns:
            MessageSendResult with delivery status.

        Raises:
            ConnectionError: If the server is unreachable.
        """
        self._ensure_connected()

        message_id: str = uuid.uuid4().hex
        resolved_conversation_id = conversation_id or uuid.uuid4().hex

        request_body: Dict[str, Any] = {
            "message_id": message_id,
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "content": content,
            "message_type": message_type.value,
            "conversation_id": resolved_conversation_id,
        }
        if metadata is not None:
            request_body["metadata"] = metadata

        try:
            response = self._request("POST", "/send", body=request_body)
        except (ConnectionError, ValueError) as exc:
            return MessageSendResult(
                message_id=message_id,
                conversation_id=resolved_conversation_id,
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

        return MessageSendResult(
            message_id=response.get("message_id", message_id),
            conversation_id=response.get("conversation_id", resolved_conversation_id),
            status=parsed_status,
            recipient_agent=recipient_id,
            error_message=response.get("error_message"),
        )

    def receive_message(
        self,
        agent_id: str,
        timeout_seconds: Optional[float] = None,
    ) -> Optional[MessageReceiveResult]:
        """Receive the next pending message for an AutoGen agent (blocking).

        Blocks until a message is available or the timeout expires.

        Args:
            agent_id: Receiving agent ID.
            timeout_seconds: Maximum wait time. ``None`` uses default.

        Returns:
            MessageReceiveResult if a message is available, ``None`` on timeout.

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
            error_str = str(exc)
            if "404" in error_str or "408" in error_str:
                return None
            raise ConnectionError(error_str) from exc

        if not response:
            return None

        return self._response_to_message_receive(response)

    def poll_messages(
        self,
        agent_id: str,
        max_count: int = 10,
        conversation_id: Optional[str] = None,
    ) -> List[MessageReceiveResult]:
        """Poll for pending messages for an AutoGen agent (non-blocking).

        Args:
            agent_id: Receiving agent ID.
            max_count: Maximum number of messages to retrieve.
            conversation_id: Optional filter to a specific conversation.

        Returns:
            List of received messages (may be empty).
        """
        self._ensure_connected()

        query_params: Dict[str, Any] = {
            "agent_id": agent_id,
            "max_count": max_count,
        }
        if conversation_id is not None:
            query_params["conversation_id"] = conversation_id

        query_string = urllib.parse.urlencode(query_params)

        try:
            response = self._request(
                "POST",
                f"/poll?{query_string}",
                body=None,
                timeout=self._default_timeout,
            )
        except (ConnectionError, ValueError, OSError):
            return []

        messages_raw = (
            response.get("messages", response.get("cards", []))
            if isinstance(response, dict)
            else []
        )
        if not isinstance(messages_raw, list):
            return []

        results: List[MessageReceiveResult] = []
        for raw in messages_raw[:max_count]:
            if isinstance(raw, dict):
                parsed = self._response_to_message_receive(raw)
                if parsed is not None:
                    results.append(parsed)
        return results

    def _response_to_message_receive(
        self,
        response: Dict[str, Any],
    ) -> Optional[MessageReceiveResult]:
        """Convert a server response dict into a MessageReceiveResult."""
        if not response:
            return None

        msg_type_str = response.get(
            "message_type", response.get("card_type", MessageType.TEXT.value)
        )
        if not isinstance(msg_type_str, str):
            msg_type_str = MessageType.TEXT.value

        content_raw = response.get("content", response.get("payload", {}))
        if not isinstance(content_raw, dict):
            content_raw = {"text": str(content_raw)}

        return MessageReceiveResult(
            message_id=str(
                response.get("message_id", response.get("card_id", ""))
            ),
            conversation_id=str(response.get("conversation_id", "")),
            sender_agent=str(
                response.get("sender_id", response.get("sender_agent", ""))
            ),
            message_type=self._parse_message_type(msg_type_str),
            content=content_raw,
            metadata=(
                dict(response["metadata"])
                if response.get("metadata") is not None
                else None
            ),
        )

    # ------------------------------------------------------------------
    # GroupChat management
    # ------------------------------------------------------------------

    def create_group_chat(
        self,
        config: GroupChatConfig,
    ) -> Any:
        """Create an AutoGen GroupChat managed through AgentMesh.

        Attempts to import ``autogen.GroupChat``.  If the package is not
        available, returns a dict-based representation.

        Args:
            config: GroupChat configuration.

        Returns:
            A GroupChat-compatible object.

        Raises:
            RuntimeError: If not connected.
        """
        self._ensure_connected()

        try:
            from autogen import GroupChat  # type: ignore[import-untyped]

            return GroupChat(
                agents=None,
                messages=[],
                max_round=config.max_round,
                admin_name=config.admin_name,
                speaker_selection_method=config.speaker_selection_method,
            )
        except ImportError:
            return {
                "name": config.name,
                "agent_ids": list(config.agent_ids),
                "max_round": config.max_round,
                "admin_name": config.admin_name,
                "speaker_selection_method": config.speaker_selection_method,
            }

    def start_conversation(
        self,
        group_chat_id: str,
        initiator_id: str,
        message: str,
    ) -> str:
        """Start a new conversation in a GroupChat via AgentMesh.

        Args:
            group_chat_id: Identifier of the GroupChat.
            initiator_id: Agent that initiates the conversation.
            message: The initial message to start the discussion.

        Returns:
            Conversation identifier for tracking.

        Raises:
            ConnectionError: If the server is unreachable.
        """
        self._ensure_connected()

        conversation_id: str = uuid.uuid4().hex

        body: Dict[str, Any] = {
            "group_chat_id": group_chat_id,
            "initiator_id": initiator_id,
            "message": message,
            "conversation_id": conversation_id,
        }

        try:
            response = self._request(
                "POST", "/conversations/start", body=body
            )
            server_conversation_id = str(
                response.get("conversation_id", conversation_id)
            )
        except (ConnectionError, ValueError) as exc:
            raise ConnectionError(
                f"Failed to start conversation in group "
                f"'{group_chat_id}': {exc}"
            ) from exc

        with self._lock:
            self._conversations[server_conversation_id] = {
                "group_chat_id": group_chat_id,
                "initiator_id": initiator_id,
                "phase": ConversationPhase.ACTIVE.value,
            }

        return server_conversation_id

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
        self._ensure_connected()

        try:
            response = self._request(
                "POST",
                "/conversations/status",
                body={"conversation_id": conversation_id},
            )
        except (ConnectionError, ValueError):
            with self._lock:
                meta = self._conversations.get(conversation_id, {})
                phase_str = meta.get(
                    "phase", ConversationPhase.ACTIVE.value
                )
            try:
                return ConversationPhase(phase_str)
            except ValueError:
                return ConversationPhase.ACTIVE

        phase_str = response.get(
            "phase", response.get("status", ConversationPhase.ACTIVE.value)
        )
        try:
            return ConversationPhase(phase_str)
        except ValueError:
            return ConversationPhase.ACTIVE

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

        Raises:
            ConnectionError: If the server is unreachable.
        """
        self._ensure_connected()

        body: Dict[str, Any] = {
            "conversation_id": conversation_id,
            "max_messages": max_messages,
        }
        if since_message_id is not None:
            body["since_message_id"] = since_message_id

        try:
            response = self._request(
                "POST", "/conversations/history", body=body
            )
        except (ConnectionError, ValueError) as exc:
            raise ConnectionError(
                f"Failed to get history for conversation "
                f"'{conversation_id}': {exc}"
            ) from exc

        messages_raw = (
            response.get("messages", [])
            if isinstance(response, dict)
            else []
        )
        if not isinstance(messages_raw, list):
            return []

        results: List[MessageReceiveResult] = []
        for raw in messages_raw[:max_messages]:
            if isinstance(raw, dict):
                parsed = self._response_to_message_receive(raw)
                if parsed is not None:
                    results.append(parsed)
        return results

    # ------------------------------------------------------------------
    # Framework bridging
    # ------------------------------------------------------------------

    def bridge_to_crewai(
        self,
        autogen_agent_id: str,
        crewai_agent_id: str,
    ) -> None:
        """Create a direct communication bridge between AutoGen and CrewAI.

        After bridging, messages sent from the AutoGen agent to the
        CrewAI agent are automatically translated between message formats.

        Args:
            autogen_agent_id: Identifier of the AutoGen agent.
            crewai_agent_id: Identifier of the CrewAI agent.

        Raises:
            ConnectionError: If the server is unreachable.
        """
        self._ensure_connected()

        try:
            self._request(
                "POST",
                "/bridge/crewai",
                body={
                    "source_agent_id": autogen_agent_id,
                    "target_agent_id": crewai_agent_id,
                    "source_framework": "autogen",
                    "target_framework": "crewai",
                },
            )
        except (ConnectionError, ValueError) as exc:
            raise ConnectionError(
                f"Failed to bridge AutoGen agent '{autogen_agent_id}' "
                f"to CrewAI agent '{crewai_agent_id}': {exc}"
            ) from exc

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

        Raises:
            ConnectionError: If the server is unreachable.
        """
        self._ensure_connected()

        body: Dict[str, Any] = {
            "source_agent_id": autogen_agent_id,
            "target_agent_id": custom_agent_id,
            "source_framework": "autogen",
            "target_framework": "custom",
        }
        if format_adapter is not None:
            body["format_adapter"] = str(format_adapter)

        try:
            self._request("POST", "/bridge/custom", body=body)
        except (ConnectionError, ValueError) as exc:
            raise ConnectionError(
                f"Failed to bridge AutoGen agent '{autogen_agent_id}' "
                f"to custom agent '{custom_agent_id}': {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Health & status
    # ------------------------------------------------------------------

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
                "active_conversations": len(self._conversations),
            }
        except (ConnectionError, ValueError, OSError) as exc:
            with self._lock:
                local_count = len(self._agents)
            return {
                "status": "down",
                "server_url": self._server_url,
                "latency_ms": -1.0,
                "registered_agents": local_count,
                "active_conversations": 0,
                "error": str(exc),
            }

