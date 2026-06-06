"""Tests for audit chain (Module 3)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from db_schema import create_test_db
from identity import IdentityService
from audit_chain import AuditChainService


@pytest.fixture
def services():
    """Provide (identity_svc, audit_svc) with shared test DB."""
    conn, db_path = create_test_db()
    identity_svc = IdentityService(db_path)
    identity_svc._conn = conn  # reuse same connection
    audit_svc = AuditChainService(identity_svc, conn)
    identity_svc.register("Alice")
    identity_svc.register("Bob")
    yield identity_svc, audit_svc
    identity_svc.close()
    conn.close()
    Path(db_path).unlink(missing_ok=True)


class TestAuditChain:
    def test_record_entry(self, services):
        identity, audit = services
        alice = identity.register("Alice")
        payload = {"task_id": "t-001", "action": "publish"}

        entry = audit.record(
            task_id="t-001",
            action="publish",
            actor_id=alice["agent_id"],
            payload=payload,
        )
        assert entry.id
        assert entry.action == "publish"
        assert entry.sender_sig
        assert entry.chain_hash
        assert entry.chain_prev_hash is None  # first entry

    def test_double_sign_entry(self, services):
        identity, audit = services
        alice = identity.register("Alice")
        bob = identity.register("Bob")
        payload = {"task_id": "t-001", "action": "deliver"}

        entry = audit.record(
            task_id="t-001",
            action="deliver",
            actor_id=alice["agent_id"],
            payload=payload,
            receiver_id=bob["agent_id"],
        )
        assert entry.sender_sig
        assert entry.receiver_sig
        assert entry.receiver_sig != entry.sender_sig

    def test_hash_chain_links_entries(self, services):
        identity, audit = services
        alice = identity.register("Alice")
        bob = identity.register("Bob")

        # Three entries in sequence
        e1 = audit.record("t-001", "publish", alice["agent_id"], {"action": "publish"})
        e2 = audit.record("t-001", "assign", bob["agent_id"], {"action": "assign"}, receiver_id=alice["agent_id"])
        e3 = audit.record("t-001", "deliver", alice["agent_id"], {"action": "deliver"}, receiver_id=bob["agent_id"])

        assert e1.chain_prev_hash is None
        assert e2.chain_prev_hash == e1.chain_hash
        assert e3.chain_prev_hash == e2.chain_hash

    def test_verify_chain_valid(self, services):
        identity, audit = services
        alice = identity.register("Alice")
        bob = identity.register("Bob")
        payload = {"task_id": "t-001", "action": "publish"}
        audit.record("t-001", "publish", alice["agent_id"], payload)
        audit.record("t-001", "assign", bob["agent_id"], payload, receiver_id=alice["agent_id"])
        audit.record("t-001", "verify", alice["agent_id"], payload)

        chain = audit.verify_chain("t-001")
        assert len(chain) == 3
        assert all(e["chain_ok"] for e in chain)

    def test_tampered_hash_detected(self, services):
        identity, audit = services
        alice = identity.register("Alice")
        payload = {"task_id": "t-001", "action": "publish"}
        audit.record("t-001", "publish", alice["agent_id"], payload)

        # Manually corrupt the chain_hash in DB
        audit.conn.execute(
            "UPDATE audit_log SET chain_hash = 'corrupted' WHERE task_id = 't-001'"
        )
        audit.conn.commit()

        chain = audit.verify_chain("t-001")
        assert len(chain) == 1
        assert not chain[0]["chain_ok"]

    def test_payload_signature_verification(self, services):
        identity, audit = services
        alice = identity.register("Alice")
        payload = {"task_id": "t-001", "reward": 100}

        entry = audit.record("t-001", "publish", alice["agent_id"], payload)
        assert audit.verify_signature_for_audit(alice["agent_id"], payload, entry.sender_sig)

        # Tampered payload should fail verification
        assert not audit.verify_signature_for_audit(alice["agent_id"], {"task_id": "t-002"}, entry.sender_sig)

    def test_query_by_task(self, services):
        identity, audit = services
        alice = identity.register("Alice")
        audit.record("t-001", "publish", alice["agent_id"], {"action": "a"})
        audit.record("t-002", "publish", alice["agent_id"], {"action": "b"})
        audit.record("t-001", "verify", alice["agent_id"], {"action": "c"})

        logs = audit.get_by_task("t-001")
        assert len(logs) == 2

    def test_query_by_actor(self, services):
        identity, audit = services
        alice = identity.register("Alice")
        bob = identity.register("Bob")
        audit.record("t-001", "publish", alice["agent_id"], {"a": 1})
        audit.record("t-002", "publish", bob["agent_id"], {"b": 2})
        audit.record("t-003", "publish", alice["agent_id"], {"c": 3})

        logs = audit.get_by_actor(alice["agent_id"])
        assert len(logs) == 2
