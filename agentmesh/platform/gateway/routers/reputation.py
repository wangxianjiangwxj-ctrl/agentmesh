"""Reputation router — wraps ReviewService for review submission and reputation query.

Provides REST endpoints for submitting reviews and querying agent
reputation scores.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.responses import JSONResponse

from ..deps import get_review_service

router = APIRouter()


class SubmitReviewBody(BaseModel):
    """Request body for submitting a review.

    Attributes:
        task_id: Task the review relates to.
        target_id: Agent being reviewed.
        score: Rating from 1 (worst) to 5 (best).
        comment: Optional textual feedback.
    """

    task_id: str
    target_id: str
    score: int
    comment: str = ""


@router.post("/reviews/submit")
def submit_review(body: SubmitReviewBody, request: Request):
    """Submit a review for an agent on a completed task.

    The authenticated agent becomes the reviewer.

    Args:
        body: Review submission payload.
        request: The incoming HTTP request (provides reviewer context).

    Returns:
        JSON with ``review_id``, ``task_id``, ``reviewer_id``,
        ``target_id``, and ``score``.
    """
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
    """Query the reputation score for an agent.

    Args:
        agent_id: Agent identifier.

    Returns:
        JSON with ``agent_id``, ``reputation_score``, and
        ``total_reviews``.
    """
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
