#!/usr/bin/env python3
"""
AgentMesh SDK v0.3 — A2A Provider抽象层

Provider是A2A运行时的抽象基类，定义了与A2A Server通信的标准接口。
MemoryProvider提供本地内存模拟，HttpProvider连接真实A2A Server。

使用方式:
  from a2a_provider import A2AProvider, MemoryProvider, HttpProvider, A2AResult
"""

## ============================================================
## A2A Result & Error
## ============================================================


class A2AResult:
    """A2A操作结果封装"""

    def __init__(self, success: bool, data=None, error=None, task_state=None):
        self.success = success
        self.data = data
        self.error = error
        self.task_state = task_state

    @classmethod
    def ok(cls, data, task_state=None):
        return cls(True, data=data, task_state=task_state)

    @classmethod
    def fail(cls, error, task_state=None):
        return cls(False, error=error, task_state=task_state)

    def __bool__(self):
        return self.success


class A2AError(Exception):
    """A2A协议错误"""

    def __init__(self, code: int, message: str, recoverable: bool = False):
        self.code = code
        self.message = message
        self.recoverable = recoverable
        super().__init__(f"[{code}] {message}")


class ProviderError(A2AError):
    """Provider-level error (e.g. network, config, upstream failure).

    Raised by provider implementations when an external dependency fails.
    Maps to HTTP 500 by default, or a provider-specific status code.
    """
    def __init__(self, code: int = 500, message: str = "Provider error",
                 recoverable: bool = True):
        super().__init__(code, message, recoverable)


# ============================================================
# A2A Task State Machine
# ============================================================


class A2ATaskState:
    """A2A Task状态"""

    PENDING = "pending"
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"

    _VALID_TRANSITIONS = {
        PENDING: [SUBMITTED, FAILED, CANCELED],
        SUBMITTED: [WORKING, FAILED, CANCELED],
        WORKING: [INPUT_REQUIRED, COMPLETED, FAILED, CANCELED],
        INPUT_REQUIRED: [WORKING, CANCELED],
        COMPLETED: [],
        FAILED: [],
        CANCELED: [],
    }

    @classmethod
    def can_transition(cls, current: str, target: str) -> bool:
        if current not in cls._VALID_TRANSITIONS:
            return False
        return target in cls._VALID_TRANSITIONS[current]


class A2ATaskManager:
    """A2A Task状态机管理器"""

    def __init__(self):
        self._tasks = {}

    def track(
        self,
        task_id: str,
        initial_state: str = A2ATaskState.PENDING,
        parent_id: str = None,
        metadata: dict = None,
    ):
        if task_id in self._tasks:
            raise A2AError(409, f"Task already tracked: {task_id}")
        self._tasks[task_id] = {
            "task_id": task_id,
            "state": initial_state,
            "parent_id": parent_id,
            "children_ids": [],
            "metadata": metadata or {},
            "updated_at": None,
        }
        if parent_id and parent_id in self._tasks:
            self._tasks[parent_id]["children_ids"].append(task_id)
        return self._tasks[task_id]

    def update_state(self, task_id: str, new_state: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        old = task["state"]
        if old == new_state:
            return True  # no-op
        if not A2ATaskState.can_transition(old, new_state):
            raise A2AError(400, f"Invalid state transition: {old} -> {new_state}")
        task["state"] = new_state
        task["updated_at"] = __import__("datetime").datetime.utcnow().isoformat()
        return True

    def get_task(self, task_id: str):
        return self._tasks.get(task_id)

    def get_children(self, task_id: str):
        task = self._tasks.get(task_id)
        if not task:
            return []
        return [self._tasks[cid] for cid in task["children_ids"] if cid in self._tasks]

    def cleanup(self, max_age_seconds: float = 3600):
        now = __import__("datetime").datetime.utcnow()
        to_remove = []
        for tid, t in self._tasks.items():
            if t["state"] in (A2ATaskState.COMPLETED, A2ATaskState.FAILED, A2ATaskState.CANCELED):
                updated = t.get("updated_at")
                if updated:
                    age = (now - __import__("datetime").datetime.fromisoformat(updated)).total_seconds()
                    if age > max_age_seconds:
                        to_remove.append(tid)
        for tid in to_remove:
            del self._tasks[tid]


# ============================================================
# A2AProvider — 抽象基类
# ============================================================


class A2AProvider:
    """
    A2A Provider抽象基类

    子类必须实现: send_message, get_task, cancel_task
    可选实现: send_streaming, fetch_agent_card, ping
    """

    def __init__(self, name: str):
        self._name = name
        self._capabilities = set()

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> set:
        return self._capabilities

    def send_message(self, task: dict, auth: dict = None) -> A2AResult:
        raise NotImplementedError

    def get_task(self, task_id: str, auth: dict = None) -> A2AResult:
        raise NotImplementedError

    def cancel_task(self, task_id: str, auth: dict = None) -> A2AResult:
        raise NotImplementedError

    def ping(self) -> A2AResult:
        return A2AResult.ok({"status": "ok", "provider": self._name})


# ============================================================
# MemoryProvider — 本地内存模拟
# ============================================================


class MemoryProvider(A2AProvider):
    """
    内存Provider：不经过网络，直接内存模拟A2A Server

    用于：单进程测试、单元测试、离线开发
    不需要启动外部A2A Server
    """

    def __init__(self, name: str = "memory"):
        super().__init__(name)
        self._tasks = {}
        self._agent_cards = {}
        self._capabilities = {"local", "no-network"}

    def register_agent_card(self, card: dict):
        self._agent_cards[card.get("name", "")] = card

    def get_agent_card(self, name: str) -> dict:
        return self._agent_cards.get(name)

    def send_message(self, task: dict, auth=None) -> A2AResult:
        task_id = task.get("id", "")
        if not task_id:
            return A2AResult.fail(A2AError(400, "Missing task id"))
        self._tasks[task_id] = task
        return A2AResult.ok(task, task_state="submitted")

    def get_task(self, task_id: str, auth=None) -> A2AResult:
        task = self._tasks.get(task_id)
        if not task:
            return A2AResult.fail(A2AError(404, f"Task not found: {task_id}"))
        return A2AResult.ok(task, task_state=task.get("status", {}).get("state", "unknown"))

    def cancel_task(self, task_id: str, auth=None) -> A2AResult:
        task = self._tasks.get(task_id)
        if not task:
            return A2AResult.fail(A2AError(404, f"Task not found: {task_id}"))
        if "status" not in task:
            task["status"] = {}
        task["status"]["state"] = "canceled"
        return A2AResult.ok(task, task_state="canceled")


# ============================================================
# A2AFacade — 统一入口
# ============================================================


class A2AFacade:
    """
    A2A兼容层统一入口

    封装 Provider + TaskManager，对外暴露简洁接口。
    自动完成：AgentMesh→A2A转换 → Provider.send → 响应 → A2A→AgentMesh转换
    """

    def __init__(self, provider: A2AProvider = None, task_manager: A2ATaskManager = None):
        self.provider = provider or MemoryProvider()
        self.task_manager = task_manager or A2ATaskManager()

    def set_provider(self, provider: A2AProvider):
        self.provider = provider

    def send_task(self, task: dict) -> A2AResult:
        """发送Task到Provider并跟踪状态"""
        task_id = task.get("id", "")
        if task_id:
            existing = self.task_manager.get_task(task_id)
            if not existing:
                self.task_manager.track(task_id, A2ATaskState.SUBMITTED)
            state = task.get("status", {}).get("state", A2ATaskState.SUBMITTED)
            self.task_manager.update_state(task_id, state)
        result = self.provider.send_message(task)
        return result

    def get_task(self, task_id: str) -> A2AResult:
        return self.provider.get_task(task_id)

    def cancel_task(self, task_id: str) -> A2AResult:
        result = self.provider.cancel_task(task_id)
        if result.success:
            self.task_manager.update_state(task_id, A2ATaskState.CANCELED)
        return result


# ============================================================
# Retry utilities for HTTP requests
# ============================================================

import functools as _functools
import random as _random_module
import time as _time_module


def _should_retry_on_status(status_code: int) -> bool:
    """Return True if the HTTP status code is retryable.

    Retryable: 429 (rate limit), 5xx (server errors).
    Non-retryable: 4xx (client errors, except 429).
    """
    if status_code == 429:
        return True
    return 500 <= status_code < 600


def _should_retry_on_error(error: BaseException) -> bool:
    """Return True if the exception type is a network-level error.

    Retryable: ConnectionError, TimeoutError, OSError (DNS, socket).
    """
    return isinstance(error, (ConnectionError, TimeoutError, OSError))


def _backoff_sleep(attempt: int, backoff_factor: float = 1.0,
                   max_backoff: float = 30.0) -> None:
    """Sleep with exponential backoff and jitter.

    delay = min(backoff_factor * 2^(attempt-1), max_backoff)
    Adds uniform jitter of 0-25%.

    Args:
        attempt: 1-indexed retry attempt number.
        backoff_factor: Base multiplier for delay.
        max_backoff: Maximum delay cap in seconds.
    """
    delay = backoff_factor * (2 ** (attempt - 1))
    delay = min(delay, max_backoff)
    jitter = delay * _random_module.uniform(0, 0.25)
    _time_module.sleep(delay + jitter)


def with_retry(
    fn=None,
    *,
    max_retries: int = 3,
    backoff_factor: float = 1.0,
    max_backoff: float = 30.0,
    retryable_statuses=None,
    retry_on_network_error: bool = True,
):
    """Decorator that wraps a function with automatic retry logic.

    Can be used with or without arguments::

        @with_retry
        def my_call(url):
            ...

        @with_retry(max_retries=5, backoff_factor=2.0)
        def flaky_call(url):
            ...

    The wrapped function must return a dict with a ``success`` key.
    Retries on: 5xx/429 status codes, network-level exceptions.
    """
    if retryable_statuses is None:
        retryable_statuses = {429, 500, 502, 503, 504}

    def decorator(func):
        @_functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            last_result = None

            for attempt in range(1 + max_retries):
                try:
                    result = func(*args, **kwargs)
                except BaseException as exc:
                    last_error = exc
                    if (attempt < max_retries
                            and retry_on_network_error
                            and _should_retry_on_error(exc)):
                        _backoff_sleep(attempt + 1, backoff_factor, max_backoff)
                        continue
                    raise

                if result.get("success", True):
                    return result

                last_result = result
                error_info = result.get("error", {}) or {}
                if isinstance(error_info, dict):
                    status_code = error_info.get("code", 0)
                    if isinstance(status_code, str):
                        status_code = 500
                elif hasattr(error_info, "code"):
                    status_code = error_info.code
                else:
                    status_code = 500

                if attempt < max_retries and _should_retry_on_status(status_code):
                    recoverable = False
                    if isinstance(error_info, dict):
                        recoverable = error_info.get("recoverable", False)
                    elif hasattr(error_info, "recoverable"):
                        recoverable = error_info.recoverable

                    if recoverable or status_code >= 500:
                        _backoff_sleep(attempt + 1, backoff_factor, max_backoff)
                        continue

                return result

            if last_result is not None:
                return last_result
            if last_error is not None:
                raise last_error
            return {"success": False,
                    "error": {"code": 503, "message": "Retry exhausted"}}

        return wrapper

    # Allow usage as @with_retry (no parentheses) or @with_retry(...)
    if fn is not None:
        return decorator(fn)
    return decorator


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("A2A Provider 模块 — 单元测试")
    print("=" * 60)
    print()

    # 1. MemoryProvider
    print("[1] MemoryProvider...")
    mem = MemoryProvider("test-mem")
    mem.register_agent_card({"name": "test-agent", "skills": ["test"]})
    assert mem.get_agent_card("test-agent")["skills"] == ["test"]
    print("  ✅ AgentCard 注册/查询")
    print()

    # 2. Send/Get/Cancel Task
    print("[2] MemoryProvider Task生命周期...")
    task = {"id": "task_001", "status": {"state": "submitted"}, "payload": {}}
    r = mem.send_message(task)
    assert r.success and r.task_state == "submitted"

    r = mem.get_task("task_001")
    assert r.success and r.data["id"] == "task_001"

    r = mem.cancel_task("task_001")
    assert r.success and r.task_state == "canceled"
    print("  ✅ Send → Get → Cancel 完整生命周期")
    print()

    # 3. TaskManager 状态机
    print("[3] A2ATaskManager 状态机...")
    mgr = A2ATaskManager()
    mgr.track("task_001", A2ATaskState.PENDING)
    mgr.update_state("task_001", A2ATaskState.SUBMITTED)
    mgr.update_state("task_001", A2ATaskState.WORKING)
    mgr.update_state("task_001", A2ATaskState.COMPLETED)
    assert mgr.get_task("task_001")["state"] == A2ATaskState.COMPLETED

    # 非法转换
    try:
        mgr.update_state("task_001", A2ATaskState.WORKING)
        assert False, "不应允许从COMPLETED回到WORKING"
    except A2AError:
        pass
    print("  ✅ 合法转换通过，非法转换拦截")
    print()

    # 4. Parent/Children
    print("[4] Task上下游...")
    mgr.track("parent_001", A2ATaskState.SUBMITTED)
    mgr.track("child_001", A2ATaskState.PENDING, parent_id="parent_001")
    mgr.track("child_002", A2ATaskState.PENDING, parent_id="parent_001")
    children = mgr.get_children("parent_001")
    assert len(children) == 2
    print("  ✅ 上下游追踪正确")
    print()

    # 5. A2AFacade
    print("[5] A2AFacade 统一入口...")
    facade = A2AFacade(MemoryProvider(), A2ATaskManager())
    task = {"id": "facade_001", "status": {"state": "submitted"}}
    r = facade.send_task(task)
    assert r.success

    r = facade.get_task("facade_001")
    assert r.success

    r = facade.cancel_task("facade_001")
    assert r.success
    print("  ✅ Facade统一入口正常工作")
    print()

    # 6. 错误处理
    print("[6] 错误处理...")
    r = mem.get_task("nonexistent")
    assert not r.success
    assert isinstance(r.error, A2AError)
    assert r.error.code == 404
    print("  ✅ 404错误正确处理")
    print()

    print("=" * 60)
    print("All 6 tests passed ✅ — Provider模块就绪")
    print("=" * 60)
