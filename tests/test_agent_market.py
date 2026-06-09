"""Tests for Agent Market Module (Phase 35B).

Covers JobPosting, Application, SkillRegistry models, AgentMarketRepository,
and AgentMarketService with at least 15 test cases covering CRUD, matching,
and full workflow scenarios.
"""
from __future__ import annotations

import uuid

import pytest

from agentmesh.platform.agent_market import (
    AgentMarketRepository,
    AgentMarketService,
    Application,
    ApplicationStatus,
    JobPosting,
    JobStatus,
    SkillRegistry,
    escrow_release_for_job,
)

# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture
def repo() -> AgentMarketRepository:
    """A fresh in-memory repository for each test."""
    return AgentMarketRepository()


@pytest.fixture
def service() -> AgentMarketService:
    """A fresh service (backed by a clean in-memory repo)."""
    return AgentMarketService()


@pytest.fixture
def company_id() -> str:
    """A consistent company ID for job posting tests."""
    return uuid.uuid4().hex


@pytest.fixture
def agent_a() -> str:
    """First agent ID for application tests."""
    return uuid.uuid4().hex


@pytest.fixture
def agent_b() -> str:
    """Second agent ID for application tests."""
    return uuid.uuid4().hex


@pytest.fixture
def sample_job(service: AgentMarketService, company_id: str) -> dict:
    """Create a sample job posting and return its dict."""
    return service.create_job(
        company_id=company_id,
        title="Build AI Agent",
        description="Build an agent that automates web scraping",
        required_skills=["python", "web-scraping", "llm"],
        reward_escrow=500,
        max_applicants=5,
    )


# ====================================================================
# Tests: Models
# ====================================================================

class TestJobPostingModel:
    def test_job_create_minimal(self):
        """JobPosting can be created with just id, company_id, and title."""
        j = JobPosting(id="j1", company_id="c1", title="Build Bot")
        assert j.title == "Build Bot"
        assert j.status == JobStatus.OPEN
        assert j.reward_escrow == 0
        assert j.max_applicants == 0

    def test_job_auto_timestamp(self):
        """JobPosting gets a created_at timestamp on construction."""
        j = JobPosting(id="j2", company_id="c2", title="Test Job")
        assert j.created_at is not None
        assert "T" in j.created_at  # ISO-8601 format

    def test_job_required_skills_default(self):
        """JobPosting defaults to empty required_skills list."""
        j = JobPosting(id="j3", company_id="c3", title="Job")
        assert j.required_skills == []

    def test_application_create(self):
        """Application can be created with valid fields."""
        a = Application(id="a1", job_id="j1", agent_id="agent_a")
        assert a.status == ApplicationStatus.PENDING
        assert a.cover_letter == ""
        assert a.assigned_at == ""

    def test_skill_registry_create(self):
        """SkillRegistry can be created with valid fields."""
        s = SkillRegistry(skill_name="python", category="programming", description="Python language")
        assert s.skill_name == "python"
        assert s.category == "programming"
        assert s.description == "Python language"


# ====================================================================
# Tests: Repository
# ====================================================================

class TestAgentMarketRepository:
    def test_create_and_get_job(self, repo: AgentMarketRepository):
        """Creating a job and retrieving it by ID returns the same data."""
        job = JobPosting(id="j1", company_id="c1", title="Build Bot")
        repo.create_job(job)
        fetched = repo.get_job("j1")
        assert fetched is not None
        assert fetched.title == "Build Bot"
        assert fetched.company_id == "c1"

    def test_get_job_not_found(self, repo: AgentMarketRepository):
        """Getting a non-existent job returns None."""
        assert repo.get_job("nonexistent") is None

    def test_list_jobs_empty(self, repo: AgentMarketRepository):
        """An empty repository returns an empty list."""
        assert repo.list_jobs() == []

    def test_create_and_get_application(self, repo: AgentMarketRepository):
        """Creating an application and retrieving it by ID."""
        app = Application(id="a1", job_id="j1", agent_id="agent_x")
        repo.create_application(app)
        fetched = repo.get_application("a1")
        assert fetched is not None
        assert fetched.job_id == "j1"
        assert fetched.agent_id == "agent_x"

    def test_update_application_status(self, repo: AgentMarketRepository):
        """Updating an application's status persists the change."""
        app = Application(id="a1", job_id="j1", agent_id="agent_x")
        repo.create_application(app)
        updated = repo.update_application_status("a1", ApplicationStatus.ACCEPTED)
        assert updated is not None
        assert updated.status == ApplicationStatus.ACCEPTED

    def test_register_and_get_skill(self, repo: AgentMarketRepository):
        """Registering a skill and retrieving it by name."""
        skill = SkillRegistry(skill_name="python", category="programming")
        repo.register_skill(skill)
        fetched = repo.get_skill("python")
        assert fetched is not None
        assert fetched.category == "programming"

    def test_list_skills_by_category(self, repo: AgentMarketRepository):
        """Skills can be filtered by category."""
        repo.register_skill(SkillRegistry(skill_name="python", category="programming"))
        repo.register_skill(SkillRegistry(skill_name="design", category="design"))
        repo.register_skill(SkillRegistry(skill_name="go", category="programming"))
        prog_skills = repo.list_skills_by_category("programming")
        assert len(prog_skills) == 2


# ====================================================================
# Tests: Service
# ====================================================================

class TestAgentMarketService:
    # -- Job CRUD tests ----------------------------------------------------

    def test_create_job(self, service: AgentMarketService, company_id: str):
        """Creating a job returns a valid JobPosting dict."""
        result = service.create_job(
            company_id=company_id,
            title="Scrape Data",
            description="Scrape 1000 pages",
            required_skills=["python"],
            reward_escrow=300,
        )
        assert result["title"] == "Scrape Data"
        assert result["company_id"] == company_id
        assert result["status"] == JobStatus.OPEN.value
        assert result["reward_escrow"] == 300
        assert result["required_skills"] == ["python"]

    def test_create_job_empty_title_raises(self, service: AgentMarketService, company_id: str):
        """Creating a job with an empty title raises ValueError."""
        with pytest.raises(ValueError, match="title must not be empty"):
            service.create_job(company_id, "")

    def test_create_job_negative_reward_raises(self, service: AgentMarketService, company_id: str):
        """Creating a job with a negative reward raises ValueError."""
        with pytest.raises(ValueError, match="Reward escrow must not be negative"):
            service.create_job(company_id, "Job", reward_escrow=-1)

    def test_list_jobs(self, service: AgentMarketService, company_id: str):
        """Listing jobs returns all registered jobs."""
        assert service.list_jobs() == []
        service.create_job(company_id, "Job 1", reward_escrow=100)
        service.create_job(company_id, "Job 2", reward_escrow=200)
        jobs = service.list_jobs()
        assert len(jobs) == 2

    def test_list_jobs_filter_by_company(self, service: AgentMarketService, company_id: str):
        """Listing jobs filtered by company returns only matching jobs."""
        other_co = uuid.uuid4().hex
        service.create_job(company_id, "Job A", reward_escrow=100)
        service.create_job(company_id, "Job B", reward_escrow=200)
        service.create_job(other_co, "Job C", reward_escrow=300)
        co_jobs = service.list_jobs(company_id=company_id)
        assert len(co_jobs) == 2
        other_jobs = service.list_jobs(company_id=other_co)
        assert len(other_jobs) == 1

    def test_list_jobs_filter_by_status(self, service: AgentMarketService, company_id: str):
        """Listing jobs filtered by status returns only matching jobs."""
        j1 = service.create_job(company_id, "Open Job", reward_escrow=100)
        j2 = service.create_job(company_id, "To Cancel", reward_escrow=200)
        service.cancel_job(j2["id"], company_id)
        open_jobs = service.list_jobs(status="open")
        assert len(open_jobs) == 1
        cancelled_jobs = service.list_jobs(status="cancelled")
        assert len(cancelled_jobs) == 1

    def test_get_job_detail(self, service: AgentMarketService, company_id: str, agent_a: str):
        """Job detail includes the job and its applications."""
        job = service.create_job(company_id, "Detail Job", reward_escrow=100)
        service.apply_job(job["id"], agent_a, "I am interested")
        detail = service.get_job_detail(job["id"])
        assert detail["job"]["id"] == job["id"]
        assert len(detail["applications"]) == 1
        assert detail["applications"][0]["agent_id"] == agent_a

    def test_get_job_detail_not_found(self, service: AgentMarketService):
        """Getting detail for a non-existent job raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            service.get_job_detail("nonexistent")

    def test_cancel_job(self, service: AgentMarketService, company_id: str):
        """Cancelling an open job sets its status to cancelled."""
        job = service.create_job(company_id, "To Cancel", reward_escrow=100)
        result = service.cancel_job(job["id"], company_id)
        assert result["status"] == JobStatus.CANCELLED.value
        # Verify via detail
        detail = service.get_job_detail(job["id"])
        assert detail["job"]["status"] == JobStatus.CANCELLED.value

    def test_cancel_job_not_owner_raises(self, service: AgentMarketService, company_id: str):
        """Only the owning company can cancel a job."""
        other_co = uuid.uuid4().hex
        job = service.create_job(company_id, "Job", reward_escrow=100)
        with pytest.raises(ValueError, match="not the owner"):
            service.cancel_job(job["id"], other_co)

    def test_cancel_job_twice_raises(self, service: AgentMarketService, company_id: str):
        """Cancelling an already cancelled job raises ValueError."""
        job = service.create_job(company_id, "Job", reward_escrow=100)
        service.cancel_job(job["id"], company_id)
        with pytest.raises(ValueError, match="already cancelled"):
            service.cancel_job(job["id"], company_id)

    def test_cancel_job_not_found_raises(self, service: AgentMarketService, company_id: str):
        """Cancelling a non-existent job raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            service.cancel_job("phantom", company_id)

    def test_close_job(self, service: AgentMarketService, company_id: str):
        """Closing an open job sets its status to closed."""
        job = service.create_job(company_id, "Close Job", reward_escrow=100)
        result = service.close_job(job["id"], company_id)
        assert result["status"] == JobStatus.CLOSED.value

    def test_close_job_not_owner_raises(self, service: AgentMarketService, company_id: str):
        """Only the owning company can close a job."""
        other_co = uuid.uuid4().hex
        job = service.create_job(company_id, "Job", reward_escrow=100)
        with pytest.raises(ValueError, match="not the owner"):
            service.close_job(job["id"], other_co)

    def test_close_cancelled_job_raises(self, service: AgentMarketService, company_id: str):
        """Closing a cancelled job raises ValueError."""
        job = service.create_job(company_id, "Job", reward_escrow=100)
        service.cancel_job(job["id"], company_id)
        with pytest.raises(ValueError, match="already cancelled"):
            service.close_job(job["id"], company_id)

    # -- Application tests -------------------------------------------------

    def test_apply_job(self, service: AgentMarketService, company_id: str, agent_a: str):
        """An agent can apply to an open job."""
        job = service.create_job(company_id, "Apply Job", reward_escrow=100)
        app = service.apply_job(job["id"], agent_a, "I can do this!")
        assert app["job_id"] == job["id"]
        assert app["agent_id"] == agent_a
        assert app["cover_letter"] == "I can do this!"
        assert app["status"] == ApplicationStatus.PENDING.value

    def test_apply_job_not_open_raises(self, service: AgentMarketService, company_id: str, agent_a: str):
        """Applying to a closed/cancelled job raises ValueError."""
        job = service.create_job(company_id, "Closed Job", reward_escrow=100)
        service.cancel_job(job["id"], company_id)
        with pytest.raises(ValueError, match="not open"):
            service.apply_job(job["id"], agent_a)

    def test_apply_job_max_applicants(self, service: AgentMarketService, company_id: str, agent_a: str):
        """Applying when at max capacity raises ValueError."""
        job = service.create_job(company_id, "Popular Job", reward_escrow=100, max_applicants=1)
        service.apply_job(job["id"], agent_a)
        with pytest.raises(ValueError, match="maximum capacity"):
            service.apply_job(job["id"], uuid.uuid4().hex)

    def test_apply_job_duplicate_raises(self, service: AgentMarketService, company_id: str, agent_a: str):
        """An agent cannot apply to the same job twice."""
        job = service.create_job(company_id, "Unique Job", reward_escrow=100)
        service.apply_job(job["id"], agent_a)
        with pytest.raises(ValueError, match="already applied"):
            service.apply_job(job["id"], agent_a)

    def test_apply_job_not_found_raises(self, service: AgentMarketService, agent_a: str):
        """Applying to a non-existent job raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            service.apply_job("phantom", agent_a)

    def test_assign_agent(self, service: AgentMarketService, company_id: str, agent_a: str, agent_b: str):
        """Assigning an agent accepts their application and shortlists others."""
        job = service.create_job(company_id, "Assign Job", reward_escrow=200)
        app_a = service.apply_job(job["id"], agent_a, "I am a")
        app_b = service.apply_job(job["id"], agent_b, "I am b")
        result = service.assign_agent(app_a["id"], company_id)
        assert result["status"] == ApplicationStatus.ACCEPTED.value
        assert result["agent_id"] == agent_a
        assert result["assigned_at"] != ""

        # Check other application is shortlisted
        apps = service.list_applications(job_id=job["id"])
        statuses = {a["id"]: a["status"] for a in apps}
        assert statuses[app_a["id"]] == ApplicationStatus.ACCEPTED.value
        assert statuses[app_b["id"]] == ApplicationStatus.SHORTLISTED.value

    def test_assign_agent_not_owner_raises(self, service: AgentMarketService, company_id: str, agent_a: str):
        """Only the owning company can assign an agent."""
        other_co = uuid.uuid4().hex
        job = service.create_job(company_id, "Job", reward_escrow=100)
        app = service.apply_job(job["id"], agent_a)
        with pytest.raises(ValueError, match="does not own"):
            service.assign_agent(app["id"], other_co)

    def test_assign_agent_twice_raises(self, service: AgentMarketService, company_id: str, agent_a: str, agent_b: str):
        """Only one agent can be assigned per job (second assign fails as shortlisted)."""
        job = service.create_job(company_id, "Single Assign", reward_escrow=200)
        app_a = service.apply_job(job["id"], agent_a)
        app_b = service.apply_job(job["id"], agent_b)
        service.assign_agent(app_a["id"], company_id)
        # app_b was auto-shortlisted when app_a was accepted
        with pytest.raises(ValueError, match="already shortlisted"):
            service.assign_agent(app_b["id"], company_id)

    def test_assign_agent_already_assigned_raises(self, service: AgentMarketService, company_id: str, agent_a: str):
        """Cannot assign an already-processed application."""
        job = service.create_job(company_id, "Job", reward_escrow=100, max_applicants=3)
        # Create two jobs and ensure no other assignment exists
        app = service.apply_job(job["id"], agent_a)
        service.assign_agent(app["id"], company_id)
        # Modify directly for test: create another and try to assign same one again
        # Actually after assignment, app status is no longer PENDING
        with pytest.raises(ValueError, match="already"):
            service.assign_agent(app["id"], company_id)

    def test_reject_application(self, service: AgentMarketService, company_id: str, agent_a: str):
        """A company can reject a pending application."""
        job = service.create_job(company_id, "Job", reward_escrow=100)
        app = service.apply_job(job["id"], agent_a)
        result = service.reject_application(app["id"], company_id)
        assert result["status"] == ApplicationStatus.REJECTED.value

    def test_reject_application_not_owner_raises(self, service: AgentMarketService, company_id: str, agent_a: str):
        """Only the owning company can reject an application."""
        other_co = uuid.uuid4().hex
        job = service.create_job(company_id, "Job", reward_escrow=100)
        app = service.apply_job(job["id"], agent_a)
        with pytest.raises(ValueError, match="does not own"):
            service.reject_application(app["id"], other_co)

    def test_list_applications_filtered(self, service: AgentMarketService, company_id: str, agent_a: str, agent_b: str):
        """Applications can be filtered by job, agent, and status."""
        job1 = service.create_job(company_id, "Job 1", reward_escrow=100)
        job2 = service.create_job(company_id, "Job 2", reward_escrow=200)
        service.apply_job(job1["id"], agent_a)
        service.apply_job(job1["id"], agent_b)
        service.apply_job(job2["id"], agent_a)

        apps_job1 = service.list_applications(job_id=job1["id"])
        assert len(apps_job1) == 2

        apps_agent_a = service.list_applications(agent_id=agent_a)
        assert len(apps_agent_a) == 2

        apps_pending = service.list_applications(status="pending")
        assert len(apps_pending) == 3

    # -- Complete Job tests ------------------------------------------------

    def test_complete_job(self, service: AgentMarketService, company_id: str, agent_a: str):
        """Completing a job releases escrow and marks the job as completed."""
        job = service.create_job(company_id, "Complete Job", reward_escrow=500)
        app = service.apply_job(job["id"], agent_a)
        service.assign_agent(app["id"], company_id)
        result = service.complete_job(job["id"], company_id)
        assert result["job"]["status"] == JobStatus.COMPLETED.value
        assert result["assigned_agent_id"] == agent_a
        assert result["escrow_release"]["executor_reward"] == 500
        assert result["escrow_release"]["status"] == "released"

    def test_complete_job_no_accepted_app_raises(self, service: AgentMarketService, company_id: str):
        """Completing a job with no assigned agent raises ValueError."""
        job = service.create_job(company_id, "No Agent Job", reward_escrow=100)
        with pytest.raises(ValueError, match="no assigned agent"):
            service.complete_job(job["id"], company_id)

    def test_complete_job_not_owner_raises(self, service: AgentMarketService, company_id: str, agent_a: str):
        """Only the owning company can complete a job."""
        other_co = uuid.uuid4().hex
        job = service.create_job(company_id, "Job", reward_escrow=100)
        app = service.apply_job(job["id"], agent_a)
        service.assign_agent(app["id"], company_id)
        with pytest.raises(ValueError, match="not the owner"):
            service.complete_job(job["id"], other_co)

    def test_complete_job_already_completed_raises(self, service: AgentMarketService, company_id: str, agent_a: str):
        """Completing an already completed job raises ValueError."""
        job = service.create_job(company_id, "Done Job", reward_escrow=100)
        app = service.apply_job(job["id"], agent_a)
        service.assign_agent(app["id"], company_id)
        service.complete_job(job["id"], company_id)
        with pytest.raises(ValueError, match="already completed"):
            service.complete_job(job["id"], company_id)

    def test_complete_cancelled_job_raises(self, service: AgentMarketService, company_id: str):
        """Completing a cancelled job raises ValueError."""
        job = service.create_job(company_id, "Cancelled Job", reward_escrow=100)
        service.cancel_job(job["id"], company_id)
        with pytest.raises(ValueError, match="cancelled"):
            service.complete_job(job["id"], company_id)

    # -- Skill Registry tests ----------------------------------------------

    def test_register_skill(self, service: AgentMarketService):
        """Registering a skill returns a valid SkillRegistry dict."""
        result = service.register_skill("python", "programming", "Python language")
        assert result["skill_name"] == "python"
        assert result["category"] == "programming"
        assert result["description"] == "Python language"

    def test_register_skill_duplicate_raises(self, service: AgentMarketService):
        """Registering a duplicate skill name raises ValueError."""
        service.register_skill("python", "programming")
        with pytest.raises(ValueError, match="already registered"):
            service.register_skill("python", "data")

    def test_register_skill_empty_name_raises(self, service: AgentMarketService):
        """Registering a skill with an empty name raises ValueError."""
        with pytest.raises(ValueError, match="Skill name must not be empty"):
            service.register_skill("")

    def test_list_skills(self, service: AgentMarketService):
        """Listing skills returns all registered skills."""
        assert service.list_skills() == []
        service.register_skill("python", "programming")
        service.register_skill("design", "design")
        skills = service.list_skills()
        assert len(skills) == 2

    def test_list_skills_by_category(self, service: AgentMarketService):
        """Listing skills filtered by category."""
        service.register_skill("python", "programming")
        service.register_skill("go", "programming")
        service.register_skill("design", "design")
        prog = service.list_skills(category="programming")
        assert len(prog) == 2
        design = service.list_skills(category="design")
        assert len(design) == 1

    # -- Matching tests ----------------------------------------------------

    def test_match_agents_no_required_skills(self, service: AgentMarketService, company_id: str, agent_a: str):
        """When a job has no required skills, all applicants match."""
        job = service.create_job(company_id, "Easy Job", reward_escrow=50)
        service.apply_job(job["id"], agent_a)
        matches = service.match_agents(job["id"])
        assert len(matches) == 1
        assert matches[0]["application"]["agent_id"] == agent_a
        assert matches[0]["match_score"] == 0  # no required skills

    def test_match_agents_with_skills(self, service: AgentMarketService, company_id: str, agent_a: str):
        """Matching considers registered skills against job requirements."""
        # Register skills
        service.register_skill("python", "programming")
        service.register_skill("web-scraping", "programming")
        service.register_skill("llm", "ai")

        # Create a job requiring all three
        job = service.create_job(
            company_id,
            "Full Stack Agent",
            required_skills=["python", "web-scraping", "llm"],
            reward_escrow=500,
        )
        service.apply_job(job["id"], agent_a)
        matches = service.match_agents(job["id"])
        assert len(matches) == 1
        # Since all required skills exist in the registry
        assert len(matches[0]["matched_skills"]) == 3
        assert matches[0]["match_score"] == 1.0

    def test_match_agents_partial_skills(self, service: AgentMarketService, company_id: str, agent_a: str):
        """Matching returns partial scores when not all skills are registered."""
        service.register_skill("python", "programming")
        # Job has more skills than registered
        job = service.create_job(
            company_id,
            "Partial Job",
            required_skills=["python", "unknown_skill"],
            reward_escrow=300,
        )
        service.apply_job(job["id"], agent_a)
        matches = service.match_agents(job["id"])
        assert len(matches) == 1
        assert len(matches[0]["matched_skills"]) == 1
        assert matches[0]["match_score"] == 0.5

    def test_match_agents_ordering(self, service: AgentMarketService, company_id: str, agent_a: str, agent_b: str):
        """Matches are sorted by score descending."""
        service.register_skill("common", "general")

        job = service.create_job(
            company_id,
            "Ordered Job",
            required_skills=["common", "rare"],
            reward_escrow=400,
        )
        service.apply_job(job["id"], agent_a)
        service.apply_job(job["id"], agent_b)
        matches = service.match_agents(job["id"])
        # Both agents have the same matching (1/2)
        assert len(matches) == 2
        assert matches[0]["match_score"] >= matches[1]["match_score"]

    def test_match_agents_job_not_found_raises(self, service: AgentMarketService):
        """Matching for a non-existent job raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            service.match_agents("phantom")

    # -- Escrow Release tests ----------------------------------------------

    def test_escrow_release_simulated(self, service: AgentMarketService, company_id: str):
        """escrow_release_for_job returns a simulated result when no escrow service."""
        job = JobPosting(id="j1", company_id=company_id, title="T", reward_escrow=500)
        result = escrow_release_for_job(job, "agent_x")
        assert result["executor_reward"] == 500
        assert result["agent_id"] == "agent_x"
        assert result["status"] == "released"

    # -- Full Workflow tests -----------------------------------------------

    def test_full_workflow(self, service: AgentMarketService, company_id: str, agent_a: str, agent_b: str):
        """A complete agent market workflow from job creation to completion."""
        # 1. Register skills
        service.register_skill("python", "programming")
        service.register_skill("web-scraping", "programming")
        service.register_skill("llm", "ai")

        # 2. Company posts a job
        job = service.create_job(
            company_id,
            "Build Web Scraper",
            "Build an AI-powered web scraper",
            required_skills=["python", "web-scraping", "llm"],
            reward_escrow=1000,
            max_applicants=10,
        )
        assert job["status"] == JobStatus.OPEN.value

        # 3. Agent A applies (best match)
        app_a = service.apply_job(job["id"], agent_a, "I know all required skills")
        assert app_a["status"] == ApplicationStatus.PENDING.value

        # 4. Agent B applies
        app_b = service.apply_job(job["id"], agent_b, "I am also interested")
        assert app_b["status"] == ApplicationStatus.PENDING.value

        # 5. Match agents
        matches = service.match_agents(job["id"])
        assert len(matches) == 2

        # 6. Assign agent A
        assigned = service.assign_agent(app_a["id"], company_id)
        assert assigned["status"] == ApplicationStatus.ACCEPTED.value

        # 7. Verify Agent B is shortlisted
        apps = service.list_applications(job_id=job["id"])
        statuses = {a["agent_id"]: a["status"] for a in apps}
        assert statuses[agent_a] == ApplicationStatus.ACCEPTED.value
        assert statuses[agent_b] == ApplicationStatus.SHORTLISTED.value

        # 8. Complete the job
        complete = service.complete_job(job["id"], company_id)
        assert complete["job"]["status"] == JobStatus.COMPLETED.value
        assert complete["assigned_agent_id"] == agent_a
        assert complete["escrow_release"]["executor_reward"] == 1000

    def test_full_workflow_with_rejection(self, service: AgentMarketService, company_id: str, agent_a: str, agent_b: str):
        """Workflow where one applicant is rejected and another is assigned."""
        job = service.create_job(company_id, "Job", reward_escrow=300, max_applicants=3)

        app_a = service.apply_job(job["id"], agent_a, "I am qualified")
        app_b = service.apply_job(job["id"], agent_b, "I am better")

        # Reject agent A
        rejected = service.reject_application(app_a["id"], company_id)
        assert rejected["status"] == ApplicationStatus.REJECTED.value

        # Assign agent B
        assigned = service.assign_agent(app_b["id"], company_id)
        assert assigned["status"] == ApplicationStatus.ACCEPTED.value

        # Complete
        result = service.complete_job(job["id"], company_id)
        assert result["assigned_agent_id"] == agent_b

    def test_multiple_jobs_independent(self, service: AgentMarketService, company_id: str, agent_a: str, agent_b: str):
        """Multiple jobs can run independently with their own applicants."""
        job1 = service.create_job(company_id, "Job 1", reward_escrow=100)
        job2 = service.create_job(company_id, "Job 2", reward_escrow=200)
        job3 = service.create_job(company_id, "Job 3", reward_escrow=300)

        service.apply_job(job1["id"], agent_a)
        service.apply_job(job1["id"], agent_b)
        service.apply_job(job2["id"], agent_a)
        service.apply_job(job3["id"], agent_b)

        assert len(service.list_applications(job_id=job1["id"])) == 2
        assert len(service.list_applications(job_id=job2["id"])) == 1
        assert len(service.list_applications(job_id=job3["id"])) == 1

        # Each job can have its own assigned agent
        app1 = service.list_applications(job_id=job1["id"])[0]
        service.assign_agent(app1["id"], company_id)
        app2 = service.list_applications(job_id=job2["id"])[0]
        service.assign_agent(app2["id"], company_id)
        app3 = service.list_applications(job_id=job3["id"])[0]
        service.assign_agent(app3["id"], company_id)
