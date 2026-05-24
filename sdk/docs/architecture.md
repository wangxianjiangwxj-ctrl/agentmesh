# AgentMesh — 架构文档

> 让Agent协作不再丢信息、贡献可量化

---

## 概述

AgentMesh 是一个跨主体 Agent 协作协议与工具集。它在 A2A 通信层之上，提供保真度追踪、贡献度量化和消息 Schema 合规能力。

**核心定位**：A2A让Agent能说话，AgentMesh让Agent协作不再丢信息、贡献可量化。

---

## 系统架构

```
┌─────────────────────────────────────────────────────┐
│                    应用层                             │
│  CollaborationFlow  │   CLI (init/validate/convert  │
│                      │   /fidelity/run)              │
├─────────────────────────────────────────────────────┤
│                    核心层                             │
│  MessageBuilder │ FidelityTracker │ Contribution     │
│  Validation     │ Compatibility    │ Allocator       │
├─────────────────────────────────────────────────────┤
│                    协议层                             │
│  L1 Schema (5必填字段) │ 兼容层 │ 签名模块           │
├─────────────────────────────────────────────────────┤
│                    适配器层                            │
│  A2A Adapter (正向/反向转换) │ Agent Card Builder    │
├─────────────────────────────────────────────────────┤
│                   通信层                               │
│  JSON-RPC 2.0 over HTTP(S) │ SSE Streaming          │
└─────────────────────────────────────────────────────┘
```

### 分层职责

| 层级 | 组件 | 职责 |
|------|------|------|
| 应用层 | CollaborationFlow, CLI | 端到端工作流编排、命令行交互 |
| 核心层 | MessageBuilder, FidelityTracker, Validation | 消息构造、保真度追踪、Schema验证 |
| 协议层 | L1 Schema, 兼容层, 签名 | 消息格式规范、自然语言→数值映射、签名 |
| 适配器层 | A2A Adapter, AgentCardBuilder | 与A2A生态互操作 |
| 通信层 | JSON-RPC 2.0 | A2A协议规定的通信格式 |

---

## 核心模块

### 1. SDK (`sdk/agentmesh_sdk.py`)

一体化 SDK，包含全部核心功能：

- **MessageBuilder** — 5种消息类型构造（TaskRequest/TaskResult/QualityReview/FeedbackLoop/ContributionClaim）
- **FidelityTracker** — 保真度追踪，自动计算累积衰减
- **ContributionAllocator** — 基于Shapley值近似的贡献度分配
- **Validation** — L1 Schema合规验证
- **CollaborationFlow** — 端到端工作流编排，自动记录保真度和贡献度

### 2. A2A适配器 (`adapters/a2a_adapter.py`)

AgentMesh ↔ A2A 双向转换：

- **正向转换** — 5种AgentMesh消息类型 → A2A Task/Message
- **反向转换** — 5种A2A Task状态 → AgentMesh消息
- **AgentCardBuilder** — 从AgentMesh Agent生成A2A Agent Card
- **metadata映射** — confidence/fidelity/sender/schema_version使用agentmesh_前缀存入A2A metadata

### 3. CLI (`cli/`)

命令行工具：

| 命令 | 功能 |
|------|------|
| `agentmesh init` | 初始化项目 |
| `agentmesh validate` | 验证消息Schema |
| `agentmesh convert` | A2A双向格式转换 |
| `agentmesh fidelity` | 独立保真度追踪 |
| `agentmesh run` | 端到端流程执行 |

### 4. 数据模型 (`sdk/a2a_models.py`)

A2A协议 v1.0.0 Python 数据类：

- A2ATask, A2AMessage, A2AArtifact, AgentCard
- TaskStatus, TaskState, MessageRole, MessagePart
- A2ARequest, A2AResponse (JSON-RPC 2.0 envelope)

---

## 消息 Schema (L1)

所有AgentMesh消息必须包含5个必填字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| schema_version | string | 当前 v2.1 |
| message_id | string | 全局唯一 |
| message_type | string | TaskRequest/TaskResult/QualityReview/FeedbackLoop/ContributionClaim |
| sender | string | Agent标识 |
| timestamp | string | ISO 8601 |

可选但推荐：confidence(0-1), fidelity(0-1), recipient, signature, _compat_*

---

## 保真度追踪

累积保真度 = 各步保真度的乘积。

```
cumulative_fidelity = fidelity_1 × fidelity_2 × ... × fidelity_n
```

实验数据表明：2步传递后累积保真度约0.585，3步后约0.414。超过一半的信息在传递中丢失或变形。

默认警告阈值：0.5（累积保真度低于此值时触发警告）。

---

## 四类问题四机制

| 问题 | 机制 | 实验验证 |
|------|------|---------|
| 该说什么 | L1模板（5个必填字段） | 冲突率 100%→0%（exp-003/005） |
| 漏掉什么 | 结构化模板约束压缩空间 | 严重遗漏 3→0（exp-005） |
| 说错什么 | 审查Agent安全网 | 推理错误检测率100%（exp-008） |
| 恢复什么 | 综合Agent回溯修正 | 4步比3步更鲁棒（exp-009） |

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1 | 2026-05-18 | Phase 1-5: 可行性研究+实验验证 |
| v0.2 | 2026-05-20 | Phase 6-7: 协议原型+技能打包+产品验证 |
| v0.3 | 2026-05-22 | Phase 8: A2A适配器+CLI+3个端到端示例 |

---

## 快速开始

```bash
pip install agentmesh-sdk
```

```python
from agentmesh_sdk import CollaborationFlow

flow = CollaborationFlow("我的任务", use_signing=False)
flow.register_agent("agent-a")
flow.register_agent("agent-b")

flow.step_retrieval("agent-a", "agent-b", "检索摘要", {"sources": 5})
flow.step_integration("agent-b", "coordinator", "整合报告", {"key_findings": 3})

report = flow.full_report()
print(f"保真度: {flow.fidelity_tracker.cumulative_fidelity}")
print(f"贡献度: {report['allocation']['shares']}")
```
