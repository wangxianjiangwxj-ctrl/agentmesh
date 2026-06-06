"""AgentMesh Platform - Identity Module.

Provides DID-compatible agent identity generation, key management,
and a persistent registry backed by SQLite.
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
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

# ---------------------------------------------------------------------------
# DID-compatible agent identity
# ---------------------------------------------------------------------------

DID_METHOD = "agentmesh"
DID_PREFIX = f"did:{DID_METHOD}:key:"


def generate_agent_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Generate a fresh Ed25519 key pair for an agent.

    Returns:
        A tuple of (private_key, public_key) from the Ed25519 curve.
    """
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def encode_public_key(pub: Ed25519PublicKey) -> str:
    """Encode a public key as a multibase base64url string.

    Args:
        pub: The Ed25519 public key to encode.

    Returns:
        URL-safe base64-encoded string (without trailing padding).
    """
    raw = pub.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_public_key(key_str: str) -> Ed25519PublicKey:
    """Restore an Ed25519 public key from its encoded string form.

    Args:
        key_str: URL-safe base64-encoded public key (may lack padding).

    Returns:
        The decoded Ed25519PublicKey instance.
    """
    padding = 4 - len(key_str) % 4
    if padding != 4:
        key_str += "=" * padding
    raw = base64.urlsafe_b64decode(key_str)
    return Ed25519PublicKey.from_public_bytes(raw)


def make_did(pub: Ed25519PublicKey) -> str:
    """Build a DID string from a public key.

    Args:
        pub: The Ed25519 public key to encode into the DID.

    Returns:
        A DID string in the form ``did:agentmesh:key:<encoded_key>``.
    """
    return f"{DID_PREFIX}{encode_public_key(pub)}"


def parse_did(did: str) -> Optional[str]:
    """Extract the public-key portion from a DID string.

    Args:
        did: A DID string (e.g. ``did:agentmesh:key:...``).

    Returns:
        The encoded public-key portion, or ``None`` if the DID does not
        match the expected prefix.
    """
    if not did.startswith(DID_PREFIX):
        return None
    return did[len(DID_PREFIX):]


def sign(payload: dict, private_key: Ed25519PrivateKey) -> str:
    """Sign a JSON-serializable payload and return a base64 signature.

    The payload is canonicalised (sorted keys, no whitespace) before signing.

    Args:
        payload: The dictionary to sign.
        private_key: The Ed25519 private key used for signing.

    Returns:
        Base64-encoded signature string.
    """
    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = private_key.sign(serialised)
    return base64.b64encode(sig).decode()


def verify(payload: dict, signature: str, public_key: Ed25519PublicKey) -> bool:
    """Verify a signature against a JSON-serializable payload.

    Args:
        payload: The dictionary that was signed.
        signature: Base64-encoded signature to verify.
        public_key: The Ed25519 public key corresponding to the signing key.

    Returns:
        ``True`` if the signature is valid, ``False`` otherwise.
    """
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
    """Create a double-signed envelope (sender + optional receiver).

    Args:
        payload: The dictionary to sign.
        sender_key: The sender's Ed25519 private key.
        receiver_key: The receiver's Ed25519 private key; if provided,
            a second signature is added as ``receiver_signature``.

    Returns:
        A dict containing the original payload, the sender's signature,
        and optionally the receiver's signature.
    """
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
    """Initialise the agent database, creating tables if needed.

    Args:
        db_path: Filesystem path to the SQLite database file.

    Returns:
        A new SQLite connection with row factory and WAL mode enabled.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(CREATE_TABLE_SQL)
    conn.commit()
    return conn


class IdentityService:
    """Agent identity registration and key management.

    Provides CRUD for agents, private key storage, and signature
    generation / verification helpers.

    Args:
        db_path: Path to the SQLite database file used for persistence.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    # -- connection lifecycle ------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        """Return the lazy-initialised database connection."""
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
    ) -> dict:
        """Register a new agent: generates key pair, persists identity.

        Args:
            name: Human-readable alias for the agent.
            auth_token: Optional Feishu user_id or webhook secret.
            metadata: Optional JSON-serialisable metadata dict.

        Returns:
            A dict containing ``agent_id``, ``did``, ``name``, and
            ``public_key`` for the newly created agent.
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
        """Fetch a public agent record by ID.

        Args:
            agent_id: The agent's UUID.

        Returns:
            A dict of agent fields, or ``None`` if not found.
        """
        row = self.conn.execute(
            "SELECT id, did, name, public_key, auth_token, metadata, reputation, task_count, created_at FROM agents WHERE id = ?",
            (agent_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_agent_by_did(self, did: str) -> Optional[dict]:
        """Fetch an agent record by its DID.

        Args:
            did: The agent's DID string.

        Returns:
            A dict of agent fields, or ``None`` if not found.
        """
        row = self.conn.execute(
            "SELECT id, did, name, public_key, auth_token, metadata, reputation, task_count, created_at FROM agents WHERE did = ?",
            (did,),
        ).fetchone()
        return dict(row) if row else None

    def get_agent_by_auth(self, auth_token: str) -> Optional[dict]:
        """Look up an agent by Feishu user_id or auth token.

        Args:
            auth_token: The authentication token to search for.

        Returns:
            A dict of agent fields, or ``None`` if not found.
        """
        row = self.conn.execute(
            "SELECT id, did, name, public_key, auth_token, metadata, reputation, task_count, created_at FROM agents WHERE auth_token = ?",
            (auth_token,),
        ).fetchone()
        return dict(row) if row else None

    def get_private_key(self, agent_id: str) -> Optional[Ed25519PrivateKey]:
        """Load the private key for a registered agent.

        The key is decoded from its stored encoded form.

        Args:
            agent_id: The agent's UUID.

        Returns:
            The Ed25519PrivateKey, or ``None`` if not found.
        """
        row = self.conn.execute(
            "SELECT private_key_enc FROM agent_private_keys WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        if row is None:
            return None
        return decode_private_key(row["private_key_enc"])

    def fetch_all_registrations(self) -> list[dict]:
        """Return all registered agents ordered by creation time.

        Returns:
            A list of agent field dicts (excluding private keys).
        """
        rows = self.conn.execute(
            "SELECT id, did, name, public_key, reputation, task_count, created_at FROM agents ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    # -- raw key encoding (private) -----------------------------------------

    def export_key(self, agent_id: str) -> str:
        """Export a registered agent's private key as an encoded string.

        Args:
            agent_id: The agent's UUID.

        Returns:
            Base64-encoded private key string, or empty string if not found.
        """
        raw = self.get_private_key(agent_id)
        if raw is None:
            return ""
        return encode_private_key(raw)

    def import_key(self, agent_id: str, pem_key: str) -> None:
        """Import and store a private key for a registered agent.

        Args:
            agent_id: The agent's UUID.
            pem_key: Base64-encoded private key bytes.
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
        """Sign a payload on behalf of a registered agent.

        Args:
            agent_id: The agent's UUID.
            payload: The dictionary to sign.

        Returns:
            Base64-encoded signature, or ``None`` if the agent's private
            key is not available.
        """
        priv = self.get_private_key(agent_id)
        if priv is None:
            return None
        return sign(payload, priv)

    def verify_signature(self, did: str, payload: dict, signature: str) -> bool:
        """Verify a signature against an agent's public key (from DID).

        Args:
            did: The agent's DID string (includes the encoded public key).
            payload: The dictionary that was signed.
            signature: Base64-encoded signature to verify.

        Returns:
            ``True`` if the signature is valid, ``False`` otherwise.
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
    """Encode an Ed25519 private key as a base64 string.

    Args:
        key: The Ed25519 private key to encode.

    Returns:
        Base64-encoded private key bytes.
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
        The decoded Ed25519PrivateKey instance.
    """
    raw = base64.b64decode(encoded)
    return Ed25519PrivateKey.from_private_bytes(raw)


# -- convenience shortcut ---------------------------------------------------

def create_service(db_path: str | Path = "agentmesh.db") -> IdentityService:
    """Create and return a default IdentityService instance.

    Args:
        db_path: Path to the SQLite database file (default: ``agentmesh.db``).

    Returns:
        A ready-to-use IdentityService instance.
    """
    return IdentityService(db_path)
