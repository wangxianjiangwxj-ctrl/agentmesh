"""AgentMesh Platform - Identity Module
"""
from __future__ import annotations

import base64
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PrivateFormat,
    PublicFormat,
    NoEncryption,
)


# ---------------------------------------------------------------------------
# DID-compatible agent identity
# ---------------------------------------------------------------------------

DID_METHOD = "agentmesh"
DID_PREFIX = f"did:{DID_METHOD}:key:"


def generate_agent_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Generate a fresh Ed25519 key pair for an agent."""
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def encode_public_key(pub: Ed25519PublicKey) -> str:
    """Encode a public key as multibase base64url string."""
    raw = pub.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_public_key(key_str: str) -> Ed25519PublicKey:
    """Restore public key from encoded string."""
    padding = 4 - len(key_str) % 4
    if padding != 4:
        key_str += "=" * padding
    raw = base64.urlsafe_b64decode(key_str)
    return Ed25519PublicKey.from_public_bytes(raw)


def make_did(pub: Ed25519PublicKey) -> str:
    """Build a DID string from a public key."""
    return f"{DID_PREFIX}{encode_public_key(pub)}"


def parse_did(did: str) -> Optional[str]:
    """Extract the public-key portion from a DID, or None if invalid."""
    if not did.startswith(DID_PREFIX):
        return None
    return did[len(DID_PREFIX):]


def sign(payload: dict, private_key: Ed25519PrivateKey) -> str:
    """Sign a JSON-serializable payload; returns base64 signature."""
    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = private_key.sign(serialised)
    return base64.b64encode(sig).decode()


def verify(payload: dict, signature: str, public_key: Ed25519PublicKey) -> bool:
    """Verify a signature against a JSON-serializable payload."""
    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig_bytes = base64.b64decode(signature)
    try:
        public_key.verify(sig_bytes, serialised)
        return True
    except Exception:
        return False


def double_sign(
    payload: dict,
    sender_key: Ed25519PrivateKey,
    receiver_key: Optional[Ed25519PrivateKey] = None,
) -> dict:
    """Create a double-signed envelope (sender + optional receiver)."""
    envelope = {
        "payload": payload,
        "sender_signature": sign(payload, sender_key),
    }
    if receiver_key is not None:
        envelope["receiver_signature"] = sign(payload, receiver_key)
    return envelope


# ---------------------------------------------------------------------------
# Persistent agent registry
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agents (
    id              TEXT PRIMARY KEY,          -- UUID
    did             TEXT UNIQUE NOT NULL,       -- did:agentmesh:key:…
    name            TEXT NOT NULL,               -- human-readable alias
    public_key      TEXT NOT NULL,               -- encoded public key
    auth_token      TEXT,                        -- Feishu user_id / webhook secret
    metadata        TEXT DEFAULT '{}',           -- JSON blob for extensions
    reputation      REAL DEFAULT 0.0,
    task_count      INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_private_keys (
    agent_id        TEXT PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
    private_key_enc TEXT NOT NULL                -- encoded private key (in-memory only for MVP)
);
"""


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Initialise the agent database, creating tables if needed."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(CREATE_TABLE_SQL)
    conn.commit()
    return conn


class IdentityService:
    """Agent identity registration and key management.

    Provides DID-compatible agent registration, key pair generation,
    signature creation/verification, and persistent storage via SQLite.
    """

    def __init__(self, db_path: str | Path):
        """Initialize the identity service with a database path.

        Args:
            db_path: Filesystem path to the SQLite database file.
        """
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    # -- connection lifecycle ------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        """Lazy-initialized SQLite connection.

        Returns the existing connection or creates one on first access.
        """
        if self._conn is None:
            self._conn = init_db(self.db_path)
        return self._conn

    def close(self) -> None:
        """Close the database connection and release resources."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- registration --------------------------------------------------------

    def register(
        self,
        name: str,
        auth_token: str = "",
        metadata: dict | None = None,
    ) -> str:
        """Register a new agent: generates key pair, persists identity.

        Returns the agent ID.
        """
        priv, pub = generate_agent_keypair()
        agent_id = uuid.uuid4().hex
        did = make_did(pub)
        pub_encoded = encode_public_key(pub)
        row = dict(
            id=agent_id,
            did=did,
            name=name,
            public_key=pub_encoded,
            auth_token=auth_token,
            metadata=json.dumps(metadata or {}),
        )
        with self.conn:
            self.conn.execute(
                """INSERT INTO agents (id, did, name, public_key, auth_token, metadata)
                   VALUES (:id, :did, :name, :public_key, :auth_token, :metadata)""",
                row,
            )
            self.conn.execute(
                "INSERT INTO agent_private_keys (agent_id, private_key_enc) VALUES (?, ?)",
                (agent_id, encode_private_key(priv)),
            )

        row["agent_id"] = agent_id
        row["did"] = did
        row["public_key"] = pub_encoded
        return row

    def get_agent(self, agent_id: str) -> Optional[dict]:
        """Fetch a public agent record by ID."""
        row = self.conn.execute(
            "SELECT id, did, name, public_key, auth_token, metadata, reputation, task_count, created_at FROM agents WHERE id = ?",
            (agent_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_agent_by_did(self, did: str) -> Optional[dict]:
        """Fetch agent record by DID."""
        row = self.conn.execute(
            "SELECT id, did, name, public_key, auth_token, metadata, reputation, task_count, created_at FROM agents WHERE did = ?",
            (did,),
        ).fetchone()
        return dict(row) if row else None

    def get_agent_by_auth(self, auth_token: str) -> Optional[dict]:
        """Lookup agent by Feishu user_id / auth token."""
        row = self.conn.execute(
            "SELECT id, did, name, public_key, auth_token, metadata, reputation, task_count, created_at FROM agents WHERE auth_token = ?",
            (auth_token,),
        ).fetchone()
        return dict(row) if row else None

    def get_private_key(self, agent_id: str) -> Optional[Ed25519PrivateKey]:
        """Load the private key for a registered agent (in-memory only)."""
        row = self.conn.execute(
            "SELECT private_key_enc FROM agent_private_keys WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        if row is None:
            return None
        return decode_private_key(row["private_key_enc"])

    def fetch_all_registrations(self) -> list[dict]:
        """Fetch all registered agents, ordered by creation time.

        Returns:
            List of dicts with agent metadata (id, did, name, public_key,
            reputation, task_count, created_at).
        """
        rows = self.conn.execute(
            "SELECT id, did, name, public_key, reputation, task_count, created_at FROM agents ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    # -- raw key encoding (private) -----------------------------------------

    def export_key(self, agent_id: str) -> str:
        """Export an agent's private key as a base64-encoded string.

        Args:
            agent_id: UUID of the registered agent.

        Returns:
            Base64-encoded private key string, or empty string if not found.
        """
        raw = self.get_private_key(agent_id)
        if raw is None:
            return ""
        return encode_private_key(raw)

    def import_key(self, agent_id: str, pem_key: str) -> None:
        """Import and store a private key for an existing agent.

        Args:
            agent_id: UUID of the agent.
            pem_key: Base64-encoded (not PEM) Ed25519 private key bytes.
        """
        priv = Ed25519PrivateKey.from_private_bytes(
            base64.b64decode(pem_key) if not pem_key.startswith("-----") else ""
        )
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO agent_private_keys (agent_id, private_key_enc) VALUES (?, ?)",
                (agent_id, encode_private_key(priv)),
            )

    def sign_payload(self, agent_id: str, payload: dict) -> Optional[str]:
        """Sign a JSON-serializable payload using an agent's private key.

        Args:
            agent_id: UUID of the signing agent.
            payload: JSON-serializable dict to sign.

        Returns:
            Base64-encoded Ed25519 signature, or None if private key not found.
        """
        priv = self.get_private_key(agent_id)
        if priv is None:
            return None
        return sign(payload, priv)

    def verify_signature(self, did: str, payload: dict, signature: str) -> bool:
        """Verify an Ed25519 signature against a DID and payload.

        Args:
            did: DID string (e.g. "did:agentmesh:key:...").
            payload: Original JSON-serializable payload.
            signature: Base64-encoded signature to verify.

        Returns:
            True if the signature is valid, False otherwise.
        """
        key_str = parse_did(did)
        if key_str is None:
            return False
        pub = decode_public_key(key_str)
        return verify(payload, signature, pub)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def encode_private_key(key: Ed25519PrivateKey) -> str:
    """Encode an Ed25519 private key as a base64 string (raw bytes, no PEM).

    Args:
        key: The Ed25519 private key to encode.

    Returns:
        Base64-encoded private key string.
    """
    raw = key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    return base64.b64encode(raw).decode()


def decode_private_key(encoded: str) -> Ed25519PrivateKey:
    """Decode a base64-encoded Ed25519 private key.

    Args:
        encoded: Base64-encoded private key string.

    Returns:
        Reconstructed Ed25519PrivateKey instance.
    """
    raw = base64.b64decode(encoded)
    return Ed25519PrivateKey.from_private_bytes(raw)


# -- convenience shortcut ---------------------------------------------------

def create_service(db_path: str | Path = "agentmesh.db") -> IdentityService:
    """Create a default IdentityService instance.

    Args:
        db_path: Path to the SQLite database file. Defaults to "agentmesh.db".

    Returns:
        A configured IdentityService instance.
    """
    return IdentityService(db_path)
