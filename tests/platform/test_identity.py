"""Tests for identity module (Module 1)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from db_schema import create_test_db
from identity import (
    DID_PREFIX,
    IdentityService,
    create_service,
    decode_private_key,
    decode_public_key,
    double_sign,
    encode_private_key,
    encode_public_key,
    generate_agent_keypair,
    make_did,
    parse_did,
    sign,
    verify,
)


@pytest.fixture
def fresh_identity():
    """IdentityService using its own lazy-init connection (no _conn override)."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    svc = IdentityService(f.name)
    yield svc
    svc.close()
    Path(f.name).unlink(missing_ok=True)


@pytest.fixture
def identity_and_conn():
    """IdentityService with a shared test DB (like other test fixtures)."""
    conn, db_path = create_test_db()
    svc = IdentityService(db_path)
    svc._conn = conn
    yield svc, conn
    svc.close()
    conn.close()
    Path(db_path).unlink(missing_ok=True)


class TestIdentityHelpers:
    def test_parse_did_valid(self):
        """Verify that a valid DID string is parsed correctly."""
        priv, pub = generate_agent_keypair()
        did = make_did(pub)
        parsed = parse_did(did)
        assert parsed == encode_public_key(pub)

    def test_parse_did_invalid(self):
        """Verify that an invalid DID string raises an error."""
        assert parse_did("not-a-did") is None
        assert parse_did("did:other:key:abc123") is None

    def test_parse_did_empty(self):
        """Verify that an empty DID string raises an error."""
        assert parse_did("") is None

    def test_sign_verify_roundtrip(self):
        """Verify sign-then-verify roundtrip works for a valid payload."""
        priv, pub = generate_agent_keypair()
        payload = {"hello": "world", "num": 42}
        sig = sign(payload, priv)
        assert verify(payload, sig, pub) is True

    def test_sign_verify_tampered(self):
        """Verify that a tampered payload fails signature verification."""
        priv, pub = generate_agent_keypair()
        payload = {"msg": "original"}
        sig = sign(payload, priv)
        assert verify({"msg": "tampered"}, sig, pub) is False

    def test_double_sign(self):
        """Verify that a sender can double-sign a payload to a receiver."""
        sender_priv, _ = generate_agent_keypair()
        receiver_priv, _ = generate_agent_keypair()
        payload = {"task": "abc"}
        envelope = double_sign(payload, sender_priv, receiver_priv)
        assert "sender_signature" in envelope
        assert "receiver_signature" in envelope
        assert envelope["sender_signature"] != envelope["receiver_signature"]

    def test_double_sign_no_receiver(self):
        """Verify double-sign requires a receiver key."""
        sender_priv, _ = generate_agent_keypair()
        payload = {"task": "abc"}
        envelope = double_sign(payload, sender_priv)
        assert "sender_signature" in envelope
        assert "receiver_signature" not in envelope

    def test_make_did_format(self):
        """Verify the DID format matches the expected pattern."""
        priv, pub = generate_agent_keypair()
        did = make_did(pub)
        assert did.startswith(DID_PREFIX)
        assert len(did) > len(DID_PREFIX)

    def test_encode_decode_public_key(self):
        """Verify public key can be encoded and then decoded back."""
        priv, pub = generate_agent_keypair()
        enc = encode_public_key(pub)
        decoded = decode_public_key(enc)
        assert decoded.public_bytes_raw() == pub.public_bytes_raw()

    def test_encode_decode_private_key(self):
        """Verify private key can be encoded and then decoded back."""
        priv, _ = generate_agent_keypair()
        enc = encode_private_key(priv)
        decoded = decode_private_key(enc)
        # Sign with both and verify they produce the same result
        sig1 = sign({"test": 1}, priv)
        sig2 = sign({"test": 1}, decoded)
        assert sig1 == sig2


class TestIdentityService:
    def test_lazy_conn(self, fresh_identity):
        """Accessing identity.conn triggers lazy init (does not require _conn override)."""
        conn = fresh_identity.conn
        assert conn is not None
        row = conn.execute("SELECT COUNT(*) as c FROM agents").fetchone()
        assert row["c"] == 0

    def test_close(self, identity_and_conn):
        """close() releases the connection."""
        svc, conn = identity_and_conn
        svc.close()
        assert svc._conn is None

    def test_register(self, identity_and_conn):
        """Verify registering an agent returns agent metadata with DID and public key."""
        svc, _ = identity_and_conn
        agent = svc.register("Alice", auth_token="feishu_123")
        assert "agent_id" in agent
        assert agent["did"].startswith(DID_PREFIX)
        assert agent["name"] == "Alice"
        assert agent["auth_token"] == "feishu_123"

    def test_get_agent(self, identity_and_conn):
        """Verify retrieving an agent by ID returns the correct agent data."""
        svc, _ = identity_and_conn
        agent = svc.register("Bob")
        fetched = svc.get_agent(agent["agent_id"])
        assert fetched is not None
        assert fetched["name"] == "Bob"

    def test_get_agent_not_found(self, identity_and_conn):
        """Verify retrieving a non-existent agent returns None."""
        svc, _ = identity_and_conn
        assert svc.get_agent("nonexistent") is None

    def test_get_agent_by_did(self, identity_and_conn):
        """Verify looking up an agent by DID returns the correct agent."""
        svc, _ = identity_and_conn
        agent = svc.register("Carol")
        fetched = svc.get_agent_by_did(agent["did"])
        assert fetched is not None
        assert fetched["name"] == "Carol"

    def test_get_agent_by_did_not_found(self, identity_and_conn):
        """Verify looking up a non-existent DID returns None."""
        svc, _ = identity_and_conn
        assert svc.get_agent_by_did("did:agentmesh:key:nonexistent") is None

    def test_get_agent_by_auth(self, identity_and_conn):
        """Verify looking up an agent by auth token returns the correct agent."""
        svc, _ = identity_and_conn
        agent = svc.register("Dave", auth_token="token_dave")
        fetched = svc.get_agent_by_auth("token_dave")
        assert fetched is not None

    def test_get_agent_by_auth_not_found(self, identity_and_conn):
        """Verify looking up a non-existent auth token returns None."""
        svc, _ = identity_and_conn
        assert svc.get_agent_by_auth("bogus_token") is None

    def test_get_private_key(self, identity_and_conn):
        """Verify retrieving a private key for an existing agent succeeds."""
        svc, _ = identity_and_conn
        agent = svc.register("Eve")
        priv = svc.get_private_key(agent["agent_id"])
        assert priv is not None

    def test_get_private_key_not_found(self, identity_and_conn):
        """Verify retrieving a private key for a non-existent agent returns None."""
        svc, _ = identity_and_conn
        assert svc.get_private_key("nonexistent") is None

    def test_fetch_all_registrations(self, identity_and_conn):
        """Verify fetching all registrations returns all registered agents."""
        svc, _ = identity_and_conn
        svc.register("Alice")
        svc.register("Bob")
        all_agents = svc.fetch_all_registrations()
        assert len(all_agents) == 2

    def test_export_key(self, identity_and_conn):
        """Verify exporting an agent's private key returns the key material."""
        svc, _ = identity_and_conn
        agent = svc.register("Frank")
        exported = svc.export_key(agent["agent_id"])
        assert isinstance(exported, str)
        assert len(exported) > 0

    def test_export_key_not_found(self, identity_and_conn):
        """Verify exporting a non-existent key returns None."""
        svc, _ = identity_and_conn
        assert svc.export_key("missing") == ""

    def test_import_key(self, identity_and_conn):
        """Verify importing a key creates a new agent from the key material."""
        svc, _ = identity_and_conn
        agent = svc.register("Grace")
        exported = svc.export_key(agent["agent_id"])
        # Create new agent with same name and import the key
        svc.import_key(agent["agent_id"], exported)
        reimported = svc.get_private_key(agent["agent_id"])
        assert reimported is not None

    def test_sign_payload(self, identity_and_conn):
        """Verify signing a payload produces a valid signature."""
        svc, _ = identity_and_conn
        agent = svc.register("Heidi")
        payload = {"task": "t-001"}
        sig = svc.sign_payload(agent["agent_id"], payload)
        assert sig is not None
        assert len(sig) > 0

    def test_sign_payload_missing_key(self, identity_and_conn):
        """Verify signing fails when the agent's private key is missing."""
        svc, _ = identity_and_conn
        assert svc.sign_payload("nonexistent", {"test": 1}) is None

    def test_verify_signature(self, identity_and_conn):
        """Verify that a valid signature passes verification."""
        svc, _ = identity_and_conn
        agent = svc.register("Ivan")
        payload = {"task": "t-001"}
        sig = svc.sign_payload(agent["agent_id"], payload)
        assert svc.verify_signature(agent["did"], payload, sig) is True

    def test_verify_signature_bad_did(self, identity_and_conn):
        """Verify that a signature from a different DID fails verification."""
        svc, _ = identity_and_conn
        assert svc.verify_signature("not-a-did", {"x": 1}, "badsig") is False

    def test_verify_signature_wrong_payload(self, identity_and_conn):
        """Verify that a signature for a different payload fails verification."""
        svc, _ = identity_and_conn
        agent = svc.register("Judy")
        payload = {"task": "t-001"}
        sig = svc.sign_payload(agent["agent_id"], payload)
        assert svc.verify_signature(agent["did"], {"task": "wrong"}, sig) is False

    def test_register_with_metadata(self, identity_and_conn):
        """Verify registering an agent with additional metadata fields."""
        svc, _ = identity_and_conn
        meta = {"role": "analyst", "org": "test"}
        agent = svc.register("MetaAgent", metadata=meta)
        fetched = svc.get_agent(agent["agent_id"])
        import json
        assert json.loads(fetched["metadata"]) == meta

    def test_register_default_auth_token(self, identity_and_conn):
        """Verify registration auto-generates an auth token when not provided."""
        svc, _ = identity_and_conn
        agent = svc.register("DefaultAuth")
        fetched = svc.get_agent(agent["agent_id"])
        assert fetched["auth_token"] == ""


class TestCreateService:
    def test_create_service(self):
        """create_service returns a usable IdentityService."""
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        f.close()
        svc = create_service(f.name)
        try:
            conn = svc.conn
            assert conn is not None
            agent = svc.register("SvcAgent")
            assert agent is not None
        finally:
            svc.close()
            Path(f.name).unlink(missing_ok=True)
