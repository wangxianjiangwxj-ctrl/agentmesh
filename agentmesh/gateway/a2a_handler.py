"""Gateway A2A integration layer — translates REST requests into A2A messages.

Each method in ``GatewayA2AHandler`` corresponds to a REST endpoint and
uses ``bridge.send(agent_id, action, payload)`` to dispatch A2A messages
to the appropriate agent wrapper.

Usage::

    from agentmesh.gateway.a2a_handler import GatewayA2AHandler

    handler = GatewayA2AHandler(bridge)
    result = await handler.register_agent(name="alice")
"""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from agentmesh.agents.agent_registry import A2AMessage

if TYPE_CHECKING:
    from agentmesh.agents.bridge import AgentMeshBridge


class GatewayA2AHandler:
    """Translates REST HTTP requests into A2A messages.

    Each method corresponds to a REST endpoint and uses
    ``bridge.send(agent_id, action, payload)`` to dispatch.
    """

    def __init__(self, bridge: AgentMeshBridge):  # noqa: ANN001
        """Initialize the handler with an AgentMeshBridge instance.

        Args:
            bridge: An initialized AgentMeshBridge with all services.
        """
        self._bridge = bridge

    # ------------------------------------------------------------------
    # Identity Agent
    # ------------------------------------------------------------------

    async def register_agent(
        self,
        name: str,
        auth_token: str = "",
        metadata: Optional[dict] = None,
    ) -> dict:
        """POST /agents/register → identity-service/register_agent"""
        return await self._bridge.send(
            "identity-service",
            "register_agent",
            {
                "name": name,
                "auth_token": auth_token,
                "metadata": metadata or {},
            },
        )

    async def get_agent(self, agent_id: str) -> dict:
        """GET /agents/{agent_id} → identity-service/get_agent"""
        return await self._bridge.send(
            "identity-service",
            "get_agent",
            {"agent_id": agent_id},
        )

    async def list_agents(self) -> dict:
        """GET /agents → identity-service/list_agents"""
        return await self._bridge.send(
            "identity-service",
            "list_agents",
            {},
        )

    # ------------------------------------------------------------------
    # Task Market Agent
    # ------------------------------------------------------------------

    async def create_task(
        self,
        title: str,
        description: str,
        escrow_amount: int,
        publisher_share: float,
        executor_share: float,
        publisher_id: str,
    ) -> dict:
        """POST /tasks → task-market/create_task"""
        return await self._bridge.send(
            "task-market",
            "create_task",
            {
                "title": title,
                "description": description,
                "escrow_amount": escrow_amount,
                "publisher_share": publisher_share,
                "executor_share": executor_share,
                "publisher_id": publisher_id,
                "signature": "gateway-a2a-sig",
            },
        )

    async def list_tasks(
        self,
        status: Optional[str] = None,
        publisher_id: Optional[str] = None,
    ) -> dict:
        """GET /tasks → task-market/list_tasks"""
        return await self._bridge.send(
            "task-market",
            "list_tasks",
            {
                "status": status or "",
                "publisher_id": publisher_id or "",
            },
        )

    async def get_task(self, task_id: str) -> dict:
        """GET /tasks/{task_id} → task-market/get_task"""
        return await self._bridge.send(
            "task-market",
            "get_task",
            {"task_id": task_id},
        )

    async def assign_task(
        self, task_id: str, executor_id: str
    ) -> dict:
        """POST /tasks/{task_id}/assign → task-market/assign_task"""
        return await self._bridge.send(
            "task-market",
            "assign_task",
            {
                "task_id": task_id,
                "executor_id": executor_id,
                "signature": "gateway-a2a-sig",
            },
        )

    async def deliver_task(
        self, task_id: str, delivery_url: str, executor_id: str
    ) -> dict:
        """POST /tasks/{task_id}/deliver → task-market/deliver_task"""
        return await self._bridge.send(
            "task-market",
            "deliver_task",
            {
                "task_id": task_id,
                "delivery_url": delivery_url,
                "executor_id": executor_id,
                "signature": "gateway-a2a-sig",
            },
        )

    async def verify_task(
        self, task_id: str, publisher_id: str, approved: bool
    ) -> dict:
        """POST /tasks/{task_id}/verify → task-market/verify_task"""
        return await self._bridge.send(
            "task-market",
            "verify_task",
            {
                "task_id": task_id,
                "publisher_id": publisher_id,
                "approved": approved,
                "signature": "gateway-a2a-sig",
            },
        )

    async def settle_task(
        self, task_id: str, publisher_id: str
    ) -> dict:
        """POST /tasks/{task_id}/settle → task-market/settle_task"""
        return await self._bridge.send(
            "task-market",
            "settle_task",
            {
                "task_id": task_id,
                "publisher_id": publisher_id,
                "signature": "gateway-a2a-sig",
            },
        )

    async def cancel_task(
        self, task_id: str, agent_id: str
    ) -> dict:
        """POST /tasks/{task_id}/cancel → task-market/cancel_task"""
        return await self._bridge.send(
            "task-market",
            "cancel_task",
            {
                "task_id": task_id,
                "agent_id": agent_id,
                "signature": "gateway-a2a-sig",
            },
        )

    # ------------------------------------------------------------------
    # Escrow Agent
    # ------------------------------------------------------------------

    async def hold_escrow(
        self, agent_id: str, task_id: str, amount: int
    ) -> dict:
        """POST /escrow/hold → escrow-service/hold"""
        return await self._bridge.send(
            "escrow-service",
            "hold",
            {
                "agent_id": agent_id,
                "task_id": task_id,
                "amount": amount,
            },
        )

    async def release_escrow(
        self,
        task_id: str,
        publisher_id: str,
        executor_id: str,
        escrow_amount: int,
        publisher_share: float = 0.5,
        executor_share: float = 0.5,
    ) -> dict:
        """POST /escrow/release → escrow-service/release"""
        return await self._bridge.send(
            "escrow-service",
            "release",
            {
                "task_id": task_id,
                "publisher_id": publisher_id,
                "executor_id": executor_id,
                "escrow_amount": escrow_amount,
                "publisher_share": publisher_share,
                "executor_share": executor_share,
            },
        )

    async def refund_escrow(
        self,
        task_id: str,
        publisher_id: str,
        escrow_amount: int,
        reason: str = "cancelled",
    ) -> dict:
        """POST /escrow/refund → escrow-service/refund"""
        return await self._bridge.send(
            "escrow-service",
            "refund",
            {
                "task_id": task_id,
                "publisher_id": publisher_id,
                "escrow_amount": escrow_amount,
                "reason": reason,
            },
        )

    async def deposit(
        self, agent_id: str, amount: int
    ) -> dict:
        """POST /escrow/deposit → escrow-service/deposit"""
        return await self._bridge.send(
            "escrow-service",
            "deposit",
            {"agent_id": agent_id, "amount": amount},
        )

    async def get_balance(self, agent_id: str) -> dict:
        """GET /escrow/balance/{agent_id} → escrow-service/get_balance"""
        return await self._bridge.send(
            "escrow-service",
            "get_balance",
            {"agent_id": agent_id},
        )

    # ------------------------------------------------------------------
    # Evidence Chain Agent
    # ------------------------------------------------------------------

    async def record_evidence(
        self,
        task_id: str,
        action: str,
        actor_id: str,
        payload: Optional[dict] = None,
        secondary_actor_id: Optional[str] = None,
    ) -> dict:
        """POST /evidence/record → evidence-chain/record_evidence"""
        return await self._bridge.send(
            "evidence-chain",
            "record_evidence",
            {
                "task_id": task_id,
                "action": action,
                "actor_id": actor_id,
                "payload": payload or {},
                "secondary_actor_id": secondary_actor_id or "",
            },
        )

    async def get_evidence_chain(self, task_id: str) -> dict:
        """GET /evidence/{task_id} → evidence-chain/get_evidence_chain"""
        return await self._bridge.send(
            "evidence-chain",
            "get_evidence_chain",
            {"task_id": task_id},
        )

    async def verify_evidence_chain(self, task_id: str) -> dict:
        """GET /evidence/{task_id}/verify → evidence-chain/verify_chain"""
        return await self._bridge.send(
            "evidence-chain",
            "verify_chain",
            {"task_id": task_id},
        )

    # ------------------------------------------------------------------
    # Reputation Agent
    # ------------------------------------------------------------------

    async def submit_review(
        self,
        task_id: str,
        rater_id: str,
        target_id: str,
        score: int,
        comment: str = "",
    ) -> dict:
        """POST /reviews/submit → reputation-service/submit_review"""
        return await self._bridge.send(
            "reputation-service",
            "submit_review",
            {
                "task_id": task_id,
                "rater_id": rater_id,
                "target_id": target_id,
                "score": score,
                "comment": comment,
            },
        )

    async def get_reputation(self, agent_id: str) -> dict:
        """GET /reputation/{agent_id} → reputation-service/get_reputation"""
        return await self._bridge.send(
            "reputation-service",
            "get_reputation",
            {"agent_id": agent_id},
        )

    async def list_top_agents(self, limit: int = 10) -> dict:
        """GET /reputation/top → reputation-service/list_top_agents"""
        return await self._bridge.send(
            "reputation-service",
            "list_top_agents",
            {"limit": limit},
        )
