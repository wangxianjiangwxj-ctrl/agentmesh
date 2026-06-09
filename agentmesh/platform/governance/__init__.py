"""AgentMesh Platform — Governance Voting (Phase 34, Module C).

Provides proposal creation, voting with equity snapshots, result
tallying, and execution for Agent Company governance.
"""
from __future__ import annotations

from agentmesh.platform.governance.models import (
    Decision,
    Proposal,
    ProposalStatus,
    ProposalType,
    Vote,
    VoteResult,
)
from agentmesh.platform.governance.repository import GovernanceRepository
from agentmesh.platform.governance.service import GovernanceError, GovernanceService

__all__ = [
    "Decision",
    "GovernanceError",
    "GovernanceRepository",
    "GovernanceService",
    "Proposal",
    "ProposalStatus",
    "ProposalType",
    "Vote",
    "VoteResult",
]
