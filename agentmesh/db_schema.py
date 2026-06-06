"""
AgentMesh Platform — Shared DB schema (SQLite + WAL)

Covers all 5 MVP modules. All FKs at application-level (no DB-level FKs
for testability). Schema v2 — unified after Phase 19 Day 1 alignment.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

DEFAULT_DB = "agentmesh_platform.db"

SCHEMA_SQL = """
-- ====================================================================
-- Module 1: Agent identity
-- ====================================================================
CREATE TABLE IF NOT EXISTS agents (
    id              TEXT PRIMARY KEY,
    did             TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    public_key      TEXT NOT NULL,
    auth_token      TEXT,
    metadata        TEXT DEFAULT '{}',
    reputation      REAL DEFAULT 0.0,
    task_count      INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_private_keys (
    agent_id        TEXT PRIMARY KEY,
    private_key_enc TEXT NOT NULL
);

-- ====================================================================
-- Module 2: Task Market + Bids
-- ====================================================================
CREATE TABLE IF NOT EXISTS tasks (
    id                  TEXT PRIMARY KEY,
    publisher_id        TEXT NOT NULL,
    title               TEXT NOT NULL,
    description         TEXT NOT NULL DEFAULT '',
    escrow_amount       INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'draft'
                        CHECK(status IN (
                            'draft','open','assigned','delivered',
                            'verified','rejected','disputed','cancelled','settled'
                        )),
    executor_id         TEXT,
    delivery_url        TEXT,
    delivery_hash       TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_publisher ON tasks(publisher_id);

CREATE TABLE IF NOT EXISTS task_bids (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL,
    bidder_id       TEXT NOT NULL,
    bid_amount      INTEGER NOT NULL,
    message         TEXT DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','accepted','rejected','withdrawn')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bids_task ON task_bids(task_id);

-- ====================================================================
-- Module 3: Audit / Evidence chain
-- ====================================================================
CREATE TABLE IF NOT EXISTS evidence_chain (
    id                  TEXT PRIMARY KEY,
    task_id             TEXT NOT NULL,
    chain_index         INTEGER NOT NULL,   -- auto-increment per task
    action              TEXT NOT NULL,
    actor_id            TEXT NOT NULL,
    payload_digest      TEXT NOT NULL,
    signature           TEXT NOT NULL,       -- primary signature (actor)
    secondary_sig       TEXT,                -- optional counterparty sig
    chain_prev_hash     TEXT,
    chain_hash          TEXT NOT NULL,
    extra               TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_evidence_task ON evidence_chain(task_id, chain_index);
CREATE INDEX IF NOT EXISTS idx_evidence_actor ON evidence_chain(actor_id);

CREATE TABLE IF NOT EXISTS evidence_chain_heads (
    task_id             TEXT PRIMARY KEY,
    latest_hash         TEXT NOT NULL,
    latest_index        INTEGER NOT NULL DEFAULT 0,
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ====================================================================
-- Module 4: Accounts + Transactions (unified escrow)
-- ====================================================================
CREATE TABLE IF NOT EXISTS accounts (
    agent_id            TEXT PRIMARY KEY,
    balance             INTEGER NOT NULL DEFAULT 0,
    frozen              INTEGER NOT NULL DEFAULT 0,
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id                  TEXT PRIMARY KEY,
    task_id             TEXT,
    from_agent          TEXT,
    to_agent            TEXT,
    amount              INTEGER NOT NULL,
    action              TEXT NOT NULL
                        CHECK(action IN (
                            'deposit','hold','release','refund','transfer','fee'
                        )),
    status              TEXT NOT NULL DEFAULT 'confirmed'
                        CHECK(status IN ('pending','confirmed','disputed','resolved')),
    dispute_deadline    TEXT,
    chain_hash          TEXT,
    extra               TEXT DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_tx_task ON transactions(task_id);
CREATE INDEX IF NOT EXISTS idx_tx_agent ON transactions(from_agent);

-- ====================================================================
-- Module 5: Reputation + Revenue shares
-- ====================================================================
CREATE TABLE IF NOT EXISTS reviews (
    id                  TEXT PRIMARY KEY,
    task_id             TEXT NOT NULL,
    reviewer_id         TEXT NOT NULL,
    target_id           TEXT NOT NULL,
    rating              INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    comment             TEXT DEFAULT '',
    chain_hash          TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_reviews_target ON reviews(target_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_reviews_unique ON reviews(task_id, reviewer_id, target_id);

CREATE TABLE IF NOT EXISTS agent_reputation (
    agent_id            TEXT PRIMARY KEY,
    avg_rating          REAL DEFAULT 0.0,
    total_reviews       INTEGER DEFAULT 0,
    as_publisher        INTEGER DEFAULT 0,
    as_executor         INTEGER DEFAULT 0,
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- revenue_shares: support N-party split (MVP uses 2)
CREATE TABLE IF NOT EXISTS revenue_shares (
    id                  TEXT PRIMARY KEY,
    task_id             TEXT NOT NULL,
    agent_id            TEXT NOT NULL,
    share_pct           REAL NOT NULL CHECK(share_pct > 0 AND share_pct <= 1.0),
    role                TEXT NOT NULL DEFAULT 'executor'
                        CHECK(role IN ('publisher','executor','reviewer','referrer','other')),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_revenue_task ON revenue_shares(task_id);
"""


def init_db(db_path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """Initialise a SQLite database with the full AgentMesh schema.

    Creates all tables (agents, tasks, evidence_chain, accounts,
    transactions, reviews, agent_reputation, revenue_shares).

    Args:
        db_path: Path to the database file. Defaults to "agentmesh_platform.db".

    Returns:
        Configured SQLite connection with Row factory and WAL journal mode.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def get_conn(db_path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """Get a configured SQLite connection (convenience wrapper for init_db).

    Args:
        db_path: Path to the database file. Defaults to "agentmesh_platform.db".

    Returns:
        Configured SQLite connection.
    """
    return init_db(db_path)


def create_test_db() -> tuple[sqlite3.Connection, str]:
    """Create a temporary SQLite database for testing.

    Returns:
        Tuple of (connection, temp_file_path).
    """
    import tempfile
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return init_db(f.name), f.name
