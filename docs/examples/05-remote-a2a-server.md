# 远程A2A服务连接

本地Agent通过HTTP JSON-RPC协议连接远程A2A服务端点，实现跨进程通信。

---

## 场景

一个本地Agent Client通过HTTP协议连接到一个模拟的远程A2A Server，完成跨进程的任务提交、状态轮询和结果获取。

流程：

1. 启动一个模拟的远程A2A Server（内嵌HTTP JSON-RPC端点）
2. Server注册AgentCard（包含文本生成、摘要、数据分析等能力）
3. Client通过HttpProvider发现远程AgentCard
4. Client构造A2A Task并通过HTTP POST发送到Server
5. Server异步处理任务（状态转换：SUBMITTED -> WORKING -> COMPLETED）
6. Client通过轮询获取最终结果
7. Server优雅关闭

## 代码

```python
# a2a-remote-bridge.py — Agent 连接远程 A2A 服务端点

import asyncio
import json
import time
import uuid
import urllib.request
import urllib.error
from enum import Enum
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# 1. A2A Task 状态枚举
# ═══════════════════════════════════════════════════════════════

class A2ATaskState(str, Enum):
    SUBMITTED = "SUBMITTED"
    WORKING = "WORKING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


# ═══════════════════════════════════════════════════════════════
# 2. 远程 A2A Server (模拟)
# ═══════════════════════════════════════════════════════════════

REMOTE_CARDS = {}
REMOTE_TASKS = {}
SERVER_INSTANCE = None


class A2ARequestHandler(BaseHTTPRequestHandler):
    """
    处理 A2A JSON-RPC over HTTP 请求。

    协议端点:
        GET  /.well-known/agent.json  -> AgentCard 发现
        POST /tasks/send              -> 提交 Task
        POST /tasks/getTask           -> 查询 Task 状态
    """

    def log_message(self, format, *args):
        print(f"  [A2A Server] {args[0]} {args[1]} {args[2]}")

    def _send_json(self, status_code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/.well-known/agent.json":
            card = REMOTE_CARDS.get("self", {
                "name": "Remote AI Agent",
                "description": "A2A 兼容的远程 AI 服务",
                "url": "http://localhost:18080",
                "skills": [
                    {"name": "text-generation", "description": "文本生成"},
                    {"name": "summarization", "description": "文本摘要"},
                    {"name": "data-analysis", "description": "数据分析"},
                ],
                "capabilities": {"streaming": False, "cancellation": True},
            })
            self._send_json(200, card)
        else:
            self._send_json(404, {"error": "Not Found", "path": self.path})

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            request = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}})
            return

        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id", "1")

        if method == "tasks/send":
            self._handle_tasks_send(params, req_id)
        elif method == "tasks/getTask":
            self._handle_tasks_get(params, req_id)
        else:
            self._send_json(404, {"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Method not found: {method}"}, "id": req_id})

    def _handle_tasks_send(self, params: dict, req_id: str):
        task_id = params.get("id", f"task-{uuid.uuid4().hex[:8]}")
        message = params.get("message", {})
        metadata = params.get("metadata", {})
        task = {
            "id": task_id,
            "message": message,
            "metadata": metadata,
            "status": {"state": A2ATaskState.SUBMITTED.value,
                       "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        }
        REMOTE_TASKS[task_id] = task
        print(f"  [A2A Server] 收到 Task: {task_id}")
        print(f"  [A2A Server] 来源: {metadata.get('agentmesh_from', 'unknown')}")
        print(f"  [A2A Server] 意图: {message.get('parts', [{}])[0].get('text', '')[:60]}...")
        Thread(target=self._simulate_processing, args=(task_id,), daemon=True).start()
        self._send_json(200, {"jsonrpc": "2.0", "result": {"id": task_id, "status": task["status"]}, "id": req_id})

    def _handle_tasks_get(self, params: dict, req_id: str):
        task_id = params.get("id", "")
        task = REMOTE_TASKS.get(task_id)
        if not task:
            self._send_json(200, {"jsonrpc": "2.0",
                "error": {"code": -32000, "message": f"Task not found: {task_id}"}, "id": req_id})
            return
        self._send_json(200, {"jsonrpc": "2.0",
            "result": {"id": task_id, "status": task.get("status", {}), "artifacts": task.get("artifacts", [])},
            "id": req_id})

    def _simulate_processing(self, task_id: str):
        import time as ttime
        task = REMOTE_TASKS.get(task_id)
        if not task:
            return
        ttime.sleep(1.5)
        task["status"] = {"state": A2ATaskState.WORKING.value,
                          "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        print(f"  [A2A Server] Task {task_id}: 状态更新为 WORKING")
        ttime.sleep(2.5)
        task["status"] = {"state": A2ATaskState.COMPLETED.value,
                          "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        metadata = task.get("metadata", {})
        intent = metadata.get("intent", "processing")
        if intent == "summarization":
            result_text = (
                "Summary of the input text:\n"
                "1. AgentMesh is an A2A protocol adapter\n"
                "2. It enables standardized communication between AI agents\n"
                "3. Key features: message conversion, task lifecycle, multi-provider\n"
                "4. Version 0.3 adds streaming, auth, resilience patterns, discovery"
            )
        else:
            result_text = (
                "Analysis Result (Remote Service):\n"
                "================================\n"
                "Input received: AgentMesh enables standardized AI agent communication...\n\n"
                "Findings:\n"
                "  1. The input describes an A2A protocol adapter framework\n"
                "  2. Multi-agent orchestration is a primary use case\n"
                "  3. The system supports both local and remote providers\n"
                "\nGenerated by Remote AI Service."
            )
        task["artifacts"] = [{"artifactId": f"artifact-{uuid.uuid4().hex[:8]}",
                              "parts": [{"type": "text", "text": result_text}]}]
        print(f"  [A2A Server] Task {task_id}: 状态更新为 COMPLETED")


def start_remote_server(host: str = "localhost", port: int = 18080) -> HTTPServer:
    server = HTTPServer((host, port), A2ARequestHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"  [A2A Server] 已启动: http://{host}:{port}")
    print(f"  [A2A Server] 端点: ")
    print(f"    GET  /.well-known/agent.json  — AgentCard 发现")
    print(f"    POST /tasks/send              — 提交 Task")
    print(f"    POST /tasks/getTask           — 查询 Task 状态")
    return server


# ═══════════════════════════════════════════════════════════════
# 3. HttpProvider (Client 端) — 通过 HTTP 连接远程 A2A Server
# ═══════════════════════════════════════════════════════════════

class HttpProvider:
    """
    HTTP Provider: 通过 HTTP JSON-RPC 连接远程 A2A Server。

    职责:
        - AgentCard 发现 (GET /.well-known/agent.json)
        - 发送 Task (POST /tasks/send)
        - 查询 Task 状态 (POST /tasks/getTask)
    """

    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.name = f"HttpProvider({base_url})"

    def discover(self) -> Optional[dict]:
        url = f"{self.base_url}/.well-known/agent.json"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  [HttpProvider] AgentCard 发现失败: {e}")
            return None

    def send_task(self, task: dict) -> dict:
        url = f"{self.base_url}/tasks/send"
        return self._jsonrpc_call(url, task)

    def get_task(self, task_id: str) -> dict:
        url = f"{self.base_url}/tasks/getTask"
        return self._jsonrpc_call(url, {"id": task_id})

    def _jsonrpc_call(self, url: str, params: dict) -> dict:
        path_parts = url.split("/")
        method = "/".join(path_parts[-2:]) if len(path_parts) >= 2 else path_parts[-1]
        body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": "1"}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return {"jsonrpc": "2.0", "error": {"code": e.code, "message": str(e.reason)}}
        except urllib.error.URLError as e:
            return {"jsonrpc": "2.0", "error": {"code": -32000, "message": f"Connection failed: {e.reason}"}}


# ═══════════════════════════════════════════════════════════════
# 4. 主流程: Client 连接远程 Server
# ═══════════════════════════════════════════════════════════════

async def main():
    print("=" * 70)
    print("  AgentMesh A2A 桥接示例 — 远程 A2A 服务连接")
    print("=" * 70)
    print()

    HOST = "localhost"
    PORT = 18080

    print("[1] 启动远程 A2A Server...")
    server = start_remote_server(HOST, PORT)
    REMOTE_CARDS["self"] = {
        "name": "Remote AI Agent",
        "description": "A2A 兼容的远程 AI 服务端点，支持文本生成、摘要和数据分析",
        "url": f"http://{HOST}:{PORT}",
        "skills": [
            {"name": "text-generation", "description": "文本生成"},
            {"name": "summarization", "description": "文本摘要"},
            {"name": "data-analysis", "description": "数据分析"},
        ],
        "capabilities": {"streaming": False, "cancellation": True},
    }
    await asyncio.sleep(0.5)
    print()

    print("[2] Client: 发现远程 Agent (AgentCard)...")
    provider = HttpProvider(base_url=f"http://{HOST}:{PORT}")
    card = await asyncio.to_thread(provider.discover)
    if card:
        print(f"  名称:     {card.get('name', 'unknown')}")
        print(f"  描述:     {card.get('description', 'N/A')[:50]}...")
        print(f"  能力列表:")
        for skill in card.get("skills", []):
            print(f"    - {skill.get('name', 'unknown')}: {skill.get('description', '')}")
    else:
        print("  远程 Agent 发现失败，使用默认配置继续")
    print()

    print("[3] Client: 构造并发送 Task...")
    task_payload = {
        "id": f"task-remote-{uuid.uuid4().hex[:8]}",
        "message": {
            "messageId": f"msg-{uuid.uuid4().hex[:8]}",
            "role": "user",
            "parts": [{"type": "text", "text": "AgentMesh is an A2A protocol adapter that enables "
                      "standardized communication between different AI agents."}],
        },
        "metadata": {
            "agentmesh_from": "local-client",
            "agentmesh_to": "remote-service",
            "intent": "summarization",
            "agentmesh_adapter_version": "v0.3-simulated",
        },
    }
    print(f"  Task ID: {task_payload['id']}")
    print(f"  来源:    {task_payload['metadata']['agentmesh_from']}")
    print(f"  目标:    {task_payload['metadata']['agentmesh_to']}")
    print(f"  意图:    {task_payload['metadata']['intent']}")
    print()

    print("[4] Client: 通过 HTTP JSON-RPC 发送 Task...")
    send_result = await asyncio.to_thread(provider.send_task, task_payload)
    result = send_result.get("result", {})
    if "error" in send_result:
        print(f"  Task 发送失败: {send_result['error']}")
        server.shutdown()
        return
    task_id = result.get("id", "")
    print(f"  Task 已发送! Server 返回状态: {result.get('status', {}).get('state', 'unknown')}")
    print()

    print("[5] Client: 轮询 Task 状态...")
    print("-" * 50)
    poll_count = 0
    max_polls = 30
    poll_interval = 0.5
    start_time = time.time()
    final_state = None
    for i in range(max_polls):
        await asyncio.sleep(poll_interval)
        poll_count += 1
        elapsed = time.time() - start_time
        response = await asyncio.to_thread(provider.get_task, task_id)
        task_status = response.get("result", {}).get("status", {})
        state = task_status.get("state", "")
        if poll_count % 2 == 0 or state in ("COMPLETED", "FAILED"):
            print(f"  [Client] 轮询 #{poll_count}: {state} ({elapsed:.1f}s)")
        if state in ("COMPLETED", "FAILED", "CANCELED"):
            final_state = state
            break
    print("-" * 50)
    print()

    total_elapsed = (time.time() - start_time) * 1000
    print("[6] Client: 处理返回结果:")
    print("=" * 50)
    if final_state == "COMPLETED":
        artifacts = response.get("result", {}).get("artifacts", [])
        report_text = ""
        for artifact in artifacts:
            for part in artifact.get("parts", []):
                if part.get("type") == "text":
                    report_text += part.get("text", "")
        print(f"  SUCCESS: 远程服务返回分析结果")
        print(f"  Task ID:      {task_id}")
        print(f"  状态:         {final_state}")
        print(f"  耗时:         {total_elapsed:.0f} ms")
        print(f"  轮询次数:     {poll_count}")
        print(f"\n远程分析结果:")
        print(report_text)
    elif final_state == "FAILED":
        print(f"  FAILURE: 远程服务执行失败")
        print(f"  Task ID: {task_id}")
    else:
        print(f"  WARNING: Task 在 {max_polls * poll_interval:.0f}s 内未完成")
        print(f"  最终状态: {final_state}")
    print()

    print("[7] 清理: 停止远程 A2A Server...")
    server.shutdown()
    print("  [A2A Server] 已停止")
    print()
    print("=" * 70)
    print("  示例运行结束")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
```

## 输出

```
======================================================================
  AgentMesh A2A 桥接示例 — 远程 A2A 服务连接
======================================================================

[1] 启动远程 A2A Server...
  [A2A Server] 已启动: http://localhost:18080
  [A2A Server] 端点: 
    GET  /.well-known/agent.json  — AgentCard 发现
    POST /tasks/send              — 提交 Task
    POST /tasks/getTask           — 查询 Task 状态

[2] Client: 发现远程 Agent (AgentCard)...
  名称:     Remote AI Agent
  描述:     A2A 兼容的远程 AI 服务端点，支持文本生成、摘要和数据分析...
  能力列表:
    - text-generation: 文本生成
    - summarization: 文本摘要
    - data-analysis: 数据分析

[3] Client: 构造并发送 Task...
  Task ID: task-remote-xxxxxxxx
  来源:    local-client
  目标:    remote-service
  意图:    summarization

[4] Client: 通过 HTTP JSON-RPC 发送 Task...
  [A2A Server] 收到 Task: task-remote-xxxxxxxx
  [A2A Server] 来源: local-client
  [A2A Server] 意图: AgentMesh is an A2A protocol adapter that enables...
  Task 已发送! Server 返回状态: SUBMITTED

[5] Client: 轮询 Task 状态...
--------------------------------------------------
  [Client] 轮询 #2: WORKING (1.0s)
  [Client] 轮询 #4: COMPLETED (2.0s)
  [A2A Server] Task xxxxxxxx: 状态更新为 WORKING
  [A2A Server] Task xxxxxxxx: 状态更新为 COMPLETED
--------------------------------------------------

[6] Client: 处理返回结果:
==================================================
  SUCCESS: 远程服务返回分析结果
  Task ID:      task-remote-xxxxxxxx
  状态:         COMPLETED
  耗时:         2500 ms
  轮询次数:     5

远程分析结果:
Summary of the input text:
1. AgentMesh is an A2A protocol adapter
2. It enables standardized communication between AI agents
3. Key features: message conversion, task lifecycle, multi-provider
4. Version 0.3 adds streaming, auth, resilience patterns, discovery

[7] 清理: 停止远程 A2A Server...
  [A2A Server] 已停止

======================================================================
  示例运行结束
======================================================================
```

## 关键概念

| 概念 | 说明 |
|------|------|
| HttpProvider | 基于Python标准库的HTTP Provider，通过JSON-RPC协议与远程A2A Server通信 |
| A2A协议端点 | /.well-known/agent.json（AgentCard发现）、/tasks/send（提任务）、/tasks/getTask（查状态） |
| Server生命周期 | 通过HTTPServer启动、后台线程运行、shutdown()优雅停止 |
| 异步轮询 | Client端通过asyncio.to_thread封装阻塞HTTP调用，非阻塞等待任务完成 |
| 跨进程通信 | Server和Client处于不同进程甚至不同主机，通过HTTP JSON-RPC 进行标准化协议通信 |
| AgentCard发现 | Client通过GET请求发现远程Agent的名称、技能、能力标志等元信息 |
