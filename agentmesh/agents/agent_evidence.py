"""
AgentMesh EvidenceAgent — A2A wrapper for EvidenceChainService

Exposes tamper-evident evidence chain operations (record, query, verify)
as an A2A peer agent.
"""
from __future__ import annotations

import uuid
import time
from typing import Optional

from agentmesh.evidence_chain import EvidenceChainService
from agentmesh.agents.agent_registry import A2AMessage, AgentInfo, AgentRegistry


class EvidenceAgent:
    """A2A Agent wrapper for EvidenceChainService.

    Supported actions::

        record_evidence  — Append a new hash-chain entry
        get_evidence_chain — Fetch all entries for a task
        verify_chain     — Validate hash-chain integrity for a task
        get_by_actor     — Fetch evidence entries by actor ID
    """

    def __init__(self, evidence: EvidenceChainService, registry: AgentRegistry):
        """Initialize the EvidenceAgent wrapper.

        Args:
            evidence: EvidenceChainService for hash-chain operations.
            registry: AgentRegistry for A2A agent discovery.
        """
        self._evidence = evidence
        self._registry = registry
        self._agent_id = "evidence-chain"
        self._capabilities = ["evidence-chain", "audit", "verification"]

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

        try:
            if action == "record_evidence":
                return await self._handle_record(msg)
            elif action == "get_evidence_chain":
                return await self._handle_get_chain(msg)
            elif action == "verify_chain":
                return await self._handle_verify_chain(msg)
            elif action == "get_by_actor":
                return await self._handle_get_by_actor(msg)
            else:
                return A2AMessage.error(
                    msg, f"Unknown action: {action}", code="UNKNOWN_ACTION"
                )
        except Exception as exc:
            return A2AMessage.error(msg, str(exc), code="HANDLER_ERROR")

    # -- action handlers -------------------------------------------------

    async def _handle_record(self, msg: A2AMessage) -> A2AMessage:
        """Record an evidence chain entry.

        Payload::
            {
                "task_id": str,
                "action": str,
                "actor_id": str,
                "payload": dict,
                "secondary_actor_id": str (optional),
                "extra": dict (optional)
            }
        """
        p = msg.payload
        entry = self._evidence.record(
            task_id=p["task_id"],
            action=p["action"],
            actor_id=p["actor_id"],
            payload=p["payload"],
            secondary_actor_id=p.get("secondary_actor_id"),
            extra=p.get("extra"),
        )
        return A2AMessage.reply(msg, {
            "id": entry.id,
            "task_id": entry.task_id,
            "chain_index": entry.chain_index,
            "chain_hash": entry.chain_hash,
            "chain_prev_hash": entry.chain_prev_hash,
        })

    async def _handle_get_chain(self, msg: A2AMessage) -> A2AMessage:
        """Fetch all evidence entries for a task.

        Payload:: ``{"task_id": str}``
        """
        entries = self._evidence.get_by_task(msg.payload["task_id"])
        return A2AMessage.reply(msg, {
            "entries": entries,
            "total": len(entries),
        })

    async def _handle_verify_chain(self, msg: A2AMessage) -> A2AMessage:
        """Validate hash-chain integrity for a task.

        Payload:: ``{"task_id": str}``
        """
        result = self._evidence.verify_chain(msg.payload["task_id"])
        all_valid = all(entry.get("chain_ok", False) for entry in result)
        return A2AMessage.reply(msg, {
            "entries": result,
            "valid": all_valid,
            "total": len(result),
        })

    async def _handle_get_by_actor(self, msg: A2AMessage) -> A2AMessage:
        """Fetch evidence entries by actor.

        Payload::
            {"actor_id": str, "limit": int (optional)}
        """
        p = msg.payload
        entries = self._evidence.get_by_actor(
            actor_id=p["actor_id"],
            limit=p.get("limit", 50),
        )
        return A2AMessage.reply(msg, {
            "entries": entries,
            "total": len(entries),
        })
