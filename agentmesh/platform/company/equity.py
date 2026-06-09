"""
AgentMesh Platform — Phase 34B: Equity Management

Manages company equity/shares. Builds on Company Registry (Phase 34A).
Supports: share issuance, transfer, cap table queries.
"""
from __future__ import annotations

import uuid
from sqlite3 import Connection


class EquityError(Exception):
    pass


SCHEMA_SQL = """
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
CREATE INDEX IF NOT EXISTS idx_equity_company ON equity_shares(company_id);
CREATE INDEX IF NOT EXISTS idx_equity_agent ON equity_shares(agent_id);
"""


class EquityService:
    """Company equity management."""

    def __init__(self, conn: Connection):
        self.conn = conn
        self._ensure_schema()

    def _ensure_schema(self):
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def get_cap_table(self, company_id: str) -> list[dict]:
        """Get full capitalization table for a company."""
        rows = self.conn.execute(
            """SELECT agent_id, SUM(shares) as total_shares,
                      GROUP_CONCAT(share_class) as classes
               FROM equity_shares
               WHERE company_id = ?
               GROUP BY agent_id
               ORDER BY total_shares DESC""",
            (company_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_total_shares(self, company_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(shares), 0) FROM equity_shares WHERE company_id = ?",
            (company_id,),
        ).fetchone()
        return row[0] if row else 0

    def issue_shares(
        self,
        company_id: str,
        agent_id: str,
        shares: int,
        share_class: str = "common",
    ) -> dict:
        """Issue shares to an agent in a company.

        Validates: agent must be a member of the company.
        Each (company, agent, class) combination can have only one record.
        """
        if shares <= 0:
            raise EquityError("Shares must be positive")

        # Validate agent is a company member
        member = self.conn.execute(
            "SELECT role FROM company_members WHERE company_id = ? AND agent_id = ?",
            (company_id, agent_id),
        ).fetchone()
        if member is None:
            raise EquityError(f"Agent {agent_id[:12]} is not a member of company {company_id[:12]}")

        # Founder class only for the actual founder
        if share_class == "founder":
            company = self.conn.execute(
                "SELECT founder_id FROM companies WHERE id = ?", (company_id,)
            ).fetchone()
            if not company or company["founder_id"] != agent_id:
                raise EquityError("Only the company founder can hold founder shares")

        # Founder gets unique issuance at company creation
        # For subsequent issuance, check if record exists
        existing = self.conn.execute(
            "SELECT id, shares FROM equity_shares WHERE company_id = ? AND agent_id = ? AND share_class = ?",
            (company_id, agent_id, share_class),
        ).fetchone()

        share_id = None
        with self.conn:
            if existing:
                # Add to existing shares
                self.conn.execute(
                    "UPDATE equity_shares SET shares = shares + ? WHERE id = ?",
                    (shares, existing["id"]),
                )
                share_id = existing["id"]
            else:
                share_id = uuid.uuid4().hex
                self.conn.execute(
                    """INSERT INTO equity_shares (id, company_id, agent_id, shares, share_class)
                       VALUES (?, ?, ?, ?, ?)""",
                    (share_id, company_id, agent_id, shares, share_class),
                )

            # Update agent's role if first non-founder issuance
            if share_class == "common":
                self.conn.execute(
                    """UPDATE company_members SET role = 'member' WHERE role IS NULL
                       AND company_id = ? AND agent_id = ? AND role != 'founder'""",
                    (company_id, agent_id),
                )

        return {
            "share_id": share_id,
            "company_id": company_id,
            "agent_id": agent_id,
            "shares": shares,
            "share_class": share_class,
        }

    def transfer_shares(
        self,
        company_id: str,
        from_agent: str,
        to_agent: str,
        shares: int,
        share_class: str = "common",
    ) -> dict:
        """Transfer shares from one agent to another."""
        if shares <= 0:
            raise EquityError("Shares must be positive")

        # Check source has enough shares
        source = self.conn.execute(
            "SELECT id, shares FROM equity_shares WHERE company_id = ? AND agent_id = ? AND share_class = ?",
            (company_id, from_agent, share_class),
        ).fetchone()
        if source is None or source["shares"] < shares:
            have = source["shares"] if source else 0
            raise EquityError(f"Insufficient {share_class} shares: need {shares}, have {have}")

        with self.conn:
            # Decrease source
            remaining = source["shares"] - shares
            if remaining == 0:
                self.conn.execute("DELETE FROM equity_shares WHERE id = ?", (source["id"],))
            else:
                self.conn.execute(
                    "UPDATE equity_shares SET shares = ? WHERE id = ?",
                    (remaining, source["id"]),
                )

            # Increase destination
            dest = self.conn.execute(
                "SELECT id, shares FROM equity_shares WHERE company_id = ? AND agent_id = ? AND share_class = ?",
                (company_id, to_agent, share_class),
            ).fetchone()
            if dest:
                self.conn.execute(
                    "UPDATE equity_shares SET shares = shares + ? WHERE id = ?",
                    (shares, dest["id"]),
                )
            else:
                self.conn.execute(
                    """INSERT INTO equity_shares (id, company_id, agent_id, shares, share_class)
                       VALUES (?, ?, ?, ?, ?)""",
                    (uuid.uuid4().hex, company_id, to_agent, shares, share_class),
                )

            # Ensure recipient is a member
            member = self.conn.execute(
                "SELECT 1 FROM company_members WHERE company_id = ? AND agent_id = ?",
                (company_id, to_agent),
            ).fetchone()
            if not member:
                self.conn.execute(
                    """INSERT INTO company_members (company_id, agent_id, role, joined_at)
                       VALUES (?, ?, 'member', datetime('now'))""",
                    (company_id, to_agent),
                )

        return {
            "company_id": company_id,
            "from": from_agent,
            "to": to_agent,
            "shares": shares,
            "share_class": share_class,
        }

    def get_agent_shares(self, company_id: str, agent_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT shares, share_class, issued_at FROM equity_shares WHERE company_id = ? AND agent_id = ?",
            (company_id, agent_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def initialize_founder_equity(
        self, company_id: str, founder_id: str, initial_shares: int = 1000
    ) -> dict:
        """Issue initial founder shares when a company is created."""
        # Remove any existing equity for this company
        self.conn.execute("DELETE FROM equity_shares WHERE company_id = ?", (company_id,))
        return self.issue_shares(company_id, founder_id, initial_shares, share_class="founder")
