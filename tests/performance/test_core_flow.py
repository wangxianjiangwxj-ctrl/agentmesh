"""
Core flow stress tests for AgentMesh A2A provider.

Covers the primary message operations under increasing concurrency levels.
Each test measures throughput and latency for a specific operation type.

Operation types tested:
  - send_message: submit tasks to the provider
  - get_task: retrieve tasks by ID
  - cancel_task: cancel tasks by ID
  - mixed: concurrent combination of all three operations
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "sdk"))

from a2a_provider import MemoryProvider, A2AResult, A2AError

# ------------------------------------------------------------------
# Results directory
# ------------------------------------------------------------------
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "stress_results")


def _ensure_results_dir():
    os.makedirs(RESULTS_DIR, exist_ok=True)


def _write_json_report(name: str, data: dict):
    _ensure_results_dir()
    path = os.path.join(RESULTS_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_task(task_id: str, state: str = "submitted") -> dict:
    return {
        "id": task_id,
        "status": {"state": state},
        "payload": {"query": "stress test payload"},
        "metadata": {"source": "stress-test"},
    }


def _do_send(provider: MemoryProvider, task: dict) -> A2AResult:
    """Single send_message operation."""
    return provider.send_message(task)


def _do_get(provider: MemoryProvider, task_id: str) -> A2AResult:
    """Single get_task operation."""
    return provider.get_task(task_id)


def _do_cancel(provider: MemoryProvider, task_id: str) -> A2AResult:
    """Single cancel_task operation."""
    return provider.cancel_task(task_id)


def _run_concurrent(
    workers: int,
    tasks_per_worker: int,
    operation_fn,
    provider: MemoryProvider,
) -> list:
    """Run an operation across a thread pool and return per-call timing records."""
    # Pre-compute all arguments
    all_args = []
    for w in range(workers):
        for t in range(tasks_per_worker):
            tid = f"stress_{w}_{t}"
            all_args.append((tid,))

    records = []
    start_wall = time.perf_counter()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for tid, in all_args:
            future = pool.submit(operation_fn, provider, tid)
            futures[future] = tid

        for future in as_completed(futures):
            tid = futures[future]
            try:
                t0 = time.perf_counter()
                result = future.result()
                elapsed = time.perf_counter() - t0
                records.append({
                    "task_id": tid,
                    "success": result.success,
                    "elapsed_seconds": round(elapsed, 6),
                })
            except Exception as exc:
                records.append({
                    "task_id": tid,
                    "success": False,
                    "error": str(exc),
                })

    wall_elapsed = time.perf_counter() - start_wall
    total_ops = len(all_args)
    throughput = total_ops / wall_elapsed if wall_elapsed > 0 else 0
    success_count = sum(1 for r in records if r["success"])

    return {
        "workers": workers,
        "tasks_per_worker": tasks_per_worker,
        "total_operations": total_ops,
        "wall_elapsed_seconds": round(wall_elapsed, 4),
        "throughput_ops_per_sec": round(throughput, 2),
        "success_count": success_count,
        "failure_count": total_ops - success_count,
        "records": records,
    }


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

CONCURRENCY_LEVELS = [1, 5, 10, 20]
TASKS_PER_WORKER = 10


class TestSendMessageThroughput:
    """Stress test: provider.send_message throughput under concurrency."""

    @pytest.mark.parametrize("workers", CONCURRENCY_LEVELS)
    def test_send_message(self, workers):
        """Send N tasks to MemoryProvider with {workers} concurrent workers."""
        provider = MemoryProvider("stress-send")
        all_args = []
        for w in range(workers):
            for t in range(TASKS_PER_WORKER):
                tid = f"send_{w}_{t}"
                all_args.append(tid)

        records = []
        start = time.perf_counter()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for tid in all_args:
                task = _make_task(tid)
                future = pool.submit(_do_send, provider, task)
                futures[future] = tid

            for future in as_completed(futures):
                tid = futures[future]
                t0 = time.perf_counter()
                result = future.result()
                elapsed = time.perf_counter() - t0
                records.append({
                    "task_id": tid,
                    "success": result.success,
                    "elapsed_seconds": round(elapsed, 6),
                })
                # Assertion per iteration
                assert result.success is True, f"send_message failed for {tid}"

        wall = time.perf_counter() - start
        total = len(all_args)
        throughput = total / wall if wall > 0 else 0

        report = {
            "test": "send_message_throughput",
            "description": f"Send {total} tasks with {workers} concurrent workers",
            "workers": workers,
            "tasks_per_worker": TASKS_PER_WORKER,
            "total_operations": total,
            "wall_elapsed_seconds": round(wall, 4),
            "throughput_ops_per_sec": round(throughput, 2),
            "success_count": sum(1 for r in records if r["success"]),
            "failure_count": sum(1 for r in records if not r["success"]),
        }

        path = _write_json_report(
            f"stress_send_workers{workers}.json", report
        )
        print(f"\n  [stress] send_message workers={workers}: "
              f"{total} ops in {wall:.3f}s = {throughput:.0f} ops/s")
        print(f"  [stress] Report saved: {path}")


class TestGetTaskThroughput:
    """Stress test: provider.get_task throughput under concurrency."""

    @pytest.mark.parametrize("workers", CONCURRENCY_LEVELS)
    def test_get_task(self, workers):
        """Get N tasks from MemoryProvider with {workers} concurrent workers."""
        # Pre-populate tasks
        provider = MemoryProvider("stress-get")
        for w in range(workers):
            for t in range(TASKS_PER_WORKER):
                tid = f"get_{w}_{t}"
                provider.send_message(_make_task(tid))

        all_args = []
        for w in range(workers):
            for t in range(TASKS_PER_WORKER):
                tid = f"get_{w}_{t}"
                all_args.append(tid)

        records = []
        start = time.perf_counter()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for tid in all_args:
                future = pool.submit(_do_get, provider, tid)
                futures[future] = tid

            for future in as_completed(futures):
                tid = futures[future]
                t0 = time.perf_counter()
                result = future.result()
                elapsed = time.perf_counter() - t0
                records.append({
                    "task_id": tid,
                    "success": result.success,
                    "elapsed_seconds": round(elapsed, 6),
                })
                assert result.success is True, f"get_task failed for {tid}"
                assert result.data is not None, f"get_task returned no data for {tid}"
                assert result.data["id"] == tid, f"get_task returned wrong id for {tid}"

        wall = time.perf_counter() - start
        total = len(all_args)
        throughput = total / wall if wall > 0 else 0

        report = {
            "test": "get_task_throughput",
            "description": f"Get {total} tasks with {workers} concurrent workers",
            "workers": workers,
            "tasks_per_worker": TASKS_PER_WORKER,
            "total_operations": total,
            "wall_elapsed_seconds": round(wall, 4),
            "throughput_ops_per_sec": round(throughput, 2),
            "success_count": sum(1 for r in records if r["success"]),
            "failure_count": sum(1 for r in records if not r["success"]),
        }

        path = _write_json_report(
            f"stress_get_workers{workers}.json", report
        )
        print(f"\n  [stress] get_task workers={workers}: "
              f"{total} ops in {wall:.3f}s = {throughput:.0f} ops/s")
        print(f"  [stress] Report saved: {path}")


class TestCancelTaskThroughput:
    """Stress test: provider.cancel_task throughput under concurrency."""

    @pytest.mark.parametrize("workers", CONCURRENCY_LEVELS)
    def test_cancel_task(self, workers):
        """Cancel N tasks from MemoryProvider with {workers} concurrent workers."""
        # Pre-populate tasks
        provider = MemoryProvider("stress-cancel")
        for w in range(workers):
            for t in range(TASKS_PER_WORKER):
                tid = f"cancel_{w}_{t}"
                provider.send_message(_make_task(tid))

        all_args = []
        for w in range(workers):
            for t in range(TASKS_PER_WORKER):
                tid = f"cancel_{w}_{t}"
                all_args.append(tid)

        records = []
        start = time.perf_counter()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for tid in all_args:
                future = pool.submit(_do_cancel, provider, tid)
                futures[future] = tid

            for future in as_completed(futures):
                tid = futures[future]
                t0 = time.perf_counter()
                result = future.result()
                elapsed = time.perf_counter() - t0
                records.append({
                    "task_id": tid,
                    "success": result.success,
                    "elapsed_seconds": round(elapsed, 6),
                })
                assert result.success is True, f"cancel_task failed for {tid}"
                assert result.task_state == "canceled", \
                    f"cancel_task returned state {result.task_state} for {tid}"

        wall = time.perf_counter() - start
        total = len(all_args)
        throughput = total / wall if wall > 0 else 0

        report = {
            "test": "cancel_task_throughput",
            "description": f"Cancel {total} tasks with {workers} concurrent workers",
            "workers": workers,
            "tasks_per_worker": TASKS_PER_WORKER,
            "total_operations": total,
            "wall_elapsed_seconds": round(wall, 4),
            "throughput_ops_per_sec": round(throughput, 2),
            "success_count": sum(1 for r in records if r["success"]),
            "failure_count": sum(1 for r in records if not r["success"]),
        }

        path = _write_json_report(
            f"stress_cancel_workers{workers}.json", report
        )
        print(f"\n  [stress] cancel_task workers={workers}: "
              f"{total} ops in {wall:.3f}s = {throughput:.0f} ops/s")
        print(f"  [stress] Report saved: {path}")


class TestMixedOperationsThroughput:
    """Stress test: send, get, and cancel operations mixed under concurrency."""

    @pytest.mark.parametrize("workers", CONCURRENCY_LEVELS)
    def test_mixed_operations(self, workers):
        """Run a mix of send/get/cancel with {workers} concurrent workers."""
        provider = MemoryProvider("stress-mixed")

        # Pre-populate tasks for get/cancel operations
        for w in range(workers):
            for t in range(TASKS_PER_WORKER):
                tid = f"mixed_{w}_{t}"
                provider.send_message(_make_task(tid))

        ops = []
        # send ops: create new tasks
        for w in range(workers):
            for t in range(TASKS_PER_WORKER):
                tid = f"mixed_send_{w}_{t}"
                ops.append(("send", tid))
        # get ops: retrieve existing
        for w in range(workers):
            for t in range(TASKS_PER_WORKER):
                tid = f"mixed_{w}_{t}"
                ops.append(("get", tid))
        # cancel ops: cancel existing
        for w in range(workers):
            for t in range(TASKS_PER_WORKER):
                tid = f"mixed_{w}_{t}"
                ops.append(("cancel", tid))

        records = []
        start = time.perf_counter()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for op_type, tid in ops:
                if op_type == "send":
                    task = _make_task(tid)
                    future = pool.submit(_do_send, provider, task)
                elif op_type == "get":
                    future = pool.submit(_do_get, provider, tid)
                else:  # cancel
                    future = pool.submit(_do_cancel, provider, tid)
                futures[future] = (op_type, tid)

            for future in as_completed(futures):
                op_type, tid = futures[future]
                t0 = time.perf_counter()
                result = future.result()
                elapsed = time.perf_counter() - t0
                records.append({
                    "task_id": tid,
                    "operation": op_type,
                    "success": result.success,
                    "elapsed_seconds": round(elapsed, 6),
                })
                assert result.success is True, f"{op_type} failed for {tid}"
                if op_type == "cancel":
                    assert result.task_state == "canceled"

        wall = time.perf_counter() - start
        total = len(ops)
        throughput = total / wall if wall > 0 else 0

        # Breakdown by operation type
        by_op = {}
        for r_op_type in ("send", "get", "cancel"):
            matching = [r for r in records if r["operation"] == r_op_type]
            by_op[r_op_type] = {
                "count": len(matching),
                "success": sum(1 for r in matching if r["success"]),
            }

        report = {
            "test": "mixed_operations_throughput",
            "description": f"Mixed send/get/cancel ({total} ops) with "
                           f"{workers} concurrent workers",
            "workers": workers,
            "total_operations": total,
            "wall_elapsed_seconds": round(wall, 4),
            "throughput_ops_per_sec": round(throughput, 2),
            "success_count": sum(1 for r in records if r["success"]),
            "failure_count": sum(1 for r in records if not r["success"]),
            "breakdown_by_operation": by_op,
        }

        path = _write_json_report(
            f"stress_mixed_workers{workers}.json", report
        )
        print(f"\n  [stress] mixed operations workers={workers}: "
              f"{total} ops in {wall:.3f}s = {throughput:.0f} ops/s")
        print(f"  [stress] Report saved: {path}")


# ------------------------------------------------------------------
# Edge case tests
# ------------------------------------------------------------------

class TestCoreFlowEdgeCases:
    """Edge cases for core flow operations under stress."""

    @pytest.mark.parametrize("workers", [1, 5, 10])
    def test_send_duplicate_ids(self, workers):
        """Sending duplicate task IDs under concurrency should not corrupt state."""
        provider = MemoryProvider("stress-dup")
        tid = "dedup_target"

        # First send
        r = provider.send_message(_make_task(tid))
        assert r.success is True

        # Concurrent duplicate sends
        num_dupes = workers * 2
        records = []

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for i in range(num_dupes):
                task = _make_task(tid)
                future = pool.submit(_do_send, provider, task)
                futures[future] = i

            for future in as_completed(futures):
                t0 = time.perf_counter()
                result = future.result()
                elapsed = time.perf_counter() - t0
                records.append({
                    "attempt": futures[future],
                    "success": result.success,
                    "elapsed_seconds": round(elapsed, 6),
                })

        # The task should still be retrievable with original state
        get_r = provider.get_task(tid)
        assert get_r.success is True
        assert get_r.data["id"] == tid

        report = {
            "test": "send_duplicate_ids",
            "description": f"Send {num_dupes} duplicate task IDs with "
                           f"{workers} workers",
            "workers": workers,
            "duplicate_attempts": num_dupes,
            "total_operations": len(records),
        }
        _write_json_report(
            f"stress_dup_ids_workers{workers}.json", report
        )

    @pytest.mark.parametrize("workers", [1, 5, 10])
    def test_get_nonexistent_tasks(self, workers):
        """Getting nonexistent tasks should return errors (no crashes)."""
        provider = MemoryProvider("stress-nonexist")
        num_requests = workers * 5
        records = []

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for i in range(num_requests):
                nonexistent_id = f"nonexistent_{i}"
                future = pool.submit(_do_get, provider, nonexistent_id)
                futures[future] = nonexistent_id

            for future in as_completed(futures):
                tid = futures[future]
                t0 = time.perf_counter()
                result = future.result()
                elapsed = time.perf_counter() - t0
                records.append({
                    "task_id": tid,
                    "success": result.success,
                    "error_code": result.error.code if not result.success else None,
                    "elapsed_seconds": round(elapsed, 6),
                })
                assert result.success is False
                assert isinstance(result.error, A2AError)
                assert result.error.code == 404

        report = {
            "test": "get_nonexistent_tasks",
            "description": f"Get {num_requests} nonexistent tasks with "
                           f"{workers} workers",
            "workers": workers,
            "total_operations": num_requests,
            "all_returned_404": all(
                r.get("error_code") == 404 for r in records
            ),
        }
        _write_json_report(
            f"stress_nonexistent_workers{workers}.json", report
        )
