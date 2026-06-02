# 两Agent研究协作

A检索信息 → B整合报告，完整演示保真度追踪和贡献度分配。

---

## 场景

两个Agent协作完成一份AI Agent安全研究的调研：

- **scout-alpha**: 研究检索Agent，负责信息收集
- **forge-beta**: 整合Agent，负责报告生成

## 代码

```python
from agentmesh_sdk import CollaborationFlow

# 创建协作流
flow = CollaborationFlow("AI Agent安全调研", use_signing=False)

# 注册Agent
flow.register_agent("scout-alpha")
flow.register_agent("forge-beta")

# Step 1: scout-alpha 检索信息 → forge-beta
flow.step_retrieval(
    from_agent="scout-alpha",
    to_agent="forge-beta",
    summary="检索到5条AI Agent安全相关研究，涵盖2024-2025年主流方向",
    data={
        "sources": 5,
        "coverage": "2024-2025",
        "topics": ["prompt injection", "sandbox escape", "data leakage"],
    },
    confidence=0.85,
    fidelity=0.9,
)

# Step 2: forge-beta 整合报告 → coordinator
flow.step_integration(
    from_agent="forge-beta",
    to_agent="coordinator",
    summary="整合5条信息源，输出AI Agent安全研究方向综述",
    data={
        "key_findings": 4,
        "gaps": 2,
        "recommendations": 3,
    },
    confidence=0.78,
    fidelity=0.65,
)

# 获取完整报告
report = flow.full_report()

print("=== AgentMesh 研究协作报告 ===")
print(f"\n冲突率: {report['validation']['conflict_rate']}%")
print(f"累积保真度: {flow.fidelity_tracker.cumulative_fidelity:.3f}")
print(f"保真度警告: {report['fidelity']['warning']}")
print(f"\n贡献度分配:")
for agent, share in report['allocation']['shares'].items():
    print(f"  - {agent}: {share:.4f}")

print(f"\n消息数: {len(report['messages'])}")
for msg in report['messages']:
    print(f"  [{msg['message_type']}] {msg['sender']} -> {msg['recipient']}")
```

## 输出

```
=== AgentMesh 研究协作报告 ===

冲突率: 0.0%
累积保真度: 0.585
保真度警告: False

贡献度分配:
  - scout-alpha: 0.5095
  - forge-beta: 0.4905

消息数: 2
  [TaskRequest] scout-alpha -> forge-beta
  [TaskResult] forge-beta -> coordinator
```

## 关键观察

**保真度衰减**：scout-alpha 传递了 0.9 保真度的信息，forge-beta 处理后降至 0.65，累积保真度仅 0.585。超过 40% 的信息在传递中丢失或变形——这是肉眼看不见的，AgentMesh 把它量化出来了。

**贡献度分配**：scout-alpha 贡献略高 (0.5095 vs 0.4905)，因为它在检索阶段提供了更多原始信息，而 forge-beta 的整合虽然价值高但信息损失稍大。
