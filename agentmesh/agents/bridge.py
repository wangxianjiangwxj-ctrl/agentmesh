"""
AgentMesh A2A Bridge — Phase 21 Direction A

Unified agent lifecycle manager. Creates all module services (sharing a
single SQLite connection), instantiates the 5 A2A agent wrappers, and
registers them with the AgentRegistry for peer-to-peer message routing.
"""

from __future__ import annotations

import os
import sys
import tempfile
import sqlite3
import uuid
import time
from pathlib import Path
from typing import Optional

from agentmesh.db_schema import SCHEMA_SQL
from agentmesh.identity import IdentityService
from agentmesh.escrow import EscrowService, EscrowError
from agentmesh.evidence_chain import EvidenceChainService
from agentmesh.reputation import ReviewService
from agentmesh.task_market_api import (
    TaskMarketService,
    InMemoryTaskRepository,
    MockSignatureVerifier,
)
from agentmesh.agents.agent_registry import A2AMessage, AgentInfo, AgentRegistry
from agentmesh.agents.agent_identity import IdentityAgent
from agentmesh.agents.agent_task_market import TaskMarketAgent
from agentmesh.agents.agent_escrow import EscrowAgent
from agentmesh.agents.agent_evidence import EvidenceAgent
from agentmesh.agents.agent_reputation import ReputationAgent


class AgentMeshBridge:
    """Unified bridge that initialises all module services and A2A agents.

    Creates all 5 core services (Identity, Escrow, Evidence Chain, Reviews,
    Task Market) sharing a single SQLite connection, instantiates the A2A
    agent wrappers, and registers them in the AgentRegistry.

    Usage::

        bridge = AgentMeshBridge(db_path="agentmesh.db")
        bridge.start()
        # ... send A2A messages ...
        bridge.shutdown()

    All 5 agents are registered in the AgentRegistry on start().
    """

    def __init__(self, db_path: str = ":memory:"):
        """Initialize the bridge with a database path.

        Args:
            db_path: Path to the SQLite database. Defaults to ":memory:".
        """
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._identity_svc: Optional[IdentityService] = None
        self._escrow_svc: Optional[EscrowService] = None
        self._evidence_svc: Optional[EvidenceChainService] = None
        self._review_svc: Optional[ReviewService] = None
        self._task_market_svc: Optional[TaskMarketService] = None
        self._registry: Optional[AgentRegistry] = None
        self._agents: dict[str, object] = {}
        self._started = False

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Initialise DB, services, agents, and register them."""
        if self._started:
            return

        # 1. Shared DB connection
        self._conn = self._init_db(self._db_path)

        # 2. For :memory:, write to a temp file so IdentityService
        #    can open its own connection to the same database.
        if self._db_path == ":memory:":
            f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            f.close()
            self._db_path = f.name
            self._conn.close()
            self._conn = self._init_db(self._db_path)

        # 3. Create module services
        self._identity_svc = IdentityService(self._db_path)
        # Ensure the identity connection is initialised
        _ = self._identity_svc.conn  # triggers table creation

        self._escrow_svc = EscrowService(
            db_conn=self._conn,
            identity_svc=self._identity_svc,
        )
        self._evidence_svc = EvidenceChainService(
            identity_svc=self._identity_svc,
            db_conn=self._conn,
        )
        self._review_svc = ReviewService(
            db_conn=self._conn,
            identity_svc=self._identity_svc,
            evidence_svc=self._evidence_svc,
        )
        self._task_market_svc = TaskMarketService(
            repo=InMemoryTaskRepository(),
            sig_verifier=MockSignatureVerifier(),
        )

        # 4. Agent Registry
        self._registry = AgentRegistry()

        # 5. A2A Agent wrappers
        agents = {
            "identity-service": IdentityAgent(self._identity_svc, self._registry),
            "task-market": TaskMarketAgent(self._task_market_svc, self._registry),
            "escrow-service": EscrowAgent(self._escrow_svc, self._registry),
            "evidence-chain": EvidenceAgent(self._evidence_svc, self._registry),
            "reputation-service": ReputationAgent(self._review_svc, self._registry),
        }
        self._agents = agents

        # 6. Register every agent in the AgentRegistry
        for agent_id, agent_obj in agents.items():
            caps = list(getattr(agent_obj, "capabilities", ["default"]))
            info = AgentInfo(
                agent_id=agent_id,
                name=agent_id.replace("-", " ").title(),
                capabilities=caps,
                endpoints={"a2a": "memory://local"},
            )
            self._registry.register(info)

        self._started = True

    def shutdown(self) -> None:
        """Close all resources: database connections, agent wrappers, and registry.

        Safe to call multiple times. Clears all internal state and
        sets ``_started`` to False.
        """
        if not self._started:
            return

        for svc_name in ("_identity_svc",):
            svc = getattr(self, svc_name, None)
            if svc is not None:
                try:
                    svc.close()
                except Exception:
                    pass

        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass

        self._agents.clear()
        if self._registry is not None:
            self._registry.clear()

        self._started = False

    # -- message routing -------------------------------------------------

    async def handle_message(self, agent_id: str, msg: A2AMessage) -> A2AMessage:
        """Route an A2A message to the target agent and return its response.

        Args:
            agent_id: Target agent identifier.
            msg: The A2AMessage to deliver.

        Returns:
            Response A2AMessage from the target agent, or an error message
            if the agent is not found or the bridge is not started.
        """
        if not self._started:
            return A2AMessage.error(msg, "Bridge not started", code="BRIDGE_NOT_STARTED")

        agent = self._agents.get(agent_id)
        if agent is None:
            return A2AMessage.error(
                msg, f"Agent not found: {agent_id}", code="AGENT_NOT_FOUND"
            )

        # All agent wrappers expose async handle_message
        return await agent.handle_message(msg)

    async def send(self, agent_id: str, action: str,
                   payload: dict) -> dict:
        """Convenience method to send an A2A message and get the response payload.

        Creates an A2AMessage with ``source_agent_id="bridge"``, sends it,
        and returns only the payload dict from the response.

        Args:
            agent_id: Target agent identifier.
            action: Action name for the A2A message.
            payload: Message payload dict.

        Returns:
            Response payload dict from the target agent.
        """
        msg = A2AMessage(
            source_agent_id="bridge",
            target_agent_id=agent_id,
            action=action,
            payload=payload,
            message_id=uuid.uuid4().hex,
            timestamp=time.time(),
        )
        response = await self.handle_message(agent_id, msg)
        return response.payload

    # -- properties ------------------------------------------------------

    @property
    def registry(self) -> AgentRegistry:
        """Get the AgentRegistry (raises RuntimeError if bridge not started).

        Returns:
            The AgentRegistry instance.

        Raises:
            RuntimeError: If ``start()`` hasn't been called.
        """
        if self._registry is None:
            raise RuntimeError("Bridge not started. Call start() first.")
        return self._registry

    @property
    def agents(self) -> dict[str, object]:
        """Return a copy of the agent map (agent_id -> wrapper object)."""
        return dict(self._agents)

    @property
    def identity_service(self) -> Optional[IdentityService]:
        """Get the IdentityService instance, or None if not started."""
        return self._identity_svc

    @property
    def escrow_service(self) -> Optional[EscrowService]:
        """Get the EscrowService instance, or None if not started."""
        return self._escrow_svc

    @property
    def evidence_service(self) -> Optional[EvidenceChainService]:
        """Get the EvidenceChainService instance, or None if not started."""
        return self._evidence_svc

    @property
    def review_service(self) -> Optional[ReviewService]:
        """Get the ReviewService instance, or None if not started."""
        return self._review_svc

    @property
    def task_market_service(self) -> Optional[TaskMarketService]:
        """Get the TaskMarketService instance, or None if not started."""
        return self._task_market_svc

    @property
    def is_started(self) -> bool:
        """Check whether the bridge has been started."""
        return self._started

    # -- internal helpers ------------------------------------------------

    @staticmethod
    def _init_db(db_path: str) -> sqlite3.Connection:
        """Initialize a shared SQLite database with the unified schema.

        Args:
            db_path: Path to the database file.

        Returns:
            Configured SQLite connection with Row factory and WAL mode.
        """
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        return conn
