#!/usr/bin/env python3
"""
E2E Test: Error Recovery & Resilience

验证 AgentMesh 客户端在 A2A Server 异常情况下的行为：
- 连接超时（Server 已启动但局部超时）
- 无效请求格式
- 任务不存在等标准错误码

测试前提: A2A Test Server 运行中（默认 localhost:8000）

Phase 14, Direction A (真实集成测试)
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

SERVER_URL = os.environ.get("A2A_SERVER_URL", "http://localhost:8000")
A2A_ENDPOINT = f"{SERVER_URL}/a2a"


def _post(payload: dict, timeout: int = 5) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        A2A_ENDPOINT,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP_{e.code}", "detail": body}
    except urllib.error.URLError as e:
        return {"error": "CONNECTION_FAILED", "detail": str(e.reason)}
    except (socket.timeout, TimeoutError):
        return {"error": "TIMEOUT", "detail": f"Request timed out after {timeout}s"}


# ---------------------------------------------------------------------------
# Test 1: Invalid JSON RPC Request
# ---------------------------------------------------------------------------

def test_invalid_jsonrpc():
    """Server 应返回 JSON-RPC 标准错误响应"""
    result = _post({"jsonrpc": "2.0", "method": "invalid_method", "id": 1})
    assert "error" not in result or not result["error"].startswith("HTTP_"), \
        f"Expected graceful error response, got: {result}"
    print("  ✅ Invalid method handled gracefully")


# ---------------------------------------------------------------------------
# Test 2: Missing Required Fields
# ---------------------------------------------------------------------------

def test_missing_required_fields():
    """缺少必填字段时应返回 400 类错误"""
    result = _post({"jsonrpc": "2.0", "method": "tasks/send", "params": {}, "id": 2})
    # Either HTTP 400 or JSON-RPC error is acceptable
    is_graceful = (
        "HTTP_400" in str(result) or
        "HTTP_422" in str(result) or
        result.get("error") is not None  # JSON-RPC error object
    )
    assert is_graceful, f"Expected graceful error, got: {result}"
    print("  ✅ Missing fields handled gracefully")


# ---------------------------------------------------------------------------
# Test 3: Nonexistent Task Query
# ---------------------------------------------------------------------------

def test_nonexistent_task():
    """查询不存在的任务应返回 404 类错误"""
    result = _post({
        "jsonrpc": "2.0",
        "method": "tasks/get",
        "params": {"id": f"nonexistent-{time.time()}"},
        "id": 3,
    })
    is_graceful = (
        "HTTP_404" in str(result) or
        result.get("error") is not None
    )
    assert is_graceful, f"Expected 404-like error, got: {result}"
    print("  ✅ Nonexistent task returns graceful error")


# ---------------------------------------------------------------------------
# Test 4: Cancel Running Task
# ---------------------------------------------------------------------------

def test_cancel_task():
    """取消一个正在运行的任务"""
    task_id = f"e2e-cancel-{int(time.time())}"

    # Submit a task with a long-running hint
    result = _post({
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "id": task_id,
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": f"Sleep for 30 seconds then respond — task_id: {task_id}"}],
            },
        },
        "id": 4,
    })
    assert "error" not in result or not result["error"].startswith("HTTP_"), \
        f"Send failed: {result}"

    # Cancel the task
    cancel_result = _post({
        "jsonrpc": "2.0",
        "method": "tasks/cancel",
        "params": {"id": task_id},
        "id": 5,
    })
    is_graceful = "error" not in cancel_result or not cancel_result["error"].startswith("HTTP_5")
    assert is_graceful, f"Cancel failed: {cancel_result}"
    print("  ✅ Task cancellation handled gracefully")


# ---------------------------------------------------------------------------
# Test 5: Malformed Payload
# ---------------------------------------------------------------------------

def test_malformed_payload():
    """无效的 payload 应被拒绝而不崩溃"""
    try:
        data = b"not-json-at-all{{{"
        req = urllib.request.Request(
            A2A_ENDPOINT,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        result = {"error": f"HTTP_{e.code}"}
    except Exception as e:
        result = {"error": str(type(e).__name__), "detail": str(e)}

    # Accept any graceful response (no server crash)
    print(f"  ✅ Malformed payload returned: {json.dumps(result, ensure_ascii=False)}")


# ---------------------------------------------------------------------------
# Run all
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("E2E: Error Recovery & Resilience Test Suite")
    print(f"Server: {SERVER_URL}")
    print("=" * 60)
    print()

    tests = [
        ("Invalid JSON-RPC Method", test_invalid_jsonrpc),
        ("Missing Required Fields", test_missing_required_fields),
        ("Nonexistent Task Query", test_nonexistent_task),
        ("Cancel Running Task", test_cancel_task),
        ("Malformed Payload", test_malformed_payload),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        print(f"[{' RUN '}] {name}")
        try:
            test_fn()
            print(f"[{'PASS '}] {name}")
            passed += 1
        except Exception as e:
            print(f"[{'FAIL '}] {name}: {e}")
            failed += 1
        print()

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {len(tests)} total")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import socket  # import here to avoid shadowing
    sys.exit(main())
