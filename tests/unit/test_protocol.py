"""Unit tests for A2A protocol-level behavior.

Tests cover message format, required fields, and A2A protocol compliance
based on the A2A specification v0.1 draft.
"""

import pytest
from agentmesh.a2a.provider import (
    A2AResult,
    A2AError,
    A2ATaskState,
    MemoryProvider,
    A2ATaskManager,
)


# ── A2A Message Format Validation ────────────────────────────────────────

REQUIRED_TASK_FIELDS = ["id", "status"]
REQUIRED_STATUS_FIELDS = ["state"]
VALID_TASK_STATES = {
    "pending", "submitted", "working", "input-required",
    "completed", "failed", "canceled",
}


class TestMessageFormat:
    """A2A message format compliance tests"""

    def test_task_requires_id(self):
        provider = MemoryProvider()
        result = provider.send_message({"status": {"state": "submitted"}})
        assert result.success is False
        assert result.error.code == 400

    def test_well_formed_task_accepted(self):
        provider = MemoryProvider()
        task = {"id": "valid_001", "status": {"state": "submitted"}, "payload": {}}
        result = provider.send_message(task)
        assert result.success is True

    def test_task_state_preserved(self):
        provider = MemoryProvider()
        task = {"id": "state_001", "status": {"state": "working"}, "payload": {}}
        provider.send_message(task)
        result = provider.get_task("state_001")
        assert result.data["status"]["state"] == "working"

    def test_custom_fields_preserved(self):
        provider = MemoryProvider()
        task = {
            "id": "custom_001",
            "status": {"state": "submitted"},
            "payload": {"type": "research", "query": "test"},
            "metadata": {"priority": "high", "owner": "agent-x"},
        }
        provider.send_message(task)
        result = provider.get_task("custom_001")
        assert result.data["payload"]["type"] == "research"
        assert result.data["metadata"]["priority"] == "high"


class TestA2AErrorHandling:
    """A2A protocol error handling tests"""

    def test_error_with_code_and_message(self):
        error = A2AError(404, "Task not found")
        assert error.code == 404
        assert "not found" in error.message.lower()

    def test_error_string_representation(self):
        error = A2AError(400, "Bad request")
        assert "[400]" in str(error)
        assert "Bad request" in str(error)

    def test_recoverable_error(self):
        error = A2AError(503, "Service unavailable", recoverable=True)
        assert error.recoverable is True

    def test_non_recoverable_error(self):
        error = A2AError(500, "Fatal")
        assert error.recoverable is False


class TestTaskStateMachine:
    """A2A Task State Machine compliance tests"""

    def test_valid_transitions_from_pending(self):
        """From PENDING, can go to: SUBMITTED, FAILED, CANCELED"""
        mgr = A2ATaskManager()
        mgr.track("t", A2ATaskState.PENDING)
        mgr.update_state("t", A2ATaskState.SUBMITTED)
        mgr.update_state("t", A2ATaskState.FAILED)

    def test_valid_completion_path(self):
        """SUBMITTED → WORKING → COMPLETED"""
        mgr = A2ATaskManager()
        mgr.track("t", A2ATaskState.SUBMITTED)
        mgr.update_state("t", A2ATaskState.WORKING)
        mgr.update_state("t", A2ATaskState.COMPLETED)

    def test_input_required_returns_to_working(self):
        """WORKING → INPUT_REQUIRED → WORKING → COMPLETED"""
        mgr = A2ATaskManager()
        mgr.track("t", A2ATaskState.SUBMITTED)
        mgr.update_state("t", A2ATaskState.WORKING)
        mgr.update_state("t", A2ATaskState.INPUT_REQUIRED)
        mgr.update_state("t", A2ATaskState.WORKING)
        mgr.update_state("t", A2ATaskState.COMPLETED)

    @pytest.mark.parametrize(
        "from_state,to_state",
        [
            (A2ATaskState.COMPLETED, A2ATaskState.WORKING),
            (A2ATaskState.FAILED, A2ATaskState.SUBMITTED),
            (A2ATaskState.CANCELED, A2ATaskState.PENDING),
            (A2ATaskState.PENDING, A2ATaskState.COMPLETED),
        ],
    )
    def test_invalid_transitions_rejected(self, from_state, to_state):
        mgr = A2ATaskManager()
        mgr.track("t", from_state)
        with pytest.raises(A2AError):
            mgr.update_state("t", to_state)

    def test_canceled_is_terminal(self):
        mgr = A2ATaskManager()
        mgr.track("t", A2ATaskState.CANCELED)
        with pytest.raises(A2AError):
            mgr.update_state("t", A2ATaskState.WORKING)

    def test_failed_is_terminal(self):
        mgr = A2ATaskManager()
        mgr.track("t", A2ATaskState.FAILED)
        with pytest.raises(A2AError):
            mgr.update_state("t", A2ATaskState.PENDING)
