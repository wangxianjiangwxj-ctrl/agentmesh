# Provider — A2A 通信抽象层

**模块**: `agentmesh.a2a_provider`

Provider 是 AgentMesh A2A 运行时的核心抽象层，定义了与 A2A Server 通信的标准接口。包含内存模拟、HTTP 客户端、任务状态机和统一门面。

---

## A2AResult

A2A 操作结果的封装。

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `success` | `bool` | 操作是否成功 |
| `data` | `Any` | 返回数据 |
| `error` | `A2AError | None` | 错误信息 |
| `task_state` | `str | None` | 任务状态 |

### 工厂方法

```python
result = A2AResult.ok(data, task_state="completed")
result = A2AResult.fail(error, task_state="failed")
```

```python
from agentmesh.a2a_provider import A2AResult

# 成功结果
success = A2AResult.ok({"message": "Hello"}, task_state="submitted")
if success:  # __bool__ 返回 success
    print(success.data)

# 失败结果
from agentmesh.a2a_provider import A2AError
failure = A2AResult.fail(A2AError(404, "Task not found"))
if not failure:
    print(failure.error.message)
```

---

## A2AError

A2A 协议错误异常。

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `code` | `int` | 错误码 |
| `message` | `str` | 错误描述 |
| `recoverable` | `bool` | 是否可恢复（可否重试） |

```python
from agentmesh.a2a_provider import A2AError, ProviderError

# 创建错误
err = A2AError(400, "Invalid task payload", recoverable=False)
print(f"[{err.code}] {err.message}")  # [400] Invalid task payload

# ProviderError 是 A2AError 的子类
p_err = ProviderError(code=503, message="Service unavailable", recoverable=True)
```

---

## A2ATaskState / A2ATaskManager

任务状态机和状态管理器。

### 状态定义

| 状态 | 说明 |
|------|------|
| `PENDING` | 待处理 |
| `SUBMITTED` | 已提交 |
| `WORKING` | 处理中 |
| `INPUT_REQUIRED` | 需要额外输入 |
| `COMPLETED` | 已完成 |
| `FAILED` | 失败 |
| `CANCELED` | 已取消 |

### 合法状态转换

```
PENDING -> SUBMITTED / FAILED / CANCELED
SUBMITTED -> WORKING / FAILED / CANCELED
WORKING -> INPUT_REQUIRED / COMPLETED / FAILED / CANCELED
INPUT_REQUIRED -> WORKING / CANCELED
COMPLETED / FAILED / CANCELED -> (终止态)
```

### A2ATaskManager 用法

```python
from agentmesh.a2a_provider import A2ATaskManager, A2ATaskState

mgr = A2ATaskManager()

# 追踪任务
mgr.track("task_001", A2ATaskState.PENDING)

# 状态转换
mgr.update_state("task_001", A2ATaskState.SUBMITTED)
mgr.update_state("task_001", A2ATaskState.WORKING)
mgr.update_state("task_001", A2ATaskState.COMPLETED)

# 查询
task = mgr.get_task("task_001")
print(task["state"])  # "completed"

# 父子任务链
mgr.track("parent_001", A2ATaskState.SUBMITTED)
mgr.track("child_001", A2ATaskState.PENDING, parent_id="parent_001")
children = mgr.get_children("parent_001")
print(len(children))  # 1

# 清理过期任务
mgr.cleanup(max_age_seconds=3600)
```

---

## A2AProvider (抽象基类)

Provider 抽象基类，定义了与 A2A Server 通信的标准接口。

### 方法

| 方法 | 说明 |
|------|------|
| `send_message(task, auth)` | 发送任务消息 |
| `get_task(task_id, auth)` | 查询任务状态 |
| `cancel_task(task_id, auth)` | 取消任务 |
| `ping()` | 健康检查 |

### 属性

```python
provider.name     # 提供者名称
provider.capabilities  # 能力集合（如 {"local", "no-network"}）
```

---

## MemoryProvider

内存模拟 Provider：不经过网络，直接在内存中模拟 A2A Server。适用于单进程测试、单元测试和离线开发。

```python
from agentmesh.a2a_provider import MemoryProvider

mem = MemoryProvider("test-mem")

# 注册 AgentCard
mem.register_agent_card({
    "name": "test-agent",
    "skills": ["code-review", "debug"],
})

# 查询 AgentCard
card = mem.get_agent_card("test-agent")

# 完整生命周期
task = {"id": "t1", "status": {"state": "submitted"}, "payload": {}}

result = mem.send_message(task)
assert result.success  # task_state == "submitted"

result = mem.get_task("t1")
assert result.data["id"] == "t1"

result = mem.cancel_task("t1")
assert result.task_state == "canceled"
```

---

## A2AFacade

A2A 兼容层统一入口，封装 Provider + TaskManager，对外暴露简洁接口。自动完成 AgentMesh 到 A2A 的协议转换。

```python
from agentmesh.a2a_provider import A2AFacade, MemoryProvider, A2ATaskManager

# 快速创建（使用默认 MemoryProvider）
facade = A2AFacade()

# 指定 Provider
facade = A2AFacade(
    provider=MemoryProvider(),
    task_manager=A2ATaskManager(),
)

# 切换 Provider
http_provider = HttpProvider("http://localhost:8080")
facade.set_provider(http_provider)

# 发送任务（自动跟踪状态）
task = {"id": "task_001", "status": {"state": "submitted"}}
result = facade.send_task(task)

# 查询和取消
result = facade.get_task("task_001")
result = facade.cancel_task("task_001")
```

---

## HttpProvider

HTTP Provider：连接到远程 A2A Server 的客户端实现，通过 HTTP REST API 通信。

### 构造函数

```python
HttpProvider(
    base_url="http://localhost:8080",
    name="http",
    timeout_config=None,
    max_retries=3,
    backoff_factor=1.0,
)
```

- `base_url`: 服务器基础 URL
- `timeout_config`: 超时配置（ServerTimeoutConfig）
- `max_retries`: HTTP 重试次数（0 = 不重试）
- `backoff_factor`: 指数退避基值（秒）

### 方法

#### `send_message(task, auth=None) -> A2AResult`

发送任务到服务器。

```python
from agentmesh.a2a_server import HttpProvider

client = HttpProvider("http://localhost:8080")

task = {
    "id": "task_001",
    "status": {"state": "submitted"},
    "payload": {"text": "Hello!"},
}
result = client.send_message(task)
```

#### `get_task(task_id, auth=None) -> A2AResult`

查询任务状态。

```python
result = client.get_task("task_001")
```

#### `cancel_task(task_id, auth=None) -> A2AResult`

取消任务。

```python
result = client.cancel_task("task_001")
```

#### `ping() -> A2AResult`

健康检查。

```python
result = client.ping()
```

#### `register_agent(name, skills=None) -> A2AResult`

注册 AgentCard。

```python
result = client.register_agent("my-agent", ["code", "review"])
```

#### `stream_task(task_id) -> SSEStream`

打开 SSE 流式订阅，实时接收任务状态变化。

```python
stream = client.stream_task("task_001")
for event_type, data in stream:
    print(f"[{event_type}] {data}")
    if event_type == "done":
        break
```

### 重试行为

HttpProvider 在以下情况自动重试：

- HTTP 5xx 服务器错误（500, 502, 503, 504）
- HTTP 429 限流
- 网络层异常（ConnectionError, TimeoutError, OSError）

不重试：

- HTTP 4xx 客户端错误（除 429）

使用指数退避 + 随机抖动。

---

## with_retry 装饰器

重试装饰器，可应用于任意返回字典的函数。

```python
from agentmesh.a2a_provider import with_retry

# 无参数用法
@with_retry
def call_api(url):
    response = http_request(url)
    return {"success": response.ok, "data": response.json()}

# 自定义参数
@with_retry(max_retries=5, backoff_factor=2.0)
def flaky_call(url):
    ...

# 默认参数：max_retries=3, backoff_factor=1.0, max_backoff=30.0
```

---

## 完整示例：跨进程通信

```python
from agentmesh.a2a_server import cmd_server, HttpProvider
import threading
import time

# 启动服务器（后台线程）
def start_server():
    cmd_server(port=8080, daemon=False)

server_thread = threading.Thread(target=start_server, daemon=True)
server_thread.start()
time.sleep(2)

# 创建客户端
client = HttpProvider("http://localhost:8080")

# 健康检查
r = client.ping()
print(f"Server status: {r.data.get('status')}")  # "ok"

# 完整生命周期
task = {"id": "test_001", "status": {"state": "submitted"}, "payload": {"text": "hello"}}
r1 = client.send_message(task)
print(f"Send: success={r1.success}, state={r1.task_state}")

r2 = client.get_task("test_001")
print(f"Get: data={r2.data}")

r3 = client.cancel_task("test_001")
print(f"Cancel: state={r3.task_state}")
```

---

## 另见

- [A2A Test Server 指南](../a2a-test-server.md) — 完整的服务器启动和测试指南
- [Trace API](trace.md) — 追踪上下文与 Provider 集成
- [Log API](log.md) — 服务器端日志记录

---

## `agentmesh.a2a_provider` 自动生成参考

::: agentmesh.a2a_provider
