"""Admin Web UI router — renders Jinja2 dashboard, agent, task, and escrow pages.

Routes:
  GET /admin/          — Dashboard overview
  GET /admin/agents    — Agent list
  GET /admin/tasks     — Task list
  GET /admin/escrow    — Escrow transaction list
  GET /admin/companies — Company list
  GET /admin/equity    — Equity holdings
  GET /admin/dividends — Dividend records
  GET /admin/proposals — Proposals list
  POST /admin/...      — Form submissions for create/vote/publish
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from agentmesh.platform.company.equity import EquityService
from agentmesh.platform.dividend import DividendService
from agentmesh.platform.identity import IdentityService

from .deps import get_db, get_identity_service, get_task_market_service

web_router = APIRouter()

# ── Templates ──────────────────────────────────────────────────────────────

_templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_templates_dir)


# ── Helpers ────────────────────────────────────────────────────────────────


def _fmt_dt(raw: str | float | None) -> str:
    """Format a datetime string or unix timestamp to a human-readable string."""
    if raw is None:
        return "-"
    if isinstance(raw, (int, float)):
        dt = datetime.fromtimestamp(raw, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return str(raw)


def _fmt_ts(ts: float | None) -> str:
    """Format a unix timestamp."""
    if ts is None:
        return "-"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ── Schema helpers (Phase 34F) ────────────────────────────────────────

_COMPANY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS companies (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    founder_id      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','frozen','dissolved')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS company_members (
    company_id      TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member'
                    CHECK(role IN ('founder','admin','member')),
    joined_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (company_id, agent_id)
) WITHOUT ROWID;
"""

_PROPOSAL_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS proposals (
    id              TEXT PRIMARY KEY,
    company_id      TEXT NOT NULL DEFAULT '',
    title           TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    proposal_type   TEXT NOT NULL DEFAULT 'general'
                    CHECK(proposal_type IN ('general','budget','membership','equity')),
    proposer_id     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','passed','rejected','cancelled')),
    votes_for       INTEGER NOT NULL DEFAULT 0,
    votes_against   INTEGER NOT NULL DEFAULT 0,
    votes_abstain   INTEGER NOT NULL DEFAULT 0,
    deadline        TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at     TEXT
);
CREATE TABLE IF NOT EXISTS votes (
    id              TEXT PRIMARY KEY,
    proposal_id     TEXT NOT NULL,
    voter_id        TEXT NOT NULL,
    vote            TEXT NOT NULL CHECK(vote IN ('approve','reject','abstain')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(proposal_id, voter_id)
);
"""


def _ensure_company_schema(db) -> None:
    """Ensure companies and company_members tables exist."""
    db.executescript(_COMPANY_SCHEMA_SQL)
    db.commit()


def _ensure_proposal_schema(db) -> None:
    """Ensure proposals and votes tables exist."""
    db.executescript(_PROPOSAL_SCHEMA_SQL)
    db.commit()


# ── Routes ─────────────────────────────────────────────────────────────────


@web_router.get("/admin/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request):
    """Admin dashboard — shows summary statistics."""
    identity_svc = get_identity_service()
    task_market_svc = get_task_market_service()

    # Agent count
    agents = identity_svc.fetch_all_registrations()
    agent_count = len(agents)

    # Task count
    tasks = await task_market_svc.list_tasks()
    task_count = len(tasks)

    # Escrow summary from DB
    db = get_db()
    row = db.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total_escrow FROM transactions WHERE action = 'hold'"
    ).fetchone()
    total_escrow = row["total_escrow"] if row else 0

    # Active agent count (status column may not exist in all schema versions)
    try:
        active_agents = db.execute(
            "SELECT COUNT(*) AS cnt FROM agents WHERE status = 'active'"
        ).fetchone()
        active_agent_count = active_agents["cnt"] if active_agents else 0
    except Exception:
        active_agent_count = agent_count

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "page_title": "Dashboard",
            "agent_count": agent_count,
            "active_agent_count": active_agent_count,
            "task_count": task_count,
            "total_escrow": total_escrow,
        },
    )


@web_router.get("/admin/agents", response_class=HTMLResponse, include_in_schema=False)
def list_agents(request: Request):
    """Agent list page."""
    identity_svc = get_identity_service()
    agents = identity_svc.fetch_all_registrations()

    # Enrich agents with status and role from DB (columns may not exist)
    db = get_db()
    enriched: list[dict[str, Any]] = []
    for a in agents:
        status = "active"
        role = "agent"
        try:
            row = db.execute(
                "SELECT status, role FROM agents WHERE id = ?", (a["id"],)
            ).fetchone()
            if row:
                status = row["status"]
                role = row["role"]
        except Exception:
            pass
        enriched.append(
            {
                "id": a["id"],
                "did": a.get("did", ""),
                "name": a.get("name", ""),
                "status": status,
                "role": role,
                "reputation": round(a.get("reputation", 0.0), 2),
                "task_count": a.get("task_count", 0),
                "created_at": _fmt_dt(a.get("created_at")),
            }
        )

    return templates.TemplateResponse(
        "agents.html",
        {
            "request": request,
            "page_title": "Agents",
            "agents": enriched,
        },
    )


@web_router.get("/admin/tasks", response_class=HTMLResponse, include_in_schema=False)
async def list_tasks(request: Request):
    """Task list page."""
    task_market_svc = get_task_market_service()
    tasks = await task_market_svc.list_tasks()

    enriched: list[dict[str, Any]] = []
    for t in tasks:
        enriched.append(
            {
                "id": t.id,
                "title": t.title,
                "status": t.status.value,
                "publisher_id": t.publisher_id,
                "executor_id": t.executor_id or "-",
                "reward": t.escrow_amount,
                "created_at": _fmt_ts(t.created_at),
            }
        )

    return templates.TemplateResponse(
        "tasks.html",
        {
            "request": request,
            "page_title": "Tasks",
            "tasks": enriched,
        },
    )


@web_router.get("/admin/escrow", response_class=HTMLResponse, include_in_schema=False)
def list_escrow(request: Request):
    """Escrow transaction list page."""
    db = get_db()
    rows = db.execute(
        """SELECT id, task_id, from_agent, to_agent, amount, action, status,
                  created_at, resolved_at
           FROM transactions
           ORDER BY created_at DESC
           LIMIT 200"""
    ).fetchall()

    transactions: list[dict[str, Any]] = []
    for r in rows:
        transactions.append(
            {
                "id": r["id"],
                "task_id": r["task_id"],
                "from_agent": r["from_agent"],
                "to_agent": r.get("to_agent", ""),
                "amount": r["amount"],
                "action": r["action"],
                "status": r["status"],
                "created_at": _fmt_dt(r["created_at"]),
                "resolved_at": _fmt_dt(r.get("resolved_at")),
            }
        )

    # Total escrowed amount
    total_held = db.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM transactions WHERE action = 'hold'"
    ).fetchone()
    total_escrow = total_held["total"] if total_held else 0

    return templates.TemplateResponse(
        "escrow.html",
        {
            "request": request,
            "page_title": "Escrow",
            "transactions": transactions,
            "total_escrow": total_escrow,
        },
    )


# ── Company Management Routes (Phase 34F) ──────────────────────────


@web_router.get("/admin/companies", response_class=HTMLResponse, include_in_schema=False)
def list_companies(request: Request):
    """Company list page."""
    db = get_db()
    rows = db.execute(
        """SELECT c.*,
                  (SELECT COUNT(*) FROM company_members WHERE company_id = c.id) AS member_count
           FROM companies c ORDER BY c.created_at DESC"""
    ).fetchall()
    companies = []
    active = 0
    total_members = 0
    total_shares = 0
    for r in rows:
        d = dict(r)
        if d.get("status") == "active":
            active += 1
        total_members += d.get("member_count", 0)
        shares = db.execute(
            "SELECT COALESCE(SUM(shares),0) FROM equity_shares WHERE company_id = ?",
            (d["id"],),
        ).fetchone()[0]
        total_shares += shares
        d["created_at"] = _fmt_dt(d.get("created_at"))
        companies.append(d)
    return templates.TemplateResponse(
        "companies.html",
        {
            "request": request,
            "page_title": "Companies",
            "companies": companies,
            "active_count": active,
            "total_members": total_members,
            "total_shares": total_shares,
        },
    )


@web_router.get("/admin/companies/{company_id}", response_class=HTMLResponse, include_in_schema=False)
def company_detail(request: Request, company_id: str):
    """Company detail page."""
    db = get_db()
    company = db.execute(
        "SELECT * FROM companies WHERE id = ?", (company_id,)
    ).fetchone()
    if not company:
        return HTMLResponse("Company not found", status_code=404)
    company = dict(company)
    company["created_at"] = _fmt_dt(company.get("created_at"))

    # Cap table
    cap = db.execute(
        "SELECT agent_id, SUM(shares) as total_shares, GROUP_CONCAT(share_class) as classes "
        "FROM equity_shares WHERE company_id = ? GROUP BY agent_id ORDER BY total_shares DESC",
        (company_id,),
    ).fetchall()

    # Members
    members = db.execute(
        "SELECT * FROM company_members WHERE company_id = ? ORDER BY joined_at",
        (company_id,),
    ).fetchall()

    # Dividend funds
    funds = db.execute(
        "SELECT * FROM dividend_funds WHERE company_id = ? ORDER BY created_at DESC",
        (company_id,),
    ).fetchall()

    total_shares = db.execute(
        "SELECT COALESCE(SUM(shares),0) FROM equity_shares WHERE company_id = ?",
        (company_id,),
    ).fetchone()[0]

    return templates.TemplateResponse(
        "company_detail.html",
        {
            "request": request,
            "page_title": f"Company: {company['name']}",
            "company": company,
            "cap_table": [dict(r) for r in cap],
            "total_shares": total_shares,
            "members": [dict(r) for r in members],
            "funds": [dict(r) for r in funds],
            "member_count": len(members),
        },
    )


@web_router.get("/admin/equity", response_class=HTMLResponse, include_in_schema=False)
def list_equity(request: Request):
    """All equity holdings page."""
    db = get_db()
    holdings = db.execute(
        "SELECT * FROM equity_shares ORDER BY issued_at DESC LIMIT 200"
    ).fetchall()
    cap = db.execute(
        "SELECT COUNT(DISTINCT agent_id) as agents, COALESCE(SUM(shares),0) as total FROM equity_shares"
    ).fetchone()
    return templates.TemplateResponse(
        "equity.html",
        {
            "request": request,
            "page_title": "Equity",
            "holdings": [dict(r) for r in holdings],
            "total_agents": cap["agents"] if cap else 0,
            "total_shares_all": cap["total"] if cap else 0,
            "cap_table": [],
        },
    )


@web_router.get("/admin/dividends", response_class=HTMLResponse, include_in_schema=False)
def list_dividends(request: Request):
    """Dividend records page."""
    db = get_db()
    funds = db.execute(
        "SELECT * FROM dividend_funds ORDER BY created_at DESC LIMIT 100"
    ).fetchall()
    records = db.execute(
        "SELECT * FROM dividend_records ORDER BY created_at DESC LIMIT 200"
    ).fetchall()
    total_deposited = db.execute(
        "SELECT COALESCE(SUM(total_amount),0) FROM dividend_funds"
    ).fetchone()[0]
    total_distributed = db.execute(
        "SELECT COALESCE(SUM(dividend_amount),0) FROM dividend_records WHERE claimed = 1"
    ).fetchone()[0]
    return templates.TemplateResponse(
        "dividends.html",
        {
            "request": request,
            "page_title": "Dividends",
            "funds": [dict(r) for r in funds],
            "records": [dict(r) for r in records],
            "total_deposited": total_deposited,
            "total_distributed": total_distributed,
        },
    )


# ── Phase 34F POST Routes ────────────────────────────────────────────────


@web_router.get("/admin/companies/create", response_class=HTMLResponse, include_in_schema=False)
def company_create_form(request: Request):
    """Company creation form page."""
    return templates.TemplateResponse(
        "company_create.html",
        {"request": request, "page_title": "Create Company"},
    )


@web_router.post("/admin/companies/create", include_in_schema=False)
async def create_company(request: Request):
    """Handle company creation form submission."""
    form = await request.form()
    name = form.get("name", "")
    founder_id = form.get("founder_id", "")
    initial_shares = int(form.get("initial_shares", 1000))
    initial_class = form.get("initial_class", "founder")
    description = form.get("description", "")

    db = get_db()
    identity_svc = get_identity_service()

    # Ensure schema exists
    _ensure_company_schema(db)

    # Register the founder as an agent if not already registered
    existing = identity_svc.get_agent(founder_id)
    if existing is None:
        identity_svc.register(name=founder_id, auth_token=founder_id)

    # Create company
    company_id = uuid.uuid4().hex
    db.execute(
        "INSERT INTO companies (id, name, founder_id, description) VALUES (?, ?, ?, ?)",
        (company_id, name, founder_id, description),
    )
    db.execute(
        "INSERT INTO company_members (company_id, agent_id, role) VALUES (?, ?, 'founder')",
        (company_id, founder_id),
    )

    # Issue founder shares via EquityService
    equity_svc = EquityService(db)
    equity_svc.issue_shares(
        company_id, founder_id, initial_shares, share_class=initial_class
    )

    db.commit()

    return RedirectResponse(url="/admin/companies", status_code=303)


@web_router.get("/admin/proposals", response_class=HTMLResponse, include_in_schema=False)
def list_proposals(request: Request):
    """Proposals list page."""
    db = get_db()
    _ensure_proposal_schema(db)

    try:
        rows = db.execute("SELECT * FROM proposals ORDER BY created_at DESC").fetchall()
    except Exception:
        rows = []

    proposals = []
    total = 0
    pending = 0
    passed = 0
    rejected = 0
    for r in rows:
        d = dict(r)
        d["created_at"] = _fmt_dt(d.get("created_at"))
        total += 1
        if d["status"] == "active":
            pending += 1
        elif d["status"] == "passed":
            passed += 1
        elif d["status"] == "rejected":
            rejected += 1
        proposals.append(d)

    return templates.TemplateResponse(
        "proposals.html",
        {
            "request": request,
            "page_title": "Proposals",
            "proposals": proposals,
            "total": total,
            "pending": pending,
            "passed": passed,
            "rejected": rejected,
        },
    )


@web_router.get("/admin/proposals/new", response_class=HTMLResponse, include_in_schema=False)
def proposal_new_form(request: Request):
    """New proposal form page."""
    return templates.TemplateResponse(
        "proposal_new.html",
        {"request": request, "page_title": "New Proposal"},
    )


@web_router.post("/admin/proposals/new", include_in_schema=False)
async def create_proposal(request: Request):
    """Handle new proposal form submission."""
    form = await request.form()
    company_id = form.get("company_id", "")
    title = form.get("title", "")
    description = form.get("description", "")
    proposal_type = form.get("proposal_type", "general")
    deadline = form.get("deadline", None)
    proposer_id = form.get("proposer_id", "")

    db = get_db()
    _ensure_proposal_schema(db)

    proposal_id = uuid.uuid4().hex
    db.execute(
        """INSERT INTO proposals
           (id, company_id, title, description, proposal_type, proposer_id, deadline)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            proposal_id,
            company_id,
            title,
            description,
            proposal_type,
            proposer_id,
            deadline,
        ),
    )
    db.commit()

    return RedirectResponse(url="/admin/proposals", status_code=303)


@web_router.get("/admin/vote/{proposal_id}", response_class=HTMLResponse, include_in_schema=False)
def vote_form(request: Request, proposal_id: str):
    """Vote form page for a specific proposal."""
    db = get_db()
    _ensure_proposal_schema(db)
    row = db.execute(
        "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    if not row:
        return HTMLResponse("Proposal not found", status_code=404)
    proposal = dict(row)
    proposal["created_at"] = _fmt_dt(proposal.get("created_at"))
    return templates.TemplateResponse(
        "vote.html",
        {
            "request": request,
            "page_title": f"Vote: {proposal['title']}",
            "proposal": proposal,
        },
    )


@web_router.post("/admin/vote/{proposal_id}", include_in_schema=False)
async def submit_vote(request: Request, proposal_id: str):
    """Handle vote submission."""
    form = await request.form()
    vote = form.get("vote", "")
    voter_id = form.get("voter_id", "")

    if vote not in ("approve", "reject", "abstain"):
        return RedirectResponse(url="/admin/proposals", status_code=303)

    db = get_db()
    _ensure_proposal_schema(db)

    # Check if voter already voted on this proposal
    existing = db.execute(
        "SELECT id FROM votes WHERE proposal_id = ? AND voter_id = ?",
        (proposal_id, voter_id),
    ).fetchone()
    if existing:
        return RedirectResponse(url="/admin/proposals", status_code=303)

    # Record vote
    vote_id = uuid.uuid4().hex
    db.execute(
        "INSERT INTO votes (id, proposal_id, voter_id, vote) VALUES (?, ?, ?, ?)",
        (vote_id, proposal_id, voter_id, vote),
    )

    # Update proposal counts
    col_map = {
        "approve": "votes_for",
        "reject": "votes_against",
        "abstain": "votes_abstain",
    }
    col = col_map.get(vote)
    if col:
        db.execute(
            f"UPDATE proposals SET {col} = {col} + 1 WHERE id = ?", (proposal_id,)
        )

    db.commit()

    return RedirectResponse(url="/admin/proposals", status_code=303)


@web_router.get("/admin/dividends/publish", response_class=HTMLResponse, include_in_schema=False)
def dividend_publish_form(request: Request):
    """Dividend publish form page."""
    db = get_db()
    _ensure_company_schema(db)
    try:
        rows = db.execute("SELECT id, name FROM companies ORDER BY name").fetchall()
    except Exception:
        rows = []
    companies = [dict(r) for r in rows]
    return templates.TemplateResponse(
        "dividend_publish_form.html",
        {
            "request": request,
            "page_title": "Publish Dividend",
            "companies": companies,
        },
    )


@web_router.post("/admin/dividends/publish", include_in_schema=False)
async def publish_dividend(request: Request):
    """Handle dividend publish form submission."""
    form = await request.form()
    company_id = form.get("company_id", "")
    amount = int(form.get("amount", 0))
    source = form.get("source", "escrow")

    if amount <= 0 or not company_id:
        return RedirectResponse(url="/admin/dividends", status_code=303)

    db = get_db()

    # Deposit fund into company's dividend pool
    div_svc = DividendService(db)
    div_svc.deposit_fund(company_id, amount, source)

    # Auto-compute distribution for all available funds
    available = div_svc.get_available_funds(company_id)
    for fund in available:
        try:
            div_svc.compute_dividend(fund["id"])
        except Exception:
            pass  # Skip funds that fail (e.g., no shareholders)

    return RedirectResponse(url="/admin/dividends", status_code=303)
