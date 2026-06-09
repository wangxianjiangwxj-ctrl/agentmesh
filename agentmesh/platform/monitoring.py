"""AgentMesh Platform — Monitoring module.

Provides error counting and alert threshold configuration for
platform components. Designed to integrate with the existing
logging pipeline (see :mod:`agentmesh.platform.logging_config`).

Typical usage::

    from agentmesh.platform.monitoring import ErrorTracker

    tracker = ErrorTracker()
    tracker.record("escrow.release", "RuntimeError: timeout")
    report = tracker.report()

Alert thresholds are defined in ``config`` module-level dict and
can be overridden at runtime.
"""

from __future__ import annotations

import os
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

# ── Default alert thresholds ──────────────────────────────────────────────

#: Default alert thresholds per error category.
#:
#: Each entry maps a category name (or ``"*"`` for default) to a dict:
#:
#: .. code-block:: python
#:
#:     {
#:         "max_count": 10,        # Alert if errors exceed this in window
#:         "window_seconds": 300,  # Rolling time window (5 minutes)
#:         "min_interval": 60,     # Minimum seconds between alerts
#:     }
#:
#: Categories follow the convention ``<component>.<operation>``,
#: for example ``"escrow.release"``, ``"identity.auth"``, ``"db.query"``.
#:
#: Override by setting the ``AGENTMESH_ALERT_THRESHOLDS`` environment
#: variable to a JSON string. File-based config is planned for a
#: future release.
ALERT_THRESHOLDS: dict[str, dict[str, Any]] = {
    "*": {
        "max_count": 10,
        "window_seconds": 300,
        "min_interval": 60,
    },
    "db.query": {
        "max_count": 5,
        "window_seconds": 60,
        "min_interval": 120,
    },
    "escrow.release": {
        "max_count": 3,
        "window_seconds": 300,
        "min_interval": 300,
    },
    "identity.auth": {
        "max_count": 20,
        "window_seconds": 300,
        "min_interval": 60,
    },
}


# ── Error event ───────────────────────────────────────────────────────────

class ErrorEvent:
    """A single recorded error event.

    Attributes:
        category: Error category string (e.g. ``"db.query"``).
        message: Human-readable error message or exception repr.
        timestamp: ISO-8601 UTC timestamp.
    """

    def __init__(self, category: str, message: str) -> None:
        self.category = category
        self.message = message
        self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "category": self.category,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


# ── Error Tracker ─────────────────────────────────────────────────────────

class ErrorTracker:
    """Thread-safe error event tracker with rolling-window alerting.

    Records error events, maintains counters per category, and supports
    alert threshold evaluation based on a configurable time window.

    Thread-safety is guaranteed through a reentrant lock. The class is
    designed as a singleton for production use; call
    :func:`get_error_tracker` to obtain the shared instance.

    Args:
        thresholds: Optional dict of category -> threshold config.
            Falls back to the module-level ``ALERT_THRESHOLDS``.
    """

    def __init__(
        self,
        thresholds: Optional[dict[str, dict[str, Any]]] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._events: list[ErrorEvent] = []
        self._thresholds = thresholds or ALERT_THRESHOLDS
        self._last_alert: dict[str, datetime] = {}

    def record(self, category: str, message: str) -> None:
        """Record a single error event.

        Args:
            category: Error category (e.g. ``"db.query"``).
            message: Human-readable description of the error.
        """
        with self._lock:
            self._events.append(ErrorEvent(category, message))

    def count(self, category: Optional[str] = None) -> int:
        """Count total recorded errors, optionally filtered by category.

        Args:
            category: If provided, only count events matching this
                category (exact match).

        Returns:
            Total number of matching error events.
        """
        with self._lock:
            if category is None:
                return len(self._events)
            return sum(1 for e in self._events if e.category == category)

    def count_in_window(
        self,
        category: str,
        window_seconds: int = 300,
    ) -> int:
        """Count errors in a sliding time window.

        Args:
            category: Category to filter by.
            window_seconds: Rolling window size in seconds.

        Returns:
            Number of events in the window matching *category*.
        """
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - window_seconds
        with self._lock:
            return sum(
                1
                for e in self._events
                if e.category == category and e.timestamp.timestamp() > cutoff
            )

    def should_alert(self, category: str) -> bool:
        """Check whether an alert should fire for a given category.

        Returns ``True`` if the error count in the threshold window
        exceeds ``max_count`` AND the minimum alert interval
        (``min_interval``) has elapsed since the last alert.

        Args:
            category: Category to evaluate.

        Returns:
            ``True`` if an alert should be raised.
        """
        config = self._thresholds.get(category) or self._thresholds.get("*", {})
        max_count = config.get("max_count", 10)
        window_seconds = config.get("window_seconds", 300)
        min_interval = config.get("min_interval", 60)

        count = self.count_in_window(category, window_seconds)
        if count < max_count:
            return False

        last = self._last_alert.get(category)
        if last is not None:
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
            if elapsed < min_interval:
                return False

        return True

    def mark_alerted(self, category: str) -> None:
        """Mark that an alert was sent for a category (updates cooldown).

        Args:
            category: Category that was alerted on.
        """
        with self._lock:
            self._last_alert[category] = datetime.now(timezone.utc)

    def report(self) -> dict[str, Any]:
        """Generate a snapshot report of all tracked errors.

        Returns a dict with:
            - ``total``: total error count.
            - ``by_category``: breakdown of error counts per category.
            - ``recent``: up to 100 most recent error events (as dicts).
            - ``alert_thresholds``: current threshold configuration.

        Returns:
            A dict suitable for diagnostic endpoints or log output.
        """
        with self._lock:
            by_category: dict[str, int] = defaultdict(int)
            for e in self._events:
                by_category[e.category] += 1

            recent = [e.to_dict() for e in self._events[-100:]]

            return {
                "total": len(self._events),
                "by_category": dict(by_category),
                "recent": recent,
                "alert_thresholds": dict(self._thresholds),
            }

    def clear(self) -> None:
        """Clear all recorded error events (for tests or reset)."""
        with self._lock:
            self._events.clear()
            self._last_alert.clear()

    @property
    def events(self) -> list[ErrorEvent]:
        """Return a copy of all recorded events (thread-safe)."""
        with self._lock:
            return list(self._events)

    @property
    def last_alert_times(self) -> dict[str, datetime]:
        """Return a copy of last-alert timestamps (thread-safe)."""
        with self._lock:
            return dict(self._last_alert)


# ── Singleton accessor ────────────────────────────────────────────────────

_TRACKER: Optional[ErrorTracker] = None
_TRACKER_LOCK = threading.RLock()


def get_error_tracker() -> ErrorTracker:
    """Return the global singleton ErrorTracker instance.

    The singleton is configured with the module-level
    ``ALERT_THRESHOLDS``, which may be overridden via environment
    variables (see the ``AGENTMESH_ALERT_THRESHOLDS`` env var).

    Returns:
        The shared ``ErrorTracker`` instance.
    """
    global _TRACKER
    if _TRACKER is None:
        with _TRACKER_LOCK:
            if _TRACKER is None:
                thresholds = _load_thresholds_from_env()
                _TRACKER = ErrorTracker(thresholds=thresholds)
    return _TRACKER


def _load_thresholds_from_env() -> Optional[dict[str, dict[str, Any]]]:
    """Load alert thresholds from the ``AGENTMESH_ALERT_THRESHOLDS`` env var.

    Expects a JSON-encoded dict in the same format as
    :data:`ALERT_THRESHOLDS`.

    Returns:
        Parsed thresholds dict, or ``None`` if the env var is unset
        or invalid.
    """
    raw = os.environ.get("AGENTMESH_ALERT_THRESHOLDS")
    if not raw:
        return None
    try:
        import json
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return None
        return parsed
    except (json.JSONDecodeError, ValueError):
        import logging
        logging.getLogger(__name__).warning(
            "Invalid AGENTMESH_ALERT_THRESHOLDS env var; falling back to defaults"
        )
        return None
