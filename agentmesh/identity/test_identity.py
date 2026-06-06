"""Tests for identity module."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from identity import (
    IdentityService,
    create_service,
    generate_agent_keypair,
    encode_public_key,
    decode_public_key,
    make_did,
    parse_did,
    sign,
    verify,
    double_sign,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path() -> str:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        return f.name


@pytest.fixture
def svc(db_path: str) -> IdentityService:
    svc = create_service(db_path)
    yield svc
    svc.close()
    Path(db_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Key operations
# ---------------------------------------------------------------------------

class TestKeyOps:
    def test_generate_and_encode(self):
        priv, pub = generate_agent_keypair()
        encoded = encode_public_key(pub)
        assert isinstance(encoded, str)
        assert len(encoded) > 20

    def test_roundtrip_public_key(self):
        _, pub = generate_agent_keypair()
        encoded = encode_public_key(pub)
        restored = decode_public_key(encoded)
        assert restored.public_bytes_raw() == pub.public_bytes_raw()

    def test_did(self):
        _, pub = generate_agent_keypair()
        did = make_did(pub)
        assert did.startswith("did:agentmesh:key:")
        assert parse_did(did) is not None

    def test_bad_did_returns_none(self):
        assert parse_did("did:other:abc") is None
        assert parse_did("") is None


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------

class TestSigning:
    def test_sign_and_verify(self):
        priv, pub = generate_agent_keypair()
        payload = {"task_id": "t-001", "action": "deliver"}
        sig = sign(payload, priv)
        assert verify(payload, sig, pub) is True

    def test_tampered_payload_fails(self):
        priv, pub = generate_agent_keypair()
        payload = {"task_id": "t-001"}
        sig = sign(payload, priv)
        tampered = {"task_id": "t-002"}
        assert verify(tampered, sig, pub) is False

    def test_double_sign(self):
        sender_priv, _ = generate_agent_keypair()
        receiver_priv, _ = generate_agent_keypair()
        payload = {"task_id": "t-001", "reward": 50}
        envelope = double_sign(payload, sender_priv, receiver_priv)
        assert "sender_signature" in envelope
        assert "receiver_signature" in envelope
        assert envelope["payload"] == payload


# ---------------------------------------------------------------------------
# IdentityService
# ---------------------------------------------------------------------------

class TestIdentityService:
    def test_register_and_retrieve(self, svc: IdentityService):
        agent = svc.register("Alice", auth_token="feishu_alice")
        assert agent["agent_id"]
        assert agent["did"].startswith("did:agentmesh:key:")
        assert agent["name"] == "Alice"

        # retrieve by ID
        fetched = svc.get_agent(agent["agent_id"])
        assert fetched is not None
        assert fetched["name"] == "Alice"

        # by auth token
        fetched2 = svc.get_agent_by_auth("feishu_alice")
        assert fetched2 is not None
        assert fetched2["id"] == agent["agent_id"]

    def test_register_sets_private_key(self, svc: IdentityService):
        agent = svc.register("Bob")
        priv = svc.get_private_key(agent["agent_id"])
        assert priv is not None

    def test_sign_with_service(self, svc: IdentityService):
        agent = svc.register("Carol")
        payload = {"msg": "hello"}
        sig = svc.sign_payload(agent["agent_id"], payload)
        assert sig is not None
        assert svc.verify_signature(agent["did"], payload, sig) is True

    def test_double_sign_service(self, svc: IdentityService):
        alice = svc.register("Alice")
        bob = svc.register("Bob")
        payload = {"task_id": "t-001"}

        sig_alice = svc.sign_payload(alice["agent_id"], payload)
        sig_bob = svc.sign_payload(bob["agent_id"], payload)
        assert sig_alice and sig_bob
        assert svc.verify_signature(alice["did"], payload, sig_alice)
        assert svc.verify_signature(bob["did"], payload, sig_bob)

    def test_list_agents(self, svc: IdentityService):
        svc.register("A")
        svc.register("B")
        all_ = svc.fetch_all_registrations()
        assert len(all_) == 2

    def test_rejects_duplicate_did(self, svc: IdentityService):
        agent = svc.register("A")
        with pytest.raises(Exception):
            # re-register same DID should fail
            svc.conn.execute(
                "INSERT INTO agents (id, did, name, public_key) VALUES (?, ?, 'B', 'abc')",
                ("x", agent["did"]),
            )
