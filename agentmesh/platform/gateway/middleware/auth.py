"""Auth middleware — API key validation via static dict or IdentityService lookup.

Provides a Starlette BaseHTTPMiddleware that validates ``X-API-Key``
headers against a static key map and the IdentityService database.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

API_KEYS = {"test-key": "test-agent"}  # 开发用 (fallback)

PUBLIC_PATHS = frozenset({"/api/v1/health", "/docs", "/openapi.json"})


def _is_public_path(path: str) -> bool:
    """Check whether a request path is a public (no-auth) endpoint.

    Args:
        path: The incoming request path.

    Returns:
        ``True`` if the path is in the public endpoint set.
    """
    return path in PUBLIC_PATHS


def _resolve_by_api_key(api_key: str) -> str | None:
    """Resolve an agent ID from an API key using static map + IdentityService.

    Authentication order:
      1. Static ``API_KEYS`` dict (dev fallback)
      2. IdentityService ``get_agent_by_auth()`` lookup
      3. Candidate from static dict used as literal ``get_agent()`` lookup

    Args:
        api_key: The ``X-API-Key`` header value.

    Returns:
        An agent ID string if resolved, or ``None`` if not found.
    """
    if api_key not in API_KEYS:
        return _resolve_by_identity_auth(api_key)

    candidate = API_KEYS[api_key]

    # Try identity service first
    try:
        from ..deps import get_identity_service

        svc = get_identity_service()
        agent = svc.get_agent_by_auth(api_key)
        if agent:
            return agent["id"]
        # Try the candidate as agent_id
        agent = svc.get_agent(candidate)
        if agent:
            return agent["id"]
    except Exception:
        pass

    # Fallback to static mapping
    return candidate


def _resolve_by_identity_auth(api_key: str) -> str | None:
    """Resolve an agent ID from an API key using IdentityService only.

    Args:
        api_key: The ``X-API-Key`` header value.

    Returns:
        An agent ID string if found, or ``None``.
    """
    try:
        from ..deps import get_identity_service

        svc = get_identity_service()
        agent = svc.get_agent_by_auth(api_key)
        if agent:
            return agent["id"]
    except Exception:
        pass
    return None


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
        if _is_public_path(request.url.path):
            return await call_next(request)

        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return JSONResponse(
                status_code=401,
                content={"error": "missing API key"},
            )

        agent_id = _resolve_by_api_key(api_key)
        if agent_id is not None:
            request.state.agent_id = agent_id
            return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"error": "invalid API key"},
        )
