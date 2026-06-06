"""AgentMesh Platform — Module 4: Escrow / Point Settlement (v2 schema).

Core operations:
  - deposit:   add points to an agent's balance
  - hold:      lock points when a task is published (no real money)
  - release:   release held points to executor (on double-sign verify)
  - refund:    return held points to publisher (on cancel/reject)
  - auto_release: T+7 dispute window expiry → auto release to executor
  - balance:   query available + frozen balance
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from sqlite3 import Connection
from typing import Optional

from identity import IdentityService

DISPUTE_WINDOW_DAYS = 7
DEFAULT_INITIAL_BALANCE = 1000


class EscrowError(Exception):
    """Raised when an escrow operation fails (e.g. insufficient balance)."""

    pass


class EscrowService:
    """Centralized escrow (points-only, no real money).

    Manages agent account balances, escrow holds for tasks, and automated
    dispute resolution via time-windowed auto-release.

    Args:
        db_conn: SQLite database connection with ``accounts`` and
            ``transactions`` tables.
        identity_svc: IdentityService for agent identity lookups.
    """

    def __init__(self, db_conn: Connection, identity_svc: IdentityService):
        self.conn = db_conn
        self.identity = identity_svc

    # ── balance ─────────────────────────────────────────────────────────

    def get_balance(self, agent_id: str) -> dict:
        """Query the current balance for an agent.

        Args:
            agent_id: Agent identifier.

        Returns:
            A dict with ``balance`` (total), ``frozen`` (locked), and
            ``available`` (balance - frozen) integer values.
        """
        row = self.conn.execute(
            "SELECT balance, frozen FROM accounts WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row is None:
            return {"balance": 0, "frozen": 0, "available": 0}
        bal = row["balance"]
        frozen = row["frozen"]
        return {"balance": bal, "frozen": frozen, "available": bal - frozen}

    def deposit(self, agent_id: str, amount: int) -> dict:
        """Deposit points into an agent's account.

        Args:
            agent_id: Target agent identifier.
            amount: Positive integer number of points to deposit.

        Returns:
            Updated balance dict.

        Raises:
            EscrowError: If ``amount`` is not positive.
        """
        if amount <= 0:
            raise EscrowError("Deposit amount must be positive")
        with self.conn:
            self.conn.execute(
                """INSERT INTO accounts (agent_id, balance, frozen, updated_at)
                   VALUES (?, ?, 0, datetime('now'))
                   ON CONFLICT(agent_id) DO UPDATE SET
                       balance = balance + ?,
                       updated_at = datetime('now')""",
                (agent_id, amount, amount),
            )
            self.conn.execute(
                """INSERT INTO transactions
                   (id, task_id, from_agent, to_agent, amount, action, status, created_at)
                   VALUES (?, 'SYSTEM', ?, ?, ?, 'deposit', 'confirmed', datetime('now'))""",
                (uuid.uuid4().hex, agent_id, agent_id, amount),
            )
        return self.get_balance(agent_id)

    def ensure_account(self, agent_id: str) -> None:
        """Ensure an agent has an account, creating one with a default balance if missing.

        Args:
            agent_id: Agent identifier to check or create.
        """
        exists = self.conn.execute(
            "SELECT 1 FROM accounts WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if not exists:
            self.deposit(agent_id, DEFAULT_INITIAL_BALANCE)

    # ── hold ────────────────────────────────────────────────────────────

    def hold(self, agent_id: str, task_id: str, amount: int) -> dict:
        """Lock points for a task (escrow hold).

        Args:
            agent_id: Publisher's agent identifier.
            task_id: Task to associate the hold with.
            amount: Number of points to lock.

        Returns:
            Updated balance dict.

        Raises:
            EscrowError: If amount is not positive or available balance
                is insufficient.
        """
        if amount <= 0:
            raise EscrowError("Escrow amount must be positive")
        account = self.get_balance(agent_id)
        if account["available"] < amount:
            raise EscrowError(
                f"Insufficient available balance: have {account['available']}, need {amount}"
            )
        with self.conn:
            self.conn.execute(
                """UPDATE accounts
                   SET frozen = frozen + ?, updated_at = datetime('now')
                   WHERE agent_id = ?""",
                (amount, agent_id),
            )
            tx_id = uuid.uuid4().hex
            self.conn.execute(
                """INSERT INTO transactions
                   (id, task_id, from_agent, amount, action, status, dispute_deadline, created_at)
                   VALUES (?, ?, ?, ?, 'hold', 'pending', ?, datetime('now'))""",
                (tx_id, task_id, agent_id, amount,
                 (datetime.now() + timedelta(days=DISPUTE_WINDOW_DAYS)).isoformat()),
            )
        return self.get_balance(agent_id)

    # ── release ─────────────────────────────────────────────────────────

    def release(
        self,
        task_id: str,
        publisher_id: str,
        executor_id: str,
        escrow_amount: int,
        publisher_share: float,
        executor_share: float,
        chain_hash: Optional[str] = None,
    ) -> dict:
        """Release held points to the executor and return surplus to the publisher.

        Args:
            task_id: Task identifier.
            publisher_id: Publisher agent ID.
            executor_id: Executor agent ID.
            escrow_amount: Total escrowed amount.
            publisher_share: Fraction of escrow returned to publisher.
            executor_share: Fraction of escrow paid to executor.
            chain_hash: Optional evidence chain hash for audit linking.

        Returns:
            A dict with ``executor_reward`` and ``publisher_return`` amounts.

        Raises:
            EscrowError: If the publisher's frozen balance is insufficient.
        """
        executor_reward = int(escrow_amount * executor_share) if executor_share else escrow_amount
        publisher_return = escrow_amount - executor_reward
        self._validate_hold(publisher_id, escrow_amount)

        with self.conn:
            self.conn.execute(
                """UPDATE accounts
                   SET frozen = frozen - ?,
                       balance = balance + ?,
                       updated_at = datetime('now')
                   WHERE agent_id = ?""",
                (escrow_amount, publisher_return, publisher_id),
            )
            self.conn.execute(
                """INSERT INTO accounts (agent_id, balance, frozen, updated_at)
                   VALUES (?, ?, 0, datetime('now'))
                   ON CONFLICT(agent_id) DO UPDATE SET
                       balance = balance + ?,
                       updated_at = datetime('now')""",
                (executor_id, executor_reward, executor_reward),
            )
            tx_id = uuid.uuid4().hex
            self.conn.execute(
                """INSERT INTO transactions
                   (id, task_id, from_agent, to_agent, amount, action, status, chain_hash, created_at)
                   VALUES (?, ?, ?, ?, ?, 'release', 'confirmed', ?, datetime('now'))""",
                (tx_id, task_id, publisher_id, executor_id, executor_reward, chain_hash),
            )
        return {"executor_reward": executor_reward, "publisher_return": publisher_return}

    # ── refund ──────────────────────────────────────────────────────────

    def refund(
        self,
        task_id: str,
        publisher_id: str,
        escrow_amount: int,
        reason: str = "cancelled",
        chain_hash: Optional[str] = None,
    ) -> dict:
        """Return held points to the publisher (on cancel / rejection).

        Args:
            task_id: Task identifier.
            publisher_id: Publisher agent ID.
            escrow_amount: Total escrowed amount to release back.
            reason: Cancellation reason (default ``"cancelled"``).
            chain_hash: Optional evidence chain hash for audit linking.

        Returns:
            Updated balance dict for the publisher.

        Raises:
            EscrowError: If the publisher's frozen balance is insufficient.
        """
        self._validate_hold(publisher_id, escrow_amount)
        with self.conn:
            self.conn.execute(
                """UPDATE accounts
                   SET frozen = frozen - ?,
                       updated_at = datetime('now')
                   WHERE agent_id = ?""",
                (escrow_amount, publisher_id),
            )
            tx_id = uuid.uuid4().hex
            self.conn.execute(
                """INSERT INTO transactions
                   (id, task_id, from_agent, to_agent, amount, action, status, chain_hash, extra, created_at)
                   VALUES (?, ?, ?, ?, ?, 'refund', 'confirmed', ?, ?, datetime('now'))""",
                (tx_id, task_id, publisher_id, publisher_id, escrow_amount, chain_hash,
                 json.dumps({"reason": reason})),
            )
        return self.get_balance(publisher_id)

    # ── auto-release ────────────────────────────────────────────────────

    def auto_release(self, task_id: str) -> Optional[dict]:
        """Automatically release escrow after the dispute window has expired.

        Args:
            task_id: Task to evaluate for auto-release.

        Returns:
            A dict with ``executor_reward``, ``publisher_return``, and
            ``type`` fields, or ``None`` if no eligible hold exists.
        """
        hold_tx = self.conn.execute(
            """SELECT * FROM transactions
               WHERE task_id = ? AND action = 'hold' AND status = 'pending'
               ORDER BY created_at DESC LIMIT 1""",
            (task_id,),
        ).fetchone()
        if hold_tx is None:
            return None
        hold_tx_dict = dict(hold_tx)
        deadline = hold_tx_dict.get("dispute_deadline")
        if deadline is None:
            return None
        deadline_dt = datetime.fromisoformat(deadline)
        if datetime.now() < deadline_dt:
            return None

        with self.conn:
            from_agent = hold_tx["from_agent"]
            escrow_amount = hold_tx["amount"]
            task = self.conn.execute(
                "SELECT executor_id FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if task is None or task["executor_id"] is None:
                return self.refund(task_id, from_agent, escrow_amount, reason="auto-refund-no-executor")

            executor_id = task["executor_id"]
            # Default 50/50 split; schema does not store per-task shares
            executor_reward = escrow_amount // 2
            publisher_return = escrow_amount - executor_reward

            self.conn.execute(
                """UPDATE accounts
                   SET frozen = frozen - ?, balance = balance + ?, updated_at = datetime('now')
                   WHERE agent_id = ?""",
                (escrow_amount, publisher_return, from_agent),
            )
            self.conn.execute(
                """INSERT INTO accounts (agent_id, balance, frozen, updated_at)
                   VALUES (?, ?, 0, datetime('now'))
                   ON CONFLICT(agent_id) DO UPDATE SET
                       balance = balance + ?, updated_at = datetime('now')""",
                (executor_id, executor_reward, executor_reward),
            )
            tx_id = uuid.uuid4().hex
            self.conn.execute(
                """INSERT INTO transactions
                   (id, task_id, from_agent, to_agent, amount, action, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'release', 'confirmed', datetime('now'))""",
                (tx_id, task_id, from_agent, executor_id, executor_reward),
            )
            self.conn.execute(
                "UPDATE transactions SET status = 'resolved' WHERE id = ?",
                (hold_tx["id"],),
            )
        return {"executor_reward": executor_reward, "publisher_return": publisher_return, "type": "auto_release"}

    # ── queries ─────────────────────────────────────────────────────────

    def get_transactions(self, task_id: str) -> list[dict]:
        """Retrieve all transactions for a given task.

        Args:
            task_id: Task identifier.

        Returns:
            List of transaction dicts ordered by creation time.
        """
        rows = self.conn.execute(
            "SELECT * FROM transactions WHERE task_id = ? ORDER BY created_at ASC",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_agent_transactions(self, agent_id: str, limit: int = 20) -> list[dict]:
        """Retrieve recent transactions for a specific agent.

        Args:
            agent_id: Agent identifier.
            limit: Maximum number of transactions to return (default 20).

        Returns:
            List of transaction dicts in reverse chronological order.
        """
        rows = self.conn.execute(
            """SELECT * FROM transactions
               WHERE from_agent = ? OR to_agent = ?
               ORDER BY created_at DESC LIMIT ?""",
            (agent_id, agent_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_dispute_eligible_tasks(self) -> list[dict]:
        """Find all tasks whose dispute deadline has passed.

        Returns:
            List of dicts with task_id, title, executor_id, amount,
            and dispute_deadline.
        """
        rows = self.conn.execute(
            """SELECT t.id as task_id, t.title, t.executor_id, et.amount, et.dispute_deadline
               FROM transactions et
               JOIN tasks t ON t.id = et.task_id
               WHERE et.action = 'hold'
                 AND et.status = 'pending'
                 AND et.dispute_deadline IS NOT NULL
                 AND et.dispute_deadline <= datetime('now')
               ORDER BY et.dispute_deadline ASC""",
        ).fetchall()
        return [dict(r) for r in rows]

    # ── validators ──────────────────────────────────────────────────────

    def _validate_hold(self, agent_id: str, amount: int) -> None:
        """Assert that an agent has sufficient frozen balance.

        Args:
            agent_id: Agent identifier.
            amount: Expected frozen amount.

        Raises:
            EscrowError: If the frozen balance does not match.
        """
        account = self.get_balance(agent_id)
        if account["frozen"] < amount:
            raise EscrowError(
                f"Agent frozen balance mismatch: have {account['frozen']}, need {amount}"
            )
