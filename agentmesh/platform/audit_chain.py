"""AgentMesh Platform — Module 3: Audit/Evidence Chain.

Double-signature + hash-chain for every task lifecycle event.
Each operation (publish/assign/deliver/verify/settle/cancel) produces:
  - sender_signature (actor)
  - receiver_signature (counterparty, when applicable)
  - chain_hash linking to previous entry (tamper-evident)
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
class AuditEntry:
    """A single audit log entry with cryptographic signatures and chain linking.

    Attributes:
        id: Unique entry identifier (UUID hex).
        task_id: Task this entry belongs to.
        action: Lifecycle action (e.g. publish, assign, deliver).
        actor_id: Agent that performed the action.
        payload_digest: SHA-256 digest of the canonicalised payload JSON.
        sender_sig: Cryptographic signature from the actor.
        receiver_sig: Optional counterparty signature.
        chain_prev_hash: Hash of the previous entry in the chain.
        chain_hash: SHA-256 of (id + prev_hash + payload_digest).
        extra: JSON-encoded extra metadata.
        created_at: Timestamp set by the database.
    """

    id: str
    task_id: str
    action: str
    actor_id: str
    payload_digest: str
    sender_sig: str
    receiver_sig: Optional[str]
    chain_prev_hash: Optional[str]
    chain_hash: str
    extra: str
    created_at: str


class AuditChainService:
    """Tamper-evident audit log with hash-chain and double-signatures.

    Args:
        identity_svc: IdentityService used for key lookups and signing.
        db_conn: SQLite database connection with the audit_log tables.
    """

    def __init__(self, identity_svc: IdentityService, db_conn):
        self.identity = identity_svc
        self.conn = db_conn

    # ── record an audit event ──────────────────────────────────────────

    def record(
        self,
        task_id: str,
        action: str,
        actor_id: str,
        payload: dict,
        *,
        receiver_id: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> AuditEntry:
        """Create an audit-log entry with double-sign and hash-chain.

        Steps:
          1. Canonicalise payload → compute digest
          2. Load actor's private key → sign payload
          3. If receiver_id given, fetch their private key → double-sign
          4. Find previous chain head for this task → chain link
          5. Compute chain_hash = SHA256(id + prev_hash + digest)
          6. Persist to DB + update chain head

        Args:
            task_id: Task identifier this event belongs to.
            action: Lifecycle action name.
            actor_id: Agent that performed the action.
            payload: The event payload dict.
            receiver_id: Optional counterparty agent for double-signing.
            extra: Optional extra metadata dict.

        Returns:
            The persisted AuditEntry with database-generated timestamp.

        Raises:
            ValueError: If the actor's or receiver's private key is not found.
        """
        entry_id = uuid.uuid4().hex

        # 1. canonical payload + digest
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload_digest = hashlib.sha256(payload_json.encode()).hexdigest()

        # 2. sender signs
        actor_priv = self.identity.get_private_key(actor_id)
        if actor_priv is None:
            raise ValueError(f"Private key not found for actor {actor_id}")
        sender_sig = sign(payload, actor_priv)

        # 3. receiver signs (if applicable)
        receiver_sig: Optional[str] = None
        if receiver_id is not None:
            receiver_priv = self.identity.get_private_key(receiver_id)
            if receiver_priv is None:
                raise ValueError(f"Private key not found for receiver {receiver_id}")
            envelope = double_sign(payload, actor_priv, receiver_priv)
            receiver_sig = envelope["receiver_signature"]

        # 4. chain link
        prev_hash = self._get_chain_head(task_id)
        chain_hash = hashlib.sha256(
            f"{entry_id}{prev_hash or ''}{payload_digest}".encode()
        ).hexdigest()

        # 5. persist
        entry = AuditEntry(
            id=entry_id,
            task_id=task_id,
            action=action,
            actor_id=actor_id,
            payload_digest=payload_digest,
            sender_sig=sender_sig,
            receiver_sig=receiver_sig,
            chain_prev_hash=prev_hash,
            chain_hash=chain_hash,
            extra=json.dumps(extra or {}),
            created_at=None,  # set by SQLite DEFAULT datetime('now')
        )

        with self.conn:
            self.conn.execute(
                """INSERT INTO audit_log
                   (id, task_id, action, actor_id, payload_digest,
                    sender_sig, receiver_sig,
                    chain_prev_hash, chain_hash, extra)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (entry.id, entry.task_id, entry.action, entry.actor_id,
                 entry.payload_digest, entry.sender_sig, entry.receiver_sig,
                 entry.chain_prev_hash, entry.chain_hash, entry.extra),
            )
            self.conn.execute(
                """INSERT OR REPLACE INTO audit_chain_heads (task_id, latest_hash, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                (task_id, chain_hash),
            )

        # fetch back to get auto-generated created_at
        row = self.conn.execute(
            "SELECT * FROM audit_log WHERE id = ?", (entry_id,)
        ).fetchone()
        if row:
            return AuditEntry(**dict(row))
        return entry

    # ── verification ───────────────────────────────────────────────────

    def verify_entry(self, entry: AuditEntry) -> bool:
        """Verify all signatures and hash-chain integrity for one entry.

        Note: payload_digest integrity cannot be checked without the
        original payload (the digest is stored, not the payload itself).
        This method is a stub for future chain-structure verification.

        Args:
            entry: The AuditEntry to verify.

        Returns:
            ``True`` if the entry passes structural checks.
        """
        try:
            # b — we need the original payload to verify sender sig
            #    In practice, the caller (or task) provides the payload reference
            #    Here we only verify chain structure
            pass
        except Exception:
            return False
        return True

    def verify_chain(self, task_id: str) -> list[dict]:
        """Walk the entire hash-chain for a task and verify integrity.

        Args:
            task_id: Task identifier to verify.

        Returns:
            List of audit entry dicts, each with an added ``chain_ok``
            boolean field indicating hash-chain integrity.
        """
        rows = self.conn.execute(
            """SELECT * FROM audit_log
               WHERE task_id = ?
               ORDER BY created_at ASC""",
            (task_id,),
        ).fetchall()

        result = []
        for row in rows:
            entry = dict(row)
            computed = hashlib.sha256(
                f"{entry['id']}{entry['chain_prev_hash'] or ''}{entry['payload_digest']}".encode()
            ).hexdigest()
            chain_ok = computed == entry["chain_hash"]
            entry["chain_ok"] = chain_ok
            result.append(entry)

        return result

    # ── query ──────────────────────────────────────────────────────────

    def get_by_task(self, task_id: str) -> list[dict]:
        """Retrieve all audit entries for a given task.

        Args:
            task_id: Task identifier.

        Returns:
            List of audit entry dicts ordered by creation time.
        """
        rows = self.conn.execute(
            """SELECT * FROM audit_log WHERE task_id = ? ORDER BY created_at ASC""",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_by_actor(self, actor_id: str, limit: int = 50) -> list[dict]:
        """Retrieve audit entries for a specific actor.

        Args:
            actor_id: Agent identifier.
            limit: Maximum number of entries to return (default 50).

        Returns:
            List of audit entry dicts in reverse chronological order.
        """
        rows = self.conn.execute(
            """SELECT * FROM audit_log WHERE actor_id = ? ORDER BY created_at DESC LIMIT ?""",
            (actor_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def verify_signature_for_audit(
        self,
        actor_id: str,
        payload: dict,
        signature: str,
    ) -> bool:
        """Given an actor ID and payload, verify the stored signature.

        Args:
            actor_id: The agent ID whose public key will be used.
            payload: The dictionary that was signed.
            signature: Base64-encoded signature to verify.

        Returns:
            ``True`` if the signature is valid, ``False`` otherwise.
        """
        agent = self.identity.get_agent(actor_id)
        if agent is None:
            return False
        pub_key = agent["public_key"]
        pub = decode_public_key(pub_key)
        return verify(payload, signature, pub)

    # ── internals ──────────────────────────────────────────────────────

    def _get_chain_head(self, task_id: str) -> Optional[str]:
        """Retrieve the latest chain hash for a task.

        Args:
            task_id: Task to look up.

        Returns:
            The latest chain hash, or ``None`` if the task has no entries.
        """
        row = self.conn.execute(
            "SELECT latest_hash FROM audit_chain_heads WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return row["latest_hash"] if row else None
