"""Tests for Governance Voting Module (Phase 34, Module C).

Covers Proposal, Vote, VoteResult models, GovernanceRepository, and
GovernanceService with at least 20 test cases.

Uses an in-memory SQLite database with the full schema (companies,
company_members, equity_shares, proposals, votes) for each test.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from governance.models import (
    Decision,
    Proposal,
    ProposalStatus,
    ProposalType,
    Vote,
    VoteResult,
)
from governance.repository import GovernanceRepository
from governance.service import GovernanceError, GovernanceService

# ====================================================================
# Fixtures
# ====================================================================

_COMPANY_SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    founder_id      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','frozen','dissolved')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS company_members (
    company_id      TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member',
    joined_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (company_id, agent_id)
);
CREATE TABLE IF NOT EXISTS equity_shares (
    id              TEXT PRIMARY KEY,
    company_id      TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    shares          INTEGER NOT NULL CHECK(shares > 0),
    share_class     TEXT NOT NULL DEFAULT 'common'
                    CHECK(share_class IN ('founder', 'common', 'preferred')),
    issued_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(company_id, agent_id, share_class)
);
"""


def _iso(days_offset: int = 0) -> str:
    """Return ISO-8601 timestamp offset from now."""
    dt = datetime.now(timezone.utc) + timedelta(days=days_offset)
    return dt.isoformat()


def _past_iso(minutes_ago: int = 10) -> str:
    """Return ISO-8601 timestamp in the past."""
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return dt.isoformat()


@pytest.fixture
def db() -> sqlite3.Connection:
    """An in-memory SQLite database with all required tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_COMPANY_SCHEMA)
    # Governance tables are created by GovernanceRepository
    return conn


@pytest.fixture
def repo(db: sqlite3.Connection) -> GovernanceRepository:
    """A GovernanceRepository backed by the in-memory DB."""
    return GovernanceRepository(db)


@pytest.fixture
def svc(db: sqlite3.Connection) -> GovernanceService:
    """A GovernanceService backed by the in-memory DB."""
    return GovernanceService(GovernanceRepository(db))


@pytest.fixture
def company_id(db: sqlite3.Connection) -> str:
    """Create a sample company and return its ID."""
    cid = uuid.uuid4().hex
    db.execute(
        "INSERT INTO companies (id, name, description, founder_id) VALUES (?, ?, ?, ?)",
        (cid, "TestCo", "A test company", "founder_a"),
    )
    db.commit()
    return cid


@pytest.fixture
def founder_id() -> str:
    return "founder_a"


@pytest.fixture
def member_id_a() -> str:
    return "member_a"


@pytest.fixture
def member_id_b() -> str:
    return "member_b"


@pytest.fixture
def non_member_id() -> str:
    return "non_member"


@pytest.fixture
def populated_company(
    db: sqlite3.Connection,
    company_id: str,
    founder_id: str,
    member_id_a: str,
    member_id_b: str,
) -> str:
    """Create a company with founder and 2 members, all with equity."""
    # Add members
    for aid, role in [(founder_id, "founder"), (member_id_a, "member"), (member_id_b, "member")]:
        db.execute(
            "INSERT INTO company_members (company_id, agent_id, role) VALUES (?, ?, ?)",
            (company_id, aid, role),
        )
    # Issue equity
    for aid, shares, cls in [
        (founder_id, 500, "founder"),
        (member_id_a, 200, "common"),
        (member_id_b, 200, "common"),
    ]:
        db.execute(
            "INSERT INTO equity_shares (id, company_id, agent_id, shares, share_class) VALUES (?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, company_id, aid, shares, cls),
        )
    db.commit()
    return company_id


# ====================================================================
# Tests: Models
# ====================================================================

class TestProposalModel:
    def test_proposal_create_minimal(self):
        """Proposal can be created with required fields."""
        p = Proposal(
            id="p1",
            company_id="c1",
            title="Test Proposal",
            proposer_id="agent_a",
            voting_start=_iso(0),
            voting_end=_iso(7),
        )
        assert p.title == "Test Proposal"
        assert p.proposal_type == ProposalType.ORDINARY
        assert p.status == ProposalStatus.PENDING
        assert p.quorum == 0.3
        assert p.pass_threshold == 0.5

    def test_proposal_auto_timestamp(self):
        """Proposal gets a created_at timestamp on construction."""
        p = Proposal(
            id="p2",
            company_id="c1",
            title="Auto Timestamp",
            proposer_id="agent_a",
            voting_start=_iso(0),
            voting_end=_iso(7),
        )
        assert p.created_at is not None
        assert "T" in p.created_at

    def test_proposal_type_enum(self):
        """Proposal type must be a valid ProposalType value."""
        p = Proposal(
            id="p3",
            company_id="c1",
            title="Special",
            proposer_id="agent_a",
            proposal_type=ProposalType.SPECIAL,
            voting_start=_iso(0),
            voting_end=_iso(7),
        )
        assert p.proposal_type == ProposalType.SPECIAL
        assert p.pass_threshold == 0.5  # default, overridden in service


class TestVoteModel:
    def test_vote_create(self):
        """Vote can be created with valid fields."""
        v = Vote(
            id="v1",
            proposal_id="p1",
            voter_id="agent_a",
            voting_power=100.0,
            decision=Decision.FOR,
        )
        assert v.decision == Decision.FOR
        assert v.voting_power == 100.0
        assert v.cast_at is not None

    def test_vote_decision_enum(self):
        """Vote decision must be a valid Decision value."""
        v = Vote(
            id="v2",
            proposal_id="p1",
            voter_id="agent_b",
            voting_power=50.0,
            decision=Decision.AGAINST,
            reason="Disagree",
        )
        assert v.decision == Decision.AGAINST
        assert v.reason == "Disagree"


class TestVoteResult:
    def test_vote_result_dataclass(self):
        """VoteResult is a simple dataclass with all fields."""
        r = VoteResult(
            proposal_id="p1",
            total_voting_power=1000.0,
            cast_power=800.0,
            for_power=600.0,
            against_power=150.0,
            abstain_power=50.0,
            quorum_met=True,
            passed=True,
        )
        assert r.proposal_id == "p1"
        assert r.passed is True
        assert r.quorum_met is True


# ====================================================================
# Tests: Repository
# ====================================================================

class TestGovernanceRepository:
    def test_create_and_get_proposal(self, repo: GovernanceRepository):
        """Creating a proposal and retrieving it by ID returns the same data."""
        p = Proposal(
            id="p1", company_id="c1", title="Repo Test", proposer_id="a1",
            voting_start=_iso(0), voting_end=_iso(7),
        )
        repo.create_proposal(p)
        fetched = repo.get_proposal("p1")
        assert fetched is not None
        assert fetched.title == "Repo Test"
        assert fetched.id == "p1"
        assert fetched.proposal_type == ProposalType.ORDINARY

    def test_get_proposal_not_found(self, repo: GovernanceRepository):
        """Getting a non-existent proposal returns None."""
        assert repo.get_proposal("nonexistent") is None

    def test_list_proposals_empty(self, repo: GovernanceRepository):
        """An empty repository returns an empty list."""
        assert repo.list_proposals() == []

    def test_list_proposals_by_company(self, repo: GovernanceRepository):
        """List proposals filtered by company."""
        for i, cid in enumerate(["c1", "c1", "c2"]):
            repo.create_proposal(Proposal(
                id=f"p{i}", company_id=cid, title=f"P{i}", proposer_id="a1",
                voting_start=_iso(0), voting_end=_iso(7),
            ))
        c1_proposals = repo.list_proposals(company_id="c1")
        assert len(c1_proposals) == 2

    def test_list_proposals_by_status(self, repo: GovernanceRepository):
        """List proposals filtered by status."""
        p1 = Proposal(
            id="p1", company_id="c1", title="Active P", proposer_id="a1",
            voting_start=_iso(0), voting_end=_iso(7),
            status=ProposalStatus.ACTIVE,
        )
        p2 = Proposal(
            id="p2", company_id="c1", title="Pending P", proposer_id="a1",
            voting_start=_iso(1), voting_end=_iso(8),
            status=ProposalStatus.PENDING,
        )
        repo.create_proposal(p1)
        repo.create_proposal(p2)
        active = repo.list_proposals(status=ProposalStatus.ACTIVE)
        assert len(active) == 1
        assert active[0].id == "p1"

    def test_update_proposal_status(self, repo: GovernanceRepository):
        """Updating a proposal's status persists the change."""
        p = Proposal(
            id="p1", company_id="c1", title="Update", proposer_id="a1",
            voting_start=_iso(0), voting_end=_iso(7),
        )
        repo.create_proposal(p)
        updated = repo.update_proposal_status("p1", ProposalStatus.ACTIVE)
        assert updated is not None
        assert updated.status == ProposalStatus.ACTIVE
        fetched = repo.get_proposal("p1")
        assert fetched.status == ProposalStatus.ACTIVE

    def test_update_proposal_not_found(self, repo: GovernanceRepository):
        """Updating status on a non-existent proposal returns None."""
        result = repo.update_proposal_status("ghost", ProposalStatus.ACTIVE)
        assert result is None

    def test_cast_and_get_vote(self, repo: GovernanceRepository):
        """Casting a vote and retrieving it."""
        p = Proposal(
            id="p1", company_id="c1", title="Vote Test", proposer_id="a1",
            voting_start=_iso(0), voting_end=_iso(7),
            status=ProposalStatus.ACTIVE,
        )
        repo.create_proposal(p)
        v = Vote(
            id="v1", proposal_id="p1", voter_id="a1", voting_power=100.0,
            decision=Decision.FOR,
        )
        repo.cast_vote(v)
        fetched = repo.get_vote("v1")
        assert fetched is not None
        assert fetched.decision == Decision.FOR
        assert fetched.voting_power == 100.0

    def test_get_votes_for_proposal(self, repo: GovernanceRepository):
        """Return all votes for a proposal."""
        p = Proposal(
            id="p1", company_id="c1", title="Multi Vote", proposer_id="a1",
            voting_start=_iso(0), voting_end=_iso(7),
            status=ProposalStatus.ACTIVE,
        )
        repo.create_proposal(p)
        for i, voter in enumerate(["a1", "a2", "a3"]):
            repo.cast_vote(Vote(
                id=f"v{i}", proposal_id="p1", voter_id=voter,
                voting_power=50.0, decision=Decision.FOR,
            ))
        votes = repo.get_votes_for_proposal("p1")
        assert len(votes) == 3

    def test_get_vote_by_voter(self, repo: GovernanceRepository):
        """Check if a voter has already voted."""
        p = Proposal(
            id="p1", company_id="c1", title="Dup Check", proposer_id="a1",
            voting_start=_iso(0), voting_end=_iso(7),
            status=ProposalStatus.ACTIVE,
        )
        repo.create_proposal(p)
        assert repo.get_vote_by_voter("p1", "a1") is None
        repo.cast_vote(Vote(
            id="v1", proposal_id="p1", voter_id="a1",
            voting_power=50.0, decision=Decision.FOR,
        ))
        assert repo.get_vote_by_voter("p1", "a1") is not None


# ====================================================================
# Tests: Service
# ====================================================================

class TestGovernanceService:
    def test_create_proposal(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
    ):
        """A company member can create a proposal."""
        result = svc.create_proposal(
            company_id=populated_company,
            title="Test Proposal",
            description="A proposal for testing",
            proposal_type=ProposalType.ORDINARY,
            proposer_id=founder_id,
            voting_end=_iso(7),
        )
        assert result["title"] == "Test Proposal"
        assert result["company_id"] == populated_company
        assert result["status"] == ProposalStatus.PENDING.value
        assert result["proposal_type"] == ProposalType.ORDINARY.value

    def test_create_proposal_empty_title_raises(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
    ):
        """Creating a proposal with empty title raises GovernanceError."""
        with pytest.raises(GovernanceError, match="title must not be empty"):
            svc.create_proposal(
                company_id=populated_company, title="", description="desc",
                proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
                voting_end=_iso(7),
            )

    def test_create_proposal_non_member_raises(
        self, svc: GovernanceService, populated_company: str, non_member_id: str,
    ):
        """Creating a proposal as a non-member raises GovernanceError."""
        with pytest.raises(GovernanceError, match="not a member"):
            svc.create_proposal(
                company_id=populated_company, title="Bad", description="desc",
                proposal_type=ProposalType.ORDINARY, proposer_id=non_member_id,
                voting_end=_iso(7),
            )

    def test_create_proposal_voting_end_before_start_raises(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
    ):
        """Creating a proposal with voting_end before voting_start raises error."""
        with pytest.raises(GovernanceError, match="voting_end must be after"):
            svc.create_proposal(
                company_id=populated_company, title="Bad Time", description="desc",
                proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
                voting_start=_iso(7), voting_end=_iso(0),
            )

    def test_create_proposal_type_specific_defaults(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
    ):
        """Special proposals get default 66.7% pass_threshold and 50% quorum."""
        result = svc.create_proposal(
            company_id=populated_company, title="Special Resolution",
            description="Amend charter",
            proposal_type=ProposalType.SPECIAL,
            proposer_id=founder_id,
            voting_end=_iso(7),
        )
        assert result["proposal_type"] == ProposalType.SPECIAL.value
        assert result["pass_threshold"] == pytest.approx(0.667, rel=1e-3)
        assert result["quorum"] == 0.5

    def test_get_proposal(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
    ):
        """Fetching an existing proposal returns its data."""
        created = svc.create_proposal(
            company_id=populated_company, title="Fetch Me", description="desc",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_end=_iso(7),
        )
        fetched = svc.get_proposal(created["id"])
        assert fetched["id"] == created["id"]
        assert fetched["title"] == "Fetch Me"

    def test_get_proposal_not_found_raises(self, svc: GovernanceService):
        """Fetching a non-existent proposal raises GovernanceError."""
        with pytest.raises(GovernanceError, match="not found"):
            svc.get_proposal("nonexistent")

    def test_list_proposals(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
    ):
        """Listing proposals returns all for a company."""
        svc.create_proposal(
            company_id=populated_company, title="P1", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_end=_iso(7),
        )
        svc.create_proposal(
            company_id=populated_company, title="P2", description="",
            proposal_type=ProposalType.SPECIAL, proposer_id=founder_id,
            voting_end=_iso(7),
        )
        proposals = svc.list_proposals(company_id=populated_company)
        assert len(proposals) == 2

    def test_cast_vote(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
        member_id_a: str,
    ):
        """A member can cast a vote on an active proposal."""
        # Create a proposal with voting_start in the past
        proposal = svc.create_proposal(
            company_id=populated_company, title="Vote On Me", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_start=_past_iso(10),
            voting_end=_iso(7),
        )
        vote = svc.cast_vote(
            proposal_id=proposal["id"],
            voter_id=member_id_a,
            decision=Decision.FOR,
            reason="I support this",
        )
        assert vote["proposal_id"] == proposal["id"]
        assert vote["voter_id"] == member_id_a
        assert vote["decision"] == Decision.FOR.value
        assert vote["voting_power"] == 200.0  # member_a has 200 shares

    def test_cast_vote_non_member_raises(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
        non_member_id: str,
    ):
        """A non-member cannot vote."""
        proposal = svc.create_proposal(
            company_id=populated_company, title="Protected", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_start=_past_iso(10),
            voting_end=_iso(7),
        )
        with pytest.raises(GovernanceError, match="not a member"):
            svc.cast_vote(
                proposal_id=proposal["id"],
                voter_id=non_member_id,
                decision=Decision.FOR,
            )

    def test_cast_vote_twice_raises(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
        member_id_a: str,
    ):
        """A voter cannot vote twice on the same proposal."""
        proposal = svc.create_proposal(
            company_id=populated_company, title="One Vote", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_start=_past_iso(10),
            voting_end=_iso(7),
        )
        svc.cast_vote(proposal["id"], member_id_a, Decision.FOR)
        with pytest.raises(GovernanceError, match="already voted"):
            svc.cast_vote(proposal["id"], member_id_a, Decision.AGAINST)

    def test_cast_vote_on_expired_proposal_raises(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
        member_id_a: str,
    ):
        """Voting on an expired proposal raises GovernanceError."""
        proposal = svc.create_proposal(
            company_id=populated_company, title="Expired", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_start=_past_iso(10),
            voting_end=_past_iso(1),  # ended 1 minute ago
        )
        with pytest.raises(GovernanceError, match="expired, not active"):
            svc.cast_vote(proposal["id"], member_id_a, Decision.FOR)

    def test_get_results_quorum_not_met(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
        member_id_a: str,
    ):
        """Results reflect quorum not met when insufficient voting power."""
        # Total equity = 500 + 200 + 200 = 900
        # quorum = 0.3, so need 270 shares
        # Only member_a votes with 200 shares < 270
        proposal = svc.create_proposal(
            company_id=populated_company, title="Quorum Test", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_start=_past_iso(10),
            voting_end=_iso(7),
            quorum=0.3,
        )
        svc.cast_vote(proposal["id"], member_id_a, Decision.FOR)
        result = svc.get_results(proposal["id"])
        assert result.total_voting_power == 900.0
        assert result.cast_power == 200.0
        assert result.quorum_met is False
        assert result.passed is False

    def test_get_results_passed(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
        member_id_a: str, member_id_b: str,
    ):
        """Results correctly show passed when conditions are met."""
        # Total = 900, quorum = 0.3, need 270 shares
        # Founder (500) + member_a (200) = 700 cast => quorum met
        # for_power = 700, cast_power = 700 => 100% for => pass_threshold 50% met
        proposal = svc.create_proposal(
            company_id=populated_company, title="Pass Test", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_start=_past_iso(10),
            voting_end=_iso(7),
        )
        svc.cast_vote(proposal["id"], founder_id, Decision.FOR)
        svc.cast_vote(proposal["id"], member_id_a, Decision.FOR)
        result = svc.get_results(proposal["id"])
        assert result.quorum_met is True
        assert result.passed is True
        assert result.for_power == 700.0

    def test_get_results_rejected(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
        member_id_a: str, member_id_b: str,
    ):
        """Results correctly show rejected when majority votes against."""
        proposal = svc.create_proposal(
            company_id=populated_company, title="Reject Test", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_start=_past_iso(10),
            voting_end=_iso(7),
        )
        # Founder votes against (500), member_a votes for (200)
        svc.cast_vote(proposal["id"], founder_id, Decision.AGAINST)
        svc.cast_vote(proposal["id"], member_id_a, Decision.FOR)
        result = svc.get_results(proposal["id"])
        assert result.quorum_met is True
        assert result.passed is False
        assert result.for_power == 200.0
        assert result.against_power == 500.0

    def test_get_results_with_abstain(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
        member_id_a: str, member_id_b: str,
    ):
        """Abstain votes count toward quorum but not toward pass threshold."""
        proposal = svc.create_proposal(
            company_id=populated_company, title="Abstain Test", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_start=_past_iso(10),
            voting_end=_iso(7),
        )
        # Founder abstains (500), member_a votes for (200), member_b against (200)
        svc.cast_vote(proposal["id"], founder_id, Decision.ABSTAIN)
        svc.cast_vote(proposal["id"], member_id_a, Decision.FOR)
        svc.cast_vote(proposal["id"], member_id_b, Decision.AGAINST)
        result = svc.get_results(proposal["id"])
        assert result.cast_power == 900.0  # all 3 voted
        assert result.quorum_met is True
        # for_power=200, cast_power=900, abstain excluded from pass calculation
        # pass_threshold = 0.5, so pass requires 50% of cast (excluding abstain) to be for
        # for_power / (for_power + against_power) = 200/400 = 0.5 >= 0.5 => passes
        assert result.passed is True
        assert result.abstain_power == 500.0

    def test_execute_ordinary_proposal(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
        member_id_a: str,
    ):
        """An ordinary proposal that passed can be executed."""
        proposal = svc.create_proposal(
            company_id=populated_company, title="Exec Test", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_start=_past_iso(10),
            voting_end=_iso(7),
        )
        svc.cast_vote(proposal["id"], founder_id, Decision.FOR)
        svc.cast_vote(proposal["id"], member_id_a, Decision.FOR)
        result = svc.get_results(proposal["id"])
        assert result.passed is True

        executed = svc.execute_proposal(proposal["id"])
        assert executed["status"] == ProposalStatus.EXECUTED.value
        assert executed["executed_at"] is not None
        assert executed["execution_result"] is not None

    def test_execute_non_passed_proposal_raises(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
    ):
        """Executing a proposal that hasn't passed raises GovernanceError."""
        proposal = svc.create_proposal(
            company_id=populated_company, title="No Exec", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_start=_past_iso(10),
            voting_end=_iso(7),
        )
        with pytest.raises(GovernanceError, match="only.*passed.*can be executed"):
            svc.execute_proposal(proposal["id"])

    def test_execute_special_proposal(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
        member_id_a: str, member_id_b: str,
    ):
        """A special proposal execution records company freeze action."""
        proposal = svc.create_proposal(
            company_id=populated_company, title="Special Exec", description="",
            proposal_type=ProposalType.SPECIAL, proposer_id=founder_id,
            voting_start=_past_iso(10),
            voting_end=_iso(7),
        )
        # Need 60% for special: threshold = 0.667
        # Founder (500) + member_a (200) = 700 out of 900 = 77.7% cast, meets quorum 50%
        # for_power = 700, cast_power = 700 => 100% for, meets 66.7%
        svc.cast_vote(proposal["id"], founder_id, Decision.FOR)
        svc.cast_vote(proposal["id"], member_id_a, Decision.FOR)
        result = svc.get_results(proposal["id"])
        assert result.passed is True

        executed = svc.execute_proposal(proposal["id"])
        assert executed["status"] == ProposalStatus.EXECUTED.value
        exec_result = json.loads(executed["execution_result"])
        assert exec_result["action"] == "company_frozen"

    def test_cancel_proposal(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
    ):
        """The proposer can cancel their own pending proposal."""
        proposal = svc.create_proposal(
            company_id=populated_company, title="Cancel Me", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_end=_iso(7),
        )
        cancelled = svc.cancel_proposal(proposal["id"], founder_id)
        assert cancelled["status"] == ProposalStatus.CANCELLED.value

    def test_cancel_proposal_by_non_proposer_raises(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
        member_id_a: str,
    ):
        """Only the proposer can cancel a proposal."""
        proposal = svc.create_proposal(
            company_id=populated_company, title="Mine", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_end=_iso(7),
        )
        with pytest.raises(GovernanceError, match="not the proposer"):
            svc.cancel_proposal(proposal["id"], member_id_a)

    def test_cancel_already_executed_proposal_raises(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
        member_id_a: str,
    ):
        """An executed proposal cannot be cancelled."""
        proposal = svc.create_proposal(
            company_id=populated_company, title="Done Deal", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_start=_past_iso(10),
            voting_end=_iso(7),
        )
        svc.cast_vote(proposal["id"], founder_id, Decision.FOR)
        svc.cast_vote(proposal["id"], member_id_a, Decision.FOR)
        svc.get_results(proposal["id"])
        svc.execute_proposal(proposal["id"])
        with pytest.raises(GovernanceError, match="cannot be cancelled"):
            svc.cancel_proposal(proposal["id"], founder_id)

    def test_proposal_auto_activate_on_vote(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
        member_id_a: str,
    ):
        """A pending proposal auto-activates when someone votes on it after voting_start."""
        proposal = svc.create_proposal(
            company_id=populated_company, title="Auto Activate", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_start=_past_iso(10),  # started 10 minutes ago
            voting_end=_iso(7),
        )
        # The proposal is created as PENDING
        assert svc.get_proposal(proposal["id"])["status"] == ProposalStatus.PENDING.value
        # Voting auto-activates it
        svc.cast_vote(proposal["id"], member_id_a, Decision.FOR)
        fetched = svc.get_proposal(proposal["id"])
        assert fetched["status"] == ProposalStatus.ACTIVE.value

    def test_membership_proposal_execution(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
        member_id_a: str,
    ):
        """A membership proposal execution returns the correct action."""
        proposal = svc.create_proposal(
            company_id=populated_company, title="Add Member", description="",
            proposal_type=ProposalType.MEMBERSHIP, proposer_id=founder_id,
            voting_start=_past_iso(10),
            voting_end=_iso(7),
        )
        svc.cast_vote(proposal["id"], founder_id, Decision.FOR)
        svc.cast_vote(proposal["id"], member_id_a, Decision.FOR)
        svc.get_results(proposal["id"])
        executed = svc.execute_proposal(proposal["id"])
        exec_result = json.loads(executed["execution_result"])
        assert exec_result["action"] == "requires_membership_change"

    def test_dividend_proposal_execution(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
        member_id_a: str,
    ):
        """A dividend proposal execution returns the correct action."""
        proposal = svc.create_proposal(
            company_id=populated_company, title="Distribute", description="",
            proposal_type=ProposalType.DIVIDEND, proposer_id=founder_id,
            voting_start=_past_iso(10),
            voting_end=_iso(7),
        )
        svc.cast_vote(proposal["id"], founder_id, Decision.FOR)
        svc.cast_vote(proposal["id"], member_id_a, Decision.FOR)
        svc.get_results(proposal["id"])
        executed = svc.execute_proposal(proposal["id"])
        exec_result = json.loads(executed["execution_result"])
        assert exec_result["action"] == "requires_dividend_service"

    def test_equity_snapshot_at_vote_time(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
        member_id_a: str, db: sqlite3.Connection,
    ):
        """Voting power is snapshotted from equity at vote time."""
        proposal = svc.create_proposal(
            company_id=populated_company, title="Snapshot Test", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_start=_past_iso(10),
            voting_end=_iso(7),
        )
        vote = svc.cast_vote(proposal["id"], member_id_a, Decision.FOR)
        assert vote["voting_power"] == 200.0

        # Change equity after vote
        db.execute(
            "UPDATE equity_shares SET shares = 999 WHERE company_id = ? AND agent_id = ? AND share_class = 'common'",
            (populated_company, member_id_a),
        )
        db.commit()

        # The original vote should still show 200
        fetched_vote = svc._repo.get_vote(vote["id"])
        assert fetched_vote.voting_power == 200.0

    def test_create_proposal_custom_thresholds(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
    ):
        """Custom quorum and pass_threshold are respected."""
        result = svc.create_proposal(
            company_id=populated_company, title="Custom", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_end=_iso(7),
            quorum=0.5,
            pass_threshold=0.75,
        )
        assert result["quorum"] == 0.5
        assert result["pass_threshold"] == 0.75

    def test_list_proposals_no_filter(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
    ):
        """List all proposals without any filter."""
        svc.create_proposal(
            company_id=populated_company, title="Global1", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_end=_iso(7),
        )
        svc.create_proposal(
            company_id=populated_company, title="Global2", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_end=_iso(7),
        )
        all_props = svc.list_proposals()
        assert len(all_props) == 2

    def test_auto_expire_on_get_results(
        self, svc: GovernanceService, populated_company: str, founder_id: str,
    ):
        """Proposals past voting_end are auto-expired when results are tallied."""
        proposal = svc.create_proposal(
            company_id=populated_company, title="Expire Me", description="",
            proposal_type=ProposalType.ORDINARY, proposer_id=founder_id,
            voting_start=_past_iso(10),
            voting_end=_past_iso(1),  # ended 1 minute ago
        )
        result = svc.get_results(proposal["id"])
        fetched = svc.get_proposal(proposal["id"])
        assert fetched["status"] == ProposalStatus.EXPIRED.value or fetched["status"] == ProposalStatus.REJECTED.value
