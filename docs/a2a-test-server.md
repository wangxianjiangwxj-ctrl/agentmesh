# A2A Test Server 指南

AgentMesh 内置了一个轻量级的 A2A 测试服务器，用于跨进程、跨语言的 Agent 通信测试。服务器基于 FastAPI 构建，提供 REST API 和 SSE 流式订阅。

---

## 快速开始

### 安装

确保已安装 AgentMesh：

```bash
pip install agentmesh
```

服务器依赖 FastAPI 和 uvicorn：

```bash
pip install fastapi uvicorn
```

### 启动服务器

#### CLI 方式

```bash
# 启动（默认端口 8080）
python -m agentmesh.a2a_server server

# 指定端口
python -m agentmesh.a2a_server server --port 8080

# 后台运行
python -m agentmesh.a2a_server server --port 8080 --daemon
```

#### Python 代码方式

```python
from agentmesh.a2a_server import cmd_server

# 启动服务器（阻塞当前线程）
cmd_server(port=8080)
```

启动后访问 http://localhost:8080/health 确认服务器状态。

#### 嵌入到 FastAPI 应用

```python
from fastapi import FastAPI
from agentmesh.a2a_server import create_server_app

app = FastAPI()

# 挂载 A2A 子应用
a2a_app = create_server_app()
app.mount("/a2a", a2a_app)

# 现在访问 /a2a/health, /a2a/send 等
```

---

## API 端点

服务器在 `/api/v1/` 路径下提供 REST API（部分端点也对外暴露在 `/` 下）。

### 健康检查

```
GET /health
GET /ping
```

```json
// GET /health
{
  "status": "ok",
  "uptime": 123.45,
  "components": {
    "server": "healthy",
    "provider": "healthy"
  },
  "version": "0.3.0"
}
```

### 发送任务

```
POST /send
Content-Type: application/json

{
  "task": {
    "id": "task_001",
    "status": {"state": "submitted"},
    "payload": {"text": "Hello!"}
  }
}
```

响应：

```json
{
  "success": true,
  "data": {...},
  "error": null,
  "task_state": "submitted"
}
```

### 查询任务

```
GET /task/{task_id}
```

```json
{
  "success": true,
  "data": {
    "id": "task_001",
    "status": {"state": "submitted"},
    "payload": {"text": "Hello!"}
  },
  "task_state": "submitted"
}
```

### 取消任务

```
POST /cancel/{task_id}
```

### SSE 流式订阅

```
GET /stream/{task_id}
Accept: text/event-stream
```

返回 Server-Sent Events，事件类型包括：

| 事件类型 | 说明 |
|----------|------|
| `state` | 状态更新 |
| `completed` | 任务完成 |
| `done` | 流结束 |
| `error` | 错误 |
| `stream_timeout` | 流空闲超时 |
| `reconnect` | 重连通知 |

事件格式：

```
event: state
data: {"event": "state", "data": {"success": true, "task_state": "working", ...}}

event: completed
data: {"event": "completed", "data": {"success": true, "task_state": "completed", ...}}

event: done
data: {"event": "done", "data": {"success": true, "data": {"message": "Stream ended"}}}
```

### Agent 注册

```
GET /agents           # 列出所有 AgentCard
POST /agents          # 注册 AgentCard
```

```json
POST /agents
Content-Type: application/json

{
  "name": "test-agent",
  "skills": ["coding", "debug"]
}
```

---

## 测试场景

### 场景 1：基本协议测试

验证服务器核心功能：发送、查询、取消任务。

```python
from agentmesh.a2a_server import HttpProvider

client = HttpProvider("http://localhost:8080")

# 1. Ping
r = client.ping()
print(f"Server: {r.data['status']}")

# 2. 发送任务
task = {
    "id": "test_001",
    "status": {"state": "submitted"},
    "payload": {"text": "hello"},
}
r = client.send_message(task)
assert r.success and r.task_state == "submitted"

# 3. 查询任务
r = client.get_task("test_001")
assert r.data["id"] == "test_001"

# 4. 取消任务
r = client.cancel_task("test_001")
assert r.task_state == "canceled"

# 5. 查询不存在的任务 -> 404
r = client.get_task("nonexistent")
assert not r.success
assert r.error.code == 404

# 6. 注册 Agent
r = client.register_agent("test-bot", ["coding", "debug"])
assert r.success
```

### 场景 2：多轮会话

模拟多轮对话：提交 -> 轮询 -> 精化 -> 清理。

```python
from agentmesh.a2a_server import HttpProvider

client = HttpProvider("http://localhost:8080")
task_id = "conversation_001"

# 第1轮：初始提交
task = {
    "id": task_id,
    "status": {"state": "submitted"},
    "payload": {"text": "Initial request"},
}
r1 = client.send_message(task)
assert r1.success

# 第2轮：轮询状态
r2 = client.get_task(task_id)
print(f"Round 2: state={r2.data['status']['state']}")

# 第3轮：精化请求
updated = {
    "id": task_id,
    "status": {"state": "submitted"},
    "payload": {"text": "Refined request"},
    "metadata": {"rounds": 1},
}
r3 = client.send_message(updated)
assert r3.success

# 第4轮：验证并清理
r4 = client.get_task(task_id)
print(f"Final payload: {r4.data['payload']}")

client.cancel_task(task_id)
```

### 场景 3：SSE 流式订阅

实时订阅任务状态变化。

```python
from agentmesh.a2a_server import HttpProvider, SSEStream

client = HttpProvider("http://localhost:8080")

# 提交任务
task_id = "stream_task_001"
client.send_message({
    "id": task_id,
    "status": {"state": "submitted"},
    "payload": {"text": "Stream test"},
})

# SSE 流式订阅
stream = SSEStream("http://localhost:8080", task_id)
for event_type, data in stream:
    print(f"[{event_type}] {data}")
    if event_type == "done":
        break

# 输出类似：
# [state] {"success": true, "task_state": "submitted", ...}
# [state] {"success": true, "task_state": "working", ...}
# [completed] {"success": true, "task_state": "completed", ...}
# [done] {"success": true, "data": {"message": "Stream ended"}}
```

SSEStream 支持自动重连和心跳检测：

```python
stream = SSEStream(
    base_url="http://localhost:8080",
    task_id="task_001",
    max_retries=3,              # 最大重试次数
    backoff_factor=1.0,         # 指数退避基值
    timeout=30,                 # 连接超时（秒）
    heartbeat_timeout=15.0,     # 心跳超时（秒）
)

for event_type, data in stream:
    if event_type == "reconnect":
        print(f"重连中 (第{data['attempt']}次)...")
    elif event_type == "heartbeat_timeout":
        print(f"心跳超时: {data['idle_seconds']}秒")
    elif event_type == "error":
        print(f"错误: {data}")
    else:
        print(f"[{event_type}] {data}")
```

### 场景 4：多 Agent 链式通信

模拟 A -> B -> C 的 Agent 链式任务委派。

```python
from agentmesh.a2a_server import HttpProvider

client = HttpProvider("http://localhost:8080")

# Agent A 提交主任务
task_a = {
    "id": "chain_main",
    "status": {"state": "submitted"},
    "payload": {"text": "Calculate project timeline"},
}
r_a = client.send_message(task_a)
assert r_a.success

# Agent B 接收子任务（带 parent 引用）
task_b = {
    "id": "chain_delegate_b",
    "status": {"state": "submitted"},
    "payload": {"text": "Estimate frontend effort"},
    "metadata": {"parent": "chain_main", "agent": "B"},
}
r_b = client.send_message(task_b)
assert r_b.success

# Agent C 接收子任务
task_c = {
    "id": "chain_delegate_c",
    "status": {"state": "submitted"},
    "payload": {"text": "Estimate backend effort"},
    "metadata": {"parent": "chain_main", "agent": "C"},
}
r_c = client.send_message(task_c)
assert r_c.success

# 验证所有任务存在
for tid in ["chain_main", "chain_delegate_b", "chain_delegate_c"]:
    r = client.get_task(tid)
    assert r.success and r.data["id"] == tid

# 清理（反向顺序）
for tid in ["chain_delegate_c", "chain_delegate_b", "chain_main"]:
    client.cancel_task(tid)
```

---

## HttpProvider 客户端

HttpProvider 实现了 A2AProvider 接口，是对接 A2A Test Server 的标准客户端。

### 配置

```python
from agentmesh.a2a_server import HttpProvider
from agentmesh.a2a_models import ServerTimeoutConfig

# 基本配置
client = HttpProvider("http://localhost:8080")

# 自定义超时和重试
client = HttpProvider(
    base_url="http://localhost:8080",
    max_retries=5,
    backoff_factor=2.0,
    timeout_config=ServerTimeoutConfig(
        connect_timeout=5.0,
        read_timeout=30.0,
        request_timeout=60.0,
    ),
)
```

### 重试行为

HttpProvider 在以下情况自动重试，使用指数退避 + 随机抖动：

| 条件 | 是否重试 |
|------|----------|
| HTTP 5xx (500, 502, 503, 504) | 是 |
| HTTP 429 (Too Many Requests) | 是 |
| 网络异常 (ConnectionError, TimeoutError, OSError) | 是 |
| HTTP 4xx (除 429) | 否 |

---

## 集成测试运行

### 运行内置协议测试

```bash
# 自动启动服务器并运行测试
python -m agentmesh.a2a_server test

# 连接已运行的服务器
python -m agentmesh.a2a_server test --port 8080
```

### 运行 E2E 测试

```bash
# 安装测试依赖
pip install pytest

# 运行 A2A Server 协议测试
python -m pytest tests/e2e/test_a2a_server.py -v

# 运行多轮会话测试
python -m pytest tests/e2e/test_multi_round.py -v

# 运行 SSE 流测试
python -m pytest tests/e2e/test_sse_stream.py -v

# 全部测试
python -m pytest tests/e2e/ -v

# 指定服务器端口
python -m pytest tests/e2e/test_a2a_server.py -v --server-port 8080
```

---

## 配置参考

### ServerTimeoutConfig (from `agentmesh.a2a_models`)

```python
from agentmesh.a2a_models import ServerTimeoutConfig, DEFAULT_TIMEOUT_CONFIG

config = ServerTimeoutConfig(
    connect_timeout=10.0,       # 连接超时（秒）
    read_timeout=30.0,          # 读取超时（秒）
    request_timeout=30.0,       # 请求整体超时（秒）
    stream_idle_timeout=15.0,   # SSE 流空闲超时（秒）
)

# 使用配置
from agentmesh.a2a_server import cmd_server
cmd_server(port=8080, timeout_config=config)
```

---

## 架构说明

```
+------------------+       HTTP/SSE       +------------------+
|  HttpProvider    | ------------------->  |  A2A Server      |
|  (Client/SDK)    | <-------------------  |  (FastAPI)       |
+------------------+                       +------------------+
                                                  |
                                                  v
                                           +------------------+
                                           |  MemoryProvider  |
                                           |  (In-memory)     |
                                           +------------------+
                                                  |
                                                  v
                                           +------------------+
                                           |  A2ATaskManager  |
                                           |  (State Machine) |
                                           +------------------+
```

服务器架构分层：

1. **FastAPI 层** — HTTP 路由、请求解析、SSE 流、错误处理
2. **请求追踪中间件** — 自动注入 TraceContext 到每个请求
3. **超时中间件** — 可配置的请求处理超时
4. **MemoryProvider** — 内存状态存储，Task 状态机
5. **A2ATaskManager** — 状态转换验证和父子任务追踪

---

## 另见

- [Provider API](api-reference/provider.md) — HttpProvider 和 A2AFacade 详细文档
- [Trace API](api-reference/trace.md) — 分布式追踪与 TraceContext
- [Log API](api-reference/log.md) — 结构化日志（服务器端使用）
- [快速开始](quickstart.md) — 快速上手指南
