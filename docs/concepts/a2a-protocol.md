# A2A 协议 (A2A Protocol)

> 跨 Agent 通信的消息格式、状态机与传输协议

---

## 概述

AgentMesh 的 A2A 协议定义了一套简洁但严密的通信契约，涵盖消息格式、任务状态机、流式传输和错误处理。协议的核心设计目标：

- **简单**：消息格式基于纯字典，无需强类型约束
- **完备**：覆盖任务全生命周期（提交 -> 执行 -> 完成/失败/取消）
- **可扩展**：自定义字段可通过 metadata 自由传递
- **兼容**：与 A2A v1.0 规范保持语义一致

---

## 消息格式

### AgentMessage

Agent 之间交换的消息单元，支持多种类型：

```python
# 典型消息结构
message = {
    "id": "msg_a1b2c3d4",
    "sender": "agent-alpha",
    "recipient": "agent-beta",
    "type": "text",           # text / data / tool_call / tool_result / error
    "payload": {
        "text": "分析报告已完成",
        "confidence": 0.85,
    },
    "metadata": {
        "trace_id": "a1b2c3d4e5f6",
        "timestamp": "2026-06-03T10:30:00Z",
    },
}
```

### Task

A2A 协议中任务（Task）是通信的基本单位，以字典形式传递：

```python
task = {
    # 必填
    "id": "task_001",                     # 全局唯一任务 ID

    # 状态（由 TaskManager 管理）
    "status": {
        "state": "submitted",             # pending / submitted / working / input-required / completed / failed / canceled
        "message": "处理中...",            # 人类可读的状态说明
        "timestamp": 1717401600.0,         # 时间戳
    },

    # 荷载
    "payload": {
        "text": "请分析2024年AI趋势",       # 任务内容
    },

    # 结果（完成时填充）
    "result": {
        "data": {"output": "分析结果..."},
    },

    # 元数据
    "metadata": {
        "trace_id": "abc123",
        "agentmesh_fidelity": 0.85,
    },

    # 上下游（TaskManager 维护）
    "parent_id": "",
    "children_ids": [],
}
```

### Task 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | str | 是 | 全局唯一任务标识 |
| `status` | dict | 推荐 | 状态块，包含 `state`, `message`, `timestamp` |
| `payload` | dict | 推荐 | 任务内容 |
| `result` | dict | 否 | 执行结果 |
| `metadata` | dict | 否 | 扩展元数据 |
| `parent_id` | str | 否 | 父任务 ID |
| `children_ids` | list | 否 | 子任务 ID 列表 |

### TaskState

任务状态枚举，定义完整生命周期：

```python
from agentmesh.a2a_provider import A2ATaskState

print(A2ATaskState.PENDING)          # "pending"
print(A2ATaskState.SUBMITTED)        # "submitted"
print(A2ATaskState.WORKING)          # "working"
print(A2ATaskState.INPUT_REQUIRED)   # "input-required"
print(A2ATaskState.COMPLETED)        # "completed"
print(A2ATaskState.FAILED)           # "failed"
print(A2ATaskState.CANCELED)         # "canceled"
```

---

## TaskManager 生命周期

`A2ATaskManager` 是状态机的核心管理器，保证状态转换的合法性并维护任务间的上下游关系。

### 状态转换图

```
                    ┌─────────┐
                    │ PENDING │
                    └────┬────┘
                         │
                    ┌────▼─────┐
               ┌────│ SUBMITTED│────┐
               │    └────┬─────┘    │
               │         │          │
          ┌────▼──┐ ┌───▼───┐  ┌───▼────┐
          │FAILED │ │WORKING│  │CANCELED│
          └───────┘ └───┬───┘  └────────┘
                        │
                  ┌─────▼──────┐
                  │INPUT_REQUIRED│◄────┐
                  └─────┬──────┘     │
                        │            │
                  ┌─────▼──────┐     │
                  │ COMPLETED  │     │
                  └────────────┘     │
                  ┌────────┐         │
                  │ WORKING│─────────┘
                  └────────┘
```

### 完整生命周期示例

```python
from agentmesh.a2a_provider import A2ATaskManager, A2ATaskState

manager = A2ATaskManager()

# 1. 注册新任务
manager.track("task_001", A2ATaskState.PENDING)

# 2. 提交流程
manager.update_state("task_001", A2ATaskState.SUBMITTED)

# 3. 开始执行
manager.update_state("task_001", A2ATaskState.WORKING)

# 4. 需要更多输入
manager.update_state("task_001", A2ATaskState.INPUT_REQUIRED)

# 5. 继续执行
manager.update_state("task_001", A2ATaskState.WORKING)

# 6. 完成
manager.update_state("task_001", A2ATaskState.COMPLETED)

# 查询最终状态
task = manager.get_task("task_001")
print(task["state"])  # "completed"
```

### 上下游追踪

TaskManager 支持父子任务关系，适用于任务分解场景：

```python
# 主任务
manager.track("research_001", A2ATaskState.SUBMITTED)

# 子任务（自动关联到父任务）
manager.track("sub_web_search", A2ATaskState.PENDING, parent_id="research_001")
manager.track("sub_data_analysis", A2ATaskState.PENDING, parent_id="research_001")

# 查询所有子任务
children = manager.get_children("research_001")
print(len(children))  # 2

for child in children:
    print(f"子任务: {child['task_id']} -> {child['state']}")
```

### 自动清理

完成/失败/取消的任务会在超时后自动清理，避免内存泄漏：

```python
# 默认超时 3600 秒（1 小时）
manager.cleanup(max_age_seconds=3600)
```

---

## SSE 流式通信

AgentMesh A2A Server 支持 Server-Sent Events（SSE）流式通信，用于实时订阅任务状态变化。

### 服务器端 SSE 端点

```
GET /stream/{task_id}

Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

### 事件格式

每个 SSE 事件包含 `event` 和 `data` 两个字段：

```
event: state
data: {"success": true, "data": {"id": "task_001"}, "task_state": "working"}

event: completed
data: {"success": true, "data": {"id": "task_001", "result": {"data": {"output": "..."}}}, "task_state": "completed"}

event: done
data: {"success": true, "data": {"message": "Stream ended"}}
```

### 事件类型

| 事件类型 | 说明 | 触发时机 |
|----------|------|----------|
| `state` | 状态变更 | 每次 task_state 变化 |
| `completed` | 任务完成 | 任务进入 completed 状态 |
| `error` | 错误 | 任务失败或资源不存在 |
| `done` | 流结束 | SSE 流正常关闭 |
| `reconnect` | 重连通知 | HTTP 连接中断后自动重连 |
| `stream_timeout` | 流超时 | 超过 stream_idle_timeout 无数据 |
| `heartbeat_timeout` | 心跳超时 | 客户端检测到服务端静默超时 |

### 客户端消费 SSE

```python
from agentmesh.a2a_server import SSEStream

stream = SSEStream(
    base_url="http://localhost:8080",
    task_id="task_001",
    max_retries=3,          # 断线重连次数
    backoff_factor=1.0,     # 退避因子
    timeout=30,             # 连接超时
    heartbeat_timeout=15.0, # 心跳超时
)

# 迭代消费事件
for event_type, data in stream:
    if event_type == "state":
        print(f"进度更新: {data['task_state']} - {data['data']}")
    elif event_type == "completed":
        print(f"任务完成: {data['data']['result']}")
    elif event_type == "done":
        print("流结束")
        break
    elif event_type == "reconnect":
        print(f"重连中... 第 {data['attempt']} 次")
    elif event_type == "error":
        print(f"错误: {data}")
        break
```

### SSE 自动重连

SSE 客户端内置断线重连机制：

```python
# 当 HTTP 连接因 5xx/429 中断时，自动重试
# 重试使用指数退避：1s, 2s, 4s, 8s ... (上限 30s)

stream = SSEStream(
    base_url="http://localhost:8080",
    task_id="task_001",
    max_retries=5,
    backoff_factor=1.0,
)
```

### 空闲超时保护

防止无效连接长期占用资源：

```python
# Server: 60 秒无数据自动关闭
# Client: 15 秒无数据触发 heartbeat_timeout 事件

# 可通过 ServerTimeoutConfig 配置
from agentmesh.a2a_models import ServerTimeoutConfig
config = ServerTimeoutConfig(stream_idle_timeout=120.0)
```

---

## 错误处理协议

### 统一的错误响应格式

所有 A2A 端点返回一致的错误结构：

```python
{
    "success": false,
    "error": {
        "code": "NOT_FOUND",          # 机器可读的错误码
        "message": "Task not found",  # 人类可读的描述
        "recoverable": false,         # 是否可重试恢复
    }
}
```

### 标准错误码

| HTTP 状态码 | 错误码 | 说明 | 可恢复 |
|-------------|--------|------|--------|
| 400 | `INVALID_REQUEST` | 请求参数无效 | 否 |
| 404 | `NOT_FOUND` | 资源不存在 | 否 |
| 422 | `VALIDATION_ERROR` | 数据验证失败 | 否 |
| 429 | `SERVICE_UNAVAILABLE` | 限流 | 是 |
| 500 | `INTERNAL_ERROR` | 服务器内部错误 | 是 |
| 503 | `SERVICE_UNAVAILABLE` | 服务不可用 | 是 |

### 错误映射

```python
# 内部 A2AError -> HTTP 错误码
INTERNAL_TO_ERROR_CODE = {
    400: "INVALID_REQUEST",
    404: "NOT_FOUND",
    409: "INVALID_REQUEST",
    500: "INTERNAL_ERROR",
}

# HTTP 状态码 -> 错误码
ERROR_CODE_MAP = {
    400: "INVALID_REQUEST",
    404: "NOT_FOUND",
    405: "INVALID_REQUEST",
    422: "VALIDATION_ERROR",
    429: "SERVICE_UNAVAILABLE",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}
```

---

## 与 MCP 的区别

AgentMesh A2A 协议和 Anthropic MCP（Model Context Protocol）有不同的定位和设计哲学：

| 维度 | AgentMesh A2A | MCP |
|------|--------------|-----|
| **核心目标** | Agent-to-Agent 协作 | Model-to-Context 集成 |
| **通信模式** | 双向（Agent ↔ Agent） | 双向（Host ↔ Server） |
| **消息单元** | Task（任务） | Resource / Tool / Prompt |
| **状态管理** | 有状态（Task State Machine） | 无状态（请求-响应） |
| **传输协议** | HTTP + SSE | JSON-RPC 2.0 |
| **数据流** | 支持流式推送（SSE） | 请求-响应模式 |
| **任务生命周期** | 完整生命周期（7种状态） | 无内置状态机 |
| **嵌套/依赖** | 支持父子任务、上下游追踪 | 无 |
| **Agent 发现** | Agent Card 注册/查询 | 资源/工具列表 |
| **错误处理** | 结构化错误码 + 可恢复标记 | JSON-RPC 错误对象 |
| **最适用于** | 多 Agent 协作工作流 | LLM 上下文增强 |

**一句话总结**：MCP 让 LLM 能操作外部工具和数据，AgentMesh A2A 让多个 Agent 能协作完成复杂任务。

---

## 协议扩展点

### Metadata

通过 `metadata` 字段传递自定义信息，不影响核心协议：

```python
task["metadata"] = {
    "agentmesh_schema_version": "2.1",
    "agentmesh_fidelity": 0.85,
    "agentmesh_confidence": 0.78,
    "agentmesh_sender": "scout-alpha",
    # 任何框架无关的扩展字段
}
```

### Agent Card

Agent 注册时提供的能力描述卡片：

```python
card = {
    "name": "research-agent",
    "skills": ["web-search", "data-analysis", "report-generation"],
    "endpoints": {
        "http": "http://agent-host:8080/a2a",
        "ws": "ws://agent-host:8081/ws",
    },
}
```

---

## 相关文档

- [Provider 系统](providers.md) — 通信抽象层实现
- [运行时与可观测性](runtime.md) — Server/Client 生命周期
- [API Reference](../api-reference/index.md) — 完整 API 文档
- [快速开始](../quickstart.md) — 5 分钟上手
