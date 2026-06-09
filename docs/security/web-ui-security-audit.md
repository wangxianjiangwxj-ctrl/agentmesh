# Web UI Security Audit -- XSS & CSRF

**Date**: 2026-06-09
**Scope**: `agentmesh/platform/gateway/templates/` (Jinja2 HTML templates)
**Backend**: `agentmesh/platform/gateway/routers/web_ui.py`

---

## Summary

| Vector | Status | Risk |
|--------|--------|------|
| XSS (Reflected / Stored) | Auto-escaped via Jinja2 `{{ }}` | **Low** |
| XSS via `|safe` filter | Not used in any template | **Safe** |
| CSRF Token | Missing in all POST forms | **Medium** |
| Content Security Policy (CSP) header | Missing | **Low-Medium** |
| Clickjacking protection (X-Frame-Options) | Missing | **Low** |
| HSTS header | Missing | **Low** |

---

## A. XSS Analysis

### What was checked

Each `.html` template in `gateway/templates/` was reviewed for:

1. `{{ variable }}` output with `|safe` filter (disables auto-escaping)
2. `{% autoescape false %}` blocks
3. Inline JavaScript event handlers with user data (`onclick`, `onerror`, `onload`)
4. `javascript:` URI in `href` attributes
5. Template injection via Jinja2 expression evaluation

### Files Reviewed (15 templates)

| Template | Variables Rendered | Auto-escaped? | Risk |
|----------|-------------------|---------------|------|
| `base.html` | `page_title`, `request.url.path` | Yes (auto) | Safe |
| `dashboard.html` | `agent_count`, `active_agent_count`, `task_count`, `total_escrow` | Yes (auto) | Safe |
| `agents.html` | `agent.id`, `agent.name`, `agent.status`, `agent.role`, `agent.reputation`, `agent.task_count`, `agent.created_at` | Yes (auto) | Safe |
| `tasks.html` | `task.id`, `task.title`, `task.status`, `task.reward`, `task.publisher_id`, `task.executor_id`, `task.created_at` | Yes (auto) | Safe |
| `escrow.html` | `tx.*`, `total_escrow` | Yes (auto) | Safe |
| `companies.html` | `c.name`, `c.founder_id`, `c.member_count`, `c.status`, `c.created_at` | Yes (auto) | Safe |
| `company_detail.html` | `company.name`, `company.id`, `company.founder_id`, `company.status`, `company.created_at`, `s.*`, `m.*`, `f.*` | Yes (auto) | Safe |
| `company_create.html` | None (form only) | N/A | Safe |
| `login.html` | `error` | Yes (auto) | Safe |
| `equity.html` | `h.company_id`, `h.agent_id`, `h.shares`, `h.share_class`, `h.issued_at` | Yes (auto) | Safe |
| `dividends.html` | `f.*`, `r.*` | Yes (auto) | Safe |
| `dividend_publish_form.html` | `c.id`, `c.name` | Yes (auto) | Safe |
| `proposals.html` | `p.id`, `p.title`, `p.company_id`, `p.proposer_id`, `p.status`, `p.votes_for`, `p.votes_against`, `p.created_at` | Yes (auto) | Safe |
| `proposal_new.html` | None (form only) | N/A | Safe |
| `vote.html` | `proposal.*` | Yes (auto) | Safe |

### Finding: The `error` variable in `login.html`

```html
{% if error %}
<div class="alert" role="alert">{{ error }}</div>
{% endif %}
```

If `error` is constructed from user-provided data (e.g. username parameter in a "user not found" message), it is still auto-escaped by Jinja2's `{{ }}`. **No immediate risk**, but the backend should be reviewed to ensure error messages do not echo raw user input.

### Finding: `agent.name` in agent list

```html
<td class="fw-semibold">{{ agent.name }}</td>
```

If `agent.name` contains HTML like `<script>alert(1)</script>`, Jinja2 will render it as literal text (`&lt;script&gt;...`). **Safe** due to auto-escaping.

### XSS Verdict

No exploitable XSS vulnerabilities found. Jinja2's default auto-escaping (`{{ }}`) protects all rendered variables. No `|safe` filter or `{% autoescape false %}` block was detected in any template.

---

## B. CSRF Analysis

### Finding: Missing CSRF tokens

**All 5 POST endpoints** lack CSRF token validation:

| Endpoint | Method | Form Action |
|----------|--------|-------------|
| `/admin/companies/create` | POST | `company_create.html` |
| `/admin/proposals/new` | POST | `proposal_new.html` |
| `/admin/vote/{proposal_id}` | POST | `vote.html` |
| `/admin/dividends/publish` | POST | `dividend_publish_form.html` |
| `/admin/login` | POST | `login.html` |

**Impact**: An attacker can craft a `<form>` or `<img>` tag on an external site that, when visited by an authenticated admin, silently submits a POST request to any of these endpoints. Since sessions are authenticated via API key (sent as form data, not cookies), the practical attack surface is narrower than cookie-based auth, but still non-zero if:

- The admin has previously authenticated in the same browser session
- The API key is stored in session storage or a cookie

**Recommended Fix**: Add CSRF token generation and validation:

1. Install `fastapi-csrf-protect` or implement a simple token scheme.
2. In each GET form page, include a hidden `csrf_token` field.
3. In each POST handler, verify the token against the session.

**Example implementation**:

```python
# Middleware/route-level CSRF protection
from fastapi import Request, HTTPException
import secrets, hashlib

def generate_csrf_token(request: Request) -> str:
    token = secrets.token_hex(32)
    request.session["csrf_token"] = token
    return token

def verify_csrf_token(request: Request, form_token: str) -> None:
    expected = request.session.get("csrf_token")
    if not expected or not hmac.compare_digest(expected, form_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
```

---

## C. Missing Security Headers

The application does not set the following security-relevant HTTP headers:

| Header | Purpose | Priority |
|--------|---------|----------|
| `Content-Security-Policy` | Restricts script/style sources, mitigates XSS | High |
| `X-Frame-Options: DENY` | Prevents clickjacking | Medium |
| `X-Content-Type-Options: nosniff` | Prevents MIME-type sniffing | Medium |
| `Strict-Transport-Security` | Enforces HTTPS | Medium |
| `Referrer-Policy` | Controls referrer info leakage | Low |
| `Permissions-Policy` | Restricts browser feature access | Low |

### Recommendation

Add a middleware to inject these headers on all responses:

```python
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "font-src https://cdn.jsdelivr.net; "
            "form-action 'self'; "
            "base-uri 'self'; "
        )
        return response
```

---

## D. Recommendations (Priority Order)

1. **HIGH**: Add CSRF token validation to all POST endpoints (companies/create, proposals/new, vote, dividends/publish, login).
2. **HIGH**: Add `Content-Security-Policy` header to restrict script/style origins (currently loading Bootstrap from CDN -- whitelist only known CDN URLs).
3. **MEDIUM**: Add `X-Frame-Options: DENY` and `X-Content-Type-Options: nosniff` headers.
4. **MEDIUM**: Ensure the `error` variable passed to `login.html` template never echoes unsanitized user input from form fields.
5. **LOW**: Consider upgrading to Python 3.12+ for improved HTML escaping performance.
6. **LOW**: Add automated XSS regression tests that send `<script>alert(1)</script>` payloads through input forms and verify they render as escaped text.

---

## E. Conclusion

The web UI templates are **XSS-safe** due to Jinja2's auto-escaping. The primary concern is the **absence of CSRF protection** on all form-based POST endpoints and **missing security headers**. None of these issues represent an immediate exploit path given the API-key-based auth model, but hardening these areas significantly reduces the attack surface as the admin panel matures.
