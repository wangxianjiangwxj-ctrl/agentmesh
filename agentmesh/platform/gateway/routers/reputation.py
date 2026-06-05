"""Reputation router — wraps ReviewService for review submission and reputation query."""

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse
from pydantic import BaseModel

from ..deps import get_review_service

router = APIRouter()


class SubmitReviewBody(BaseModel):
    task_id: str
    target_id: str
    score: int
    comment: str = ""


@router.post("/reviews/submit")
def submit_review(body: SubmitReviewBody, request: Request):
    svc = get_review_service()
    rater_id = getattr(request.state, "agent_id", "unknown")
    try:
        result = svc.submit_review(
            task_id=body.task_id,
            rater_id=rater_id,
            target_id=body.target_id,
            score=body.score,
            comment=body.comment,
        )
        return JSONResponse(
            status_code=200,
            content={
                "review_id": result["id"],
                "task_id": result["task_id"],
                "reviewer_id": result["rater_id"],
                "target_id": result["target_id"],
                "score": result["score"],
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/reputation/{agent_id}")
def get_reputation(agent_id: str):
    svc = get_review_service()
    result = svc.get_reputation(agent_id)
    return JSONResponse(
        status_code=200,
        content={
            "agent_id": result["agent_id"],
            "reputation_score": result["avg_rating"],
            "total_reviews": result["total_reviews"],
        },
    )
