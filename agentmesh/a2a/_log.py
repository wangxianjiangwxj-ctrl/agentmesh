"""
AgentMesh A2A Structured Logging.

Provides StructuredLogger that emits JSON-formatted log entries with
trace context, component metadata, and custom fields (stdlib logging).

Usage::

    from agentmesh.a2a import StructuredLogger, LogLevel

    log = StructuredLogger("my-component")
    log.info("card_sent", detail="Task card dispatched")
    log.error("connection_failed", error="timeout", peer="agent-b")
"""

from __future__ import annotations

import enum
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ._trace import TraceProvider

# ---------------------------------------------------------------------------
# LogLevel
# ---------------------------------------------------------------------------


class LogLevel(str, enum.Enum):
    """Structured log severity levels, mapped to stdlib logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"

    def to_stdlib(self) -> int:
        """Return the equivalent stdlib ``logging`` level constant."""
        return _LEVEL_MAP[self]

    @classmethod
    def from_stdlib(cls, level: int) -> "LogLevel":
        """Reverse-map a stdlib logging level to a ``LogLevel``."""
        # Iterate from most to least severe; return the first match
        for ll in (cls.ERROR, cls.WARN, cls.INFO, cls.DEBUG):
            if level >= ll.to_stdlib():
                return ll
        return cls.DEBUG


_LEVEL_MAP: Dict[LogLevel, int] = {
    LogLevel.DEBUG: logging.DEBUG,
    LogLevel.INFO: logging.INFO,
    LogLevel.WARN: logging.WARN,
    LogLevel.ERROR: logging.ERROR,
}

# ---------------------------------------------------------------------------
# LoggerConfig
# ---------------------------------------------------------------------------


@dataclass
class LoggerConfig:
    """Global configuration for structured loggers.

    Attributes:
        level:        Minimum severity to emit (default ``INFO``).
        output:       One of ``"stderr"``, ``"stdout"``, or a file path.
        format:       Output format — currently only ``"json"`` is supported.
        extra_fields: Default extra fields injected into every log record.
    """

    level: LogLevel = LogLevel.INFO
    output: str = "stderr"
    format: str = "json"
    extra_fields: Dict[str, Any] = field(default_factory=dict)


# Module-level singleton config
_DEFAULT_CONFIG = LoggerConfig()

# ---------------------------------------------------------------------------
# StructuredLogger
# ---------------------------------------------------------------------------


class StructuredLogger:
    """JSON-structured logger with automatic trace context and extra fields.

    Each log entry is a single JSON line containing:

    - ``timestamp``   — ISO-8601 UTC
    - ``level``       — ``DEBUG`` / ``INFO`` / ``WARN`` / ``ERROR``
    - ``component``   — name passed at construction
    - ``event``       — event name (e.g. ``"card_sent"``, ``"error"``)
    - ``message``     — human-readable detail string (optional)
    - ``trace_id``    — from active ``TraceContext`` (if any)
    - ``span_id``     — from active ``TraceContext`` (if any)
    - ``duration_ms`` — elapsed milliseconds (optional)
    - ``error``       — error information (optional)
    - extra fields    — any keyword arguments passed to the log method
    """

    def __init__(
        self,
        component: str,
        *,
        config: Optional[LoggerConfig] = None,
    ) -> None:
        if not component:
            raise ValueError("component must be a non-empty string")
        self._component = component
        self._config = config or _DEFAULT_CONFIG
        self._stdlib = logging.getLogger(f"agentmesh.{component}")

        # Wire stdlib logger once
        stdlib_level = self._config.level.to_stdlib()
        if not self._stdlib.handlers:
            handler = logging.StreamHandler(self._resolve_stream())
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._stdlib.addHandler(handler)
        self._stdlib.setLevel(stdlib_level)

    # -- Convenience helpers -----------------------------------------------

    @classmethod
    def configure(cls, config: LoggerConfig) -> None:
        """Set the global default logger configuration."""
        global _DEFAULT_CONFIG  # noqa: PLW0603
        _DEFAULT_CONFIG = config

    # -- Public log methods ------------------------------------------------

    def debug(
        self,
        event: str,
        *,
        message: Optional[str] = None,
        duration_ms: Optional[float] = None,
        error: Any = None,
        **extra: Any,
    ) -> None:
        """Emit a ``DEBUG``-level structured log entry."""
        self._log(LogLevel.DEBUG, event, message, duration_ms, error, extra)

    def info(
        self,
        event: str,
        *,
        message: Optional[str] = None,
        duration_ms: Optional[float] = None,
        error: Any = None,
        **extra: Any,
    ) -> None:
        """Emit an ``INFO``-level structured log entry."""
        self._log(LogLevel.INFO, event, message, duration_ms, error, extra)

    def warn(
        self,
        event: str,
        *,
        message: Optional[str] = None,
        duration_ms: Optional[float] = None,
        error: Any = None,
        **extra: Any,
    ) -> None:
        """Emit a ``WARN``-level structured log entry."""
        self._log(LogLevel.WARN, event, message, duration_ms, error, extra)

    def error(
        self,
        event: str,
        *,
        message: Optional[str] = None,
        duration_ms: Optional[float] = None,
        error: Any = None,
        **extra: Any,
    ) -> None:
        """Emit an ``ERROR``-level structured log entry."""
        self._log(LogLevel.ERROR, event, message, duration_ms, error, extra)

    # -- Low-level emit ----------------------------------------------------

    def _log(
        self,
        level: LogLevel,
        event: str,
        message: Optional[str],
        duration_ms: Optional[float],
        error: Any,
        extra: Dict[str, Any],
    ) -> None:
        if not self._stdlib.isEnabledFor(level.to_stdlib()):
            return

        record: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level.value,
            "component": self._component,
            "event": event,
        }

        if message is not None:
            record["message"] = message

        # Attach trace context from current thread if available
        trace_ctx = TraceProvider.get_current_context()
        if trace_ctx is not None:
            record["trace_id"] = trace_ctx.trace_id
            record["span_id"] = trace_ctx.span_id
            if trace_ctx.baggage:
                record["trace_baggage"] = dict(trace_ctx.baggage)

        if duration_ms is not None:
            record["duration_ms"] = round(duration_ms, 3)

        if error is not None:
            if isinstance(error, BaseException):
                record["error"] = {
                    "type": type(error).__name__,
                    "message": str(error),
                }
            elif isinstance(error, dict):
                record["error"] = error
            else:
                record["error"] = str(error)

        # Inject configured default extra fields
        if self._config.extra_fields:
            for k, v in self._config.extra_fields.items():
                if k not in record:
                    record[k] = v

        # Per-call extra fields (overwrite anything above)
        if extra:
            for k, v in extra.items():
                record[k] = v

        json_line = json.dumps(record, default=str, ensure_ascii=False)

        stdlib_level = level.to_stdlib()
        self._stdlib.log(stdlib_level, "%s", json_line)

    # -- Internal helpers --------------------------------------------------

    def _resolve_stream(self) -> Any:
        out = self._config.output
        if out == "stderr":
            return sys.stderr
        if out == "stdout":
            return sys.stdout
        return open(out, "a")  # noqa: SIM115 — owned by logging framework
