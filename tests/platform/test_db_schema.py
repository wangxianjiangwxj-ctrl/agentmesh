"""Tests for db_schema module."""
from __future__ import annotations

import tempfile
from pathlib import Path

from db_schema import create_test_db, get_conn, init_db


class TestDbSchema:
    def test_get_conn(self):
        """get_conn creates and returns an initialised connection."""
        conn, db_path = create_test_db()
        # Re-open same DB via get_conn
        conn2 = get_conn(db_path)
        try:
            assert conn2 is not None
            row = conn2.execute(
                "SELECT COUNT(*) as c FROM agents"
            ).fetchone()
            assert row["c"] == 0
        finally:
            conn2.close()
            conn.close()
            Path(db_path).unlink(missing_ok=True)

    def test_init_db_respects_path(self):
        """init_db creates a proper SQLite file at the given path."""
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        f.close()
        try:
            conn = init_db(f.name)
            assert conn is not None
            # Verify tables exist
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = [r["name"] for r in tables]
            assert "agents" in table_names
            assert "accounts" in table_names
            conn.close()
        finally:
            Path(f.name).unlink(missing_ok=True)
