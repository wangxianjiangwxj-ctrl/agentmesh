# Log — 结构化日志

**模块**: `agentmesh.a2a._log`

AgentMesh 的结构化日志系统，输出 JSON 格式的日志条目，自动附加追踪上下文和组件元数据。

## 核心概念

每条日志是一个 JSON 行，包含以下字段：

| 字段 | 说明 |
|------|------|
| `timestamp` | ISO-8601 UTC 时间戳 |
| `level` | `DEBUG` / `INFO` / `WARN` / `ERROR` |
| `component` | 组件名称 |
| `event` | 事件名称（如 `"card_sent"`, `"error"`） |
| `message` | 人类可读的描述（可选） |
| `trace_id` | 来自当前 TraceContext（如存在） |
| `span_id` | 来自当前 TraceContext（如存在） |
| `duration_ms` | 耗时毫秒（可选） |
| `error` | 错误信息（可选） |
| 额外字段 | 调用日志方法时传入的任意关键字参数 |

---

## LogLevel

日志严重级别枚举，映射到 stdlib 日志级别。

| 成员 | stdlib 映射值 | 说明 |
|------|-------------|------|
| `DEBUG` | `logging.DEBUG` (10) | 调试信息 |
| `INFO` | `logging.INFO` (20) | 一般信息 |
| `WARN` | `logging.WARN` (30) | 警告 |
| `ERROR` | `logging.ERROR` (40) | 错误 |

### 方法

#### `to_stdlib() -> int`

返回对应的 stdlib 日志级别常量。

```python
level = LogLevel.INFO
assert level.to_stdlib() == logging.INFO
```

#### `from_stdlib(level: int) -> LogLevel`

从 stdlib 级别反向映射到 LogLevel。

```python
level = LogLevel.from_stdlib(logging.WARNING)
assert level == LogLevel.WARN
```

---

## LoggerConfig

全局日志器配置。

### 属性

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `level` | `LogLevel` | `INFO` | 最低输出级别 |
| `output` | `str` | `"stderr"` | 输出目标：`"stderr"`, `"stdout"`, 或文件路径 |
| `format` | `str` | `"json"` | 输出格式（当前仅支持 JSON） |
| `extra_fields` | `Dict[str, Any]` | `{}` | 注入到每条日志的默认字段 |

---

## StructuredLogger

JSON 结构化日志器，自动附加追踪上下文。

### 构造函数

```python
StructuredLogger(component: str, *, config: Optional[LoggerConfig] = None)
```

- `component`: 组件名称，将出现在每条日志的 `component` 字段
- `config`: 自定义配置，不传则使用全局默认配置

### 类方法

#### `configure(config: LoggerConfig) -> None`

设置全局默认日志器配置。

```python
from agentmesh.a2a import StructuredLogger, LogLevel, LoggerConfig

StructuredLogger.configure(
    LoggerConfig(
        level=LogLevel.DEBUG,
        output="stdout",
    )
)
```

### 日志方法

所有日志方法使用相同的签名：

- `event`: 事件名称（必须）
- `message`: 人类可读描述（可选关键字）
- `duration_ms`: 耗时毫秒（可选）
- `error`: 错误信息（可选，可为异常对象、字典或字符串）
- `**extra`: 任意关键字参数，作为额外 JSON 字段

#### `debug(event, *, message=None, duration_ms=None, error=None, **extra)`

#### `info(event, *, message=None, duration_ms=None, error=None, **extra)`

#### `warn(event, *, message=None, duration_ms=None, error=None, **extra)`

#### `error(event, *, message=None, duration_ms=None, error=None, **extra)`

---

## 完整示例

### 基本用法

```python
from agentmesh.a2a import StructuredLogger, LogLevel, LoggerConfig

# 全局配置
StructuredLogger.configure(LoggerConfig(
    level=LogLevel.INFO,
    output="stdout",
))

# 创建日志器
log = StructuredLogger("my-component")

# 基本日志
log.info("card_sent", detail="Task card dispatched")
log.error("connection_failed", error="timeout", peer="agent-b")

# 带异常的错误日志
try:
    risky_operation()
except ValueError as e:
    log.error("validation_error", message="Input validation failed", error=e)

# 带耗时测量的日志
import time
start = time.monotonic()
result = expensive_operation()
elapsed = (time.monotonic() - start) * 1000
log.info("operation_complete", message="Processing done", duration_ms=elapsed, result_size=len(result))
```

### 与追踪集成

```python
from agentmesh.a2a import (
    StructuredLogger, TraceProvider, with_trace_context,
)

log = StructuredLogger("my-component")
provider = TraceProvider()

with with_trace_context(provider.new_context()) as ctx:
    log.info("work_started", step="phase1")
    # 日志会自动包含 trace_id 和 span_id
    # {"timestamp": "...", "level": "INFO", "component": "my-component",
    #  "event": "work_started", "step": "phase1",
    #  "trace_id": "abc...", "span_id": "def..."}

# 退出上下文后，日志不再附加追踪 ID
log.info("work_done")
# 无 trace_id/span_id 字段
```

### 自定义配置

```python
# 输出到文件
StructuredLogger.configure(LoggerConfig(
    level=LogLevel.DEBUG,
    output="/var/log/agentmesh.log",
))

# 全局额外字段
StructuredLogger.configure(LoggerConfig(
    extra_fields={"env": "production", "region": "us-east-1"},
))

# 每条日志都会自动包含 extra_fields 中的字段
log = StructuredLogger("api")
log.info("request", method="GET", path="/health")
# 日志包含: env, region, method, path
```

---

## 输出示例

```json
{"timestamp": "2026-06-03T08:00:00.000000+00:00", "level": "INFO", "component": "my-component", "event": "card_sent", "detail": "Task card dispatched", "direction": "outbound"}
{"timestamp": "2026-06-03T08:00:00.100000+00:00", "level": "ERROR", "component": "my-component", "event": "connection_failed", "error": "timeout", "peer": "agent-b"}
{"timestamp": "2026-06-03T08:00:01.000000+00:00", "level": "INFO", "component": "my-component", "event": "work_started", "step": "phase1", "trace_id": "a1b2c3d4e5f6...", "span_id": "a1b2c3d4e5f6..."}
```

---

## 另见

- [Trace API](trace.md) — 追踪上下文自动注入日志
- [Provider API](provider.md) — 服务器使用 StructuredLogger 记录请求
