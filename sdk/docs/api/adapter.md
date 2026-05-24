# A2A适配器 API

AgentMesh ↔ A2A 协议双向转换适配器。

---

## A2AAdapter

核心适配器类，实现AgentMesh与A2A协议之间的双向消息转换。

### 正向转换 (AgentMesh → A2A)

将5种AgentMesh消息类型转换为A2A Task/Message格式。

```python
from agentmesh_sdk.adapters import A2AAdapter

adapter = A2AAdapter()

# 构造一条AgentMesh消息
agentmesh_msg = {
    "schema_version": "v2.1",
    "message_id": "msg-001",
    "message_type": "TaskRequest",
    "sender": "agent-a",
    "timestamp": "2026-05-22T10:00:00Z",
    "recipient": "agent-b",
    "confidence": 0.9,
    "fidelity": 1.0,
}

# 正向转换：AgentMesh → A2A
a2a_task = adapter.to_a2a(agentmesh_msg)
print(a2a_task)
# A2ATask(
#     id="msg-001",
#     sessionId="agentmesh-session-...",
#     status=TaskStatus.SUBMITTED,
#     messages=[
#         A2AMessage(
#             role=MessageRole.USER,
#             parts=[MessagePart(text="任务内容...")],
#             metadata={
#                 "agentmesh_sender": "agent-a",
#                 "agentmesh_confidence": 0.9,
#                 "agentmesh_fidelity": 1.0,
#             }
#         )
#     ]
# )
```

### 反向转换 (A2A → AgentMesh)

将A2A Task状态转换回AgentMesh消息。

```python
# 假设收到一个A2A响应
a2a_response = {
    "id": "task-001",
    "status": "completed",
    "messages": [
        {
            "role": "agent",
            "parts": [{"text": "检索结果摘要..."}],
            "metadata": {
                "agentmesh_sender": "agent-b",
                "agentmesh_fidelity": 0.85,
                "agentmesh_confidence": 0.78,
            }
        }
    ],
    "artifacts": [
        {
            "id": "art-001",
            "name": "research-results.json",
            "parts": [{"text": "...", "mimeType": "application/json"}],
        }
    ]
}

# 反向转换
agentmesh_msg = adapter.to_agentmesh(a2a_response)
print(agentmesh_msg)
# {
#     "schema_version": "v2.1",
#     "message_id": "task-001",
#     "message_type": "TaskResult",
#     "sender": "agent-b",
#     "timestamp": "...",
#     "confidence": 0.78,
#     "fidelity": 0.85,
#     "data": {"artifacts": [...], "summary": "检索结果摘要..."},
# }
```

### 类型映射

| AgentMesh消息类型 | A2A Task状态 |
|-------------------|--------------|
| TaskRequest | SUBMITTED |
| TaskResult | COMPLETED |
| QualityReview | INPUT_REQUIRED（带评分元数据） |
| FeedbackLoop | INPUT_REQUIRED（带修订请求元数据） |
| ContributionClaim | COMPLETED（带贡献声明元数据） |

### metadata映射规则

所有AgentMesh特有字段使用 `agentmesh_` 前缀存入A2A metadata：

| AgentMesh字段 | A2A metadata键 |
|---------------|-----------------|
| sender | agentmesh_sender |
| confidence | agentmesh_confidence |
| fidelity | agentmesh_fidelity |
| schema_version | agentmesh_schema_version |

---

## AgentCardBuilder

从AgentMesh Agent生成A2A Agent Card，使AgentMesh Agent能被A2A生态发现和调用。

```python
from agentmesh_sdk.adapters import AgentCardBuilder

builder = AgentCardBuilder()

agent_card = builder.build(
    name="research-scout",
    description="研究检索Agent，负责信息收集",
    url="http://agentmesh.local/agents/scout",
    capabilities=["research", "retrieval", "summarization"],
    skills=["web-search", "document-analysis"],
    authentication={"schemes": [{"type": "none"}]},
    agentmesh_metadata={  # AgentMesh特有扩展
        "fidelity_avg": 0.85,
        "confidence_avg": 0.82,
        "contribution_history": {"tasks": 15, "avg_share": 0.45},
    }
)

print(agent_card)
# AgentCard(
#     name="research-scout",
#     description="研究检索Agent，负责信息收集",
#     url="http://agentmesh.local/agents/scout",
#     capabilities=...,
#     skills=["web-search", "document-analysis"],
#     authentication=...,
# )
```

**AgentCard属性**：

| 属性 | 类型 | 说明 |
|------|------|------|
| name | str | Agent名称 |
| description | str | 描述 |
| url | str | 端点URL |
| capabilities | list[str] | 能力列表 |
| skills | list[str] | 技能列表 |
| authentication | dict | 认证方式 |

---

## 数据类

### A2ATask

```python
from agentmesh_sdk.a2a_models import (
    A2ATask, A2AMessage, A2AArtifact,
    AgentCard, TaskStatus, MessageRole,
)

task = A2ATask(
    id="task-001",
    sessionId="session-001",
    status=TaskStatus.SUBMITTED,
    messages=[...],
    artifacts=[...],
)
```

### A2AMessage

```python
msg = A2AMessage(
    role=MessageRole.USER,   # USER / AGENT
    parts=[MessagePart(text="内容")],
    metadata={"key": "value"},
)
```

### A2AArtifact

```python
art = A2AArtifact(
    id="art-001",
    name="results.json",
    parts=[MessagePart(text="...", mimeType="application/json")],
)
```

---

## 完整示例

> 查看[跨A2A协作示例](../examples/03-cross-a2a-collaboration.md)了解完整使用场景
