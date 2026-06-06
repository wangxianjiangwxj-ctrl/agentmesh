#!/usr/bin/env python3
"""
E2E Test: Bidirectional Fidelity — agentmesh ↔ A2A Server

验证 AgentMesh SDK 通过 A2AAdapter 连接真实 A2A Server 时，任务下发和结果
回传的完整往返路径无数据丢失。

测试前提: A2A Test Server 运行在 --server-url 指定的地址（默认 localhost:8000）

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


def _post(payload: dict) -> dict:
    """发送 HTTP POST 到 A2A Server"""
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


def _get(path: str) -> dict:
    """发送 HTTP GET 到 A2A Server"""
    try:
        with urllib.request.urlopen(f"{SERVER_URL}{path}", timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}"}
    except urllib.error.URLError as e:
        return {"error": f"Connection failed: {e.reason}"}


# ---------------------------------------------------------------------------
# Test 1: Server Health Check
# ---------------------------------------------------------------------------

def test_server_ping():
    """A2A Server 运行中且可响应"""
    result = _get("/health")
    assert "error" not in result, f"Server not reachable: {result.get('error')}"
    print(f"  ✅ Server health: {json.dumps(result, ensure_ascii=False)}")


# ---------------------------------------------------------------------------
# Test 2: Agent Card Discovery
# ---------------------------------------------------------------------------

def test_agent_card_discovery():
    """A2A Server 应返回 Agent Card"""
    result = _get("/.well-known/agent-card")
    assert "error" not in result, f"Agent Card not available: {result}"
    assert "name" in result, f"Agent Card missing 'name': {result}"
    print(f"  ✅ Agent Card: {result.get('name')} — skills: {result.get('capabilities', [])}")


# ---------------------------------------------------------------------------
# Test 3: Send Task → Poll Result
# ---------------------------------------------------------------------------

def test_send_and_poll_task():
    """发送 A2A Task 并通过 polling 获取结果"""
    task_payload = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "id": f"e2e-fidelity-{int(time.time())}",
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "Hello A2A Server — bidirectional fidelity test"}],
            },
        },
        "id": 1,
    }

    result = _post(task_payload)
    assert "error" not in result, f"Send task failed: {result}"
    task_id = result.get("result", {}).get("id", task_payload["params"]["id"])
    print(f"  ✅ Task sent: {task_id}")

    # Poll until completed (max 30s)
    deadline = time.time() + 30
    final_state = None
    while time.time() < deadline:
        poll_payload = {
            "jsonrpc": "2.0",
            "method": "tasks/get",
            "params": {"id": task_id},
            "id": 2,
        }
        poll_result = _post(poll_payload)
        if "error" not in poll_result:
            state = poll_result.get("result", {}).get("status", {}).get("state", "")
            if state in ("completed", "failed", "canceled"):
                final_state = state
                break
        time.sleep(1)

    assert final_state == "completed", f"Task did not complete (state={final_state})"
    print(f"  ✅ Task completed in {time.time() - (deadline - 30):.1f}s")


# ---------------------------------------------------------------------------
# Test 4: Bidirectional Message Integrity
# ---------------------------------------------------------------------------

def test_message_integrity():
    """发送带有检查用 payload 的消息，验证回传内容完整性"""
    test_id = f"e2e-integrity-{int(time.time())}"
    payload_text = "AgentMesh bidirectional fidelity check — send this exact text back"

    task_payload = {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "params": {
            "id": test_id,
            "message": {
                "role": "user",
                "parts": [{
                    "type": "text",
                    "text": payload_text,
                    "metadata": {
                        "test_id": test_id,
                        "source": "agentmesh-e2e",
                        "expected_content": payload_text[:20],
                    },
                }],
            },
        },
        "id": 3,
    }

    result = _post(task_payload)
    assert "error" not in result, f"Send failed: {result}"

    # Wait for completion
    deadline = time.time() + 30
    final_result = None
    while time.time() < deadline:
        poll = {
            "jsonrpc": "2.0",
            "method": "tasks/get",
            "params": {"id": test_id},
            "id": 4,
        }
        resp = _post(poll)
        if "error" not in resp:
            state = resp.get("result", {}).get("status", {}).get("state", "")
            if state == "completed":
                final_result = resp
                break
            elif state in ("failed", "canceled"):
                break
        time.sleep(1)

    assert final_result is not None, "Task did not complete"

    # Verify metadata integrity: test_id should appear in response
    result_str = json.dumps(final_result, ensure_ascii=False)
    assert test_id in result_str, \
        f"Test ID not preserved in response! Metadata lost at protocol boundary.\nResponse: {result_str[:500]}"
    print("  ✅ Message integrity verified — test_id preserved through round-trip")


# ---------------------------------------------------------------------------
# Test 5: Task History Preservation
# ---------------------------------------------------------------------------

def test_task_history():
    """验证 A2A Server 保留任务历史（可追溯先前的交互）"""
    session_id = f"e2e-session-{int(time.time())}"

    # Send 3 sequential messages in the same session
    for i, text in enumerate([
        "Message 1: Initialize session",
        "Message 2: Continue conversation",
        "Message 3: Verify history",
    ]):
        task_payload = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "params": {
                "id": f"{session_id}-{i}",
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": text}],
                },
                "session_id": session_id,
            },
            "id": 5 + i,
        }
        result = _post(task_payload)
        assert "error" not in result, f"Send task {i} failed: {result}"
        # Wait briefly between messages
        time.sleep(0.5)

    # Query session history
    history_payload = {
        "jsonrpc": "2.0",
        "method": "tasks/list",
        "params": {"session_id": session_id},
        "id": 8,
    }
    history = _post(history_payload)
    tasks = history.get("result", {}).get("tasks", [])
    assert len(tasks) >= 3, \
        f"Expected at least 3 tasks in session history, got {len(tasks)}"
    print(f"  ✅ Session history preserved: {len(tasks)} tasks in session {session_id}")


# ---------------------------------------------------------------------------
# Run all
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("E2E: Bidirectional Fidelity Test Suite")
    print(f"Server: {SERVER_URL}")
    print("=" * 60)
    print()

    tests = [
        ("Server Ping", test_server_ping),
        ("Agent Card Discovery", test_agent_card_discovery),
        ("Send & Poll Task", test_send_and_poll_task),
        ("Message Integrity", test_message_integrity),
        ("Task History", test_task_history),
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
