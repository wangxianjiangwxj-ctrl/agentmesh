"""
AgentMesh A2A Agent Registry — Phase 20 Direction C

Maintains agent_id -> AgentInfo mapping for peer-to-peer A2A discovery.
Compatible with the existing IdentityService DID mechanism.
"""
from __future__ import annotations

import uuid
import time
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# A2A Message Protocol
# ---------------------------------------------------------------------------


@dataclass
class A2AMessage:
    """Wire format for agent-to-agent communication.

    Every agent wrapper exposes ``handle_message(msg: A2AMessage) -> A2AMessage``.
    The source of the response is the original target, and vice versa.

    Attributes:
        source_agent_id: ID of the sending agent.
        target_agent_id: ID of the receiving agent.
        action: Action name (e.g. "register_agent", "create_task").
        payload: Method arguments as a JSON-serializable dict.
        message_id: Unique identifier (hex UUID).
        timestamp: Unix timestamp of message creation.
        signature: Optional Ed25519 signature (reserved for future use).
    """
    source_agent_id: str
    target_agent_id: str
    action: str
    payload: dict
    message_id: str
    timestamp: float
    signature: Optional[str] = None

    @classmethod
    def reply(cls, request: A2AMessage, payload: dict,
              action: str = "ok") -> A2AMessage:
        """Create a reply message with source and target swapped.

        Args:
            request: The original incoming message.
            payload: Response payload.
            action: Response action name. Defaults to "ok".

        Returns:
            New A2AMessage with reversed source/target.
        """
        return cls(
            source_agent_id=request.target_agent_id,
            target_agent_id=request.source_agent_id,
            action=action,
            payload=payload,
            message_id=uuid.uuid4().hex,
            timestamp=time.time(),
        )

    @classmethod
    def error(cls, request: A2AMessage, message: str,
              code: str = "ERROR") -> A2AMessage:
        """Create an error reply message.

        Args:
            request: The original incoming message.
            message: Human-readable error description.
            code: Machine-readable error code. Defaults to "ERROR".

        Returns:
            New A2AMessage with action="error" and error details in payload.
        """
        return cls.reply(request, {"error": message, "code": code}, action="error")


# ---------------------------------------------------------------------------
# Agent Info
# ---------------------------------------------------------------------------


@dataclass
class AgentInfo:
    """Descriptor for a registered A2A agent.

    Attributes:
        agent_id: Unique identifier for the agent.
        name: Human-readable name.
        capabilities: List of capability strings (e.g. ["identity", "registration"]).
        endpoints: Connection endpoints dict (e.g. ``{"a2a": "memory://local"}``).
        did: Optional DID string like ``did:agentmesh:key:...``.
        public_key: Optional base64-encoded Ed25519 public key.
        metadata: Extensible key-value storage.
    """
    agent_id: str
    name: str
    capabilities: list[str]
    endpoints: dict
    did: Optional[str] = None
    public_key: Optional[str] = None
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent Registry
# ---------------------------------------------------------------------------


class AgentRegistry:
    """Central registry for A2A agent discovery.

    Maintains an in-memory mapping of ``agent_id`` to ``AgentInfo``.
    Supports registration, unregistration, lookup by ID, and discovery
    by capability. Compatible with the DID-based IdentityService.
    """

    def __init__(self):
        """Initialize an empty agent registry."""
        self._agents: dict[str, AgentInfo] = {}

    # -- lifecycle -------------------------------------------------------

    def register(self, info: AgentInfo) -> None:
        """Register or update an agent's info.

        Args:
            info: AgentInfo descriptor to store.
        """
        self._agents[info.agent_id] = info

    def unregister(self, agent_id: str) -> bool:
        """Remove an agent from the registry.

        Args:
            agent_id: UUID of the agent to remove.

        Returns:
            True if the agent was found and removed, False otherwise.
        """
        if agent_id in self._agents:
            del self._agents[agent_id]
            return True
        return False

    # -- queries ---------------------------------------------------------

    def lookup(self, agent_id: str) -> Optional[AgentInfo]:
        """Look up a single agent by ID.

        Args:
            agent_id: UUID of the agent.

        Returns:
            AgentInfo if found, None otherwise.
        """
        return self._agents.get(agent_id)

    def discover(self, capability: Optional[str] = None) -> list[AgentInfo]:
        """Find agents matching an optional capability filter.

        Args:
            capability: Capability string to filter by. If None, returns all agents.

        Returns:
            List of matching AgentInfo objects.
        """
        if capability is None:
            return list(self._agents.values())

        matched = []
        for info in self._agents.values():
            if capability in info.capabilities:
                matched.append(info)
        return matched

    # -- bulk ------------------------------------------------------------

    def list_all(self) -> list[AgentInfo]:
        """Return all registered agents.

        Returns:
            List of all AgentInfo objects currently registered.
        """
        return list(self._agents.values())

    def count(self) -> int:
        """Return the number of registered agents.

        Returns:
            Integer count of registered agents.
        """
        return len(self._agents)

    def clear(self) -> None:
        """Remove all agents from the registry."""
        self._agents.clear()
