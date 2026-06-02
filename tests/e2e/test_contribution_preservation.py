#!/usr/bin/env python3
"""
E2E Test: Contribution Preservation Across Protocol Boundary

验证 AgentMesh 的贡献度元数据（source、attribution、task lineage）在
通过 A2A 协议传输时不丢失。这是 AgentMesh 的核心差异化特性。

测试前提: A2A Test Server 运行中（默认 localhost:8000）

Phase 14, Direction A (真实集成测试)
"""

import json
import os
import sys
import time
import uuid
import urllib.request
import urllib.error

SERVER_URL = os.environ.get("A2A_SERVER_URL", "http://localhost:8000")
A2A_ENDPOINT = f"{SERVER_URL}/a2a"


def _post(payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        A2A_ENDPOINT,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}"}
    except urllib.error.URLError as e:
        return {"error": f"Connection failed: {e.reason}"}


def _poll_task(task_id: str, timeout: int = 30) -> dict:
    """Poll A2A task until completion."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = {
            "jsonrpc": "2.0",
            "method": "tasks/get",
            "params": {"id": task_id},
            "id": 100,
        }
        result = _post(payload)
        if "error" not in result:
            state = result.get("result", {}).get("status", {}).get("state", "")
            if state in ("completed", "failed", "canceled"):
                return result
        time.sleep(0.5)
    return {"error": "Poll timeout"}


# ---------------------------------------------------------------------------
# Test 1: Source Attribution Preservation
# ---------------------------------------------------------------------------

def test_source_attribution_preserved():
    """验证 source 字段在 A2A 往返中保留"""
    task_id = f"e2e-source-{int(time.time())}"

    result = _post({
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "id": task_id,
            "message": {
                "role": "user",
                "parts": [{
                    "type": "text",
                    "text": "Echo back the metadata you received",
                }],
            },
            "metadata": {
                "source": "agentmesh-e2e-test",
                "agent": "bidirectional-fidelity-test",
                "session_id": str(uuid.uuid4()),
            },
        },
        "id": 1,
    })

    assert "error" not in result, f"Send failed: {result}"
    final = _poll_task(task_id)
    assert "error" not in final, f"Task did not complete: {final}"

    resp_json = json.dumps(final, ensure_ascii=False)
    assert "agentmesh-e2e-test" in resp_json, \
        f"Source attribution lost in A2A round-trip!\nResponse (truncated): {resp_json[:500]}"
    print("  ✅ Source attribution preserved through A2A boundary")


# ---------------------------------------------------------------------------
# Test 2: Task Lineage (Parent-Child) Preservation
# ---------------------------------------------------------------------------

def test_task_lineage_preserved():
    """验证 parent-child 任务关系在 A2A 中保留"""
    parent_id = f"e2e-parent-{int(time.time())}"
    child_id = f"e2e-child-{parent_id}"

    # Send parent task
    result = _post({
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "id": parent_id,
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "Parent task – create a subtask"}],
            },
        },
        "id": 2,
    })
    assert "error" not in result, f"Parent send failed: {result}"

    # Send child task referencing parent
    result = _post({
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "id": child_id,
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "Child task – depends on parent"}],
            },
            "parent_id": parent_id,
        },
        "id": 3,
    })
    assert "error" not in result, f"Child send failed: {result}"

    # Check child task for parent reference
    child_result = _post({
        "jsonrpc": "2.0",
        "method": "tasks/get",
        "params": {"id": child_id},
        "id": 4,
    })
    assert "error" not in child_result, f"Get child failed: {child_result}"

    child_data = json.dumps(child_result, ensure_ascii=False)
    assert parent_id in child_data, \
        f"Parent reference lost in child task!\nResponse: {child_data[:500]}"
    print("  ✅ Task lineage (parent-child) preserved in A2A")


# ---------------------------------------------------------------------------
# Test 3: Contribution Metadata Integrity
# ---------------------------------------------------------------------------

def test_contribution_metadata_integrity():
    """验证完整的贡献度元数据结构通过 A2A 后不变"""
    test_id = f"e2e-contrib-{int(time.time())}"
    contrib_metadata = {
        "contribution_id": test_id,
        "framework": "agentmesh",
        "version": "0.4.0",
        "source_agent": "test-runner",
        "target_agent": "a2a-test-server",
        "protocol": "A2A",
        "timestamp": time.time(),
        "tags": ["e2e", "fidelity", "contribution-preservation"],
    }

    result = _post({
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "id": test_id,
            "message": {
                "role": "user",
                "parts": [{
                    "type": "text",
                    "text": "Verify contribution metadata integrity",
                }],
            },
            "metadata": contrib_metadata,
        },
        "id": 5,
    })
    assert "error" not in result, f"Send failed: {result}"
    final = _poll_task(test_id)

    # Check each field survived
    resp_str = json.dumps(final, ensure_ascii=False)
    for key, value in contrib_metadata.items():
        str_val = str(value)
        assert str_val in resp_str, \
            f"Contribution field '{key}={str_val}' lost after A2A round-trip!\nResponse: {resp_str[:500]}"

    print("  ✅ All contribution metadata fields preserved (7/7 checked)")


# ---------------------------------------------------------------------------
# Run all
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("E2E: Contribution Preservation Test Suite")
    print(f"Server: {SERVER_URL}")
    print("=" * 60)
    print()

    tests = [
        ("Source Attribution", test_source_attribution_preserved),
        ("Task Lineage", test_task_lineage_preserved),
        ("Contribution Metadata", test_contribution_metadata_integrity),
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
    sys.exit(main())
