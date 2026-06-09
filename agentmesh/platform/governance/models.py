"""Governance Voting — Data Models.

Pydantic models for Proposal and Vote entities, plus a VoteResult
dataclass used by the governance voting system (Phase 34, Module C).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ProposalType(str, Enum):
    """Types of proposals in the governance system."""

    ORDINARY = "ordinary"
    SPECIAL = "special"
    MEMBERSHIP = "membership"
    DIVIDEND = "dividend"


class ProposalStatus(str, Enum):
    """Possible states for a proposal through its lifecycle."""

    PENDING = "pending"
    ACTIVE = "active"
    PASSED = "passed"
    REJECTED = "rejected"
    EXECUTED = "executed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class Decision(str, Enum):
    """Vote decision options."""

    FOR = "for"
    AGAINST = "against"
    ABSTAIN = "abstain"


def _now_utc() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


class Proposal(BaseModel):
    """A proposal submitted by a company member for voting.

    Attributes:
        id: Unique identifier (UUID hex).
        company_id: The company this proposal belongs to.
        title: Short title of the proposal.
        description: Detailed description of the proposal.
        proposal_type: Type of proposal (ordinary/special/membership/dividend).
        proposer_id: Agent ID of the proposer.
        voting_start: ISO-8601 timestamp when voting starts.
        voting_end: ISO-8601 timestamp when voting ends.
        quorum: Minimum voting power required as fraction (e.g. 0.3 = 30%).
        pass_threshold: Fraction of cast votes needed to pass (e.g. 0.5 = 50%).
        status: Current proposal status.
        execution_result: JSON string with execution result details (optional).
        created_at: ISO-8601 creation timestamp.
        executed_at: ISO-8601 execution timestamp (optional).
    """

    id: str = Field(description="Unique proposal identifier (UUID hex)")
    company_id: str = Field(description="The company this proposal belongs to")
    title: str = Field(description="Short title of the proposal", min_length=1)
    description: str = Field(default="", description="Detailed description of the proposal")
    proposal_type: ProposalType = Field(default=ProposalType.ORDINARY, description="Type of proposal")
    proposer_id: str = Field(description="Agent ID of the proposer")
    voting_start: str = Field(description="ISO-8601 timestamp when voting starts")
    voting_end: str = Field(description="ISO-8601 timestamp when voting ends")
    quorum: float = Field(default=0.3, description="Minimum voting power fraction required", ge=0.0, le=1.0)
    pass_threshold: float = Field(default=0.5, description="Fraction of cast votes needed to pass", ge=0.0, le=1.0)
    status: ProposalStatus = Field(default=ProposalStatus.PENDING, description="Current proposal status")
    execution_result: Optional[str] = Field(default=None, description="JSON string with execution result details")
    created_at: str = Field(default_factory=_now_utc, description="ISO-8601 creation timestamp")
    executed_at: Optional[str] = Field(default=None, description="ISO-8601 execution timestamp")


class Vote(BaseModel):
    """A vote cast by a company member on a proposal.

    Attributes:
        id: Unique identifier (UUID hex).
        proposal_id: The proposal being voted on.
        voter_id: Agent ID of the voter.
        voting_power: Snapshot of the voter's equity shares at vote time.
        decision: Vote decision (for/against/abstain).
        reason: Optional reason for the vote.
        cast_at: ISO-8601 timestamp when the vote was cast.
    """

    id: str = Field(description="Unique vote identifier (UUID hex)")
    proposal_id: str = Field(description="The proposal being voted on")
    voter_id: str = Field(description="Agent ID of the voter")
    voting_power: float = Field(description="Snapshot of equity shares at vote time", ge=0.0)
    decision: Decision = Field(description="Vote decision (for/against/abstain)")
    reason: str = Field(default="", description="Optional reason for the vote")
    cast_at: str = Field(default_factory=_now_utc, description="ISO-8601 vote timestamp")


@dataclass
class VoteResult:
    """Result of a proposal vote tally."""

    proposal_id: str
    total_voting_power: float
    cast_power: float
    for_power: float
    against_power: float
    abstain_power: float
    quorum_met: bool
    passed: bool
