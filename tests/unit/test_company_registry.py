"""Unit tests for Company Registry Module (Phase 34).

Covers Company, CompanyMember models, CompanyRepository, and
CompanyService with at least 20 test cases.
"""
from __future__ import annotations

import uuid

import pytest

from agentmesh.platform.company import (
    Company,
    CompanyMember,
    CompanyRepository,
    CompanyRole,
    CompanyService,
    CompanyStatus,
)


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture
def repo() -> CompanyRepository:
    """A fresh in-memory repository for each test."""
    return CompanyRepository()


@pytest.fixture
def service() -> CompanyService:
    """A fresh service (backed by a clean in-memory repo)."""
    return CompanyService()


@pytest.fixture
def founder_id() -> str:
    """A consistent founder agent ID."""
    return uuid.uuid4().hex


@pytest.fixture
def other_agent_id() -> str:
    """Another agent ID for membership tests."""
    return uuid.uuid4().hex


@pytest.fixture
def sample_company(service: CompanyService, founder_id: str) -> dict:
    """Create a sample company and return its detail dict."""
    return service.create_company("TestCorp", "A test company", founder_id)


# ====================================================================
# Tests: Models
# ====================================================================

class TestCompanyModel:
    def test_company_create_minimal(self):
        """Company can be created with just id, name, and founder_id."""
        c = Company(id="c1", name="Acme", founder_id="agent_a")
        assert c.name == "Acme"
        assert c.status == CompanyStatus.ACTIVE
        assert c.description == ""

    def test_company_auto_timestamp(self):
        """Company gets a created_at timestamp on construction."""
        c = Company(id="c2", name="Beta", founder_id="agent_b")
        assert c.created_at is not None
        assert "T" in c.created_at  # ISO-8601 format

    def test_company_status_enum(self):
        """Company status must be a valid CompanyStatus value."""
        c = Company(id="c3", name="Gamma", founder_id="agent_c", status=CompanyStatus.FROZEN)
        assert c.status == CompanyStatus.FROZEN

    def test_company_member_create(self):
        """CompanyMember can be created with valid fields."""
        m = CompanyMember(company_id="c1", agent_id="agent_a", role=CompanyRole.FOUNDER)
        assert m.role == CompanyRole.FOUNDER
        assert m.joined_at is not None

    def test_company_member_default_role(self):
        """CompanyMember defaults to MEMBER role."""
        m = CompanyMember(company_id="c1", agent_id="agent_b")
        assert m.role == CompanyRole.MEMBER


# ====================================================================
# Tests: Repository
# ====================================================================

class TestCompanyRepository:
    def test_create_and_get_company(self, repo: CompanyRepository):
        """Creating a company and retrieving it by ID returns the same data."""
        company = Company(id="c1", name="Acme", founder_id="agent_a")
        repo.create_company(company)
        fetched = repo.get_company("c1")
        assert fetched is not None
        assert fetched.name == "Acme"
        assert fetched.id == "c1"

    def test_get_company_not_found(self, repo: CompanyRepository):
        """Getting a non-existent company returns None."""
        assert repo.get_company("nonexistent") is None

    def test_list_companies_empty(self, repo: CompanyRepository):
        """An empty repository returns an empty list."""
        assert repo.list_companies() == []

    def test_list_companies_multiple(self, repo: CompanyRepository):
        """Multiple companies are all returned."""
        repo.create_company(Company(id="c1", name="A", founder_id="a1"))
        repo.create_company(Company(id="c2", name="B", founder_id="a2"))
        companies = repo.list_companies()
        assert len(companies) == 2

    def test_update_company_status(self, repo: CompanyRepository):
        """Updating a company's status persists the change."""
        repo.create_company(Company(id="c1", name="Acme", founder_id="a1"))
        updated = repo.update_company_status("c1", CompanyStatus.FROZEN)
        assert updated is not None
        assert updated.status == CompanyStatus.FROZEN
        fetched = repo.get_company("c1")
        assert fetched.status == CompanyStatus.FROZEN

    def test_update_status_not_found(self, repo: CompanyRepository):
        """Updating status on a non-existent company returns None."""
        result = repo.update_company_status("ghost", CompanyStatus.DISSOLVED)
        assert result is None

    def test_add_and_get_members(self, repo: CompanyRepository):
        """Members can be added to a company and retrieved."""
        repo.create_company(Company(id="c1", name="Acme", founder_id="a1"))
        member = CompanyMember(company_id="c1", agent_id="a1", role=CompanyRole.FOUNDER)
        repo.add_member(member)
        members = repo.get_members("c1")
        assert len(members) == 1
        assert members[0].agent_id == "a1"

    def test_remove_member(self, repo: CompanyRepository):
        """Removing a member succeeds and reduces the member count."""
        repo.create_company(Company(id="c1", name="Acme", founder_id="a1"))
        repo.add_member(CompanyMember(company_id="c1", agent_id="a1", role=CompanyRole.FOUNDER))
        repo.add_member(CompanyMember(company_id="c1", agent_id="a2"))
        assert repo.remove_member("c1", "a2") is True
        assert len(repo.get_members("c1")) == 1

    def test_remove_member_not_found(self, repo: CompanyRepository):
        """Removing a non-existent member returns False."""
        assert repo.remove_member("c1", "ghost") is False

    def test_get_companies_for_agent(self, repo: CompanyRepository):
        """All companies an agent is a member of are returned."""
        repo.create_company(Company(id="c1", name="A", founder_id="a1"))
        repo.create_company(Company(id="c2", name="B", founder_id="a2"))
        repo.add_member(CompanyMember(company_id="c1", agent_id="a1", role=CompanyRole.FOUNDER))
        repo.add_member(CompanyMember(company_id="c1", agent_id="a2"))
        repo.add_member(CompanyMember(company_id="c2", agent_id="a2", role=CompanyRole.FOUNDER))
        companies = repo.get_companies_for_agent("a2")
        assert len(companies) == 2
        assert {c.id for c in companies} == {"c1", "c2"}


# ====================================================================
# Tests: Service
# ====================================================================

class TestCompanyService:
    def test_create_company_founder_auto_join(self, service: CompanyService, founder_id: str):
        """Creating a company automatically adds the founder as a member with founder role."""
        result = service.create_company("NewCo", "A new company", founder_id)
        assert result["name"] == "NewCo"
        assert result["founder_id"] == founder_id
        assert result["status"] == "active"
        assert len(result["members"]) == 1
        member = result["members"][0]
        assert member["agent_id"] == founder_id
        assert member["role"] == CompanyRole.FOUNDER.value

    def test_create_company_empty_name_raises(self, service: CompanyService, founder_id: str):
        """Creating a company with an empty name raises ValueError."""
        with pytest.raises(ValueError, match="name must not be empty"):
            service.create_company("", "desc", founder_id)
        with pytest.raises(ValueError, match="name must not be empty"):
            service.create_company("   ", "desc", founder_id)

    def test_create_company_long_description(self, service: CompanyService, founder_id: str):
        """Creating a company with a very long description is allowed."""
        long_desc = "x" * 10_000
        result = service.create_company("LongDescCo", long_desc, founder_id)
        assert result["description"] == long_desc

    def test_list_companies(self, service: CompanyService, founder_id: str):
        """Listing companies returns all registered companies."""
        assert service.list_companies() == []
        service.create_company("Co1", "First", founder_id)
        service.create_company("Co2", "Second", uuid.uuid4().hex)
        companies = service.list_companies()
        assert len(companies) == 2

    def test_get_company_detail(self, service: CompanyService, founder_id: str, other_agent_id: str):
        """Company detail includes the company and its member list."""
        result = service.create_company("DetailCo", "detail", founder_id)
        cid = result["id"]
        service.join_company(cid, other_agent_id)
        detail = service.get_company_detail(cid)
        assert detail["company"]["id"] == cid
        assert len(detail["members"]) == 2
        roles = {m["agent_id"]: m["role"] for m in detail["members"]}
        assert roles[founder_id] == CompanyRole.FOUNDER.value
        assert roles[other_agent_id] == CompanyRole.MEMBER.value

    def test_get_company_detail_not_found(self, service: CompanyService):
        """Getting detail for a non-existent company raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            service.get_company_detail("nonexistent")

    def test_join_company(self, service: CompanyService, founder_id: str, other_agent_id: str):
        """An agent can join an active company."""
        company = service.create_company("JoinCo", "", founder_id)
        member = service.join_company(company["id"], other_agent_id)
        assert member["company_id"] == company["id"]
        assert member["agent_id"] == other_agent_id
        assert member["role"] == CompanyRole.MEMBER.value

    def test_join_company_twice_raises(self, service: CompanyService, founder_id: str, other_agent_id: str):
        """Joining a company twice raises ValueError."""
        company = service.create_company("JoinCo2", "", founder_id)
        service.join_company(company["id"], other_agent_id)
        with pytest.raises(ValueError, match="already a member"):
            service.join_company(company["id"], other_agent_id)

    def test_join_dissolved_company_raises(self, service: CompanyService, founder_id: str, other_agent_id: str):
        """Joining a dissolved company raises ValueError."""
        company = service.create_company("DeadCo", "", founder_id)
        service.dissolve_company(company["id"], founder_id)
        with pytest.raises(ValueError, match="dissolved"):
            service.join_company(company["id"], other_agent_id)

    def test_leave_company(self, service: CompanyService, founder_id: str, other_agent_id: str):
        """A non-founder member can leave a company."""
        company = service.create_company("LeaveCo", "", founder_id)
        service.join_company(company["id"], other_agent_id)
        result = service.leave_company(company["id"], other_agent_id)
        assert result["action"] == "left"
        assert result["agent_id"] == other_agent_id
        # Agent should no longer see this company in their list
        agent_companies = service.get_agent_companies(other_agent_id)
        assert len(agent_companies) == 0

    def test_leave_company_as_founder_raises(self, service: CompanyService, founder_id: str):
        """The founder cannot leave the company."""
        company = service.create_company("FounderCo", "", founder_id)
        with pytest.raises(ValueError, match="Founder.*cannot leave"):
            service.leave_company(company["id"], founder_id)

    def test_leave_company_non_member_raises(self, service: CompanyService, founder_id: str, other_agent_id: str):
        """A non-member cannot leave a company."""
        company = service.create_company("NonMemberCo", "", founder_id)
        with pytest.raises(ValueError, match="not a member"):
            service.leave_company(company["id"], other_agent_id)

    def test_dissolve_company(self, service: CompanyService, founder_id: str):
        """The founder can dissolve their company."""
        company = service.create_company("DissolveCo", "", founder_id)
        result = service.dissolve_company(company["id"], founder_id)
        assert result["status"] == CompanyStatus.DISSOLVED.value
        # Verify via detail
        detail = service.get_company_detail(company["id"])
        assert detail["company"]["status"] == CompanyStatus.DISSOLVED.value

    def test_dissolve_company_by_non_founder_raises(self, service: CompanyService, founder_id: str, other_agent_id: str):
        """Only the founder can dissolve a company."""
        company = service.create_company("ProtectCo", "", founder_id)
        with pytest.raises(ValueError, match="not the founder"):
            service.dissolve_company(company["id"], other_agent_id)

    def test_dissolve_already_dissolved_raises(self, service: CompanyService, founder_id: str):
        """Dissolving an already-dissolved company raises ValueError."""
        company = service.create_company("DeadAgain", "", founder_id)
        service.dissolve_company(company["id"], founder_id)
        with pytest.raises(ValueError, match="already dissolved"):
            service.dissolve_company(company["id"], founder_id)

    def test_dissolve_nonexistent_company_raises(self, service: CompanyService, founder_id: str):
        """Dissolving a non-existent company raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            service.dissolve_company("phantom", founder_id)

    def test_get_agent_companies(self, service: CompanyService, founder_id: str, other_agent_id: str):
        """An agent can list all companies they belong to."""
        co1 = service.create_company("FirstCo", "", founder_id)
        co2 = service.create_company("SecondCo", "", founder_id)
        co3 = service.create_company("ThirdCo", "", uuid.uuid4().hex)
        service.join_company(co3["id"], founder_id)  # join as member
        service.join_company(co1["id"], other_agent_id)
        service.join_company(co2["id"], other_agent_id)

        founder_companies = service.get_agent_companies(founder_id)
        assert len(founder_companies) == 3  # founded 2 + joined 1
        other_companies = service.get_agent_companies(other_agent_id)
        assert len(other_companies) == 2

    def test_get_agent_companies_empty(self, service: CompanyService, other_agent_id: str):
        """An agent with no memberships gets an empty list."""
        assert service.get_agent_companies(other_agent_id) == []

    def test_create_company_uuid_uniqueness(self, service: CompanyService, founder_id: str):
        """Each created company gets a unique ID (UUID hex)."""
        c1 = service.create_company("C1", "", founder_id)
        c2 = service.create_company("C2", "", founder_id)
        assert c1["id"] != c2["id"]
