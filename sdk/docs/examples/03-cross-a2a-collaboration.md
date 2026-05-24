# 跨A2A协作

AgentMesh Agent ↔ A2A Server 双向通信演示。

---

## 场景

一个AgentMesh Agent（research-scout）与一个标准A2A Server协作完成跨平台研究任务。

流程：

1. AgentMesh Agent 发送研究请求（正向转换）
2. A2A Server 返回研究结果（反向转换）
3. AgentMesh 追踪保真度和贡献度

## 代码

```python
from agentmesh_sdk import CollaborationFlow
from agentmesh_sdk.adapters import A2AAdapter, AgentCardBuilder

# ---- 1. AgentMesh Agent准备 ----

flow = CollaborationFlow("跨A2A协作研究", use_signing=False)
flow.register_agent("research-scout")

adapter = A2AAdapter()

# 构造AgentMesh消息
agentmesh_request = {
    "schema_version": "v2.1",
    "message_id": "cross-001",
    "message_type": "TaskRequest",
    "sender": "research-scout",
    "timestamp": "2026-05-22T10:00:00Z",
    "recipient": "a2a-server-01",
    "confidence": 0.9,
    "fidelity": 1.0,
    "payload": {
        "task": "research",
        "query": "AI Agent安全2025趋势",
        "sources": ["arxiv", "acm", "ieee"],
    },
}

# ---- 2. 正向转换：AgentMesh → A2A ----

a2a_task = adapter.to_a2a(agentmesh_request)
print(f"A2A Task ID: {a2a_task.id}")
print(f"A2A Status: {a2a_task.status}")
print(f"metadata: {a2a_task.messages[0].metadata}")

# ---- 3. 模拟A2A Server响应 ----

a2a_response = {
    "id": "cross-001",
    "status": "completed",
    "messages": [
        {
            "role": "agent",
            "parts": [{"text": "2025年AI Agent安全三大趋势：1. 供应链攻击..."}],
            "metadata": {
                "agentmesh_sender": "a2a-server-01",
                "agentmesh_fidelity": 0.82,
                "agentmesh_confidence": 0.85,
                "agentmesh_schema_version": "v2.1",
            },
        }
    ],
    "artifacts": [
        {
            "id": "art-001",
            "name": "trends-2025.json",
            "parts": [{"text": "...", "mimeType": "application/json"}],
        }
    ],
}

# ---- 4. 反向转换：A2A → AgentMesh ----

agentmesh_result = adapter.to_agentmesh(a2a_response)
print(f"\n恢复的AgentMesh消息:")
print(f"  类型: {agentmesh_result['message_type']}")
print(f"  发送者: {agentmesh_result['sender']}")
print(f"  保真度: {agentmesh_result.get('fidelity')}")
print(f"  置信度: {agentmesh_result.get('confidence')}")

# ---- 5. AgentMesh追踪 ----

# 通过CollaborationFlow继续追踪
flow.step_retrieval(
    from_agent="research-scout",
    to_agent="a2a-server-01",
    summary="A2A Server返回2025年AI Agent安全趋势",
    data={
        "trends_found": 3,
        "sources": ["arxiv", "acm", "ieee"],
        "artifacts": 1,
    },
    confidence=agentmesh_result.get("confidence", 0.85),
    fidelity=agentmesh_result.get("fidelity", 0.82),
)

flow.step_integration(
    from_agent="a2a-server-01",
    to_agent="coordinator",
    summary="整合A2A Server返回的研究结果",
    data={"key_findings": 3, "confidence": 0.82},
    confidence=0.82,
    fidelity=0.75,
)

# ---- 6. 生成Agent Card ----

card_builder = AgentCardBuilder()
agent_card = card_builder.build(
    name="research-scout",
    description="研究检索Agent，支持跨A2A协作",
    url="http://agentmesh.local/agents/scout",
    capabilities=["research", "retrieval", "summarization"],
    skills=["web-search", "a2a-integration"],
    authentication={"schemes": [{"type": "none"}]},
    agentmesh_metadata={
        "fidelity_avg": 0.85,
        "confidence_avg": 0.82,
    },
)

print(f"\nAgent Card: {agent_card.name}")
print(f"  URL: {agent_card.url}")
print(f"  Capabilities: {', '.join(agent_card.capabilities)}")

# ---- 7. 完整报告 ----

report = flow.full_report()
print(f"\n=== 跨A2A协作报告 ===")
print(f"累积保真度: {flow.fidelity_tracker.cumulative_fidelity:.3f}")
print(f"贡献度: {report['allocation']['shares']}")
```

## 输出

```
A2A Task ID: cross-001
A2A Status: TaskStatus.SUBMITTED
metadata: {'agentmesh_sender': 'research-scout',
           'agentmesh_confidence': 0.9,
           'agentmesh_fidelity': 1.0}

恢复的AgentMesh消息:
  类型: TaskResult
  发送者: a2a-server-01
  保真度: 0.82
  置信度: 0.85

Agent Card: research-scout
  URL: http://agentmesh.local/agents/scout
  Capabilities: research, retrieval, summarization

=== 跨A2A协作报告 ===
累积保真度: 0.615
贡献度: {'research-scout': 0.4850, 'a2a-server-01': 0.5150}
```

## 关键观察

**无损互操作**：AgentMesh消息 → A2A Task → AgentMesh消息 的双向转换保持关键字段完整（sender/confidence/fidelity通过metadata `agentmesh_` 前缀保留）。

**跨平台保真度追踪**：即使信息流经标准A2A Server，AgentMesh仍能通过metadata读取到跨平台传递的保真度信息。

**AgentCard可发现**：AgentMesh Agent通过AgentCard暴露给A2A生态，实现双向发现和调用。
