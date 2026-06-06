"""Tasks router — wraps TaskMarketService for task marketplace CRUD.

All TaskMarketService methods are async, so route handlers use async def.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from starlette.responses import JSONResponse
from task_market_api import CreateTaskRequest, TaskStatus

from ..deps import get_task_market_service

router = APIRouter()


class CreateTaskBody(BaseModel):
    """Request body for creating a new task.

    Attributes:
        title: Task title.
        description: Optional task description.
        escrow_amount: Number of points escrowed for this task.
        publisher_share: Fraction of escrow returned to the publisher on release.
        executor_share: Fraction of escrow paid to the executor on release.
    """

    title: str
    description: str = ""
    escrow_amount: int = 0
    publisher_share: float = 0.5
    executor_share: float = 0.5


class AssignTaskBody(BaseModel):
    """Request body for assigning a task to an executor.

    Attributes:
        agent_id: Identifier of the agent to assign as executor.
    """

    agent_id: str


class DeliverTaskBody(BaseModel):
    """Request body for delivering task output.

    Attributes:
        submission: URL or reference to the delivered work.
        executor_id: Identifier of the delivering executor.
    """

    submission: str  # delivery URL
    executor_id: str


class VerifyTaskBody(BaseModel):
    """Request body for verifying / rejecting a delivered task.

    Attributes:
        approved: Whether the delivery is approved.
        publisher_id: Identifier of the publisher agent.
    """

    approved: bool = True
    publisher_id: str


class CancelTaskBody(BaseModel):
    """Request body for cancelling a task.

    Attributes:
        agent_id: Identifier of the agent requesting cancellation.
    """

    agent_id: str


@router.post("/tasks")
async def create_task(body: CreateTaskBody, request: Request):
    """Create a new task in the marketplace.

    Args:
        body: Task creation payload.
        request: The incoming HTTP request (provides agent context).

    Returns:
        JSON with ``task_id``, ``title``, ``status``, ``publisher_id``,
        ``escrow_amount``, and ``created_at``.
    """
    svc = get_task_market_service()
    publisher_id = getattr(request.state, "agent_id", "unknown")
    try:
        req = CreateTaskRequest(
            title=body.title,
            description=body.description,
            escrow_amount=body.escrow_amount,
            publisher_share=body.publisher_share,
            executor_share=body.executor_share,
        )
        task = await svc.create_task(req, publisher_id, signature="gateway-sig")
        return JSONResponse(
            status_code=200,
            content={
                "task_id": task.id,
                "title": task.title,
                "status": task.status.value,
                "publisher_id": task.publisher_id,
                "escrow_amount": task.escrow_amount,
                "created_at": task.created_at,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/tasks")
async def list_tasks(
    request: Request,
    status: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
):
    """List tasks, optionally filtered by status or publisher.

    Args:
        request: The incoming HTTP request.
        status: Optional status filter (e.g. ``"open"``, ``"assigned"``).
        agent_id: Optional publisher agent ID filter.

    Returns:
        JSON with a ``tasks`` array containing task summaries.
    """
    svc = get_task_market_service()
    task_status = None
    if status:
        try:
            task_status = TaskStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid status: {status}")
    tasks = await svc.list_tasks(status=task_status, publisher_id=agent_id)
    return JSONResponse(
        status_code=200,
        content={
            "tasks": [
                {
                    "task_id": t.id,
                    "title": t.title,
                    "status": t.status.value,
                    "reward": t.escrow_amount,
                    "publisher_id": t.publisher_id,
                    "executor_id": t.executor_id,
                    "created_at": t.created_at,
                }
                for t in tasks
            ]
        },
    )


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Retrieve a single task by its ID.

    Args:
        task_id: Task identifier.

    Returns:
        JSON with full task details, or 404 if not found.
    """
    svc = get_task_market_service()
    task = await svc.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return JSONResponse(
        status_code=200,
        content={
            "task_id": task.id,
            "title": task.title,
            "description": task.description,
            "status": task.status.value,
            "reward": task.escrow_amount,
            "publisher_id": task.publisher_id,
            "executor_id": task.executor_id,
            "publisher_share": task.publisher_share,
            "executor_share": task.executor_share,
            "delivery_url": task.delivery_url,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        },
    )


@router.post("/tasks/{task_id}/assign")
async def assign_task(task_id: str, body: AssignTaskBody, request: Request):
    """Assign an executor to a task.

    Args:
        task_id: Task to assign.
        body: Assignment payload with executor agent_id.
        request: The incoming HTTP request.

    Returns:
        JSON with ``task_id``, ``agent_id``, and ``status``.
    """
    svc = get_task_market_service()
    executor_id = body.agent_id
    try:
        task = await svc.assign_task(task_id, executor_id, signature="gateway-sig")
        return JSONResponse(
            status_code=200,
            content={
                "task_id": task.id,
                "agent_id": task.executor_id,
                "status": task.status.value,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/tasks/{task_id}/deliver")
async def deliver_task(task_id: str, body: DeliverTaskBody):
    """Submit delivery for a task.

    Args:
        task_id: Task being delivered.
        body: Delivery payload with submission URL and executor ID.

    Returns:
        JSON with ``task_id``, ``status``, and ``submission``.
    """
    svc = get_task_market_service()
    try:
        task = await svc.deliver_task(
            task_id, body.submission, body.executor_id, signature="gateway-sig"
        )
        return JSONResponse(
            status_code=200,
            content={
                "task_id": task.id,
                "status": task.status.value,
                "submission": task.delivery_url,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/tasks/{task_id}/verify")
async def verify_task(task_id: str, body: VerifyTaskBody):
    """Verify or reject a delivered task.

    Args:
        task_id: Task to verify.
        body: Verification payload with approval flag and publisher ID.

    Returns:
        JSON with ``task_id``, ``status``, and ``approved``.
    """
    svc = get_task_market_service()
    try:
        task = await svc.verify_task(
            task_id, body.publisher_id, body.approved, signature="gateway-sig"
        )
        return JSONResponse(
            status_code=200,
            content={
                "task_id": task.id,
                "status": task.status.value,
                "approved": body.approved,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, body: CancelTaskBody):
    """Cancel a task.

    Args:
        task_id: Task to cancel.
        body: Cancellation payload with requesting agent ID.

    Returns:
        JSON with ``task_id`` and updated ``status``.
    """
    svc = get_task_market_service()
    try:
        task = await svc.cancel_task(task_id, body.agent_id, signature="gateway-sig")
        return JSONResponse(
            status_code=200,
            content={
                "task_id": task.id,
                "status": task.status.value,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
