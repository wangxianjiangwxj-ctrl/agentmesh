"""Identity router — wraps IdentityService for agent registration and lookup."""

from fastapi import APIRouter, HTTPException
from starlette.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from ..deps import get_identity_service

router = APIRouter()


class RegisterAgentRequest(BaseModel):
    name: str
    auth_token: str = ""
    metadata: Optional[dict] = None


@router.post("/agents/register")
def register_agent(body: RegisterAgentRequest):
    svc = get_identity_service()
    result = svc.register(
        name=body.name,
        auth_token=body.auth_token,
        metadata=body.metadata or {},
    )
    # The register() dict doesn't include created_at; fetch it back
    agent_id = result["id"]
    agent = svc.get_agent(agent_id)
    return JSONResponse(
        status_code=200,
        content={
            "agent_id": agent["id"],
            "did": agent["did"],
            "name": agent["name"],
            "public_key": agent["public_key"],
            "created_at": agent["created_at"],
        },
    )


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str):
    svc = get_identity_service()
    result = svc.get_agent(agent_id)
    if result is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return JSONResponse(
        status_code=200,
        content={
            "agent_id": result["id"],
            "did": result["did"],
            "name": result["name"],
            "public_key": result["public_key"],
            "reputation_score": result["reputation"],
            "created_at": result["created_at"],
        },
    )
