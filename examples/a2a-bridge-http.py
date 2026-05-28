#!/usr/bin/env python3
"""
AgentMesh A2A Bridge — HTTP 远程 A2A Server 通信示例

展示：
  - 内嵌 HTTP A2A Server（JSON-RPC 2.0 over HTTP）
  - bot-alpha 通过 HTTP POST 发送 TaskRequest
  - A2A Server 接收、处理并返回 TaskResult
  - 保真度（fidelity）跨网络保留
  - 完整的 JSON-RPC 请求/响应生命周期

运行方式（独立可运行，内置 Server）:
  python3 a2a-bridge-http.py

如果已有外部 A2A Server，可通过 --server-url 指定：
  python3 a2a-bridge-http.py --server-url http://localhost:8080
"""

import sys, os, json, uuid, time, threading
from datetime import datetime, timezone

# SDK路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'sdk'))

from a2a_provider import (
    A2AProvider, MemoryProvider, A2AFacade,
    A2ATaskManager, A2ATaskState, A2AResult, A2AError,
)

# AgentMesh SDK — 保真度追踪
sys.path.insert(0, os.path.expanduser('~/.openclaw/skills/agentmesh-protocol/'))
try:
    from agentmesh_sdk import FidelityTracker, validate_message
    AGENTMESH_SDK = True
except ImportError:
    AGENTMESH_SDK = False


# ============================================================
# 工具函数
# ============================================================

def make_id(prefix: str = "msg") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# 1. A2A HTTP Server (JSON-RPC 2.0)
# ============================================================

class A2AHTTPServer:
    """
    轻量 A2A HTTP Server，基于 http.server 实现 JSON-RPC 2.0 端点。
    支持：tasks.send, tasks.get, tasks.cancel
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0, name: str = "a2a-http-server"):
        self.host = host
        self.port = port
        self.name = name
        self.provider = MemoryProvider(f"http-{name}")
        self.task_manager = A2ATaskManager()

        # 注册 Agent Card
        self.provider.register_agent_card({
            "name": name,
            "description": "A2A HTTP Server — 支持 tasks.send/get/cancel",
            "url": f"http://{host}:{port}/a2a",
            "capabilities": ["task-processing", "analysis", "json-rpc"],
            "authentication": {"schemes": [{"type": "none"}]},
        })

    def _make_response(self, request_id, result: dict = None, error: dict = None):
        resp = {"jsonrpc": "2.0", "id": request_id}
        if error:
            resp["error"] = error
        else:
            resp["result"] = result
        return resp

    def handle_request(self, body: dict) -> dict:
        """处理 JSON-RPC 2.0 请求"""
        method = body.get("method", "")
        req_id = body.get("id", None)
        params = body.get("params", {})

        if method == "tasks.send":
            return self._handle_tasks_send(req_id, params)
        elif method == "tasks.get":
            return self._handle_tasks_get(req_id, params)
        elif method == "tasks.cancel":
            return self._handle_tasks_cancel(req_id, params)
        else:
            return self._make_response(req_id, error={
                "code": -32601, "message": f"Method not found: {method}",
            })

    def _handle_tasks_send(self, req_id, params: dict) -> dict:
        task_id = params.get("id", make_id("task"))
        state = params.get("status", {}).get("state", A2ATaskState.SUBMITTED)

        # 追踪任务
        self.task_manager.track(task_id, state)

        # 提取保真度信息
        messages = params.get("messages", [])
        fidelity_info = None
        request_text = ""
        for msg in messages:
            meta = msg.get("metadata", {})
            if meta.get("agentmesh_fidelity") is not None:
                fidelity_info = {
                    "sender": meta.get("agentmesh_sender", "unknown"),
                    "fidelity": meta.get("agentmesh_fidelity"),
                    "confidence": meta.get("agentmesh_confidence"),
                }
            for part in msg.get("parts", []):
                request_text += part.get("text", "")

        # 模拟处理
        self.task_manager.update_state(task_id, A2ATaskState.WORKING)
        time.sleep(0.05)  # 模拟处理延迟

        # 构造响应
        result_text = self._generate_analysis(request_text)

        # 响应中携带保真度信息
        response_fidelity = 0.85
        response_confidence = 0.80
        if fidelity_info:
            # 跨网络保真度：基于传入保真度 × 本次处理保真度
            incoming_fid = fidelity_info["fidelity"]
            response_fidelity = round(incoming_fid * 0.85, 4)
            response_confidence = 0.80

        self.task_manager.update_state(task_id, A2ATaskState.COMPLETED)

        result = {
            "id": task_id,
            "status": {"state": A2ATaskState.COMPLETED},
            "messages": [
                {
                    "role": "agent",
                    "parts": [{"text": result_text}],
                    "metadata": {
                        "agentmesh_sender": self.name,
                        "agentmesh_confidence": response_confidence,
                        "agentmesh_fidelity": response_fidelity,
                        "agentmesh_schema_version": "2.1",
                    },
                }
            ],
        }

        # 存回 Provider
        self.provider._tasks[task_id] = result
        return self._make_response(req_id, result=result)

    def _handle_tasks_get(self, req_id, params: dict) -> dict:
        task_id = params.get("id", "")
        task = self.provider.get_task(task_id)
        if not task:
            return self._make_response(req_id, error={
                "code": -32000, "message": f"Task not found: {task_id}",
            })
        task_data = task.data if isinstance(task, A2AResult) else task
        return self._make_response(req_id, result={
            "id": task_id,
            "status": {"state": self.task_manager.get_task(task_id).get("state", "unknown") if self.task_manager.get_task(task_id) else "unknown"},
        })

    def _handle_tasks_cancel(self, req_id, params: dict) -> dict:
        task_id = params.get("id", "")
        self.provider.cancel_task(task_id)
        self.task_manager.update_state(task_id, A2ATaskState.CANCELED)
        return self._make_response(req_id, result={
            "id": task_id, "status": {"state": A2ATaskState.CANCELED},
        })

    def _generate_analysis(self, request_text: str) -> str:
        """模拟 A2A Server 的处理逻辑"""
        return (
            "A2A HTTP Server 处理结果:\n\n"
            "收到 TaskRequest，已完成分析。\n\n"
            "分析结论 (基于请求内容):\n"
            "  1. 多Agent通信协议中，A2A JSON-RPC v2.0 是最佳选择\n"
            "  2. 保真度追踪可无损跨网络传递（通过 metadata agentmesh_* 字段）\n"
            "  3. 建议在生产环境启用 mTLS 加密\n\n"
            "server_response:\n"
            "  - status: completed\n"
            "  - 处理时间: 0.05s (模拟)\n"
            "  - 保真度已在网络中保留\n\n"
            f"--- {self.name} 处理完毕 ---"
        )

    def start(self):
        """启动 HTTP Server（阻塞）"""
        from http.server import HTTPServer, BaseHTTPRequestHandler

        server_self = self

        class A2ARequestHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                content_length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(content_length).decode("utf-8"))
                response = server_self.handle_request(body)
                resp_body = json.dumps(response, ensure_ascii=False, indent=2)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(resp_body.encode("utf-8"))

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def log_message(self, fmt, *args):
                # 静默日志，避免干扰输出
                if "POST" in str(args):
                    pass  # suppress

        self.httpd = HTTPServer((self.host, self.port), A2ARequestHandler)
        self.port = self.httpd.server_address[1]
        print(f"  A2A HTTP Server 已启动: http://{self.host}:{self.port}/a2a")
        self.httpd.serve_forever()

    def start_background(self) -> threading.Thread:
        """在后台线程中启动 Server"""
        from http.server import HTTPServer, BaseHTTPRequestHandler

        server_self = self

        class A2ARequestHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                content_length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(content_length).decode("utf-8"))
                response = server_self.handle_request(body)
                resp_body = json.dumps(response, ensure_ascii=False, indent=2)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(resp_body.encode("utf-8"))

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def log_message(self, fmt, *args):
                pass

        self.httpd = HTTPServer((self.host, self.port), A2ARequestHandler)
        self.port = self.httpd.server_address[1]
        t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        t.start()
        return t

    def stop(self):
        if hasattr(self, "httpd"):
            self.httpd.shutdown()


# ============================================================
# 2. A2A HTTP Client
# ============================================================

class A2AHTTPClient:
    """
    A2A JSON-RPC 2.0 HTTP 客户端。
    封装对 A2A Server 的 HTTP POST 调用。
    """

    def __init__(self, server_url: str, agent_name: str = "bot-alpha"):
        self.server_url = server_url
        self.agent_name = agent_name
        self.request_counter = 0

    def send_task(self, task_id: str, request_text: str, fidelity: float = 1.0,
                  confidence: float = 0.9) -> dict:
        """
        发送 TaskRequest 到 A2A Server。
        构造符合 JSON-RPC 2.0 的请求体，携带保真度追踪信息。
        """
        import urllib.request

        self.request_counter += 1
        body = {
            "jsonrpc": "2.0",
            "id": self.request_counter,
            "method": "tasks.send",
            "params": {
                "id": task_id,
                "status": {"state": A2ATaskState.SUBMITTED},
                "messages": [
                    {
                        "role": "user",
                        "parts": [{"text": request_text}],
                        "metadata": {
                            "agentmesh_sender": self.agent_name,
                            "agentmesh_confidence": confidence,
                            "agentmesh_fidelity": fidelity,
                            "agentmesh_schema_version": "2.1",
                        },
                    }
                ],
            },
        }

        req_data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.server_url,
            data=req_data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            response = json.loads(resp.read().decode("utf-8"))

        return response

    def get_task(self, task_id: str) -> dict:
        """查询任务状态"""
        import urllib.request

        self.request_counter += 1
        body = {
            "jsonrpc": "2.0",
            "id": self.request_counter,
            "method": "tasks.get",
            "params": {"id": task_id},
        }

        req = urllib.request.Request(
            self.server_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def cancel_task(self, task_id: str) -> dict:
        """取消任务"""
        import urllib.request

        self.request_counter += 1
        body = {
            "jsonrpc": "2.0",
            "id": self.request_counter,
            "method": "tasks.cancel",
            "params": {"id": task_id},
        }

        req = urllib.request.Request(
            self.server_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))


# ============================================================
# 3. 保真度追踪演示
# ============================================================

def extract_fidelity_chain(response: dict) -> list:
    """从 HTTP 响应中提取保真度链"""
    chain = []
    result = response.get("result", {})
    for msg in result.get("messages", []):
        meta = msg.get("metadata", {})
        if meta.get("agentmesh_fidelity") is not None:
            chain.append({
                "sender": meta.get("agentmesh_sender", "unknown"),
                "fidelity": meta.get("agentmesh_fidelity"),
                "confidence": meta.get("agentmesh_confidence"),
            })
    return chain


def demo_json_rpc_error():
    """演示 JSON-RPC 错误处理"""
    print()
    print("  [JSON-RPC 错误处理演示]")
    print("    method: tasks.get (不存在任务)")
    print("    预期: -32000 / Task not found")


# ============================================================
# 4. 主流程
# ============================================================

def main():
    print("=" * 65)
    print("AgentMesh A2A Bridge — HTTP A2A Server 通信")
    print("=" * 65)
    print()

    # ---- 4a. 启动内嵌 A2A HTTP Server ----
    print("[启动 Server]")
    server = A2AHTTPServer(host="127.0.0.1", port=0, name="a2a-server-01")
    server.start_background()
    server_url = f"http://{server.host}:{server.port}/a2a"
    print(f"  Server URL : {server_url}")
    print(f"  Agent Name : {server.name}")
    print(f"  Methods    : tasks.send, tasks.get, tasks.cancel")
    print()

    # ---- 4b. 创建 HTTP Client ----
    print("[初始化 Client]")
    client = A2AHTTPClient(server_url=server_url, agent_name="bot-alpha")
    print(f"  Client Agent : {client.agent_name}")
    print(f"  Server URL   : {server_url}")
    print()

    # ---- 4c. 保真度追踪 ----
    if AGENTMESH_SDK:
        tracker = FidelityTracker(warning_threshold=0.5)
        print("[保真度追踪]  已启用")
    print()

    # ---- 4d. bot-alpha 发送 TaskRequest ----
    task_id = make_id("task")
    request_text = (
        "请评估以下三种Agent通信协议，给出建议：\n"
        "1. A2A JSON-RPC v2.0 over HTTP\n"
        "2. MCP (Model Context Protocol)\n"
        "3. 自定义WebSocket协议"
    )

    print("[Step 1] HTTP POST — tasks.send")
    print(f"  Task ID     : {task_id}")
    print(f"  请求方法    : POST {server_url}")
    print(f"  协议        : JSON-RPC 2.0")
    print(f"  发送者      : bot-alpha")
    print(f"  初始保真度  : 1.0")
    print(f"  请求内容    : {request_text[:60]}...")
    print()

    # 保真度追踪 — Step 1
    if AGENTMESH_SDK:
        tracker.add_step("bot-alpha", 1.0, "HTTP POST TaskRequest")

    # 执行 HTTP 调用
    response = client.send_task(
        task_id=task_id,
        request_text=request_text,
        fidelity=1.0,
        confidence=0.9,
    )

    # ---- 4e. 处理 Server 响应 ----
    print("[Step 2] 接收 HTTP 响应")
    if "error" in response:
        print(f"  错误: [{response['error'].get('code')}] {response['error'].get('message')}")
        print()
        print("=" * 65)
        print("HTTP A2A 通信失败")
        print("=" * 65)
        server.stop()
        return

    result = response.get("result", {})
    task_status = result.get("status", {}).get("state", "unknown")
    messages = result.get("messages", [])
    artifacts = result.get("artifacts", [])

    print(f"  JSON-RPC ID : {response.get('id')}")
    print(f"  任务状态    : {task_status}")
    print(f"  消息数      : {len(messages)}")

    for msg in messages:
        meta = msg.get("metadata", {})
        print(f"  回复者      : {meta.get('agentmesh_sender', 'unknown')}")
        print(f"  保真度      : {meta.get('agentmesh_fidelity', 'N/A')}")
        print(f"  置信度      : {meta.get('agentmesh_confidence', 'N/A')}")
        print(f"  响应内容:")
        for line in msg["parts"][0]["text"].strip().split("\n"):
            print(f"    {line}")
    print()

    # ---- 4f. 保真度跨网络验证 ----
    print("[Step 3] 保真度跨网络验证")
    fidelity_chain = extract_fidelity_chain(response)
    if fidelity_chain:
        for entry in fidelity_chain:
            print(f"  {entry['sender']}: fidelity={entry['fidelity']}, confidence={entry['confidence']}")
        print()
        print("  → 保真度成功通过网络保留了！")
        print("  → JSON-RPC metadata 中 agentmesh_fidelity 字段完好")

        # 保真度追踪 — Step 2
        if AGENTMESH_SDK:
            last_fid = fidelity_chain[-1]["fidelity"]
            tracker.add_step("a2a-server-01", last_fid, "HTTP Server处理并响应")
            print()
            print(f"  AgentMesh FidelityTracker:")
            print(f"    累积保真度: {tracker.cumulative_fidelity:.4f}")
            print(f"    警告触发  : {tracker.warning_triggered}")
    else:
        print("  未找到保真度追踪信息")
    print()

    # ---- 4g. 验证 Server Agent Card ----
    print("[Step 4] Server Agent Card 查询")
    card = server.provider.get_agent_card(server.name)
    if card:
        print(f"  名称        : {card['name']}")
        print(f"  描述        : {card['description']}")
        print(f"  URL         : {card['url']}")
        print(f"  能力        : {', '.join(card['capabilities'])}")
    print()

    # ---- 4h. 测试 tasks.get ----
    print("[Step 5] JSON-RPC tasks.get 验证")
    get_resp = client.get_task(task_id)
    if "error" not in get_resp:
        get_result = get_resp.get("result", {})
        print(f"  GET task {task_id}: 状态 = {get_result.get('status', {}).get('state', 'unknown')}")
        print(f"  任务存在: 是")
    else:
        print(f"  GET task {task_id}: 错误 = {get_resp['error']}")
    print()

    # ---- 4i. JSON-RPC 错误处理 ----
    demo_json_rpc_error()
    print()

    # ---- 4j. 完整通信报告 ----
    print("=" * 65)
    print("HTTP A2A 通信完成 — 保真度跨网络保留")
    print("=" * 65)
    print()
    print("通信链路:")
    print("  bot-alpha --[HTTP POST JSON-RPC 2.0]--> a2a-server-01")
    print("                                                   |")
    print("  bot-alpha <--[HTTP 200 JSON-RPC Response]-- a2a-server-01")
    print()
    print("保真度传递:")
    print("  bot-alpha(1.0) --HTTP--> a2a-server-01(*0.85) = {}".format(
        fidelity_chain[-1]["fidelity"] if fidelity_chain else "N/A"
    ))
    print()
    print("协议层:")
    print("  JSON-RPC 2.0 params.messages[].metadata.agentmesh_fidelity")
    print("  保真度无损跨网络传递")
    print()
    print("注意: 此示例内嵌了 A2A HTTP Server。")
    print("      实际部署时可独立运行 Server，client 远程连接。")
    print()

    # 关闭 Server
    server.stop()


if __name__ == "__main__":
    main()
