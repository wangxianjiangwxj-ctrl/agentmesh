"""Agent Market — In-Memory Repository.

Provides an in-memory data layer for JobPosting, Application, and
SkillRegistry entities.
"""
from __future__ import annotations

from typing import Optional

from agentmesh.platform.agent_market.models import (
    Application,
    ApplicationStatus,
    JobPosting,
    JobStatus,
    SkillRegistry,
)


class AgentMarketRepository:
    """In-memory repository for Agent Market entities.

    All data is stored in plain dicts keyed by their natural identifiers.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobPosting] = {}
        self._applications: dict[str, Application] = {}
        self._skills: dict[str, SkillRegistry] = {}

    # -- Job Posting CRUD --------------------------------------------------

    def create_job(self, job: JobPosting) -> JobPosting:
        """Persist a new job posting.

        Args:
            job: The JobPosting object to store.

        Returns:
            A deep copy of the stored JobPosting.
        """
        self._jobs[job.id] = job.model_copy(deep=True)
        return self.get_job(job.id)

    def get_job(self, job_id: str) -> Optional[JobPosting]:
        """Fetch a job posting by ID.

        Args:
            job_id: The unique job identifier.

        Returns:
            A deep copy of the JobPosting, or ``None`` if not found.
        """
        job = self._jobs.get(job_id)
        if job is None:
            return None
        return job.model_copy(deep=True)

    def list_jobs(self) -> list[JobPosting]:
        """Return all job postings.

        Returns:
            A list of deep-copied JobPosting objects.
        """
        return [j.model_copy(deep=True) for j in self._jobs.values()]

    def update_job_status(self, job_id: str, status: JobStatus) -> Optional[JobPosting]:
        """Update the status of an existing job posting.

        Args:
            job_id: The unique job identifier.
            status: The new JobStatus value.

        Returns:
            A deep copy of the updated JobPosting, or ``None`` if not found.
        """
        job = self._jobs.get(job_id)
        if job is None:
            return None
        job.status = status
        return job.model_copy(deep=True)

    # -- Application CRUD --------------------------------------------------

    def create_application(self, application: Application) -> Application:
        """Persist a new application.

        Args:
            application: The Application object to store.

        Returns:
            A deep copy of the stored Application.
        """
        self._applications[application.id] = application.model_copy(deep=True)
        return self.get_application(application.id)

    def get_application(self, application_id: str) -> Optional[Application]:
        """Fetch an application by ID.

        Args:
            application_id: The unique application identifier.

        Returns:
            A deep copy of the Application, or ``None`` if not found.
        """
        app = self._applications.get(application_id)
        if app is None:
            return None
        return app.model_copy(deep=True)

    def list_applications(self) -> list[Application]:
        """Return all applications.

        Returns:
            A list of deep-copied Application objects.
        """
        return [a.model_copy(deep=True) for a in self._applications.values()]

    def update_application_status(
        self, application_id: str, status: ApplicationStatus,
    ) -> Optional[Application]:
        """Update the status of an existing application.

        Args:
            application_id: The unique application identifier.
            status: The new ApplicationStatus value.

        Returns:
            A deep copy of the updated Application, or ``None`` if not found.
        """
        app = self._applications.get(application_id)
        if app is None:
            return None
        app.status = status
        return app.model_copy(deep=True)

    def update_application_status_and_assigned_at(
        self, application_id: str, status: ApplicationStatus, assigned_at: str,
    ) -> Optional[Application]:
        """Update the status and assignment timestamp of an application.

        Args:
            application_id: The unique application identifier.
            status: The new ApplicationStatus value.
            assigned_at: ISO-8601 assignment timestamp.

        Returns:
            A deep copy of the updated Application, or ``None`` if not found.
        """
        app = self._applications.get(application_id)
        if app is None:
            return None
        app.status = status
        app.assigned_at = assigned_at
        return app.model_copy(deep=True)

    # -- Skill Registry CRUD -----------------------------------------------

    def register_skill(self, skill: SkillRegistry) -> SkillRegistry:
        """Register a new skill in the skill registry.

        Args:
            skill: The SkillRegistry object to store.

        Returns:
            A deep copy of the stored SkillRegistry.
        """
        self._skills[skill.skill_name] = skill.model_copy(deep=True)
        return self.get_skill(skill.skill_name)

    def get_skill(self, skill_name: str) -> Optional[SkillRegistry]:
        """Fetch a skill by name.

        Args:
            skill_name: The skill name.

        Returns:
            A deep copy of the SkillRegistry, or ``None`` if not found.
        """
        skill = self._skills.get(skill_name)
        if skill is None:
            return None
        return skill.model_copy(deep=True)

    def list_skills(self) -> list[SkillRegistry]:
        """Return all registered skills.

        Returns:
            A list of deep-copied SkillRegistry objects.
        """
        return [s.model_copy(deep=True) for s in self._skills.values()]

    def list_skills_by_category(self, category: str) -> list[SkillRegistry]:
        """Return all skills in a given category.

        Args:
            category: The category to filter by.

        Returns:
            A list of deep-copied SkillRegistry objects.
        """
        return [
            s.model_copy(deep=True)
            for s in self._skills.values()
            if s.category == category
        ]
