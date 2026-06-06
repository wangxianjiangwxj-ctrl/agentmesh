"""
AgentMesh A2A Agent Wrappers — Phase 20 Direction C

Each module wraps a core AgentMesh service as an A2A-aware agent
that can communicate with other agents directly (peer-to-peer,
without going through the Gateway).
"""
from __future__ import annotations

from .agent_registry import A2AMessage, AgentInfo, AgentRegistry
from .agent_identity import IdentityAgent
from .agent_task_market import TaskMarketAgent
from .agent_escrow import EscrowAgent
from .agent_evidence import EvidenceAgent
from .agent_reputation import ReputationAgent

__all__ = [
    "A2AMessage",
    "AgentInfo",
    "AgentRegistry",
    "IdentityAgent",
    "TaskMarketAgent",
    "EscrowAgent",
    "EvidenceAgent",
    "ReputationAgent",
]
