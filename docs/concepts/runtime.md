# 运行时与可观测性 (Runtime & Observability)

> A2AServer / A2AClient 生命周期、追踪、日志与健康检查

---

## 概述

AgentMesh 运行时提供了一套完整的 A2A Server/Client 基础设施，涵盖：

- **A2A Server** — 轻量级 FastAPI HTTP 服务器，处理 Agent 通信
- **A2AClient (HttpProvider)** — 客户端实现，连接远程 Server
- **Telemetry (可观测性)** — 分布式追踪、结构化日志、健康检查
- **可靠性** — 超时控制、重试机制

```
┌─────────────────────────────────────────────────────┐
│                   运行时全景图                          │
│                                                       │
│  ┌──────────────┐         ┌──────────────────────┐   │
│  │   A2AClient  │──HTTP──>│     A2A Server        │   │
│  │ (HttpProvider)│         │  (FastAPI + uvicorn)  │   │
│  │              │<──SSE──│                        │   │
│  └──────────────┘         │  ┌──────────────────┐  │   │
│                           │  │   MemoryProvider  │  │   │
│  ┌──────────────┐         │  │   A2ATaskManager  │  │   │
│  │ TraceProvider│         │  └──────────────────┘  │   │
│  │ StructuredLog│         └──────────────────────┘   │
│  └──────────────┘                                    │
└─────────────────────────────────────────────────────┘
```

---

## A2A Server 生命周期

### 启动 Server

AgentMesh 内置的 A2A Server 基于 FastAPI，提供完整的 REST API。

```python
# 方式一：CLI 启动
# agentmesh serve --port 8080

# 方式二：Python 代码启动
from agentmesh.a2a_server import cmd_server

# 监听 0.0.0.0:8080
cmd_server(port=8080)
```

**启动顺序**：

1. 创建 `MemoryProvider` 实例（或自定义 Provider）
2. 创建 `A2ATaskManager` 实例
3. 初始化 `A2AFacade`（Provider + TaskManager）
4. 构建 FastAPI 应用，挂载所有端点
5. 启动 uvicorn 监听端口

### Graceful Shutdown

```python
# Ctrl+C 或 SIGTERM 触发优雅关闭
# - 正在处理的请求继续执行直到完成（受 request_timeout 约束）
# - 活跃 SSE 流释放
# - 日志刷新
```

### REST API 端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/health` | GET | 健康检查 (status, uptime, components, version) |
| `/ping` | GET | 轻量级健康探测 |
| `/send` | POST | 提交任务 |
| `/task/{id}` | GET | 查询任务状态 |
| `/cancel/{id}` | POST | 取消任务 |
| `/stream/{id}` | GET | SSE 流式订阅任务状态 |
| `/agents` | GET | 列出已注册 Agent |
| `/agents` | POST | 注册 Agent |

### Server 中间件栈

请求经过的中间件依次为：

```
HTTP Request
    │
    ├── 请求超时中间件 (Request Timeout Middleware)
    │   └── 限制单个请求处理时间，超时返回 503
    │
    ├── Trace 中间件 (Trace Middleware)
    │   ├── 注入/提取追踪上下文
    │   ├── 记录请求开始和结束日志
    │   └── 在响应头中写入 X-Trace-Id
    │
    └── 异常处理中间件 (Exception Handler)
        ├── A2AServerError → 结构化错误响应
        ├── HTTPException → 标准 HTTP 错误响应
        └── 通用异常 → 500 Internal Error
```

---

## A2A Client (HttpProvider) 生命周期

### 创建客户端

```python
from agentmesh.a2a_server import HttpProvider
from agentmesh.a2a_models import ServerTimeoutConfig

client = HttpProvider(
    base_url="http://localhost:8080",
    name="my-client",
    timeout_config=ServerTimeoutConfig(
        request_timeout=30.0,
        connect_timeout=10.0,
    ),
    max_retries=3,
    backoff_factor=1.0,
)
```

### 客户端操作流程

```python
# 1. 健康检查
result = client.ping()
print(result.data)  # {"status": "ok", "provider": "http"}

# 2. 发送任务
task = {
    "id": "task_001",
    "status": {"state": "submitted"},
    "payload": {"text": "Hello A2A"},
}
result = client.send_message(task)

# 3. 查询状态
result = client.get_task("task_001")
print(result.task_state)  # "submitted"

# 4. SSE 流式订阅
stream = client.stream_task("task_001")
for event, data in stream:
    print(f"[{event}] {data}")
    if event == "done":
        break

# 5. 取消任务
client.cancel_task("task_001")

# 6. 注册 Agent
client.register_agent("my-agent", skills=["analysis"])
```

### SSE 流式客户端

`SSEStream` 封装了 HTTP 流式连接的细节，支持自动重连：

```python
from agentmesh.a2a_server import SSEStream

stream = SSEStream(
    base_url="http://localhost:8080",
    task_id="task_001",
    max_retries=3,
    backoff_factor=1.0,
    timeout=30,
    heartbeat_timeout=15.0,
)

for event_type, data in stream:
    if event_type == "state":
        print(f"状态更新: {data['task_state']}")
    elif event_type == "completed":
        print(f"完成: {data['data']['result']}")
    elif event_type == "reconnect":
        print(f"重连: attempt {data['attempt']}/{data['max_retries']}")
    elif event_type == "error":
        break
```

---

## Telemetry (可观测性)

### 分布式追踪 (Trace)

AgentMesh 的 Trace 系统实现了 OpenTelemetry 兼容的追踪上下文传播。

**TraceContext** — 不可变追踪上下文：

```python
from agentmesh.a2a import TraceProvider, TraceContext, with_trace_context

provider = TraceProvider()

# 创建根追踪上下文
ctx = provider.new_context(baggage={
    "method": "research",
    "project": "ai-safety",
})
print(ctx.trace_id)    # 32 位 hex（如 "a1b2c3d4e5f6..."）
print(ctx.span_id)     # 16 位 hex
print(ctx.parent_span_id)  # "" (根 span)

# 创建子 span
child_ctx = provider.child_context(ctx)
print(child_ctx.parent_span_id)  # 等于 ctx.span_id
print(child_ctx.trace_id)        # 等于 ctx.trace_id (同一个 trace)

# 在请求上下文中使用
with with_trace_context(context=ctx):
    # 在此范围内，TraceProvider.get_current_context() 返回 ctx
    current = TraceProvider.get_current_context()
    assert current is ctx
```

**追踪传播机制**：

```
Agent A                     Agent B
   │                           │
   │── 创建根 TraceContext ────│
   │── inject() 写入 headers ──>── extract() 解析 headers
   │                           │── 创建 child span
   │                           │── with_trace_context
   │                           │── 处理完成后返回
   │<── 响应带回 trace_id ─────│
```

```python
# 注入追踪上下文到请求头
headers = {}
ctx = provider.new_context()
provider.inject(ctx, headers)
print(headers)
# {
#     "trace_id": "...",
#     "parent_span_id": "",
#     "span_id": "...",
#     "baggage": ""
# }

# 从请求头提取追踪上下文
extracted = TraceProvider.extract(headers)
if extracted:
    print(f"追踪 ID: {extracted.trace_id}")
```

### 结构化日志 (Log)

`StructuredLogger` 输出 JSON 格式的日志条目，自动包含追踪上下文。

```python
from agentmesh.a2a import StructuredLogger, LogLevel, LoggerConfig

# 全局配置
StructuredLogger.configure(LoggerConfig(
    level=LogLevel.INFO,
    output="stdout",
    extra_fields={"environment": "production"},
))

# 创建日志器
log = StructuredLogger("my-component")

# 日志条目示例
from agentmesh.a2a import with_trace_context, TraceProvider

provider = TraceProvider()
with with_trace_context(provider.new_context()) as ctx:
    log.info("card_sent",
              detail="Task card dispatched",
              recipient="agent-b",
              card_type="text")

    log.warn("slow_response",
              message="Response took longer than expected",
              duration_ms=5200.0,
              threshold_ms=3000.0)

    try:
        raise ConnectionError("Timeout")
    except ConnectionError as e:
        log.error("connection_failed",
                   error=e,
                   peer="agent-b",
                   attempt=3)
```

**JSON 日志输出格式**：

```json
{
    "timestamp": "2026-06-03T10:30:00.123456+00:00",
    "level": "INFO",
    "component": "my-component",
    "event": "card_sent",
    "trace_id": "a1b2c3d4e5f67890a1b2c3d4e5f67890",
    "span_id": "a1b2c3d4e5f67890",
    "detail": "Task card dispatched",
    "recipient": "agent-b",
    "card_type": "text"
}
```

**日志等级**：

| 等级 | 方法 | 说明 |
|------|------|------|
| DEBUG | `log.debug()` | 详细调试信息 |
| INFO | `log.info()` | 正常操作信息 |
| WARN | `log.warn()` | 需要注意的情况 |
| ERROR | `log.error()` | 错误和异常 |

**日志字段自动注入**：

- `timestamp` — ISO-8601 UTC 时间戳
- `level` — 日志等级
- `component` — 组件名称
- `event` — 事件名称
- `trace_id` / `span_id` — 当前追踪上下文（自动附加）
- `trace_baggage` — 追踪 baggage（自动附加）
- 自定义字段 — 通过 `**extra` 传入

### 健康检查 (Health)

Server 提供两层级健康检查：

**1. Ping (轻量级)**：

```python
# 快速可用性检查
result = client.ping()
print(result.data["status"])  # "ok"
```

**2. Health (详细)**：

```python
# 完整健康检查
# GET /health

{
    "status": "ok",
    "uptime": 86400.0,           # 启动时长（秒）
    "components": {
        "server": "healthy",
        "provider": "healthy",
    },
    "version": "0.3.0"
}
```

---

## 超时与重试机制

### 超时配置 (ServerTimeoutConfig)

```python
from agentmesh.a2a_models import ServerTimeoutConfig

config = ServerTimeoutConfig(
    request_timeout=30.0,       # 单个请求最大处理时间（默认30s）
    stream_idle_timeout=60.0,   # SSE 流空闲超时（默认60s）
    connect_timeout=10.0,       # TCP 连接超时（默认10s）
    read_timeout=30.0,         # 响应读取超时（默认30s）
)
```

**超时行为**：

| 超时类型 | 配置字段 | 默认值 | 触发后果 |
|----------|----------|--------|----------|
| 请求处理 | `request_timeout` | 30s | 返回 503, recoverable=true |
| SSE 空闲 | `stream_idle_timeout` | 60s | 发送 stream_timeout 事件后关闭 |
| TCP 连接 | `connect_timeout` | 10s | 客户端重试 |
| 响应读取 | `read_timeout` | 30s | 客户端重试 |

**特殊值**：

```python
# 0.0 = 无超时限制
config = ServerTimeoutConfig(
    request_timeout=ServerTimeoutConfig.NO_TIMEOUT,  # 不限制处理时间
)
```

### 重试配置 (RetryConfig)

```python
from agentmesh.a2a_models import RetryConfig

config = RetryConfig(
    max_retries=3,              # 最大重试次数 (0 = 不重试)
    backoff_factor=1.0,         # 退避因子（秒）
    max_backoff=30.0,           # 最大退避时间（秒）
    retryable_statuses={429, 500, 502, 503, 504},  # 可重试的HTTP状态码
    retry_on_network_error=True, # 网络错误是否重试
)
```

**退避算法**：

```
delay = min(backoff_factor * 2^(attempt-1), max_backoff)
jitter = delay * uniform(0, 0.25)  # 添加 0-25% 随机抖动
sleep(delay + jitter)
```

**退避时间示例**（backoff_factor=1.0, max_backoff=30.0）：

```
Attempt 1: 1.0s  + jitter (重试之间等待~1s)
Attempt 2: 2.0s  + jitter
Attempt 3: 4.0s  + jitter
Attempt 4: 8.0s  + jitter
Attempt 5: 16.0s + jitter
Attempt 6+: 30.0s + jitter (cap)
```

### @with_retry 装饰器

对自定义函数应用自动重试：

```python
from agentmesh.a2a_provider import with_retry

# 基本用法（无参数）
@with_retry
def fetch_data(url: str) -> dict:
    response = http_get(url)
    return response

# 自定义参数
@with_retry(
    max_retries=5,
    backoff_factor=2.0,
    retryable_statuses={429, 500, 502, 503, 504},
    retry_on_network_error=True,
)
def flaky_call(url: str) -> dict:
    return json.loads(urllib.request.urlopen(url).read())
```

### HttpProvider 重试策略

```python
client = HttpProvider(
    base_url="http://localhost:8080",
    max_retries=3,
    backoff_factor=1.0,
)

# 以下情况会自动重试：
# - HTTP 5xx (500, 502, 503, 504)
# - HTTP 429 (Rate Limit)
# - 网络错误 (ConnectionError, TimeoutError, OSError)

# 以下情况不重试：
# - HTTP 4xx (除 429)
# - 应用层异常
```

---

## 超时与重试最佳实践

### 1. 本地开发

```python
config = ServerTimeoutConfig(
    request_timeout=60.0,  # 调试时放宽限制
    stream_idle_timeout=300.0,
)
```

### 2. 生产环境

```python
config = ServerTimeoutConfig(
    request_timeout=30.0,  # 严格限制防止资源泄漏
    stream_idle_timeout=30.0,
)

retry = RetryConfig(
    max_retries=3,
    backoff_factor=1.0,
)
```

### 3. 长任务处理

```python
# 使用 SSE 流式订阅，避免请求超时
stream = client.stream_task("long_task_001")
for event, data in stream:
    if event == "state":
        print(f"进度: {data['task_state']}")
    elif event == "completed":
        print(f"结果: {data}")
        break
```

---

## 相关文档

- [Provider 系统](providers.md) — 通信抽象层
- [A2A 协议](a2a-protocol.md) — 消息格式和状态机
- [Agent 编排](agents.md) — 多 Agent 协作模式
- [API Reference - Trace](../api-reference/trace.md) — 追踪 API
- [API Reference - Log](../api-reference/log.md) — 日志 API
