"""A2A provider performance benchmarks.

Benchmarks the actual A2A provider classes: MemoryProvider, A2ATaskManager, A2AFacade.
"""

import pytest

from agentmesh.a2a_models import ServerTimeoutConfig
from agentmesh.a2a_provider import (
    A2AFacade,
    A2AResult,
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
            result = provider.create_task(
                task_id="bench-task",
                message="Test message",
                metadata={"bench": "true"},
            )
            return result

        result = benchmark(_run)
        assert result.success

    @pytest.mark.benchmark(min_rounds=100)
    def test_send_message(self, benchmark):
        """Benchmark sending messages to an existing task."""
        provider = MemoryProvider()
        provider.create_task(task_id="bench-task", message="Hello")

        def _run():
            result = provider.send_message(
                task_id="bench-task",
                message="Ping",
            )
            return result

        result = benchmark(_run)
        assert result.success

    @pytest.mark.benchmark(min_rounds=50)
    def test_get_task(self, benchmark):
        """Benchmark getting task state."""
        provider = MemoryProvider()
        provider.create_task(task_id="bench-task", message="Hello")
        provider.send_message(task_id="bench-task", message="Ping")

        def _run():
            state = provider.get_task(task_id="bench-task")
            return state

        state = benchmark(_run)
        assert state is not None

    @pytest.mark.benchmark(min_rounds=30)
    def test_cancel_task(self, benchmark):
        """Benchmark task cancellation."""
        def _run():
            provider = MemoryProvider()
            provider.create_task(task_id="cancel-me", message="Hello")
            result = provider.cancel_task(task_id="cancel-me")
            return result

        result = benchmark(_run)
        assert result.success


class TestA2ATaskManagerBenchmarks:
    """Benchmark A2ATaskManager operations."""

    @pytest.mark.benchmark(min_rounds=100)
    def test_manager_create_task(self, benchmark):
        """Benchmark task manager create + assign id."""
        manager = A2ATaskManager()

        def _run():
            task = manager.create_task(message="Bench task")
            return task

        task = benchmark(_run)
        assert task is not None
        assert task.task_id is not None

    @pytest.mark.benchmark(min_rounds=50)
    def test_manager_list_tasks(self, benchmark):
        """Benchmark listing tasks from manager."""
        manager = A2ATaskManager()
        for i in range(10):
            manager.create_task(message=f"Task {i}")

        def _run():
            tasks = manager.list_tasks()
            return len(tasks)

        count = benchmark(_run)
        assert count == 10


class TestA2AFacadeBenchmarks:
    """Benchmark A2AFacade end-to-end flows."""

    @pytest.mark.benchmark(min_rounds=50)
    def test_facade_initialization(self, benchmark):
        """Benchmark A2AFacade creation with MemoryProvider."""
        config = ServerTimeoutConfig()

        def _run():
            facade = A2AFacade(provider=MemoryProvider(), config=config)
            return facade

        facade = benchmark(_run)
        assert facade is not None

    @pytest.mark.benchmark(min_rounds=30)
    def test_facade_send_and_poll(self, benchmark):
        """Benchmark facade send + poll flow."""
        config = ServerTimeoutConfig()

        def _run():
            facade = A2AFacade(provider=MemoryProvider(), config=config)
            result = facade.send_message(
                task_id="test",
                message="Hello from bench",
                on_result=lambda r: None,
            )
            return result

        result = benchmark(_run)
        assert result is not None
