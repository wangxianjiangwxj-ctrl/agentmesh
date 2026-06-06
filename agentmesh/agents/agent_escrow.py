"""
AgentMesh EscrowAgent — A2A wrapper for EscrowService

Exposes escrow operations (deposit, hold, release, refund, balance query)
as an A2A peer agent.
"""
from __future__ import annotations

import uuid
import time
from typing import Optional

from agentmesh.escrow import EscrowService, EscrowError
from agentmesh.agents.agent_registry import A2AMessage, AgentInfo, AgentRegistry


class EscrowAgent:
    """A2A Agent wrapper for EscrowService (points-based escrow).

    Supported actions::

        hold         — Lock points when a task is published
        release      — Release held points to executor (on settlement)
        refund       — Return held points to publisher (on cancel/reject)
        deposit      — Add points to an agent's balance
        get_balance  — Query available + frozen balance
        get_transactions — Query transaction history for a task or agent
        auto_release — Process T+7 dispute window auto-release
    """

    def __init__(self, escrow: EscrowService, registry: AgentRegistry):
        """Initialize the EscrowAgent wrapper.

        Args:
            escrow: EscrowService instance for points management.
            registry: AgentRegistry for A2A agent discovery.
        """
        self._escrow = escrow
        self._registry = registry
        self._agent_id = "escrow-service"
        self._capabilities = ["escrow", "settlement", "points"]

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
            if action == "hold":
                return await self._handle_hold(msg)
            elif action == "release":
                return await self._handle_release(msg)
            elif action == "refund":
                return await self._handle_refund(msg)
            elif action == "deposit":
                return await self._handle_deposit(msg)
            elif action == "get_balance":
                return await self._handle_get_balance(msg)
            elif action == "get_transactions":
                return await self._handle_get_transactions(msg)
            elif action == "auto_release":
                return await self._handle_auto_release(msg)
            else:
                return A2AMessage.error(
                    msg, f"Unknown action: {action}", code="UNKNOWN_ACTION"
                )
        except (EscrowError, ValueError, PermissionError) as exc:
            return A2AMessage.error(msg, str(exc), code="ESCROW_ERROR")
        except Exception as exc:
            return A2AMessage.error(msg, str(exc), code="HANDLER_ERROR")

    # -- action handlers -------------------------------------------------

    async def _handle_hold(self, msg: A2AMessage) -> A2AMessage:
        """Lock points when a task is published.

        Payload::
            {"agent_id": str, "task_id": str, "amount": int}
        """
        p = msg.payload
        self._escrow.ensure_account(p["agent_id"])
        result = self._escrow.hold(
            agent_id=p["agent_id"],
            task_id=p["task_id"],
            amount=p["amount"],
        )
        return A2AMessage.reply(msg, {
            "balance": result.get("balance"),
            "frozen": result.get("frozen"),
            "available": result.get("available"),
        })

    async def _handle_release(self, msg: A2AMessage) -> A2AMessage:
        """Release held points to executor on settlement.

        Payload::
            {
                "task_id": str,
                "publisher_id": str,
                "executor_id": str,
                "escrow_amount": int,
                "publisher_share": float,
                "executor_share": float,
                "chain_hash": str (optional)
            }
        """
        p = msg.payload
        result = self._escrow.release(
            task_id=p["task_id"],
            publisher_id=p["publisher_id"],
            executor_id=p["executor_id"],
            escrow_amount=p["escrow_amount"],
            publisher_share=p["publisher_share"],
            executor_share=p["executor_share"],
            chain_hash=p.get("chain_hash"),
        )
        return A2AMessage.reply(msg, result)

    async def _handle_refund(self, msg: A2AMessage) -> A2AMessage:
        """Return held points to publisher (on cancel/reject).

        Payload::
            {
                "task_id": str,
                "publisher_id": str,
                "escrow_amount": int,
                "reason": str (optional),
                "chain_hash": str (optional)
            }
        """
        p = msg.payload
        result = self._escrow.refund(
            task_id=p["task_id"],
            publisher_id=p["publisher_id"],
            escrow_amount=p["escrow_amount"],
            reason=p.get("reason", "cancelled"),
            chain_hash=p.get("chain_hash"),
        )
        return A2AMessage.reply(msg, {
            "balance": result.get("balance"),
            "frozen": result.get("frozen"),
            "available": result.get("available"),
        })

    async def _handle_deposit(self, msg: A2AMessage) -> A2AMessage:
        """Add points to an agent's balance.

        Payload::
            {"agent_id": str, "amount": int}
        """
        p = msg.payload
        result = self._escrow.deposit(
            agent_id=p["agent_id"],
            amount=p["amount"],
        )
        return A2AMessage.reply(msg, {
            "balance": result.get("balance"),
            "frozen": result.get("frozen"),
            "available": result.get("available"),
        })

    async def _handle_get_balance(self, msg: A2AMessage) -> A2AMessage:
        """Query an agent's balance.

        Payload:: ``{"agent_id": str}``
        """
        result = self._escrow.get_balance(msg.payload["agent_id"])
        return A2AMessage.reply(msg, {
            "balance": result.get("balance"),
            "frozen": result.get("frozen"),
            "available": result.get("available"),
        })

    async def _handle_get_transactions(self, msg: A2AMessage) -> A2AMessage:
        """Query transaction history.

        Payload::
            {"task_id": str} or {"agent_id": str, "limit": int (optional)}
        """
        p = msg.payload
        if "task_id" in p:
            txs = self._escrow.get_transactions(p["task_id"])
            return A2AMessage.reply(msg, {
                "transactions": txs,
                "total": len(txs),
            })
        elif "agent_id" in p:
            txs = self._escrow.get_agent_transactions(
                p["agent_id"],
                limit=p.get("limit", 20),
            )
            return A2AMessage.reply(msg, {
                "transactions": txs,
                "total": len(txs),
            })
        else:
            return A2AMessage.error(msg, "Provide task_id or agent_id", code="INVALID_PAYLOAD")

    async def _handle_auto_release(self, msg: A2AMessage) -> A2AMessage:
        """Process T+7 dispute window auto-release.

        Payload:: ``{"task_id": str}``
        """
        result = self._escrow.auto_release(msg.payload["task_id"])
        if result is None:
            return A2AMessage.error(
                msg, "No eligible hold found or dispute window not expired",
                code="NO_ELIGIBLE_HOLD",
            )
        return A2AMessage.reply(msg, result)
