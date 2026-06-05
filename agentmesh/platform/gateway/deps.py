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

# ── Import real modules — local platform-agentmesh first, then task_market ──

# Add the local platform-agentmesh directory (this package's siblings)
_local_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _local_dir not in sys.path:
    sys.path.insert(0, _local_dir)

# Add the task_market_api.py parent directory (only for task_market_api)
# task_market_api is at: <workspace>/shangshuling/platform-agentmesh/task_market_api.py
_base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..', '..'))
_tm_dir = os.path.join(_base_dir, 'platform-agentmesh')
if _tm_dir not in sys.path:
    sys.path.append(_tm_dir)  # append, NOT insert(0) — local takes priority

from db_schema import SCHEMA_SQL
import identity
# Monkey-patch identity module to use check_same_thread=False (needed for TestClient)
_orig_identity_init = identity.init_db
def _patched_identity_init(db_path):
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(identity.CREATE_TABLE_SQL)
    conn.commit()
    return conn
identity.init_db = _patched_identity_init

from identity import IdentityService
from escrow import EscrowService
from evidence_chain import EvidenceChainService
from reputation import ReviewService
from task_market_api import (
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
    """Create a fresh SQLite connection and run the unified schema."""
    global _db_path
    _db_path = db_path
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def get_db() -> sqlite3.Connection:
    """Lazy-initialized shared DB connection."""
    global _db
    if _db is None:
        _db = init_db(_db_path)
    return _db


def reset_db() -> None:
    """Close and clear all singletons (used in tests)."""
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
    """Create a temp file for the shared DB and return its path."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return f.name


# ── Service factories (lazy init, all share the same DB file) ─────────────


def get_identity_service() -> IdentityService:
    """Lazy-init IdentityService. Uses the shared DB file path."""
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
    """Lazy-init EscrowService."""
    global _escrow_svc
    if _escrow_svc is None:
        _escrow_svc = EscrowService(
            db_conn=get_db(),
            identity_svc=get_identity_service(),
        )
    return _escrow_svc


def get_evidence_service() -> EvidenceChainService:
    """Lazy-init EvidenceChainService."""
    global _evidence_svc
    if _evidence_svc is None:
        _evidence_svc = EvidenceChainService(
            identity_svc=get_identity_service(),
            db_conn=get_db(),
        )
    return _evidence_svc


def get_review_service() -> ReviewService:
    """Lazy-init ReviewService."""
    global _review_svc
    if _review_svc is None:
        _review_svc = ReviewService(
            db_conn=get_db(),
            identity_svc=get_identity_service(),
            evidence_svc=get_evidence_service(),
        )
    return _review_svc


def get_task_market_service() -> TaskMarketService:
    """Lazy-init TaskMarketService with in-memory repo + mock sig verifier."""
    global _task_market_svc
    if _task_market_svc is None:
        _task_market_svc = TaskMarketService(
            repo=InMemoryTaskRepository(),
            sig_verifier=MockSignatureVerifier(),
        )
    return _task_market_svc
