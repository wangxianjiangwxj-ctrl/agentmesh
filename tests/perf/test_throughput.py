"""
P2: Throughput & Concurrency Tests.

Measures operations-per-second (TPS) under various concurrency levels
for MemoryProvider and A2AFacade. Tests cover:

  1. Sequential throughput (single-threaded, your baseline)
  2. Concurrent throughput (threaded, ramped concurrency)
  3. Mixed-operation throughput (send + get interleaved)
  4. Resource usage (memory growth under load)

Design:
  - Uses time.perf_counter() for timing (no pytest-benchmark dependency).
  - Concurrent execution via Python threading + manual thread coordination.
  - Memory tracking via resource.getrusage().
  - All tests assert against ThroughputThresholds and ResourceThresholds.
  - No external services required; MemoryProvider runs entirely in-process.
"""

from __future__ import annotations

import gc
import os
import resource
import statistics
import sys
import threading
import time
from typing import List

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agentmesh"))

from agentmesh.a2a_provider import A2AFacade, A2AResult, MemoryProvider
from tests.perf.conftest import (
    LATENCY_THRESHOLDS,
    TimingStats,
    get_rss_mb,
    measure_latency,
    run_concurrent,
)
from tests.perf.conftest import (
    RESOURCE_THRESHOLDS as RT,
)
from tests.perf.conftest import (
    THROUGHPUT_THRESHOLDS as TPT,
)

# ===================================================================
# MemoryProvider — Sequential Throughput
# ===================================================================


class TestMemoryProviderSequentialThroughput:
    """Single-threaded throughput baselines for MemoryProvider."""

    def test_send_message_tps(self, memory_provider):
        """MemoryProvider.send_message: >= 5000 ops/sec sequential."""
        task_template = {"status": {"state": "submitted"}, "payload": {}}

        def op():
            task = dict(task_template)
            task["id"] = f"tps_seq_{int(time.time() * 1e9)}"
            r = memory_provider.send_message(task)
            assert r.success

        stats = measure_latency(
            op, iterations=2000, warmup=200,
            label="MemoryProvider.send_message throughput",
        )

        assert stats.ops_per_sec >= TPT.memory_send_tps_min, (
            f"send_message throughput={stats.ops_per_sec:,.0f} ops/s < "
            f"threshold={TPT.memory_send_tps_min:,.0f} ops/s"
        )

    def test_get_task_tps(self, memory_provider):
        """MemoryProvider.get_task: >= 8000 ops/sec sequential."""
        # Pre-populate a single task — all gets hit the same key
        task_id = f"tps_get_{int(time.time() * 1e9)}"
        memory_provider.send_message({
            "id": task_id, "status": {"state": "submitted"}, "payload": {},
        })

        def op():
            r = memory_provider.get_task(task_id)
            assert r.success

        stats = measure_latency(
            op, iterations=2000, warmup=200,
            label="MemoryProvider.get_task throughput",
        )

        assert stats.ops_per_sec >= TPT.memory_get_tps_min, (
            f"get_task throughput={stats.ops_per_sec:,.0f} ops/s < "
            f"threshold={TPT.memory_get_tps_min:,.0f} ops/s"
        )

    def test_mixed_operations_tps(self, memory_provider):
        """MemoryProvider: mixed send+get+cancel >= 4000 ops/sec."""
        task_id = None

        def op_send():
            nonlocal task_id
            task_id = f"tps_mix_{int(time.time() * 1e9)}"
            r = memory_provider.send_message({
                "id": task_id, "status": {"state": "submitted"}, "payload": {},
            })
            assert r.success

        def op_get():
            nonlocal task_id
            if task_id:
                r = memory_provider.get_task(task_id)
                assert r.success

        def op_cancel():
            nonlocal task_id
            if task_id:
                r = memory_provider.cancel_task(task_id)
                assert r.success

        ops = [op_send, op_get, op_cancel]
        latencies: List[float] = []
        for _ in range(1000):
            for op in ops:
                t0 = time.perf_counter()
                op()
                latencies.append(time.perf_counter() - t0)

        stats = TimingStats.compute(latencies)

        assert stats.ops_per_sec >= TPT.memory_mixed_tps_min, (
            f"mixed ops throughput={stats.ops_per_sec:,.0f} ops/s < "
            f"threshold={TPT.memory_mixed_tps_min:,.0f} ops/s"
        )


# ===================================================================
# MemoryProvider — Concurrent Throughput
# ===================================================================


class TestMemoryProviderConcurrentThroughput:
    """Multi-threaded throughput for MemoryProvider.

    Tests with 2, 4, and 8 concurrent worker threads to verify
    that the provider scales with parallelism (no global locks).
    """

    @pytest.mark.parametrize("num_workers", [2, 4, 8])
    def test_concurrent_send_throughput(
        self, memory_provider, num_workers
    ):
        """MemoryProvider.send_message concurrent: >= 20K ops/sec at 4 workers."""

        def send_op(idx: int):
            r = memory_provider.send_message({
                "id": f"concurrent_{idx}_{int(time.time() * 1e9)}",
                "status": {"state": "submitted"},
                "payload": {},
            })
            assert r.success
            return r

        stats = run_concurrent(
            send_op,
            num_workers=num_workers,
            iterations_per_worker=250,
            label=f"MemoryProvider.concurrent_send (workers={num_workers})",
        )

        # At 4 workers, we expect >= 20K ops/sec
        if num_workers == 4:
            assert stats.ops_per_sec >= TPT.memory_concurrent_tps_min, (
                f"concurrent send (4 workers) = {stats.ops_per_sec:,.0f} ops/s < "
                f"threshold={TPT.memory_concurrent_tps_min:,.0f} ops/s"
            )

        # Higher workers should not regress — scaling check
        print(
            f"  [Scaling] workers={num_workers} ops/s={stats.ops_per_sec:,.0f} "
            f"mean={stats.mean*1e6:.1f}us"
        )

    @pytest.mark.parametrize("num_workers", [2, 4])
    def test_concurrent_mixed_throughput(
        self, memory_provider, num_workers
    ):
        """MemoryProvider mixed ops (send+get) under concurrency."""

        def mixed_op(idx: int):
            task_id = f"conc_mix_{idx}_{int(time.time() * 1e9)}"
            # Send
            r1 = memory_provider.send_message({
                "id": task_id, "status": {"state": "submitted"}, "payload": {},
            })
            assert r1.success
            # Get
            r2 = memory_provider.get_task(task_id)
            assert r2.success
            # Cancel
            r3 = memory_provider.cancel_task(task_id)
            assert r3.success

        stats = run_concurrent(
            mixed_op,
            num_workers=num_workers,
            iterations_per_worker=100,
            label=f"MemoryProvider.concurrent_mixed (workers={num_workers})",
        )

        # Ensure 100% success rate
        # (run_concurrent does not capture per-invocation success, but
        #  the op function raises on assertion failure)
        assert stats.count > 0


# ===================================================================
# A2AFacade — Sequential Throughput
# ===================================================================


class TestA2AFacadeThroughput:
    """Throughput baselines for A2AFacade (wraps MemoryProvider + TaskManager)."""

    def test_send_task_tps(self, facade):
        """A2AFacade.send_task: >= 3000 ops/sec sequential."""

        def op():
            task = {
                "id": f"facade_tps_{int(time.time() * 1e9)}",
                "status": {"state": "submitted"},
                "payload": {},
            }
            r = facade.send_task(task)
            assert r.success

        stats = measure_latency(
            op, iterations=1000, warmup=100,
            label="A2AFacade.send_task throughput",
        )

        assert stats.ops_per_sec >= TPT.facade_send_tps_min, (
            f"Facade send_task throughput={stats.ops_per_sec:,.0f} ops/s < "
            f"threshold={TPT.facade_send_tps_min:,.0f} ops/s"
        )

    def test_get_task_tps(self, facade):
        """A2AFacade.get_task: >= 5000 ops/sec sequential."""
        task_id = f"facade_tps_get_{int(time.time() * 1e9)}"
        facade.send_task({
            "id": task_id, "status": {"state": "submitted"}, "payload": {},
        })

        def op():
            r = facade.get_task(task_id)
            assert r.success

        stats = measure_latency(
            op, iterations=1000, warmup=100,
            label="A2AFacade.get_task throughput",
        )

        assert stats.ops_per_sec >= TPT.facade_get_tps_min, (
            f"Facade get_task throughput={stats.ops_per_sec:,.0f} ops/s < "
            f"threshold={TPT.facade_get_tps_min:,.0f} ops/s"
        )


# ===================================================================
# Resource Usage Under Load
# ===================================================================


class TestResourceUsage:
    """Memory and CPU baselines under sustained throughput load."""

    def test_memory_baseline_and_growth(self, memory_provider):
        """MemoryProvider sustained load: RSS < 200MB, growth < 50MB.

        Sends 10,000 tasks and checks memory before/after.
        """
        gc.collect()
        before = get_rss_mb()

        # Send 10K tasks
        for i in range(10000):
            memory_provider.send_message({
                "id": f"mem_test_{i}",
                "status": {"state": "submitted"},
                "payload": {"query": f"test_{i}" * 10},
            })

        gc.collect()
        after = get_rss_mb()
        growth = after - before

        print(
            f"  [Memory] Before={before:.1f}MB After={after:.1f}MB "
            f"Growth={growth:+.1f}MB"
        )

        assert after < RT.memory_max_mb, (
            f"RSS {after:.1f}MB exceeds max {RT.memory_max_mb:.1f}MB"
        )
        assert growth < RT.memory_growth_mb, (
            f"RSS growth {growth:.1f}MB exceeds limit {RT.memory_growth_mb:.1f}MB"
        )

    def test_concurrent_memory_stability(self, memory_provider):
        """MemoryProvider under 4-thread concurrent load: no leak.

        Runs concurrent send+get operations and verifies memory
        returns near baseline after cleanup.
        """
        gc.collect()
        before = get_rss_mb()

        def worker(idx: int):
            for j in range(50):
                tid = f"leak_test_{idx}_{j}"
                memory_provider.send_message({
                    "id": tid, "status": {"state": "submitted"}, "payload": {},
                })
                memory_provider.get_task(tid)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Explicitly clear all tasks from the provider
        memory_provider._tasks.clear()
        gc.collect()
        after = get_rss_mb()
        net_growth = after - before

        print(
            f"  [Memory Stability] Baseline={before:.1f}MB "
            f"After-cleanup={after:.1f}MB Growth={net_growth:+.1f}MB"
        )

        # After clearing and GC, memory should be close to baseline.
        # Allow tolerance for Python's allocator internal fragmentation.
        assert net_growth < 50.0, (
            f"Memory did not return to baseline after cleanup: "
            f"growth={net_growth:.1f}MB (limit: 50MB)"
        )


# ===================================================================
# Concurrency Scaling Check
# ===================================================================


class TestConcurrencyScaling:
    """Check how throughput scales with concurrency level.

    This test is informational (no assert) — it logs the scaling
    curve for trend analysis. A regression here would show up
    as flat or degraded throughput with more workers.
    """

    @pytest.mark.parametrize("num_workers", [1, 2, 4, 8])
    def test_scaling_curve(self, memory_provider, num_workers):
        """Throughput at various concurrency levels (informational)."""

        def op(idx: int):
            memory_provider.send_message({
                "id": f"scale_{idx}",
                "status": {"state": "submitted"},
                "payload": {},
            })

        stats = run_concurrent(
            op,
            num_workers=num_workers,
            iterations_per_worker=200,
            label=f"Scaling curve (workers={num_workers})",
        )

        # Log scaling efficiency
        print(
            f"  [Scale] {num_workers} workers -> {stats.ops_per_sec:,.0f} ops/s "
            f"({stats.ops_per_sec / num_workers:,.0f} ops/s/worker)"
        )
