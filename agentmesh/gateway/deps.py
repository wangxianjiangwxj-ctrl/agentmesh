"""
Gateway dependency injection — connects FastAPI routes to real module services.

Initializes a shared SQLite database (temp file or :memory:) and creates
all service instances (IdentityService, EscrowService, EvidenceChainService,
ReviewService, TaskMarketService) using the db_schema.py unified schema.
"""

from __future__ import annotations

import os
import sys
import tempfile
import sqlite3
from pathlib import Path
from typing import Optional

# ── Import real modules from the agentmesh package ──

from agentmesh.db_schema import SCHEMA_SQL
from agentmesh.identity import (
    IdentityService,
    init_db as identity_init_db,
    CREATE_TABLE_SQL,
)
from agentmesh.escrow import EscrowService
from agentmesh.evidence_chain import EvidenceChainService
from agentmesh.reputation import ReviewService
from agentmesh.task_market_api import (
    TaskMarketService,
    InMemoryTaskRepository,
    MockSignatureVerifier,
)

# ── Global lazy singletons ────────────────────────────────────────────────

_db: Optional[sqlite3.Connection] = None
_db_path: str = ":memory:"
_identity_svc: Optional[IdentityService] = None
_escrow_svc: Optional[EscrowService] = None
_evidence_svc: Optional[EvidenceChainService] = None
_review_svc: Optional[ReviewService] = None
_task_market_svc: Optional[TaskMarketService] = None


# ── DB helpers ────────────────────────────────────────────────────────────


def init_db(db_path: str = ":memory:") -> sqlite3.Connection:
    """Create a fresh SQLite connection and run the unified schema.

    Args:
        db_path: Path to the SQLite database file. Defaults to ":memory:".

    Returns:
        Configured SQLite connection with row factory and WAL mode.
    """
    global _db_path
    _db_path = db_path
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def get_db() -> sqlite3.Connection:
    """Get the lazy-initialized shared database connection.

    Creates the connection on first call using the current ``_db_path``.

    Returns:
        Shared SQLite connection.
    """
    global _db
    if _db is None:
        _db = init_db(_db_path)
    return _db


def reset_db() -> None:
    """Close and clear all singleton services (for test isolation).

    Closes the shared DB connection and resets all global service
    references to ``None`` so they are re-created on next access.
    """
    global _db, _identity_svc, _escrow_svc, _evidence_svc, _review_svc, _task_market_svc
    global _db_path
    for svc in (_identity_svc,):
        if svc is not None:
            try:
                svc.close()
            except Exception:
                pass
    if _db is not None:
        try:
            _db.close()
        except Exception:
            pass
    _db = None
    _db_path = ":memory:"
    _identity_svc = None
    _escrow_svc = None
    _evidence_svc = None
    _review_svc = None
    _task_market_svc = None


def get_temp_db_path() -> str:
    """Create a temporary file for the shared database.

    Returns:
        Path string to a temporary .db file.
    """
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return f.name


# ── Service factories (lazy init, all share the same DB file) ─────────────


def get_identity_service() -> IdentityService:
    """Get the lazy-initialized IdentityService singleton.

    If the current DB path is ``:memory:``, migrates to a temp file
    so that ``IdentityService`` can open its own connection.

    Returns:
        Singleton IdentityService instance.
    """
    global _identity_svc, _db, _db_path
    if _identity_svc is None:
        # IdentityService opens its own connection but needs the same DB file
        if _db_path == ":memory:":
            db_path = get_temp_db_path()
            _db_path = db_path
            # Re-init our shared connection to the same temp file
            _db = init_db(db_path)
        _identity_svc = IdentityService(_db_path)
        # trigger connection init (creates identity tables with IF NOT EXISTS)
        _identity_svc.conn
    return _identity_svc


def get_escrow_service() -> EscrowService:
    """Get the lazy-initialized EscrowService singleton.

    Returns:
        Singleton EscrowService instance.
    """
    global _escrow_svc
    if _escrow_svc is None:
        _escrow_svc = EscrowService(
            db_conn=get_db(),
            identity_svc=get_identity_service(),
        )
    return _escrow_svc


def get_evidence_service() -> EvidenceChainService:
    """Get the lazy-initialized EvidenceChainService singleton.

    Returns:
        Singleton EvidenceChainService instance.
    """
    global _evidence_svc
    if _evidence_svc is None:
        _evidence_svc = EvidenceChainService(
            identity_svc=get_identity_service(),
            db_conn=get_db(),
        )
    return _evidence_svc


def get_review_service() -> ReviewService:
    """Get the lazy-initialized ReviewService singleton.

    Returns:
        Singleton ReviewService instance.
    """
    global _review_svc
    if _review_svc is None:
        _review_svc = ReviewService(
            db_conn=get_db(),
            identity_svc=get_identity_service(),
            evidence_svc=get_evidence_service(),
        )
    return _review_svc


def get_task_market_service() -> TaskMarketService:
    """Get the lazy-initialized TaskMarketService singleton.

    Uses an in-memory task repository and mock signature verifier.

    Returns:
        Singleton TaskMarketService instance.
    """
    global _task_market_svc
    if _task_market_svc is None:
        _task_market_svc = TaskMarketService(
            repo=InMemoryTaskRepository(),
            sig_verifier=MockSignatureVerifier(),
        )
    return _task_market_svc
