"""AgentMesh Platform — Phase 34E: Escrow & Dividend Integration.

Bridges the EscrowService and DividendService so that task rewards can
automatically contribute to company dividend pools.

Key capabilities:
  - ``dividend_deposit_from_escrow`` — Move funds from a company's escrow
    account into its dividend fund pool.
  - ``company_aware_release`` — Perform a standard escrow release and
    automatically deduct a configurable contribution to the company
    dividend fund (if the executor belongs to a company).
  - ``get_company_earnings`` — Aggregate total income earned by all
    members of a company through escrow releases.
"""
from __future__ import annotations

import uuid

from dividend import DividendError, DividendService
from escrow import EscrowError, EscrowService


class EscrowIntegrationError(Exception):
    """Raised when an escrow-integration business rule is violated."""


# ---------------------------------------------------------------------------
# 1. Deposit escrow funds into a company dividend pool
# ---------------------------------------------------------------------------

def dividend_deposit_from_escrow(
    escrow_svc: EscrowService,
    dividend_svc: DividendService,
    company_id: str,
    amount: int,
    source: str = "task_reward",
) -> dict:
    """Transfer funds from a company's escrow account to its dividend pool.

    The company's escrow account is identified by ``company_id`` (the
    same convention used throughout the escrow module).

    Args:
        escrow_svc: EscrowService instance (provides ``accounts`` and
            ``transactions`` table access).
        dividend_svc: DividendService instance (provides dividend fund
            management).
        company_id: Company identifier (used as escrow agent ID).
        amount: Positive integer number of points to deposit.
        source: Source label for the dividend fund (default
            ``"task_reward"``).

    Returns:
        A dict with the created dividend fund (keys include
        ``fund_id``, ``company_id``, ``amount``).

    Raises:
        EscrowError: If amount is not positive or available balance
            is insufficient.
        EscrowIntegrationError: If the debit transaction fails.
    """
    if amount <= 0:
        raise EscrowError("Deposit amount must be positive")

    # Verify sufficient available balance
    bal = escrow_svc.get_balance(company_id)
    if bal["available"] < amount:
        raise EscrowError(
            f"Insufficient available balance in company '{company_id[:12]}': "
            f"have {bal['available']}, need {amount}"
        )

    # Debit the company's escrow account directly via SQL
    with escrow_svc.conn:
        escrow_svc.conn.execute(
            """UPDATE accounts
               SET balance = balance - ?,
                   updated_at = datetime('now')
               WHERE agent_id = ?""",
            (amount, company_id),
        )
        tx_id = uuid.uuid4().hex
        escrow_svc.conn.execute(
            """INSERT INTO transactions
               (id, task_id, from_agent, to_agent, amount, action, status, extra, created_at)
               VALUES (?, 'SYSTEM', ?, 'dividend_fund', ?, 'transfer', 'confirmed', ?, datetime('now'))""",
            (tx_id, company_id, amount, '{"source": "dividend_deposit"}'),
        )

    # Create the dividend fund record
    result = dividend_svc.deposit_fund(company_id, amount, source)
    return result


# ---------------------------------------------------------------------------
# 2. Company-aware escrow release
# ---------------------------------------------------------------------------

def company_aware_release(
    escrow_svc: EscrowService,
    dividend_svc: DividendService,
    task_id: str,
    publisher_id: str,
    executor_id: str,
    escrow_amount: int,
    publisher_share: float = 0.3,
    executor_share: float = 0.7,
    contribution_rate: float = 0.1,
) -> dict:
    """Perform a standard escrow release with optional company dividend contribution.

    The function:
    1. Executes a standard escrow ``release`` with the given shares.
    2. Checks whether the executor is a member of any company (by
       querying ``company_members``).
    3. If the executor belongs to a company, deducts
       ``contribution_rate * executor_reward`` from the executor's
       balance and deposits it into the company's dividend fund.

    Args:
        escrow_svc: EscrowService instance.
        dividend_svc: DividendService instance.
        task_id: Task identifier.
        publisher_id: Publisher agent ID.
        executor_id: Executor agent ID.
        escrow_amount: Total escrowed amount (points).
        publisher_share: Fraction of escrow returned to publisher
            (default 0.3).
        executor_share: Fraction of escrow paid to executor
            (default 0.7).
        contribution_rate: Fraction of executor reward deducted for
            company dividend pool (default 0.1, i.e. 10%%).

    Returns:
        A dict with the full breakdown:

        .. code-block:: python

            {
                "release": {
                    "executor_reward": 140,
                    "publisher_return": 60,
                },
                "company_contribution": {
                    "executor_id": "...",
                    "company_id": "...",
                    "contribution_amount": 14,
                    "contribution_rate": 0.1,
                    "fund_id": "...",
                } if executor belongs to a company else None,
                "net_rewards": {
                    "executor_net": 126,
                    "publisher_return": 60,
                },
            }

    Raises:
        EscrowError: If the escrow release fails.
        EscrowIntegrationError: If the dividend deposit fails.
    """
    # Step 1: Standard escrow release
    release_result = escrow_svc.release(
        task_id=task_id,
        publisher_id=publisher_id,
        executor_id=executor_id,
        escrow_amount=escrow_amount,
        publisher_share=publisher_share,
        executor_share=executor_share,
    )
    executor_reward = release_result["executor_reward"]
    publisher_return = release_result["publisher_return"]

    result: dict = {
        "release": release_result,
        "company_contribution": None,
        "net_rewards": {
            "executor_net": executor_reward,
            "publisher_return": publisher_return,
        },
    }

    # Step 2: Check if executor belongs to a company
    companies = _find_companies_for_agent(escrow_svc.conn, executor_id)
    if not companies:
        return result

    # Use the first company the executor belongs to
    company_id = companies[0]

    # Step 3: Deduct contribution from executor's balance
    contribution_amount = int(executor_reward * contribution_rate)
    if contribution_amount <= 0:
        return result

    with escrow_svc.conn:
        escrow_svc.conn.execute(
            """UPDATE accounts
               SET balance = balance - ?,
                   updated_at = datetime('now')
               WHERE agent_id = ? AND balance >= ?""",
            (contribution_amount, executor_id, contribution_amount),
        )
        # Record the contribution transaction
        tx_id = uuid.uuid4().hex
        escrow_svc.conn.execute(
            """INSERT INTO transactions
               (id, task_id, from_agent, to_agent, amount, action, status, extra, created_at)
               VALUES (?, ?, ?, ?, ?, 'transfer', 'confirmed', ?, datetime('now'))""",
            (
                tx_id,
                task_id,
                executor_id,
                company_id,
                contribution_amount,
                '{"source": "dividend_contribution"}',
            ),
        )

    # Step 4: Deposit into company dividend fund
    try:
        fund_result = dividend_svc.deposit_fund(
            company_id, contribution_amount, source="task_contribution"
        )
    except DividendError as exc:
        raise EscrowIntegrationError(
            f"Failed to deposit dividend contribution: {exc}"
        ) from exc

    result["company_contribution"] = {
        "executor_id": executor_id,
        "company_id": company_id,
        "contribution_amount": contribution_amount,
        "contribution_rate": contribution_rate,
        "fund_id": fund_result["fund_id"],
    }
    result["net_rewards"]["executor_net"] = executor_reward - contribution_amount

    return result


# ---------------------------------------------------------------------------
# 3. Query company total earnings
# ---------------------------------------------------------------------------

def get_company_earnings(
    escrow_svc: EscrowService,
    company_id: str,
) -> dict:
    """Aggregate total escrow earnings for all members of a company.

    Queries the ``transactions`` table for all ``release`` transactions
    where the recipient (``to_agent``) is a member of the given company.

    Args:
        escrow_svc: EscrowService instance.
        company_id: Company identifier.

    Returns:
        A dict with:

        .. code-block:: python

            {
                "company_id": "...",
                "total_earnings": 500,
                "member_earnings": [
                    {"agent_id": "...", "total": 300},
                    {"agent_id": "...", "total": 200},
                ],
            }
    """
    # Get all company members
    members = _get_company_members(escrow_svc.conn, company_id)
    if not members:
        return {
            "company_id": company_id,
            "total_earnings": 0,
            "member_earnings": [],
        }

    # Build a list of (agent_id, total) for each member
    member_earnings: list[dict] = []
    total_earnings = 0

    for member_id in members:
        row = escrow_svc.conn.execute(
            """SELECT COALESCE(SUM(amount), 0)
               FROM transactions
               WHERE to_agent = ?
                 AND action IN ('release', 'transfer')""",
            (member_id,),
        ).fetchone()
        amount = row[0] if row else 0
        if amount > 0:
            member_earnings.append({"agent_id": member_id, "total": amount})
            total_earnings += amount

    return {
        "company_id": company_id,
        "total_earnings": total_earnings,
        "member_earnings": member_earnings,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_companies_for_agent(conn, agent_id: str) -> list[str]:
    """Return a list of company IDs the agent is a member of.

    Args:
        conn: SQLite connection with a ``company_members`` table.
        agent_id: Agent identifier to look up.

    Returns:
        List of company IDs (may be empty).
    """
    rows = conn.execute(
        "SELECT company_id FROM company_members WHERE agent_id = ?",
        (agent_id,),
    ).fetchall()
    return [r["company_id"] for r in rows]


def _get_company_members(conn, company_id: str) -> list[str]:
    """Return all agent IDs that are members of a company.

    Args:
        conn: SQLite connection with a ``company_members`` table.
        company_id: Company identifier.

    Returns:
        List of agent IDs (may be empty).
    """
    rows = conn.execute(
        "SELECT agent_id FROM company_members WHERE company_id = ?",
        (company_id,),
    ).fetchall()
    return [r["agent_id"] for r in rows]
