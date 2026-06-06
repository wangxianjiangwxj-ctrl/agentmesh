"""
Performance test fixtures and helper utilities for AgentMesh A2A provider benchmarks.

Provides:
  - Provider instances (memory_provider, facade, http_provider)
  - Timing utilities (measure_latency, timed_task)
  - Concurrent execution helpers (run_concurrent)
  - Resource monitoring (get_rss_mb, cpu_percent)
  - Standard benchmark scenarios (sample_task_full, sample_task_minimal)
  - Shared thresholds config
"""

from __future__ import annotations

import json
import math
import os
import resource
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

# Add SDK to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agentmesh"))

from agentmesh.a2a_provider import (
    A2AFacade,
    A2AProvider,
    A2ATaskManager,
    MemoryProvider,
)

# ===================================================================
# Threshold Configuration
# ===================================================================


@dataclass
class LatencyThresholds:
    """Pass/fail latency thresholds (in seconds).

    These are baseline expectations for the in-memory provider on
    a reasonably fast machine (M1 Mac mini or equivalent).
    Adjust for CI runners or constrained environments.
    """
    # MemoryProvider — pure in-memory, no I/O
    memory_send_mean: float = 0.0005   # 500 us
    memory_send_p99: float = 0.002     # 2 ms
    memory_get_mean: float = 0.0003    # 300 us
    memory_get_p99: float = 0.001      # 1 ms
    memory_cancel_mean: float = 0.0003 # 300 us
    memory_cancel_p99: float = 0.001   # 1 ms

    # A2AFacade (wraps MemoryProvider + TaskManager)
    facade_send_mean: float = 0.001    # 1 ms
    facade_send_p99: float = 0.005     # 5 ms
    facade_get_mean: float = 0.0005    # 500 us
    facade_get_p99: float = 0.002      # 2 ms

    # HttpProvider (localhost, needs server) — much looser
    http_ping_mean: float = 0.050      # 50 ms (including FastAPI overhead)
    http_send_mean: float = 0.050      # 50 ms
    http_get_mean: float = 0.050       # 50 ms

    # Success rate thresholds (must be >= this ratio)
    min_success_rate: float = 0.99     # 99% of operations must succeed


@dataclass
class ThroughputThresholds:
    """Pass/fail throughput baselines.

    Values are for a single-threaded/4-thread in-memory test on
    a modern dev machine. Adjust for CI/constrained environments.
    """
    # MemoryProvider: ops/sec under sequential load
    memory_send_tps_min: float = 5000      # at least 5K send ops/sec
    memory_get_tps_min: float = 8000       # at least 8K get ops/sec
    memory_mixed_tps_min: float = 4000     # at least 4K mixed ops/sec

    # MemoryProvider: ops/sec under concurrent load
    memory_concurrent_tps_min: float = 20000  # at least 20K ops/sec (4 workers)

    # A2AFacade: sequential
    facade_send_tps_min: float = 3000     # at least 3K ops/sec
    facade_get_tps_min: float = 5000      # at least 5K ops/sec


@dataclass
class ResourceThresholds:
    """Resource usage thresholds (memory & CPU)."""
    memory_max_mb: float = 200   # max resident set size under test load
    memory_growth_mb: float = 50 # allowable growth from baseline


# Singleton thresholds — shared across test modules
LATENCY_THRESHOLDS = LatencyThresholds()
THROUGHPUT_THRESHOLDS = ThroughputThresholds()
RESOURCE_THRESHOLDS = ResourceThresholds()


# ===================================================================
# Fixtures — Provider Instances
# ===================================================================


@pytest.fixture(scope="module")
def memory_provider() -> MemoryProvider:
    """A fresh MemoryProvider for latency/throughput tests.

    Module-scoped so all tests in a file share the same instance,
    avoiding repeated construction overhead in benchmarks.
    """
    return MemoryProvider("perf-memory")


@pytest.fixture(scope="module")
def facade() -> A2AFacade:
    """A fresh A2AFacade wrapping a MemoryProvider + TaskManager.

    Module-scoped for shared usage within a test file.
    """
    provider = MemoryProvider("perf-facade")
    return A2AFacade(provider=provider, task_manager=A2ATaskManager())


@pytest.fixture(scope="module")
def http_provider():
    """HttpProvider pointing at an auto-started local A2A server.

    Uses module-scoped setup/teardown: starts the server once
    before all tests in the module and tears it down after.

    This fixture is slower (~2s startup) and only available when
    FastAPI/uvicorn are installed.  Skip tests that need it if
    the server cannot start.
    """
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        pytest.skip("FastAPI/uvicorn not available; skipping HTTP provider tests")

    port = _find_free_port()
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "agentmesh.a2a_server", "server", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for server to be ready
    _wait_for_server(port, timeout=10.0)

    from agentmesh.a2a_server import HttpProvider

    provider = HttpProvider(f"http://localhost:{port}", name="perf-http")

    yield provider

    # Teardown
    server_proc.terminate()
    try:
        server_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server_proc.kill()


# ===================================================================
# Fixtures — Sample Tasks
# ===================================================================


@pytest.fixture
def sample_task_full() -> dict:
    """A realistic task payload — full metadata."""
    return {
        "id": "perf_task_{}".format(int(time.time() * 1_000_000)),
        "status": {"state": "submitted"},
        "payload": {
            "query": "What is the weather in Shanghai today? "
                     "Provide a detailed forecast including temperature, "
                     "humidity, and chance of rain.",
            "max_tokens": 1024,
            "temperature": 0.7,
        },
        "metadata": {
            "source": "perf-test",
            "version": "1.0",
            "priority": "normal",
            "trace_id": "perf-trace-001",
        },
    }


@pytest.fixture
def sample_task_minimal() -> dict:
    """A minimal task payload — only required fields."""
    return {
        "id": "perf_mini_{}".format(int(time.time() * 1_000_000)),
        "status": {"state": "submitted"},
        "payload": {},
    }


@pytest.fixture
def sample_task_completed() -> dict:
    """A task that is already in completed state."""
    return {
        "id": "perf_compl_{}".format(int(time.time() * 1_000_000)),
        "status": {"state": "completed"},
        "payload": {},
        "result": {"data": "done"},
    }


# ===================================================================
# Timing Utilities
# ===================================================================


@dataclass
class TimingStats:
    """Aggregated timing statistics."""
    count: int = 0
    total: float = 0.0
    mean: float = 0.0
    median: float = 0.0
    p99: float = 0.0
    min: float = 0.0
    max: float = 0.0
    stddev: float = 0.0
    ops_per_sec: float = 0.0
    latencies: List[float] = field(default_factory=list)

    @classmethod
    def compute(cls, latencies: List[float]) -> TimingStats:
        """Compute statistics from a list of latencies (seconds)."""
        if not latencies:
            return cls()
        n = len(latencies)
        total = sum(latencies)
        sorted_lats = sorted(latencies)
        return cls(
            count=n,
            total=total,
            mean=total / n,
            median=sorted_lats[n // 2] if n % 2 else
                   (sorted_lats[n // 2 - 1] + sorted_lats[n // 2]) / 2,
            p99=sorted_lats[min(int(n * 0.99), n - 1)],
            min=sorted_lats[0],
            max=sorted_lats[-1],
            stddev=statistics.stdev(latencies) if n > 1 else 0.0,
            ops_per_sec=n / total if total > 0 else 0.0,
            latencies=sorted_lats,
        )


def measure_latency(
    fn: Callable[[], Any],
    iterations: int = 1000,
    warmup: int = 100,
    label: str = "",
) -> TimingStats:
    """Measure latencies of a callable.

    Args:
        fn: Zero-argument callable to benchmark.
        iterations: Number of timed iterations.
        warmup: Number of warmup iterations (not counted).
        label: Optional label for logging.

    Returns:
        TimingStats with mean/median/p99/stddev/ops_per_sec.
    """
    # Warmup
    for _ in range(warmup):
        fn()

    # Timed iterations
    latencies: List[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - t0
        latencies.append(elapsed)

    stats = TimingStats.compute(latencies)
    if label:
        print(
            f"  [{label}] mean={stats.mean*1e6:.1f}us "
            f"p99={stats.p99*1e6:.1f}us "
            f"median={stats.median*1e6:.1f}us "
            f"stddev={stats.stddev*1e6:.1f}us "
            f"ops/s={stats.ops_per_sec:,.0f}"
        )
    return stats


def run_concurrent(
    fn: Callable[[int], Any],
    num_workers: int = 4,
    iterations_per_worker: int = 100,
    label: str = "",
) -> TimingStats:
    """Execute a callable concurrently and collect latency stats.

    The callable receives a unique index per invocation so it can
    generate distinct task IDs.

    Args:
        fn: Callable that takes an int index and returns anything.
        num_workers: Number of concurrent threads.
        iterations_per_worker: Iterations per thread.
        label: Optional label for logging.

    Returns:
        TimingStats aggregated across all workers.
    """
    total_iterations = num_workers * iterations_per_worker
    latencies: List[float] = []
    lock = threading.Lock()

    def worker(worker_id: int):
        local_lats: List[float] = []
        base = worker_id * iterations_per_worker
        for i in range(iterations_per_worker):
            idx = base + i
            t0 = time.perf_counter()
            fn(idx)
            elapsed = time.perf_counter() - t0
            local_lats.append(elapsed)
        with lock:
            latencies.extend(local_lats)

    threads = [
        threading.Thread(target=worker, args=(wid,))
        for wid in range(num_workers)
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stats = TimingStats.compute(latencies)
    if label:
        print(
            f"  [{label}] workers={num_workers} total={total_iterations} "
            f"mean={stats.mean*1e6:.1f}us "
            f"p99={stats.p99*1e6:.1f}us "
            f"ops/s={stats.ops_per_sec:,.0f}"
        )
    return stats


# ===================================================================
# Resource Monitoring
# ===================================================================


def get_rss_mb() -> float:
    """Return current resident set size (RSS) in megabytes.

    Handles platform differences:
    - macOS (Darwin): ru_maxrss is in bytes
    - Linux: ru_maxrss is in kilobytes
    """
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    import sys as _sys
    if _sys.platform == "darwin":
        # macOS: ru_maxrss is in bytes
        return raw / (1024.0 * 1024.0)
    # Linux and others: ru_maxrss is in kilobytes
    return raw / 1024.0


def measure_memory_usage(
    fn: Callable[[], Any],
    label: str = "",
) -> Tuple[float, float]:
    """Measure RSS before and after executing fn.

    Returns:
        (before_mb, after_mb) tuple.
    """
    # Force garbage collection before measurement
    import gc
    gc.collect()

    before = get_rss_mb()
    fn()
    gc.collect()
    after = get_rss_mb()

    if label:
        growth = after - before
        print(f"  [{label}] RSS: {before:.1f}MB -> {after:.1f}MB (delta={growth:+.1f}MB)")

    return before, after


# ===================================================================
# Internal Helpers
# ===================================================================


def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_server(url_or_port: Any, timeout: float = 10.0) -> None:
    """Poll the A2A server's /ping endpoint until it responds."""
    import urllib.error
    import urllib.request

    if isinstance(url_or_port, int):
        base = f"http://localhost:{url_or_port}"
    else:
        base = url_or_port.rstrip("/")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(f"{base}/ping", method="GET")
            with urllib.request.urlopen(req, timeout=1) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(0.1)

    raise RuntimeError(f"Server at {base} did not become ready within {timeout}s")
