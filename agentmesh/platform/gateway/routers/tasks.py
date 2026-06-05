"""Tasks router — wraps TaskMarketService for task marketplace CRUD.

All TaskMarketService methods are async, so route handlers use async def.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import JSONResponse
from pydantic import BaseModel

from ..deps import get_task_market_service
from task_market_api import CreateTaskRequest, TaskStatus

router = APIRouter()


class CreateTaskBody(BaseModel):
    title: str
    description: str = ""
    escrow_amount: int = 0
    publisher_share: float = 0.5
    executor_share: float = 0.5


class AssignTaskBody(BaseModel):
    agent_id: str


class DeliverTaskBody(BaseModel):
    submission: str  # delivery URL
    executor_id: str


class VerifyTaskBody(BaseModel):
    approved: bool = True
    publisher_id: str


class CancelTaskBody(BaseModel):
    agent_id: str


@router.post("/tasks")
async def create_task(body: CreateTaskBody, request: Request):
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
