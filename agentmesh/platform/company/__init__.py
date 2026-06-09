"""AgentMesh Platform — Company Registry (Phase 34, Module A).

Provides company creation, dissolution, membership management, and
company queries for the "Agent Company" feature.
"""
from __future__ import annotations

from agentmesh.platform.company.models import (
    Company,
    CompanyDetail,
    CompanyMember,
    CompanyRole,
    CompanyStatus,
)
from agentmesh.platform.company.repository import CompanyRepository
from agentmesh.platform.company.equity import EquityService
from agentmesh.platform.company.service import CompanyService

__all__ = [
    "Company",
    "CompanyDetail",
    "CompanyMember",
    "CompanyRepository",
    "CompanyRole",
    "CompanyService",
    "CompanyStatus",
    "EquityService",
]
