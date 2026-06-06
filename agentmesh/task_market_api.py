"""Task Market CRUD API — Phase 19 MVP, Module 2

角色：    尚书令
预期完成：Day 2-3 (2026-06-05~06)
依赖：    DB schema 骨架（中书令 Day 1）
状态：    ⚡ 骨架完成，等待 DB schema 后接入

API 一览（签名版）：
  POST /tasks              — 发布（需签名）
  GET  /tasks              — 浏览列表
  GET  /tasks/{id}         — 详情
  POST /tasks/{id}/assign  — 接单（需签名）
  POST /tasks/{id}/deliver — 交付（需签名）
  POST /tasks/{id}/verify  — 验收（需签名）
  POST /tasks/{id}/settle  — 结算（需签名）
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Protocol


# ─── 状态模型 ─────────────────────────────────────────────

class TaskStatus(str, Enum):
    """Task lifecycle states with valid transition rules."""
    DRAFT     = "draft"
    OPEN      = "open"        # 已发布，可接单
    ASSIGNED  = "assigned"    # 已接单，进行中
    DELIVERED = "delivered"   # 已交付，待验收
    VERIFIED  = "verified"    # 已验收
    REJECTED  = "rejected"    # 被驳回
    CANCELLED = "cancelled"   # 已取消
    SETTLED   = "settled"     # 已结算（终态）

    @classmethod
    def valid_transitions(cls, current: TaskStatus) -> set[TaskStatus]:
        """状态机：只允许合法转移"""
        transitions = {
            cls.DRAFT:     {cls.OPEN, cls.CANCELLED},
            cls.OPEN:      {cls.ASSIGNED, cls.CANCELLED},
            cls.ASSIGNED:  {cls.DELIVERED, cls.CANCELLED},
            cls.DELIVERED: {cls.VERIFIED, cls.REJECTED},
            cls.VERIFIED:  {cls.SETTLED},
            cls.REJECTED:  {cls.ASSIGNED, cls.CANCELLED},
            cls.CANCELLED: set(),
            cls.SETTLED:   set(),
        }
        return transitions.get(current, set())

    def can_transition_to(self, target: TaskStatus) -> bool:
        """Check whether a state transition is allowed.

        Args:
            target: The target status to transition to.

        Returns:
            True if the transition is valid, False otherwise.
        """
        return target in self.valid_transitions(current=self)


@dataclass
class Task:
    """任务聚合根"""
    id: str                      # UUID
    publisher_id: str            # 发布者 Agent ID
    title: str
    description: str
    escrow_amount: int           # 托管积分
    publisher_share: float       # 发布者分成比例 (0-1)
    executor_share: float        # 执行者分成比例 (0-1)
    status: TaskStatus = TaskStatus.DRAFT
    executor_id: Optional[str] = None
    delivery_url: Optional[str] = None
    delivery_hash: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def validate_shares(self) -> None:
        """分成比例必须合法且和为1"""
        if not (0 <= self.publisher_share <= 1):
            raise ValueError("publisher_share must be 0-1")
        if not (0 <= self.executor_share <= 1):
            raise ValueError("executor_share must be 0-1")
        total = round(self.publisher_share + self.executor_share, 4)
        if total != 1.0:
            raise ValueError(f"shares must sum to 1.0, got {total}")

    def transition_to(self, target: TaskStatus) -> None:
        """Transition the task to a new status, validating the move.

        Args:
            target: The target TaskStatus to transition to.

        Raises:
            ValueError: If the transition is not allowed by the state machine.
        """
        if not self.status.can_transition_to(target):
            raise ValueError(
                f"invalid transition: {self.status.value} → {target.value}"
            )
        self.status = target
        self.updated_at = time.time()


# ─── 仓库抽象（待中书令 DB schema 后实现） ─────────────

class TaskRepository(Protocol):
    """Task 仓库接口 — 等待 DB schema 后实现 SQLite 版本"""
    async def save(self, task: Task) -> None:
        """Persist a task to the repository.

        Args:
            task: The Task instance to save.
        """
        ...
    async def get(self, task_id: str) -> Optional[Task]:
        """Retrieve a task by its ID.

        Args:
            task_id: The task identifier.

        Returns:
            The Task instance, or None if not found.
        """
        ...
    async def list(self, status: Optional[TaskStatus] = None,
                   publisher_id: Optional[str] = None) -> list[Task]:
        """List tasks filtered by status and/or publisher.

        Args:
            status: Optional status filter.
            publisher_id: Optional publisher filter.

        Returns:
            List of matching Task instances.
        """
        ...
    async def delete(self, task_id: str) -> None:
        """Delete a task by its ID.

        Args:
            task_id: The task identifier to delete.
        """
        ...


class InMemoryTaskRepository:
    """内存实现 — 用于开发阶段 & 测试"""

    def __init__(self):
        """Initialize an empty in-memory task store."""
        self._store: dict[str, Task] = {}

    async def save(self, task: Task) -> None:
        """Persist a task to the in-memory store.

        Args:
            task: The Task instance to save.
        """
        self._store[task.id] = task

    async def get(self, task_id: str) -> Optional[Task]:
        """Retrieve a task from the in-memory store.

        Args:
            task_id: The task identifier.

        Returns:
            The Task instance, or None if not found.
        """
        return self._store.get(task_id)

    async def list(self, status: Optional[TaskStatus] = None,
                   publisher_id: Optional[str] = None) -> list[Task]:
        """List tasks filtered by status and/or publisher.

        Args:
            status: Optional status filter.
            publisher_id: Optional publisher filter.

        Returns:
            List of matching Task instances, sorted by created_at descending.
        """
        results = list(self._store.values())
        if status:
            results = [t for t in results if t.status == status]
        if publisher_id:
            results = [t for t in results if t.publisher_id == publisher_id]
        results.sort(key=lambda t: t.created_at, reverse=True)
        return results

    async def delete(self, task_id: str) -> None:
        """Delete a task from the in-memory store.

        Args:
            task_id: The task identifier to delete.
        """
        self._store.pop(task_id, None)


# ─── 签名验证抽象（等待签名中间件） ──────────────────

class SignatureVerifier(Protocol):
    """Signature verification protocol for Ed25519-based agent identity."""
    async def verify(self, agent_id: str, payload: str, signature_hex: str) -> bool:
        """验证 agent_id 对应的公钥对 payload 的 Ed25519 签名"""


class MockSignatureVerifier:
    """开发用：总返回 True"""
    async def verify(self, agent_id: str, payload: str, signature_hex: str) -> bool:
        """Always returns True for development purposes.

        Args:
            agent_id: The agent identifier.
            payload: The signed payload string.
            signature_hex: The signature in hex format.

        Returns:
            Always True.
        """
        return True  # TODO: 接入 Ed25519


# ─── 证据链钩子（等待 Module 3） ─────────────────────

async def emit_evidence(task_id: str, actor_id: str, action: str,
                        payload_hash: str, signature: str) -> None:
    """占位：写入审计链（待中书令 EvidenceChain 实现后接入）"""
    pass  # TODO: EvidenceChain.append()


# ─── 核心 API 服务 ────────────────────────────────────────

@dataclass
class CreateTaskRequest:
    """Request payload for creating a new task."""
    title: str
    description: str
    escrow_amount: int
    publisher_share: float
    executor_share: float

@dataclass
class TaskMarketService:
    """任务市场核心服务 — 包含所有领域逻辑"""
    repo: TaskRepository
    sig_verifier: SignatureVerifier

    async def create_task(self, req: CreateTaskRequest,
                          publisher_id: str, signature: str) -> Task:
        """Create a new task in the marketplace.

        Validates the publisher's signature, creates the task with
        OPEN status, checks share proportions, persists it, and
        emits an evidence-chain event.

        Args:
            req: The task creation request details.
            publisher_id: The agent ID of the publisher.
            signature: Ed25519 signature for authentication.

        Returns:
            The newly created Task instance.

        Raises:
            PermissionError: If signature verification fails.
            ValueError: If shares do not sum to 1.0.
        """
        # 1. 验证签名（发布者身份）
        payload = json.dumps(asdict(req), sort_keys=True)
        ok = await self.sig_verifier.verify(publisher_id, payload, signature)
        if not ok:
            raise PermissionError("signature verification failed")

        # 2. 创建任务
        import uuid
        task = Task(
            id=str(uuid.uuid4()),
            publisher_id=publisher_id,
            title=req.title,
            description=req.description,
            escrow_amount=req.escrow_amount,
            publisher_share=req.publisher_share,
            executor_share=req.executor_share,
            status=TaskStatus.OPEN,
        )
        task.validate_shares()

        # 3. 持久化
        await self.repo.save(task)

        # 4. 证据链
        payload_hash = hashlib.sha256(payload.encode()).hexdigest()
        await emit_evidence(task.id, publisher_id, "task.created",
                          payload_hash, signature)

        return task

    async def list_tasks(self, status: Optional[TaskStatus] = None,
                         publisher_id: Optional[str] = None) -> list[Task]:
        """List tasks with optional filters.

        Args:
            status: Optional status filter.
            publisher_id: Optional publisher filter.

        Returns:
            List of matching Task instances.
        """
        return await self.repo.list(status=status, publisher_id=publisher_id)

    async def get_task(self, task_id: str) -> Optional[Task]:
        """Retrieve a task by its ID.

        Args:
            task_id: The task identifier.

        Returns:
            The Task instance, or None if not found.
        """
        return await self.repo.get(task_id)

    async def assign_task(self, task_id: str, executor_id: str,
                          signature: str) -> Task:
        """Assign an executor to an open task.

        Validates the executor's signature and transitions the task
        to ASSIGNED status.

        Args:
            task_id: The task to assign.
            executor_id: The agent ID of the executor.
            signature: Ed25519 signature for authentication.

        Returns:
            The updated Task instance.

        Raises:
            ValueError: If the task is not found.
            PermissionError: If signature verification fails.
        """
        task = await self.repo.get(task_id)
        if task is None:
            raise ValueError("task not found")

        # 验证签名
        payload = json.dumps({"task_id": task_id}, sort_keys=True)
        ok = await self.sig_verifier.verify(executor_id, payload, signature)
        if not ok:
            raise PermissionError("signature verification failed")

        # 状态转移
        task.transition_to(TaskStatus.ASSIGNED)
        task.executor_id = executor_id
        await self.repo.save(task)

        payload_hash = hashlib.sha256(json.dumps(
            {"task_id": task_id, "executor_id": executor_id},
            sort_keys=True).encode()).hexdigest()
        await emit_evidence(task.id, executor_id, "task.assigned",
                          payload_hash, signature)

        return task

    async def deliver_task(self, task_id: str, delivery_url: str,
                           executor_id: str, signature: str) -> Task:
        """Deliver a completed task.

        Validates the executor's signature and transitions the task
        to DELIVERED status.

        Args:
            task_id: The task to mark as delivered.
            delivery_url: URL pointing to the delivered output.
            executor_id: The agent ID of the executor.
            signature: Ed25519 signature for authentication.

        Returns:
            The updated Task instance.

        Raises:
            ValueError: If the task is not found.
            PermissionError: If the caller is not the executor or
                signature verification fails.
        """
        task = await self.repo.get(task_id)
        if task is None:
            raise ValueError("task not found")
        if task.executor_id != executor_id:
            raise PermissionError("only assigned executor can deliver")

        payload = json.dumps({
            "task_id": task_id, "delivery_url": delivery_url
        }, sort_keys=True)
        ok = await self.sig_verifier.verify(executor_id, payload, signature)
        if not ok:
            raise PermissionError("signature verification failed")

        task.delivery_url = delivery_url
        task.delivery_hash = hashlib.sha256(delivery_url.encode()).hexdigest()
        task.transition_to(TaskStatus.DELIVERED)
        await self.repo.save(task)

        payload_hash = hashlib.sha256(json.dumps(
            {"task_id": task_id, "delivery_hash": task.delivery_hash},
            sort_keys=True).encode()).hexdigest()
        await emit_evidence(task.id, executor_id, "task.delivered",
                          payload_hash, signature)

        return task

    async def verify_task(self, task_id: str, publisher_id: str,
                          approved: bool, signature: str) -> Task:
        """Verify (approve or reject) a delivered task.

        Transitions the task to VERIFIED or REJECTED based on
        the approved flag.

        Args:
            task_id: The task to verify.
            publisher_id: The agent ID of the publisher.
            approved: True to approve, False to reject.
            signature: Ed25519 signature for authentication.

        Returns:
            The updated Task instance.

        Raises:
            ValueError: If the task is not found.
            PermissionError: If the caller is not the publisher or
                signature verification fails.
        """
        task = await self.repo.get(task_id)
        if task is None:
            raise ValueError("task not found")
        if task.publisher_id != publisher_id:
            raise PermissionError("only publisher can verify")

        payload = json.dumps({
            "task_id": task_id, "approved": approved
        }, sort_keys=True)
        ok = await self.sig_verifier.verify(publisher_id, payload, signature)
        if not ok:
            raise PermissionError("signature verification failed")

        target = TaskStatus.VERIFIED if approved else TaskStatus.REJECTED
        task.transition_to(target)
        await self.repo.save(task)

        payload_hash = hashlib.sha256(payload.encode()).hexdigest()
        await emit_evidence(task.id, publisher_id,
                          "task.verified" if approved else "task.rejected",
                          payload_hash, signature)

        return task

    async def settle_task(self, task_id: str, publisher_id: str,
                          signature: str) -> Task:
        """Settle a verified task and release escrow funds.

        Transitions the task to SETTLED status (final state).
        TODO: Trigger escrow release and share settlement (Module 4).

        Args:
            task_id: The task to settle.
            publisher_id: The agent ID of the publisher.
            signature: Ed25519 signature for authentication.

        Returns:
            The updated Task instance.

        Raises:
            ValueError: If the task is not found.
            PermissionError: If the caller is not the publisher.
        """
        task = await self.repo.get(task_id)
        if task is None:
            raise ValueError("task not found")
        if task.publisher_id != publisher_id:
            raise PermissionError("only publisher can settle")

        task.transition_to(TaskStatus.SETTLED)
        await self.repo.save(task)

        # TODO: 触发 Escrow 释放 + 分成结算（Module 4）
        return task

    async def cancel_task(self, task_id: str, agent_id: str,
                          signature: str) -> Task:
        """Cancel a task.

        Only the publisher or the assigned executor can cancel.
        Transitions the task to CANCELLED status.

        Args:
            task_id: The task to cancel.
            agent_id: The agent ID requesting cancellation.
            signature: Ed25519 signature for authentication.

        Returns:
            The updated Task instance.

        Raises:
            ValueError: If the task is not found.
            PermissionError: If the caller is neither publisher nor executor.
        """
        task = await self.repo.get(task_id)
        if task is None:
            raise ValueError("task not found")
        if task.publisher_id != agent_id and task.executor_id != agent_id:
            raise PermissionError("only publisher or executor can cancel")

        task.transition_to(TaskStatus.CANCELLED)
        await self.repo.save(task)
        return task


# ─── 测试 ──────────────────────────────────────────────────

import pytest

@pytest.fixture
def service() -> TaskMarketService:
    """Create a TaskMarketService fixture with in-memory repository."""
    return TaskMarketService(
        repo=InMemoryTaskRepository(),
        sig_verifier=MockSignatureVerifier(),
    )

@pytest.mark.asyncio
async def test_create_and_list_task(service: TaskMarketService):
    """Test creating a task and listing all tasks."""
    req = CreateTaskRequest(
        title="设计一张海报",
        description="尺寸 1080x1920，科技风",
        escrow_amount=100,
        publisher_share=0.4,
        executor_share=0.6,
    )
    task = await service.create_task(req, "agent-1", "fake_sig")
    assert task.status == TaskStatus.OPEN
    assert task.publisher_id == "agent-1"

    tasks = await service.list_tasks()
    assert len(tasks) == 1

@pytest.mark.asyncio
async def test_assign_deliver_verify_settle(service: TaskMarketService):
    """Test the full task lifecycle: assign, deliver, verify, settle."""
    req = CreateTaskRequest("海报", "test", 100, 0.4, 0.6)
    task = await service.create_task(req, "agent-1", "sig")

    # 接单
    task = await service.assign_task(task.id, "agent-2", "sig")
    assert task.status == TaskStatus.ASSIGNED
    assert task.executor_id == "agent-2"

    # 交付
    task = await service.deliver_task(task.id, "https://img.url/done.png",
                                      "agent-2", "sig")
    assert task.status == TaskStatus.DELIVERED

    # 验收
    task = await service.verify_task(task.id, "agent-1", True, "sig")
    assert task.status == TaskStatus.VERIFIED

    # 结算
    task = await service.settle_task(task.id, "agent-1", "sig")
    assert task.status == TaskStatus.SETTLED

@pytest.mark.asyncio
async def test_invalid_transitions(service: TaskMarketService):
    """状态机边界：验收后不能直接接单"""
    req = CreateTaskRequest("海报", "test", 100, 0.4, 0.6)
    task = await service.create_task(req, "agent-1", "sig")
    task = await service.assign_task(task.id, "agent-2", "sig")
    task = await service.deliver_task(task.id, "url", "agent-2", "sig")
    task = await service.verify_task(task.id, "agent-1", True, "sig")

    with pytest.raises(ValueError, match="invalid transition"):
        await service.assign_task(task.id, "agent-3", "sig")

@pytest.mark.asyncio
async def test_share_validation(service: TaskMarketService):
    """分成比例必须和为1"""
    with pytest.raises(ValueError, match="shares must sum to 1.0"):
        req = CreateTaskRequest("海报", "test", 100, 0.7, 0.2)
        await service.create_task(req, "agent-1", "sig")

@pytest.mark.asyncio
async def test_reject_and_reassign(service: TaskMarketService):
    """驳回后可重新接单"""
    req = CreateTaskRequest("海报", "test", 100, 0.4, 0.6)
    task = await service.create_task(req, "agent-1", "sig")
    task = await service.assign_task(task.id, "agent-2", "sig")
    task = await service.deliver_task(task.id, "url", "agent-2", "sig")
    task = await service.verify_task(task.id, "agent-1", False, "sig")
    assert task.status == TaskStatus.REJECTED

    # 可以重新接单
    task = await service.assign_task(task.id, "agent-3", "sig")
    assert task.status == TaskStatus.ASSIGNED
    assert task.executor_id == "agent-3"
