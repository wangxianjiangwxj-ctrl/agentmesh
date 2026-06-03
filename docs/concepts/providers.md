# Provider 系统 (Provider System)

> A2A 通信的抽象层，连接 Agent 与 A2A 运行时的桥梁

---

## 什么是 Provider

Provider 是 AgentMesh 中 A2A 通信的抽象基类，定义了与 A2A Server 通信的标准接口。通过 Provider，Agent 可以发送任务、查询状态、取消操作，而无需关心底层通信细节。

```
┌─────────────────────────────────────────────────────┐
│                    Agent / 应用层                      │
│                                                       │
│     A2AFacade (统一入口)                               │
│         │                                              │
│         ├── MemoryProvider  (单进程 / 内存模拟)        │
│         ├── HttpProvider    (远程 A2A Server / HTTP)   │
│         └── 自定义 Provider  (扩展接口)                │
│                                                       │
│     A2ATaskManager (状态机管理)                        │
└─────────────────────────────────────────────────────┘
```

**核心职责**：

- 抽象化底层通信：本地内存 VS 远程 HTTP 对上层透明
- 标准化接口：`send_message`, `get_task`, `cancel_task`
- 可扩展性：开发者可以接入自己的传输层

---

## 核心接口

### A2AProvider (抽象基类)

所有 Provider 必须继承的抽象基类，定义标准接口：

```python
class A2AProvider:
    """A2A Provider 抽象基类

    子类必须实现: send_message, get_task, cancel_task
    可选实现: send_streaming, fetch_agent_card, ping
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._capabilities: set = set()

    @property
    def name(self) -> str:
        """返回 Provider 名称"""
        return self._name

    @property
    def capabilities(self) -> set:
        """返回 Provider 能力集合 (如 {"local"}, {"http", "network"})"""
        return self._capabilities

    def send_message(self, task: dict, auth: dict = None) -> A2AResult:
        """发送任务消息到 A2A Server

        Args:
            task: A2A Task 字典，必须包含 id 字段
            auth: 可选的认证信息

        Returns:
            A2AResult: 操作结果封装
        """
        raise NotImplementedError

    def get_task(self, task_id: str, auth: dict = None) -> A2AResult:
        """查询任务状态

        Args:
            task_id: 任务唯一标识
            auth: 可选的认证信息

        Returns:
            A2AResult: 包含任务数据的操作结果
        """
        raise NotImplementedError

    def cancel_task(self, task_id: str, auth: dict = None) -> A2AResult:
        """取消一个正在执行的任务

        Args:
            task_id: 任务唯一标识
            auth: 可选的认证信息

        Returns:
            A2AResult: 操作结果，成功时 task_state 为 "canceled"
        """
        raise NotImplementedError

    def ping(self) -> A2AResult:
        """健康检查，测试 Provider 可用性"""
        return A2AResult.ok({"status": "ok", "provider": self._name})
```

### A2AResult (操作结果封装)

所有 Provider 方法的返回类型，统一封装成功/失败状态：

```python
class A2AResult:
    """A2A 操作结果封装

    Attributes:
        success: 操作是否成功
        data: 成功时的返回数据
        error: 失败时的错误信息 (A2AError / dict / str)
        task_state: 当前任务状态 (如 "submitted", "completed")
    """

    @classmethod
    def ok(cls, data: dict, task_state: str = None) -> A2AResult:
        """创建成功结果"""
        return cls(True, data=data, task_state=task_state)

    @classmethod
    def fail(cls, error, task_state: str = None) -> A2AResult:
        """创建失败结果"""
        return cls(False, error=error, task_state=task_state)

    def __bool__(self):
        return self.success
```

**使用模式**：

```python
result = provider.send_message(task)
if result:
    print(f"成功: {result.task_state}")
else:
    print(f"失败: {result.error}")
```

---

## MemoryProvider (内存模拟)

MemoryProvider 是 AgentMesh 内置的本地内存 Provider，不经过网络，直接在进程中模拟 A2A Server 的行为。

**适用场景**：

- 单元测试和集成测试
- 离线开发和原型验证
- 单进程内的多 Agent 模拟
- CI/CD 管线中无需启动外部服务

```python
from agentmesh.a2a_provider import MemoryProvider

# 创建 MemoryProvider
mem = MemoryProvider("local-test")

# 注册 Agent Card
mem.register_agent_card({
    "name": "research-agent",
    "skills": ["web-search", "data-analysis"],
    "endpoints": {}
})

# 查询 Agent Card
card = mem.get_agent_card("research-agent")
print(card["skills"])  # ["web-search", "data-analysis"]

# 发送任务（内存操作，无网络）
task = {
    "id": "task_001",
    "status": {"state": "submitted"},
    "payload": {"text": "分析报告"}
}
result = mem.send_message(task)
assert result.success  # True
assert result.task_state == "submitted"

# 查询任务
result = mem.get_task("task_001")
print(result.data["id"])  # "task_001"

# 取消任务
result = mem.cancel_task("task_001")
print(result.task_state)  # "canceled"
```

**特点**：

- 零依赖：不需要安装 FastAPI / uvicorn
- 闪电速度：没有网络往返，纯内存操作
- 完整语义：支持完整的任务生命周期
- Agent Card 注册：支持 Agent 发现能力

---

## HttpProvider (远程 HTTP)

HttpProvider 通过 HTTP 协议与远程 A2A Server 通信，实现跨进程、跨主机的 Agent 协作。

**适用场景**：

- 跨进程 Agent 通信
- 分布式多 Agent 系统
- 跨语言协作（Server 可以对接不同语言的 Agent）
- 生产环境部署

```python
from agentmesh.a2a_server import HttpProvider

# 连接远程 A2A Server
client = HttpProvider(
    base_url="http://remote-server:8080",
    timeout_config=ServerTimeoutConfig(
        request_timeout=30.0,
        connect_timeout=10.0,
    ),
    max_retries=3,
    backoff_factor=1.0,
)

# 发送任务
task = {
    "id": "task_remote_001",
    "status": {"state": "submitted"},
    "payload": {"text": "跨进程协作任务"},
}
result = client.send_message(task)

# SSE 流式订阅
stream = client.stream_task("task_remote_001")
for event_type, data in stream:
    print(f"[{event_type}] {data}")
    if event_type == "done":
        break
```

**内置重试机制**：

```python
# HttpProvider 自动处理以下情况的指数退避重试：
# - 5xx 服务器错误 (500, 502, 503, 504)
# - 429 限流 (rate limit)
# - 网络错误 (ConnectionError, TimeoutError, OSError)

# 不会重试：
# - 4xx 客户端错误 (除 429)
# - 非网络异常

# 配置重试参数
client = HttpProvider(
    base_url="http://localhost:8080",
    max_retries=5,         # 最大重试次数
    backoff_factor=2.0,    # 退避因子（2^attempt * factor)
)
```

---

## A2AFacade (统一入口)

A2AFacade 封装了 Provider + TaskManager，对外暴露简洁的统一接口，自动完成消息转换、状态管理和 Provider 路由。

```python
from agentmesh.a2a_provider import A2AFacade, MemoryProvider, A2ATaskManager

# 创建 Facade（自动使用 MemoryProvider 和新的 TaskManager）
facade = A2AFacade()

# 自定义 Provider
facade = A2AFacade(
    provider=MemoryProvider("custom"),
    task_manager=A2ATaskManager(),
)

# 运行时切换 Provider
http_client = HttpProvider("http://localhost:8080")
facade.set_provider(http_client)

# 使用统一接口
task = {"id": "demo", "status": {"state": "submitted"}}
result = facade.send_task(task)      # 自动追踪状态
result = facade.get_task("demo")     # 通过 Provider 查询
result = facade.cancel_task("demo")  # 自动更新状态
```

**Facade 的内部工作流**：

```
Agent / 应用层
    │
    └── facade.send_task(task)
         │
         ├── A2ATaskManager.track(id, "submitted")
         │   └── 验证状态转换合法性
         │
         └── provider.send_message(task)
              │
              ├── (MemoryProvider) 直接内存操作
              └── (HttpProvider)   HTTP POST /send
                   │
                   ├── ✅ 成功 → 返回 task_state
                   └── ❌ 失败 → 指数退避重试
                   └── ❌ 全部失败 → 返回 A2AResult.fail
```

---

## A2ATaskManager (状态机管理器)

任务状态由 `A2ATaskManager` 统一管理，确保状态转换合法、支持上下游追踪。

```python
from agentmesh.a2a_provider import A2ATaskManager, A2ATaskState

manager = A2ATaskManager()

# 跟踪任务
manager.track("task_001", A2ATaskState.PENDING)
manager.track("child_001", A2ATaskState.PENDING, parent_id="task_001")

# 更新状态
manager.update_state("task_001", A2ATaskState.SUBMITTED)
manager.update_state("task_001", A2ATaskState.WORKING)
manager.update_state("task_001", A2ATaskState.COMPLETED)

# 查询子任务
children = manager.get_children("task_001")
print(len(children))  # 1
```

**状态转换矩阵**：

| 当前状态 | 可转换到 |
|----------|----------|
| pending | submitted, failed, canceled |
| submitted | working, failed, canceled |
| working | input-required, completed, failed, canceled |
| input-required | working, canceled |
| completed | (终态) |
| failed | (终态) |
| canceled | (终态) |

**非法转换会被拦截**：

```python
try:
    manager.update_state("task_001", A2ATaskState.WORKING)
    # 如果 task_001 已经是 COMPLETED，这里会抛出 A2AError
except A2AError:
    print("非法状态转换被拦截")
```

---

## 工作流程图示

### 基本发送流程

```
发送方                          A2AFacade                      Provider                      接收方
  │                               │                              │                              │
  │── send_task(task) ──────────> │                              │                              │
  │                               │── TaskManager.track() ──────>│                              │
  │                               │                              │── 存储任务状态 ─────────────>│
  │                               │── provider.send_message() ──>│                              │
  │                               │                              │── (内存/HTTP) ──────────────>│
  │                               │<── A2AResult ───────────────│                              │
  │<── A2AResult ───────────────│                              │                              │
```

### 查询与取消流程

```
查询方                          A2AFacade                      Provider
  │                               │                              │
  │── get_task(id) ──────────────  >                              │
  │                               │── provider.get_task(id) ────>│
  │                               │<── task_data ───────────────│
  │<── A2AResult ───────────────│                              │
  │                               │                              │
  │── cancel_task(id) ──────────── >                              │
  │                               │── provider.cancel_task(id) ──>│
  │                               │── TaskManager.update(cancel)  │
  │                               │<── A2AResult ───────────────│
  │<── A2AResult ───────────────│                              │
```

---

## 错误处理

### A2AError (协议错误)

```python
from agentmesh.a2a_provider import A2AError

# 创建错误
error = A2AError(code=404, message="Task not found", recoverable=False)

# 可恢复的错误（会自动重试）
error = A2AError(code=503, message="Service unavailable", recoverable=True)

print(error)  # "[404] Task not found"
```

### ProviderError (提供者错误)

```python
from agentmesh.a2a_provider import ProviderError

# 网络错误 / 上游服务失败
error = ProviderError(
    code=500,
    message="Failed to reach upstream A2A server",
    recoverable=True,  # 网络错误通常是可恢复的
)
```

---

## 扩展自定义 Provider

开发者可以实现自己的 Provider 来接入不同的传输层。

```python
from agentmesh.a2a_provider import A2AProvider, A2AResult

class WebSocketProvider(A2AProvider):
    """自定义 WebSocket Provider 示例"""

    def __init__(self, ws_url: str):
        super().__init__(name="websocket")
        self._ws_url = ws_url
        self._capabilities.add("websocket")
        self._capabilities.add("real-time")

    def send_message(self, task: dict, auth: dict = None) -> A2AResult:
        # 实现 WebSocket 发送逻辑
        try:
            response = self._ws_send(json.dumps(task))
            return A2AResult.ok(response, task_state="submitted")
        except ConnectionError as e:
            return A2AResult.fail(
                A2AError(503, f"WebSocket send failed: {e}", recoverable=True)
            )

    def get_task(self, task_id: str, auth: dict = None) -> A2AResult:
        # 实现 WebSocket 查询逻辑
        ...

    def cancel_task(self, task_id: str, auth: dict = None) -> A2AResult:
        # 实现 WebSocket 取消逻辑
        ...

# 使用自定义 Provider
ws_provider = WebSocketProvider("ws://a2a-server:8080/ws")
facade = A2AFacade(provider=ws_provider)
```

**扩展步骤**：

1. 继承 `A2AProvider`
2. 实现三个抽象方法：`send_message`, `get_task`, `cancel_task`
3. 可选覆盖 `ping` 方法
4. 在 `capabilities` 中添加自定义能力标识
5. 通过 `A2AFacade` 对外暴露统一入口

---

## Provider 选型指南

| 场景 | 推荐 Provider | 原因 |
|------|--------------|------|
| 单元测试 | MemoryProvider | 零依赖、速度快 |
| 本地开发 | MemoryProvider | 无需启动 Server |
| CI/CD 测试 | MemoryProvider | 无需网络，稳定可靠 |
| 跨进程通信 | HttpProvider | 标准 HTTP 协议 |
| 分布式部署 | HttpProvider | 支持远程节点 |
| 实时通信 | 自定义 WebSocketProvider | 低延迟双向通信 |
| 消息队列 | 自定义 KafkaProvider | 高吞吐、持久化 |

---

## 相关文档

- [A2A 协议](a2a-protocol.md) — 了解消息格式和状态机
- [运行时](runtime.md) — Server/Client 生命周期
- [API Reference - Provider](../api-reference/provider.md) — 完整 API 文档
- [快速开始](../quickstart.md) — 5 分钟上手
