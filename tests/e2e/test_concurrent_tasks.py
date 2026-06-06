#!/usr/bin/env python3
"""
E2E Test: Concurrent Task Processing

验证 A2A Server 并发处理多个任务的能力。同时提交 N 个任务，
验证全部完成且结果可正确关联。

测试前提: A2A Test Server 运行中（默认 localhost:8000）

Phase 14, Direction A (真实集成测试)
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

SERVER_URL = os.environ.get("A2A_SERVER_URL", "http://localhost:8000")
A2A_ENDPOINT = f"{SERVER_URL}/a2a"
CONCURRENCY = int(os.environ.get("E2E_CONCURRENCY", "5"))


def _post(payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        A2A_ENDPOINT,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}"}
    except urllib.error.URLError as e:
        return {"error": f"Connection failed: {e.reason}"}


def _send_and_poll(task_index: int) -> dict:
    """Send a task and poll for completion. Returns result dict."""
    task_id = f"e2e-concurrent-{task_index}-{int(time.time())}"
    payload = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "id": task_id,
            "message": {
                "role": "user",
                "parts": [{
                    "type": "text",
                    "text": f"Concurrent test task #{task_index} at {time.time()}",
                }],
            },
            "metadata": {"index": task_index, "task_id": task_id},
        },
        "id": task_index,
    }

    send_result = _post(payload)
    if "error" in send_result:
        return {"task_id": task_id, "index": task_index, "error": send_result["error"]}

    # Poll (max 30s)
    deadline = time.time() + 30
    while time.time() < deadline:
        poll = {
            "jsonrpc": "2.0",
            "method": "tasks/get",
            "params": {"id": task_id},
            "id": task_index + 100,
        }
        resp = _post(poll)
        if "error" not in resp:
            state = resp.get("result", {}).get("status", {}).get("state", "")
            if state == "completed":
                return {"task_id": task_id, "index": task_index, "state": "completed"}
            elif state in ("failed", "canceled"):
                return {"task_id": task_id, "index": task_index, "state": state, "error": "Task did not succeed"}
        time.sleep(0.5)

    return {"task_id": task_id, "index": task_index, "error": "Poll timeout"}


# ---------------------------------------------------------------------------
# Test 1: Concurrent Task Submission
# ---------------------------------------------------------------------------

def test_concurrent_submission():
    """同时提交多个任务，所有任务应全部完成"""
    threads = []
    results = [None] * CONCURRENCY
    errors = []

    def _run(idx: int):
        try:
            results[idx] = _send_and_poll(idx)
        except Exception as e:
            errors.append(f"Thread {idx}: {e}")

    start = time.time()

    for i in range(CONCURRENCY):
        t = threading.Thread(target=_run, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    elapsed = time.time() - start
    completed = sum(1 for r in results if r and r.get("state") == "completed")
    failed = sum(1 for r in results if r and r.get("error"))

    total_checked = len(results)
    assert completed == total_checked, \
        f"Expected {total_checked} completed, got {completed} (failed={failed}, errors={errors})"

    # Verify all task IDs are unique
    task_ids = [r["task_id"] for r in results if r]
    assert len(set(task_ids)) == len(task_ids), "Duplicate task IDs detected!"

    print(f"  ✅ {total_checked}/{total_checked} concurrent tasks completed in {elapsed:.2f}s")
    print(f"     Avg {(elapsed / total_checked):.2f}s per task")
    print("     All task IDs unique: ✅")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print(f"E2E: Concurrent Task Processing ({CONCURRENCY} tasks)")
    print(f"Server: {SERVER_URL}")
    print("=" * 60)
    print()

    try:
        test_concurrent_submission()
        print(f"\n[PASS] All {CONCURRENCY} concurrent tasks passed")
        return 0
    except Exception as e:
        print(f"\n[FAIL] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
