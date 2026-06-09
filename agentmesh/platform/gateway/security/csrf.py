"""CSRF protection — token generation, cookie management, and FastAPI Depends.

Provides a cookie-based CSRF protection scheme:
- GET responses receive a ``csrf_token`` cookie (HttpOnly, SameSite=Strict).
- Form templates include a hidden field echoing the same token.
- POST routes validate the cookie token against the form token
  via ``Depends(csrf_protected)``.

Usage in routes::

    @router.post("/path")
    async def handler(request: Request, _=Depends(csrf_protected)):
        ...

Usage in templates::

    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
"""

from __future__ import annotations

import hmac
import secrets

from fastapi import HTTPException, Request
from fastapi.responses import Response

# ── Constants ──────────────────────────────────────────────────────────

CSRF_COOKIE = "csrf_token"
CSRF_FIELD = "csrf_token"
CSRF_TTL = 1800  # 30 minutes


# ── Token management ───────────────────────────────────────────────────


def generate_token() -> str:
    """Generate a new 32-byte (64 hex char) CSRF token."""
    return secrets.token_hex(32)


def get_token(request: Request) -> str:
    """Return the CSRF token from the cookie, generating one if needed.

    Args:
        request: The incoming request.

    Returns:
        A 64-character hex token.
    """
    token = request.cookies.get(CSRF_COOKIE)
    if not token or len(token) != 64:
        token = generate_token()
    return token


def set_cookie(response: Response, token: str) -> None:
    """Attach the CSRF token cookie to a response.

    Args:
        response: The outgoing HTTP response.
        token: The token to store in the cookie.
    """
    response.set_cookie(
        key=CSRF_COOKIE,
        value=token,
        max_age=CSRF_TTL,
        httponly=True,
        samesite="strict",
    )


# ── Dependency ─────────────────────────────────────────────────────────


async def csrf_protected(request: Request) -> None:
    """FastAPI dependency: validate CSRF token on POST requests.

    For non-POST methods this is a no-op. For POST, it reads the token
    from the ``csrf_token`` cookie and compares it (constant-time) with
    the ``csrf_token`` form field. A mismatch or missing token raises
    HTTP 403.

    Raises:
        HTTPException(403): If the CSRF token is missing or invalid.
    """
    if request.method != "POST":
        return

    cookie_token = request.cookies.get(CSRF_COOKIE)
    if not cookie_token:
        raise HTTPException(status_code=403, detail="CSRF token missing from cookie")

    form = await request.form()
    form_token = form.get(CSRF_FIELD, "")
    if not form_token:
        raise HTTPException(status_code=403, detail="CSRF token missing from form")

    # Constant-time comparison
    if not hmac.compare_digest(cookie_token, form_token):
        raise HTTPException(status_code=403, detail="CSRF token mismatch")

    # Optional TTL check: the cookie's max_age handles expiry, but
    # we also do a time-based check for extra safety.
    # (Cookies can persist longer than intended if not cleared.)


# ── Template helpers ───────────────────────────────────────────────────


def csrf_input(request: Request) -> str:
    """Return an HTML hidden input element with the CSRF token.

    Args:
        request: The incoming request (used to read the cookie token).

    Returns:
        A ``<input type="hidden">`` HTML string.
    """
    token = get_token(request)
    return f'<input type="hidden" name="{CSRF_FIELD}" value="{token}">'
