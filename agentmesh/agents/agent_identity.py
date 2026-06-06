"""
AgentMesh IdentityAgent — A2A wrapper for IdentityService

Exposes DID-based agent registration and lookup as an A2A peer agent.
"""
from __future__ import annotations

import uuid
import time
from typing import Optional

from agentmesh.identity import IdentityService
from agentmesh.agents.agent_registry import A2AMessage, AgentInfo, AgentRegistry


class IdentityAgent:
    """A2A Agent wrapper for IdentityService.

    Supported actions::

        register_agent  — Register a new agent (generates keypair, registers in both
                          IdentityService and AgentRegistry).
        get_agent       — Look up agent details by agent_id.
        list_agents     — List all registered agents.
        get_agent_by_did — Look up by DID string.
    """

    def __init__(self, identity_service: IdentityService, registry: AgentRegistry):
        """Initialize the IdentityAgent wrapper.

        Args:
            identity_service: IdentityService instance for registration.
            registry: AgentRegistry for A2A agent discovery.
        """
        self._identity = identity_service
        self._registry = registry
        self._agent_id = "identity-service"
        self._capabilities = ["identity", "registration", "did"]

    @property
    def agent_id(self) -> str:
        """Return the unique identifier for this agent."""
        return self._agent_id

    @property
    def capabilities(self) -> list[str]:
        """Return the list of capability strings for this agent."""
        return list(self._capabilities)

    async def handle_message(self, msg: A2AMessage) -> A2AMessage:
        """Route an incoming A2A message to the appropriate handler."""
        action = msg.action
        payload = msg.payload

        try:
            if action == "register_agent":
                return await self._handle_register(msg)
            elif action == "get_agent":
                return await self._handle_get_agent(msg)
            elif action == "list_agents":
                return await self._handle_list_agents(msg)
            elif action == "get_agent_by_did":
                return await self._handle_get_by_did(msg)
            else:
                return A2AMessage.error(
                    msg, f"Unknown action: {action}", code="UNKNOWN_ACTION"
                )
        except Exception as exc:
            return A2AMessage.error(msg, str(exc), code="HANDLER_ERROR")

    # -- action handlers -------------------------------------------------

    async def _handle_register(self, msg: A2AMessage) -> A2AMessage:
        """Register a new agent.

        Payload::
            {"name": str, "auth_token": str (optional), "metadata": dict (optional)}
        """
        payload = msg.payload
        name = payload["name"]
        auth_token = payload.get("auth_token", "")
        metadata = payload.get("metadata")

        result = self._identity.register(
            name=name,
            auth_token=auth_token,
            metadata=metadata,
        )

        # Also register in the A2A AgentRegistry
        agent_info = AgentInfo(
            agent_id=result["agent_id"],
            name=name,
            capabilities=["default"],
            endpoints={"a2a": "memory://local"},
            did=result.get("did"),
            public_key=result.get("public_key"),
            metadata={"did": result.get("did", "")},
        )
        self._registry.register(agent_info)

        return A2AMessage.reply(msg, {
            "agent_id": result["agent_id"],
            "did": result.get("did"),
            "public_key": result.get("public_key"),
            "name": name,
        })

    async def _handle_get_agent(self, msg: A2AMessage) -> A2AMessage:
        """Look up an agent by ID.

        Payload:: ``{"agent_id": str}``
        """
        agent_id = msg.payload["agent_id"]
        agent = self._identity.get_agent(agent_id)
        if agent is None:
            return A2AMessage.error(msg, f"Agent not found: {agent_id}", code="NOT_FOUND")

        return A2AMessage.reply(msg, {
            "agent_id": agent["id"],
            "did": agent.get("did"),
            "name": agent.get("name"),
            "public_key": agent.get("public_key"),
            "auth_token": agent.get("auth_token", ""),
            "reputation": agent.get("reputation", 0.0),
            "task_count": agent.get("task_count", 0),
        })

    async def _handle_list_agents(self, msg: A2AMessage) -> A2AMessage:
        """List all registered agents.

        Payload: ``{}`` (empty)
        """
        agents = self._identity.fetch_all_registrations()
        return A2AMessage.reply(msg, {
            "agents": agents,
            "total": len(agents),
        })

    async def _handle_get_by_did(self, msg: A2AMessage) -> A2AMessage:
        """Look up an agent by DID string.

        Payload:: ``{"did": str}``
        """
        did = msg.payload["did"]
        agent = self._identity.get_agent_by_did(did)
        if agent is None:
            return A2AMessage.error(msg, f"Agent not found by DID: {did}", code="NOT_FOUND")

        return A2AMessage.reply(msg, {
            "agent_id": agent["id"],
            "did": agent.get("did"),
            "name": agent.get("name"),
            "public_key": agent.get("public_key"),
        })
