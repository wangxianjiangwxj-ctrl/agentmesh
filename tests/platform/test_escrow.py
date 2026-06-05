"""Tests for escrow (Module 4, v2 schema: accounts table)."""
from __future__ import annotations

from pathlib import Path

import pytest

from db_schema import create_test_db
from identity import IdentityService
from escrow import EscrowService, EscrowError


@pytest.fixture
def escrow_svc():
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
        escrow, _, _, _, _ = escrow_svc
        bal = escrow.get_balance("nonexistent")
        assert bal["balance"] == 0

    def test_deposit(self, escrow_svc):
        escrow, _, alice, _, _ = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        bal = escrow.get_balance(alice["agent_id"])
        assert bal["balance"] == 1000
        assert bal["available"] == 1000

    def test_hold(self, escrow_svc):
        escrow, _, alice, _, _ = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        escrow.hold(alice["agent_id"], "t-001", 300)
        bal = escrow.get_balance(alice["agent_id"])
        assert bal["frozen"] == 300
        assert bal["available"] == 700

    def test_hold_insufficient(self, escrow_svc):
        escrow, _, alice, _, _ = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        with pytest.raises(EscrowError, match="Insufficient"):
            escrow.hold(alice["agent_id"], "t-001", 9999)

    def test_release(self, escrow_svc):
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
        escrow, _, alice, _, task_id = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        escrow.hold(alice["agent_id"], task_id, 200)
        escrow.refund(task_id, alice["agent_id"], 200)
        bal = escrow.get_balance(alice["agent_id"])
        assert bal["frozen"] == 0
        assert bal["available"] == 1000

    def test_auto_release_not_eligible(self, escrow_svc):
        escrow, _, alice, _, task_id = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        escrow.hold(alice["agent_id"], task_id, 100)
        assert escrow.auto_release(task_id) is None

    def test_tx_history(self, escrow_svc):
        escrow, _, alice, bob, task_id = escrow_svc
        escrow.ensure_account(alice["agent_id"])
        escrow.hold(alice["agent_id"], task_id, 100)
        escrow.release(task_id, alice["agent_id"], bob["agent_id"], 100, 0.5, 0.5)

        txs = escrow.get_transactions(task_id)
        assert len(txs) == 2
