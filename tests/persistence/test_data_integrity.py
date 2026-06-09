"""Data persistence and integrity tests.

Tests cover:
  1. Restart recovery: write data, close DB, reopen, verify
  2. Transaction rollback on error
  3. Schema compatibility / migration
  4. Data consistency across modules (cross-table referential integrity)
  5. Evidence chain persistence across DB reopen
  6. WAL mode crash recovery characteristics
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agentmesh.db_schema import SCHEMA_SQL, init_db
from agentmesh.escrow import EscrowError, EscrowService
from agentmesh.evidence_chain import EvidenceChainService
from agentmesh.identity import IdentityService
from agentmesh.reputation import ReviewService

# ===================================================================
# Helpers
# ===================================================================


def _create_full_services(db_path):
    """Re-create all services against a given DB path.

    This simulates a "restart" — services are initialized from
    scratch against an existing database file.
    """
    conn = init_db(db_path)
    identity = IdentityService(db_path)
    identity._conn = conn
    escrow = EscrowService(conn, identity)
    evidence = EvidenceChainService(identity, conn)
    review = ReviewService(conn, identity, evidence)
    return conn, identity, escrow, evidence, review


# ===================================================================
# E-3a: Restart recovery (write -> close -> reopen -> verify)
# ===================================================================


class TestRestartRecovery:
    """Verify data survives a close-reopen cycle."""

    def test_identity_persistence_across_restart(self):
        """Agent identity data survives DB close/reopen."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            # -- First session --
            conn1 = init_db(db_path)
            id1 = IdentityService(db_path)
            id1._conn = conn1
            agent_id = id1.register("persistent-agent", auth_token="persist")["agent_id"]
            conn1.close()

            # -- Simulate restart --
            conn2 = init_db(db_path)
            id2 = IdentityService(db_path)
            id2._conn = conn2
            agent = id2.get_agent(agent_id)
            assert agent is not None, "Agent lost after restart"
            assert agent["name"] == "persistent-agent"
            assert agent["auth_token"] == "persist"
            assert agent["public_key"] is not None
            conn2.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_escrow_balance_survives_restart(self):
        """Escrow balance data survives DB close/reopen."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn1, id1, esc1, _, _ = _create_full_services(db_path)
            agent_id = id1.register("escrow-agent", auth_token="esc-persist")["agent_id"]
            esc1.deposit(agent_id, 500)
            esc1.hold(agent_id, "persist-task", 100)
            bal_before = esc1.get_balance(agent_id)
            conn1.close()

            conn2, id2, esc2, _, _ = _create_full_services(db_path)
            bal_after = esc2.get_balance(agent_id)
            assert bal_after == bal_before, (
                f"Balance changed after restart: {bal_before} -> {bal_after}"
            )
            assert bal_after["balance"] == 500
            assert bal_after["frozen"] == 100
            assert bal_after["available"] == 400
            conn2.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_evidence_chain_survives_restart(self):
        """Evidence chain data and integrity survive DB close/reopen."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn1, id1, _, ev1, _ = _create_full_services(db_path)
            agent_id = id1.register("chain-persist", auth_token="cp")["agent_id"]
            ev1.record("persist-chain-task", "task.created", agent_id, {"step": 1})
            ev1.record("persist-chain-task", "task.assigned", agent_id, {"step": 2})
            conn1.close()

            conn2, id2, _, ev2, _ = _create_full_services(db_path)
            chain = ev2.verify_chain("persist-chain-task")
            assert len(chain) == 2, f"Expected 2 entries, got {len(chain)}"
            assert all(e["chain_ok"] for e in chain), "Chain integrity broken after restart"
            assert chain[0]["action"] == "task.created"
            assert chain[1]["action"] == "task.assigned"
            conn2.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_review_data_survives_restart(self):
        """Review and reputation data survive DB close/reopen."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn1, id1, _, ev1, rv1 = _create_full_services(db_path)
            rater = id1.register("review-rater", auth_token="rr")["agent_id"]
            target = id1.register("review-target", auth_token="rt")["agent_id"]
            rv1.submit_review("persist-review-task", rater, target, 5, "Excellent")
            rep_before = rv1.get_reputation(target)
            conn1.close()

            conn2, id2, _, ev2, rv2 = _create_full_services(db_path)
            rep_after = rv2.get_reputation(target)
            reviews = rv2.get_reviews_for_target(target)
            assert len(reviews) == 1
            assert reviews[0]["rating"] == 5
            assert rep_after["avg_rating"] == rep_before["avg_rating"]
            assert rep_after["total_reviews"] == 1
            conn2.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ===================================================================
# E-3b: Transaction rollback on error
# ===================================================================


class TestTransactionRollback:
    """Verify partial writes are rolled back on error."""

    def test_escrow_deposit_with_invalid_amount_rolls_back(self):
        """Deposit with negative amount raises error and does not write."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn, id_svc, esc, _, _ = _create_full_services(db_path)
            agent_id = id_svc.register("rollback-agent", auth_token="rb")["agent_id"]

            # Attempt invalid deposit
            with pytest.raises(EscrowError):
                esc.deposit(agent_id, -100)

            # Balance should remain unchanged (or zero if never deposited)
            bal = esc.get_balance(agent_id)
            assert bal["balance"] == 0, f"Balance changed after failed deposit: {bal}"
            conn.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_escrow_hold_exceeding_balance_rolls_back(self):
        """Hold exceeding balance raises error and does not freeze."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn, id_svc, esc, _, _ = _create_full_services(db_path)
            agent_id = id_svc.register("poor-agent", auth_token="pa")["agent_id"]
            esc.deposit(agent_id, 100)

            with pytest.raises(EscrowError):
                esc.hold(agent_id, "task-over", 9999)

            # No frozen amount should be recorded
            bal = esc.get_balance(agent_id)
            assert bal["frozen"] == 0, "Frozen balance changed after failed hold"
            assert bal["balance"] == 100, "Balance changed after failed hold"
            conn.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ===================================================================
# E-3c: Schema compatibility
# ===================================================================


class TestSchemaCompatibility:
    """Verify schema persists correctly across initializations."""

    def test_schema_is_idempotent(self):
        """Running init_db multiple times on the same file is safe."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            # First init
            conn1 = init_db(db_path)
            conn1.close()

            # Second init (should be a no-op)
            conn2 = init_db(db_path)
            conn2.close()

            # Third init
            conn3 = init_db(db_path)
            conn3.close()

            # Verify schema is intact by writing and reading
            conn4 = init_db(db_path)
            conn4.execute(
                "INSERT INTO agents (id, did, name, public_key) VALUES (?, ?, ?, ?)",
                ("test-id", "did:agentmesh:key:test", "test-agent", "test-pk"),
            )
            conn4.commit()
            row = conn4.execute("SELECT name FROM agents WHERE id = ?", ("test-id",)).fetchone()
            assert row["name"] == "test-agent"
            conn4.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_schema_contains_all_expected_tables(self):
        """Verify all expected tables exist in the schema."""
        expected_tables = [
            "agents",
            "agent_private_keys",
            "tasks",
            "task_bids",
            "evidence_chain",
            "evidence_chain_heads",
            "accounts",
            "transactions",
            "reviews",
            "agent_reputation",
            "revenue_shares",
        ]
        for table in expected_tables:
            assert table in SCHEMA_SQL, f"Table '{table}' not found in SCHEMA_SQL"

    def test_schema_has_unique_constraints(self):
        """Schema defines UNIQUE constraints for key fields."""
        assert "UNIQUE" in SCHEMA_SQL, "Schema has no UNIQUE constraints"
        # Check for either inline UNIQUE (e.g. "did TEXT UNIQUE NOT NULL")
        # or CREATE UNIQUE INDEX statements
        has_inline = "UNIQUE NOT" in SCHEMA_SQL
        has_index = "CREATE UNIQUE" in SCHEMA_SQL
        assert has_inline or has_index, (
            "Schema has neither inline UNIQUE constraints nor UNIQUE INDEX statements"
        )


# ===================================================================
# E-3d: Cross-module data consistency
# ===================================================================


class TestCrossModuleConsistency:
    """Verify data consistency across identity + escrow + evidence + review."""

    def test_full_workflow_persists_correctly(self):
        """Full workflow data persists correctly and remains consistent."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            # Setup
            conn, id_svc, esc, ev, rv = _create_full_services(db_path)
            pub = id_svc.register("publisher", auth_token="pub-consist")["agent_id"]
            exe = id_svc.register("executor", auth_token="exe-consist")["agent_id"]
            esc.deposit(pub, 1000)

            # Hold
            esc.hold(pub, "consist-task", 300)
            ev.record("consist-task", "task.created", pub, {"escrow": 300})

            # Release
            result = esc.release("consist-task", pub, exe, 300, 0.5, 0.5)
            ev.record("consist-task", "task.settled", pub, {"reward": result["executor_reward"]})

            # Review
            rv.submit_review("consist-task", pub, exe, 5)
            conn.close()

            # -- Restart and verify all --
            conn2, id_svc2, esc2, ev2, rv2 = _create_full_services(db_path)

            pub_agent = id_svc2.get_agent(pub)
            assert pub_agent is not None

            bal_pub = esc2.get_balance(pub)
            bal_exe = esc2.get_balance(exe)
            # Release subtracts frozen (300) and adds publisher_return (150) to balance
            # So balance = 1000 + 150 = 1150
            assert bal_pub["balance"] == 1150  # 1000 + 150 returned
            assert bal_exe["balance"] == 150  # 150 reward

            chain = ev2.verify_chain("consist-task")
            assert len(chain) == 2
            assert all(e["chain_ok"] for e in chain)

            rep = rv2.get_reputation(exe)
            assert rep["total_reviews"] == 1
            assert rep["avg_rating"] > 0

            conn2.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ===================================================================
# E-3e: Evidence chain hash persistence
# ===================================================================


class TestEvidenceChainPersistence:
    """Verify evidence hash-chain data remains valid across DB reopen."""

    def test_long_chain_survives_restart(self):
        """A long evidence chain survives restart with full integrity."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn1, id1, _, ev1, _ = _create_full_services(db_path)
            agent_id = id1.register("long-chain", auth_token="lc")["agent_id"]

            actions = [f"event.{i}" for i in range(20)]
            for i, action in enumerate(actions):
                ev1.record("long-chain-task", action, agent_id, {"seq": i, "data": f"payload-{i}"})
            conn1.close()

            conn2, id2, _, ev2, _ = _create_full_services(db_path)
            chain = ev2.verify_chain("long-chain-task")
            assert len(chain) == 20
            assert all(e["chain_ok"] for e in chain), (
                "Long chain has broken entries after restart"
            )
            # Verify sequential ordering
            indices = [e["chain_index"] for e in chain]
            assert indices == list(range(1, 21)), f"Chain indices out of order: {indices}"
            conn2.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# ===================================================================
# E-3f: WAL mode pragmas
# ===================================================================


class TestWALMode:
    """Verify WAL journal mode is enabled for crash resilience."""

    def test_wal_mode_enabled(self):
        """Database connection has WAL journal mode."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = init_db(db_path)
            cursor = conn.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            assert mode in ("wal",), f"Expected WAL, got {mode}"
            conn.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_wal_pragma_on_each_connection(self):
        """Each new connection sets WAL mode."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            for _ in range(3):
                conn = init_db(db_path)
                cursor = conn.execute("PRAGMA journal_mode")
                mode = cursor.fetchone()[0]
                assert mode == "wal", f"Expected WAL, got {mode}"
                conn.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)
