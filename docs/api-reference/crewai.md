# CrewAI Adapter — CrewAI 集成适配器

**模块**: `agentmesh.a2a.integration.crewai_adapter`

AgentMesh 与 CrewAI 框架的集成适配器。将 AgentMesh 操作封装为 CrewAI `BaseTool`，实现跨框架的 Agent 通信。

## 设计思路

- **Provider 层集成**：通过 `_A2AToolProxy` 将 AgentMesh 操作暴露为 CrewAI Agent 可调用的 Tool
- **HTTP 传输**：所有通信通过 HTTP REST API 发送到 AgentMesh A2A Server
- **零依赖降级**：当 CrewAI 包未安装时，自动使用 `_CrewAIProxyAgent` 代理，确保代码不会硬失败

## 核心类型

### CardType

标准 A2A Card 类型枚举。

| 成员 | 值 | 说明 |
|------|-----|------|
| `TEXT` | `"text"` | 文本消息 |
| `DATA` | `"data"` | 数据消息 |
| `TOOL_CALL` | `"tool_call"` | 工具调用 |
| `TOOL_RESULT` | `"tool_result"` | 工具结果 |
| `ERROR` | `"error"` | 错误消息 |
| `CUSTOM` | `"custom"` | 自定义 |

### CardStatus

| 状态 | 说明 |
|------|------|
| `PENDING` | 待发送 |
| `DELIVERED` | 已送达 |
| `FAILED` | 发送失败 |
| `TIMEOUT` | 超时 |

### A2AToolDef

Tool 定义元数据。

```python
from agentmesh.a2a.integration.crewai_adapter import A2AToolDef, CardType

tool_def = A2AToolDef(
    name="agentmesh_send",
    description="Send a card through AgentMesh to another agent",
    card_type=CardType.TEXT,
    timeout_seconds=30.0,
)
```

### CrewAIAgentConfig

CrewAI Agent 配置。

```python
from agentmesh.a2a.integration.crewai_adapter import CrewAIAgentConfig

config = CrewAIAgentConfig(
    role="researcher",
    goal="Research and summarize AI trends",
    backstory="I am an experienced AI researcher.",
    allow_delegation=True,
    tools=[],  # 额外 CrewAI tools
    agentmesh_tool_name="agentmesh_send",
)
```

### CardSendResult / CardReceiveResult

Card 发送和接收的结果封装。

```python
# 发送结果
result = adapter.send_card(
    sender_id="agent_a",
    recipient_id="agent_b",
    payload={"text": "Hello!"},
)
print(f"Card {result.card_id} -> {result.recipient_agent}: {result.status}")

# 接收结果
card = adapter.receive_card(agent_id="agent_b")
if card:
    print(f"From: {card.sender_agent}, Type: {card.card_type}")
    print(f"Payload: {card.payload}")
```

---

## CrewAIAdapter

CrewAI 适配器的具体实现，使用 HTTP 传输到 AgentMesh A2A Server。

### 生命周期

```python
from agentmesh.a2a.integration.crewai_adapter import CrewAIAdapter

adapter = CrewAIAdapter()

# 连接服务器
adapter.connect("http://localhost:8080", timeout_seconds=30.0)

# 检查连接
print(adapter.is_connected)  # True

# 断开连接
adapter.disconnect()
```

### Agent 创建与管理

```python
from agentmesh.a2a.integration.crewai_adapter import (
    CrewAIAdapter, CrewAIAgentConfig,
)

adapter = CrewAIAdapter()
adapter.connect("http://localhost:8080")

# 创建 Agent（自动注册到服务器）
agent = adapter.create_agent(
    config=CrewAIAgentConfig(
        role="researcher",
        goal="Research AI topics",
        backstory="Expert researcher.",
    ),
    agent_id="researcher_001",
)
# agent 的 tools 列表中已包含 A2ATool

# 手动注册
adapter.register_agent("custom_agent_001", agent)

# 注销
adapter.unregister_agent("custom_agent_001")
```

### Card 操作

```python
# 发送 Card
send_result = adapter.send_card(
    sender_id="agent_a",
    recipient_id="agent_b",
    payload={"text": "Analyze the attached data", "data_keys": ["q1", "q2"]},
    card_type=CardType.TEXT,
    metadata={"priority": "high"},
)

# 阻塞接收（等待直到有消息）
receive_result = adapter.receive_card(
    agent_id="agent_b",
    timeout_seconds=30.0,
)
if receive_result:
    print(receive_result.payload)

# 非阻塞轮询
cards = adapter.poll_cards(
    agent_id="agent_b",
    max_count=10,
    timeout_seconds=1.0,
)
```

### Tool 管理

```python
from agentmesh.a2a.integration.crewai_adapter import A2AToolDef, CardType

# 创建自定义 Tool
tool = adapter.create_a2a_tool(
    A2AToolDef(
        name="agentmesh_analyze",
        description="Send analysis request through AgentMesh",
        card_type=CardType.DATA,
        timeout_seconds=60.0,
    )
)

# 查询已注册 Tools
tools = adapter.list_registered_tools()
for t in tools:
    print(f"Tool: {t.name} ({t.card_type})")
```

### 任务生命周期

```python
# 启动任务
task_id = adapter.start_agent_task(
    agent_id="agent_b",
    task_description="Write a summary of Q3 results",
    context={"quarter": "Q3", "data_url": "https://..."},
)

# 查询任务结果
result = adapter.get_task_result(
    agent_id="agent_b",
    task_id=task_id,
    timeout_seconds=30.0,
)
```

### 健康检查

```python
health = adapter.health_check()
print(f"Status: {health['status']}")
print(f"Latency: {health['latency_ms']}ms")
print(f"Registered agents: {health['registered_agents']}")
```

---

## 完整示例

```python
from agentmesh.a2a.integration.crewai_adapter import (
    CrewAIAdapter, CrewAIAgentConfig, CardType,
)

# 1. 创建适配器并连接
adapter = CrewAIAdapter()
adapter.connect("http://localhost:8080")

# 2. 创建两个 Agent
researcher = adapter.create_agent(
    CrewAIAgentConfig(
        role="researcher",
        goal="Research AI safety topics",
    ),
    agent_id="researcher",
)

writer = adapter.create_agent(
    CrewAIAgentConfig(
        role="writer",
        goal="Write comprehensive reports",
    ),
    agent_id="writer",
)

# 3. 发送研究请求
result = adapter.send_card(
    sender_id="researcher",
    recipient_id="writer",
    payload={"text": "Please write a report on AI safety"},
    card_type=CardType.TEXT,
)

# 4. 接收回复
reply = adapter.receive_card(agent_id="researcher", timeout_seconds=10.0)
if reply:
    print(f"收到来自 {reply.sender_agent} 的回复: {reply.payload}")

# 5. 清理
adapter.unregister_agent("researcher")
adapter.unregister_agent("writer")
adapter.disconnect()
```

---

## 集成协议

### CrewAI 兼容性

`CrewAIAgentProtocol` 定义了适配器兼容的接口：

```python
class CrewAIAgentProtocol:
    role: str
    goal: str
    backstory: str
    allow_delegation: bool
    tools: List[Any]
```

适配器自动处理 CrewAI 包的导入：包未安装时使用 `_CrewAIProxyAgent` 代理，确保代码在无 CrewAI 环境下也能运行。

---

## 另见

- [AutoGen Adapter](autogen.md) — 另一个框架适配器实现
- [Provider API](provider.md) — 底层 Provider 抽象
- [A2A Test Server 指南](../a2a-test-server.md) — 搭建测试环境
