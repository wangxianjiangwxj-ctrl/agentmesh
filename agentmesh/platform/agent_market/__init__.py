"""AgentMesh Platform — Agent Market (Phase 35B).

Provides job posting, agent application, skill-based matching, and
automated escrow settlement for the Agent Market ("Agent Hiring")
feature.
"""
from __future__ import annotations

from agentmesh.platform.agent_market.models import (
    Application,
    ApplicationStatus,
    JobPosting,
    JobStatus,
    SkillRegistry,
)
from agentmesh.platform.agent_market.repository import AgentMarketRepository
from agentmesh.platform.agent_market.service import (
    AgentMarketService,
    escrow_release_for_job,
)

__all__ = [
    "AgentMarketRepository",
    "AgentMarketService",
    "Application",
    "ApplicationStatus",
    "JobPosting",
    "JobStatus",
    "SkillRegistry",
    "escrow_release_for_job",
]
