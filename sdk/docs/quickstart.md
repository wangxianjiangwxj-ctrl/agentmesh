# 快速开始

5分钟上手 AgentMesh。

---

## 安装

```bash
pip install agentmesh-sdk
```

## 最小示例

```python
from agentmesh_sdk import CollaborationFlow

# 1. 创建协作流
flow = CollaborationFlow("AI Agent安全调研", use_signing=False)

# 2. 注册Agent
flow.register_agent("scout-alpha")
flow.register_agent("forge-beta")

# 3. A检索信息
flow.step_retrieval(
    "scout-alpha", "forge-beta",
    summary="检索到5条AI Agent安全相关研究",
    data={"sources": 5, "coverage": "2024-2025"},
    confidence=0.85,
    fidelity=0.9,
)

# 4. B整合报告
flow.step_integration(
    "forge-beta", "coordinator",
    summary="5条信息源整合：AI Agent安全研究方向综述",
    data={"key_findings": 4, "gaps": 2},
    confidence=0.78,
    fidelity=0.65,
)

# 5. 获取报告
report = flow.full_report()
print(f"冲突率: {report['validation']['conflict_rate']}%")
print(f"累积保真度: {flow.fidelity_tracker.cumulative_fidelity:.3f}")
print(f"贡献度: {report['allocation']['shares']}")
```

## 输出

```
冲突率: 0.0%
累积保真度: 0.585
贡献度: {'scout-alpha': 0.5095, 'forge-beta': 0.4905}
```

**Aha Moment**: 2步传递后，累积保真度仅0.585——超过40%的信息在传递中丢失或变形。没有AgentMesh，你看不见这个衰减。

---

## CLI 使用

```bash
# 初始化项目
agentmesh init

# 验证消息
agentmesh validate message.json

# A2A格式转换
agentmesh convert message.json --to a2a

# 保真度追踪
agentmesh fidelity chain.json

# 运行端到端流程
agentmesh run flow.json
```

---

## 下一步

- 查看[架构文档](architecture.md)了解系统设计
- 运行[完整示例](examples/)看场景演示
- 接入[A2A适配器](api/adapter.md)与A2A生态互操作
