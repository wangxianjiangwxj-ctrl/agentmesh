"""
AgentMesh Platform — Module 5: Reviews & Reputation (sync, SQLite-backed)

Matches db_schema.py v2 (reviews + agent_reputation tables).
"""
from __future__ import annotations

import uuid
import json
import time
from typing import Optional
from sqlite3 import Connection

from agentmesh.identity import IdentityService
from agentmesh.evidence_chain import EvidenceChainService

BAYESIAN_PRIOR = 3.0
BAYESIAN_PRIOR_N = 2


class ReviewService:
    """Synchronous review and reputation service for the AgentMesh platform.

    Uses Bayesian averaging to compute reputation scores from 1-5 ratings.
    Handles review submission, duplicate detection, and automatic reputation
    recalculation. Integrates with ``EvidenceChainService`` for audit trail.
    """

    def __init__(
        self,
        db_conn: Connection,
        identity_svc: IdentityService,
        evidence_svc: EvidenceChainService,
    ):
        """Initialize the review service.

        Args:
            db_conn: SQLite connection with reviews/agent_reputation tables.
            identity_svc: IdentityService for agent lookups.
            evidence_svc: EvidenceChainService for audit trail integration.
        """
        self.conn = db_conn
        self.identity = identity_svc
        self.evidence = evidence_svc

    # ── submit ─────────────────────────────────────────────────────────

    def submit_review(
        self,
        task_id: str,
        rater_id: str,
        target_id: str,
        score: int,
        comment: str = "",
    ) -> dict:
        """Submit a review (1-5). No self-review, no duplicates."""
        if rater_id == target_id:
            raise ValueError("Cannot self-review")
        if not (1 <= score <= 5):
            raise ValueError("Score must be 1-5")

        # Check duplicate
        existing = self.conn.execute(
            "SELECT id FROM reviews WHERE task_id = ? AND reviewer_id = ? AND target_id = ?",
            (task_id, rater_id, target_id),
        ).fetchone()
        if existing:
            raise ValueError(f"Duplicate review: {rater_id} already reviewed {target_id} on {task_id}")

        review_id = uuid.uuid4().hex
        with self.conn:
            self.conn.execute(
                """INSERT INTO reviews (id, task_id, reviewer_id, target_id, rating, comment, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
                (review_id, task_id, rater_id, target_id, score, comment),
            )
            self._recompute_reputation(target_id)

        return {
            "id": review_id,
            "task_id": task_id,
            "rater_id": rater_id,
            "target_id": target_id,
            "score": score,
            "comment": comment,
        }

    # ── queries ────────────────────────────────────────────────────────

    def get_reviews_for_target(self, target_id: str, limit: int = 50) -> list[dict]:
        """Fetch reviews received by a target agent, newest first.

        Args:
            target_id: UUID of the agent being reviewed.
            limit: Maximum number of reviews to return. Defaults to 50.

        Returns:
            List of review dicts sorted by created_at descending.
        """
        rows = self.conn.execute(
            "SELECT * FROM reviews WHERE target_id = ? ORDER BY created_at DESC LIMIT ?",
            (target_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_reviews_for_task(self, task_id: str) -> list[dict]:
        """Fetch all reviews for a specific task.

        Args:
            task_id: UUID of the task.

        Returns:
            List of review dicts sorted by created_at ascending.
        """
        rows = self.conn.execute(
            "SELECT * FROM reviews WHERE task_id = ? ORDER BY created_at ASC",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_reputation(self, agent_id: str) -> dict:
        """Get an agent's Bayesian reputation score.

        Queries the cached ``agent_reputation`` table. If no entry
        exists, returns a fallback with the Bayesian prior.

        Args:
            agent_id: UUID of the agent.

        Returns:
            Dict with agent_id, avg_rating, total_reviews, as_publisher, as_executor.
        """
        row = self.conn.execute(
            "SELECT * FROM agent_reputation WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        if row:
            return dict(row)

        # Fallback: compute on the fly
        return {
            "agent_id": agent_id,
            "avg_rating": BAYESIAN_PRIOR,
            "total_reviews": 0,
            "as_publisher": 0,
            "as_executor": 0,
        }

    def list_top_agents(self, limit: int = 10) -> list[dict]:
        """List the highest-rated agents by Bayesian average.

        Args:
            limit: Maximum number of agents to return. Defaults to 10.

        Returns:
            List of agent_reputation dicts sorted by avg_rating descending.
        """
        rows = self.conn.execute(
            """SELECT * FROM agent_reputation
               ORDER BY avg_rating DESC, total_reviews DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── lifecycle ──────────────────────────────────────────────────────

    def on_task_settled(self, task_id: str, publisher_id: str, executor_id: str) -> dict:
        """Update task stats when a task is settled.

        Increments the ``as_publisher`` or ``as_executor`` counter
        for each involved agent. Opens the review window for feedback.

        Args:
            task_id: UUID of the settled task.
            publisher_id: UUID of the publisher.
            executor_id: UUID of the executor.

        Returns:
            Dict with task_id and review_window_open flag.
        """
        with self.conn:
            for agent_id in (publisher_id, executor_id):
                self.conn.execute(
                    """INSERT INTO agent_reputation (agent_id, as_publisher, as_executor, updated_at)
                       VALUES (?, ?, ?, datetime('now'))
                       ON CONFLICT(agent_id) DO UPDATE SET
                           as_publisher = CASE WHEN ? = ? THEN as_publisher + 1 ELSE as_publisher END,
                           as_executor = CASE WHEN ? = ? THEN as_executor + 1 ELSE as_executor END,
                           updated_at = datetime('now')""",
                    (agent_id,
                     1 if agent_id == publisher_id else 0,
                     1 if agent_id == executor_id else 0,
                     agent_id, publisher_id,
                     agent_id, executor_id),
                )
        return {"task_id": task_id, "review_window_open": True}

    # ── internals ──────────────────────────────────────────────────────

    def _recompute_reputation(self, agent_id: str) -> None:
        """Recompute Bayesian average reputation score for an agent.

        Uses all reviews targeting the agent, blended with a prior
        (``BAYESIAN_PRIOR``) to avoid extreme scores for agents
        with few reviews.

        Args:
            agent_id: UUID of the agent to update.
        """
        rows = self.conn.execute(
            "SELECT rating FROM reviews WHERE target_id = ?",
            (agent_id,),
        ).fetchall()
        ratings = [r["rating"] for r in rows]
        n = len(ratings)
        if n == 0:
            return

        avg = (sum(ratings) + BAYESIAN_PRIOR * BAYESIAN_PRIOR_N) / (n + BAYESIAN_PRIOR_N)

        self.conn.execute(
            """INSERT INTO agent_reputation (agent_id, avg_rating, total_reviews, updated_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(agent_id) DO UPDATE SET
                   avg_rating = ?,
                   total_reviews = ?,
                   updated_at = datetime('now')""",
            (agent_id, avg, n, avg, n),
        )
