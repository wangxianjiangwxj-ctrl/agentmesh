"""Unit tests for MemoryProvider — the in-process A2A Server simulation."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "sdk"))

import pytest
from a2a_provider import (
    MemoryProvider,
    A2AProvider,
    A2AResult,
    A2AError,
    A2ATaskManager,
    A2ATaskState,
    A2AFacade,
)


class TestMemoryProvider:
    """MemoryProvider: core A2A Server simulation"""

    def setup_method(self):
        self.provider = MemoryProvider("test-mem")

    def test_provider_creation(self):
        assert self.provider.name == "test-mem"
        assert isinstance(self.provider, A2AProvider)
        assert "local" in self.provider.capabilities

    def test_agent_card_registration(self):
        card = {"name": "scout-agent", "skills": ["search", "analyze"]}
        self.provider.register_agent_card(card)
        retrieved = self.provider.get_agent_card("scout-agent")
        assert retrieved["skills"] == ["search", "analyze"]

    def test_agent_card_not_found(self):
        assert self.provider.get_agent_card("nonexistent") is None

    def test_send_message_creates_task(self):
        task = {"id": "task_001", "status": {"state": "submitted"}, "payload": {}}
        result = self.provider.send_message(task)
        assert result.success is True
        assert result.task_state == "submitted"

    def test_send_message_missing_id_returns_error(self):
        result = self.provider.send_message({"status": {}, "payload": {}})
        assert result.success is False
        assert isinstance(result.error, A2AError)
        assert result.error.code == 400

    def test_get_task_returns_task(self):
        task = {"id": "task_002", "status": {"state": "working"}, "payload": {"query": "test"}}
        self.provider.send_message(task)
        result = self.provider.get_task("task_002")
        assert result.success is True
        assert result.data["id"] == "task_002"
        assert result.data["payload"]["query"] == "test"

    def test_get_task_not_found(self):
        result = self.provider.get_task("nonexistent")
        assert result.success is False
        assert result.error.code == 404

    def test_cancel_task(self):
        task = {"id": "task_003", "status": {"state": "working"}, "payload": {}}
        self.provider.send_message(task)
        result = self.provider.cancel_task("task_003")
        assert result.success is True
        assert result.task_state == "canceled"

        # Verify state persisted
        get_result = self.provider.get_task("task_003")
        assert get_result.data["status"]["state"] == "canceled"

    def test_cancel_nonexistent_task(self):
        result = self.provider.cancel_task("ghost")
        assert result.success is False
        assert result.error.code == 404

    def test_ping(self):
        result = self.provider.ping()
        assert result.success is True
        assert result.data["status"] == "ok"
        assert result.data["provider"] == "test-mem"

    def test_multiple_conversations_isolated(self):
        # Two independent conversations should not interfere
        task_a = {"id": "conv_a_001", "status": {"state": "submitted"}, "payload": {}}
        task_b = {"id": "conv_b_001", "status": {"state": "working"}, "payload": {}}

        self.provider.send_message(task_a)
        self.provider.send_message(task_b)

        result_a = self.provider.get_task("conv_a_001")
        result_b = self.provider.get_task("conv_b_001")

        assert result_a.data["id"] == "conv_a_001"
        assert result_b.data["id"] == "conv_b_001"
        assert result_a.data["status"]["state"] == "submitted"
        assert result_b.data["status"]["state"] == "working"


class TestA2ATaskManager:
    """A2ATaskManager: task lifecycle and state machine"""

    def setup_method(self):
        self.mgr = A2ATaskManager()

    def test_track_new_task(self):
        self.mgr.track("task_001", A2ATaskState.PENDING)
        task = self.mgr.get_task("task_001")
        assert task["state"] == A2ATaskState.PENDING

    def test_valid_state_transition_chain(self):
        self.mgr.track("task_001", A2ATaskState.PENDING)
        self.mgr.update_state("task_001", A2ATaskState.SUBMITTED)
        self.mgr.update_state("task_001", A2ATaskState.WORKING)
        self.mgr.update_state("task_001", A2ATaskState.COMPLETED)

        final = self.mgr.get_task("task_001")
        assert final["state"] == A2ATaskState.COMPLETED

    def test_invalid_state_transition_raises(self):
        self.mgr.track("task_001", A2ATaskState.COMPLETED)
        with pytest.raises(A2AError, match="400"):
            self.mgr.update_state("task_001", A2ATaskState.WORKING)

    def test_get_task_non_existent(self):
        assert self.mgr.get_task("ghost") is None

    def test_parent_child_relationship(self):
        self.mgr.track("parent", A2ATaskState.SUBMITTED)
        self.mgr.track("child_1", A2ATaskState.PENDING, parent_id="parent")
        self.mgr.track("child_2", A2ATaskState.PENDING, parent_id="parent")

        children = self.mgr.get_children("parent")
        assert len(children) == 2
        assert children[0]["id"] == "child_1"
        assert children[1]["id"] == "child_2"

    def test_nonexistent_parent_children(self):
        assert self.mgr.get_children("no_such_task") == []

    def test_cleanup_removes_stale_tasks(self):
        self.mgr.track("completed_task", A2ATaskState.COMPLETED)
        self.mgr.track("pending_task", A2ATaskState.PENDING)

        # Mock stale completed task
        task = self.mgr.get_task("completed_task")
        task["updated_at"] = "2020-01-01T00:00:00"

        self.mgr.cleanup(max_age_seconds=1)
        assert self.mgr.get_task("completed_task") is None
        assert self.mgr.get_task("pending_task") is not None

    def test_noop_transition(self):
        self.mgr.track("task_001", A2ATaskState.PENDING)
        # Same state should be a no-op
        self.mgr.update_state("task_001", A2ATaskState.PENDING)
        assert self.mgr.get_task("task_001")["state"] == A2ATaskState.PENDING


class TestA2AFacade:
    """A2AFacade: unified entry point for Provider + TaskManager"""

    def setup_method(self):
        provider = MemoryProvider("test-facade")
        self.facade = A2AFacade(provider, A2ATaskManager())

    def test_send_task_through_facade(self):
        task = {"id": "facade_001", "status": {"state": "submitted"}}
        result = self.facade.send_task(task)
        assert result.success is True

    def test_get_task_through_facade(self):
        task = {"id": "facade_002", "status": {"state": "working"}}
        self.facade.send_task(task)
        result = self.facade.get_task("facade_002")
        assert result.success is True

    def test_cancel_task_through_facade(self):
        task = {"id": "facade_003", "status": {"state": "submitted"}}
        self.facade.send_task(task)
        result = self.facade.cancel_task("facade_003")
        assert result.success is True

    def test_provider_switching(self):
        new_provider = MemoryProvider("switched")
        self.facade.set_provider(new_provider)
        assert self.facade.provider.name == "switched"

    def test_task_state_tracked_through_facade(self):
        task = {"id": "facade_state", "status": {"state": "submitted"}}
        self.facade.send_task(task)
        tracked = self.facade.task_manager.get_task("facade_state")
        assert tracked["state"] == A2ATaskState.SUBMITTED


class TestA2AResult:
    """A2AResult: operation result encapsulation"""

    def test_ok_result(self):
        r = A2AResult.ok({"message": "hello"})
        assert r.success is True
        assert r.data["message"] == "hello"

    def test_fail_result(self):
        error = A2AError(500, "Internal error", recoverable=True)
        r = A2AResult.fail(error)
        assert r.success is False
        assert r.error.code == 500
        assert r.error.recoverable is True

    def test_bool_conversion(self):
        assert bool(A2AResult.ok("data")) is True
        assert bool(A2AResult.fail(A2AError(400, "bad"))) is False
