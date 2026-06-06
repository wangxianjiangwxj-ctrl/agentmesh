"""Tests for evidence chain (Module 3, v2 schema)."""
from __future__ import annotations

from pathlib import Path

import pytest
from db_schema import create_test_db
from evidence_chain import EvidenceChainService
from identity import IdentityService


@pytest.fixture
def services():
    """Create evidence chain service and identity service for testing."""
    conn, db_path = create_test_db()
    identity = IdentityService(db_path)
    identity._conn = conn
    evidence = EvidenceChainService(identity, conn)
    identity.register("Alice")
    identity.register("Bob")
    yield identity, evidence, "t-001"
    identity.close()
    conn.close()
    Path(db_path).unlink(missing_ok=True)


class TestEvidenceChain:
    def test_record_entry(self, services):
        """Verify recording an evidence entry returns a valid record with chain index."""
        identity, evidence, task_id = services
        alice = identity.get_agent_by_auth("")
        # get first agent
        alice = identity.fetch_all_registrations()[0]
        payload = {"task_id": task_id, "action": "publish"}

        entry = evidence.record(task_id, "publish", alice["id"], payload)
        assert entry.id
        assert entry.action == "publish"
        assert entry.signature
        assert entry.chain_index == 1
        assert entry.chain_hash
        assert entry.chain_prev_hash is None

    def test_chain_index_increments(self, services):
        """Verify each new evidence entry increments the chain index."""
        identity, evidence, task_id = services
        alice = identity.fetch_all_registrations()[0]
        bob = identity.fetch_all_registrations()[1]

        e1 = evidence.record(task_id, "publish", alice["id"], {"a": 1})
        e2 = evidence.record(task_id, "assign", bob["id"], {"a": 2})
        e3 = evidence.record(task_id, "deliver", alice["id"], {"a": 3})

        assert e1.chain_index == 1
        assert e2.chain_index == 2
        assert e3.chain_index == 3
        assert e2.chain_prev_hash == e1.chain_hash
        assert e3.chain_prev_hash == e2.chain_hash

    def test_secondary_signature(self, services):
        """Verify recording an entry with receiver's signature succeeds."""
        identity, evidence, task_id = services
        alice = identity.fetch_all_registrations()[0]
        bob = identity.fetch_all_registrations()[1]
        payload = {"task_id": task_id, "action": "deliver"}

        entry = evidence.record(
            task_id, "deliver", alice["id"], payload,
            secondary_actor_id=bob["id"],
        )
        assert entry.signature
        assert entry.secondary_sig
        assert entry.secondary_sig != entry.signature

    def test_verify_chain_valid(self, services):
        """Verify that an unmodified evidence chain passes verification."""
        identity, evidence, task_id = services
        alice = identity.fetch_all_registrations()[0]
        bob = identity.fetch_all_registrations()[1]

        evidence.record(task_id, "publish", alice["id"], {"a": 1})
        evidence.record(task_id, "assign", bob["id"], {"a": 2})
        evidence.record(task_id, "verify", alice["id"], {"a": 3})

        chain = evidence.verify_chain(task_id)
        assert len(chain) == 3
        assert all(e["chain_ok"] for e in chain)

    def test_tampered_hash_detected(self, services):
        """Verify that tampering with an entry's hash causes verification to fail."""
        identity, evidence, task_id = services
        alice = identity.fetch_all_registrations()[0]
        evidence.record(task_id, "publish", alice["id"], {"a": 1})
        evidence.conn.execute(
            "UPDATE evidence_chain SET chain_hash = 'corrupted' WHERE task_id = ?",
            (task_id,),
        )
        evidence.conn.commit()
        chain = evidence.verify_chain(task_id)
        assert not chain[0]["chain_ok"]

    def test_signature_verification(self, services):
        """Verify that a tampered entry signature causes verification to fail."""
        identity, evidence, task_id = services
        alice = identity.fetch_all_registrations()[0]
        payload = {"task_id": task_id, "reward": 100}

        entry = evidence.record(task_id, "publish", alice["id"], payload)
        assert evidence.verify_signature(alice["id"], payload, entry.signature)
        assert not evidence.verify_signature(alice["id"], {"task_id": "faked"}, entry.signature)

    def test_query_by_task(self, services):
        """Verify querying evidence entries by task ID returns matching records."""
        identity, evidence, task_id = services
        alice = identity.fetch_all_registrations()[0]
        evidence.record(task_id, "a", alice["id"], {"x": 1})
        evidence.record("t-002", "a", alice["id"], {"x": 2})

        logs = evidence.get_by_task(task_id)
        assert len(logs) == 1

    def test_query_by_actor(self, services):
        """Verify querying evidence entries by actor ID returns matching records."""
        identity, evidence, _ = services
        alice = identity.fetch_all_registrations()[0]
        evidence.record("t-001", "a", alice["id"], {"x": 1})
        evidence.record("t-002", "a", alice["id"], {"x": 2})

        logs = evidence.get_by_actor(alice["id"])
        assert len(logs) == 2

    def test_record_missing_actor_key(self, services):
        """record raises ValueError when actor has no private key."""
        identity, evidence, task_id = services
        alice = identity.fetch_all_registrations()[0]
        evidence.conn.execute(
            "DELETE FROM agent_private_keys WHERE agent_id = ?",
            (alice["id"],),
        )
        evidence.conn.commit()
        with pytest.raises(ValueError, match="Private key not found for actor"):
            evidence.record(task_id, "publish", alice["id"], {"x": 1})

    def test_record_missing_secondary_key(self, services):
        """record raises ValueError when secondary actor has no private key."""
        identity, evidence, task_id = services
        alice = identity.fetch_all_registrations()[0]
        bob = identity.fetch_all_registrations()[1]
        evidence.conn.execute(
            "DELETE FROM agent_private_keys WHERE agent_id = ?",
            (bob["id"],),
        )
        evidence.conn.commit()
        with pytest.raises(ValueError, match="Private key not found for"):
            evidence.record(task_id, "deliver", alice["id"], {"x": 1},
                            secondary_actor_id=bob["id"])

    def test_verify_signature_missing_agent(self, services):
        """verify_signature returns False for unknown agent."""
        _, evidence, _ = services
        assert evidence.verify_signature("bogus", {"x": 1}, "sig") is False

    def test_verify_chain_empty(self, services):
        """verify_chain returns empty list for non-existent task."""
        _, evidence, _ = services
        chain = evidence.verify_chain("nonexistent")
        assert chain == []
