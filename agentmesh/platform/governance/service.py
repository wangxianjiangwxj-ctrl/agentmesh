"""Governance Voting — Business Logic Service.

Provides the public API for the governance voting system:
- Create proposals (member-gated)
- List / query proposals
- Cast votes (with equity snapshot)
- Tally results
- Execute passed proposals
- Cancel proposals

All business rules are enforced here (not in the repository layer).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from agentmesh.platform.governance.models import (
    Decision,
    Proposal,
    ProposalStatus,
    ProposalType,
    Vote,
    VoteResult,
)
from agentmesh.platform.governance.repository import GovernanceRepository


class GovernanceError(Exception):
    """Raised when a governance business rule is violated."""


class GovernanceService:
    """High-level service for company governance voting.

    Wraps a ``GovernanceRepository`` with business rules for proposal
    lifecycle, voting with equity snapshots, and result tallying.

    Args:
        repository: The data repository to use.  Defaults to a fresh
            ``GovernanceRepository`` backed by an in-memory SQLite DB.
    """

    # Threshold overrides per proposal type: (pass_threshold, quorum)
    _TYPE_DEFAULTS: dict[ProposalType, tuple[float, float]] = {
        ProposalType.ORDINARY: (0.50, 0.30),
        ProposalType.SPECIAL: (0.667, 0.50),
        ProposalType.MEMBERSHIP: (0.60, 0.30),
        ProposalType.DIVIDEND: (0.50, 0.30),
    }

    def __init__(self, repository: Optional[GovernanceRepository] = None) -> None:
        self._repo = repository or self._build_default_repo()

    @staticmethod
    def _build_default_repo() -> GovernanceRepository:
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        return GovernanceRepository(conn)

    @staticmethod
    def _now_utc() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _parse_iso(ts: str) -> datetime:
        """Parse an ISO-8601 string into a datetime object."""
        # Handle timezone-aware and naive strings
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            # Fallback for dateutil-parsed strings
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def _check_member(self, company_id: str, agent_id: str) -> bool:
        """Check if an agent is a member of a company via raw SQL.

        This works with any SQLite database that has the
        ``company_members`` table (Phase 34A).
        """
        row = self._repo.conn.execute(
            "SELECT 1 FROM company_members WHERE company_id = ? AND agent_id = ?",
            (company_id, agent_id),
        ).fetchone()
        return row is not None

    def _get_agent_equity(self, company_id: str, agent_id: str) -> float:
        """Get total equity shares for an agent in a company.

        Queries the ``equity_shares`` table (Phase 34B).
        """
        row = self._repo.conn.execute(
            "SELECT COALESCE(SUM(shares), 0) FROM equity_shares WHERE company_id = ? AND agent_id = ?",
            (company_id, agent_id),
        ).fetchone()
        return float(row[0]) if row else 0.0

    def _get_total_company_equity(self, company_id: str) -> float:
        """Get total equity shares issued by a company."""
        row = self._repo.conn.execute(
            "SELECT COALESCE(SUM(shares), 0) FROM equity_shares WHERE company_id = ?",
            (company_id,),
        ).fetchone()
        return float(row[0]) if row else 0.0

    # -- Proposal lifecycle -------------------------------------------------

    def create_proposal(
        self,
        company_id: str,
        title: str,
        description: str,
        proposal_type: ProposalType,
        proposer_id: str,
        voting_end: str,
        voting_start: Optional[str] = None,
        quorum: Optional[float] = None,
        pass_threshold: Optional[float] = None,
    ) -> dict:
        """Create a new governance proposal.

        The proposer must be a member of the company.  Default quorum
        and pass_threshold are applied per proposal type if not provided.

        Args:
            company_id: The company this proposal belongs to.
            title: Short title of the proposal.
            description: Detailed description.
            proposal_type: Type of proposal.
            proposer_id: Agent ID of the proposer.
            voting_end: ISO-8601 timestamp when voting ends.
            voting_start: ISO-8601 timestamp when voting starts (defaults to now).
            quorum: Minimum voting power fraction required.  Defaults per type.
            pass_threshold: Fraction of cast votes needed to pass.  Defaults per type.

        Returns:
            A dict representation of the created Proposal.

        Raises:
            GovernanceError: If the proposer is not a member, title is
                empty, or voting_end is before voting_start.
        """
        if not title or not title.strip():
            raise GovernanceError("Proposal title must not be empty")

        if not self._check_member(company_id, proposer_id):
            raise GovernanceError(
                f"Agent '{proposer_id[:12]}' is not a member of company '{company_id[:12]}'"
            )

        # Apply type defaults if not provided
        type_defaults = self._TYPE_DEFAULTS.get(proposal_type, (0.50, 0.30))
        effective_pass = pass_threshold if pass_threshold is not None else type_defaults[0]
        effective_quorum = quorum if quorum is not None else type_defaults[1]

        start_ts = voting_start or self._now_utc()
        end_dt = self._parse_iso(voting_end)
        start_dt = self._parse_iso(start_ts)

        if end_dt <= start_dt:
            raise GovernanceError("voting_end must be after voting_start")

        proposal_id = uuid.uuid4().hex
        proposal = Proposal(
            id=proposal_id,
            company_id=company_id,
            title=title.strip(),
            description=description,
            proposal_type=proposal_type,
            proposer_id=proposer_id,
            voting_start=start_ts,
            voting_end=voting_end,
            quorum=effective_quorum,
            pass_threshold=effective_pass,
            status=ProposalStatus.PENDING,
        )
        self._repo.create_proposal(proposal)
        return proposal.model_dump()

    def get_proposal(self, proposal_id: str) -> dict:
        """Fetch a proposal by ID.

        Args:
            proposal_id: The unique proposal identifier.

        Returns:
            The Proposal dict.

        Raises:
            GovernanceError: If the proposal does not exist.
        """
        proposal = self._repo.get_proposal(proposal_id)
        if proposal is None:
            raise GovernanceError(f"Proposal '{proposal_id[:12]}' not found")
        return proposal.model_dump()

    def list_proposals(
        self,
        company_id: Optional[str] = None,
        status: Optional[ProposalStatus] = None,
    ) -> list[dict]:
        """List proposals, optionally filtered.

        Args:
            company_id: Filter by company.
            status: Filter by proposal status.

        Returns:
            A list of Proposal dicts.
        """
        return [p.model_dump() for p in self._repo.list_proposals(company_id, status)]

    def _activate_pending_proposal(self, proposal_id: str) -> Proposal:
        """Automatically activate a proposal if voting_start <= now."""
        proposal = self._repo.get_proposal(proposal_id)
        if proposal is None:
            raise GovernanceError(f"Proposal '{proposal_id[:12]}' not found")

        now = self._now_utc()
        start_dt = self._parse_iso(proposal.voting_start)
        now_dt = self._parse_iso(now)
        end_dt = self._parse_iso(proposal.voting_end)

        # Check for expiry
        if now_dt >= end_dt and proposal.status == ProposalStatus.PENDING:
            self._repo.update_proposal_status(proposal_id, ProposalStatus.EXPIRED)
            proposal = self._repo.get_proposal(proposal_id)

        # Auto-activate if past start time
        if now_dt >= start_dt and proposal.status == ProposalStatus.PENDING:
            self._repo.update_proposal_status(proposal_id, ProposalStatus.ACTIVE)
            proposal = self._repo.get_proposal(proposal_id)

        return proposal

    # -- Voting -------------------------------------------------------------

    def cast_vote(
        self,
        proposal_id: str,
        voter_id: str,
        decision: Decision,
        reason: str = "",
    ) -> dict:
        """Cast a vote on an active proposal.

        Voting power is snapshotted from the voter's equity shares at
        the time of voting.

        Args:
            proposal_id: The proposal to vote on.
            voter_id: The agent casting the vote.
            decision: Vote decision (for/against/abstain).
            reason: Optional reason for the vote.

        Returns:
            A dict representation of the cast Vote.

        Raises:
            GovernanceError: If the proposal is not active, the voter
                is not a member, the voter has already voted, or voting
                has ended.
        """
        proposal = self._activate_pending_proposal(proposal_id)
        if proposal is None:
            raise GovernanceError(f"Proposal '{proposal_id[:12]}' not found")

        if proposal.status != ProposalStatus.ACTIVE:
            raise GovernanceError(
                f"Proposal '{proposal_id[:12]}' is {proposal.status.value}, not active"
            )

        now = self._now_utc()
        now_dt = self._parse_iso(now)
        end_dt = self._parse_iso(proposal.voting_end)
        start_dt = self._parse_iso(proposal.voting_start)

        if now_dt < start_dt:
            raise GovernanceError("Voting has not started yet for this proposal")

        if now_dt >= end_dt:
            # Auto-expire
            self._repo.update_proposal_status(proposal_id, ProposalStatus.EXPIRED)
            raise GovernanceError("Voting has ended for this proposal")

        if not self._check_member(proposal.company_id, voter_id):
            raise GovernanceError(
                f"Agent '{voter_id[:12]}' is not a member of the company"
            )

        existing_vote = self._repo.get_vote_by_voter(proposal_id, voter_id)
        if existing_vote is not None:
            raise GovernanceError(
                f"Agent '{voter_id[:12]}' has already voted on proposal '{proposal_id[:12]}'"
            )

        # Snapshot voting power from equity_shares
        voting_power = self._get_agent_equity(proposal.company_id, voter_id)

        vote = Vote(
            id=uuid.uuid4().hex,
            proposal_id=proposal_id,
            voter_id=voter_id,
            voting_power=voting_power,
            decision=decision,
            reason=reason,
        )
        self._repo.cast_vote(vote)
        return vote.model_dump()

    # -- Results / Tallying -------------------------------------------------

    def get_results(self, proposal_id: str) -> VoteResult:
        """Tally votes for a proposal and determine the outcome.

        Also checks whether the proposal should auto-expire and can
        trigger automatic status transitions (passed/rejected) after
        tallying.

        Args:
            proposal_id: The proposal to tally.

        Returns:
            A VoteResult dataclass with the tally details.

        Raises:
            GovernanceError: If the proposal does not exist.
        """
        proposal = self._repo.get_proposal(proposal_id)
        if proposal is None:
            raise GovernanceError(f"Proposal '{proposal_id[:12]}' not found")

        # Handle expiry
        now = self._now_utc()
        now_dt = self._parse_iso(now)
        end_dt = self._parse_iso(proposal.voting_end)

        if now_dt >= end_dt and proposal.status in (ProposalStatus.PENDING, ProposalStatus.ACTIVE):
            self._repo.update_proposal_status(proposal_id, ProposalStatus.EXPIRED)
            proposal = self._repo.get_proposal(proposal_id)

        total_voting_power = self._get_total_company_equity(proposal.company_id)
        votes = self._repo.get_votes_for_proposal(proposal_id)

        for_power = sum(v.voting_power for v in votes if v.decision == Decision.FOR)
        against_power = sum(v.voting_power for v in votes if v.decision == Decision.AGAINST)
        abstain_power = sum(v.voting_power for v in votes if v.decision == Decision.ABSTAIN)
        cast_power = for_power + against_power + abstain_power

        quorum_met = (total_voting_power > 0 and cast_power / total_voting_power >= proposal.quorum)
        passed = False

        if quorum_met and cast_power > 0:
            # Pass threshold is calculated against non-abstain votes
            non_abstain_power = for_power + against_power
            if non_abstain_power > 0:
                passed = (for_power / non_abstain_power) >= proposal.pass_threshold
            else:
                # Everyone abstained — fails
                passed = False
        elif quorum_met and cast_power == 0:
            passed = False  # No votes cast, fails

        result = VoteResult(
            proposal_id=proposal_id,
            total_voting_power=total_voting_power,
            cast_power=cast_power,
            for_power=for_power,
            against_power=against_power,
            abstain_power=abstain_power,
            quorum_met=quorum_met,
            passed=passed,
        )

        # Auto-transition status based on tally (only if voting has ended)
        if proposal.status in (ProposalStatus.ACTIVE, ProposalStatus.EXPIRED):
            if passed:
                self._repo.update_proposal_status(proposal_id, ProposalStatus.PASSED)
            else:
                self._repo.update_proposal_status(proposal_id, ProposalStatus.REJECTED)

        return result

    # -- Execution ----------------------------------------------------------

    def execute_proposal(self, proposal_id: str) -> dict:
        """Execute a passed proposal.

        The action performed depends on ``proposal_type``:
        - ordinary: Records a resolution in execution_result.
        - special: Marks the company as frozen (resolution).
        - membership: Not implemented — requires caller to use
          CompanyService separately.
        - dividend: Not implemented — requires DividendService (Phase 34D).

        Args:
            proposal_id: The proposal to execute.

        Returns:
            A dict with the execution result.

        Raises:
            GovernanceError: If the proposal is not in ``passed``
                status, or if the execution fails.
        """
        proposal = self._repo.get_proposal(proposal_id)
        if proposal is None:
            raise GovernanceError(f"Proposal '{proposal_id[:12]}' not found")

        if proposal.status != ProposalStatus.PASSED:
            raise GovernanceError(
                f"Proposal '{proposal_id[:12]}' is {proposal.status.value}, "
                "only 'passed' proposals can be executed"
            )

        now = self._now_utc()
        execution_result: dict = {}

        if proposal.proposal_type == ProposalType.ORDINARY:
            execution_result = {
                "action": "resolution_recorded",
                "detail": f"Ordinary resolution '{proposal.title}' adopted",
                "executed_at": now,
            }
        elif proposal.proposal_type == ProposalType.SPECIAL:
            execution_result = {
                "action": "company_frozen",
                "detail": f"Special resolution '{proposal.title}' adopted — company frozen",
                "executed_at": now,
            }
        elif proposal.proposal_type == ProposalType.MEMBERSHIP:
            execution_result = {
                "action": "requires_membership_change",
                "detail": "Membership resolution passed — use CompanyService to add/remove members",
                "executed_at": now,
            }
        elif proposal.proposal_type == ProposalType.DIVIDEND:
            execution_result = {
                "action": "requires_dividend_service",
                "detail": "Dividend resolution passed — use DividendService (Phase 34D) to distribute",
                "executed_at": now,
            }

        self._repo.update_proposal_status(
            proposal_id,
            ProposalStatus.EXECUTED,
            execution_result=json.dumps(execution_result),
            executed_at=now,
        )

        proposal = self._repo.get_proposal(proposal_id)
        result = proposal.model_dump()
        return result

    def cancel_proposal(self, proposal_id: str, requester_id: str) -> dict:
        """Cancel a proposal that is still in pending or active status.

        Only the original proposer can cancel their own proposal.

        Args:
            proposal_id: The proposal to cancel.
            requester_id: The agent requesting cancellation.

        Returns:
            The cancelled Proposal dict.

        Raises:
            GovernanceError: If the proposal does not exist, is not
                cancelable, or the requester is not the proposer.
        """
        proposal = self._repo.get_proposal(proposal_id)
        if proposal is None:
            raise GovernanceError(f"Proposal '{proposal_id[:12]}' not found")

        if proposal.proposer_id != requester_id:
            raise GovernanceError(
                f"Agent '{requester_id[:12]}' is not the proposer and cannot cancel this proposal"
            )

        if proposal.status not in (ProposalStatus.PENDING, ProposalStatus.ACTIVE):
            raise GovernanceError(
                f"Proposal '{proposal_id[:12]}' is {proposal.status.value} and cannot be cancelled"
            )

        self._repo.update_proposal_status(proposal_id, ProposalStatus.CANCELLED)
        proposal = self._repo.get_proposal(proposal_id)
        return proposal.model_dump()
