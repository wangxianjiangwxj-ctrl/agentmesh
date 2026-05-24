# AgentMesh

> 让Agent协作不再丢信息、贡献可量化

---

## 核心数据

| 指标 | 值 |
|------|-----|
| 实验轮次 | 9轮 |
| 测试用例 | 53个全部通过 |
| 问题类型 | 4类 |
| 应对机制 | 4种 |

---

## 定位

A2A让Agent能说话，AgentMesh让Agent协作**不再丢信息、贡献可量化**。

AgentMesh 是一个跨主体 Agent 协作协议与工具集。它在 A2A 通信层之上，提供保真度追踪、贡献度量化和消息 Schema 合规能力。没有 AgentMesh，Agent 之间的信息传递衰减是不可见的；有了 AgentMesh，每一步的衰减都清晰可追踪。

---

## 快速安装

```bash
pip install git+https://github.com/wangxianjiangwxj-ctrl/agentmesh.git
```

## 5分钟上手

```python
from agentmesh_sdk import CollaborationFlow

flow = CollaborationFlow("AI Agent安全调研", use_signing=False)
flow.register_agent("scout-alpha")
flow.register_agent("forge-beta")

flow.step_retrieval("scout-alpha", "forge-beta",
    summary="检索到5条AI Agent安全相关研究",
    data={"sources": 5}, confidence=0.85, fidelity=0.9)

flow.step_integration("forge-beta", "coordinator",
    summary="5条信息源整合综述",
    data={"key_findings": 4}, confidence=0.78, fidelity=0.65)

report = flow.full_report()
print(f"累积保真度: {flow.fidelity_tracker.cumulative_fidelity:.3f}")
print(f"贡献度: {report['allocation']['shares']}")
```

> [5分钟快速上手](quickstart.md) | [架构文档](architecture.md) | [完整示例](examples/)

---

## 核心能力

| 能力 | 说明 |
|------|------|
| L1 Schema | 5个必填字段，强制Agent说该说的话 |
| 保真度追踪 | 自动计算累积衰减，低于阈值触发警告 |
| 贡献度分配 | 基于Shapley值近似，量化每个Agent贡献 |
| A2A适配 | 与A2A协议双向互操作 |
| CLI工具 | init/validate/convert/fidelity/run |

## 实验验证

9轮实验逐步验证了AgentMesh的效果：

- **信息损失存在**：exp-001/002 证实，2步传递后保真度仅0.585
- **Schema有效**：exp-003/005 证实，冲突率从100%降到0%
- **审查Agent有效**：exp-008 证实，推理错误检测率100%
- **恢复机制有效**：exp-009 证实，4步比3步更鲁棒

> 查看[完整路线图](roadmap.md)了解每个阶段的详细进展
