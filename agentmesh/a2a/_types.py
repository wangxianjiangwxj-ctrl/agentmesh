"""
AgentMesh A2A Shared Type Definitions.

Type annotation skeletons for the A2A protocol core. These types
provide the shared vocabulary used across a2a_provider.py,
a2a_server.py, and a2a_models.py.

Usage:
    from agentmesh.a2a._types import (
        TaskState, TaskDict, TaskStatusDict, AgentCardDict,
        AuthDict, ErrorDict, A2AProviderProtocol, HttpMethod,
        ResultData, _T,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    ClassVar,
    Dict,
    Generic,
    Iterator,
    List,
    Literal,
    Optional,
    Protocol,
    Set,
    TypedDict,
    TypeVar,
    Union,
    runtime_checkable,
)


# ===================================================================
# Task State Literal
# ===================================================================

TaskState = Literal[
    "pending",
    "submitted",
    "working",
    "input-required",
    "completed",
    "failed",
    "canceled",
]


# ===================================================================
# TypedDicts for A2A wire format
# ===================================================================


class TaskStatusDict(TypedDict, total=False):
    """Status block embedded inside a TaskDict."""
    state: TaskState
    message: str
    timestamp: float


class TaskDict(TypedDict, total=False):
    """A2A task dictionary used across the entire protocol.

    Represents a task at rest or in flight.  All fields except ``id``
    are optional; the exact shape depends on lifecycle stage.
    """
    id: str
    status: TaskStatusDict
    payload: dict
    result: dict
    metadata: dict
    parent_id: str
    children_ids: List[str]


class AgentCardDict(TypedDict, total=False):
    """Agent discovery card -- describes an agent's capabilities."""
    name: str
    skills: List[str]
    endpoints: dict


class AuthDict(TypedDict, total=False):
    """Authentication / authorization payload for A2A requests.

    Carried alongside every task submission and query. Contents are
    provider-specific (API keys, tokens, JWTs, etc.).
    """


class ErrorDict(TypedDict, total=False):
    """Structured error block returned by A2A endpoints."""
    code: Union[int, str]
    message: str
    recoverable: bool


# ===================================================================
# Generic result type variable
# ===================================================================

ResultData = TypeVar("ResultData")
"""Type variable for the ``data`` field in A2AResult / A2AResponse."""


# ===================================================================
# Provider Protocol
# ===================================================================


@runtime_checkable
class A2AProviderProtocol(Protocol):
    """Structural typing protocol for A2A providers.

    Any object conforming to this interface can be used as an A2A
    provider, even if it doesn't inherit from ``A2AProvider``.
    Useful for duck-typed testing, wrapping third-party clients, etc.
    """

    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> Set[str]: ...

    def send_message(
        self, task: dict, auth: dict | None = None
    ) -> Any: ...

    def get_task(
        self, task_id: str, auth: dict | None = None
    ) -> Any: ...

    def cancel_task(
        self, task_id: str, auth: dict | None = None
    ) -> Any: ...

    def ping(self) -> Any: ...


# ===================================================================
# HTTP Method Literal
# ===================================================================

HttpMethod = Literal["GET", "POST", "PUT", "DELETE"]


# ===================================================================
# Internal utility TypeVar
# ===================================================================

_T = TypeVar("_T")
"""Internal utility TypeVar for generic helper functions / decorators."""
