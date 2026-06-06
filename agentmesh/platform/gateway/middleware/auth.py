"""Auth middleware — API key validation via static dict or IdentityService lookup.

Provides a Starlette BaseHTTPMiddleware that validates ``X-API-Key``
headers against a static key map and the IdentityService database.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

API_KEYS = {"test-key": "test-agent"}  # 开发用 (fallback)


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that validates API keys on incoming requests.

    Public endpoints (``/api/v1/health``, ``/docs``, ``/openapi.json``)
    are allowed through without authentication. All other requests must
    provide a valid ``X-API-Key`` header.

    Authentication order:
      1. Static ``API_KEYS`` dict (dev fallback)
      2. IdentityService ``get_agent_by_auth()`` lookup
    """

    async def dispatch(self, request: Request, call_next):
        """Process an incoming request, validating the API key.

        Args:
            request: The incoming Starlette Request.
            call_next: The next middleware or route handler.

        Returns:
            A Response — either the original response from the route
            handler on success, or a 401 JSON error on auth failure.
        """
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
