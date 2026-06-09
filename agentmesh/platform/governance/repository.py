"""Governance Voting — SQLite Repository.

Provides a data access layer for Proposal and Vote entities backed by
SQLite.  All methods are synchronous and operate on an existing
``sqlite3.Connection`` provided at construction time.

The repository expects that the ``proposals`` and ``votes`` tables
already exist (created via the schema in ``schema_export.json`` or by
the upstream ``db_schema`` initialisation flow).
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from agentmesh.platform.governance.models import (
    Decision,
    Proposal,
    ProposalStatus,
    ProposalType,
    Vote,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS proposals (
    id                TEXT PRIMARY KEY,
    company_id        TEXT NOT NULL,
    title             TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    proposal_type     TEXT NOT NULL DEFAULT 'ordinary'
                      CHECK(proposal_type IN ('ordinary','special','membership','dividend')),
    proposer_id       TEXT NOT NULL,
    voting_start      TEXT NOT NULL,
    voting_end        TEXT NOT NULL,
    quorum            REAL NOT NULL DEFAULT 0.3
                      CHECK(quorum >= 0.0 AND quorum <= 1.0),
    pass_threshold    REAL NOT NULL DEFAULT 0.5
                      CHECK(pass_threshold >= 0.0 AND pass_threshold <= 1.0),
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK(status IN ('pending','active','passed','rejected','executed','expired','cancelled')),
    execution_result  TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    executed_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_proposals_company ON proposals(company_id);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
CREATE INDEX IF NOT EXISTS idx_proposals_company_status ON proposals(company_id, status);

CREATE TABLE IF NOT EXISTS votes (
    id                TEXT PRIMARY KEY,
    proposal_id       TEXT NOT NULL,
    voter_id          TEXT NOT NULL,
    voting_power      REAL NOT NULL CHECK(voting_power >= 0.0),
    decision          TEXT NOT NULL
                      CHECK(decision IN ('for','against','abstain')),
    reason            TEXT NOT NULL DEFAULT '',
    cast_at           TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(proposal_id, voter_id)
);

CREATE INDEX IF NOT EXISTS idx_votes_proposal ON votes(proposal_id);
"""


class GovernanceRepository:
    """SQLite-backed repository for proposals and votes.

    Args:
        conn: An open SQLite connection with Row factory enabled.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    # -- Proposals ----------------------------------------------------------

    def create_proposal(self, proposal: Proposal) -> Proposal:
        """Persist a new proposal.

        Args:
            proposal: The Proposal object to store.

        Returns:
            The stored Proposal.
        """
        self.conn.execute(
            """INSERT INTO proposals
               (id, company_id, title, description, proposal_type, proposer_id,
                voting_start, voting_end, quorum, pass_threshold, status,
                execution_result, created_at, executed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                proposal.id,
                proposal.company_id,
                proposal.title,
                proposal.description,
                proposal.proposal_type.value,
                proposal.proposer_id,
                proposal.voting_start,
                proposal.voting_end,
                proposal.quorum,
                proposal.pass_threshold,
                proposal.status.value,
                proposal.execution_result,
                proposal.created_at,
                proposal.executed_at,
            ),
        )
        self.conn.commit()
        return self.get_proposal(proposal.id)

    def get_proposal(self, proposal_id: str) -> Optional[Proposal]:
        """Fetch a proposal by ID.

        Args:
            proposal_id: The unique proposal identifier.

        Returns:
            The Proposal object, or ``None`` if not found.
        """
        row = self.conn.execute(
            "SELECT * FROM proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_proposal(row)

    def list_proposals(
        self,
        company_id: Optional[str] = None,
        status: Optional[ProposalStatus] = None,
    ) -> list[Proposal]:
        """List proposals, optionally filtered by company and/or status.

        Args:
            company_id: If provided, only proposals for this company.
            status: If provided, only proposals with this status.

        Returns:
            A list of matching Proposal objects.
        """
        conditions: list[str] = []
        params: list[str] = []

        if company_id is not None:
            conditions.append("company_id = ?")
            params.append(company_id)
        if status is not None:
            conditions.append("status = ?")
            params.append(status.value)

        where = ""
        if conditions:
            where = " WHERE " + " AND ".join(conditions)

        rows = self.conn.execute(
            f"SELECT * FROM proposals{where} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [self._row_to_proposal(r) for r in rows]

    def update_proposal_status(
        self,
        proposal_id: str,
        status: ProposalStatus,
        execution_result: Optional[str] = None,
        executed_at: Optional[str] = None,
    ) -> Optional[Proposal]:
        """Update the status (and optionally execution details) of a proposal.

        Args:
            proposal_id: The proposal to update.
            status: The new status.
            execution_result: Optional JSON string with execution details.
            executed_at: Optional ISO-8601 execution timestamp.

        Returns:
            The updated Proposal, or ``None`` if not found.
        """
        existing = self.get_proposal(proposal_id)
        if existing is None:
            return None

        self.conn.execute(
            """UPDATE proposals SET status = ?, execution_result = ?,
               executed_at = ? WHERE id = ?""",
            (status.value, execution_result, executed_at, proposal_id),
        )
        self.conn.commit()
        return self.get_proposal(proposal_id)

    # -- Votes --------------------------------------------------------------

    def cast_vote(self, vote: Vote) -> Vote:
        """Record a vote.  Each (proposal_id, voter_id) pair is unique.

        Args:
            vote: The Vote object to store.

        Returns:
            The stored Vote.
        """
        self.conn.execute(
            """INSERT OR REPLACE INTO votes
               (id, proposal_id, voter_id, voting_power, decision, reason, cast_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                vote.id,
                vote.proposal_id,
                vote.voter_id,
                vote.voting_power,
                vote.decision.value,
                vote.reason,
                vote.cast_at,
            ),
        )
        self.conn.commit()
        return self.get_vote(vote.id)

    def get_vote(self, vote_id: str) -> Optional[Vote]:
        """Fetch a single vote by ID.

        Args:
            vote_id: The unique vote identifier.

        Returns:
            The Vote object, or ``None`` if not found.
        """
        row = self.conn.execute(
            "SELECT * FROM votes WHERE id = ?",
            (vote_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_vote(row)

    def get_votes_for_proposal(self, proposal_id: str) -> list[Vote]:
        """Return all votes cast on a given proposal.

        Args:
            proposal_id: The proposal to look up.

        Returns:
            A list of Vote objects ordered by cast time.
        """
        rows = self.conn.execute(
            "SELECT * FROM votes WHERE proposal_id = ? ORDER BY cast_at ASC",
            (proposal_id,),
        ).fetchall()
        return [self._row_to_vote(r) for r in rows]

    def get_vote_by_voter(self, proposal_id: str, voter_id: str) -> Optional[Vote]:
        """Check if a specific voter has already voted on a proposal.

        Args:
            proposal_id: The proposal identifier.
            voter_id: The voter identifier.

        Returns:
            The Vote object, or ``None`` if the voter has not voted.
        """
        row = self.conn.execute(
            "SELECT * FROM votes WHERE proposal_id = ? AND voter_id = ?",
            (proposal_id, voter_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_vote(row)

    # -- Helpers ------------------------------------------------------------

    def _row_to_proposal(self, row: sqlite3.Row) -> Proposal:
        return Proposal(
            id=row["id"],
            company_id=row["company_id"],
            title=row["title"],
            description=row["description"],
            proposal_type=ProposalType(row["proposal_type"]),
            proposer_id=row["proposer_id"],
            voting_start=row["voting_start"],
            voting_end=row["voting_end"],
            quorum=row["quorum"],
            pass_threshold=row["pass_threshold"],
            status=ProposalStatus(row["status"]),
            execution_result=row["execution_result"],
            created_at=row["created_at"],
            executed_at=row["executed_at"],
        )

    def _row_to_vote(self, row: sqlite3.Row) -> Vote:
        return Vote(
            id=row["id"],
            proposal_id=row["proposal_id"],
            voter_id=row["voter_id"],
            voting_power=row["voting_power"],
            decision=Decision(row["decision"]),
            reason=row["reason"],
            cast_at=row["cast_at"],
        )
