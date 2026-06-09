"""A2A provider performance benchmarks.

Benchmarks the actual A2A provider classes: MemoryProvider, A2ATaskManager, A2AFacade.
"""

import pytest

from agentmesh.a2a_provider import (
    A2AFacade,
    A2ATaskManager,
    MemoryProvider,
)


class TestA2AProviderBenchmarks:
    """Benchmark MemoryProvider core operations."""

    @pytest.mark.benchmark(min_rounds=200)
    def test_create_task(self, benchmark):
        """Benchmark task creation in MemoryProvider."""
        provider = MemoryProvider()

        def _run():
            result = provider.send_message(
                {"id": "bench-task", "message": "Test message", "metadata": {"bench": "true"}},
            )
            return result

        result = benchmark(_run)
        assert result.success
        assert result.task_state == "submitted"

    @pytest.mark.benchmark(min_rounds=100)
    def test_send_message(self, benchmark):
        """Benchmark sending messages via MemoryProvider."""
        provider = MemoryProvider()
        provider.send_message({"id": "bench-task", "message": "Hello"})

        def _run():
            result = provider.send_message({"id": "bench-task", "message": "Ping"})
            return result

        result = benchmark(_run)
        assert result.success

    @pytest.mark.benchmark(min_rounds=50)
    def test_get_task(self, benchmark):
        """Benchmark getting task state."""
        provider = MemoryProvider()
        provider.send_message({"id": "bench-task", "message": "Hello"})

        def _run():
            state = provider.get_task(task_id="bench-task")
            return state

        state = benchmark(_run)
        assert state is not None
        assert state.success

    @pytest.mark.benchmark(min_rounds=30)
    def test_cancel_task(self, benchmark):
        """Benchmark task cancellation."""
        def _run():
            provider = MemoryProvider()
            provider.send_message({"id": "cancel-me", "message": "Hello"})
            result = provider.cancel_task(task_id="cancel-me")
            return result

        result = benchmark(_run)
        assert result.success
        assert result.task_state == "canceled"


class TestA2ATaskManagerBenchmarks:
    """Benchmark A2ATaskManager operations."""

    @pytest.mark.benchmark(min_rounds=100)
    def test_manager_create_task(self, benchmark):
        """Benchmark task manager create + assign id."""
        import uuid
        manager = A2ATaskManager()

        def _run():
            tid = f"bench-{uuid.uuid4().hex[:8]}"
            task = manager.track(task_id=tid, initial_state="pending", metadata={"desc": "Bench task"})
            return task

        task = benchmark(_run)
        assert task is not None
        assert task["task_id"] is not None

    @pytest.mark.benchmark(min_rounds=50)
    def test_manager_list_tasks(self, benchmark):
        """Benchmark listing tasks from manager."""
        manager = A2ATaskManager()
        for i in range(10):
            manager.track(task_id=f"task-{i}", initial_state="pending", metadata={"desc": f"Task {i}"})

        def _run():
            # Use get_task for each known id as a proxy for list operations
            count = sum(1 for i in range(10) if manager.get_task(f"task-{i}") is not None)
            return count

        count = benchmark(_run)
        assert count == 10


class TestA2AFacadeBenchmarks:
    """Benchmark A2AFacade end-to-end flows."""

    @pytest.mark.benchmark(min_rounds=50)
    def test_facade_initialization(self, benchmark):
        """Benchmark A2AFacade creation with MemoryProvider."""
        def _run():
            facade = A2AFacade(provider=MemoryProvider())
            return facade

        facade = benchmark(_run)
        assert facade is not None

    @pytest.mark.benchmark(min_rounds=30)
    def test_facade_send_task(self, benchmark):
        """Benchmark facade send task flow."""
        import uuid
        def _run():
            facade = A2AFacade(provider=MemoryProvider())
            tid = f"facade-{uuid.uuid4().hex[:8]}"
            result = facade.send_task({"id": tid, "message": "Hello from bench"})
            return result

        result = benchmark(_run)
        assert result is not None
        assert result.success
