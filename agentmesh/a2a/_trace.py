"""
AgentMesh A2A Trace ID Propagation.

Provides TraceContext, TraceProvider, and with_trace_context()
for OpenTelemetry-compatible distributed tracing across agents.

Trace ID format (OTel compatible):
  - trace_id: 16-byte, 32-hex-char string
  - span_id:  8-byte, 16-hex-char string
"""

from __future__ import annotations

import contextlib
import os
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, Optional

# ---------------------------------------------------------------------------
# Global thread-local state
# ---------------------------------------------------------------------------

_tls = threading.local()


def _get_current_context() -> Optional["TraceContext"]:
    """Retrieve the active TraceContext for the current thread, or None."""
    return getattr(_tls, "trace_context", None)


# ---------------------------------------------------------------------------
# TraceContext
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TraceContext:
    """Immutable context holding distributed-tracing identifiers.

    Attributes:
        trace_id:       Globally unique 32-hex-char trace identifier.
        parent_span_id: Span ID of the caller, or "" for root spans.
        span_id:        Current span identifier (16 hex chars).
        baggage:        Optional key-value map propagated alongside the trace.
    """

    trace_id: str
    parent_span_id: str
    span_id: str
    baggage: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_hex(self.trace_id, 32, "trace_id")
        _validate_hex(self.parent_span_id, 16, "parent_span_id", allow_empty=True)
        _validate_hex(self.span_id, 16, "span_id")

    def to_header(self) -> Dict[str, str]:
        """Serialise the trace context to a flat header dict for wire propagation."""
        return {
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "span_id": self.span_id,
            "baggage": _encode_baggage(self.baggage),
        }

    @classmethod
    def from_header(cls, headers: Dict[str, str]) -> Optional["TraceContext"]:
        """Parse a TraceContext from a header dict (e.g. JSON message headers).

        Returns None when required fields are missing or malformed.
        """
        trace_id = headers.get("trace_id", "")
        span_id = headers.get("span_id", "")
        parent_span_id = headers.get("parent_span_id", "")
        baggage_raw = headers.get("baggage", "")

        if not trace_id or not span_id:
            return None

        baggage = _decode_baggage(baggage_raw)

        try:
            return cls(
                trace_id=trace_id,
                parent_span_id=parent_span_id,
                span_id=span_id,
                baggage=baggage,
            )
        except (ValueError, AttributeError):
            return None

    def new_child(self) -> "TraceContext":
        """Create a child span context linked to this context as parent."""
        return TraceContext(
            trace_id=self.trace_id,
            parent_span_id=self.span_id,
            span_id=_new_span_id(),
            baggage=dict(self.baggage),
        )

    def with_baggage(self, key: str, value: str) -> "TraceContext":
        """Return a new context with an additional baggage entry."""
        new_baggage = dict(self.baggage)
        new_baggage[key] = value
        return TraceContext(
            trace_id=self.trace_id,
            parent_span_id=self.parent_span_id,
            span_id=self.span_id,
            baggage=new_baggage,
        )


# ---------------------------------------------------------------------------
# TraceProvider
# ---------------------------------------------------------------------------


class TraceProvider:
    """Factory and registry for distributed-trace contexts.

    The provider generates new root contexts and can create child spans
    from an existing context.  It also manages a thread-local stack so
    that ``with_trace_context()`` works correctly.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # -- Generation --------------------------------------------------------

    @staticmethod
    def new_trace_id() -> str:
        """Generate a new 32-hex-char trace ID (16 random bytes)."""
        return uuid.uuid4().hex  # 32 hex chars

    @staticmethod
    def new_span_id() -> str:
        """Generate a new 16-hex-char span ID (8 random bytes)."""
        return _new_span_id()

    def new_context(
        self,
        baggage: Optional[Dict[str, str]] = None,
    ) -> TraceContext:
        """Create a brand-new root TraceContext with a fresh trace ID."""
        return TraceContext(
            trace_id=self.new_trace_id(),
            parent_span_id="",
            span_id=self.new_span_id(),
            baggage=baggage or {},
        )

    def child_context(
        self,
        parent: TraceContext,
        baggage: Optional[Dict[str, str]] = None,
    ) -> TraceContext:
        """Create a child span context while preserving the parent trace ID."""
        child = parent.new_child()
        if baggage:
            for k, v in baggage.items():
                child = child.with_baggage(k, v)
        return child

    # -- Injection / extraction --------------------------------------------

    def inject(
        self,
        context: TraceContext,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Inject trace context into a headers dict (mutates and returns it)."""
        if headers is None:
            headers = {}
        headers.update(context.to_header())
        return headers

    @staticmethod
    def extract(
        headers: Dict[str, str],
    ) -> Optional[TraceContext]:
        """Extract trace context from message headers, if present."""
        return TraceContext.from_header(headers)

    # -- Context stack helpers ---------------------------------------------

    @staticmethod
    def get_current_context() -> Optional[TraceContext]:
        """Return the active TraceContext for the current thread."""
        return _get_current_context()


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def with_trace_context(
    context: Optional[TraceContext] = None,
    *,
    provider: Optional[TraceProvider] = None,
) -> Generator[TraceContext, None, None]:
    """Context manager that sets the active TraceContext for the duration.

    If *context* is ``None`` a new root context is created via *provider*
    (or a default provider).  Inside the block the context is available
    via ``TraceProvider.get_current_context()``.

    Example::

        with with_trace_context() as ctx:
            # ctx is the active trace context for this thread
            do_work(ctx)
    """
    if context is None:
        p = provider or TraceProvider()
        context = p.new_context()

    prev = _get_current_context()
    _tls.trace_context = context
    try:
        yield context
    finally:
        _tls.trace_context = prev


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _new_span_id() -> str:
    """8 random bytes -> 16 hex chars."""
    return os.urandom(8).hex()


def _validate_hex(
    value: str,
    expected_len: int,
    field_name: str,
    allow_empty: bool = False,
) -> None:
    if allow_empty and not value:
        return
    if len(value) != expected_len:
        raise ValueError(
            f"{field_name} must be {expected_len} hex chars, got {len(value)!r}"
        )
    try:
        int(value, 16)
    except ValueError:
        raise ValueError(f"{field_name} is not valid hex: {value!r}")


_BAGGAGE_SEPARATOR = ","


def _encode_baggage(baggage: Dict[str, str]) -> str:
    """Encode baggage dict as ``key=val,key=val`` (no escaping for simplicity)."""
    if not baggage:
        return ""
    return _BAGGAGE_SEPARATOR.join(f"{k}={v}" for k, v in baggage.items())


def _decode_baggage(raw: str) -> Dict[str, str]:
    """Decode a baggage header string back into a dict."""
    if not raw:
        return {}
    result: Dict[str, str] = {}
    for part in raw.split(_BAGGAGE_SEPARATOR):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            result[k.strip()] = v.strip()
    return result
