# AgentMesh: 让Agent协作不再丢信息、贡献可量化

**A2A让Agent能说话，AgentMesh让Agent协作不再丢信息、贡献可量化。**

---

## 你的多Agent系统在丢信息，但你不知道

你用 LangGraph / CrewAI / AutoGen 搭了一个多Agent系统。

scout-alpha（A）检索信息 → forge-beta（B）整合报告 → audit-gamma（C）做审查。

看起来很美。但你想过一个问题吗：

**B整合时，丢掉了A的哪些关键信息？C审查时，有没有曲解A的结论？3步传递下来，原始信息还剩多少？**

答案是：你不知道。

因为现有的多Agent框架只关心"Agent间能说话"，不关心"说对了没、漏了没、错了没"。

直觉告诉我们多步传递会有信息损失。但损失多少？损失在哪里？什么原因导致的？——这些问题没有工具能回答。

为了找到答案，我们设计了一套标准实验流程，用真实Agent协作场景来量化信息衰减。

---

## 实验设置
- Agent数量：2-4个（A→B→C→D协作链）
- 消息类型：5种（TaskRequest / TaskResult / QualityReview / FeedbackLoop / ContributionClaim）
- 评估方式：人工审查每步的摘要、数据、置信度和保真度，对比A→B→C间的信息衰减
- 样本量：9轮独立实验（exp-001至exp-009），每轮含多次消息传递

实验结果显示：Agent协作确实在丢信息。

---

## 核心发现

| 问题 | 角色 | 发生率（无AgentMesh） | 你能发现吗 |
|------|------|-------------------|-----------|
| 格式冲突 — 消息格式不兼容 | A→B | 100%（exp-003/005, N=4） | 能，但每次手动调试 |
| 严重遗漏 — B整合时遗漏A的关键信息 | B（整合） | 对照组3处 vs 模板组0处（N=6） | 不对比原文发现不了 |
| 事实曲解 — C把个别结论夸大为共识 | C（审查） | 自然发生（exp-006） | 需专人审查 |
| 信息衰减 — A→B两站保真度仅0.585 | A→B→C | 每步衰减15-35% | 没有追踪工具就看不见 |

**最扎心的数据**：3步传递后累积保真度仅0.414——超过一半的信息在传递中丢失。

---

## AgentMesh：4类问题4机制

针对四个问题，我们设计了四个对应机制：

| 问题 | 角色 | 机制 | 效果 |
|------|------|------|------|
| 该说什么 — A不知道消息格式 | A | 格式模板（5个必填字段） | 冲突100%→0%，N=4 |
| 漏掉什么 — B遗漏A的关键信息 | B（整合） | 内容模板（结构化约束） | 遗漏3→0，N=6 |
| 说错什么 — C曲解了A的结论 | C（审查） | 审查Agent安全网 | 检测率100%，N=4 |
| 恢复什么 — D修复A→B→C的偏差 | D（综合） | 综合修正（回溯修复） | 4步>3步，N=1 |

### 1. 格式模板 — "该说什么"（A→B）

5个必填字段：schema_version, message_id, message_type, sender, timestamp。保证A发给B的消息格式一致。

在我们的测试中（exp-003, exp-005），无模板时冲突率100%；引入格式模板后，冲突率降至0%。

### 2. 内容模板 — "漏掉什么"（B→C）

结构化模板约束限制B的发挥空间，确保B在整合时不会遗漏A的关键字段（summary, data, confidence, fidelity）。

在我们的测试中（exp-005），对照组B遗漏了3处严重信息；内容模板引导后，实验组0处遗漏。

### 3. 审查Agent安全网 — "说错什么"（C→D）

引入独立审查Agent（C角色），在B→C传递后检查推理错误，防止错误结论传递到D。

在我们的测试中（exp-008, N=4: 以偏概全、因果混淆、遗漏声明、主观优先级注入），审查Agent检测到全部4类错误。

### 4. 综合修正 — "恢复什么"（D输出）

综合Agent（D角色）回溯A→B→C的产出，识别累积的偏差并修复，输出终版结果。

在我们的测试中（exp-009），4步流程（A→B→C→D）比3步（A→B→C）更鲁棒，D步恢复了C未标注的问题。

---

## 5分钟上手

```bash
pip install agentmesh-sdk
```

```python
from agentmesh_sdk import CollaborationFlow

flow = CollaborationFlow("AI Agent安全调研", use_signing=False)
flow.register_agent("scout-alpha")
flow.register_agent("forge-beta")

# A检索 → B传递（含保真度标注）
flow.step_retrieval("scout-alpha", "forge-beta",
    summary="检索到5条AI安全相关研究",
    data={"sources": 5},
    confidence=0.85, fidelity=0.9)

# B整合 → 协调者（含保真度标注）
flow.step_integration("forge-beta", "coordinator",
    summary="整合完成：5条信息源归类为4个方向",
    data={"key_findings": 4, "gaps": 2},
    confidence=0.78, fidelity=0.65)

report = flow.full_report()
print(f"冲突率: {report['validation']['conflict_rate']}%")
print(f"保真度: {flow.fidelity_tracker.cumulative_fidelity:.3f}")
print(f"贡献度: {report['allocation']['shares']}")
```

输出：

```
冲突率: 0.0%
保真度: 0.585
贡献度: {'scout-alpha': 0.5095, 'forge-beta': 0.4905}
```

**Aha Moment**：A→B两步传递后保真度仅0.585——超过40%的信息在传递中丢失。没有AgentMesh，你看不见这个衰减。

---

## 与A2A的关系

A2A让不同框架的Agent能说话。

AgentMesh让协作不再丢信息、贡献可量化。

我们在A2A协议之上构建了保真度追踪层和贡献度分配层，并通过A2A适配器实现了与A2A生态的双向互操作。适配器已通过HTTP JSON-RPC端到端验证——AgentMesh Agent可以给任何A2A兼容Server发送消息，并保留保真度和置信度数据。

---

## 技术博客
- 这篇就是
- GitHub: [github.com/wangxianjiangwxj-ctrl/agentmesh](https://github.com/wangxianjiangwxj-ctrl/agentmesh)
- 文档站: [wangxianjiangwxj-ctrl.github.io/agentmesh](https://wangxianjiangwxj-ctrl.github.io/agentmesh/)
- Web Demo: [wangxianjiangwxj-ctrl.github.io/agentmesh/demo/fidelity-demo.html](https://wangxianjiangwxj-ctrl.github.io/agentmesh/demo/fidelity-demo.html)（保真度可视化）
- 安装: `pip install agentmesh-sdk`（PyPI发布中，或 `pip install git+https://github.com/wangxianjiangwxj-ctrl/agentmesh.git`）

---

**AgentMesh — 让Agent协作不再丢信息、贡献可量化。**
