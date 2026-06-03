# Trace — 分布式追踪

**模块**: `agentmesh.a2a._trace`

AgentMesh 的分布式追踪系统基于 OpenTelemetry 兼容的 Trace ID 传播协议，用于在跨 Agent 协作中追踪消息链路。

## 核心概念

- **Trace ID** — 一次完整协作的唯一标识（32 位十六进制字符串）
- **Span ID** — 单次操作的标识（16 位十六进制字符串）
- **Parent Span ID** — 调用方的 Span ID，用于构建调用链
- **Baggage** — 随追踪上下文传播的键值对元数据

---

## TraceContext

不可变的追踪上下文对象，包含分布式追踪标识符。

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `trace_id` | `str` | 全局唯一的 32 字符十六进制追踪标识 |
| `parent_span_id` | `str` | 调用方的 Span ID，根 Span 为空字符串 |
| `span_id` | `str` | 当前 Span 标识（16 字符十六进制） |
| `baggage` | `Dict[str, str]` | 随追踪传播的可选键值对 |

### 方法

#### `to_header() -> Dict[str, str]`

将追踪上下文序列化为扁平的消息头字典，用于网络传播。

```python
from agentmesh.a2a import TraceProvider

ctx = TraceProvider().new_context()
headers = ctx.to_header()
# 返回: {"trace_id": "abc...", "parent_span_id": "", "span_id": "def...", "baggage": ""}
```

#### `from_header(headers) -> Optional[TraceContext]`

从消息头字典解析 TraceContext。缺失必需字段时返回 `None`。

```python
from agentmesh.a2a import TraceContext

headers = {
    "trace_id": "abc123...",
    "span_id": "def456...",
    "parent_span_id": "",
    "baggage": "key=val",
}
ctx = TraceContext.from_header(headers)
```

#### `new_child() -> TraceContext`

创建子 Span：保留父 Trace ID，当前 Span 成为子 Span 的父。

```python
child = ctx.new_child()
# child.trace_id == ctx.trace_id
# child.parent_span_id == ctx.span_id
```

#### `with_baggage(key, value) -> TraceContext`

返回带附加 baggage 条目的新上下文（原始对象不变）。

```python
ctx = ctx.with_baggage("user_id", "007")
```

---

## TraceProvider

追踪工厂，用于创建和管理分布式追踪上下文。

### 方法

#### `new_trace_id() -> str`

生成新的 32 字符十六进制 Trace ID（16 个随机字节）。

```python
trace_id = TraceProvider.new_trace_id()
```

#### `new_span_id() -> str`

生成新的 16 字符十六进制 Span ID（8 个随机字节）。

```python
span_id = TraceProvider.new_span_id()
```

#### `new_context(baggage=None) -> TraceContext`

创建全新的根 TraceContext，带新的 Trace ID 和 Span ID。

```python
provider = TraceProvider()
ctx = provider.new_context(baggage={"env": "production"})
```

#### `child_context(parent, baggage=None) -> TraceContext`

创建子 Span 上下文，保留父 Trace ID。

```python
child = provider.child_context(parent, baggage={"step": "analysis"})
```

#### `inject(context, headers=None) -> Dict[str, str]`

将追踪上下文注入到消息头字典中（原地修改并返回）。

```python
headers = {"Content-Type": "application/json"}
headers = provider.inject(ctx, headers)
# headers 现在包含 trace_id, span_id, parent_span_id, baggage
```

#### `extract(headers) -> Optional[TraceContext]`

从消息头提取追踪上下文。

```python
ctx = TraceProvider.extract(incoming_headers)
```

#### `get_current_context() -> Optional[TraceContext]`

返回当前线程的活动 TraceContext。

```python
active_ctx = TraceProvider.get_current_context()
```

---

## with_trace_context

上下文管理器，在作用域内设置当前线程的活动 TraceContext。

```python
from agentmesh.a2a import TraceProvider, with_trace_context

provider = TraceProvider()

# 自动创建根上下文
with with_trace_context() as ctx:
    # 在此作用域内，TraceProvider.get_current_context() 返回 ctx
    do_work()

# 使用已有上下文
with with_trace_context(context=existing_ctx) as ctx:
    do_work()

# 指定 Provider
with with_trace_context(provider=provider) as ctx:
    do_work()
```

---

## 完整示例

```python
from agentmesh.a2a import TraceProvider, TraceContext, with_trace_context

# 1. 创建根追踪上下文
provider = TraceProvider()
root = provider.new_context(baggage={"service": "agent-a"})

# 2. 在根上下文中执行工作
with with_trace_context(context=root) as ctx:
    print(f"Trace: {ctx.trace_id}, Span: {ctx.span_id}")

    # 3. 创建子 Span，模拟远程调用
    child = provider.child_context(ctx, baggage={"step": "remote-call"})
    # 4. 序列化用于网络传输
    headers = provider.inject(child)
    # headers = {"trace_id": "...", "span_id": "...", "parent_span_id": "...", "baggage": "service=agent-a,step=remote-call"}

# 5. 在接收端恢复上下文
received_ctx = TraceProvider.extract(headers)
with with_trace_context(context=received_ctx) as restored:
    print(f"Restored: {restored.trace_id}, Parent: {restored.parent_span_id}")
```

---

## 另见

- [Log API](log.md) — 结构化日志会自动附加当前追踪上下文
- [Provider API](provider.md) — Provider 层使用 Trace ID 追踪任务
