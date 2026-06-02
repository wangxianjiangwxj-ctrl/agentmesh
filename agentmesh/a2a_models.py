#!/usr/bin/env python3
"""
AgentMesh A2A Configuration Models.

Defines configuration dataclasses for timeout and retry behavior
used by the A2A server and HTTP provider/client infrastructure.

Usage:
    from agentmesh.a2a_models import ServerTimeoutConfig, RetryConfig

    timeout_cfg = ServerTimeoutConfig(request_timeout=30.0)
    retry_cfg = RetryConfig(max_retries=3)

    task = async_send_with_timeout(facade, task_body, timeout_cfg)
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import ClassVar, List, Optional, Set


# ---------------------------------------------------------------------------
# Server Timeout Configuration
# ---------------------------------------------------------------------------


@dataclass
class ServerTimeoutConfig:
    """Timeout configuration for the A2A HTTP server.

    Controls how long the server waits before interrupting long-running
    request handlers or closing idle SSE streams.

    Attributes:
        request_timeout: Max seconds for a single request handler to execute.
                         Default 30.0. Raise ``asyncio.TimeoutError`` on expiry.
        stream_idle_timeout: Max seconds of inactivity on an SSE stream before
                             the server closes the connection. Default 60.0.
        connect_timeout: Max seconds for establishing a TCP connection
                         (client-side). Default 10.0.
        read_timeout: Max seconds waiting for a response body/next chunk
                      (client-side). Default 30.0.
    """
    request_timeout: float = 30.0
    stream_idle_timeout: float = 60.0
    connect_timeout: float = 10.0
    read_timeout: float = 30.0

    # Sentinel: marker value meaning "no limit"
    NO_TIMEOUT: ClassVar[float] = 0.0

    def __post_init__(self):
        if self.request_timeout < 0:
            raise ValueError(f"request_timeout must be >= 0, got {self.request_timeout}")
        if self.stream_idle_timeout < 0:
            raise ValueError(f"stream_idle_timeout must be >= 0, got {self.stream_idle_timeout}")
        if self.connect_timeout < 0:
            raise ValueError(f"connect_timeout must be >= 0, got {self.connect_timeout}")
        if self.read_timeout < 0:
            raise ValueError(f"read_timeout must be >= 0, got {self.read_timeout}")


# ---------------------------------------------------------------------------
# Retry Configuration
# ---------------------------------------------------------------------------


# HTTP status codes that are considered safe to retry
_DEFAULT_RETRYABLE_STATUSES: Set[int] = {429, 500, 502, 503, 504}


@dataclass
class RetryConfig:
    """Retry configuration for HTTP requests.

    Controls automatic retry with exponential backoff for transient
    failures. By default, only 5xx and 429 status codes are retried;
    4xx errors are never retried.

    Attributes:
        max_retries: Maximum number of retry attempts (default 3).
                     0 means no retry.
        backoff_factor: Base delay in seconds for exponential backoff
                        (delay = backoff_factor * 2 ** attempt). Default 1.0.
        max_backoff: Maximum backoff delay cap in seconds. Default 30.0.
        retryable_statuses: Set of HTTP status codes that trigger retry.
                            Default {429, 500, 502, 503, 504}.
        retry_on_network_error: Whether to retry on network-level errors
                                (connection refused, DNS failure, timeout).
                                Default True.
    """
    max_retries: int = 3
    backoff_factor: float = 1.0
    max_backoff: float = 30.0
    retryable_statuses: Set[int] = field(default_factory=lambda: set(_DEFAULT_RETRYABLE_STATUSES))
    retry_on_network_error: bool = True

    def __post_init__(self):
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {self.max_retries}")
        if self.backoff_factor <= 0:
            raise ValueError(f"backoff_factor must be > 0, got {self.backoff_factor}")
        if self.max_backoff <= 0:
            raise ValueError(f"max_backoff must be > 0, got {self.max_backoff}")

    def backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay for the given attempt (1-indexed)."""
        delay = self.backoff_factor * (2 ** (attempt - 1))
        return min(delay, self.max_backoff)

    def should_retry_on_status(self, status_code: int) -> bool:
        """Check if a given HTTP status code is retryable."""
        return status_code in self.retryable_statuses

    def should_retry_on_error(self, error: Exception) -> bool:
        """Check if a given exception type should trigger a retry.

        Retries on network-level errors (ConnectionError, TimeoutError, OSError)
        when ``retry_on_network_error`` is True.
        """
        if not self.retry_on_network_error:
            return False
        return isinstance(error, (ConnectionError, TimeoutError, OSError))


# Default shared instances for convenience
DEFAULT_TIMEOUT_CONFIG = ServerTimeoutConfig()
DEFAULT_RETRY_CONFIG = RetryConfig()
