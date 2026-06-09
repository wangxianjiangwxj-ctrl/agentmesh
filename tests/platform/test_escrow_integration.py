"""Tests for Escrow & Dividend Integration (Phase 34E).

Covers:
  - dividend_deposit_from_escrow (success / insufficient balance)
  - company_aware_release (no company / with company / varied rates)
  - get_company_earnings (zero earnings / with releases)
  - Edge cases (zero contribution, non-positive amount, etc.)

All tests use an in-memory SQLite database populated with the full
set of required tables (accounts, transactions, company_members,
equity_shares, dividend_funds, dividend_records).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from db_schema import create_test_db
from dividend import DividendService
from escrow import EscrowError, EscrowService
from escrow_integration import (
    EscrowIntegrationError,
    company_aware_release,
    dividend_deposit_from_escrow,
    get_company_earnings,
)
from identity import IdentityService

# ====================================================================
# Helper Schema for company / equity / dividend tables
# ====================================================================

_AUX_SCHEMA = """
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

# ====================================================================
# Fixtures
# ====================================================================


@pytest.fixture
def services():
    """Create a full-service fixture with in-memory DB.

    Returns:
        Tuple of (escrow_svc, dividend_svc, identity_svc, agents, companies).

        ``agents`` is a dict with keys ``alice``, ``bob``, ``carol``:
        each an agent dict with ``agent_id``.

        ``companies`` is a dict with keys ``alpha``, ``beta``: each a
        dict with ``company_id``.
    """
    conn, db_path = create_test_db()

    # Add auxiliary tables (company, equity, etc.)
    conn.executescript(_AUX_SCHEMA)
    conn.commit()

    identity = IdentityService(db_path)
    identity._conn = conn

    escrow = EscrowService(conn, identity)
    dividend = DividendService(conn)

    # Register agents
    alice = identity.register("Alice")
    bob = identity.register("Bob")
    carol = identity.register("Carol")

    # Fund Alice's account for escrow operations
    escrow.ensure_account(alice["agent_id"])
    escrow.ensure_account(bob["agent_id"])
    escrow.ensure_account(carol["agent_id"])

    # Create companies
    alpha_id = uuid.uuid4().hex
    beta_id = uuid.uuid4().hex
    gama_id = uuid.uuid4().hex

    conn.execute(
        "INSERT INTO companies (id, name, founder_id) VALUES (?, ?, ?)",
        (alpha_id, "AlphaCorp", alice["agent_id"]),
    )
    conn.execute(
        "INSERT INTO companies (id, name, founder_id) VALUES (?, ?, ?)",
        (beta_id, "BetaInc", bob["agent_id"]),
    )
    conn.execute(
        "INSERT INTO companies (id, name, founder_id) VALUES (?, ?, ?)",
        (gama_id, "GamaLtd", carol["agent_id"]),
    )

    # Make alice(executor) a member of AlphaCorp
    conn.execute(
        "INSERT INTO company_members (company_id, agent_id, role) VALUES (?, ?, ?)",
        (alpha_id, alice["agent_id"], "member"),
    )
    # Make bob(executor) a member of BetaInc
    conn.execute(
        "INSERT INTO company_members (company_id, agent_id, role) VALUES (?, ?, ?)",
        (beta_id, bob["agent_id"], "member"),
    )
    conn.commit()

    # Issue equity shares for dividend computation
    conn.execute(
        "INSERT INTO equity_shares (id, company_id, agent_id, shares, share_class) VALUES (?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, alpha_id, alice["agent_id"], 100, "common"),
    )
    conn.execute(
        "INSERT INTO equity_shares (id, company_id, agent_id, shares, share_class) VALUES (?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, beta_id, bob["agent_id"], 200, "common"),
    )
    conn.execute(
        "INSERT INTO equity_shares (id, company_id, agent_id, shares, share_class) VALUES (?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, gama_id, carol["agent_id"], 150, "common"),
    )
    conn.commit()

    agents = {
        "alice": {"agent_id": alice["agent_id"]},
        "bob": {"agent_id": bob["agent_id"]},
        "carol": {"agent_id": carol["agent_id"]},
    }
    companies = {
        "alpha": {"company_id": alpha_id},
        "beta": {"company_id": beta_id},
        "gama": {"company_id": gama_id},
    }

    yield escrow, dividend, identity, agents, companies

    identity.close()
    conn.close()
    Path(db_path).unlink(missing_ok=True)


# ====================================================================
# Tests: dividend_deposit_from_escrow
# ====================================================================


class TestDividendDepositFromEscrow:
    """Tests for escrow-to-dividend fund transfers."""

    def test_deposit_success(self, services):
        """Successfully deposit escrow funds into a dividend fund."""
        escrow, dividend, _, agents, companies = services
        company_id = companies["alpha"]["company_id"]

        # Fund the company's escrow account
        escrow.deposit(company_id, 2000)

        result = dividend_deposit_from_escrow(
            escrow, dividend, company_id, 500
        )
        assert result["company_id"] == company_id
        assert result["amount"] == 500
        assert "fund_id" in result

        # Verify escrow balance decreased
        bal = escrow.get_balance(company_id)
        assert bal["available"] == 1500

        # Verify dividend fund was created
        available = dividend.get_total_available(company_id)
        assert available == 500

    def test_deposit_insufficient_balance(self, services):
        """Raise EscrowError when escrow balance is too low."""
        escrow, dividend, _, _, companies = services
        company_id = companies["alpha"]["company_id"]

        # Company has no funds in escrow
        with pytest.raises(EscrowError, match="Insufficient"):
            dividend_deposit_from_escrow(
                escrow, dividend, company_id, 100
            )

    def test_deposit_non_positive(self, services):
        """Raise EscrowError for non-positive amounts."""
        escrow, dividend, _, _, companies = services
        company_id = companies["alpha"]["company_id"]
        escrow.deposit(company_id, 1000)

        with pytest.raises(EscrowError, match="must be positive"):
            dividend_deposit_from_escrow(escrow, dividend, company_id, 0)
        with pytest.raises(EscrowError, match="must be positive"):
            dividend_deposit_from_escrow(escrow, dividend, company_id, -5)

    def test_deposit_custom_source(self, services):
        """Deposit with a custom source label."""
        escrow, dividend, _, _, companies = services
        company_id = companies["beta"]["company_id"]
        escrow.deposit(company_id, 3000)

        result = dividend_deposit_from_escrow(
            escrow, dividend, company_id, 800, source="platform_bonus"
        )
        assert result["amount"] == 800
        assert "fund_id" in result

    def test_deposit_partial_funds(self, services):
        """Deposit only part of available escrow balance."""
        escrow, dividend, _, _, companies = services
        company_id = companies["gama"]["company_id"]
        escrow.deposit(company_id, 1000)

        result = dividend_deposit_from_escrow(
            escrow, dividend, company_id, 300
        )
        assert result["amount"] == 300

        bal = escrow.get_balance(company_id)
        assert bal["available"] == 700  # remaining


# ====================================================================
# Tests: company_aware_release
# ====================================================================


class TestCompanyAwareRelease:
    """Tests for the company-aware escrow release."""

    def test_release_no_company(self, services):
        """When executor is not in any company, no contribution is made."""
        escrow, dividend, _, agents, companies = services
        alice = agents["alice"]["agent_id"]
        carol = agents["carol"]["agent_id"]
        task_id = "t-no-company"

        escrow.ensure_account(alice)
        escrow.hold(alice, task_id, 200)

        # Carol is not a member of any company (only Alice and Bob are)
        result = company_aware_release(
            escrow, dividend, task_id, alice, carol, 200,
        )

        assert result["company_contribution"] is None
        assert result["release"]["executor_reward"] == 140  # 200 * 0.7
        assert result["release"]["publisher_return"] == 60  # 200 * 0.3
        assert result["net_rewards"]["executor_net"] == 140

    def test_release_with_company_default_rate(self, services):
        """Executor in a company defaults to 10% contribution."""
        escrow, dividend, _, agents, companies = services
        alice = agents["alice"]["agent_id"]
        bob = agents["bob"]["agent_id"]
        task_id = "t-with-company"

        escrow.ensure_account(alice)
        escrow.hold(alice, task_id, 200)

        result = company_aware_release(
            escrow, dividend, task_id, alice, bob, 200,
        )
        # Bob belongs to BetaInc; 10% of 140 = 14
        contrib = result["company_contribution"]
        assert contrib is not None
        assert contrib["executor_id"] == bob
        assert contrib["company_id"] == companies["beta"]["company_id"]
        assert contrib["contribution_rate"] == 0.1
        assert contrib["contribution_amount"] == 14

        assert result["net_rewards"]["executor_net"] == 140 - 14
        assert result["net_rewards"]["publisher_return"] == 60

        # Verify dividend fund received the contribution
        available = dividend.get_total_available(companies["beta"]["company_id"])
        assert available == 14

    def test_release_with_custom_contribution_rate(self, services):
        """Custom contribution rate applies correctly."""
        escrow, dividend, _, agents, companies = services
        alice = agents["alice"]["agent_id"]
        bob = agents["bob"]["agent_id"]
        task_id = "t-custom-rate"

        escrow.ensure_account(alice)
        escrow.hold(alice, task_id, 500)

        result = company_aware_release(
            escrow, dividend, task_id, alice, bob, 500,
            contribution_rate=0.2,
        )
        # executor_reward = 500 * 0.7 = 350, 20% = 70
        assert result["company_contribution"]["contribution_amount"] == 70
        assert result["company_contribution"]["contribution_rate"] == 0.2
        assert result["net_rewards"]["executor_net"] == 350 - 70

    def test_release_alice_in_company(self, services):
        """Alice is a member of AlphaCorp, so contribution applies."""
        escrow, dividend, _, agents, companies = services
        alice = agents["alice"]["agent_id"]
        carol = agents["carol"]["agent_id"]
        task_id = "t-alice-company"

        escrow.ensure_account(alice)
        # We need a publisher other than alice; use carol as publisher
        # Actually Alice is the executor and belongs to AlphaCorp
        # So the release should deduct from Alice's reward
        escrow.ensure_account(carol)
        escrow.hold(carol, task_id, 300)

        result = company_aware_release(
            escrow, dividend, task_id, carol, alice, 300,
        )
        # executor_reward = 300 * 0.7 = 210, 10% = 21
        contrib = result["company_contribution"]
        assert contrib is not None
        assert contrib["company_id"] == companies["alpha"]["company_id"]
        assert contrib["contribution_amount"] == 21
        assert result["net_rewards"]["executor_net"] == 210 - 21

    def test_release_zero_contribution_rate(self, services):
        """Zero contribution rate means no company contribution."""
        escrow, dividend, _, agents, companies = services
        alice = agents["alice"]["agent_id"]
        bob = agents["bob"]["agent_id"]
        task_id = "t-zero-rate"

        escrow.ensure_account(alice)
        escrow.hold(alice, task_id, 100)

        result = company_aware_release(
            escrow, dividend, task_id, alice, bob, 100,
            contribution_rate=0.0,
        )
        assert result["company_contribution"] is None
        assert result["net_rewards"]["executor_net"] == 70  # 100 * 0.7

    def test_release_with_different_shares(self, services):
        """Custom publisher/executor shares work correctly."""
        escrow, dividend, _, agents, companies = services
        alice = agents["alice"]["agent_id"]
        bob = agents["bob"]["agent_id"]
        task_id = "t-diff-shares"

        escrow.ensure_account(alice)
        escrow.hold(alice, task_id, 400)

        result = company_aware_release(
            escrow, dividend, task_id, alice, bob, 400,
            publisher_share=0.5,
            executor_share=0.5,
            contribution_rate=0.1,
        )
        # executor_reward = 200, 10% = 20
        assert result["release"]["executor_reward"] == 200
        assert result["release"]["publisher_return"] == 200
        assert result["company_contribution"]["contribution_amount"] == 20
        assert result["net_rewards"]["executor_net"] == 180


# ====================================================================
# Tests: get_company_earnings
# ====================================================================


class TestGetCompanyEarnings:
    """Tests for the company earnings aggregation."""

    def test_no_earnings(self, services):
        """Company with no earnings returns zero totals."""
        escrow, _, _, _, companies = services
        result = get_company_earnings(escrow, companies["alpha"]["company_id"])
        assert result["total_earnings"] == 0
        assert result["member_earnings"] == []

    def test_single_member_earnings(self, services):
        """Earnings from a single escrow release are captured."""
        escrow, dividend, _, agents, companies = services
        alice = agents["alice"]["agent_id"]
        bob = agents["bob"]["agent_id"]
        alpha_id = companies["alpha"]["company_id"]

        # Alice belongs to AlphaCorp; release funds to Alice (as executor)
        task_id = "t-earn-1"
        escrow.ensure_account(bob)
        escrow.hold(bob, task_id, 200)
        escrow.release(task_id, bob, alice, 200, 0.3, 0.7)

        result = get_company_earnings(escrow, alpha_id)
        assert result["total_earnings"] == 140  # 200 * 0.7
        assert len(result["member_earnings"]) == 1
        assert result["member_earnings"][0]["agent_id"] == alice
        assert result["member_earnings"][0]["total"] == 140

    def test_multiple_members_earnings(self, services):
        """Earnings from multiple company members are summed."""
        escrow, dividend, _, agents, companies = services
        alice = agents["alice"]["agent_id"]
        bob = agents["bob"]["agent_id"]
        carol = agents["carol"]["agent_id"]
        beta_id = companies["beta"]["company_id"]

        # Bob is a member of BetaInc; Carol is NOT a member of BetaInc
        # But Bob's company is BetaInc, so earnings from releases to Bob
        # should show up. Actually get_company_earnings queries all members
        # of a company and sums their release transactions.

        # Add Carol to BetaInc for this test
        escrow.conn.execute(
            "INSERT INTO company_members (company_id, agent_id, role) VALUES (?, ?, ?)",
            (beta_id, carol, "member"),
        )
        escrow.conn.commit()

        task1 = "t-multi-1"
        task2 = "t-multi-2"
        escrow.ensure_account(alice)
        escrow.hold(alice, task1, 300)
        escrow.hold(alice, task2, 100)

        escrow.release(task1, alice, bob, 300, 0.3, 0.7)     # Bob gets 210
        escrow.release(task2, alice, carol, 100, 0.3, 0.7)   # Carol gets 70

        result = get_company_earnings(escrow, beta_id)
        assert result["total_earnings"] == 280  # 210 + 70
        assert len(result["member_earnings"]) == 2
        for me in result["member_earnings"]:
            if me["agent_id"] == bob:
                assert me["total"] == 210
            elif me["agent_id"] == carol:
                assert me["total"] == 70

    def test_company_without_members(self, services):
        """Company with no members returns zero earnings."""
        escrow, _, _, _, _ = services
        no_member_id = uuid.uuid4().hex
        result = get_company_earnings(escrow, no_member_id)
        assert result["total_earnings"] == 0
        assert result["member_earnings"] == []


# ====================================================================
# Edge cases
# ====================================================================


class TestEdgeCases:
    """Edge cases for the integration layer."""

    def test_deposit_then_release_flow(self, services):
        """End-to-end flow: escrow deposit -> release -> company contribution."""
        escrow, dividend, _, agents, companies = services
        alice = agents["alice"]["agent_id"]
        bob = agents["bob"]["agent_id"]
        alpha_id = companies["alpha"]["company_id"]
        task_id = "t-e2e"

        # Alice (publisher) holds escrow
        escrow.ensure_account(alice)
        escrow.hold(alice, task_id, 500)

        # Bob (executor, BetaInc member) gets release with company contribution
        result = company_aware_release(
            escrow, dividend, task_id, alice, bob, 500,
        )
        contrib = result["company_contribution"]
        assert contrib is not None
        beta_contrib = contrib["contribution_amount"]  # 500*0.7*0.1 = 35

        # Also deposit directly into AlphaCorp's dividend fund
        escrow.deposit(alpha_id, 1000)
        dividend_deposit_from_escrow(escrow, dividend, alpha_id, 500)

        # Verify BetaInc dividend fund has the contribution
        beta_funds = dividend.get_available_funds(companies["beta"]["company_id"])
        assert len(beta_funds) == 1
        assert beta_funds[0]["total_amount"] == beta_contrib

        # Verify AlphaCorp dividend fund has the direct deposit
        alpha_funds = dividend.get_available_funds(alpha_id)
        assert len(alpha_funds) >= 1
        total_alpha = dividend.get_total_available(alpha_id)
        assert total_alpha == 500

    def test_company_aware_release_no_escrow_hold(self, services):
        """Release with insufficient frozen balance raises EscrowError."""
        escrow, dividend, _, agents, _ = services
        alice = agents["alice"]["agent_id"]
        bob = agents["bob"]["agent_id"]

        with pytest.raises(EscrowError, match="frozen balance mismatch"):
            company_aware_release(
                escrow, dividend, "no-hold", alice, bob, 999,
            )
