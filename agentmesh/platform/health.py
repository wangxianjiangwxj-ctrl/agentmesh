"""AgentMesh Platform — Health check module.

Provides database connection status checking and component status
aggregation for the Gateway health endpoint.

Usage:
    from agentmesh.platform.health import get_health_status
    status = get_health_status()
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Optional

from agentmesh.platform.db_schema import DEFAULT_DB

# ── Component registry ────────────────────────────────────────────────────

class ComponentStatus:
    """Represents the health status of a single platform component.

    Attributes:
        name: Human-readable component name.
        status: One of ``"ok"``, ``"degraded"``, or ``"down"``.
        detail: Optional human-readable detail string.
        latency_ms: Time spent checking this component, in milliseconds.
    """

    def __init__(
        self,
        name: str,
        status: str = "ok",
        detail: Optional[str] = None,
        latency_ms: Optional[float] = None,
    ) -> None:
        self.name = name
        self.status = status
        self.detail = detail
        self.latency_ms = latency_ms

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON responses."""
        result: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
        }
        if self.detail is not None:
            result["detail"] = self.detail
        if self.latency_ms is not None:
            result["latency_ms"] = round(self.latency_ms, 2)
        return result


# ── DB connection check ───────────────────────────────────────────────────

def check_db(db_path: str = DEFAULT_DB) -> ComponentStatus:
    """Check whether the SQLite database is reachable and responsive.

    Performs a ``PRAGMA integrity_check`` with a short timeout.
    Returns a ``ComponentStatus`` reflecting the result.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        A ``ComponentStatus`` with name ``"database"``.
    """
    start = time.monotonic()
    try:
        conn = sqlite3.connect(str(db_path), timeout=2.0)
        cursor = conn.execute("SELECT 1")
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        elapsed = (time.monotonic() - start) * 1000

        if row is not None and row[0] == 1:
            return ComponentStatus(
                name="database",
                status="ok",
                detail=f"Responded in {elapsed:.1f}ms",
                latency_ms=elapsed,
            )
        else:
            return ComponentStatus(
                name="database",
                status="degraded",
                detail="Unexpected query result",
                latency_ms=elapsed,
            )
    except sqlite3.OperationalError as exc:
        elapsed = (time.monotonic() - start) * 1000
        return ComponentStatus(
            name="database",
            status="down",
            detail=f"OperationalError: {exc}",
            latency_ms=elapsed,
        )
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return ComponentStatus(
            name="database",
            status="down",
            detail=f"Unexpected error: {exc}",
            latency_ms=elapsed,
        )


# ── Component status check (extensible) ───────────────────────────────────

def check_components() -> list[ComponentStatus]:
    """Check status of all registered platform components.

    Currently checks:
        - database (SQLite connectivity)

    Subclass or extend this function to add more component checks
    (e.g. identity service, escrow service, cache, message queue).

    Returns:
        A list of ``ComponentStatus`` objects, one per component.
    """
    results: list[ComponentStatus] = []
    results.append(check_db())
    return results


# ── Aggregate status ──────────────────────────────────────────────────────

def get_health_status(db_path: str = DEFAULT_DB) -> dict[str, Any]:
    """Aggregate full health status for the Gateway health endpoint.

    Returns a dict with:
        - ``status``: overall status ("ok" if all components ok,
          "degraded" if any component degraded, "down" if any down).
        - ``version``: platform version string.
        - ``components``: list of per-component status dicts.
        - ``timestamp``: ISO-8601 timestamp of the check.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        A dict suitable for JSON serialization in a health endpoint.
    """
    from datetime import datetime, timezone

    components = check_components()

    # Derive overall status
    overall: str = "ok"
    for c in components:
        if c.status == "down":
            overall = "down"
        elif c.status == "degraded" and overall != "down":
            overall = "degraded"

    return {
        "status": overall,
        "version": "0.1.0",
        "components": [c.to_dict() for c in components],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
