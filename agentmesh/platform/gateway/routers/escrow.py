"""Escrow router — wraps EscrowService for point hold/release/refund.

Provides REST endpoints for escrow lifecycle management, tied to
the authenticated agent from the request context.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.responses import JSONResponse

from ..deps import get_escrow_service

router = APIRouter()


class HoldEscrowBody(BaseModel):
    """Request body for placing an escrow hold.

    Attributes:
        task_id: Task to hold escrow for.
        amount: Number of points to lock.
    """

    task_id: str
    amount: int


class ReleaseEscrowBody(BaseModel):
    """Request body for releasing escrow to the executor.

    Attributes:
        task_id: Task whose escrow to release.
        publisher_id: Publisher agent ID (falls back to request agent).
        executor_id: Executor agent ID.
        escrow_amount: Total amount to release.
        publisher_share: Fraction returned to publisher.
        executor_share: Fraction paid to executor.
    """

    task_id: str
    publisher_id: str = ""
    executor_id: str = ""
    escrow_amount: int = 0
    publisher_share: float = 0.5
    executor_share: float = 0.5


class RefundEscrowBody(BaseModel):
    """Request body for refunding escrow to the publisher.

    Attributes:
        task_id: Task whose escrow to refund.
        publisher_id: Publisher agent ID (falls back to request agent).
        escrow_amount: Total amount to refund.
    """

    task_id: str
    publisher_id: str = ""
    escrow_amount: int = 0


@router.post("/escrow/hold")
def hold_escrow(body: HoldEscrowBody, request: Request):
    """Lock points for a task escrow.

    Args:
        body: Hold request with task_id and amount.
        request: The incoming HTTP request (provides agent context).

    Returns:
        JSON with ``task_id``, ``amount``, ``payer_id``, ``status``,
        and updated ``balance``.
    """
    svc = get_escrow_service()
    agent_id = getattr(request.state, "agent_id", "unknown")
    svc.ensure_account(agent_id)
    try:
        result = svc.hold(agent_id, body.task_id, body.amount)
        return JSONResponse(
            status_code=200,
            content={
                "task_id": body.task_id,
                "amount": body.amount,
                "payer_id": agent_id,
                "status": "held",
                "balance": result,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/escrow/release")
def release_escrow(body: ReleaseEscrowBody, request: Request):
    """Release escrow points to the executor.

    Args:
        body: Release request with task_id, agent IDs, and shares.
        request: The incoming HTTP request (provides agent context).

    Returns:
        JSON with ``task_id``, ``status``, ``executor_reward``, and
        ``publisher_return``.
    """
    svc = get_escrow_service()
    agent_id = getattr(request.state, "agent_id", "unknown")
    publisher_id = body.publisher_id or agent_id
    try:
        result = svc.release(
            task_id=body.task_id,
            publisher_id=publisher_id,
            executor_id=body.executor_id,
            escrow_amount=body.escrow_amount,
            publisher_share=body.publisher_share,
            executor_share=body.executor_share,
        )
        return JSONResponse(
            status_code=200,
            content={
                "task_id": body.task_id,
                "status": "released",
                "executor_reward": result["executor_reward"],
                "publisher_return": result["publisher_return"],
            },
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/escrow/refund")
def refund_escrow(body: RefundEscrowBody, request: Request):
    """Refund escrow points to the publisher (on cancel / rejection).

    Args:
        body: Refund request with task_id, publisher ID, and amount.
        request: The incoming HTTP request (provides agent context).

    Returns:
        JSON with ``task_id``, ``status``, and updated ``balance``.
    """
    svc = get_escrow_service()
    agent_id = getattr(request.state, "agent_id", "unknown")
    publisher_id = body.publisher_id or agent_id
    try:
        result = svc.refund(
            task_id=body.task_id,
            publisher_id=publisher_id,
            escrow_amount=body.escrow_amount,
        )
        return JSONResponse(
            status_code=200,
            content={
                "task_id": body.task_id,
                "status": "refunded",
                "balance": result,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
