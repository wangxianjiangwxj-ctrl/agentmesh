"""Escrow router — wraps EscrowService for point hold/release/refund."""

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse
from pydantic import BaseModel

from ..deps import get_escrow_service

router = APIRouter()


class HoldEscrowBody(BaseModel):
    """Request body for holding escrow points on a task."""
    task_id: str
    amount: int


class ReleaseEscrowBody(BaseModel):
    """Request body for releasing escrow points to executor."""
    task_id: str
    publisher_id: str = ""
    executor_id: str = ""
    escrow_amount: int = 0
    publisher_share: float = 0.5
    executor_share: float = 0.5


class RefundEscrowBody(BaseModel):
    """Request body for refunding escrow points to publisher."""
    task_id: str
    publisher_id: str = ""
    escrow_amount: int = 0


@router.post("/escrow/hold")
def hold_escrow(body: HoldEscrowBody, request: Request):
    """Lock points for a task's escrow."""
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
    """Release escrowed points to the executor on settlement."""
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
    """Refund escrowed points to the publisher on cancellation."""
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
