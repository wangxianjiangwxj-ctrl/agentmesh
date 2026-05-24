# SDK API

AgentMesh SDK 提供7个核心模块，覆盖消息构造、保真度追踪、贡献度分配、Schema验证等全链路功能。

---

## 模块概览

| 模块 | 功能 |
|------|------|
| 兼容层 | 自然语言到数值字段的自动映射 |
| ID生成 | 全局唯一message_id生成 |
| 签名模块 | ECDSA / Ed25519 可选签名 |
| 验证模块 | L1 Schema合规验证 |
| 消息构造 | 5种消息类型的构建与序列化 |
| 保真度追踪 | 累积衰减计算与阈值告警 |
| 贡献度分配 | 基于Shapley值近似 |

---

## MessageBuilder

构造5种标准消息类型。

```python
from agentmesh_sdk import MessageBuilder

builder = MessageBuilder(sender="agent-a")

# TaskRequest
req = builder.build_task_request(
    recipient="agent-b",
    task_type="research",
    payload={"query": "AI Agent安全问题"},
    confidence=0.9,
)

# TaskResult
result = builder.build_task_result(
    recipient="coordinator",
    summary="检索到5条AI Agent安全研究",
    task_id=req["message_id"],
    data={"sources": 5, "coverage": "2024-2025"},
    fidelity=0.85,
)

# QualityReview
review = builder.build_quality_review(
    recipient="agent-b",
    target_message_id=result["message_id"],
    score=0.78,
    issues=[{"type": "incomplete", "detail": "缺少2026年数据"}],
)

# FeedbackLoop
feedback = builder.build_feedback_loop(
    recipient="agent-b",
    target_message_id=result["message_id"],
    revision_request="补充2026年数据源",
    priority="high",
)

# ContributionClaim
claim = builder.build_contribution_claim(
    recipient="coordinator",
    claim={"type": "retrieval", "value": 0.45, "basis": "检索了5个数据源"},
)
```

**参数说明**：

| 参数 | 类型 | 必填 |
|------|------|------|
| sender | str | 是 |
| recipient | str | 是 |
| summary | str | 推荐 |
| fidelity | float (0-1) | 推荐 |
| confidence | float (0-1) | 可选 |

---

## FidelityTracker

追踪消息传递中的信息保真度。

```python
from agentmesh_sdk import FidelityTracker

tracker = FidelityTracker(
    warn_threshold=0.5,  # 默认警告阈值
    decay_fn="product",   # 累积方式：乘积
)

# 记录每一步的保真度
tracker.record("agent-a", "agent-b", 0.9)
tracker.record("agent-b", "coordinator", 0.65)

print(tracker.cumulative_fidelity)  # 0.585
print(tracker.steps)
# [{"from": "agent-a", "to": "agent-b", "fidelity": 0.9},
#  {"from": "agent-b", "to": "coordinator", "fidelity": 0.65}]
print(tracker.is_below_threshold())  # False (0.585 > 0.5)
```

**核心属性**：

- `cumulative_fidelity` — 累积保真度（各步乘积）
- `steps` — 每一步的保真度记录
- `warn_threshold` — 警告阈值

**核心方法**：

- `record(from_agent, to_agent, fidelity)` — 记录一步
- `is_below_threshold()` — 是否低于警告阈值
- `reset()` — 重置追踪

---

## ContributionAllocator

基于Shapley值近似计算每个Agent的贡献度。

```python
from agentmesh_sdk import ContributionAllocator

allocator = ContributionAllocator(agents=["scout-alpha", "forge-beta"])

# 记录每个Agent的贡献数据
allocator.record("scout-alpha", {
    "messages_sent": 2,
    "tasks_completed": 1,
    "confidence_avg": 0.85,
    "fidelity_avg": 0.9,
})
allocator.record("forge-beta", {
    "messages_sent": 1,
    "tasks_completed": 1,
    "confidence_avg": 0.78,
    "fidelity_avg": 0.65,
})

# 计算贡献度
shares = allocator.allocate()
print(shares)
# {"scout-alpha": 0.5095, "forge-beta": 0.4905}

# 获取完整报告
report = allocator.full_report()
print(report["shares"])
print(report["rationale"])
```

**核心方法**：

- `record(agent, metrics)` — 记录Agent的指标数据
- `allocate()` — 计算贡献度分配
- `full_report()` — 获取完整分配报告（含分配理由）

---

## CollaborationFlow

端到端工作流编排，自动处理消息构造、保真度追踪和贡献度分配。

```python
from agentmesh_sdk import CollaborationFlow

# 初始化
flow = CollaborationFlow("研究协作", use_signing=False)

# 注册Agent
flow.register_agent("scout-alpha")
flow.register_agent("forge-beta")

# 步骤：检索
flow.step_retrieval(
    from_agent="scout-alpha",
    to_agent="forge-beta",
    summary="检索到5条AI Agent安全研究",
    data={"sources": 5, "coverage": "2024-2025"},
    confidence=0.85,
    fidelity=0.9,
)

# 步骤：整合
flow.step_integration(
    from_agent="forge-beta",
    to_agent="coordinator",
    summary="5条信息源整合综述",
    data={"key_findings": 4, "gaps": 2},
    confidence=0.78,
    fidelity=0.65,
)

# 获取完整报告
report = flow.full_report()
```

**full_report() 返回结构**：

```python
{
    "project": "研究协作",
    "messages": [...],          # 所有消息
    "fidelity": {
        "cumulative": 0.585,
        "steps": [...],
        "warning": False,
    },
    "allocation": {
        "shares": {"scout-alpha": 0.5095, "forge-beta": 0.4905},
        "rationale": "...",
    },
    "validation": {
        "conflict_rate": 0.0,
        "issues": [],
    },
}
```

**可用步骤方法**：

| 方法 | 功能 |
|------|------|
| `step_retrieval` | 检索步骤 |
| `step_integration` | 整合步骤 |
| `step_review` | 审查步骤 |
| `step_synthesis` | 综合步骤 |
| `step_custom` | 自定义步骤 |

---

## 验证模块

```python
from agentmesh_sdk import Validation

validator = Validation()

# 验证单条消息
result = validator.validate_message(message)
print(result.is_valid)    # True / False
print(result.issues)      # 问题列表

# 验证消息链
chain_result = validator.validate_chain(messages)
print(chain_result.conflict_rate)  # 冲突率
```

---

## 签名模块

```python
from agentmesh_sdk import Signing

# ECDSA签名
signer = Signing(algorithm="ecdsa")
message_signed = signer.sign(message)

# 验证签名
is_valid = signer.verify(message_signed)
```

---

## 兼容层

自然语言到数值字段的自动映射，处理`_compat_*`前缀字段。

```python
from agentmesh_sdk import CompatibilityLayer

compat = CompatibilityLayer()
converted = compat.resolve(message)  # 自动映射_compat_字段
```

---

## 完整示例

> 参见[示例文档](../examples/)获取完整场景演示
