# Agent 编排 (Agent Orchestration)

> 定义、配置和编排多 Agent 协作工作流

---

## Agent 定义

在 AgentMesh 中，Agent 可以从多个角度理解：

### 1. 从代码角度

Agent 是一个参与协作流程的命名实体，通过 `CollaborationFlow` 注册后参与消息传递：

```python
from agentmesh import CollaborationFlow

flow = CollaborationFlow("AI Agent安全调研", use_signing=False)

# 注册 Agent（只需提供唯一名称）
flow.register_agent("scout-alpha")
flow.register_agent("forge-beta")

# Agent 通过步骤函数参与协作
flow.step_retrieval("scout-alpha", "forge-beta", ...)
flow.step_integration("forge-beta", "coordinator", ...)
```

每个 Agent 在 AgentMesh 内部存储为一条关联记录，包含名称、参与步骤、消息历史和贡献度等元数据。

### 2. 从 CLI 角度

通过 `agentmesh init` 生成的配置文件定义 Agent：

```yaml
# agents.yaml
agents:
  - name: scout-alpha
    role: 搜索研究员
    skills: [web-search, data-collection]
    llm: gpt-4o
  - name: forge-beta
    role: 分析师
    skills: [data-analysis, report-generation]
    llm: gpt-4o

flows:
  - name: 研究协作
    agents: [scout-alpha, forge-beta]
    steps:
      - type: retrieval
        from: scout-alpha
        to: forge-beta
```

### 3. 从 A2A 协议角度

拥有注册 Agent Card 的端点，可通过 HTTP 注册和发现：

```python
from agentmesh.a2a_server import HttpProvider

client = HttpProvider("http://localhost:8080")

# 注册 Agent
client.register_agent("agent-alpha", skills=["web-search", "analysis"])

# Agent Card 结构
card = {
    "name": "agent-alpha",
    "skills": ["web-search", "analysis"],
    "endpoints": {"http": "http://agent-alpha-host:8080/a2a"},
}
```

---

## Multi-Agent 编排模式

### 模式一：研究协作模式（Research Pipeline）

最基础的 Agent 协作模式：一个 Agent 负责收集信息，另一个负责整合分析。

**适用场景**：信息检索 + 报告撰写、数据采集 + 分析。

```
┌─────────────┐    检索结果     ┌─────────────┐    最终报告     ┌──────────────┐
│ scout-alpha │ ──────────────> │ forge-beta  │ ──────────────> │ coordinator  │
│ (搜索研究员) │                │ (分析师)     │                │ (协调者)     │
└─────────────┘                └─────────────┘                └──────────────┘
     │                              │
     │ fidelity=0.90                │ fidelity=0.65
     │ confidence=0.85              │ confidence=0.78
     └─ 找到5条信息源 ───────────────┘─ 整合为4个关键发现
```

```python
from agentmesh import CollaborationFlow

flow = CollaborationFlow("研究协作", use_signing=False)
flow.register_agent("scout-alpha")
flow.register_agent("forge-beta")

# Step 1: 搜索研究员收集信息
flow.step_retrieval(
    "scout-alpha", "forge-beta",
    summary="检索到5条AI Agent安全相关研究",
    data={"sources": 5, "coverage": "2024-2025"},
    confidence=0.85,
    fidelity=0.90,
)

# Step 2: 分析师整合报告
flow.step_integration(
    "forge-beta", "coordinator",
    summary="5条信息源整合：AI Agent安全研究方向综述",
    data={"key_findings": 4, "gaps": 2},
    confidence=0.78,
    fidelity=0.65,
)

report = flow.full_report()
print(f"累积保真度: {flow.fidelity_tracker.cumulative_fidelity:.3f}")
# 输出: 累积保真度: 0.585 (0.90 * 0.65)
```

### 模式二：代码审查模式（Code Review）

多个审查 Agent 并行工作，最后由综合 Agent 汇总意见。

**适用场景**：代码审查、文档审核、多角度分析。

```
                  ┌─────────────────┐
                  │  security-agent  │── 安全审查报告
                  │ (安全审查)      │
                  └─────────────────┘
                         │
┌─────────────┐          │          ┌──────────────────┐
│ dev-agent   │── 提交 ──┼──────────> review-coordinator│── 综合最终报告
│ (开发者)    │  代码    │          │ (审查协调者)    │
└─────────────┘          │          └──────────────────┘
                         │
                  ┌─────────────────┐
                  │  perf-agent     │── 性能审查报告
                  │ (性能审查)      │
                  └─────────────────┘
```

```python
from agentmesh import CollaborationFlow

flow = CollaborationFlow("代码审查", use_signing=False)
flow.register_agent("dev-agent")
flow.register_agent("security-agent")
flow.register_agent("perf-agent")

# Step 1: 开发者提交代码
flow.step_retrieval(
    "dev-agent", "security-agent",
    summary="提交PR #42：用户认证模块重构",
    data={"files": 5, "lines_changed": 320},
    confidence=0.95,
    fidelity=0.98,
)

# Step 2: 安全审查
flow.step_quality_review(
    "security-agent", "review-coordinator",
    summary="安全审查通过，建议增加输入验证",
    data={"issues": 1, "severity": "low", "recommendations": 2},
    confidence=0.80,
    fidelity=0.70,
)

# Step 3: 性能审查
flow.step_quality_review(
    "perf-agent", "review-coordinator",
    summary="性能审查通过，无显著性能退化",
    data={"issues": 0, "response_time": "baseline"},
    confidence=0.85,
    fidelity=0.75,
)
```

### 模式三：跨 A2A 协作模式（Cross-A2A）

Agent 分布在不同进程中，通过 A2A Server 代理通信。

**适用场景**：微服务架构、跨团队协作、异构系统集成。

```
┌──────────────────┐        ┌───────────────────┐
│  Process A       │        │  Process B         │
│                  │        │                     │
│  agent-alpha     │        │  agent-beta        │
│       │          │        │       │            │
│       ▼          │        │       ▼            │
│  A2A Server :8080│──HTTP──│ A2A Server :8081  │
│  (HttpProvider)  │        │  (HttpProvider)    │
└──────────────────┘        └───────────────────┘
         │                         │
         └───────────┬─────────────┘
                     │
            ┌────────▼────────┐
            │  AgentMesh CLI  │
            │  connect / run  │
            └─────────────────┘
```

### 模式四：A2A 桥接模式（A2A Bridge）

本地 Agent 通过 bridge 连接到远程 A2A 生态。

**适用场景**：本地 Agent 调用远程服务、混合云部署。

```
┌──────────────────────┐         ┌──────────────────────┐
│  本地环境             │         │  远程环境              │
│                      │         │                        │
│  local-agent         │  bridge │  remote-agent-1       │
│  (MemoryProvider)    │────────>│  remote-agent-2       │
│                      │  A2A    │  remote-agent-3       │
│  A2AFacade           │  Tunnel │  A2A Server           │
└──────────────────────┘         └──────────────────────┘
```

---

## 与 CrewAI 集成

AgentMesh 提供 CrewAI 适配器，使 CrewAI Agent 可以通过 A2A 协议与远程 Agent 通信。

### 基本集成

```python
from agentmesh.a2a.integration import CrewAIAdapter, CrewAIAgentConfig

# 创建适配器并连接 A2A Server
adapter = CrewAIAdapter()
adapter.connect("http://localhost:8080")

# 创建 CrewAI Agent（自动装配 A2A 工具）
agent = adapter.create_agent(CrewAIAgentConfig(
    role="Researcher",
    goal="收集和整理AI安全研究资料",
    backstory="你是一个经验丰富的AI安全研究员",
))

# Agent 可以发送卡片到其他 Agent
adapter.send_card(
    sender_id="researcher",
    recipient_id="analyst",
    payload={"text": "找到5篇关于LLM越狱攻击的论文"},
    card_type="text",
)

# 接收其他 Agent 的回复
card = adapter.receive_card(agent_id="researcher")
if card:
    print(f"收到: {card.payload}")
```

### A2A Tool

CrewAI Agent 内部使用 `A2ATool` 作为工具来通信：

```python
from agentmesh.a2a.integration import A2AToolDef, CardType

# 定义工具
tool_def = A2AToolDef(
    name="agentmesh_send",
    description="通过 AgentMesh 向其他 Agent 发送卡片并等待回复",
    card_type=CardType.TEXT,
    timeout_seconds=30.0,
)

# 创建工具（返回 CrewAI BaseTool 兼容对象）
tool = adapter.create_a2a_tool(tool_def)

# 工具可被 CrewAI Agent 直接调用
result = tool(recipient_id="analyst", message="分析结果如何？")
```

---

## 与 AutoGen 集成

AgentMesh 的 AutoGen 适配器使 AutoGen 的 ConversableAgent 可以通过 A2A 路由消息。

### 基本集成

```python
from agentmesh.a2a.integration import (
    AutoGenAdapter,
    AutoGenAgentConfig,
    A2AAgentDef,
    MessageType,
)

# 创建适配器并连接
adapter = AutoGenAdapter()
adapter.connect("http://localhost:8080")

# 创建 AutoGen Agent（消息通过 A2A 路由）
agent = adapter.create_agent(AutoGenAgentConfig(
    agent_def=A2AAgentDef(
        name="autogen-researcher",
        system_message="你是一个AI研究员，负责信息收集",
        max_consecutive_auto_reply=10,
    ),
    llm_config={"model": "gpt-4", "api_key": "...", "temperature": 0.7},
))

# 发送消息
adapter.send_message(
    sender_id="autogen-researcher",
    recipient_id="analyst",
    content={"text": "请分析最新的AI安全趋势"},
    message_type=MessageType.TEXT,
)

# 接收消息
msg = adapter.receive_message(agent_id="autogen-researcher")
```

### GroupChat 集成

```python
from agentmesh.a2a.integration import GroupChatConfig

# 创建跨框架的 GroupChat
chat = adapter.create_group_chat(GroupChatConfig(
    name="cross-framework-discussion",
    agent_ids=["autogen-researcher", "autogen-analyst", "crewai-expert"],
    max_round=50,
    speaker_selection_method="auto",
))

# 启动对话
conversation_id = adapter.start_conversation(
    group_chat_id="cross-framework-discussion",
    initiator_id="autogen-researcher",
    message="今天讨论主题：AI Agent 安全最佳实践",
)

# 查询对话状态
phase = adapter.get_conversation_status(conversation_id)
print(f"对话阶段: {phase}")

# 获取对话历史
history = adapter.get_conversation_history(
    conversation_id=conversation_id,
    max_messages=50,
)
```

### 跨框架桥接

```python
# AutoGen → CrewAI 桥接
adapter.bridge_to_crewai(
    autogen_agent_id="autogen-researcher",
    crewai_agent_id="crewai-expert",
)

# AutoGen → 自定义 Agent 桥接
adapter.bridge_to_custom(
    autogen_agent_id="autogen-researcher",
    custom_agent_id="legacy-agent",
)
```

---

## 框架集成对比

| 框架 | 集成方式 | 核心概念 | 通信单元 | 适用场景 |
|------|---------|----------|----------|----------|
| **CrewAI** | A2ATool (BaseTool) | Agent, Tool, Task, Crew | Card (卡片) | 结构化多 Agent 工作流 |
| **AutoGen** | A2A 消息路由 | ConversableAgent, GroupChat | Message (消息) | 灵活的多 Agent 对话 |

**集成原则**：

- Provider Layer Layer — 包装为框架的 Tool/Plugin，零修改框架源码
- HTTP 传输 — 所有跨框架通信通过 A2A Server 中转
- 框架无关 — 同一 Server 可以同时处理 CrewAI 和 AutoGen 的消息

---

## Agent 健康管理

```python
# 健康检查
health = adapter.health_check()
print(f"状态: {health['status']}")
print(f"Server: {health['server_url']}")
print(f"延迟: {health['latency_ms']}ms")
print(f"注册Agent数: {health['registered_agents']}")
```

---

## 最佳实践

### 1. Agent 命名规范

- 使用小写字母和连字符：`data-collector`, `security-reviewer`
- 名称应反映角色：`scout-alpha` > `agent-1`
- 保持全局唯一

### 2. 步骤顺序

- 检索 → 质量审查 → 整合 → 反馈循环
- 每个步骤记录 fidelity 和 confidence
- 关键步骤后做 fidelity 检查

### 3. 通信可靠性

- 关键消息设置超时（默认 30s）
- 使用 SSE 流式订阅长任务
- 配置合适的重试策略

### 4. 性能考虑

- 本地开发使用 MemoryProvider
- 跨进程使用 HttpProvider，配置超时参数
- 大规模场景考虑消息队列集成

---

## 相关文档

- [Provider 系统](providers.md) — 通信抽象层
- [A2A 协议](a2a-protocol.md) — 消息格式和状态机
- [运行时](runtime.md) — Server/Client 生命周期
- [示例 - 两Agent研究协作](../examples/01-two-agent-research.md)
- [示例 - 三Agent代码审查](../examples/02-three-agent-review.md)
- [示例 - 跨A2A协作](../examples/03-cross-a2a-collaboration.md)
