"""
AgentMesh Platform — Module 3: Evidence Chain (v2)

Schema-aligned: evidence_chain table with chain_index, signature + optional secondary_sig,
hash-chain linking. Compatible with db_schema.py v2.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Optional

from agentmesh.identity import (
    IdentityService,
    sign,
    verify,
    double_sign,
    decode_public_key,
)


@dataclass
class EvidenceEntry:
    """A single entry in the evidence chain (hash-linked log).

    Attributes:
        id: Unique entry identifier (hex UUID).
        task_id: Associated task UUID.
        chain_index: Auto-incrementing index within the task's chain.
        action: Action description (e.g. "task.created").
        actor_id: Agent UUID who performed the action.
        payload_digest: SHA-256 digest of the canonical payload JSON.
        signature: Ed25519 primary signature from the actor.
        secondary_sig: Optional counterparty signature (double-sign).
        chain_prev_hash: Hash of the previous entry in the chain.
        chain_hash: SHA-256 hash of (id + prev_hash + digest).
        extra: JSON blob for extensible metadata.
        created_at: ISO-8601 timestamp set by SQLite.
    """
    id: str
    task_id: str
    chain_index: int
    action: str
    actor_id: str
    payload_digest: str
    signature: str
    secondary_sig: Optional[str]
    chain_prev_hash: Optional[str]
    chain_hash: str
    extra: str
    created_at: str


TABLE = "evidence_chain"
HEAD_TABLE = "evidence_chain_heads"


class EvidenceChainService:
    """Tamper-evident evidence chain with hash-chain and optional dual signatures.

    Records every task lifecycle event as a hash-linked chain entry
    with cryptographic signatures, making the log tamper-evident.
    Supports optional double-signatures for two-party operations.
    """

    def __init__(self, identity_svc: IdentityService, db_conn: sqlite3.Connection):
        """Initialize the evidence chain service.

        Args:
            identity_svc: IdentityService for key lookup and signing.
            db_conn: SQLite connection with evidence_chain tables.
        """
        self.identity = identity_svc
        self.conn = db_conn

    # ── record ─────────────────────────────────────────────────────────

    def record(
        self,
        task_id: str,
        action: str,
        actor_id: str,
        payload: dict,
        *,
        secondary_actor_id: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> EvidenceEntry:
        """Create an evidence-chain entry.

        Steps:
          1. Canonicalise payload → digest
          2. Actor signs payload
          3. If secondary_actor_id given, they also sign (double-sign envelope)
          4. Get previous chain head (hash + index) for this task
          5. Compute chain_hash = SHA256(id + prev_hash + digest)
          6. Persist to evidence_chain + update chain head
        """
        entry_id = uuid.uuid4().hex

        # 1. digest
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload_digest = hashlib.sha256(payload_json.encode()).hexdigest()

        # 2. primary signature
        actor_priv = self.identity.get_private_key(actor_id)
        if actor_priv is None:
            raise ValueError(f"Private key not found for actor {actor_id}")
        signature = sign(payload, actor_priv)

        # 3. secondary signature
        secondary_sig: Optional[str] = None
        if secondary_actor_id is not None:
            receiver_priv = self.identity.get_private_key(secondary_actor_id)
            if receiver_priv is None:
                raise ValueError(f"Private key not found for {secondary_actor_id}")
            envelope = double_sign(payload, actor_priv, receiver_priv)
            secondary_sig = envelope["receiver_signature"]

        # 4. chain link + index
        head = self._get_chain_head(task_id)
        prev_hash = head["hash"] if head else None
        chain_index = (head["index"] or 0) + 1 if head else 1

        chain_hash = hashlib.sha256(
            f"{entry_id}{prev_hash or ''}{payload_digest}".encode()
        ).hexdigest()

        entry = EvidenceEntry(
            id=entry_id,
            task_id=task_id,
            chain_index=chain_index,
            action=action,
            actor_id=actor_id,
            payload_digest=payload_digest,
            signature=signature,
            secondary_sig=secondary_sig,
            chain_prev_hash=prev_hash,
            chain_hash=chain_hash,
            extra=json.dumps(extra or {}),
            created_at=None,
        )

        # 5. persist
        with self.conn:
            self.conn.execute(
                f"""INSERT INTO {TABLE}
                   (id, task_id, chain_index, action, actor_id, payload_digest,
                    signature, secondary_sig, chain_prev_hash, chain_hash, extra)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (entry.id, entry.task_id, entry.chain_index, entry.action,
                 entry.actor_id, entry.payload_digest, entry.signature,
                 entry.secondary_sig, entry.chain_prev_hash, entry.chain_hash,
                 entry.extra),
            )
            self.conn.execute(
                f"""INSERT OR REPLACE INTO {HEAD_TABLE}
                   (task_id, latest_hash, latest_index, updated_at)
                   VALUES (?, ?, ?, datetime('now'))""",
                (task_id, chain_hash, chain_index),
            )

        # fetch back for created_at
        row = self.conn.execute(
            f"SELECT * FROM {TABLE} WHERE id = ?", (entry_id,)
        ).fetchone()
        if row:
            return EvidenceEntry(**dict(row))
        return entry

    # ── verification ───────────────────────────────────────────────────

    def verify_chain(self, task_id: str) -> list[dict]:
        """Walk the hash-chain for a task and validate integrity.

        Recomputes each chain_hash from (id + prev_hash + payload_digest)
        and adds a ``chain_ok`` boolean field to each returned dict.

        Args:
            task_id: UUID of the task to verify.

        Returns:
            List of entry dicts with an added ``chain_ok`` field.
        """
        rows = self.conn.execute(
            f"""SELECT * FROM {TABLE}
               WHERE task_id = ?
               ORDER BY chain_index ASC""",
            (task_id,),
        ).fetchall()

        result = []
        for row in rows:
            entry = dict(row)
            computed = hashlib.sha256(
                f"{entry['id']}{entry['chain_prev_hash'] or ''}{entry['payload_digest']}".encode()
            ).hexdigest()
            entry["chain_ok"] = computed == entry["chain_hash"]
            result.append(entry)

        return result

    def verify_signature(self, actor_id: str, payload: dict, signature: str) -> bool:
        """Verify a signature against an actor's public key.

        Looks up the actor's public key from the identity service
        and verifies the Ed25519 signature on the given payload.

        Args:
            actor_id: UUID of the signing agent.
            payload: Original JSON-serializable payload.
            signature: Ed25519 signature to verify.

        Returns:
            True if the signature is valid, False otherwise.
        """
        agent = self.identity.get_agent(actor_id)
        if agent is None:
            return False
        pub = decode_public_key(agent["public_key"])
        return verify(payload, signature, pub)

    # ── queries ────────────────────────────────────────────────────────

    def get_by_task(self, task_id: str) -> list[dict]:
        """Get all evidence entries for a task, ordered by chain index.

        Args:
            task_id: UUID of the task.

        Returns:
            List of evidence entry dicts sorted by chain_index ascending.
        """
        rows = self.conn.execute(
            f"""SELECT * FROM {TABLE}
               WHERE task_id = ? ORDER BY chain_index ASC""",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_by_actor(self, actor_id: str, limit: int = 50) -> list[dict]:
        """Get evidence entries by actor, newest chain index first.

        Args:
            actor_id: UUID of the acting agent.
            limit: Maximum number of entries to return. Defaults to 50.

        Returns:
            List of evidence entry dicts ordered by chain_index descending.
        """
        rows = self.conn.execute(
            f"""SELECT * FROM {TABLE}
               WHERE actor_id = ? ORDER BY chain_index DESC LIMIT ?""",
            (actor_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── internals ──────────────────────────────────────────────────────

    def _get_chain_head(self, task_id: str) -> Optional[dict]:
        row = self.conn.execute(
            f"SELECT latest_hash as h, latest_index as idx FROM {HEAD_TABLE} WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return {"hash": row["h"], "index": row["idx"]}
