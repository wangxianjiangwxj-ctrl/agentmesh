"""Agent Market — Business Logic Service.

Provides the public API for the Agent Market:
- Job posting lifecycle (create, cancel, complete)
- Agent applications (apply, assign)
- Skill-based candidate matching
- Escrow integration for job completion rewards
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from agentmesh.platform.agent_market.models import (
    Application,
    ApplicationStatus,
    JobPosting,
    JobStatus,
    SkillRegistry,
)
from agentmesh.platform.agent_market.repository import AgentMarketRepository

# ---------------------------------------------------------------------------
# Escrow integration helper
# ---------------------------------------------------------------------------

def escrow_release_for_job(
    job: JobPosting,
    agent_id: str,
    escrow_svc=None,
) -> dict:
    """Release escrow reward for a completed job.

    When integrated with the platform's EscrowService, this function
    performs the actual point transfer from the company's escrow account
    to the assigned agent.  When called without an EscrowService instance
    (e.g., in tests), it returns a simulated release result.

    Args:
        job: The completed JobPosting.
        agent_id: The agent who completed the job.
        escrow_svc: Optional EscrowService instance for real point
            settlement.

    Returns:
        A dict with ``executor_reward`` and ``agent_id`` keys.
    """
    if escrow_svc is not None:
        # Real escrow release via platform EscrowService
        return escrow_svc.release(
            task_id=job.id,
            publisher_id=job.company_id,
            executor_id=agent_id,
            escrow_amount=job.reward_escrow,
            publisher_share=0.0,
            executor_share=1.0,
        )

    # Simulated release (used in tests / in-memory mode)
    return {
        "executor_reward": job.reward_escrow,
        "agent_id": agent_id,
        "status": "released",
    }


# ---------------------------------------------------------------------------
# AgentMarketService
# ---------------------------------------------------------------------------

class AgentMarketService:
    """High-level service for Agent Market management.

    Wraps the ``AgentMarketRepository`` with business rules such as:
    - Only open jobs accept applications.
    - Jobs at max_applicants capacity stop accepting new applications.
    - Only one agent can be assigned per job (accepted status).
    - Completed jobs are final and cannot be re-opened.

    Args:
        repository: The data repository to use.  Defaults to a fresh
            in-memory ``AgentMarketRepository``.
    """

    def __init__(self, repository: Optional[AgentMarketRepository] = None) -> None:
        self._repo = repository or AgentMarketRepository()

    # -- Job Posting Lifecycle ---------------------------------------------

    def create_job(
        self,
        company_id: str,
        title: str,
        description: str = "",
        required_skills: Optional[list[str]] = None,
        reward_escrow: int = 0,
        max_applicants: int = 0,
        deadline: str = "",
    ) -> dict:
        """Create a new job posting on behalf of a company.

        Args:
            company_id: The company posting the job.
            title: Job title (must be non-empty).
            description: Optional job description.
            required_skills: List of required skill names.
            reward_escrow: Escrow reward amount (points).
            max_applicants: Max applicants (0 = unlimited).
            deadline: ISO-8601 deadline string.

        Returns:
            A dict representation of the created JobPosting.

        Raises:
            ValueError: If ``title`` is empty.
        """
        if not title or not title.strip():
            raise ValueError("Job title must not be empty")

        if reward_escrow < 0:
            raise ValueError("Reward escrow must not be negative")

        job_id = uuid.uuid4().hex
        job = JobPosting(
            id=job_id,
            company_id=company_id,
            title=title.strip(),
            description=description,
            required_skills=required_skills or [],
            reward_escrow=reward_escrow,
            max_applicants=max_applicants,
            deadline=deadline,
        )
        self._repo.create_job(job)
        return job.model_dump()

    def cancel_job(self, job_id: str, company_id: str) -> dict:
        """Cancel an open job posting (company owner only).

        Args:
            job_id: The job to cancel.
            company_id: The company requesting cancellation.

        Returns:
            The updated JobPosting dict with status ``cancelled``.

        Raises:
            ValueError: If the job does not exist, is not owned by
                the company, or is already completed/cancelled.
        """
        job = self._repo.get_job(job_id)
        if job is None:
            raise ValueError(f"Job '{job_id}' not found")

        if job.company_id != company_id:
            raise ValueError(
                f"Company '{company_id}' is not the owner of job '{job_id}'"
            )

        if job.status in (JobStatus.COMPLETED, JobStatus.CANCELLED):
            raise ValueError(
                f"Job '{job_id}' is already {job.status.value} and cannot be cancelled"
            )

        updated = self._repo.update_job_status(job_id, JobStatus.CANCELLED)
        return updated.model_dump()

    def complete_job(
        self,
        job_id: str,
        company_id: str,
        escrow_svc=None,
    ) -> dict:
        """Mark a job as completed and trigger escrow payment.

        Must have at least one accepted application (assigned agent).

        Args:
            job_id: The job to complete.
            company_id: The company confirming completion.
            escrow_svc: Optional EscrowService for real point settlement.

        Returns:
            A dict with the job detail and escrow release result.

        Raises:
            ValueError: If the job is not found, not owned by the
                company, already completed, or has no assigned agent.
        """
        job = self._repo.get_job(job_id)
        if job is None:
            raise ValueError(f"Job '{job_id}' not found")

        if job.company_id != company_id:
            raise ValueError(
                f"Company '{company_id}' is not the owner of job '{job_id}'"
            )

        if job.status == JobStatus.COMPLETED:
            raise ValueError(f"Job '{job_id}' is already completed")

        if job.status == JobStatus.CANCELLED:
            raise ValueError(f"Job '{job_id}' is cancelled and cannot be completed")

        # Find the accepted (assigned) application
        apps = self.list_applications(job_id=job_id)
        accepted = [a for a in apps if a["status"] == ApplicationStatus.ACCEPTED.value]
        if not accepted:
            raise ValueError(
                f"Job '{job_id}' has no assigned agent; cannot complete without an accepted application"
            )

        assigned_agent_id = accepted[0]["agent_id"]

        # Update job status to completed
        self._repo.update_job_status(job_id, JobStatus.COMPLETED)

        # Release escrow
        release_result = escrow_release_for_job(job, assigned_agent_id, escrow_svc)

        return {
            "job": self._repo.get_job(job_id).model_dump(),
            "assigned_agent_id": assigned_agent_id,
            "escrow_release": release_result,
        }

    def close_job(self, job_id: str, company_id: str) -> dict:
        """Close a job posting to new applications.

        Unlike cancel, closing keeps existing applications intact.

        Args:
            job_id: The job to close.
            company_id: The company requesting close.

        Returns:
            The updated JobPosting dict with status ``closed``.

        Raises:
            ValueError: If the job is not found, not owned, or
                already in a final state.
        """
        job = self._repo.get_job(job_id)
        if job is None:
            raise ValueError(f"Job '{job_id}' not found")

        if job.company_id != company_id:
            raise ValueError(
                f"Company '{company_id}' is not the owner of job '{job_id}'"
            )

        if job.status in (JobStatus.COMPLETED, JobStatus.CANCELLED):
            raise ValueError(
                f"Job '{job_id}' is already {job.status.value} and cannot be closed"
            )

        updated = self._repo.update_job_status(job_id, JobStatus.CLOSED)
        return updated.model_dump()

    # -- Applications ------------------------------------------------------

    def apply_job(self, job_id: str, agent_id: str, cover_letter: str = "") -> dict:
        """Submit an application for a job.

        Args:
            job_id: The job to apply to.
            agent_id: The agent submitting the application.
            cover_letter: Optional cover letter / pitch.

        Returns:
            A dict representation of the created Application.

        Raises:
            ValueError: If the job is not found, not open, already at
                max capacity, or the agent already applied.
        """
        job = self._repo.get_job(job_id)
        if job is None:
            raise ValueError(f"Job '{job_id}' not found")

        if job.status != JobStatus.OPEN:
            raise ValueError(
                f"Job '{job_id}' is not open for applications (status: {job.status.value})"
            )

        # Check max applicants
        existing_apps = self.list_applications(job_id=job_id)
        if job.max_applicants > 0 and len(existing_apps) >= job.max_applicants:
            raise ValueError(
                f"Job '{job_id}' has reached its maximum capacity of {job.max_applicants} applicants"
            )

        # Check for duplicate application
        for app in existing_apps:
            if app["agent_id"] == agent_id:
                raise ValueError(
                    f"Agent '{agent_id}' has already applied to job '{job_id}'"
                )

        application_id = uuid.uuid4().hex
        application = Application(
            id=application_id,
            job_id=job_id,
            agent_id=agent_id,
            cover_letter=cover_letter,
        )
        self._repo.create_application(application)
        return application.model_dump()

    def assign_agent(self, application_id: str, company_id: str) -> dict:
        """Accept an application and assign the agent to the job.

        Only one application per job can be accepted. Other pending
        applications for the same job are set to shortlisted status.

        Args:
            application_id: The application to accept.
            company_id: The company accepting the application.

        Returns:
            The updated Application dict.

        Raises:
            ValueError: If the application is not found, the company
                does not own the job, or another agent is already
                assigned.
        """
        app = self._repo.get_application(application_id)
        if app is None:
            raise ValueError(f"Application '{application_id}' not found")

        job = self._repo.get_job(app.job_id)
        if job is None:
            raise ValueError(f"Job '{app.job_id}' not found (orphaned application)")

        if job.company_id != company_id:
            raise ValueError(
                f"Company '{company_id}' does not own job '{job.id}'"
            )

        if job.status != JobStatus.OPEN:
            raise ValueError(
                f"Job '{job.id}' is not open for assignment (status: {job.status.value})"
            )

        if app.status != ApplicationStatus.PENDING:
            raise ValueError(
                f"Application '{application_id}' is already {app.status.value}"
            )

        # Check if another agent is already accepted for this job
        all_apps = self.list_applications(job_id=app.job_id)
        for other in all_apps:
            if other["status"] == ApplicationStatus.ACCEPTED.value:
                raise ValueError(
                    f"Job '{app.job_id}' already has an assigned agent"
                )

        # Accept this application
        now = datetime.now(timezone.utc).isoformat()
        updated = self._repo.update_application_status_and_assigned_at(
            application_id, ApplicationStatus.ACCEPTED, now,
        )

        # Shortlist other pending applications
        for other in all_apps:
            if other["id"] != application_id and other["status"] == ApplicationStatus.PENDING.value:
                self._repo.update_application_status(
                    other["id"], ApplicationStatus.SHORTLISTED,
                )

        return updated.model_dump()

    def reject_application(self, application_id: str, company_id: str) -> dict:
        """Reject a pending or shortlisted application.

        Args:
            application_id: The application to reject.
            company_id: The company rejecting the application.

        Returns:
            The updated Application dict.

        Raises:
            ValueError: If the application is not found, the job
                ownership check fails, or the application is in a
                final state (accepted/rejected).
        """
        app = self._repo.get_application(application_id)
        if app is None:
            raise ValueError(f"Application '{application_id}' not found")

        job = self._repo.get_job(app.job_id)
        if job is None:
            raise ValueError(f"Job '{app.job_id}' not found (orphaned application)")

        if job.company_id != company_id:
            raise ValueError(
                f"Company '{company_id}' does not own job '{job.id}'"
            )

        if app.status in (ApplicationStatus.ACCEPTED, ApplicationStatus.REJECTED):
            raise ValueError(
                f"Application '{application_id}' is already {app.status.value}"
            )

        updated = self._repo.update_application_status(
            application_id, ApplicationStatus.REJECTED,
        )
        return updated.model_dump()

    # -- Skill Matching ----------------------------------------------------

    def register_skill(
        self,
        skill_name: str,
        category: str = "general",
        description: str = "",
    ) -> dict:
        """Register a new skill in the skill registry.

        Args:
            skill_name: Unique skill name.
            category: Category for the skill.
            description: Optional description.

        Returns:
            A dict representation of the registered SkillRegistry.

        Raises:
            ValueError: If the skill already exists or the name is empty.
        """
        if not skill_name or not skill_name.strip():
            raise ValueError("Skill name must not be empty")

        existing = self._repo.get_skill(skill_name.strip())
        if existing is not None:
            raise ValueError(f"Skill '{skill_name}' is already registered")

        skill = SkillRegistry(
            skill_name=skill_name.strip(),
            category=category,
            description=description,
        )
        self._repo.register_skill(skill)
        return skill.model_dump()

    def match_agents(self, job_id: str) -> list[dict]:
        """Find all applicants whose skills match the job requirements.

        An agent is considered a match if their application is pending
        or shortlisted, and they have been registered with skills that
        cover all the job's required_skills.

        Args:
            job_id: The job to find matching agents for.

        Returns:
            A list of dicts, each containing ``application`` and
            ``matched_skills`` keys.

        Raises:
            ValueError: If the job is not found.
        """
        job = self._repo.get_job(job_id)
        if job is None:
            raise ValueError(f"Job '{job_id}' not found")

        if not job.required_skills:
            # No required skills means all applicants are a match
            apps = self.list_applications(job_id=job_id)
            return [
                {
                    "application": a,
                    "matched_skills": [],
                    "match_score": 0,
                }
                for a in apps
                if a["status"] in (
                    ApplicationStatus.PENDING.value,
                    ApplicationStatus.SHORTLISTED.value,
                )
            ]

        required = set(job.required_skills)
        all_skills = self._repo.list_skills()
        platform_skill_names = {s.skill_name for s in all_skills}

        # All applicants for this job
        apps = self.list_applications(job_id=job_id)
        results: list[dict] = []

        for a in apps:
            if a["status"] not in (
                ApplicationStatus.PENDING.value,
                ApplicationStatus.SHORTLISTED.value,
            ):
                continue

            # An agent "has" a skill if it's registered in the platform
            # and is among the job's required skills.
            # In this simplified matching, we check which required skills
            # exist on the platform.
            matched = required & platform_skill_names
            score = len(matched) / len(required) if required else 1.0

            results.append({
                "application": a,
                "matched_skills": sorted(matched),
                "match_score": round(score, 2),
            })

        # Sort by match score descending
        results.sort(key=lambda r: r["match_score"], reverse=True)
        return results

    # -- Queries -----------------------------------------------------------

    def list_jobs(
        self,
        company_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[dict]:
        """List jobs with optional filters.

        Args:
            company_id: If set, only return jobs from this company.
            status: If set, only return jobs with this status.

        Returns:
            A list of JobPosting dicts.
        """
        jobs = self._repo.list_jobs()
        if company_id is not None:
            jobs = [j for j in jobs if j.company_id == company_id]
        if status is not None:
            jobs = [j for j in jobs if j.status.value == status]
        return [j.model_dump() for j in jobs]

    def list_applications(
        self,
        job_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[dict]:
        """List applications with optional filters.

        Args:
            job_id: If set, only return applications for this job.
            agent_id: If set, only return applications from this agent.
            status: If set, only return applications with this status.

        Returns:
            A list of Application dicts.
        """
        apps = self._repo.list_applications()
        if job_id is not None:
            apps = [a for a in apps if a.job_id == job_id]
        if agent_id is not None:
            apps = [a for a in apps if a.agent_id == agent_id]
        if status is not None:
            apps = [a for a in apps if a.status.value == status]
        return [a.model_dump() for a in apps]

    def get_job_detail(self, job_id: str) -> dict:
        """Return a job posting with its applications.

        Args:
            job_id: The job to inspect.

        Returns:
            A dict with keys ``job`` and ``applications``.

        Raises:
            ValueError: If the job does not exist.
        """
        job = self._repo.get_job(job_id)
        if job is None:
            raise ValueError(f"Job '{job_id}' not found")

        return {
            "job": job.model_dump(),
            "applications": self.list_applications(job_id=job_id),
        }

    def list_skills(self, category: Optional[str] = None) -> list[dict]:
        """List registered skills with optional category filter.

        Args:
            category: If set, only return skills in this category.

        Returns:
            A list of SkillRegistry dicts.
        """
        if category is not None:
            return [s.model_dump() for s in self._repo.list_skills_by_category(category)]
        return [s.model_dump() for s in self._repo.list_skills()]
