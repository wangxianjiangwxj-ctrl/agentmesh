"""AgentMesh Platform — Module 3: Evidence Chain (v2).

Schema-aligned: evidence_chain table with chain_index, signature + optional
secondary_sig, hash-chain linking. Compatible with db_schema.py v2.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Optional

from identity import (
    IdentityService,
    decode_public_key,
    double_sign,
    sign,
    verify,
)


@dataclass
class EvidenceEntry:
    """A single evidence chain entry with cryptographic signature and hash linking.

    Attributes:
        id: Unique entry identifier (UUID hex).
        task_id: Task this evidence belongs to.
        chain_index: Auto-incrementing index within the task's chain.
        action: Lifecycle action that produced this evidence.
        actor_id: Agent that performed the action.
        payload_digest: SHA-256 digest of the canonicalised payload JSON.
        signature: Primary cryptographic signature from the actor.
        secondary_sig: Optional counterparty signature.
        chain_prev_hash: Hash of the previous entry in the chain.
        chain_hash: SHA-256 of (id + prev_hash + payload_digest).
        extra: JSON-encoded extra metadata.
        created_at: Timestamp set by the database.
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

    Each event produces a signed entry linked to the previous one via
    a SHA-256 hash, making the chain tamper-evident.

    Args:
        identity_svc: IdentityService for key lookups and signing.
        db_conn: SQLite database connection with the evidence_chain tables.
    """

    def __init__(self, identity_svc: IdentityService, db_conn):
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

        Args:
            task_id: Task identifier.
            action: Lifecycle action name.
            actor_id: Primary actor agent ID.
            payload: The event payload dict.
            secondary_actor_id: Optional secondary actor for double-signing.
            extra: Optional extra metadata dict.

        Returns:
            The persisted EvidenceEntry with database-generated timestamp.

        Raises:
            ValueError: If the actor's or secondary actor's private key
                is not found.
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
        """Walk the hash-chain and validate integrity.

        Args:
            task_id: Task identifier to verify.

        Returns:
            List of entry dicts, each with an added ``chain_ok``
            boolean indicating hash integrity.
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
        """Verify a stored signature against an actor's public key.

        Args:
            actor_id: Agent ID whose public key to use.
            payload: The dictionary that was signed.
            signature: Base64-encoded signature to verify.

        Returns:
            ``True`` if the signature is valid, ``False`` otherwise.
        """
        agent = self.identity.get_agent(actor_id)
        if agent is None:
            return False
        pub = decode_public_key(agent["public_key"])
        return verify(payload, signature, pub)

    # ── queries ────────────────────────────────────────────────────────

    def get_by_task(self, task_id: str) -> list[dict]:
        """Retrieve all evidence entries for a task.

        Args:
            task_id: Task identifier.

        Returns:
            List of entry dicts ordered by chain index.
        """
        rows = self.conn.execute(
            f"""SELECT * FROM {TABLE}
               WHERE task_id = ? ORDER BY chain_index ASC""",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_by_actor(self, actor_id: str, limit: int = 50) -> list[dict]:
        """Retrieve evidence entries for a specific actor.

        Args:
            actor_id: Agent identifier.
            limit: Maximum number of entries (default 50).

        Returns:
            List of entry dicts in reverse chain-index order.
        """
        rows = self.conn.execute(
            f"""SELECT * FROM {TABLE}
               WHERE actor_id = ? ORDER BY chain_index DESC LIMIT ?""",
            (actor_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── internals ──────────────────────────────────────────────────────

    def _get_chain_head(self, task_id: str) -> Optional[dict]:
        """Retrieve the latest chain head for a task.

        Args:
            task_id: Task to look up.

        Returns:
            A dict with ``hash`` and ``index`` keys, or ``None`` if the
            task has no entries.
        """
        row = self.conn.execute(
            f"SELECT latest_hash as h, latest_index as idx FROM {HEAD_TABLE} WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return {"hash": row["h"], "index": row["idx"]}
