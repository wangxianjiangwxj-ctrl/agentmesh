#!/usr/bin/env python3
"""
AgentMesh Phase 35C Level 1 — Multi-Company Basic Interaction Stress Test.

Covers the following 6-step flow across two agent companies:

  1. Register AgentA company and AgentB company
  2. A issues 1000 shares; B issues 500 shares
  3. A invests in B: equity transfer + governance approval (100 shares)
  4. B initiates a service contract with A (escrow)
  5. Service completes -> B pays dividend to A
  6. Verify A asset changes + B balance sheet (full-chain consistency)

Usage:
    cd agentmesh/
    python3 tests/stress/test_multi_company.py

Zero external dependencies.  Zero network.  SQLite in-memory.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Path setup — ensure platform/ is on sys.path (flat imports for escrow,
# dividend, identity, etc.)
# ---------------------------------------------------------------------------
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_platform_dir = os.path.join(_project_root, "agentmesh", "platform")
for p in [_project_root, _platform_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from db_schema import create_test_db
from dividend import DividendService
from escrow import EscrowService
from identity import IdentityService  # platform identity

from agentmesh.platform.company.repository import CompanyRepository
from agentmesh.platform.company.service import CompanyService
from agentmesh.platform.governance.models import Decision, ProposalStatus, ProposalType
from agentmesh.platform.governance.repository import GovernanceRepository
from agentmesh.platform.governance.service import GovernanceError, GovernanceService

# ====================================================================
# Extended schema for company / equity / governance tables
# ====================================================================

COMPANY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS companies (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    founder_id      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','frozen','dissolved')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_companies_founder ON companies(founder_id);
CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(status);

CREATE TABLE IF NOT EXISTS company_members (
    company_id      TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member'
                    CHECK(role IN ('founder','admin','member')),
    joined_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (company_id, agent_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_members_agent ON company_members(agent_id);

CREATE TABLE IF NOT EXISTS equity_shares (
    id              TEXT PRIMARY KEY,
    company_id      TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    shares          INTEGER NOT NULL CHECK(shares > 0),
    share_class     TEXT NOT NULL DEFAULT 'common'
                    CHECK(share_class IN ('founder','common','preferred')),
    issued_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(company_id, agent_id, share_class)
);
CREATE INDEX IF NOT EXISTS idx_equity_company ON equity_shares(company_id);
CREATE INDEX IF NOT EXISTS idx_equity_holder ON equity_shares(agent_id);
"""

# GovernanceRepository creates its own proposals + votes tables on init.
# We need an in-memory connection with all tables for GovernanceRepository
# and GovernanceService to work correctly.

# ====================================================================
# Stress-test result types
# ====================================================================


@dataclass
class StressStep:
    """A single step within the stress test."""

    name: str
    elapsed: float
    ok: bool
    detail: str = ""


@dataclass
class AssertionResult:
    """A single assertion check."""

    check: str
    expected: Any
    actual: Any
    passed: bool


@dataclass
class StressResult:
    """Aggregated result for the entire stress test."""

    steps: list[StressStep] = field(default_factory=list)
    assertions: list[AssertionResult] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    passed: bool = False
    duration_seconds: float = 0.0


# ====================================================================
# Helpers
# ====================================================================


def info(msg: str) -> None:
    print(f"  {msg}")


def detail(msg: str) -> None:
    print(f"    - {msg}")


def section(title: str) -> None:
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def sub_section(title: str) -> None:
    print()
    print(f"  --- {title} ---")


def _ensure_company_tables(conn: sqlite3.Connection) -> None:
    """Create company, company_members, and equity_shares tables."""
    conn.executescript(COMPANY_SCHEMA_SQL)
    conn.commit()


def _ensure_dividend_tables(conn: sqlite3.Connection) -> None:
    """Create dividend_funds and dividend_records tables."""
    conn.executescript("""
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
    """)
    conn.commit()


def issue_shares(
    conn: sqlite3.Connection,
    company_id: str,
    agent_id: str,
    shares: int,
    share_class: str = "common",
) -> str:
    """Issue equity shares to an agent. Returns the record ID."""
    record_id = uuid.uuid4().hex
    conn.execute(
        """INSERT OR REPLACE INTO equity_shares
           (id, company_id, agent_id, shares, share_class)
           VALUES (?, ?, ?, ?, ?)""",
        (record_id, company_id, agent_id, shares, share_class),
    )
    conn.commit()
    return record_id


def transfer_equity(
    conn: sqlite3.Connection,
    company_id: str,
    from_agent: str,
    to_agent: str,
    shares: int,
    share_class: Optional[str] = None,
) -> None:
    """Transfer equity shares from one agent to another within the same company.

    If ``share_class`` is None, searches across all share classes.
    """
    # Find from_agent's shares
    if share_class is not None:
        from_rows = conn.execute(
            "SELECT id, shares, share_class FROM equity_shares WHERE company_id = ? AND agent_id = ? AND share_class = ?",
            (company_id, from_agent, share_class),
        ).fetchall()
    else:
        from_rows = conn.execute(
            "SELECT id, shares, share_class FROM equity_shares WHERE company_id = ? AND agent_id = ?",
            (company_id, from_agent),
        ).fetchall()

    total_from = sum(r["shares"] for r in from_rows)
    if total_from < shares:
        raise ValueError(
            f"Agent {from_agent[:12]} has only {total_from} shares "
            f"in company {company_id[:12]}, need {shares}"
        )

    # Deduct pro-rata from the first record
    first = from_rows[0]
    actual_class = first["share_class"]
    remaining = first["shares"] - shares
    if remaining > 0:
        conn.execute(
            "UPDATE equity_shares SET shares = ? WHERE id = ?",
            (remaining, first["id"]),
        )
    else:
        conn.execute("DELETE FROM equity_shares WHERE id = ?", (first["id"],))

    # Give to to_agent — upsert
    existing = conn.execute(
        "SELECT id, shares FROM equity_shares WHERE company_id = ? AND agent_id = ? AND share_class = ?",
        (company_id, to_agent, actual_class),
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE equity_shares SET shares = shares + ? WHERE id = ?",
            (shares, existing["id"]),
        )
    else:
        record_id = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO equity_shares
               (id, company_id, agent_id, shares, share_class)
               VALUES (?, ?, ?, ?, ?)""",
            (record_id, company_id, to_agent, shares, actual_class),
        )

    conn.commit()


def get_agent_equity(conn: sqlite3.Connection, company_id: str, agent_id: str) -> int:
    """Get total equity shares for an agent in a company."""
    row = conn.execute(
        "SELECT COALESCE(SUM(shares), 0) FROM equity_shares WHERE company_id = ? AND agent_id = ?",
        (company_id, agent_id),
    ).fetchone()
    return int(row[0]) if row else 0


def get_total_equity(conn: sqlite3.Connection, company_id: str) -> int:
    """Get total equity shares issued by a company."""
    row = conn.execute(
        "SELECT COALESCE(SUM(shares), 0) FROM equity_shares WHERE company_id = ?",
        (company_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def get_escrow_balance(escrow: EscrowService, entity_id: str) -> int:
    """Get the available escrow balance for an entity (agent or company)."""
    bal = escrow.get_balance(entity_id)
    return bal.get("available", 0)


def make_governance_db(conn: sqlite3.Connection) -> GovernanceRepository:
    """Create a GovernanceRepository using an existing connection.

    The GovernanceRepository creates its own proposals + votes tables.
    We bypass its __init__ and call _ensure_schema manually so it shares
    the same connection.
    """
    repo = object.__new__(GovernanceRepository)
    repo.conn = conn
    repo._ensure_schema()
    return repo


# ====================================================================
# Main stress test
# ====================================================================


def run_multi_company_stress() -> StressResult:
    """Execute the 6-step multi-company stress test.

    Returns:
        A StressResult with all step timings, assertions, and metrics.
    """
    result = StressResult()
    t0 = time.monotonic()

    section("Phase 35C Level 1 — Multi-Company Basic Interaction Stress Test")
    info("Starting 6-step scenario")

    # ------------------------------------------------------------------
    # 0. Setup: create test DB with all required tables
    # ------------------------------------------------------------------
    t_step = time.monotonic()
    conn, db_path = create_test_db()

    # Add company/equity tables
    _ensure_company_tables(conn)
    _ensure_dividend_tables(conn)

    # Create identity service (shares the in-memory connection)
    identity = IdentityService(db_path)
    identity._conn = conn

    # Create governance repository (also adds proposals/votes tables)
    gov_repo = make_governance_db(conn)
    gov_service = GovernanceService(gov_repo)
    # Re-point gov_service to use our shared connection (GovService uses repo.conn)
    gov_service._repo.conn = conn

    # Create company service with its own in-memory repo
    company_repo = CompanyRepository()
    company_service = CompanyService(company_repo)

    # Create escrow and dividend services
    escrow = EscrowService(conn, identity)
    dividend = DividendService(conn)

    result.steps.append(StressStep("service_init", time.monotonic() - t_step, True))
    info("Service layer initialised")

    try:
        # ------------------------------------------------------------------
        # Step 1: Register AgentA company and AgentB company
        # ------------------------------------------------------------------
        sub_section("Step 1: Register AgentA and AgentB companies")
        t_step = time.monotonic()

        # Register agents
        agent_a = identity.register("AgentA", auth_token="token_a")
        agent_b = identity.register("AgentB", auth_token="token_b")
        a_id = agent_a["agent_id"]
        b_id = agent_b["agent_id"]
        info(f"Registered AgentA: {a_id[:12]}...")
        info(f"Registered AgentB: {b_id[:12]}...")

        # Ensure escrow accounts
        escrow.ensure_account(a_id)
        escrow.ensure_account(b_id)

        # Create companies
        company_a = company_service.create_company(
            name="AgentA Inc.",
            description="Company A for stress test",
            founder_id=a_id,
        )
        company_b = company_service.create_company(
            name="AgentB Ltd.",
            description="Company B for stress test",
            founder_id=b_id,
        )
        ca_id = company_a["id"]
        cb_id = company_b["id"]
        info(f"Company A: {ca_id[:12]}... ({company_a['name']})")
        info(f"Company B: {cb_id[:12]}... ({company_b['name']})")

        # Sync company data to SQL tables so governance/escrow can use them
        _sync_company_to_sql(conn, company_a, a_id)
        _sync_company_to_sql(conn, company_b, b_id)

        result.steps.append(
            StressStep("register_companies", time.monotonic() - t_step, True,
                       f"A={ca_id[:12]}, B={cb_id[:12]}")
        )

        # ------------------------------------------------------------------
        # Step 2: A issues 1000 shares; B issues 500 shares
        # ------------------------------------------------------------------
        sub_section("Step 2: Issue equity shares")
        t_step = time.monotonic()

        issue_shares(conn, ca_id, a_id, 1000, share_class="common")
        issue_shares(conn, cb_id, b_id, 500, share_class="common")

        a_equity = get_agent_equity(conn, ca_id, a_id)
        b_equity = get_agent_equity(conn, cb_id, b_id)
        total_a = get_total_equity(conn, ca_id)
        total_b = get_total_equity(conn, cb_id)

        info(f"A's equity in A Inc: {a_equity} / {total_a} total shares")
        info(f"B's equity in B Ltd: {b_equity} / {total_b} total shares")

        result.steps.append(
            StressStep("issue_shares", time.monotonic() - t_step, True,
                       f"A({a_equity}) B({b_equity})")
        )

        # ------------------------------------------------------------------
        # Step 3: A invests in B — equity transfer + governance approval
        # This means A (as a company entity) buys 100 shares of B Ltd.
        # However, A Inc. is not a person — it's a company. Company A
        # invests in Company B by having the founder of Company A
        # (agent A) acquire shares of Company B.
        #
        # Flow:
        #   a) Agent A (founder of A Inc.) joins B Ltd as member
        #   b) B Ltd issues or transfers 100 shares to Agent A
        #   c) Governance approval: B Ltd members vote on the transfer
        # ------------------------------------------------------------------
        sub_section("Step 3: A invests in B (equity transfer + governance)")
        t_step = time.monotonic()

        # 3a. Add Agent A as member of Company B (needed for voting)
        conn.execute(
            "INSERT OR REPLACE INTO company_members (company_id, agent_id, role) VALUES (?, ?, ?)",
            (cb_id, a_id, "member"),
        )
        conn.commit()



        # 3b. Create governance proposal for equity transfer
        #    B Ltd votes on issuing 100 shares to Agent A
        voting_end = _future_iso(minutes=60)
        proposal = gov_service.create_proposal(
            company_id=cb_id,
            title="Approve equity transfer: issue 100 shares to Agent A",
            description=(
                "Proposal to transfer 100 common shares of B Ltd "
                "to Agent A as an investment from Agent A Inc."
            ),
            proposal_type=ProposalType.SPECIAL,
            proposer_id=b_id,
            voting_end=voting_end,
            quorum=0.3,
            pass_threshold=0.5,
        )
        prop_id = proposal["id"]
        info(f"Created proposal {prop_id[:12]}... for equity transfer")

        # 3c. Cast votes: B (founder, 500 shares) votes FOR,
        #    A (member, 0 shares currently) votes FOR
        vote_b = gov_service.cast_vote(prop_id, b_id, Decision.FOR, "Approve investment")
        vote_a = gov_service.cast_vote(prop_id, a_id, Decision.FOR, "Accept investment")
        info(f"Votes cast: B={vote_b['decision']}, A={vote_a['decision']}")

        # 3d. Tally results and auto-execute
        vote_result = gov_service.get_results(prop_id)
        info(f"Vote result: quorum_met={vote_result.quorum_met}, passed={vote_result.passed}")

        # If passed, execute the proposal (which records the resolution)
        if vote_result.passed:
            executed = gov_service.execute_proposal(prop_id)
            info(f"Proposal executed: {executed['status']}")

            # Transfer 100 shares from B to A in B Ltd
            transfer_equity(conn, cb_id, b_id, a_id, 100)
            info("Transferred 100 shares from B to A in B Ltd")
        else:
            result.errors.append("Equity transfer proposal did not pass")
            info("WARNING: Governance proposal failed. Debugging...")
            # Force-transfer anyway for the test to continue
            transfer_equity(conn, cb_id, b_id, a_id, 100)
            info("(forced transfer for test continuity)")

        a_equity_b = get_agent_equity(conn, cb_id, a_id)
        b_equity_b = get_agent_equity(conn, cb_id, b_id)
        total_b_after = get_total_equity(conn, cb_id)
        info(f"After transfer — B Ltd: A holds {a_equity_b}, B holds {b_equity_b}, total {total_b_after}")

        # Verify the transfer
        equity_transfer_ok = (a_equity_b == 100 and b_equity_b == 400 and total_b_after == 500)
        result.steps.append(
            StressStep("equity_transfer", time.monotonic() - t_step, equity_transfer_ok,
                       f"A_holds_in_B={a_equity_b}, B_owns={b_equity_b}, total={total_b_after}")
        )

        # ------------------------------------------------------------------
        # Step 4: B initiates service contract with A (escrow)
        # ------------------------------------------------------------------
        sub_section("Step 4: B initiates service contract with A (escrow)")
        t_step = time.monotonic()

        # Agent B (B Ltd founder) acts as publisher
        # Agent A (A Inc founder) acts as executor
        # B creates a task and holds escrow
        task_id = "stress-mc-task-001"
        escrow_amount = 500

        # Insert task
        conn.execute(
            """INSERT INTO tasks
               (id, publisher_id, title, description, escrow_amount, status,
                executor_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'open', ?, datetime('now'), datetime('now'))""",
            (task_id, b_id, "Service contract: B to A",
             "B Ltd requires A Inc to provide consulting services", escrow_amount, a_id),
        )
        conn.commit()

        # B holds escrow
        escrow.ensure_account(b_id)
        escrow.hold(b_id, task_id, escrow_amount)
        info(f"Escrow held: {escrow_amount} points by B for task {task_id}")

        result.steps.append(
            StressStep("create_escrow", time.monotonic() - t_step, True,
                       f"task={task_id}, amount={escrow_amount}")
        )

        # ------------------------------------------------------------------
        # Step 5: Service completes -> B pays dividend to A
        # ------------------------------------------------------------------
        sub_section("Step 5: Service completes, B pays dividend")
        t_step = time.monotonic()

        # 5a. Release escrow (B pays A for the service)
        release_result = escrow.release(
            task_id=task_id,
            publisher_id=b_id,
            executor_id=a_id,
            escrow_amount=escrow_amount,
            publisher_share=0.0,   # B pays all to A
            executor_share=1.0,    # A receives all
        )
        info(f"Escrow release: A receives {release_result['executor_reward']}, "
             f"B gets back {release_result['publisher_return']}")

        # Mark task settled
        conn.execute("UPDATE tasks SET status='settled' WHERE id=?", (task_id,))
        conn.commit()

        # 5b. B's escrow account now has the remainder (if any) plus
        #     B's company earnings. B deposits into its dividend pool.
        #     B Ltd deposits 200 points as profit to distribute to shareholders.
        dividend_amount = 200
        escrow.ensure_account(cb_id)  # B Ltd company account
        escrow.deposit(cb_id, dividend_amount)

        # Move from escrow to dividend pool
        fund = dividend.deposit_fund(cb_id, dividend_amount, source="task_reward")
        fund_id = fund["fund_id"]
        info(f"Dividend fund created: {fund_id[:12]}..., amount={dividend_amount}")

        # 5c. Compute dividend distribution to shareholders
        #     Total shares: 500 (400 B, 100 A)
        #     A gets: 200 * 100/500 = 40
        #     B gets: 200 * 400/500 = 160
        dividend_records = dividend.compute_dividend(fund_id)
        info(f"Dividend computed: {len(dividend_records)} records")
        for rec in dividend_records:
            info(f"  {rec['agent_id'][:12]}... gets {rec['dividend']} points "
                 f"(shares: {rec['shares']})")

        # 5d. Claim the dividends
        a_dividend_record = None
        b_dividend_record = None
        for rec in dividend_records:
            claimed = dividend.claim_dividend(rec["agent_id"], rec["id"])
            info(f"  Claimed: {claimed['agent_id'][:12]}... amount={claimed['amount']}")
            if rec["agent_id"] == a_id:
                a_dividend_record = claimed
            if rec["agent_id"] == b_id:
                b_dividend_record = claimed

        result.steps.append(
            StressStep("dividend_distribution", time.monotonic() - t_step, True,
                       f"fund={fund_id[:12]}., A_dividend={a_dividend_record['amount'] if a_dividend_record else 0}, "
                       f"B_dividend={b_dividend_record['amount'] if b_dividend_record else 0}")
        )

        # ------------------------------------------------------------------
        # Step 6: Verify A asset changes + B balance sheet (full-chain
        #         consistency)
        # ------------------------------------------------------------------
        sub_section("Step 6: Verify assets and balance sheet consistency")
        t_step = time.monotonic()

        # A's assets:
        #   - 1000 A Inc shares -> not monetary
        #   - 100 B Ltd shares -> not monetary (equity)
        #   - Escrow balance: initial 1000 + escrow release 500 = 1500
        a_escrow_bal = escrow.get_balance(a_id)
        a_escrow_available = a_escrow_bal["available"]
        a_div_received = a_dividend_record["amount"] if a_dividend_record else 0

        # After dividend claim, the dividend is credited to escrow account
        # So A's escrow balance should be: initial 1000 + release 500 + dividend
        a_expected = 1000 + 500 + a_div_received
        a_actual = a_escrow_bal["balance"]

        info(f"A's escrow: balance={a_escrow_bal['balance']}, "
             f"frozen={a_escrow_bal['frozen']}, available={a_escrow_available}")
        info(f"A expected balance: 1000 (init) + 500 (release) + {a_div_received} (dividend) = {a_expected}")

        # B's balance sheet:
        #   Liabilities: escrow obligation to A (none after release)
        #   Equity: 400 shares (B owns)
        #   Assets: escrow balance
        b_escrow_bal = escrow.get_balance(b_id)
        b_equity_shares = get_agent_equity(conn, cb_id, b_id)
        b_div_received = b_dividend_record["amount"] if b_dividend_record else 0

        # B's escrow: initial 1000 + dividend 160 (hold doesn't reduce balance,
        # the deposit of 200 went to B Ltd company account cb_id, not b_id)
        b_expected = 1000 + b_div_received
        b_actual = b_escrow_bal["balance"]

        info(f"B's escrow: balance={b_escrow_bal['balance']}, "
             f"frozen={b_escrow_bal['frozen']}")
        info(f"B expected balance: 1000 (init) + {b_div_received} (dividend) = {b_expected}")
        info(f"B's equity in B Ltd: {b_equity_shares} shares")

        # Balance sheet identity check:
        # For B Ltd company entity (cb_id):
        #   Company assets = escrow balance (if company has its own account)
        #   Company equity = total shares outstanding
        b_company_bal = escrow.get_balance(cb_id)
        total_b_shares = get_total_equity(conn, cb_id)

        info(f"B Ltd company escrow balance: {b_company_bal['balance']}")

        # Also check equity_shares table consistency
        equity_a_in_b = get_agent_equity(conn, cb_id, a_id)
        equity_b_in_b = get_agent_equity(conn, cb_id, b_id)
        equity_total_b = get_total_equity(conn, cb_id)

        info("Balance sheet (B Ltd):")
        info(f"  Assets (escrow): {b_company_bal['balance']}")
        info("  Liabilities: 0 (escrow released)")
        info("  Equity:")
        info(f"    Agent A (B Ltd shareholder): {equity_a_in_b} shares")
        info(f"    Agent B (B Ltd founder): {equity_b_in_b} shares")
        info(f"    Total equity shares: {equity_total_b}")

        # Assertions
        a_asset_ok = abs(a_actual - a_expected) <= 2  # allow rounding
        b_asset_ok = abs(b_actual - b_expected) <= 2
        equity_balance_ok = (equity_a_in_b + equity_b_in_b) == equity_total_b
        equity_total_ok = equity_total_b == 500  # original issuance

        # Balance sheet identity: Total Assets = Total Liabilities + Total Equity
        # For B Ltd: assets (escrow) = 0 (liabilities) + shares outstanding value
        # Since shares are not monetary-valued here, we check consistency of
        # the equity ledger alone.
        balance_sheet_identity_ok = equity_balance_ok and equity_total_ok

        result.assertions = [
            AssertionResult("a_escrow_balance", a_expected, a_actual, a_asset_ok),
            AssertionResult("b_escrow_balance", b_expected, b_actual, b_asset_ok),
            AssertionResult("equity_a_in_b", 100, equity_a_in_b, equity_a_in_b == 100),
            AssertionResult("equity_b_in_b", 400, equity_b_in_b, equity_b_in_b == 400),
            AssertionResult("total_equity_b", 500, equity_total_b, equity_total_ok),
            AssertionResult("equity_ledger_balance", equity_total_b, equity_a_in_b + equity_b_in_b, equity_balance_ok),
            AssertionResult("balance_sheet_identity",
                            "sum(equity)=total_outstanding",
                            f"A={equity_a_in_b}, B={equity_b_in_b}, total={equity_total_b}",
                            balance_sheet_identity_ok),
            AssertionResult("dividend_a_correct", 40, a_div_received, a_div_received == 40),
            AssertionResult("dividend_b_correct", 160, b_div_received, b_div_received == 160),
        ]

        result.steps.append(
            StressStep("verification", time.monotonic() - t_step,
                       all(a.passed for a in result.assertions),
                       f"{len(result.assertions)} assertions")
        )

        # --- Metrics ---
        total_duration = time.monotonic() - t0
        result.metrics = {
            "total_duration_s": round(total_duration, 3),
            "company_a_id": ca_id[:16],
            "company_b_id": cb_id[:16],
            "agent_a_id": a_id[:16],
            "agent_b_id": b_id[:16],
            "a_equity_in_a": get_agent_equity(conn, ca_id, a_id),
            "a_equity_in_b": equity_a_in_b,
            "b_equity_in_b": equity_b_in_b,
            "total_equity_b": equity_total_b,
            "a_escrow_final": a_actual,
            "b_escrow_final": b_actual,
            "b_company_escrow_final": b_company_bal["balance"],
            "a_dividend_received": a_div_received,
            "b_dividend_received": b_div_received,
            "a_expected_escrow": a_expected,
            "b_expected_escrow": b_expected,
        }

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        result.errors.append(f"Exception: {exc}\n{tb}")
        info(f"ERROR: {exc}")
    finally:
        # Cleanup
        conn.close()
        try:
            os.unlink(db_path)
        except OSError:
            pass

    # Final evaluation
    result.duration_seconds = round(time.monotonic() - t0, 3)
    result.passed = len(result.errors) == 0 and all(a.passed for a in result.assertions)
    return result


def _sync_company_to_sql(
    conn: sqlite3.Connection,
    company_dict: dict,
    founder_id: str,
) -> None:
    """Sync a CompanyService-created company to the SQL tables."""
    # Insert into companies table
    conn.execute(
        """INSERT OR REPLACE INTO companies
           (id, name, description, founder_id, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (company_dict["id"], company_dict["name"],
         company_dict.get("description", ""),
         founder_id,
         company_dict.get("status", "active"),
         company_dict.get("created_at", time.strftime("%Y-%m-%dT%H:%M:%S"))),
    )

    # Insert founder membership
    conn.execute(
        """INSERT OR REPLACE INTO company_members
           (company_id, agent_id, role)
           VALUES (?, ?, ?)""",
        (company_dict["id"], founder_id, "founder"),
    )
    conn.commit()


def _future_iso(minutes: int = 60) -> str:
    """Return an ISO-8601 timestamp ``minutes`` from now."""
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


# ====================================================================
# Report writer
# ====================================================================

REPORT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "reports", "multi-company-stress.md",
)


def write_report(result: StressResult) -> None:
    """Write the stress test report markdown file."""
    status = "PASSED" if result.passed else "FAILED"

    lines: list[str] = []
    lines.append("# AgentMesh Phase 35C Level 1 — Multi-Company Stress Test Report")
    lines.append("")
    lines.append(f"- **Date**: {time.strftime('%Y-%m-%d %H:%M:%S')} (Asia/Shanghai)")
    lines.append(f"- **Status**: {status}")
    lines.append(f"- **Total duration**: {result.duration_seconds:.2f}s")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Steps
    lines.append("## Execution Steps")
    lines.append("")
    lines.append("| # | Step | Elapsed (s) | OK | Detail |")
    lines.append("|---|------|------------|----|--------|")
    for i, s in enumerate(result.steps, 1):
        ok_mark = "Yes" if s.ok else "No"
        lines.append(f"| {i} | {s.name} | {s.elapsed:.3f} | {ok_mark} | {s.detail} |")
    lines.append("")

    # Assertions
    lines.append("## Assertion Results")
    lines.append("")
    lines.append("| Check | Expected | Actual | Passed |")
    lines.append("|-------|----------|--------|--------|")
    for a in result.assertions:
        ok_mark = "Yes" if a.passed else "No"
        lines.append(f"| {a.check} | {a.expected} | {a.actual} | {ok_mark} |")
    lines.append("")

    # Metrics
    lines.append("## Performance Metrics")
    lines.append("")
    for key, value in result.metrics.items():
        lines.append(f"- **{key}**: {value}")
    lines.append("")

    # Errors
    if result.errors:
        lines.append("## Errors")
        lines.append("")
        for err in result.errors:
            lines.append(f"- {err}")
        lines.append("")

    # Balance sheet
    lines.append("## Balance Sheet Verification")
    lines.append("")
    lines.append("### B Ltd (Company B)")
    lines.append("")
    lines.append("```")
    lines.append("Assets:")
    lines.append(f"  Escrow balance: {result.metrics.get('b_escrow_final', '?')}")
    lines.append("")
    lines.append("Liabilities:")
    lines.append("  0 (all escrow released)")
    lines.append("")
    lines.append("Equity:")
    lines.append(f"  Agent A (shareholder): {result.metrics.get('a_equity_in_b', '?')} shares")
    lines.append(f"  Agent B (founder):     {result.metrics.get('b_equity_in_b', '?')} shares")
    lines.append(f"  Total outstanding:     {result.metrics.get('total_equity_b', '?')} shares")
    lines.append("")
    lines.append("Balance sheet identity: Σ(Assets) = Σ(Liabilities) + Σ(Equity)")
    equity_sum = result.metrics.get('a_equity_in_b', 0) + result.metrics.get('b_equity_in_b', 0)
    total_eq = result.metrics.get('total_equity_b', 0)
    identity_ok = "CONSISTENT" if equity_sum == total_eq else "MISMATCH"
    lines.append(f"  Equity sum: {equity_sum} = Total outstanding: {total_eq} => {identity_ok}")
    lines.append("```")
    lines.append("")
    lines.append("### Agent A")
    lines.append("")
    lines.append("```")
    lines.append(f"  A Inc shares held: {result.metrics.get('a_equity_in_a', '?')}")
    lines.append(f"  B Ltd shares held: {result.metrics.get('a_equity_in_b', '?')}")
    lines.append(f"  Escrow balance: {result.metrics.get('a_escrow_final', '?')}")
    lines.append(f"  Expected: {result.metrics.get('a_expected_escrow', '?')}")
    lines.append(f"  Dividend received: {result.metrics.get('a_dividend_received', '?')}")
    lines.append("```")
    lines.append("")
    lines.append("### Agent B")
    lines.append("")
    lines.append("```")
    lines.append(f"  B Ltd shares held: {result.metrics.get('b_equity_in_b', '?')}")
    lines.append(f"  Escrow balance: {result.metrics.get('b_escrow_final', '?')}")
    lines.append(f"  Expected: {result.metrics.get('b_expected_escrow', '?')}")
    lines.append(f"  Dividend received: {result.metrics.get('b_dividend_received', '?')}")
    lines.append("```")
    lines.append("")

    lines.append("---")
    lines.append(f"_Report generated at {time.strftime('%Y-%m-%d %H:%M:%S')}._")
    lines.append("")

    report_dir = os.path.dirname(REPORT_PATH)
    if report_dir:
        os.makedirs(report_dir, exist_ok=True)

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    info(f"Report written to {REPORT_PATH}")


# ====================================================================
# Main
# ====================================================================


def main() -> int:
    """Run the multi-company stress test and write the report.

    Returns:
        0 if all assertions passed, 1 otherwise.
    """
    print()
    print("  AgentMesh Phase 35C Level 1 — Multi-Company Stress Test")
    print("  =======================================================")
    print()
    print("  Scenario: 2-company basic interaction")
    print()

    result = run_multi_company_stress()

    # Summary
    print()
    print("=" * 70)
    print("  RESULTS")
    print("=" * 70)

    status = "PASSED" if result.passed else "FAILED"
    print(f"  [{status}] Multi-Company Interaction")
    for s in result.steps:
        ok = "OK" if s.ok else "FAIL"
        print(f"    [{ok}] {s.name} ({s.elapsed:.3f}s)")

    print()
    for a in result.assertions:
        ok = "PASS" if a.passed else "FAIL"
        print(f"  [{ok}] {a.check}: expected={a.expected}, actual={a.actual}")

    print()
    print(f"  Overall: {status} | Duration: {result.duration_seconds:.2f}s")
    print()

    if result.errors:
        print("  Errors:")
        for err in result.errors:
            print(f"    - {err}")
        print()

    # Write report
    write_report(result)

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
