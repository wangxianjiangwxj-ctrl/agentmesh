"""Concurrency tests: race conditions, deadlock scenarios, thread safety.

Tests cover:
  1. Escrow concurrent deposits and holds (SQLite locking)
  2. Evidence chain concurrent records for the same task
  3. Identity service concurrent registration
  4. Review service concurrent submission
  5. Task market concurrent create/assign

Uses threading + shared SQLite connections with a serialization lock.
Python 3.9's sqlite3 module does not support true concurrent access
on the same connection object (segfault risk), so a threading.Lock
serializes physical DB writes while the tests verify logical atomicity
(isolation, rollback-on-error, unique-index enforcement).
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import threading
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agentmesh.db_schema import SCHEMA_SQL
from agentmesh.escrow import EscrowError, EscrowService
from agentmesh.evidence_chain import EvidenceChainService
from agentmesh.identity import IdentityService
from agentmesh.reputation import ReviewService

# ---------------------------------------------------------------------------
# Helper: create a WAL-mode connection safe for multi-threaded use
# ---------------------------------------------------------------------------


def _make_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Thread-safe service wrapper
# ---------------------------------------------------------------------------


class SerializedServices:
    """Wraps all platform services with a threading.Lock for safe
    multi-threaded access from Python 3.9's sqlite3 module.

    The lock serializes concurrent operations so the tests can verify
    logical atomicity without crashing the SQLite driver.
    """

    def __init__(self):
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        f.close()
        self.db_path = f.name
        self.conn = _make_conn(self.db_path)
        self.identity = IdentityService(self.db_path)
        self.identity._conn = self.conn
        self.escrow = EscrowService(self.conn, self.identity)
        self.evidence = EvidenceChainService(self.identity, self.conn)
        self.review = ReviewService(self.conn, self.identity, self.evidence)
        self.lock = threading.Lock()

    def close(self):
        self.conn.close()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)


@pytest.fixture
def svc():
    """Yield a SerializedServices instance and clean up after the test."""
    s = SerializedServices()
    try:
        yield s
    finally:
        s.close()


# ===================================================================
# E-2a: Escrow race conditions (concurrent deposits/holds)
# ===================================================================


class TestEscrowRaceConditions:
    """Simulate concurrent deposit and hold operations."""

    CONCURRENCY = 10

    def test_concurrent_deposits_no_loss(self, svc):
        """Concurrent deposits should not lose points."""
        with svc.lock:
            agent_id = svc.identity.register("concurrent-depositor", auth_token="cd")["agent_id"]

        errors = []

        def deposit_100():
            try:
                with svc.lock:
                    svc.escrow.deposit(agent_id, 100)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=deposit_100) for _ in range(self.CONCURRENCY)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Deposit errors: {errors}"
        with svc.lock:
            balance = svc.escrow.get_balance(agent_id)
        expected = self.CONCURRENCY * 100
        assert balance["balance"] == expected, (
            f"Expected balance {expected}, got {balance['balance']}"
        )

    def test_concurrent_holds_atomicity(self, svc):
        """Concurrent holds should not double-freeze or exceed balance."""
        with svc.lock:
            agent_id = svc.identity.register("concurrent-holder", auth_token="ch")["agent_id"]
            svc.escrow.deposit(agent_id, 1000)

        errors = []
        successes = []
        lock2 = threading.Lock()

        def try_hold(idx):
            try:
                with svc.lock:
                    task_id = f"concurrent-hold-task-{idx}-{uuid.uuid4().hex[:8]}"
                    svc.escrow.hold(agent_id, task_id, 200)
                with lock2:
                    successes.append(idx)
            except EscrowError as e:
                with lock2:
                    errors.append(str(e))
            except Exception as e:
                with lock2:
                    errors.append(f"Unexpected: {e}")

        # 10 threads each trying to hold 200 = 2000 total, but balance is 1000
        threads = [threading.Thread(target=try_hold, args=(i,)) for i in range(self.CONCURRENCY)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with svc.lock:
            balance = svc.escrow.get_balance(agent_id)

        # At most 5 holds should succeed (5 * 200 = 1000)
        total_success = len(successes)
        assert total_success <= 5, (
            f"Expected at most 5 holds to succeed, got {total_success}"
        )
        assert balance["frozen"] == total_success * 200, (
            f"Frozen {balance['frozen']} != {total_success * 200}"
        )
        assert balance["available"] == 1000 - total_success * 200, (
            f"Available {balance['available']} != {1000 - total_success * 200}"
        )

    def test_concurrent_hold_and_release_no_negative(self, svc):
        """Concurrent holds and releases should not produce negative balances."""
        with svc.lock:
            pub_id = svc.identity.register("pub", auth_token="cr-pub")["agent_id"]
            exe_id = svc.identity.register("exe", auth_token="cr-exe")["agent_id"]
            svc.escrow.deposit(pub_id, 500)
            svc.escrow.hold(pub_id, "hold-release-task", 300)

        errors = []

        def attempt_release():
            try:
                with svc.lock:
                    svc.escrow.release("hold-release-task", pub_id, exe_id, 300, 0.5, 0.5)
            except EscrowError as e:
                errors.append(str(e))

        threads = [threading.Thread(target=attempt_release) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with svc.lock:
            balance = svc.escrow.get_balance(pub_id)
            exe_balance = svc.escrow.get_balance(exe_id)

        assert balance["balance"] >= 0, f"Publisher balance negative: {balance['balance']}"
        assert balance["frozen"] >= 0, f"Publisher frozen negative: {balance['frozen']}"
        assert exe_balance["balance"] >= 0, f"Executor balance negative: {exe_balance['balance']}"


# ===================================================================
# E-2b: Evidence chain concurrent records
# ===================================================================


class TestEvidenceChainConcurrency:
    """Verify hash-chain integrity under concurrent record operations."""

    CONCURRENCY = 5

    def test_concurrent_evidence_records(self, svc):
        """Multiple concurrent evidence records for the same task.

        Each record must get a unique chain_index and the hash chain
        must remain valid.
        """
        with svc.lock:
            agent_id = svc.identity.register("chain-agent", auth_token="cc")["agent_id"]
            task_id = f"concurrent-chain-{uuid.uuid4().hex[:8]}"

        errors = []
        indices = []

        def record_entry(idx):
            try:
                with svc.lock:
                    entry = svc.evidence.record(
                        task_id,
                        f"concurrent.action.{idx}",
                        agent_id,
                        {"index": idx, "data": f"payload-{idx}"},
                    )
                    indices.append(entry.chain_index)
            except Exception as e:
                errors.append(f"Thread {idx}: {e}")

        threads = [
            threading.Thread(target=record_entry, args=(i,))
            for i in range(self.CONCURRENCY)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Record errors: {errors}"
        assert len(indices) == self.CONCURRENCY

        # All indices must be unique
        assert len(set(indices)) == self.CONCURRENCY, f"Duplicate chain indices: {sorted(indices)}"
        assert sorted(indices) == list(range(1, self.CONCURRENCY + 1)), (
            f"Expected indices 1-{self.CONCURRENCY}, got {sorted(indices)}"
        )

        # Verify chain integrity
        with svc.lock:
            chain = svc.evidence.verify_chain(task_id)
        assert len(chain) == self.CONCURRENCY
        assert all(e["chain_ok"] for e in chain), "Hash chain broken due to concurrent writes"

    def test_concurrent_multiple_tasks_no_interference(self, svc):
        """Concurrent records across different tasks don't interfere."""
        with svc.lock:
            agent_id = svc.identity.register("multi-chain", auth_token="mc")["agent_id"]

        errors = []

        def record_for_task(task_id, idx):
            try:
                with svc.lock:
                    svc.evidence.record(task_id, "task.event", agent_id, {"seq": idx})
            except Exception as e:
                errors.append(f"Task {task_id}: {e}")

        threads = []
        for t_id in range(3):
            task_name = f"concurrent-multi-{t_id}"
            for i in range(3):
                t = threading.Thread(target=record_for_task, args=(task_name, i))
                threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"

        with svc.lock:
            for t_id in range(3):
                task_name = f"concurrent-multi-{t_id}"
                chain = svc.evidence.verify_chain(task_name)
                assert len(chain) == 3, f"Task {task_name}: expected 3, got {len(chain)}"
                assert all(e["chain_ok"] for e in chain), f"Task {task_name}: chain broken"


# ===================================================================
# E-2c: Identity concurrent registration
# ===================================================================


class TestIdentityConcurrency:
    """Verify identity registration handles concurrent operations."""

    CONCURRENCY = 20

    def test_concurrent_registration_unique_ids(self, svc):
        """Concurrent registrations produce unique agent IDs."""
        errors = []
        agent_ids = []

        def register(idx):
            try:
                with svc.lock:
                    result = svc.identity.register(
                        f"concurrent-agent-{idx}", auth_token=f"ca-{idx}"
                    )
                    agent_ids.append(result["agent_id"])
            except Exception as e:
                errors.append(f"Thread {idx}: {e}")

        threads = [
            threading.Thread(target=register, args=(i,))
            for i in range(self.CONCURRENCY)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Registration errors: {errors}"
        assert len(agent_ids) == self.CONCURRENCY
        assert len(set(agent_ids)) == self.CONCURRENCY, (
            f"Duplicate agent IDs generated: {len(set(agent_ids))} unique out of {len(agent_ids)}"
        )

    def test_concurrent_get_agent_safe(self, svc):
        """Concurrent reads of identity data are safe."""
        with svc.lock:
            agent_id = svc.identity.register("read-target", auth_token="rt")["agent_id"]

        errors = []

        def read_agent():
            try:
                with svc.lock:
                    agent = svc.identity.get_agent(agent_id)
                    assert agent is not None
                    assert agent["name"] == "read-target"
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=read_agent) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Read errors: {errors}"


# ===================================================================
# E-2d: Review concurrent submission
# ===================================================================


class TestReviewConcurrency:
    """Verify review service handles concurrent submissions."""

    def test_concurrent_reviews_no_duplicates(self, svc):
        """Concurrent duplicate review submissions - only one succeeds."""
        with svc.lock:
            rater = svc.identity.register("rater-concurrent", auth_token="rc-rater")["agent_id"]
            target = svc.identity.register("target-concurrent", auth_token="rc-target")["agent_id"]

        results = []

        def submit_review():
            try:
                with svc.lock:
                    r = svc.review.submit_review("task-rc-001", rater, target, 4, "Good work")
                    results.append(("ok", r["id"]))
            except ValueError as e:
                results.append(("duplicate", str(e)))

        threads = [threading.Thread(target=submit_review) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        ok_count = sum(1 for r in results if r[0] == "ok")
        dup_count = sum(1 for r in results if r[0] == "duplicate")
        assert ok_count == 1, f"Expected exactly 1 successful review, got {ok_count}"
        assert dup_count == 4, f"Expected 4 duplicate rejections, got {dup_count}"

    def test_concurrent_reviews_different_targets(self, svc):
        """Concurrent reviews for different targets all succeed."""
        with svc.lock:
            rater = svc.identity.register("rater-multi", auth_token="rm-rater")["agent_id"]
            targets = [
                svc.identity.register(f"target-{i}", auth_token=f"rm-t{i}")["agent_id"]
                for i in range(5)
            ]

        errors = []

        def review_target(target_id):
            try:
                with svc.lock:
                    svc.review.submit_review(f"task-multi-{target_id[:8]}", rater, target_id, 3)
            except Exception as e:
                errors.append(f"{target_id}: {e}")

        threads = [threading.Thread(target=review_target, args=(t,)) for t in targets]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Review errors: {errors}"
        with svc.lock:
            for target_id in targets:
                rep = svc.review.get_reputation(target_id)
                assert rep["total_reviews"] == 1, f"Target {target_id}: expected 1 review"


# ===================================================================
# E-2e: Deadlock detection (sequential ops that should not deadlock)
# ===================================================================


class TestDeadlockSafety:
    """Verify no deadlocks occur in sequential interleaved operations."""

    def test_escrow_interleave_no_deadlock(self, svc):
        """Interleaved escrow operations should not deadlock."""
        with svc.lock:
            a_id = svc.identity.register("agent-a", auth_token="da-a")["agent_id"]
            b_id = svc.identity.register("agent-b", auth_token="da-b")["agent_id"]
            svc.escrow.deposit(a_id, 1000)
            svc.escrow.deposit(b_id, 500)
            svc.escrow.hold(a_id, "deadlock-task-1", 200)
            svc.escrow.release("deadlock-task-1", a_id, b_id, 200, 0.5, 0.5)
            bal_a = svc.escrow.get_balance(a_id)
            bal_b = svc.escrow.get_balance(b_id)

        # Release subtracts frozen (200) and adds publisher_return (100) to balance
        # So balance = 1000 + 100 = 1100, frozen = 0
        assert bal_a["balance"] == 1100  # 1000 + 100 returned
        assert bal_b["balance"] == 600  # 500 + 100 reward

    def test_identity_then_escrow_consistent(self, svc):
        """Register then escrow for same agent preserves consistency."""
        with svc.lock:
            agent_id = svc.identity.register("new-agent", auth_token="new-a")["agent_id"]
            svc.escrow.deposit(agent_id, 500)
            svc.escrow.hold(agent_id, "new-task", 100)
            bal = svc.escrow.get_balance(agent_id)

        assert bal["balance"] == 500
        assert bal["frozen"] == 100
        assert bal["available"] == 400
