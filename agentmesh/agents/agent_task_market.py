"""
AgentMesh TaskMarketAgent — A2A wrapper for TaskMarketService

Exposes task lifecycle operations (create, assign, deliver, verify,
settle, cancel) as an A2A peer agent.
"""
from __future__ import annotations

import uuid
import time
from typing import Optional

from agentmesh.task_market_api import TaskMarketService, CreateTaskRequest, TaskStatus
from agentmesh.agents.agent_registry import A2AMessage, AgentInfo, AgentRegistry


class TaskMarketAgent:
    """A2A Agent wrapper for TaskMarketService.

    Supported actions::

        create_task   — Publish a new task (requires publisher_id + signature in payload)
        list_tasks    — Browse tasks, optional status / publisher_id filter
        get_task      — Get task details by ID
        assign_task   — Accept / assign a task to an executor
        deliver_task  — Submit a delivery URL for an assigned task
        verify_task   — Approve or reject a delivered task
        settle_task   — Settle a verified task (final state)
        cancel_task   — Cancel a task (any cancellable state)
    """

    def __init__(self, task_market: TaskMarketService, registry: AgentRegistry):
        """Initialize the TaskMarketAgent wrapper.

        Args:
            task_market: TaskMarketService instance for task operations.
            registry: AgentRegistry for A2A agent discovery.
        """
        self._service = task_market
        self._registry = registry
        self._agent_id = "task-market"
        self._capabilities = ["task-market", "tasks"]

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
            if action == "create_task":
                return await self._handle_create_task(msg)
            elif action == "list_tasks":
                return await self._handle_list_tasks(msg)
            elif action == "get_task":
                return await self._handle_get_task(msg)
            elif action == "assign_task":
                return await self._handle_assign_task(msg)
            elif action == "deliver_task":
                return await self._handle_deliver_task(msg)
            elif action == "verify_task":
                return await self._handle_verify_task(msg)
            elif action == "settle_task":
                return await self._handle_settle_task(msg)
            elif action == "cancel_task":
                return await self._handle_cancel_task(msg)
            else:
                return A2AMessage.error(
                    msg, f"Unknown action: {action}", code="UNKNOWN_ACTION"
                )
        except Exception as exc:
            return A2AMessage.error(msg, str(exc), code="HANDLER_ERROR")

    # -- action handlers -------------------------------------------------

    async def _handle_create_task(self, msg: A2AMessage) -> A2AMessage:
        """Create a new task.

        Payload::
            {
                "title": str,
                "description": str,
                "escrow_amount": int,
                "publisher_share": float,
                "executor_share": float,
                "publisher_id": str,
                "signature": str
            }
        """
        p = msg.payload
        req = CreateTaskRequest(
            title=p["title"],
            description=p.get("description", ""),
            escrow_amount=p["escrow_amount"],
            publisher_share=p["publisher_share"],
            executor_share=p["executor_share"],
        )
        task = await self._service.create_task(
            req=req,
            publisher_id=p["publisher_id"],
            signature=p.get("signature", ""),
        )
        return A2AMessage.reply(msg, {
            "task_id": task.id,
            "status": task.status.value,
            "title": task.title,
            "publisher_id": task.publisher_id,
        })

    async def _handle_list_tasks(self, msg: A2AMessage) -> A2AMessage:
        """List tasks with optional filters.

        Payload::
            {"status": str (optional), "publisher_id": str (optional)}
        """
        p = msg.payload
        status = None
        if "status" in p and p["status"]:
            status = TaskStatus(p["status"])

        tasks = await self._service.list_tasks(
            status=status,
            publisher_id=p.get("publisher_id"),
        )
        return A2AMessage.reply(msg, {
            "tasks": [
                {
                    "task_id": t.id,
                    "title": t.title,
                    "status": t.status.value,
                    "publisher_id": t.publisher_id,
                    "executor_id": t.executor_id,
                    "escrow_amount": t.escrow_amount,
                    "created_at": t.created_at,
                }
                for t in tasks
            ],
            "total": len(tasks),
        })

    async def _handle_get_task(self, msg: A2AMessage) -> A2AMessage:
        """Get task details by ID.

        Payload:: ``{"task_id": str}``
        """
        task = await self._service.get_task(msg.payload["task_id"])
        if task is None:
            return A2AMessage.error(
                msg, f"Task not found: {msg.payload['task_id']}", code="NOT_FOUND"
            )
        return A2AMessage.reply(msg, {
            "task_id": task.id,
            "title": task.title,
            "description": task.description,
            "status": task.status.value,
            "publisher_id": task.publisher_id,
            "executor_id": task.executor_id,
            "escrow_amount": task.escrow_amount,
            "publisher_share": task.publisher_share,
            "executor_share": task.executor_share,
            "delivery_url": task.delivery_url,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        })

    async def _handle_assign_task(self, msg: A2AMessage) -> A2AMessage:
        """Assign a task to an executor.

        Payload::
            {"task_id": str, "executor_id": str, "signature": str}
        """
        p = msg.payload
        task = await self._service.assign_task(
            task_id=p["task_id"],
            executor_id=p["executor_id"],
            signature=p.get("signature", ""),
        )
        return A2AMessage.reply(msg, {
            "task_id": task.id,
            "status": task.status.value,
            "executor_id": task.executor_id,
        })

    async def _handle_deliver_task(self, msg: A2AMessage) -> A2AMessage:
        """Submit a delivery URL for an assigned task.

        Payload::
            {"task_id": str, "delivery_url": str, "executor_id": str, "signature": str}
        """
        p = msg.payload
        task = await self._service.deliver_task(
            task_id=p["task_id"],
            delivery_url=p["delivery_url"],
            executor_id=p["executor_id"],
            signature=p.get("signature", ""),
        )
        return A2AMessage.reply(msg, {
            "task_id": task.id,
            "status": task.status.value,
            "delivery_url": task.delivery_url,
        })

    async def _handle_verify_task(self, msg: A2AMessage) -> A2AMessage:
        """Approve or reject a delivered task.

        Payload::
            {"task_id": str, "publisher_id": str, "approved": bool, "signature": str}
        """
        p = msg.payload
        task = await self._service.verify_task(
            task_id=p["task_id"],
            publisher_id=p["publisher_id"],
            approved=p["approved"],
            signature=p.get("signature", ""),
        )
        return A2AMessage.reply(msg, {
            "task_id": task.id,
            "status": task.status.value,
            "approved": p["approved"],
        })

    async def _handle_settle_task(self, msg: A2AMessage) -> A2AMessage:
        """Settle a verified task.

        Payload::
            {"task_id": str, "publisher_id": str, "signature": str}
        """
        p = msg.payload
        task = await self._service.settle_task(
            task_id=p["task_id"],
            publisher_id=p["publisher_id"],
            signature=p.get("signature", ""),
        )
        return A2AMessage.reply(msg, {
            "task_id": task.id,
            "status": task.status.value,
        })

    async def _handle_cancel_task(self, msg: A2AMessage) -> A2AMessage:
        """Cancel a task (publisher or executor).

        Payload::
            {"task_id": str, "agent_id": str, "signature": str}
        """
        p = msg.payload
        task = await self._service.cancel_task(
            task_id=p["task_id"],
            agent_id=p["agent_id"],
            signature=p.get("signature", ""),
        )
        return A2AMessage.reply(msg, {
            "task_id": task.id,
            "status": task.status.value,
        })
