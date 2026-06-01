"""
Integration tests: A2AFacade + MemoryProvider + TaskManager end-to-end pipeline.

Tests cover the full lifecycle that real A2A agents would exercise:
create -> submit -> work -> complete/cancel, plus error handling.
"""

import pytest
from agentmesh.a2a.provider import (
    MemoryProvider,
    A2AProvider,
    A2AResult,
    A2AError,
    A2ATaskManager,
    A2ATaskState,
    A2AFacade,
)


class TestFacadeMemoryIntegration:
    """A2AFacade <-> MemoryProvider end-to-end flow"""

    def setup_method(self):
        self.provider = MemoryProvider("integration-test")
        self.facade = A2AFacade(provider=self.provider)

    def test_full_task_lifecycle_via_facade(self):
        """Realistic: create, submit, track state, retrieve, cancel via Facade"""
        # Step 1: Facade sends a task
        task = {"id": "lifecycle_001", "status": {"state": "submitted"}, "payload": {"query": "test"}}
        result = self.facade.send_task(task)
        assert result.success is True
        assert result.task_state == "submitted"

        # Step 2: Facade retrieves by id
        get_result = self.facade.get_task("lifecycle_001")
        assert get_result.success is True
        assert get_result.data["payload"]["query"] == "test"

        # Step 3: Cancel via Facade (should also update TaskManager state)
        cancel_result = self.facade.cancel_task("lifecycle_001")
        assert cancel_result.success is True
        assert cancel_result.task_state == "canceled"

        # Step 4: Verify TaskManager tracked the state
        tracked = self.facade.task_manager.get_task("lifecycle_001")
        assert tracked is not None
        assert tracked["state"] == A2ATaskState.CANCELED

    def test_multiple_tasks_via_single_facade(self):
        """Facade handles multiple concurrent tasks"""
        task_ids = [f"multi_{i:03d}" for i in range(5)]
        for tid in task_ids:
            task = {"id": tid, "status": {"state": "submitted"}, "payload": {"idx": int(tid.split("_")[1])}}
            r = self.facade.send_task(task)
            assert r.success is True

        # All retrievable independently
        for tid in task_ids:
            r = self.facade.get_task(tid)
            assert r.success is True
            assert r.data["id"] == tid

    def test_provider_swap_facade(self):
        """Facade.set_provider() allows runtime provider switching"""
        provider_b = MemoryProvider("swap-provider")
        self.facade.set_provider(provider_b)
        assert self.facade.provider.name == "swap-provider"

        # Verify operations go to the new provider
        task = {"id": "swap_001", "status": {"state": "submitted"}, "payload": {}}
        r = self.facade.send_task(task)
        assert r.success is True

        # Old provider should not have this task
        r_fail = self.provider.get_task("swap_001")
        assert r_fail.success is False

    def test_facade_error_propagation(self):
        """Errors from Provider propagate through Facade"""
        # Send a task without id -> MemoryProvider returns error (400)
        task = {"status": {"state": "submitted"}, "payload": {}}
        result = self.facade.send_task(task)
        assert result.success is False
        assert isinstance(result.error, A2AError)
        assert result.error.code == 400

        # Get nonexistent task
        result = self.facade.get_task("nobody_home")
        assert result.success is False
        assert result.error.code == 404

        # Cancel nonexistent task
        result = self.facade.cancel_task("ghost")
        assert result.success is False
        assert result.error.code == 404

    def test_facade_send_twice_tracks_once(self):
        """Sending the same task id twice should not duplicate tracking"""
        task = {"id": "dedup_001", "status": {"state": "submitted"}, "payload": {}}

        # First send
        r1 = self.facade.send_task(task)
        assert r1.success is True

        # Second send with updated state
        task["status"]["state"] = "working"
        r2 = self.facade.send_task(task)
        assert r2.success is True

        # TaskManager should have only one entry, state should be updated
        tracked = self.facade.task_manager.get_task("dedup_001")
        assert tracked is not None
        assert tracked["state"] == "working"


class TestTaskManagerIntegration:
    """A2ATaskManager integration with real-world workflows"""

    def setup_method(self):
        self.mgr = A2ATaskManager()
        self.provider = MemoryProvider("tm-integration")

    def test_parent_child_task_workflow(self):
        """Parent task spawns children, all tracked"""
        # Parent creation
        self.mgr.track("parent_001", A2ATaskState.SUBMITTED)
        self.mgr.update_state("parent_001", A2ATaskState.WORKING)

        # Child tasks
        children = ["child_001", "child_002", "child_003"]
        for cid in children:
            self.mgr.track(cid, A2ATaskState.PENDING, parent_id="parent_001")
            self.mgr.update_state(cid, A2ATaskState.SUBMITTED)
            self.mgr.update_state(cid, A2ATaskState.WORKING)
            self.mgr.update_state(cid, A2ATaskState.COMPLETED)

        # Verify parent state
        parent = self.mgr.get_task("parent_001")
        assert parent["state"] == A2ATaskState.WORKING

        # Verify children traversal
        retrieved_children = self.mgr.get_children("parent_001")
        assert len(retrieved_children) == 3
        for c in retrieved_children:
            assert c["state"] == A2ATaskState.COMPLETED

    def test_cleanup_expired_tasks(self):
        """TTL-based cleanup removes completed/failed/canceled tasks"""
        import time

        self.mgr.track("keep_me", A2ATaskState.SUBMITTED)
        self.mgr.track("expire_completed", A2ATaskState.WORKING)
        self.mgr.update_state("expire_completed", A2ATaskState.COMPLETED)
        self.mgr.track("expire_failed", A2ATaskState.WORKING)
        self.mgr.update_state("expire_failed", A2ATaskState.FAILED)
        self.mgr.track("expire_canceled", A2ATaskState.SUBMITTED)
        self.mgr.update_state("expire_canceled", A2ATaskState.CANCELED)

        # Force updated_at to be old by sleeping, or directly manipulate
        # We set max_age to 0 so all terminal-state tasks expire
        self.mgr.cleanup(max_age_seconds=0)

        assert self.mgr.get_task("keep_me") is not None  # pending state, not terminal
        assert self.mgr.get_task("expire_completed") is None
        assert self.mgr.get_task("expire_failed") is None
        assert self.mgr.get_task("expire_canceled") is None

    def test_invalid_transition_raises(self):
        """Invalid state transitions are rejected"""
        self.mgr.track("bad_tx", A2ATaskState.PENDING)
        with pytest.raises(A2AError, match="Invalid state transition"):
            self.mgr.update_state("bad_tx", A2ATaskState.COMPLETED)  # PENDING -> COMPLETED is invalid

    def test_task_not_found_transition(self):
        """Updating nonexistent task returns False"""
        result = self.mgr.update_state("ghost", A2ATaskState.WORKING)
        assert result is False


class TestProviderTaskManagerCoexistence:
    """Provider + TaskManager used together without Facade"""

    def setup_method(self):
        self.provider = MemoryProvider("coexistence")
        self.mgr = A2ATaskManager()

    def test_provider_and_manager_stay_in_sync(self):
        """Manually keep Provider and TaskManager state consistent"""
        task = {"id": "sync_001", "status": {"state": "submitted"}, "payload": {}}

        # Track in both
        self.mgr.track(task["id"], A2ATaskState.SUBMITTED)
        r = self.provider.send_message(task)
        assert r.success is True

        # Independent retrieval
        provider_task = self.provider.get_task("sync_001")
        mgr_task = self.mgr.get_task("sync_001")

        assert provider_task.data["id"] == mgr_task["task_id"]
        assert provider_task.data["status"]["state"] == mgr_task["state"]

    def test_provider_returns_consistent_artifacts(self):
        """MemoryProvider preserves task payload across lifecycle"""
        payload = {"query": "search", "max_results": 10, "filters": {"lang": "python"}}
        task = {"id": "artifact_001", "status": {"state": "working"}, "payload": payload}
        self.provider.send_message(task)

        # Simulate agent output written back to task
        task["status"]["state"] = "completed"
        task["payload"]["results"] = ["item1", "item2"]
        self.provider.send_message(task)  # update

        retrieved = self.provider.get_task("artifact_001")
        assert retrieved.data["payload"]["query"] == "search"
        assert retrieved.data["payload"]["max_results"] == 10
        assert retrieved.data["payload"]["results"] == ["item1", "item2"]
