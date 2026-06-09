"""Company Registry — Data Models.

Pydantic models for Company and CompanyMember used by the AgentMesh
company-registry module (Phase 34, Module A).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class CompanyStatus(str, Enum):
    """Possible states for an agent company."""

    ACTIVE = "active"
    FROZEN = "frozen"
    DISSOLVED = "dissolved"


class CompanyRole(str, Enum):
    """Roles an agent can hold within a company."""

    FOUNDER = "founder"
    ADMIN = "admin"
    MEMBER = "member"


def _now_utc() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


class Company(BaseModel):
    """An agent-owned company / organisation on the platform.

    Attributes:
        id: Unique identifier (UUID hex).
        name: Human-readable company name.
        description: Optional description of the company.
        founder_id: Agent ID of the founding agent.
        status: Current life-cycle status (active | frozen | dissolved).
        created_at: ISO-8601 timestamp of creation.
    """

    id: str = Field(description="Unique company identifier (UUID hex)")
    name: str = Field(description="Human-readable company name", min_length=1)
    description: str = Field(default="", description="Optional description of the company")
    founder_id: str = Field(description="Agent ID of the founding agent")
    status: CompanyStatus = Field(default=CompanyStatus.ACTIVE, description="Current life-cycle status")
    created_at: str = Field(default_factory=_now_utc, description="ISO-8601 creation timestamp")


class CompanyMember(BaseModel):
    """An agent's membership in a company.

    Attributes:
        company_id: The company this membership belongs to.
        agent_id: The agent who is a member.
        role: Role within the company (founder | admin | member).
        joined_at: ISO-8601 timestamp of when the agent joined.
    """

    company_id: str = Field(description="The company this membership belongs to")
    agent_id: str = Field(description="The agent who is a member")
    role: CompanyRole = Field(default=CompanyRole.MEMBER, description="Role within the company")
    joined_at: str = Field(default_factory=_now_utc, description="ISO-8601 join timestamp")


class CompanyDetail(BaseModel):
    """Full company detail including member list.

    Attributes:
        company: The Company object.
        members: List of CompanyMember objects.
    """

    company: Company
    members: list[CompanyMember]
