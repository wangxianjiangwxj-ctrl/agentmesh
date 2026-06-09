"""
AgentMesh Platform — Structured Logging & File Rotation

Provides a ready-to-use logging configuration that outputs JSON-formatted
structured logs to both stderr (for container/console consumption) and
rotating log files (for long-term retention).

Usage:
    from agentmesh.platform.logging_config import setup_logging
    logger = setup_logging("agentmesh", level="info")
    logger.info("Server started", extra={"host": "0.0.0.0", "port": 8000})

Environment variables read:
    AGENTMESH_LOG_LEVEL — log level (debug/info/warning/error/critical)
    AGENTMESH_LOG_DIR   — directory for rotating log files
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Custom JSON Formatter ──────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    """Format log records as newline-delimited JSON objects.

    Produces structured output suitable for log aggregators (Loki,
    ELK, Datadog, etc.) without parsing brittle text patterns.
    """

    def format(self, record: logging.LogRecord) -> str:
        extra = {
            k: v
            for k, v in record.__dict__.items()
            if k not in ("name", "msg", "args", "levelname",
                         "levelno", "pathname", "filename", "module",
                         "funcName", "lineno", "exc_info", "exc_text",
                         "stack_info", "created", "msecs", "relativeCreated",
                         "process", "thread", "threadName", "message")
        }
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
            "extra": extra if extra else None,
        }
        if record.exc_info and record.exc_info[0]:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


# ── Logger setup ───────────────────────────────────────────────────────

_loggers: dict[str, logging.Logger] = {}
_default_log_dir = "/var/lib/agentmesh/logs"


def setup_logging(
    name: str = "agentmesh",
    level: Optional[str] = None,
    log_dir: Optional[str] = None,
) -> logging.Logger:
    """Configure and return a structured logger.

    Parameters
    ----------
    name : str
        Logger name. Use dot-separated hierarchy, e.g. "agentmesh.gateway".
    level : str, optional
        Log level. Reads AGENTMESH_LOG_LEVEL env var if not provided.
        Defaults to "info".
    log_dir : str, optional
        Directory for rotating log files. Reads AGENTMESH_LOG_DIR env
        var if not provided. Falls back to /var/lib/agentmesh/logs.

    Returns
    -------
    logging.Logger
        Configured logger instance.
    """
    global _loggers

    if name in _loggers:
        return _loggers[name]

    # ── Resolve level ──────────────────────────────────────────────
    level_str = (level or os.environ.get("AGENTMESH_LOG_LEVEL") or "info").strip().lower()
    log_level = getattr(logging, level_str.upper(), logging.INFO)

    # ── Resolve log dir ────────────────────────────────────────────
    log_dir_path = Path(log_dir or os.environ.get("AGENTMESH_LOG_DIR") or _default_log_dir)

    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    logger.handlers.clear()
    logger.propagate = False

    # ── Handler 1: Console (stderr) — JSON format ──────────────────
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(JSONFormatter())
    logger.addHandler(console_handler)

    # ── Handler 2: File rotation — JSON format ─────────────────────
    try:
        log_dir_path.mkdir(parents=True, exist_ok=True)
        log_file = log_dir_path / f"{name}.log"
        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_file),
            maxBytes=10 * 1024 * 1024,   # 10 MB per file
            backupCount=5,                # keep 5 rotated files
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(JSONFormatter())
        logger.addHandler(file_handler)
    except (OSError, PermissionError) as exc:
        logger.warning("Cannot create rotating file handler at %s: %s", log_dir_path, exc)

    _loggers[name] = logger
    return logger


def get_logger(name: str = "agentmesh") -> logging.Logger:
    """Retrieve an already-configured logger, or create one with defaults.

    Safe to call from any module — will not re-configure if the logger
    was already set up via setup_logging().
    """
    if name in _loggers:
        return _loggers[name]
    return setup_logging(name)


# ── Convenience: integration hook for uvicorn / FastAPI ────────────────

def get_uvicorn_log_config() -> dict:
    """Return a logging config dict compatible with uvicorn.run(log_config=...).

    Overrides uvicorn's default access/error loggers with JSON format.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": JSONFormatter,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "stream": "ext://sys.stderr",
            },
        },
        "root": {
            "level": (os.environ.get("AGENTMESH_LOG_LEVEL") or "info").upper(),
            "handlers": ["console"],
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }
