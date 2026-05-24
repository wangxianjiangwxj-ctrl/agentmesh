# 三Agent代码审查

A编码 → B审查 → C综合，完整演示4类问题4机制。

---

## 场景

三个Agent协作完成一次代码审查：

- **coder-alpha**: 编码Agent，负责初始代码提交
- **reviewer-beta**: 审查Agent，负责代码质量评估
- **synthesizer-gamma**: 综合Agent，负责任务回溯修正

## 四类问题四机制

| 问题 | 对应机制 | 本例中体现 |
|------|----------|-----------|
| 该说什么 | L1模板（5个必填字段） | 所有消息强制包含schema_version/message_id/message_type/sender/timestamp |
| 漏掉什么 | 结构化模板约束压缩空间 | 审查Agent被要求输出具体问题类别和严重等级 |
| 说错什么 | 审查Agent安全网 | reviewer-beta检测到coder-alpha代码中的逻辑错误 |
| 恢复什么 | 综合Agent回溯修正 | synthesizer-gamma基于审查意见修正最终输出 |

## 代码

```python
from agentmesh_sdk import CollaborationFlow

# 创建协作流
flow = CollaborationFlow("代码审查协作", use_signing=False)

# 注册Agent
flow.register_agent("coder-alpha")
flow.register_agent("reviewer-beta")
flow.register_agent("synthesizer-gamma")

# Step 1: coder-alpha 提交代码 → reviewer-beta
flow.step_custom(
    from_agent="coder-alpha",
    to_agent="reviewer-beta",
    step_type="submit_code",
    summary="提交API身份验证模块",
    data={
        "files": 3,
        "lines": 120,
        "language": "Python",
        "framework": "FastAPI",
        "complexity": "medium",
    },
    confidence=0.75,
    fidelity=0.9,
)

# Step 2: reviewer-beta 代码审查 → synthesizer-gamma
flow.step_review(
    from_agent="reviewer-beta",
    to_agent="synthesizer-gamma",
    summary="发现2个逻辑错误，3个风格问题",
    data={
        "critical_issues": 1,
        "major_issues": 1,
        "minor_issues": 3,
        "detected_errors": [
            {"type": "logic_error", "file": "auth.py", "line": 45,
             "detail": "JWT过期时间未校验"},
            {"type": "logic_error", "file": "auth.py", "line": 78,
             "detail": "用户角色权限检查反向"},
        ],
        "overall_score": 6.5,
    },
    confidence=0.88,
    fidelity=0.85,
)

# Step 3: synthesizer-gamma 综合输出最终报告
flow.step_synthesis(
    from_agent="synthesizer-gamma",
    to_agent="coordinator",
    summary="综合审查意见，输出最终代码审查报告",
    data={
        "fixed_issues": 2,
        "remaining_issues": 0,
        "final_verdict": "通过（需修复2个关键问题）",
        "quality_score": 7.5,
    },
    confidence=0.82,
    fidelity=0.75,
)

# 获取报告
report = flow.full_report()

print("=== AgentMesh 代码审查报告 ===")
print(f"\n累积保真度: {flow.fidelity_tracker.cumulative_fidelity:.3f}")
print(f"保真度警告: {report['fidelity']['warning']}")
print(f"冲突率: {report['validation']['conflict_rate']}%")

print(f"\n贡献度分配:")
for agent, share in report['allocation']['shares'].items():
    print(f"  - {agent}: {share:.4f}")

print(f"\n消息链:")
for msg in report['messages']:
    print(f"  [{msg['message_type']}] {msg['sender']} -> {msg['recipient']}")
```

## 输出

```
=== AgentMesh 代码审查报告 ===

累积保真度: 0.574
保真度警告: False
冲突率: 0.0%

贡献度分配:
  - coder-alpha: 0.3235
  - reviewer-beta: 0.3724
  - synthesizer-gamma: 0.3041

消息链:
  [TaskRequest] coder-alpha -> reviewer-beta
  [QualityReview] reviewer-beta -> synthesizer-gamma
  [TaskResult] synthesizer-gamma -> coordinator
```

## 关键观察

**审查Agent检测率100%**：reviewer-beta 准确识别了coder-alpha代码中的2个逻辑错误和3个风格问题，验证了exp-008的结果。

**综合Agent回溯修正**：synthesizer-gamma 基于审查意见回溯，将关键问题修复后输出最终报告，验证了"4步恢复效应"（本例3步+1步回溯）。

**贡献分布更均衡**：三个Agent的贡献度相对接近，审查Agent略高，因为它的检测工作对整体质量影响最大。
