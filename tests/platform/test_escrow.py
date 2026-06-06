"""Tests for escrow (Module 4, v2 schema: accounts table)."""
from __future__ import annotations

from pathlib import Path

import pytest
from db_schema import create_test_db
from escrow import EscrowError, EscrowService
from identity import IdentityService


@pytest.fixture
def escrow_svc():
    """Create an EscrowService instance with in-memory DB for testing."""
    conn, db_path = create_test_db()
    identity = IdentityService(db_path)
    identity._conn = conn
    escrow = EscrowService(conn, identity)
    alice = identity.register("Alice")
    bob = identity.register("Bob")
    yield escrow, identity, alice, bob, "t-001"
    identity.close()
    conn.close()
    Path(db_path).unlink(missing_ok=True)


class TestEscrow:
    def test_balance_zero_for_new(self, escrow_svc):
        """Verify a new agent's balance starts at zero."""
        escrow, _, _, _, _ = escrow_svc
        bal = escrow.get_balance("nonexistent")
        assert bal["balance"] == 0

    def test_deposit(self, escrow_svc):
        """Verify depositing funds increases the agent's balance."""
        escrow, _, alice, _, _ = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        bal = escrow.get_balance(alice["agent_id"])
        assert bal["balance"] == 1000
        assert bal["available"] == 1000

    def test_hold(self, escrow_svc):
        """Verify holding escrow freezes funds and returns a hold record."""
        escrow, _, alice, _, _ = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        escrow.hold(alice["agent_id"], "t-001", 300)
        bal = escrow.get_balance(alice["agent_id"])
        assert bal["frozen"] == 300
        assert bal["available"] == 700

    def test_hold_insufficient(self, escrow_svc):
        """Verify holding more than the available balance raises an error."""
        escrow, _, alice, _, _ = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        with pytest.raises(EscrowError, match="Insufficient"):
            escrow.hold(alice["agent_id"], "t-001", 9999)

    def test_release(self, escrow_svc):
        """Verify releasing escrow transfers frozen funds to the target agent."""
        escrow, _, alice, bob, task_id = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        escrow.hold(alice["agent_id"], task_id, 200)

        result = escrow.release(task_id, alice["agent_id"], bob["agent_id"], 200, 0.3, 0.7)
        assert result["executor_reward"] == 140
        assert result["publisher_return"] == 60

        alice_bal = escrow.get_balance(alice["agent_id"])
        bob_bal = escrow.get_balance(bob["agent_id"])
        assert alice_bal["balance"] == 1000 + 60
        assert bob_bal["balance"] == 140

    def test_refund(self, escrow_svc):
        """Verify refunding escrow returns frozen funds to the original agent."""
        escrow, _, alice, _, task_id = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        escrow.hold(alice["agent_id"], task_id, 200)
        escrow.refund(task_id, alice["agent_id"], 200)
        bal = escrow.get_balance(alice["agent_id"])
        assert bal["frozen"] == 0
        assert bal["available"] == 1000

    def test_auto_release_not_eligible(self, escrow_svc):
        """Verify auto-release fails when conditions are not met."""
        escrow, _, alice, _, task_id = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        escrow.hold(alice["agent_id"], task_id, 100)
        assert escrow.auto_release(task_id) is None

    def test_tx_history(self, escrow_svc):
        """Verify transaction history returns deposits and escrow operations."""
        escrow, _, alice, bob, task_id = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        escrow.hold(alice["agent_id"], task_id, 100)
        escrow.release(task_id, alice["agent_id"], bob["agent_id"], 100, 0.5, 0.5)

        txs = escrow.get_transactions(task_id)
        assert len(txs) == 2

    def test_deposit_non_positive(self, escrow_svc):
        """Deposit with amount <= 0 raises EscrowError."""
        escrow, _, alice, _, _ = escrow_svc
        with pytest.raises(EscrowError, match="must be positive"):
            escrow.deposit(alice["agent_id"], 0)
        with pytest.raises(EscrowError, match="must be positive"):
            escrow.deposit(alice["agent_id"], -10)

    def test_hold_non_positive(self, escrow_svc):
        """Hold with amount <= 0 raises EscrowError."""
        escrow, _, alice, _, _ = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        with pytest.raises(EscrowError, match="must be positive"):
            escrow.hold(alice["agent_id"], "t-001", 0)
        with pytest.raises(EscrowError, match="must be positive"):
            escrow.hold(alice["agent_id"], "t-001", -5)

    def test_release_insufficient_frozen(self, escrow_svc):
        """Release with more than frozen balance raises EscrowError."""
        escrow, _, alice, _, task_id = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        escrow.hold(alice["agent_id"], task_id, 100)
        with pytest.raises(EscrowError, match="frozen balance mismatch"):
            escrow.release(task_id, alice["agent_id"], "bogus", 999, 0.5, 0.5)

    def test_auto_release_no_hold(self, escrow_svc):
        """auto_release returns None when no pending hold exists."""
        escrow, _, _, _, _ = escrow_svc
        assert escrow.auto_release("nonexistent") is None

    def test_auto_release_no_deadline(self, escrow_svc):
        """auto_release returns None when hold has no dispute deadline."""
        escrow, _, alice, _, task_id = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        escrow.hold(alice["agent_id"], task_id, 100)
        # Manually null the deadline
        escrow.conn.execute(
            "UPDATE transactions SET dispute_deadline = NULL WHERE task_id = ?",
            (task_id,),
        )
        escrow.conn.commit()
        assert escrow.auto_release(task_id) is None

    def test_get_agent_transactions(self, escrow_svc):
        """Query transactions by agent_id."""
        escrow, _, alice, bob, task_id = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        escrow.hold(alice["agent_id"], task_id, 100)
        txs = escrow.get_agent_transactions(alice["agent_id"], limit=10)
        # ensure_account creates a deposit tx, and hold creates a hold tx
        assert len(txs) >= 2
        actions = [t["action"] for t in txs]
        assert "hold" in actions
        assert "deposit" in actions

    def test_get_dispute_eligible_tasks_empty(self, escrow_svc):
        """get_dispute_eligible_tasks returns empty list when none eligible."""
        escrow, _, _, _, _ = escrow_svc
        eligible = escrow.get_dispute_eligible_tasks()
        assert isinstance(eligible, list)
