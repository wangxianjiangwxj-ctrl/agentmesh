# A2A 子包 — agentmesh.a2a

**模块**: `agentmesh.a2a`

AgentMesh A2A 协议子包，包含分布式追踪 (`_trace`)、结构化日志 (`_log`) 和类型定义 (`_types`) 的核心组件，以及集成适配器 (`integration`) 子包。

## 导出内容

```python
from agentmesh.a2a import (
    # Trace
    TraceProvider, TraceContext, with_trace_context,
    # Log
    LogLevel, LoggerConfig, StructuredLogger,
)
```

## 子包结构

| 模块 | 说明 |
|------|------|
| `agentmesh.a2a._trace` | 分布式追踪上下文和 Trace ID 传播 |
| `agentmesh.a2a._log` | JSON 结构化日志系统 |
| `agentmesh.a2a._types` | 公共类型定义 |
| `agentmesh.a2a.integration` | 集成适配器子包 |
| `agentmesh.a2a.integration.crewai_adapter` | CrewAI 框架适配器 |
| `agentmesh.a2a.integration.autogen_adapter` | AutoGen 框架适配器 |

---

## `agentmesh.a2a` 自动生成参考

::: agentmesh.a2a
