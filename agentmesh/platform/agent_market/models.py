"""Agent Market — Data Models.

Pydantic models for JobPosting, Application, and SkillRegistry used by
the Agent Market module (Phase 35B).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Possible states for a job posting."""

    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class ApplicationStatus(str, Enum):
    """Possible states for an application."""

    PENDING = "pending"
    SHORTLISTED = "shortlisted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


def _now_utc() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


class SkillRegistry(BaseModel):
    """A registered skill available in the agent market.

    Attributes:
        skill_name: Unique name of the skill.
        category: Category grouping (e.g. "programming", "design").
        description: Optional description of the skill.
    """

    skill_name: str = Field(description="Unique skill name")
    category: str = Field(default="general", description="Category of the skill")
    description: str = Field(default="", description="Description of the skill")


class JobPosting(BaseModel):
    """A job posted by a company in the Agent Market.

    Attributes:
        id: Unique job identifier (UUID hex).
        company_id: The company posting the job.
        title: Job title.
        description: Optional detailed job description.
        required_skills: List of required skill names.
        reward_escrow: Escrow reward amount (points) for completing the job.
        max_applicants: Maximum number of applicants allowed (0 = unlimited).
        deadline: ISO-8601 deadline string; empty means no deadline.
        status: Current job status (open | closed | cancelled | completed).
        created_at: ISO-8601 creation timestamp.
    """

    id: str = Field(description="Unique job identifier (UUID hex)")
    company_id: str = Field(description="Company posting the job")
    title: str = Field(description="Job title", min_length=1)
    description: str = Field(default="", description="Detailed job description")
    required_skills: list[str] = Field(default_factory=list, description="List of required skill names")
    reward_escrow: int = Field(default=0, description="Escrow reward amount (points)")
    max_applicants: int = Field(default=0, ge=0, description="Max applicants (0 = unlimited)")
    deadline: str = Field(default="", description="ISO-8601 deadline string")
    status: JobStatus = Field(default=JobStatus.OPEN, description="Current job status")
    created_at: str = Field(default_factory=_now_utc, description="ISO-8601 creation timestamp")


class Application(BaseModel):
    """An agent's application for a job posting.

    Attributes:
        id: Unique application identifier (UUID hex).
        job_id: The job being applied to.
        agent_id: The agent submitting the application.
        cover_letter: Optional cover letter / pitch from the agent.
        status: Current application status (pending | shortlisted | accepted | rejected).
        assigned_at: ISO-8601 timestamp when the agent was assigned (accepted).
        created_at: ISO-8601 creation timestamp.
    """

    id: str = Field(description="Unique application identifier (UUID hex)")
    job_id: str = Field(description="The job being applied to")
    agent_id: str = Field(description="The agent submitting the application")
    cover_letter: str = Field(default="", description="Optional cover letter")
    status: ApplicationStatus = Field(default=ApplicationStatus.PENDING, description="Current application status")
    assigned_at: str = Field(default="", description="ISO-8601 assignment timestamp")
    created_at: str = Field(default_factory=_now_utc, description="ISO-8601 creation timestamp")
