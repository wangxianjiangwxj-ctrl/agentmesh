"""
AgentMesh Platform — Phase 34D: Dividend System

Distributes company profits to shareholders proportionally.
Builds on Company Registry (34A) + Equity Management (34B).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional
from sqlite3 import Connection, Row


class DividendError(Exception):
    pass


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dividend_funds (
    id              TEXT PRIMARY KEY,
    company_id      TEXT NOT NULL,
    total_amount    INTEGER NOT NULL CHECK(total_amount > 0),
    available_amount INTEGER NOT NULL CHECK(available_amount >= 0),
    distributed     INTEGER NOT NULL DEFAULT 0,
    source          TEXT NOT NULL DEFAULT 'escrow',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_df_company ON dividend_funds(company_id);

CREATE TABLE IF NOT EXISTS dividend_records (
    id              TEXT PRIMARY KEY,
    fund_id         TEXT NOT NULL,
    company_id      TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    shares_at_snapshot INTEGER NOT NULL,
    total_shares    INTEGER NOT NULL,
    dividend_amount  INTEGER NOT NULL,
    claimed         INTEGER NOT NULL DEFAULT 0,
    claimed_at      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(fund_id, agent_id)
);
CREATE INDEX IF NOT EXISTS idx_dr_agent ON dividend_records(agent_id);
CREATE INDEX IF NOT EXISTS idx_dr_fund ON dividend_records(fund_id);
"""


class DividendService:
    """Profit distribution to shareholders."""

    def __init__(self, conn: Connection):
        self.conn = conn
        self._ensure_schema()

    def _ensure_schema(self):
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    # ── Fund management ─────────────────────────────────────────────

    def deposit_fund(
        self, company_id: str, amount: int, source: str = "escrow"
    ) -> dict:
        """Deposit profits into company's dividend pool."""
        if amount <= 0:
            raise DividendError("Amount must be positive")

        fund_id = uuid.uuid4().hex
        self.conn.execute(
            """INSERT INTO dividend_funds
               (id, company_id, total_amount, available_amount, source)
               VALUES (?, ?, ?, ?, ?)""",
            (fund_id, company_id, amount, amount, source),
        )
        self.conn.commit()
        return {"fund_id": fund_id, "company_id": company_id, "amount": amount}

    def get_available_funds(self, company_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM dividend_funds WHERE company_id = ? AND available_amount > 0 ORDER BY created_at",
            (company_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_total_available(self, company_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(available_amount), 0) FROM dividend_funds WHERE company_id = ?",
            (company_id,),
        ).fetchone()
        return row[0]

    # ── Dividend computation ────────────────────────────────────────

    def compute_dividend(self, fund_id: str) -> list[dict]:
        """Compute per-share dividend for a fund, creating dividend records.

        Takes a snapshot of equity_shares at computation time.
        Returns list of individual dividend records.
        """
        # Get fund
        fund = self.conn.execute(
            "SELECT * FROM dividend_funds WHERE id = ?", (fund_id,)
        ).fetchone()
        if fund is None:
            raise DividendError(f"Fund {fund_id[:12]} not found")
        if fund["distributed"]:
            raise DividendError("Dividend already distributed for this fund")

        fund = dict(fund)
        company_id = fund["company_id"]
        total_amount = fund["available_amount"]

        # Snapshot: get all shareholders and their shares
        shareholders = self.conn.execute(
            """SELECT agent_id, SUM(shares) as total_shares
               FROM equity_shares
               WHERE company_id = ?
               GROUP BY agent_id
               HAVING total_shares > 0""",
            (company_id,),
        ).fetchall()

        if not shareholders:
            raise DividendError(f"No shareholders in company {company_id[:12]}")

        total_shares = sum(r["total_shares"] for r in shareholders)

        records = []
        with self.conn:
            for sh in shareholders:
                agent_id = sh["agent_id"]
                shares = sh["total_shares"]
                dividend = int(total_amount * shares / total_shares)
                record_id = uuid.uuid4().hex
                self.conn.execute(
                    """INSERT INTO dividend_records
                       (id, fund_id, company_id, agent_id, shares_at_snapshot,
                        total_shares, dividend_amount)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (record_id, fund_id, company_id, agent_id,
                     shares, total_shares, dividend),
                )
                records.append({
                    "id": record_id,
                    "agent_id": agent_id,
                    "shares": shares,
                    "dividend": dividend,
                })

            # Mark fund as distributed
            self.conn.execute(
                "UPDATE dividend_funds SET distributed = 1, available_amount = 0, closed_at = datetime('now') WHERE id = ?",
                (fund_id,),
            )
        self.conn.commit()

        return records

    # ── Claiming ─────────────────────────────────────────────────────

    def claim_dividend(self, agent_id: str, record_id: str) -> dict:
        """Claim a dividend payment. Credits to agent's escrow account."""
        record = self.conn.execute(
            "SELECT * FROM dividend_records WHERE id = ? AND agent_id = ?",
            (record_id, agent_id),
        ).fetchone()
        if record is None:
            raise DividendError("Dividend record not found")
        if record["claimed"]:
            raise DividendError("Dividend already claimed")

        record = dict(record)
        amount = record["dividend_amount"]

        with self.conn:
            self.conn.execute(
                """UPDATE dividend_records
                   SET claimed = 1, claimed_at = datetime('now')
                   WHERE id = ?""",
                (record_id,),
            )
            # Credit to escrow account
            self.conn.execute(
                """INSERT INTO accounts (agent_id, balance, frozen, updated_at)
                   VALUES (?, ?, 0, datetime('now'))
                   ON CONFLICT(agent_id) DO UPDATE SET
                       balance = balance + ?,
                       updated_at = datetime('now')""",
                (agent_id, amount, amount),
            )
        self.conn.commit()

        return {"record_id": record_id, "agent_id": agent_id, "amount": amount}

    def claim_all(self, agent_id: str, company_id: Optional[str] = None) -> list[dict]:
        """Claim all unclaimed dividends for an agent."""
        query = "SELECT id, dividend_amount FROM dividend_records WHERE agent_id = ? AND claimed = 0"
        params = [agent_id]
        if company_id:
            query += " AND company_id = ?"
            params.append(company_id)

        records = self.conn.execute(query, params).fetchall()
        if not records:
            return []

        results = []
        for r in records:
            results.append(self.claim_dividend(agent_id, r["id"]))
        return results

    # ── Queries ─────────────────────────────────────────────────────

    def get_unclaimed(self, agent_id: str) -> list[dict]:
        rows = self.conn.execute(
            """SELECT dr.*, df.source as fund_source
               FROM dividend_records dr
               JOIN dividend_funds df ON df.id = dr.fund_id
               WHERE dr.agent_id = ? AND dr.claimed = 0
               ORDER BY dr.created_at DESC""",
            (agent_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_company_dividends(self, company_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM dividend_records WHERE company_id = ? ORDER BY created_at",
            (company_id,),
        ).fetchall()
        return [dict(r) for r in rows]
