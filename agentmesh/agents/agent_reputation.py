"""
AgentMesh ReputationAgent — A2A wrapper for ReviewService

Exposes review and reputation operations (submit, query, top agents)
as an A2A peer agent.
"""
from __future__ import annotations

import uuid
import time
from typing import Optional

from agentmesh.reputation import ReviewService
from agentmesh.agents.agent_registry import A2AMessage, AgentInfo, AgentRegistry


class ReputationAgent:
    """A2A Agent wrapper for ReviewService (Bayesian reputation).

    Supported actions::

        submit_review    — Submit a 1-5 rating after task settlement
        get_reputation   — Query an agent's Bayesian reputation score
        get_reviews      -- Query all reviews for a target agent or task
        list_top_agents  -- List highest-rated agents
        on_task_settled  -- Notify reputation service of a settled task
    """

    def __init__(self, rep_service: ReviewService, registry: AgentRegistry):
        """Initialize the ReputationAgent wrapper.

        Args:
            rep_service: ReviewService for reputation operations.
            registry: AgentRegistry for A2A agent discovery.
        """
        self._rep = rep_service
        self._registry = registry
        self._agent_id = "reputation-service"
        self._capabilities = ["reputation", "reviews", "ratings"]

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
            if action == "submit_review":
                return await self._handle_submit_review(msg)
            elif action == "get_reputation":
                return await self._handle_get_reputation(msg)
            elif action == "get_reviews":
                return await self._handle_get_reviews(msg)
            elif action == "list_top_agents":
                return await self._handle_list_top_agents(msg)
            elif action == "on_task_settled":
                return await self._handle_on_task_settled(msg)
            else:
                return A2AMessage.error(
                    msg, f"Unknown action: {action}", code="UNKNOWN_ACTION"
                )
        except ValueError as exc:
            return A2AMessage.error(msg, str(exc), code="VALIDATION_ERROR")
        except Exception as exc:
            return A2AMessage.error(msg, str(exc), code="HANDLER_ERROR")

    # -- action handlers -------------------------------------------------

    async def _handle_submit_review(self, msg: A2AMessage) -> A2AMessage:
        """Submit a 1-5 rating after task settlement.

        Payload::
            {
                "task_id": str,
                "rater_id": str,
                "target_id": str,
                "score": int,
                "comment": str (optional)
            }
        """
        p = msg.payload
        result = self._rep.submit_review(
            task_id=p["task_id"],
            rater_id=p["rater_id"],
            target_id=p["target_id"],
            score=p["score"],
            comment=p.get("comment", ""),
        )
        return A2AMessage.reply(msg, {
            "id": result["id"],
            "task_id": result["task_id"],
            "rater_id": result["rater_id"],
            "target_id": result["target_id"],
            "score": result["score"],
        })

    async def _handle_get_reputation(self, msg: A2AMessage) -> A2AMessage:
        """Query an agent's Bayesian reputation.

        Payload:: ``{"agent_id": str}``
        """
        rep = self._rep.get_reputation(msg.payload["agent_id"])
        return A2AMessage.reply(msg, {
            "agent_id": rep.get("agent_id"),
            "avg_rating": rep.get("avg_rating"),
            "total_reviews": rep.get("total_reviews"),
            "as_publisher": rep.get("as_publisher", 0),
            "as_executor": rep.get("as_executor", 0),
        })

    async def _handle_get_reviews(self, msg: A2AMessage) -> A2AMessage:
        """Query reviews for a target agent or task.

        Payload::
            {"target_id": str, "limit": int (optional)}
            {"task_id": str}
        """
        p = msg.payload
        if "target_id" in p:
            reviews = self._rep.get_reviews_for_target(
                p["target_id"],
                limit=p.get("limit", 50),
            )
            return A2AMessage.reply(msg, {
                "reviews": reviews,
                "total": len(reviews),
            })
        elif "task_id" in p:
            reviews = self._rep.get_reviews_for_task(p["task_id"])
            return A2AMessage.reply(msg, {
                "reviews": reviews,
                "total": len(reviews),
            })
        else:
            return A2AMessage.error(msg, "Provide target_id or task_id", code="INVALID_PAYLOAD")

    async def _handle_list_top_agents(self, msg: A2AMessage) -> A2AMessage:
        """List highest-rated agents.

        Payload:: ``{"limit": int (optional)}``
        """
        agents = self._rep.list_top_agents(
            limit=msg.payload.get("limit", 10),
        )
        return A2AMessage.reply(msg, {
            "agents": agents,
            "total": len(agents),
        })

    async def _handle_on_task_settled(self, msg: A2AMessage) -> A2AMessage:
        """Notify reputation service that a task has been settled.

        Payload::
            {"task_id": str, "publisher_id": str, "executor_id": str}
        """
        p = msg.payload
        result = self._rep.on_task_settled(
            task_id=p["task_id"],
            publisher_id=p["publisher_id"],
            executor_id=p["executor_id"],
        )
        return A2AMessage.reply(msg, result)
