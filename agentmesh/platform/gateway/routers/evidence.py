"""Evidence router — wraps EvidenceChainService for recording and querying evidence chain.

Provides REST endpoints for recording evidence entries and querying
the evidence chain for a given task.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.responses import JSONResponse

from ..deps import get_evidence_service

router = APIRouter()


class RecordEvidenceBody(BaseModel):
    """Request body for recording an evidence chain entry.

    Attributes:
        task_id: Task this evidence belongs to.
        action: Lifecycle action name.
        payload: Optional event payload dict.
        secondary_actor_id: Optional secondary signer agent ID.
        extra: Optional extra metadata dict.
    """

    task_id: str
    action: str
    payload: Optional[dict] = None
    secondary_actor_id: Optional[str] = None
    extra: Optional[dict] = None


@router.post("/evidence/record")
def record_evidence(body: RecordEvidenceBody, request: Request):
    """Record a new evidence chain entry.

    The authenticated agent becomes the primary actor for the entry.

    Args:
        body: Evidence recording payload.
        request: The incoming HTTP request (provides agent context).

    Returns:
        JSON with ``evidence_id``, ``task_id``, ``chain_index``,
        ``action``, ``actor_id``, ``chain_hash``, and ``created_at``.
    """
    svc = get_evidence_service()
    agent_id = getattr(request.state, "agent_id", "unknown")
    try:
        entry = svc.record(
            task_id=body.task_id,
            action=body.action,
            actor_id=agent_id,
            payload=body.payload or {},
            secondary_actor_id=body.secondary_actor_id,
            extra=body.extra,
        )
        return JSONResponse(
            status_code=200,
            content={
                "evidence_id": entry.id,
                "task_id": entry.task_id,
                "chain_index": entry.chain_index,
                "action": entry.action,
                "actor_id": entry.actor_id,
                "chain_hash": entry.chain_hash,
                "created_at": entry.created_at,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/evidence/{task_id}")
def query_evidence(task_id: str):
    """Retrieve the full evidence chain for a task.

    Args:
        task_id: Task identifier.

    Returns:
        JSON with ``task_id`` and a ``chain`` array of evidence entries.
    """
    svc = get_evidence_service()
    try:
        chain = svc.get_by_task(task_id)
        return JSONResponse(
            status_code=200,
            content={
                "task_id": task_id,
                "chain": [
                    {
                        "evidence_id": e["id"],
                        "chain_index": e["chain_index"],
                        "action": e["action"],
                        "actor_id": e["actor_id"],
                        "chain_hash": e["chain_hash"],
                        "created_at": e["created_at"],
                    }
                    for e in chain
                ],
            },
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
