"""
P2: Provider Latency Baseline Tests.

Measures the mean/median/P99 latency of each A2A Provider's core
operations (send_message, get_task, cancel_task) under controlled
conditions.

Pass/fail thresholds are defined in perf/conftest.py LatencyThresholds.
All tests run in-process with MemoryProvider or A2AFacade, requiring
no network or external services.

Design:
  - Each test collects 1000 timed iterations after 100 warmup calls.
  - Assertions check mean and P99 against the threshold constants.
  - The same provider instance is reused within a module (module-scoped
    fixture) to amortize construction overhead.
  - HttpProvider tests are gated behind FastAPI availability and start
    their own ephemeral server.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agentmesh"))

from agentmesh.a2a_provider import A2AFacade, A2AResult, MemoryProvider
from tests.perf.conftest import (
    LATENCY_THRESHOLDS as T,
)
from tests.perf.conftest import (
    get_rss_mb,
    measure_latency,
)

# ===================================================================
# MemoryProvider — Latency Baselines
# ===================================================================


class TestMemoryProviderLatency:
    """Latency baseline for pure in-memory provider (no framework overhead)."""

    ITERATIONS = 1000
    WARMUP = 100

    def test_send_message_mean_p99(self, memory_provider, sample_task_full):
        """MemoryProvider.send_message: mean < 500us, P99 < 2ms."""
        task = dict(sample_task_full)

        def op():
            r = memory_provider.send_message(task)
            # Assert inside the timed loop is fine for perf tests
            assert r.success, f"send_message failed: {r.error}"

        stats = measure_latency(
            op, iterations=self.ITERATIONS, warmup=self.WARMUP,
            label="MemoryProvider.send_message",
        )

        assert stats.mean < T.memory_send_mean, (
            f"send_message mean={stats.mean*1e6:.1f}us > "
            f"threshold={T.memory_send_mean*1e6:.1f}us"
        )
        assert stats.p99 < T.memory_send_p99, (
            f"send_message p99={stats.p99*1e6:.1f}us > "
            f"threshold={T.memory_send_p99*1e6:.1f}us"
        )

    def test_get_task_mean_p99(self, memory_provider, sample_task_full):
        """MemoryProvider.get_task: mean < 300us, P99 < 1ms."""
        task = dict(sample_task_full)
        task_id = task["id"]
        memory_provider.send_message(task)

        def op():
            r = memory_provider.get_task(task_id)
            assert r.success

        stats = measure_latency(
            op, iterations=self.ITERATIONS, warmup=self.WARMUP,
            label="MemoryProvider.get_task",
        )

        assert stats.mean < T.memory_get_mean, (
            f"get_task mean={stats.mean*1e6:.1f}us > "
            f"threshold={T.memory_get_mean*1e6:.1f}us"
        )
        assert stats.p99 < T.memory_get_p99, (
            f"get_task p99={stats.p99*1e6:.1f}us > "
            f"threshold={T.memory_get_p99*1e6:.1f}us"
        )

    def test_cancel_task_mean_p99(self, memory_provider, sample_task_full):
        """MemoryProvider.cancel_task: mean < 300us, P99 < 1ms."""
        # Use a fresh task each iteration so cancel doesn't see "canceled"
        task = dict(sample_task_full)
        task_id = task["id"]
        memory_provider.send_message(task)

        def op():
            r = memory_provider.cancel_task(task_id)
            assert r.success

        stats = measure_latency(
            op, iterations=self.ITERATIONS, warmup=self.WARMUP,
            label="MemoryProvider.cancel_task",
        )

        assert stats.mean < T.memory_cancel_mean, (
            f"cancel_task mean={stats.mean*1e6:.1f}us > "
            f"threshold={T.memory_cancel_mean*1e6:.1f}us"
        )
        assert stats.p99 < T.memory_cancel_p99, (
            f"cancel_task p99={stats.p99*1e6:.1f}us > "
            f"threshold={T.memory_cancel_p99*1e6:.1f}us"
        )

    def test_ping_latency(self, memory_provider):
        """MemoryProvider.ping: verify it returns under 100us."""
        def op():
            r = memory_provider.ping()
            assert r.success
            assert r.data["status"] == "ok"

        stats = measure_latency(
            op, iterations=500, warmup=50,
            label="MemoryProvider.ping",
        )

        # Ping is extremely lightweight — just a dict construction
        assert stats.mean < 0.0002, (
            f"ping mean={stats.mean*1e6:.1f}us > 200us"
        )

    def test_task_not_found_error_latency(self, memory_provider):
        """MemoryProvider.get_task on missing ID: error path latency < 200us."""
        def op():
            r = memory_provider.get_task("nonexistent_task_id_xyz")
            assert not r.success
            assert r.error is not None

        stats = measure_latency(
            op, iterations=500, warmup=50,
            label="MemoryProvider.get_task (404)",
        )

        assert stats.mean < 0.0002, (
            f"404 latency mean={stats.mean*1e6:.1f}us > 200us"
        )


# ===================================================================
# A2AFacade — Latency Baselines
# ===================================================================


class TestA2AFacadeLatency:
    """Latency baseline for A2AFacade (MemoryProvider + TaskManager wrapper).

    Facade adds TaskManager tracking on send, which should be slightly
    slower than raw MemoryProvider but still in the low-microsecond range.
    """

    ITERATIONS = 500   # fewer iterations due to extra manager overhead
    WARMUP = 50

    def test_send_task_mean_p99(self, facade, sample_task_full):
        """A2AFacade.send_task: mean < 1ms, P99 < 5ms."""

        def op():
            task = {
                "id": f"facade_send_{int(time.time() * 1e9)}",
                "status": {"state": "submitted"},
                "payload": {},
            }
            r = facade.send_task(task)
            assert r.success

        stats = measure_latency(
            op, iterations=self.ITERATIONS, warmup=self.WARMUP,
            label="A2AFacade.send_task",
        )

        assert stats.mean < T.facade_send_mean, (
            f"Facade send_task mean={stats.mean*1e6:.1f}us > "
            f"threshold={T.facade_send_mean*1e6:.1f}us"
        )
        assert stats.p99 < T.facade_send_p99, (
            f"Facade send_task p99={stats.p99*1e6:.1f}us > "
            f"threshold={T.facade_send_p99*1e6:.1f}us"
        )

    def test_get_task_mean_p99(self, facade):
        """A2AFacade.get_task: mean < 500us, P99 < 2ms."""
        # Pre-populate a task
        task_id = f"facade_get_{int(time.time() * 1e9)}"
        facade.send_task({
            "id": task_id,
            "status": {"state": "submitted"},
            "payload": {},
        })

        def op():
            r = facade.get_task(task_id)
            assert r.success

        stats = measure_latency(
            op, iterations=self.ITERATIONS, warmup=self.WARMUP,
            label="A2AFacade.get_task",
        )

        assert stats.mean < T.facade_get_mean, (
            f"Facade get_task mean={stats.mean*1e6:.1f}us > "
            f"threshold={T.facade_get_mean*1e6:.1f}us"
        )
        assert stats.p99 < T.facade_get_p99, (
            f"Facade get_task p99={stats.p99*1e6:.1f}us > "
            f"threshold={T.facade_get_p99*1e6:.1f}us"
        )

    def test_cancel_task_latency(self, facade):
        """A2AFacade.cancel_task: mean < 1ms."""
        task_id = f"facade_cancel_{int(time.time() * 1e9)}"
        facade.send_task({
            "id": task_id,
            "status": {"state": "submitted"},
            "payload": {},
        })

        def op():
            r = facade.cancel_task(task_id)
            assert r.success

        stats = measure_latency(
            op, iterations=self.ITERATIONS, warmup=self.WARMUP,
            label="A2AFacade.cancel_task",
        )

        assert stats.mean < 0.001, (
            f"Facade cancel_task mean={stats.mean*1e6:.1f}us > 1ms"
        )


# ===================================================================
# HttpProvider — Latency (requires local server)
# ===================================================================


class TestHttpProviderLatency:
    """Latency baseline for HttpProvider (HTTP to localhost).

    These tests are only collected when FastAPI/uvicorn are available.
    They start an ephemeral server on a random port.
    """

    ITERATIONS = 200   # fewer iterations — HTTP involves real I/O
    WARMUP = 20

    @pytest.mark.skipif(
        not sys.modules.get("fastapi"),
        reason="FastAPI/uvicorn not installed",
    )
    def test_send_message_latency(self, http_provider):
        """HttpProvider.send_message: mean < 50ms (localhost)."""

        def op():
            task = {
                "id": f"http_send_{int(time.time() * 1e9)}",
                "status": {"state": "submitted"},
                "payload": {},
            }
            r = http_provider.send_message(task)
            assert r.success

        stats = measure_latency(
            op, iterations=self.ITERATIONS, warmup=self.WARMUP,
            label="HttpProvider.send_message",
        )

        # Looser thresholds for HTTP even on localhost
        assert stats.mean < T.http_send_mean, (
            f"Http send_message mean={stats.mean*1e3:.1f}ms > "
            f"threshold={T.http_send_mean*1e3:.1f}ms"
        )

    @pytest.mark.skipif(
        not sys.modules.get("fastapi"),
        reason="FastAPI/uvicorn not installed",
    )
    def test_ping_latency(self, http_provider):
        """HttpProvider.ping: mean < 50ms (localhost)."""

        def op():
            r = http_provider.ping()
            assert r.success

        stats = measure_latency(
            op, iterations=self.ITERATIONS, warmup=self.WARMUP,
            label="HttpProvider.ping",
        )

        assert stats.mean < T.http_ping_mean, (
            f"Http ping mean={stats.mean*1e3:.1f}ms > "
            f"threshold={T.http_ping_mean*1e3:.1f}ms"
        )

    @pytest.mark.skipif(
        not sys.modules.get("fastapi"),
        reason="FastAPI/uvicorn not installed",
    )
    def test_get_task_latency(self, http_provider):
        """HttpProvider.get_task: mean < 50ms (localhost)."""
        task_id = f"http_get_{int(time.time() * 1e9)}"
        http_provider.send_message({
            "id": task_id,
            "status": {"state": "submitted"},
            "payload": {},
        })

        def op():
            r = http_provider.get_task(task_id)
            assert r.success

        stats = measure_latency(
            op, iterations=self.ITERATIONS, warmup=self.WARMUP,
            label="HttpProvider.get_task",
        )

        assert stats.mean < T.http_get_mean, (
            f"Http get_task mean={stats.mean*1e3:.1f}ms > "
            f"threshold={T.http_get_mean*1e3:.1f}ms"
        )


# ===================================================================
# Cross-Provider Comparison (informational)
# ===================================================================


class TestProviderComparison:
    """Compare latency across all available providers.

    This test runs against both MemoryProvider and A2AFacade,
    reporting and asserting that A2AFacade is not drastically
    slower than raw MemoryProvider on the same operation.
    """

    def test_facade_not_slower_than_memory_by_factor(
        self, memory_provider, facade
    ):
        """Facade.send_task should be no more than 5x slower than raw MemoryProvider.

        This catches regressions where the wrapper layer introduces
        disproportionate overhead (e.g., unnecessary locking, deep copies).
        """
        task_mem = {
            "id": f"cmp_send_{int(time.time() * 1e9)}",
            "status": {"state": "submitted"},
            "payload": {},
        }

        def send_mem():
            r = memory_provider.send_message(task_mem)
            assert r.success

        def send_facade():
            t = {
                "id": f"cmp_facade_{int(time.time() * 1e9)}",
                "status": {"state": "submitted"},
                "payload": {},
            }
            r = facade.send_task(t)
            assert r.success

        mem_stats = measure_latency(send_mem, iterations=500, warmup=50)
        facade_stats = measure_latency(send_facade, iterations=500, warmup=50)

        slowdown_ratio = facade_stats.mean / mem_stats.mean if mem_stats.mean > 0 else float("inf")

        print(
            f"  [Comparison] MemoryProvider.mean={mem_stats.mean*1e6:.1f}us "
            f"Facade.mean={facade_stats.mean*1e6:.1f}us "
            f"ratio={slowdown_ratio:.2f}x"
        )

        assert slowdown_ratio < 5.0, (
            f"A2AFacade is {slowdown_ratio:.1f}x slower than MemoryProvider "
            f"(threshold: 5x)"
        )
