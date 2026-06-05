"""Auth middleware — API key validation via static dict or IdentityService lookup."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

API_KEYS = {"test-key": "test-agent"}  # 开发用 (fallback)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/api/v1/health", "/docs", "/openapi.json"):
            return await call_next(request)
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return JSONResponse(
                status_code=401,
                content={"error": "missing API key"},
            )

        # Check static dict first
        if api_key in API_KEYS:
            candidate = API_KEYS[api_key]
            # Try to find a registered agent by auth_token or candidate ID
            try:
                from ..deps import get_identity_service

                svc = get_identity_service()
                agent = svc.get_agent_by_auth(api_key)
                if agent:
                    request.state.agent_id = agent["id"]
                    return await call_next(request)
                # Try the candidate as agent_id
                agent = svc.get_agent(candidate)
                if agent:
                    request.state.agent_id = agent["id"]
                    return await call_next(request)
            except Exception:
                pass
            # Fallback to static mapping
            request.state.agent_id = candidate
            return await call_next(request)

        # Try IdentityService auth_token lookup for unknown keys
        try:
            from ..deps import get_identity_service

            svc = get_identity_service()
            agent = svc.get_agent_by_auth(api_key)
            if agent:
                request.state.agent_id = agent["id"]
                return await call_next(request)
        except Exception:
            pass

        return JSONResponse(
            status_code=401,
            content={"error": "invalid API key"},
        )
