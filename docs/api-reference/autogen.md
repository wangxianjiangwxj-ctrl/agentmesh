# AutoGen Adapter — AutoGen 集成适配器

**模块**: `agentmesh.a2a.integration.autogen_adapter`

AgentMesh 与 AutoGen (pyautogen) 框架的集成适配器。将 AgentMesh 通信层接入 AutoGen 的 `ConversableAgent`，实现跨框架的 Agent 消息路由。

## 设计思路

- **消息路由层集成**：AutoGen Agent 的 `send()`/`receive()` 改为通过 AgentMesh 路由，而非直接进程内调用
- **HTTP 传输**：所有消息通过 HTTP REST API 发送到 AgentMesh A2A Server
- **零依赖降级**：当 pyautogen 包未安装时，使用 `_ConversableAgentProxy` 代理
- **跨框架桥接**：支持 AutoGen 与 CrewAI 或其他自定义 Agent 的通信

## 核心类型

### MessageType

AutoGen 会话中使用的消息类型枚举。

| 成员 | 值 | 说明 |
|------|-----|------|
| `TEXT` | `"text"` | 文本消息 |
| `FUNCTION_CALL` | `"function_call"` | 函数调用 |
| `FUNCTION_RESULT` | `"function_result"` | 函数结果 |
| `CODE` | `"code"` | 代码消息 |
| `ERROR` | `"error"` | 错误消息 |
| `CUSTOM` | `"custom"` | 自定义 |

### ConversationPhase

会话阶段枚举。

| 阶段 | 说明 |
|------|------|
| `INITIATION` | 初始化中 |
| `ACTIVE` | 活跃对话 |
| `WAITING_RESPONSE` | 等待回复 |
| `COMPLETED` | 已完成 |
| `FAILED` | 失败 |
| `TERMINATED` | 终止 |

### A2AAgentDef

AutoGen Agent 定义。

```python
from agentmesh.a2a.integration.autogen_adapter import A2AAgentDef

agent_def = A2AAgentDef(
    name="researcher",
    system_message="You are a helpful AI researcher.",
    description="Researches AI topics",
    max_consecutive_auto_reply=10,
    human_input_mode="NEVER",
)
```

### AutoGenAgentConfig

完整 AutoGen Agent 配置。

```python
from agentmesh.a2a.integration.autogen_adapter import (
    AutoGenAgentConfig, A2AAgentDef,
)

config = AutoGenAgentConfig(
    agent_def=A2AAgentDef(
        name="researcher",
        system_message="You are a researcher.",
    ),
    llm_config={
        "model": "gpt-4",
        "api_key": "sk-...",
    },
    agentmesh_routing=True,
)
```

### GroupChatConfig

群聊配置。

```python
from agentmesh.a2a.integration.autogen_adapter import GroupChatConfig

config = GroupChatConfig(
    name="research-group",
    agent_ids=["researcher", "writer", "reviewer"],
    max_round=50,
    admin_name="admin",
    speaker_selection_method="auto",
)
```

### MessageSendResult / MessageReceiveResult

消息发送和接收的结果封装。

```python
# 发送结果
result = adapter.send_message(
    sender_id="agent_a",
    recipient_id="agent_b",
    content={"text": "Hello!"},
)
print(f"Msg {result.message_id} in conv {result.conversation_id}: {result.status}")

# 接收结果
msg = adapter.receive_message(agent_id="agent_b")
if msg:
    print(f"From: {msg.sender_agent}, Type: {msg.message_type}")
```

---

## AutoGenAdapter

AutoGen 适配器的具体实现，使用 HTTP 传输。

### 生命周期

```python
from agentmesh.a2a.integration.autogen_adapter import AutoGenAdapter

adapter = AutoGenAdapter()

# 连接服务器
adapter.connect("http://localhost:8080", timeout_seconds=30.0)

# 检查
print(adapter.is_connected)  # True

# 断开
adapter.disconnect()
```

### Agent 创建与管理

```python
from agentmesh.a2a.integration.autogen_adapter import (
    AutoGenAdapter, AutoGenAgentConfig, A2AAgentDef,
)

adapter = AutoGenAdapter()
adapter.connect("http://localhost:8080")

# 创建 Agent（自动注册到服务器）
agent = adapter.create_agent(
    AutoGenAgentConfig(
        agent_def=A2AAgentDef(
            name="researcher",
            system_message="You are a researcher.",
        ),
        llm_config={"model": "gpt-4"},
    )
)

# 手动注册
adapter.register_agent("custom_agent", agent)

# 注销
adapter.unregister_agent("custom_agent")
```

### 消息操作

```python
# 发送消息
result = adapter.send_message(
    sender_id="agent_a",
    recipient_id="agent_b",
    content={"text": "Analyze the data"},
    message_type=MessageType.TEXT,
    conversation_id="conv_001",
    metadata={"priority": "high"},
)

# 阻塞接收
msg = adapter.receive_message(
    agent_id="agent_b",
    timeout_seconds=30.0,
)

# 非阻塞轮询
messages = adapter.poll_messages(
    agent_id="agent_b",
    max_count=10,
    conversation_id="conv_001",
)
```

### 群聊管理

```python
from agentmesh.a2a.integration.autogen_adapter import GroupChatConfig

# 创建群聊
group_chat = adapter.create_group_chat(
    GroupChatConfig(
        name="research-team",
        agent_ids=["researcher", "writer", "reviewer"],
        max_round=30,
    )
)

# 发起对话
conv_id = adapter.start_conversation(
    group_chat_id="research-team",
    initiator_id="researcher",
    message="Let's discuss the latest AI papers.",
)

# 查询对话状态
from agentmesh.a2a.integration.autogen_adapter import ConversationPhase
phase = adapter.get_conversation_status(conv_id)
print(f"Conversation phase: {phase}")

# 获取对话历史
history = adapter.get_conversation_history(
    conversation_id=conv_id,
    max_messages=50,
)
for msg in history:
    print(f"[{msg.sender_agent}] {msg.content}")
```

### 跨框架桥接

```python
# AutoGen -> CrewAI 桥接
adapter.bridge_to_crewai(
    autogen_agent_id="autogen_agent_a",
    crewai_agent_id="crewai_agent_b",
)

# AutoGen -> 自定义 Agent 桥接
adapter.bridge_to_custom(
    autogen_agent_id="autogen_agent_a",
    custom_agent_id="custom_agent_c",
)
```

### 健康检查

```python
health = adapter.health_check()
print(f"Status: {health['status']}")
print(f"Latency: {health['latency_ms']}ms")
print(f"Active conversations: {health['active_conversations']}")
```

---

## 完整示例

```python
from agentmesh.a2a.integration.autogen_adapter import (
    AutoGenAdapter, AutoGenAgentConfig, A2AAgentDef,
)

# 1. 连接
adapter = AutoGenAdapter()
adapter.connect("http://localhost:8080")

# 2. 创建 Agent
researcher = adapter.create_agent(
    AutoGenAgentConfig(
        agent_def=A2AAgentDef(
            name="researcher",
            system_message="You research AI safety.",
        ),
    )
)

writer = adapter.create_agent(
    AutoGenAgentConfig(
        agent_def=A2AAgentDef(
            name="writer",
            system_message="You write clear reports.",
        ),
    )
)

# 3. 发送消息
result = adapter.send_message(
    sender_id="researcher",
    recipient_id="writer",
    content={"text": "Summarize the findings on AI alignment."},
)

# 4. 接收回复
reply = adapter.receive_message(agent_id="researcher", timeout_seconds=15.0)
if reply:
    print(f"来自 {reply.sender_agent}: {reply.content}")

# 5. 清理
adapter.unregister_agent("researcher")
adapter.unregister_agent("writer")
adapter.disconnect()
```

---

## Agent 代理 (Proxy)

当 pyautogen 包未安装时，适配器使用 `_ConversableAgentProxy` 作为降级方案。

代理实现了 AutoGen `ConversableAgent` 的核心接口：

- `send(message, recipient, request_reply, silent)` — 通过 AgentMesh 发送消息
- `receive(message, sender, request_reply, silent)` — 接收消息（存入收件箱）
- `generate_reply(messages, sender, exclude)` — 生成回复（可注入自定义回复函数）

```python
# 设置自定义回复函数
proxy = adapter.create_agent(
    AutoGenAgentConfig(
        agent_def=A2AAgentDef(name="proxy_agent"),
    )
)

# 注入自定义回复逻辑
if hasattr(proxy, '_generate_reply_fn'):
    def my_reply(messages, sender, exclude):
        return "Custom response based on input"
    proxy._generate_reply_fn = my_reply
```

---

## 另见

- [CrewAI Adapter](crewai.md) — CrewAI 集成适配器
- [Provider API](provider.md) — 底层 Provider 抽象
- [A2A Test Server 指南](../a2a-test-server.md) — 搭建测试环境
